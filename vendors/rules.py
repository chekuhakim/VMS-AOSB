"""Rules-based auto evaluation for company registration (plan decision 1A).

Deterministic checks only — no ML. Outcomes are approved or rejected with
machine-readable reason codes stored on Company.evaluation_notes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.utils import timezone

from vendors.models import Company, CompanyDocument


@dataclass(frozen=True)
class EvaluationResult:
    approved: bool
    reason_codes: list[str]


def _latest_doc(company: Company, doc_type: str) -> CompanyDocument | None:
    return company.documents.filter(doc_type=doc_type).order_by("-version").first()


def _expired(expiry: date | None, today: date) -> bool:
    return expiry is not None and expiry < today


def evaluate_company_registration(company: Company) -> EvaluationResult:
    """Return approve/reject for a fully filled registration.

    Compliance gates (ISO-aligned completeness + expiry):
    - Steps 1–3, 5–6 required always
    - Step 4 required only when includes_electrical_work is True
    - Required PDFs present; enterprise SSM + CIDB (+ ST if electrical) not expired
    - Declaration accepted with a stored text version
    """
    reasons: list[str] = []
    today = timezone.localdate()

    # Step 1
    if not (company.name and company.primary_contact_name and company.contact_number and company.official_email):
        reasons.append("incomplete_company_profile")

    # Step 2
    if not (company.ssm_registration_number and company.date_of_incorporation):
        reasons.append("incomplete_ssm")
    ssm_doc = _latest_doc(company, CompanyDocument.DocType.SSM)
    if ssm_doc is None:
        reasons.append("missing_ssm_document")
    if company.is_enterprise:
        if company.ssm_document_expiry is None:
            reasons.append("missing_ssm_expiry")
        elif _expired(company.ssm_document_expiry, today):
            reasons.append("ssm_document_expired")

    # Step 3
    if not (
        company.cidb_registration_number
        and company.cidb_grade
        and company.cidb_categories
        and company.cidb_certificate_expiry
    ):
        reasons.append("incomplete_cidb")
    cidb_doc = _latest_doc(company, CompanyDocument.DocType.CIDB)
    if cidb_doc is None:
        reasons.append("missing_cidb_document")
    if _expired(company.cidb_certificate_expiry, today):
        reasons.append("cidb_certificate_expired")

    # Step 4 — only when electrical scope is yes
    if company.includes_electrical_work is None:
        reasons.append("missing_electrical_scope_answer")
    elif company.includes_electrical_work:
        if not (
            company.st_contractor_class
            and company.st_license_number
            and company.st_certificate_expiry
            and company.chargeman_name
        ):
            reasons.append("incomplete_st_licensing")
        st_doc = _latest_doc(company, CompanyDocument.DocType.ST)
        if st_doc is None:
            reasons.append("missing_st_document")
        if _expired(company.st_certificate_expiry, today):
            reasons.append("st_certificate_expired")

    # Step 5
    if not (
        company.lhdn_tin
        and company.sst_registration_number
        and company.myinvois_readiness
        and company.bank_account_for_payment
    ):
        reasons.append("incomplete_lhdn")

    # Step 6
    if not (company.hse_representative_name and company.public_liability_coverage):
        reasons.append("incomplete_hse")
    if not company.declaration_accepted or not company.declaration_text_version:
        reasons.append("declaration_missing")

    return EvaluationResult(approved=len(reasons) == 0, reason_codes=reasons)


REASON_LABELS: dict[str, str] = {
    "incomplete_company_profile": "Company profile is incomplete.",
    "incomplete_ssm": "SSM registration details are incomplete.",
    "missing_ssm_document": "SSM statutory PDF is missing.",
    "missing_ssm_expiry": "Enterprise SSM document expiry date is required.",
    "ssm_document_expired": "SSM document is expired.",
    "incomplete_cidb": "CIDB registration details are incomplete.",
    "missing_cidb_document": "CIDB certificate PDF is missing.",
    "cidb_certificate_expired": "CIDB certificate is expired.",
    "missing_electrical_scope_answer": "Electrical work scope (yes/no) is required.",
    "incomplete_st_licensing": "ST licensing details are incomplete.",
    "missing_st_document": "ST license PDF is missing.",
    "st_certificate_expired": "ST license is expired.",
    "incomplete_lhdn": "LHDN / e-invoice details are incomplete.",
    "incomplete_hse": "HSE details are incomplete.",
    "declaration_missing": "Declaration was not accepted.",
}
