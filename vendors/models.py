"""Vendor company registry and registration wizard data."""

from __future__ import annotations

import re
import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q, Value
from django.db.models.functions import Replace, Upper

# Government-issued identifiers: one legal entity may hold each value only once
UNIQUE_IDENTIFIER_FIELDS: dict[str, str] = {
    "ssm_registration_number": "SSM Registration Number",
    "cidb_registration_number": "CIDB Registration Number",
    "st_license_number": "ST License Number",
    "lhdn_tin": "LHDN TIN",
}


def normalize_identifier(value: str | None) -> str:
    """Stored form: no whitespace, upper-case (dashes kept for readability)."""
    return re.sub(r"\s+", "", value or "").upper()


def identifier_key(field: str) -> Upper:
    """Comparison key ignoring case, spaces and dashes (2020-0123 == 20200123)."""
    return Upper(
        Replace(Replace(F(field), Value(" "), Value("")), Value("-"), Value(""))
    )


class Company(models.Model):
    """A company owned by one vendor user — filled via the 6-step registration wizard."""

    class RegistrationStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    class Bank(models.TextChoices):
        MAYBANK = "maybank", "Maybank"
        CIMB = "cimb", "CIMB Bank"
        PUBLIC_BANK = "public_bank", "Public Bank"
        RHB = "rhb", "RHB Bank"
        HONG_LEONG = "hong_leong", "Hong Leong Bank"
        AMBANK = "ambank", "AmBank"
        BANK_ISLAM = "bank_islam", "Bank Islam"
        BANK_RAKYAT = "bank_rakyat", "Bank Rakyat"
        BSN = "bsn", "Bank Simpanan Nasional (BSN)"
        AFFIN = "affin", "Affin Bank"
        ALLIANCE = "alliance", "Alliance Bank"
        OCBC = "ocbc", "OCBC Bank"
        UOB = "uob", "UOB Bank"
        HSBC = "hsbc", "HSBC Bank"
        STANDARD_CHARTERED = "standard_chartered", "Standard Chartered"
        AGROBANK = "agrobank", "Agrobank"
        MUAMALAT = "muamalat", "Bank Muamalat"
        MBSB = "mbsb", "MBSB Bank"
        OTHER = "other", "Other"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="companies",
    )
    # Step progress: 1–6 while drafting; 6 after last step saved
    wizard_step = models.PositiveSmallIntegerField(default=1)

    # --- Step 1: Company profile ---
    name = models.CharField(max_length=255)
    primary_contact_name = models.CharField(max_length=150, blank=True)
    contact_number = models.CharField(max_length=40, blank=True)
    official_email = models.EmailField(blank=True)
    principal_address = models.TextField(blank=True)
    # MSA party details used to generate the agreement during registration.
    msa_signatory_name = models.CharField(max_length=150, blank=True)
    msa_signatory_designation = models.CharField(max_length=150, blank=True)

    # --- Step 2: SSM E-info ---
    ssm_registration_number = models.CharField(max_length=50, blank=True)
    date_of_incorporation = models.DateField(null=True, blank=True)
    is_enterprise = models.BooleanField(
        default=False,
        help_text="Enterprises must provide an SSM document expiry date.",
    )
    ssm_document_expiry = models.DateField(null=True, blank=True)

    # --- Step 3: CIDB ---
    # Opt-out is explicit: a company with no CIDB registration can still be approved,
    # but tender eligibility treats a blank grade as below every minimum grade.
    no_cidb_registration = models.BooleanField(
        default=False,
        help_text="Vendor declared that the company does not hold a CIDB registration.",
    )
    cidb_registration_number = models.CharField(max_length=50, blank=True)
    cidb_grade = models.CharField(max_length=20, blank=True)
    cidb_certificate_expiry = models.DateField(null=True, blank=True)

    # --- Step 4: ST Licensing (optional / conditional) ---
    includes_electrical_work = models.BooleanField(null=True, blank=True)
    st_license_number = models.CharField(max_length=50, blank=True)
    st_certificate_expiry = models.DateField(null=True, blank=True)

    # --- Step 5: LHDN & bank details ---
    lhdn_tin = models.CharField(max_length=50, blank=True)
    bank_name = models.CharField(max_length=30, choices=Bank.choices, blank=True)
    bank_name_other = models.CharField(max_length=120, blank=True)
    bank_account_number = models.CharField(max_length=20, blank=True)
    bank_account_name = models.CharField(max_length=150, blank=True)

    # --- Step 6: Declaration ---
    declaration_accepted = models.BooleanField(default=False)
    declaration_text_version = models.CharField(max_length=20, blank=True)
    declaration_accepted_at = models.DateTimeField(null=True, blank=True)
    declaration_ip = models.GenericIPAddressField(null=True, blank=True)

    registration_status = models.CharField(
        max_length=20,
        choices=RegistrationStatus.choices,
        default=RegistrationStatus.DRAFT,
        db_index=True,
    )
    # Test / demo companies stay in the database for audit but are hidden from
    # staff queues, dashboards, tender eligibility, and vendor company lists.
    is_hidden = models.BooleanField(default=False, db_index=True)
    # Machine-readable reason codes from the rules engine
    evaluation_notes = models.JSONField(default=list, blank=True)
    evaluated_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "company"
        verbose_name_plural = "companies"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "name"],
                name="uniq_company_name_per_owner",
            ),
            # Blank values are allowed on many drafts; filled identifiers are unique system-wide
            *[
                models.UniqueConstraint(
                    identifier_key(field),
                    condition=~Q(**{field: ""}),
                    name=f"uniq_company_{field}",
                    violation_error_message=f"This {label} is already registered to another company.",
                )
                for field, label in UNIQUE_IDENTIFIER_FIELDS.items()
            ],
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def is_editable(self) -> bool:
        """Vendors may edit drafts and re-submit rejected/approved records."""
        return True

    @property
    def bank_display(self) -> str:
        if self.bank_name == self.Bank.OTHER:
            return self.bank_name_other
        return self.get_bank_name_display() if self.bank_name else ""


