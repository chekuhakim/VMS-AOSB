"""Tender rules: eligibility, sealed quotations, publishing, and award approval."""

from __future__ import annotations

from typing import Any

from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction
from django.db.models import QuerySet
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone

from accounts.models import Notification
from accounts.notifications import notify_event, staff_recipients, upsert_notification
from accounts.roles import DIRECTOR, PROCUREMENT
from audit.models import AuditLog
from audit.services import client_ip, write_audit
from envelope1.models import Envelope1Submission
from envelope1.services import latest_submission
from tenders.declaration import DECLARATION_VERSION, declaration_text
from tenders.documents import store_quotation_document
from tenders.models import RFQ, Project, Quotation, TenderAward
from vendors.models import Company


def grade_rank(grade: str) -> int:
    """'G5' → 5; blank or malformed → 0."""
    try:
        return int((grade or "").upper().lstrip("G"))
    except ValueError:
        return 0


def company_prequalified(company: Company) -> bool:
    """Stage 3 gate: registration approved and Envelope 1 approved by the Director."""
    if company.registration_status != Company.RegistrationStatus.APPROVED:
        return False
    submission = latest_submission(company)
    return bool(submission and submission.status == Envelope1Submission.Status.APPROVED)


def requirement_issues(company: Company, project: Project) -> list[str]:
    """Project-specific CIDB requirements the company does not meet."""
    issues: list[str] = []
    if project.min_cidb_grade and grade_rank(company.cidb_grade) < grade_rank(project.min_cidb_grade):
        issues.append(f"Requires CIDB grade {project.min_cidb_grade} or higher")
    return issues


def eligible_companies(project: Project) -> list[Company]:
    candidates = Company.objects.filter(
        registration_status=Company.RegistrationStatus.APPROVED
    ).select_related("owner")
    return [
        c for c in candidates
        if company_prequalified(c) and not requirement_issues(c, project)
    ]


def next_rfq_code(project: Project) -> tuple[str, int]:
    position = project.rfqs.count() + 1
    taken = set(project.rfqs.values_list("code", flat=True))
    while f"RFQ-{position:02d}" in taken:
        position += 1
    return f"RFQ-{position:02d}", position


def _assign_reference(project: Project) -> None:
    if not project.reference:
        year = (project.published_at or timezone.now()).year
        project.reference = f"PRJ-{year}-{project.pk:04d}"


@transaction.atomic
def publish_project(*, project: Project, actor: AbstractBaseUser, request: HttpRequest | None) -> None:
    project = Project.objects.select_for_update().get(pk=project.pk)
    if project.status != Project.Status.DRAFT:
        raise ValueError("Only draft projects can be published.")
    if not project.rfqs.exists():
        raise ValueError("Add at least one RFQ before publishing.")
    if project.closing_at <= timezone.now():
        raise ValueError("Closing date must be in the future. Edit the project first.")

    project.status = Project.Status.OPEN
    project.published_at = timezone.now()
    project.published_by = actor
    _assign_reference(project)
    project.save(update_fields=["status", "published_at", "published_by", "reference", "updated_at"])

    write_audit(
        category=AuditLog.Category.PROJECT,
        action="project_published",
        actor=actor,
        request=request,
        changes={
            "reference": project.reference,
            "closing_at": project.closing_at.isoformat(),
            "rfqs": project.rfqs.count(),
        },
        object_type="Project",
        object_id=project.pk,
    )
    link = reverse("tenders:project_detail", kwargs={"pk": project.pk})
    for company in eligible_companies(project):
        upsert_notification(
            user=company.owner,
            dedupe_key=f"tender-open-{project.pk}-{company.pk}",
            title=f"New project open — {project.title}",
            body=(
                f"{project.reference} is open for quotations until "
                f"{timezone.localtime(project.closing_at):%d %b %Y %H:%M}."
            ),
            level=Notification.Level.INFO,
            link_url=link,
            link_label="View project",
        )


