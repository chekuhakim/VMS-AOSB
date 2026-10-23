"""Envelope 1 domain helpers."""

from __future__ import annotations

from envelope1.checklist import (
    ALL_ITEMS,
    MIN_FINANCIAL_STATEMENTS,
    REQUIRED_UPLOADS,
    YES_NO_UPLOADS,
)
from envelope1.models import Envelope1Document, Envelope1Item, Envelope1Submission
from vendors.models import Company


def latest_submission(company: Company) -> Envelope1Submission | None:
    return (
        Envelope1Submission.objects.filter(company=company)
        .order_by("-cycle_number")
        .first()
    )


def get_or_create_draft(company: Company) -> tuple[Envelope1Submission, bool]:
    """One Envelope 1 per company — create on first visit, otherwise reuse it.

    Returns (submission, created).
    """
    latest = latest_submission(company)
    if latest is not None:
        return latest, False

    submission = Envelope1Submission.objects.create(
        company=company,
        cycle_number=1,
        status=Envelope1Submission.Status.DRAFT,
        legal_name=company.name,
        ssm_registration_number=company.ssm_registration_number,
        contact_name=company.primary_contact_name,
        contact_email=company.official_email,
    )
    return submission, True


def latest_docs_map(submission: Envelope1Submission) -> dict[str, Envelope1Document]:
    latest: dict[str, Envelope1Document] = {}
    for doc in submission.documents.order_by("-version"):
        latest.setdefault(doc.doc_type, doc)
    return latest


def missing_items(submission: Envelope1Submission) -> list[str]:
    """Checklist items (Envelope1Item values) still incomplete — gates the final submit."""
    docs = latest_docs_map(submission)
    missing: list[str] = []
    for item in ALL_ITEMS:
        if item in REQUIRED_UPLOADS:
            done = REQUIRED_UPLOADS[item] in docs
        elif item in YES_NO_UPLOADS:
            answer_field, doc_type = YES_NO_UPLOADS[item]
            answer = getattr(submission, answer_field)
            # "No" is a complete answer; "Yes" needs its supporting PDF
            done = answer is False or (answer is True and doc_type in docs)
        elif item == Envelope1Item.FINANCIAL_STATEMENTS:
            done = submission.financial_statements.count() >= MIN_FINANCIAL_STATEMENTS
        elif item == Envelope1Item.SABAH_INTEREST:
            done = submission.sabah_interest is not None
        elif item == Envelope1Item.PRIMARY_SUPPLIERS:
            done = submission.primary_suppliers.exists()
        elif item == Envelope1Item.LEAD_TIME:
            done = bool(
                submission.lead_time_sea_freight_days or submission.lead_time_semenanjung_days
            )
        elif item == Envelope1Item.SITE_SUPERVISOR:
            done = bool(submission.site_supervisor_name.strip())
        elif item == Envelope1Item.TIMESTAMPED_REPORTING:
            done = submission.accepts_timestamped_reporting
        elif item == Envelope1Item.METMALAYSIA_EOT:
            done = submission.accepts_metmalaysia_eot
        elif item == Envelope1Item.PAST_PROJECTS:
            done = submission.has_past_projects is False or (
                submission.has_past_projects is True and submission.past_projects.exists()
            )
        else:
            done = True
        if not done:
            missing.append(item)
    return missing


def can_access_envelope1(company: Company | None) -> bool:
    return bool(
        company
        and company.registration_status == Company.RegistrationStatus.APPROVED
    )
