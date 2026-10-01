"""Envelope 1 submission cycles — vendor pre-qualification pack."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from vendors.models import Company


class Envelope1Submission(models.Model):
    """Single Envelope 1 pack per company (cycle_number kept for audit history)."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        PENDING_EVALUATION = "pending_evaluation", "Pending evaluation"
        IN_PROGRESS = "in_progress", "In progress"
        PENDING_DIRECTOR = "pending_director_approval", "Pending director approval"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="envelope1_submissions",
    )
    cycle_number = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=40,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    # Wizard progress 1–6 while drafting
    wizard_step = models.PositiveSmallIntegerField(default=1)

    # --- Step 1: MSA party details ---
    legal_name = models.CharField(max_length=255, blank=True)
    ssm_registration_number = models.CharField(max_length=50, blank=True)
    principal_address = models.TextField(blank=True)
    contact_name = models.CharField(max_length=150, blank=True)
    contact_email = models.EmailField(blank=True)
    msa_signatory_name = models.CharField(max_length=150, blank=True)
    msa_signatory_designation = models.CharField(max_length=150, blank=True)
    msa_party_saved_at = models.DateTimeField(null=True, blank=True)

    # --- Step 2: Signed MSA ---
    msa_effective_date = models.DateField(null=True, blank=True)

    # Lock when procurement starts evaluating (Phase 4); vendors may still edit
    # submitted packs until locked_at is set.
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="envelope1_locks",
    )

    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-cycle_number", "-created_at"]
        verbose_name = "Envelope 1 submission"
        verbose_name_plural = "Envelope 1 submissions"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "cycle_number"],
                name="uniq_envelope1_cycle_per_company",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.company_id} E1 cycle {self.cycle_number} ({self.status})"

    @property
    def is_locked(self) -> bool:
        """Vendor edits blocked once procurement has started evaluating."""
        return self.locked_at is not None

    @property
    def is_editable(self) -> bool:
        if self.is_locked:
            return False
        return self.status in {
            self.Status.DRAFT,
            self.Status.SUBMITTED,
            self.Status.PENDING_EVALUATION,
        }


class Envelope1Document(models.Model):
    """Versioned PDF belonging to an Envelope 1 cycle (never overwrite blobs)."""

    class DocType(models.TextChoices):
        SIGNED_MSA = "signed_msa", "Signed MSA"
        AUDITED_FINANCIALS = "audited_financials", "1.1 Audited Financial Statements (last 2 years)"
        BANK_FACILITY = "bank_facility", "1.2 Bank credit facility / overdraft"
        SUPPLIER_CREDIT = "supplier_credit", "1.3 Supplier credit terms proof"
        NO_ADVANCE = "no_advance", "1.4 No advance payment declaration"
        CAR_INSURANCE = "car_insurance", "1.5 Insurance — Contractor's All Risk (CAR)"
        FREIGHT_FORWARDER = "freight_forwarder", "2.1 Named freight forwarder"
        PRIMARY_SUPPLIERS = "primary_suppliers", "2.2 Primary Supplier List"
        SABAH_BACKUP = "sabah_backup", "2.3 Local Sabah backup suppliers"
        LEAD_TIME_MATRIX = "lead_time_matrix", "2.4 Logistic lead-time matrix"
        SITE_SUPERVISOR_CV = "site_supervisor_cv", "3.1 Dedicated site supervisor CV"
        TIMESTAMPED_REPORTING = "timestamped_reporting", "3.2 Timestamped reporting agreement"
        METMALAYSIA_EOT = "metmalaysia_eot", "3.3 MetMalaysia EOT agreement"
        QUALITY_PLAN = "quality_plan", "3.4 Quality management plan"
        HSE_PLAN = "hse_plan", "3.5 Health & safety (HSE) plan"
        PAST_PROJECTS = "past_projects", "4.1 Past Project List"
        CLIENT_REFERENCES = "client_references", "4.2 Client References"
        MANPOWER_MATRIX = "manpower_matrix", "4.3 Specialized manpower matrix"

    submission = models.ForeignKey(
        Envelope1Submission,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    doc_type = models.CharField(max_length=40, choices=DocType.choices, db_index=True)
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
        verbose_name = "Envelope 1 document"
        verbose_name_plural = "Envelope 1 documents"

    def __str__(self) -> str:
        return f"E1:{self.submission_id}:{self.doc_type}:v{self.version}"


class WithdrawalRequest(models.Model):
    """Vendor request to unlock a locked Envelope 1 cycle for edits."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    submission = models.ForeignKey(
        Envelope1Submission,
        on_delete=models.CASCADE,
        related_name="withdrawal_requests",
    )
    reason = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="envelope1_withdrawals",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="envelope1_withdrawal_reviews",
    )
    review_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Withdrawal {self.pk} ({self.status}) for E1 {self.submission_id}"
