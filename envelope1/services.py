"""Envelope 1 domain helpers."""

from __future__ import annotations

from envelope1.checklist import STEP_DOC_TYPES
from envelope1.models import Envelope1Document, Envelope1Submission
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


def missing_required_docs(submission: Envelope1Submission) -> list[str]:
    have = latest_docs_map(submission)
    missing: list[str] = []
    for _step, types in STEP_DOC_TYPES.items():
        for doc_type in types:
            if doc_type not in have:
                missing.append(doc_type)
    return missing


def can_access_envelope1(company: Company | None) -> bool:
    return bool(
        company
        and company.registration_status == Company.RegistrationStatus.APPROVED
    )
