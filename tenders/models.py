"""Tender projects, their RFQ work packages, sealed vendor quotations, and awards."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from vendors.models import Company


class Project(models.Model):
    """A tender published by Procurement; vendors quote per RFQ until closing_at."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        OPEN = "open", "Open"
        CANCELLED = "cancelled", "Cancelled"

    reference = models.CharField(max_length=30, unique=True, null=True, blank=True)
    title = models.CharField(max_length=255)
    scope = models.TextField()
    start_date = models.DateField()
    end_date = models.DateField()
    closing_at = models.DateTimeField(help_text="No quotations accepted after this time.")
    min_cidb_grade = models.CharField(max_length=5, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_projects",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_projects",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.reference or 'Draft'} · {self.title}"

    @property
    def accepting_quotations(self) -> bool:
        return self.status == self.Status.OPEN and timezone.now() < self.closing_at

    @property
    def is_sealed(self) -> bool:
        # Compliance: sealed bidding — prices/files hidden from staff until closing
        return timezone.now() < self.closing_at

    @property
    def is_editable(self) -> bool:
        return self.status == self.Status.DRAFT

    @property
    def can_add_rfq(self) -> bool:
        """New work packages are allowed in draft, and on an open project until closing."""
        return self.is_editable or self.accepting_quotations

    @property
    def display_status(self) -> str:
        """Lifecycle label: Draft → Open → Closed → Awarded, or Cancelled."""
        if self.status != self.Status.OPEN:
            return self.get_status_display()
        if self.accepting_quotations:
            return "Open"
        rfqs = list(self.rfqs.all())
        if rfqs and all(rfq.approved_award is not None for rfq in rfqs):
            return "Awarded"
        return "Closed"


class RFQ(models.Model):
    """One work package inside a project; vendors submit one quotation per RFQ."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="rfqs")
    code = models.CharField(max_length=20)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    unit = models.CharField(max_length=30, blank=True)
    document_path = models.CharField(max_length=500, blank=True)
    document_backend = models.CharField(max_length=20, blank=True)
    document_filename = models.CharField(max_length=255, blank=True)
    position = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "RFQ"
        verbose_name_plural = "RFQs"
        constraints = [
            models.UniqueConstraint(fields=["project", "code"], name="uniq_rfq_code_per_project"),
        ]

    def __str__(self) -> str:
        return f"{self.code} · {self.title}"

    @property
    def approved_award(self) -> TenderAward | None:
        for award in self.awards.all():
            if award.status == TenderAward.Status.APPROVED:
                return award
        return None

    @property
    def active_award(self) -> TenderAward | None:
        for award in self.awards.all():
            if award.status in TenderAward.ACTIVE_STATUSES:
                return award
        return None


class Quotation(models.Model):
    """A vendor's sealed price for one RFQ. Editable/withdrawable until closing."""

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        WITHDRAWN = "withdrawn", "Withdrawn"

    rfq = models.ForeignKey(RFQ, on_delete=models.CASCADE, related_name="quotations")
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="quotations")
    total_price = models.DecimalField(max_digits=14, decimal_places=2)
    # Nullable only for quotations made before this field existed; the form always requires it
    handover_date = models.DateField(null=True, blank=True)
    remarks = models.TextField(blank=True)
    document_path = models.CharField(max_length=500)
    document_backend = models.CharField(max_length=20)
    document_filename = models.CharField(max_length=255)
    version = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.SUBMITTED, db_index=True
    )
    # Compliance: exact declaration wording version + time + IP the vendor accepted
    declaration_version = models.CharField(max_length=30)
    declaration_text = models.TextField()
    declaration_accepted_at = models.DateTimeField()
    declaration_ip = models.GenericIPAddressField(null=True, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_quotations",
    )
    submitted_at = models.DateTimeField()
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["total_price", "submitted_at"]
        constraints = [
            models.UniqueConstraint(fields=["rfq", "company"], name="uniq_quotation_per_rfq_company"),
        ]

    def __str__(self) -> str:
        return f"{self.company} → {self.rfq}"


class TenderAward(models.Model):
    """Procurement recommends a winning quotation; the Director approves or rejects."""

    class Status(models.TextChoices):
        PENDING_DIRECTOR = "pending_director", "Pending director approval"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    ACTIVE_STATUSES = (Status.PENDING_DIRECTOR, Status.APPROVED)

    rfq = models.ForeignKey(RFQ, on_delete=models.CASCADE, related_name="awards")
    quotation = models.ForeignKey(Quotation, on_delete=models.PROTECT, related_name="awards")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING_DIRECTOR, db_index=True
    )
    recommendation_note = models.TextField()
    recommended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recommended_awards",
    )
    recommended_at = models.DateTimeField(default=timezone.now)
    decision_note = models.TextField(blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="decided_awards",
    )
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-recommended_at"]
        constraints = [
            # One live recommendation/award per RFQ; rejected ones stay as history
            models.UniqueConstraint(
                fields=["rfq"],
                condition=Q(status__in=["pending_director", "approved"]),
                name="uniq_active_award_per_rfq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.rfq} → {self.quotation.company} ({self.get_status_display()})"