@transaction.atomic
def cancel_project(
    *, project: Project, actor: AbstractBaseUser, reason: str, request: HttpRequest | None
) -> None:
    project = Project.objects.select_for_update().get(pk=project.pk)
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("A cancellation reason is required.")
    if project.status == Project.Status.CANCELLED:
        raise ValueError("Project is already cancelled.")
    if TenderAward.objects.filter(rfq__project=project, status=TenderAward.Status.APPROVED).exists():
        raise ValueError("Cannot cancel a project with an approved award.")

    was_open = project.status == Project.Status.OPEN
    project.status = Project.Status.CANCELLED
    project.cancelled_at = timezone.now()
    project.cancel_reason = reason
    project.save(update_fields=["status", "cancelled_at", "cancel_reason", "updated_at"])
    TenderAward.objects.filter(
        rfq__project=project, status=TenderAward.Status.PENDING_DIRECTOR
    ).update(status=TenderAward.Status.REJECTED, decision_note="Project cancelled", decided_at=timezone.now())

    write_audit(
        category=AuditLog.Category.PROJECT,
        action="project_cancelled",
        actor=actor,
        request=request,
        changes={"reason": reason, "was_open": was_open},
        object_type="Project",
        object_id=project.pk,
    )
    if was_open:
        bidders = Company.objects.filter(
            quotations__rfq__project=project,
            quotations__status=Quotation.Status.SUBMITTED,
        ).distinct().select_related("owner")
        for company in bidders:
            upsert_notification(
                user=company.owner,
                dedupe_key=f"tender-cancelled-{project.pk}-{company.pk}",
                title=f"Project cancelled — {project.title}",
                body=f"{project.reference} was cancelled: {reason}",
                level=Notification.Level.WARNING,
                link_url=reverse("tenders:your_bids"),
                link_label="Your bids",
            )


def quote_blockers(*, company: Company, project: Project) -> list[str]:
    """Reasons this company cannot submit or change a quotation right now."""
    if not project.accepting_quotations:
        return ["This project is not accepting quotations."]
    if not company_prequalified(company):
        return ["Envelope 1 must be approved before quoting."]
    return requirement_issues(company, project)


@transaction.atomic
def submit_quotation(
    *,
    rfq: RFQ,
    company: Company,
    data: dict[str, Any],
    uploaded: Any,
    user: AbstractBaseUser,
    request: HttpRequest | None,
) -> Quotation:
    """Create or replace the company's quotation for this RFQ (before closing only)."""
    project = Project.objects.select_for_update().get(pk=rfq.project_id)
    blockers = quote_blockers(company=company, project=project)
    if blockers:
        raise ValueError(blockers[0])

    existing = (
        Quotation.objects.select_for_update().filter(rfq=rfq, company=company).first()
    )
    if existing is None and uploaded is None:
        raise ValueError("Upload your quotation PDF.")

    now = timezone.now()
    is_new_bid = existing is None or existing.status != Quotation.Status.SUBMITTED
    quotation = existing or Quotation(rfq=rfq, company=company)
    quotation.total_price = data["total_price"]
    quotation.handover_date = data["handover_date"]
    quotation.remarks = data.get("remarks") or ""
    quotation.status = Quotation.Status.SUBMITTED
    quotation.withdrawn_at = None
    quotation.declaration_version = DECLARATION_VERSION
    quotation.declaration_text = declaration_text(company.name)
    quotation.declaration_accepted_at = now
    quotation.declaration_ip = client_ip(request)
    quotation.submitted_by = user
    quotation.submitted_at = now
    if uploaded is not None:
        version = (existing.version + 1) if existing else 1
        store_quotation_document(quotation=quotation, uploaded=uploaded, version=version)
    quotation.save()

    # Sealed bidding: the audit trail (visible to staff) never records the price
    write_audit(
        category=AuditLog.Category.RFQ,
        action="quotation_updated" if existing else "quotation_submitted",
        actor=user,
        request=request,
        changes={
            "project": project.reference,
            "rfq": rfq.code,
            "company_id": company.pk,
            "version": quotation.version,
            "declaration_version": DECLARATION_VERSION,
        },
        object_type="Quotation",
        object_id=quotation.pk,
    )
    if is_new_bid:
        count = rfq.quotations.filter(status=Quotation.Status.SUBMITTED).count()
        # Sealed bidding: staff see only that a bid arrived — never the bidder, price, or file
        notify_event(
            users=staff_recipients(PROCUREMENT),
            dedupe_key=f"staff-quotes-{rfq.pk}",
            title=f"New quotation received — {rfq.code} {rfq.title}",
            body=(
                f"{project.reference}: {count} vendor{'s have' if count != 1 else ' has'} quoted so far. "
                f"Quotations stay sealed until {timezone.localtime(project.closing_at):%d %b %Y %H:%M}."
            ),
            link_url=reverse("tenders:tender_detail", kwargs={"pk": project.pk}),
            link_label="View tender",
        )
    return quotation


@transaction.atomic
def withdraw_quotation(
    *, quotation: Quotation, user: AbstractBaseUser, request: HttpRequest | None
) -> None:
    quotation = Quotation.objects.select_for_update().select_related("rfq__project").get(pk=quotation.pk)
    if not quotation.rfq.project.accepting_quotations:
        raise ValueError("Quotations cannot be withdrawn after closing.")
    if quotation.status == Quotation.Status.WITHDRAWN:
        raise ValueError("Quotation is already withdrawn.")
    quotation.status = Quotation.Status.WITHDRAWN
    quotation.withdrawn_at = timezone.now()
    quotation.save(update_fields=["status", "withdrawn_at", "updated_at"])
    write_audit(
        category=AuditLog.Category.RFQ,
        action="quotation_withdrawn",
        actor=user,
        request=request,
        changes={"project": quotation.rfq.project.reference, "rfq": quotation.rfq.code},
        object_type="Quotation",
        object_id=quotation.pk,
    )


