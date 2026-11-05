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
        RETURNED_FOR_CORRECTION = (
            "returned_for_correction",
            "Returned for correction",
        )
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

    # --- Step 3: Financials (None = not answered yet) ---
    has_bank_facility = models.BooleanField(null=True, blank=True)
    has_supplier_credit = models.BooleanField(null=True, blank=True)

    # --- Step 4: Logistics ---
    class LeadTimeRange(models.TextChoices):
        UNDER_30 = "under_30", "Under 30 days"
        DAYS_30_60 = "30_60", "30–60 days"
        DAYS_60_90 = "60_90", "60–90 days"
        OVER_90 = "over_90", "More than 90 days"

    sabah_interest = models.BooleanField(null=True, blank=True)
    lead_time_range = models.CharField(
        max_length=20,
        choices=LeadTimeRange.choices,
        blank=True,
        help_text="Typical Sabah delivery range. Only asked when the vendor is interested in Sabah work.",
    )
    # Legacy exact-day values retained for historical submissions. New responses
    # use lead_time_range because a single number is not comparable across scopes.
    lead_time_sea_freight_days = models.PositiveSmallIntegerField(null=True, blank=True)
    lead_time_semenanjung_days = models.PositiveSmallIntegerField(null=True, blank=True)

    # --- Step 5: Quality, safety & governance ---
    site_supervisor_name = models.CharField(max_length=150, blank=True)
    accepts_timestamped_reporting = models.BooleanField(default=False)
    accepts_metmalaysia_eot = models.BooleanField(default=False)
    declarations_accepted_at = models.DateTimeField(null=True, blank=True)
    has_quality_plan = models.BooleanField(null=True, blank=True)
    has_hse_plan = models.BooleanField(null=True, blank=True)

    # --- Step 6: Track record ---
    has_past_projects = models.BooleanField(null=True, blank=True)
    has_client_references = models.BooleanField(null=True, blank=True)

    # Lock when procurement starts evaluating (Phase 4). Before that, a submitted
    # pack is reopened to Draft by the vendor (envelope1:reopen) before editing.
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="envelope1_locks",
    )

    submitted_at = models.DateTimeField(null=True, blank=True)

    # Return-for-correction loop. Failed items keep their FAIL result so the vendor
    # and Procurement can see exactly what needs fixing; on resubmission the failed
    # rows go back to PENDING, while previously passed items stay passed.
    returned_at = models.DateTimeField(null=True, blank=True)
    returned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="envelope1_returns",
    )
    returned_note = models.TextField(blank=True)
    correction_round = models.PositiveIntegerField(default=0)

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
        # Only drafts take edits, so Procurement never evaluates a half-edited pack
        return not self.is_locked and self.status == self.Status.DRAFT

    @property
    def can_reopen(self) -> bool:
        """Submitted but not yet locked by Procurement — vendor may pull it back to Draft."""
        return not self.is_locked and self.status in {
            self.Status.SUBMITTED,
            self.Status.PENDING_EVALUATION,
        }

    @property
    def is_returned_for_correction(self) -> bool:
        return self.status == self.Status.RETURNED_FOR_CORRECTION


