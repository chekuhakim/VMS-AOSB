"""Sample company registration payload for local / DEBUG testing."""

from __future__ import annotations

import secrets
from datetime import date, timedelta
from io import BytesIO

from django.contrib.auth.models import AbstractBaseUser
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone

from vendors.documents import save_company_pdf
from vendors.models import Company, CompanyDocument

# Minimal valid PDF bytes for upload tests
_MIN_PDF = b"""%PDF-1.1
1 0 obj<<>>endobj
2 0 obj<< /Length 44 >>stream
BT /F1 12 Tf 100 700 Td (Sample) Tj ET
endstream
endobj
3 0 obj<< /Type /Page /Parent 4 0 R /Contents 2 0 R >>endobj
4 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj
5 0 obj<< /Type /Catalog /Pages 4 0 R >>endobj
xref
0 6
trailer<< /Size 6 /Root 5 0 R >>
startxref
0
%%EOF
"""


def _sample_pdf(name: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, _MIN_PDF, content_type="application/pdf")


def _random_digits(length: int) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(length))


def sample_identifiers() -> dict[str, str]:
    """Random government identifiers so repeated samples never hit the unique constraints."""
    return {
        "ssm_registration_number": f"20{_random_digits(10)}",
        "cidb_registration_number": f"CIDB-{_random_digits(7)}",
        "st_license_number": f"ST-{_random_digits(6)}",
        "lhdn_tin": f"C{_random_digits(10)}",
        "ic_number": f"{_random_digits(6)}-{_random_digits(2)}-{_random_digits(4)}",
    }


def unique_sample_name(owner: AbstractBaseUser) -> str:
    """Avoid unique-constraint clashes when loading sample data repeatedly."""
    base = "Cahaya Engineering Sdn Bhd"
    if not Company.objects.filter(owner=owner, name__iexact=base).exists():
        return base
    stamp = timezone.now().strftime("%H%M%S")
    return f"Cahaya Engineering Sdn Bhd ({stamp})"


@transaction.atomic
def create_sample_company(*, owner: AbstractBaseUser) -> Company:
    """Create a draft company with realistic Malaysian sample fields + PDFs."""
    today = timezone.localdate()
    ids = sample_identifiers()
    company = Company.objects.create(
        owner=owner,
        name=unique_sample_name(owner),
        wizard_step=6,
        registration_status=Company.RegistrationStatus.DRAFT,
        registration_type=Company.RegistrationType.ENTERPRISE,
        # Step 1
        primary_contact_name="Abu bin Bakar",
        contact_number="0123456789",
        official_email="abu@cahaya.com.my",
        principal_address="Lot 12, Jalan Perindustrian, 88450 Kota Kinabalu, Sabah",
        msa_signatory_name="Abu bin Bakar",
        msa_signatory_designation="Managing Director",
        # Step 2
        ssm_registration_number=ids["ssm_registration_number"],
        date_of_incorporation=date(2018, 3, 15),
        ssm_document_expiry=today + timedelta(days=400),
        ic_number=ids["ic_number"],
        # Step 3
        cidb_registration_number=ids["cidb_registration_number"],
        cidb_grade="G5",
        cidb_certificate_expiry=today + timedelta(days=200),
        # Step 4
        includes_electrical_work=True,
        st_license_number=ids["st_license_number"],
        st_certificate_expiry=today + timedelta(days=180),
        # Step 5
        lhdn_tin=ids["lhdn_tin"],
        bank_name=Company.Bank.MAYBANK,
        bank_account_number=f"5642{_random_digits(8)}",
        bank_account_name="Cahaya Engineering Sdn Bhd",
        # Step 6 declaration is confirmed on submit
        declaration_accepted=False,
    )

    save_company_pdf(
        company=company,
        doc_type=CompanyDocument.DocType.SSM,
        uploaded=_sample_pdf("ssm-sample.pdf"),
        user=owner,
        expiry_date=company.ssm_document_expiry,
    )
    save_company_pdf(
        company=company,
        doc_type=CompanyDocument.DocType.CIDB,
        uploaded=_sample_pdf("cidb-sample.pdf"),
        user=owner,
        expiry_date=company.cidb_certificate_expiry,
    )
    save_company_pdf(
        company=company,
        doc_type=CompanyDocument.DocType.ST,
        uploaded=_sample_pdf("st-sample.pdf"),
        user=owner,
        expiry_date=company.st_certificate_expiry,
    )
    save_company_pdf(
        company=company,
        doc_type=CompanyDocument.DocType.IC,
        uploaded=_sample_pdf("ic-sample.pdf"),
        user=owner,
    )
    save_company_pdf(
        company=company,
        doc_type=CompanyDocument.DocType.SIGNED_MSA,
        uploaded=_sample_pdf("signed-msa-sample.pdf"),
        user=owner,
    )
    return company