@transaction.atomic
def recommend_award(
    *,
    rfq: RFQ,
    quotation: Quotation,
    actor: AbstractBaseUser,
    note: str,
    request: HttpRequest | None,
) -> TenderAward:
    project = Project.objects.select_for_update().get(pk=rfq.project_id)
    note = (note or "").strip()
    if not note:
        raise ValueError("A recommendation justification is required.")
    if project.status != Project.Status.OPEN or project.is_sealed:
        raise ValueError("Awards can only be recommended after the project closes.")
    if quotation.rfq_id != rfq.pk or quotation.status != Quotation.Status.SUBMITTED:
        raise ValueError("Select a submitted quotation for this RFQ.")
    if TenderAward.objects.filter(rfq=rfq, status__in=TenderAward.ACTIVE_STATUSES).exists():
        raise ValueError("This RFQ already has a pending or approved award.")

    award = TenderAward.objects.create(
        rfq=rfq,
        quotation=quotation,
        recommendation_note=note,
        recommended_by=actor,
    )
    write_audit(
        category=AuditLog.Category.APPROVAL,
        action="award_recommended",
        actor=actor,
        request=request,
        changes={
            "project": project.reference,
            "rfq": rfq.code,
            "company_id": quotation.company_id,
            "total_price": str(quotation.total_price),
            "note": note,
        },
        object_type="TenderAward",
        object_id=award.pk,
    )
    notify_event(
        users=staff_recipients(DIRECTOR, exclude=actor),
        dedupe_key=f"staff-award-{award.pk}",
        title=f"Award awaiting your approval — {rfq.code} {rfq.title}",
        body=f"Procurement recommends {quotation.company.name} for {rfq.code} under {project.reference}.",
        link_url=reverse("staff:approval_queue"),
        link_label="Open approval queue",
    )
    return award


@transaction.atomic
def decide_award(
    *,
    award: TenderAward,
    actor: AbstractBaseUser,
    approve: bool,
    note: str,
    request: HttpRequest | None,
) -> None:
    award = (
        TenderAward.objects.select_for_update()
        .select_related("rfq__project", "quotation__company__owner")
        .get(pk=award.pk)
    )
    if award.status != TenderAward.Status.PENDING_DIRECTOR:
        raise ValueError("This award is not awaiting a decision.")
    note = (note or "").strip()
    if not approve and not note:
        raise ValueError("A reason is required to reject a recommendation.")

    award.status = TenderAward.Status.APPROVED if approve else TenderAward.Status.REJECTED
    award.decision_note = note
    award.decided_by = actor
    award.decided_at = timezone.now()
    award.save(update_fields=["status", "decision_note", "decided_by", "decided_at"])

    rfq = award.rfq
    project = rfq.project
    write_audit(
        category=AuditLog.Category.APPROVAL,
        action="award_approved" if approve else "award_rejected",
        actor=actor,
        request=request,
        changes={
            "project": project.reference,
            "rfq": rfq.code,
            "company_id": award.quotation.company_id,
            "note": note,
        },
        object_type="TenderAward",
        object_id=award.pk,
    )
    # Vendors are told the result by staff outside the system, so only Procurement is notified here
    winner = award.quotation.company
    if approve:
        title = f"Award approved — {rfq.code} {rfq.title}"
        body = f"The Director approved {winner.name} for {rfq.code} under {project.reference}. Please inform the vendor."
        level = Notification.Level.SUCCESS
    else:
        title = f"Award recommendation rejected — {rfq.code} {rfq.title}"
        body = f"The Director rejected {winner.name} for {rfq.code}. Reason: {note}"
        level = Notification.Level.WARNING
    notify_event(
        users=staff_recipients(PROCUREMENT, exclude=actor),
        dedupe_key=f"staff-award-decision-{rfq.pk}",
        title=title,
        body=body,
        level=level,
        link_url=reverse("tenders:tender_detail", kwargs={"pk": project.pk}),
        link_label="View tender",
    )


def pending_awards() -> QuerySet[TenderAward]:
    return (
        TenderAward.objects.filter(status=TenderAward.Status.PENDING_DIRECTOR)
        .select_related("rfq__project", "quotation__company", "recommended_by")
        .order_by("recommended_at")
    )
