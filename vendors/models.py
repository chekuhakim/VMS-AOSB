"""Vendor company registry and registration wizard data."""

from __future__ import annotations

import re

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
    "sst_registration_number": "SST Registration Number",
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

    class MyInvoisReadiness(models.TextChoices):
        YES = "yes", "Ready"
        NO = "no", "Not ready"
        PARTIAL = "partial", "In progress"

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

    # --- Step 2: SSM E-info ---
    ssm_registration_number = models.CharField(max_length=50, blank=True)
    date_of_incorporation = models.DateField(null=True, blank=True)
    is_enterprise = models.BooleanField(
        default=False,
        help_text="Enterprises must provide an SSM document expiry date.",
    )
    ssm_document_expiry = models.DateField(null=True, blank=True)

    # --- Step 3: CIDB ---
    cidb_registration_number = models.CharField(max_length=50, blank=True)
    cidb_grade = models.CharField(max_length=20, blank=True)
    cidb_categories = models.JSONField(
        default=list,
        blank=True,
        help_text="List of selected CIDB registered categories.",
    )
    cidb_certificate_expiry = models.DateField(null=True, blank=True)

    # --- Step 4: ST Licensing (optional / conditional) ---
    includes_electrical_work = models.BooleanField(null=True, blank=True)
    st_contractor_class = models.CharField(max_length=50, blank=True)
    st_license_number = models.CharField(max_length=50, blank=True)
    st_certificate_expiry = models.DateField(null=True, blank=True)
    chargeman_name = models.CharField(max_length=150, blank=True)

    # --- Step 5: LHDN & e-invoice ---
    lhdn_tin = models.CharField(max_length=50, blank=True)
    sst_registration_number = models.CharField(max_length=50, blank=True)
    myinvois_readiness = models.CharField(
        max_length=20,
        choices=MyInvoisReadiness.choices,
        blank=True,
    )
    bank_account_for_payment = models.CharField(max_length=120, blank=True)

    # --- Step 6: HSE + declaration ---
    hse_representative_name = models.CharField(max_length=150, blank=True)
    public_liability_coverage = models.CharField(max_length=120, blank=True)
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


class CompanyDocument(models.Model):
    """Versioned PDF attached to a company registration (never overwrite blobs)."""

    class DocType(models.TextChoices):
        SSM = "ssm", "SSM statutory forms"
        CIDB = "cidb", "CIDB certificate"
        ST = "st", "ST license certificate"

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