class Envelope1Document(models.Model):
    """Versioned PDF belonging to an Envelope 1 cycle (never overwrite blobs)."""

    class DocType(models.TextChoices):
        SIGNED_MSA = "signed_msa", "Signed MSA"
        AUDITED_FINANCIALS = "audited_financials", "1.1 Financial statement"
        BANK_FACILITY = "bank_facility", "1.2 Bank credit facility / overdraft"
        SUPPLIER_CREDIT = "supplier_credit", "1.3 Supplier credit terms proof"
        NO_ADVANCE = "no_advance", "1.4 No advance payment declaration"
        CAR_INSURANCE = "car_insurance", "1.5 Insurance — Contractor's All Risk (CAR)"
        QUALITY_PLAN = "quality_plan", "3.4 Quality management plan"
        HSE_PLAN = "hse_plan", "3.5 Health & safety (HSE) plan"
        PAST_PROJECTS = "past_projects", "4.1 Past project document"
        CLIENT_REFERENCES = "client_references", "4.2 Client references"
        ORG_CHART = "org_chart", "4.3 Organisation chart"
        # Legacy upload types from the pre-questionnaire checklist; kept so old files still display
        FREIGHT_FORWARDER = "freight_forwarder", "Named freight forwarder (legacy)"
        PRIMARY_SUPPLIERS = "primary_suppliers", "Primary supplier list (legacy)"
        SABAH_BACKUP = "sabah_backup", "Local Sabah backup suppliers (legacy)"
        LEAD_TIME_MATRIX = "lead_time_matrix", "Logistic lead-time matrix (legacy)"
        SITE_SUPERVISOR_CV = "site_supervisor_cv", "Site supervisor CV (legacy)"
        TIMESTAMPED_REPORTING = "timestamped_reporting", "Timestamped reporting agreement (legacy)"
        METMALAYSIA_EOT = "metmalaysia_eot", "MetMalaysia EOT agreement (legacy)"
        MANPOWER_MATRIX = "manpower_matrix", "Specialized manpower matrix (legacy)"

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


class Envelope1Item(models.TextChoices):
    """Checklist items Procurement passes/fails (keys stored on Envelope1ItemEvaluation)."""

    SIGNED_MSA = "signed_msa", "Signed MSA"
    FINANCIAL_STATEMENTS = "audited_financials", "1.1 Financial statements (last 2 years)"
    BANK_FACILITY = "bank_facility", "1.2 Bank credit facility / overdraft"
    SUPPLIER_CREDIT = "supplier_credit", "1.3 Supplier credit terms"
    NO_ADVANCE = "no_advance", "1.4 No advance payment declaration"
    CAR_INSURANCE = "car_insurance", "1.5 Insurance — Contractor's All Risk (CAR)"
    SABAH_INTEREST = "sabah_interest", "2.1 Interest in working in Sabah"
    PRIMARY_SUPPLIERS = "primary_suppliers", "2.2 Primary suppliers"
    LEAD_TIME = "lead_time", "2.3 Logistic lead time"
    SITE_SUPERVISOR = "site_supervisor", "3.1 Dedicated site supervisor"
    TIMESTAMPED_REPORTING = "timestamped_reporting", "3.2 Timestamped reporting declaration"
    METMALAYSIA_EOT = "metmalaysia_eot", "3.3 MetMalaysia EOT declaration"
    QUALITY_PLAN = "quality_plan", "3.4 Quality management plan"
    HSE_PLAN = "hse_plan", "3.5 Health & safety (HSE) plan"
    PAST_PROJECTS = "past_projects", "4.1 Past project list"
    CLIENT_REFERENCES = "client_references", "4.2 Client references"
    ORG_CHART = "org_chart", "4.3 Organisation chart"


class FinancialStatement(models.Model):
    """1.1 row: one financial statement PDF for one financial year."""

    submission = models.ForeignKey(
        Envelope1Submission,
        on_delete=models.CASCADE,
        related_name="financial_statements",
    )
    year = models.PositiveSmallIntegerField()
    document = models.ForeignKey(
        Envelope1Document,
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        ordering = ["-year", "pk"]

    def __str__(self) -> str:
        return f"E1 {self.submission_id} FS {self.year}"


class PrimarySupplier(models.Model):
    """2.2 row: which supplier provides which structure."""

    submission = models.ForeignKey(
        Envelope1Submission,
        on_delete=models.CASCADE,
        related_name="primary_suppliers",
    )
    structure = models.CharField(max_length=200)
    supplier_name = models.CharField(max_length=200)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "pk"]

    def __str__(self) -> str:
        return f"{self.structure} — {self.supplier_name}"


class PastProject(models.Model):
    """4.1 row: past project name with its supporting PDF."""

    submission = models.ForeignKey(
        Envelope1Submission,
        on_delete=models.CASCADE,
        related_name="past_projects",
    )
    project_name = models.CharField(max_length=255)
    document = models.ForeignKey(
        Envelope1Document,
        on_delete=models.PROTECT,
        related_name="+",
    )
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "pk"]

    def __str__(self) -> str:
        return self.project_name


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
