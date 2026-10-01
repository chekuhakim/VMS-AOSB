"""Data builders for the staff admin dashboard (stat cards, submissions, pipeline, audit)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.urls import reverse
from django.utils import timezone

from audit.models import AuditLog
from envelope1.models import Envelope1Document, Envelope1Submission
from vendors.models import Company

EXPIRY_WINDOW_DAYS = 30

# Per-step saves and company switching would drown out the governance events
NOISY_AUDIT_ACTIONS: set[str] = {"switch_active_company", "envelope1_draft_msa_downloaded"}
NOISY_AUDIT_PREFIXES: tuple[str, ...] = ("wizard_step_", "envelope1_step_")

AUDIT_TITLES: dict[str, str] = {
    "vendor_registered": "New vendor account registered",
    "vendor_registered_social": "New vendor account (Google)",
    "company_draft_created": "Company registration started",
    "company_sample_created": "Sample company created",
    "company_deleted": "Company deleted",
    "company_registration_evaluated": "Company registration evaluated",
    "envelope1_draft_opened": "Envelope 1 draft opened",
    "envelope1_submitted": "Envelope 1 submitted",
    "envelope1_withdrawal_requested": "Envelope 1 withdrawal requested",
    "envelope1_locked_for_evaluation": "Envelope 1 locked for evaluation",
    "envelope1_item_evaluated": "Checklist item evaluated",
    "envelope1_sent_to_director": "Envelope 1 sent to Director",
    "envelope1_rejected_by_procurement": "Envelope 1 rejected by Procurement",
    "envelope1_director_approved": "Envelope 1 approved by Director",
    "envelope1_director_rejected": "Envelope 1 rejected by Director",
    "envelope1_withdrawal_approved": "Withdrawal approved — Envelope 1 unlocked",
    "envelope1_withdrawal_rejected": "Withdrawal rejected",
}


@dataclass(frozen=True)
class SubmissionRow:
    company_name: str
    ssm: str
    stage: str  # "Envelope 1" | "Registration"
    submitted_at: datetime | None
    status_label: str
    status_tone: str  # amber | red | green | slate
    action_label: str
    action_url: str


@dataclass(frozen=True)
class PipelineStage:
    title: str
    count: int
    percent: int


@dataclass(frozen=True)
class AuditItem:
    title: str
    actor: str
    created_at: datetime
    tone: str  # green | red | blue


def build_stat_cards() -> dict[str, int]:
    today = timezone.localdate()
    month_start = today.replace(day=1)
    approved = Company.objects.filter(registration_status=Company.RegistrationStatus.APPROVED)
    return {
        "vendors_total": approved.count(),
        "vendors_this_month": approved.filter(evaluated_at__date__gte=month_start).count(),
        "pending_e1_reviews": Envelope1Submission.objects.filter(
            status__in=[
                Envelope1Submission.Status.SUBMITTED,
                Envelope1Submission.Status.PENDING_EVALUATION,
                Envelope1Submission.Status.IN_PROGRESS,
            ]
        ).count(),
        "pending_approval": Envelope1Submission.objects.filter(
            status=Envelope1Submission.Status.PENDING_DIRECTOR
        ).count(),
        "expiring_certificates": count_expiring_certificates(today),
    }


def count_expiring_certificates(today: date) -> int:
    """Certificates already expired or expiring within the window (compliance alert)."""
    limit = today + timedelta(days=EXPIRY_WINDOW_DAYS)
    total = 0
    companies = Company.objects.exclude(registration_status=Company.RegistrationStatus.DRAFT)
    for company in companies.only(
        "ssm_document_expiry", "cidb_certificate_expiry", "st_certificate_expiry"
    ):
        for expiry in (
            company.ssm_document_expiry,
            company.cidb_certificate_expiry,
            company.st_certificate_expiry,
        ):
            if expiry and expiry <= limit:
                total += 1

    # Only the latest version of each Envelope 1 document counts — older versions are superseded
    latest: dict[tuple[int, str], Envelope1Document] = {}
    for doc in (
        Envelope1Document.objects.exclude(submission__status=Envelope1Submission.Status.DRAFT)
        .order_by("-version")
        .only("submission_id", "doc_type", "version", "expiry_date")
    ):
        latest.setdefault((doc.submission_id, doc.doc_type), doc)
    for doc in latest.values():
        if doc.expiry_date and doc.expiry_date <= limit:
            total += 1
    return total


def _e1_row(sub: Envelope1Submission, *, can_evaluate: bool, can_approve: bool) -> SubmissionRow:
    detail_url = reverse("staff:envelope1_detail", args=[sub.pk])
    status = sub.status
    S = Envelope1Submission.Status
    if status in {S.SUBMITTED, S.PENDING_EVALUATION}:
        label, tone = "Pending Evaluation", "amber"
        action = "Evaluate Now" if can_evaluate else "View Details"
    elif status == S.IN_PROGRESS:
        label, tone = "In Evaluation", "amber"
        action = "Review Now" if can_evaluate else "View Details"
    elif status == S.PENDING_DIRECTOR:
        label, tone = "Awaiting Approval", "red"
        action = "Approve Now" if can_approve else "View Details"
    elif status == S.APPROVED:
        label, tone, action = "Approved", "green", "View Details"
    elif status == S.REJECTED:
        label, tone, action = "Rejected", "red", "View Details"
    else:
        label, tone, action = sub.get_status_display(), "slate", "View Details"
    return SubmissionRow(
        company_name=sub.company.name,
        ssm=sub.ssm_registration_number or sub.company.ssm_registration_number or "—",
        stage="Envelope 1",
        submitted_at=sub.submitted_at or sub.updated_at,
        status_label=label,
        status_tone=tone,
        action_label=action,
        action_url=detail_url,
    )


def _registration_row(company: Company) -> SubmissionRow:
    R = Company.RegistrationStatus
    if company.registration_status == R.APPROVED:
        label, tone = "Verified", "green"
    elif company.registration_status == R.REJECTED:
        label, tone = "Rejected", "red"
    else:
        label, tone = "Submitted", "amber"
    return SubmissionRow(
        company_name=company.name,
        ssm=company.ssm_registration_number or "—",
        stage="Registration",
        submitted_at=company.submitted_at or company.updated_at,
        status_label=label,
        status_tone=tone,
        action_label="View Details",
        action_url=reverse("staff:company_detail", args=[company.pk]),
    )


def build_recent_submissions(
    *, stage: str, can_evaluate: bool, can_approve: bool, limit: int = 8
) -> list[SubmissionRow]:
    rows: list[SubmissionRow] = []
    if stage in ("", "envelope1"):
        for sub in (
            Envelope1Submission.objects.select_related("company")
            .exclude(status=Envelope1Submission.Status.DRAFT)
            .order_by("-updated_at")[:limit]
        ):
            rows.append(_e1_row(sub, can_evaluate=can_evaluate, can_approve=can_approve))
    if stage in ("", "registration"):
        for company in (
            Company.objects.exclude(registration_status=Company.RegistrationStatus.DRAFT)
            .order_by("-updated_at")[:limit]
        ):
            rows.append(_registration_row(company))
    epoch = timezone.make_aware(datetime(1970, 1, 1))
    rows.sort(key=lambda r: r.submitted_at or epoch, reverse=True)
    return rows[:limit]


def build_pipeline() -> list[PipelineStage]:
    """Where each company currently sits; percent is its share of all companies in process."""
    S = Envelope1Submission.Status
    active_e1_company_ids = set(
        Envelope1Submission.objects.exclude(status=S.DRAFT).values_list("company_id", flat=True)
    )
    initial = (
        Company.objects.filter(registration_status=Company.RegistrationStatus.APPROVED)
        .exclude(pk__in=active_e1_company_ids)
        .count()
    )
    compliance = Envelope1Submission.objects.filter(
        status__in=[S.SUBMITTED, S.PENDING_EVALUATION, S.IN_PROGRESS]
    ).count()
    director = Envelope1Submission.objects.filter(status=S.PENDING_DIRECTOR).count()
    total = initial + compliance + director

    def pct(n: int) -> int:
        return round(n * 100 / total) if total else 0

    return [
        PipelineStage("Initial registration", initial, pct(initial)),
        PipelineStage("Compliance check", compliance, pct(compliance)),
        PipelineStage("Director review", director, pct(director)),
    ]


def _audit_tone(action: str) -> str:
    if "rejected" in action or "deleted" in action:
        return "red"
    if "approved" in action:
        return "green"
    return "blue"


def build_audit_feed(limit: int = 5) -> list[AuditItem]:
    items: list[AuditItem] = []
    for row in AuditLog.objects.order_by("-created_at")[: limit * 10]:
        if row.action in NOISY_AUDIT_ACTIONS or row.action.startswith(NOISY_AUDIT_PREFIXES):
            continue
        title = AUDIT_TITLES.get(row.action) or row.action.replace("_", " ").capitalize()
        items.append(
            AuditItem(
                title=title,
                actor=row.actor_label or "System",
                created_at=row.created_at,
                tone=_audit_tone(row.action),
            )
        )
        if len(items) >= limit:
            break
    return items
