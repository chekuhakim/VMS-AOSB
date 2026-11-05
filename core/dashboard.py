"""Dashboard progress stages, quick actions, and document expiry cards."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from django.urls import reverse
from django.utils import timezone

from vendors.models import Company, CompanyDocument

StatusTone = Literal["completed", "progress", "locked", "action", "soon", "expired", "valid"]
SOON_DAYS = 30


@dataclass
class StageCard:
    number: int
    title: str
    description: str
    status_label: str
    tone: StatusTone
    locked: bool
    href: str = ""


@dataclass
class QuickAction:
    title: str
    hint: str
    href: str
    icon: str  # building | envelope | vault | bid | plus


@dataclass
class ExpiryItem:
    label: str
    detail: str
    tone: StatusTone
    status_label: str


def _registration_stage(company: Company | None) -> StageCard:
    if company is None:
        return StageCard(
            number=1,
            title="Company registration",
            description="Create and submit your company profile for system evaluation.",
            status_label="Not started",
            tone="action",
            locked=False,
            href=reverse("vendors:register_company"),
        )

    status = company.registration_status
    if status == Company.RegistrationStatus.APPROVED:
        return StageCard(
            number=1,
            title="Company registration",
            description=f"{company.name} is registered and approved.",
            status_label="Completed",
            tone="completed",
            locked=False,
            href=reverse("vendors:company_detail", kwargs={"pk": company.pk}),
        )
    if status == Company.RegistrationStatus.REJECTED:
        return StageCard(
            number=1,
            title="Company registration",
            description="Registration was rejected — review notes and resubmit.",
            status_label="Action needed",
            tone="action",
            locked=False,
            href=reverse("vendors:company_detail", kwargs={"pk": company.pk}),
        )
    if status == Company.RegistrationStatus.SUBMITTED:
        return StageCard(
            number=1,
            title="Company registration",
            description="Submitted — waiting for rules-based evaluation.",
            status_label="In progress",
            tone="progress",
            locked=False,
            href=reverse("vendors:company_detail", kwargs={"pk": company.pk}),
        )
    return StageCard(
        number=1,
        title="Company registration",
        description=f"Draft in progress — step {company.wizard_step} of 6.",
        status_label="In progress",
        tone="progress",
        locked=False,
        href=reverse(
            "vendors:wizard_step",
            kwargs={"pk": company.pk, "step": max(1, company.wizard_step)},
        ),
    )


def build_progress_stages(company: Company | None) -> list[StageCard]:
    """Three onboarding stages — registration, Envelope 1, RFQ submission."""
    from envelope1.models import Envelope1Submission
    from envelope1.services import latest_submission

    stage1 = _registration_stage(company)
    reg_approved = bool(
        company and company.registration_status == Company.RegistrationStatus.APPROVED
    )
    e1 = latest_submission(company) if company and reg_approved else None

    if not reg_approved:
        stage2 = StageCard(
            number=2,
            title="Envelope 1",
            description="Company qualification pack. Unlocks after registration is approved.",
            status_label="Locked",
            tone="locked",
            locked=True,
        )
    elif e1 is None or e1.status == Envelope1Submission.Status.DRAFT:
        stage2 = StageCard(
            number=2,
            title="Envelope 1",
            description=(
                "Continue your qualification pack."
                if e1
                else "Complete pre-qualification documents for tender eligibility."
            ),
            status_label="In progress" if e1 else "Not started",
            tone="progress",
            locked=False,
            href=reverse("envelope1:home"),
        )
    elif e1.status == Envelope1Submission.Status.APPROVED:
        stage2 = StageCard(
            number=2,
            title="Envelope 1",
            description="Approved — tender eligibility unlocked.",
            status_label="Completed",
            tone="completed",
            locked=False,
            href=reverse("envelope1:home"),
        )
    elif e1.status == Envelope1Submission.Status.RETURNED_FOR_CORRECTION:
        stage2 = StageCard(
            number=2,
            title="Envelope 1",
            description="Returned for correction — fix the failed items and resubmit.",
            status_label="Action needed",
            tone="action",
            locked=False,
            href=reverse("envelope1:home"),
        )
    elif e1.status == Envelope1Submission.Status.REJECTED:
        stage2 = StageCard(
            number=2,
            title="Envelope 1",
            description="Rejected — contact procurement if you need to revise.",
            status_label="Action needed",
            tone="action",
            locked=False,
            href=reverse("envelope1:home"),
        )
    else:
        stage2 = StageCard(
            number=2,
            title="Envelope 1",
            description=e1.get_status_display(),
            status_label="In progress",
            tone="progress",
            locked=False,
            href=reverse("envelope1:home"),
        )

    envelope1_approved = bool(
        e1 and e1.status == Envelope1Submission.Status.APPROVED
    )
    if not envelope1_approved:
        stage3 = StageCard(
            number=3,
            title="RFQ submission",
            description="Submit RFQs on open projects once Envelope 1 is approved.",
            status_label="Locked",
            tone="locked",
            locked=True,
        )
    else:
        stage3 = StageCard(
            number=3,
            title="RFQ submission",
            description="Browse open projects and submit RFQs.",
            status_label="Available",
            tone="progress",
            locked=False,
            href=reverse("tenders:project_list"),
        )

    # The vendor journey ends at RFQ submission; award outcomes are handled by staff
    return [stage1, stage2, stage3]


def build_quick_actions(company: Company | None) -> list[QuickAction]:
    actions: list[QuickAction] = []
    if company is None:
        actions.append(
            QuickAction(
                title="Register company",
                hint="Start the 6-step company registration wizard",
                href=reverse("vendors:register_company"),
                icon="plus",
            )
        )
    elif company.registration_status == Company.RegistrationStatus.DRAFT:
        actions.append(
            QuickAction(
                title="Continue registration",
                hint=f"Resume {company.name} at step {company.wizard_step}",
                href=reverse(
                    "vendors:wizard_step",
                    kwargs={"pk": company.pk, "step": max(1, company.wizard_step)},
                ),
                icon="building",
            )
        )
    else:
        actions.append(
            QuickAction(
                title="View company",
                hint=f"{company.name} · {company.get_registration_status_display()}",
                href=reverse("vendors:company_detail", kwargs={"pk": company.pk}),
                icon="building",
            )
        )

    actions.append(
        QuickAction(
            title="Your companies",
            hint="Manage all companies under this vendor account",
            href=reverse("vendors:your_company"),
            icon="building",
        )
    )
    actions.append(
        QuickAction(
            title="Envelope 1",
            hint="Company qualification — opens after registration approval",
            href=reverse("envelope1:home"),
            icon="envelope",
        )
    )
    actions.append(
        QuickAction(
            title="Document vault",
            hint="Versioned PDFs and expiry tracking",
            href=reverse("envelope1:vault"),
            icon="vault",
        )
    )
    return actions[:4]


def _expiry_item(label: str, expiry: date | None, today: date) -> ExpiryItem | None:
    if expiry is None:
        return None
    soon = today + timedelta(days=SOON_DAYS)
    if expiry < today:
        days = (today - expiry).days
        return ExpiryItem(
            label=label,
            detail=f"Expired {days} day{'s' if days != 1 else ''} ago",
            tone="expired",
            status_label="Expired",
        )
    if expiry <= soon:
        days = (expiry - today).days
        return ExpiryItem(
            label=label,
            detail=f"Expires in {days} day{'s' if days != 1 else ''}",
            tone="soon",
            status_label="Soon",
        )
    return ExpiryItem(
        label=label,
        detail=f"Valid until {expiry:%b %Y}",
        tone="valid",
        status_label="Valid",
    )


def build_expiry_warnings(company: Company | None) -> list[ExpiryItem]:
    if company is None:
        return []
    today = timezone.localdate()
    items: list[ExpiryItem] = []

    mapping = [
        (CompanyDocument.DocType.CIDB, "CIDB certificate", company.cidb_certificate_expiry),
        (CompanyDocument.DocType.SSM, "SSM document", company.ssm_document_expiry),
        (CompanyDocument.DocType.ST, "ST license", company.st_certificate_expiry),
    ]
    for doc_type, label, fallback in mapping:
        doc = (
            CompanyDocument.objects.filter(company=company, doc_type=doc_type)
            .order_by("-version")
            .first()
        )
        expiry = doc.expiry_date if doc and doc.expiry_date else fallback
        # Skip SSM expiry when not an enterprise and no document expiry on file
        if doc_type == CompanyDocument.DocType.SSM and not company.is_enterprise and not expiry:
            continue
        # A declared absence of CIDB is not a missing certificate
        if doc_type == CompanyDocument.DocType.CIDB and company.no_cidb_registration:
            continue
        # Skip ST when electrical not in scope
        if doc_type == CompanyDocument.DocType.ST and not company.includes_electrical_work:
            continue
        item = _expiry_item(label, expiry, today)
        if item:
            items.append(item)

    # Sort: expired → soon → valid
    order = {"expired": 0, "soon": 1, "valid": 2, "action": 3, "locked": 4, "progress": 5, "completed": 6}
    items.sort(key=lambda i: order.get(i.tone, 9))
    return items
