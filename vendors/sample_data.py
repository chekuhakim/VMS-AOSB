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
        "sst_registration_number": f"W10-{_random_digits(4)}-{_random_digits(8)}",
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
        # Step 1
        primary_contact_name="Abu bin Bakar",
        contact_number="0123456789",
        official_email="abu@cahaya.com.my",
        # Step 2
        ssm_registration_number=ids["ssm_registration_number"],
        date_of_incorporation=date(2018, 3, 15),
        is_enterprise=True,
        ssm_document_expiry=today + timedelta(days=400),
        # Step 3
        cidb_registration_number=ids["cidb_registration_number"],
        cidb_grade="G5",
        cidb_categories=["CE", "ME"],
        cidb_certificate_expiry=today + timedelta(days=200),
        # Step 4
        includes_electrical_work=True,
        st_contractor_class="Class A",
        st_license_number=ids["st_license_number"],
        st_certificate_expiry=today + timedelta(days=180),
        chargeman_name="Ahmad bin Hassan",
        # Step 5
        lhdn_tin=ids["lhdn_tin"],
        sst_registration_number=ids["sst_registration_number"],
        myinvois_readiness=Company.MyInvoisReadiness.YES,
        bank_account_for_payment="Maybank 5642-1234-5678",
        # Step 6 fields (declaration still confirmed on submit)
        hse_representative_name="Siti Nurhaliza",
        public_liability_coverage="RM 1,000,000",
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
    return company