class VendorInvitation(models.Model):
    """Staff-issued invitation for a vendor to create an account and register."""

    company_name = models.CharField(max_length=255)
    email = models.EmailField(db_index=True)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vendor_invitations_sent",
    )
    note = models.TextField(blank=True)
    company = models.ForeignKey(
        Company,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invitations",
    )
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vendor_invitations_accepted",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "vendor invitation"
        verbose_name_plural = "vendor invitations"

    def __str__(self) -> str:
        return f"{self.company_name} · {self.email}"

    @property
    def is_accepted(self) -> bool:
        return self.accepted_at is not None

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def is_expired(self) -> bool:
        from django.utils import timezone

        return not self.is_accepted and not self.is_revoked and timezone.now() >= self.expires_at

    @property
    def is_pending(self) -> bool:
        return not self.is_accepted and not self.is_revoked and not self.is_expired

    @property
    def status_label(self) -> str:
        if self.is_accepted:
            return "Accepted"
        if self.is_revoked:
            return "Revoked"
        if self.is_expired:
            return "Expired"
        return "Pending"


class CompanyDocument(models.Model):
    """Versioned PDF attached to a company registration (never overwrite blobs)."""

    class DocType(models.TextChoices):
        SSM = "ssm", "SSM statutory forms"
        CIDB = "cidb", "CIDB certificate"
        ST = "st", "ST license certificate"
        IC = "ic", "Identity card (IC)"
        SIGNED_MSA = "signed_msa", "Signed Master Service Agreement"

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    doc_type = models.CharField(max_length=20, choices=DocType.choices, db_index=True)
    storage_path = models.CharField(max_length=500)
    storage_backend = models.CharField(max_length=20, default="local")
    original_filename = models.CharField(max_length=255)
    version = models.PositiveIntegerField(default=1)
    expiry_date = models.DateField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-uploaded_at"]
        verbose_name = "company document"
        verbose_name_plural = "company documents"

    def __str__(self) -> str:
        return f"{self.company_id}:{self.doc_type}:v{self.version}"
