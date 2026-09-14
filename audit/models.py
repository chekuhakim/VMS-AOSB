"""Immutable audit trail for ISO 9001 evidence of who changed what, when."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Append-only event log. Rows must never be updated or deleted via the UI."""

    class Category(models.TextChoices):
        AUTH = "auth", "Auth"
        COMPANY = "company", "Company"
        ENVELOPE1 = "envelope1", "Envelope 1"
        DOCUMENT = "document", "Document"
        EVALUATION = "evaluation", "Evaluation"
        APPROVAL = "approval", "Approval"
        PROJECT = "project", "Project"
        RFQ = "rfq", "RFQ"
        SYSTEM = "system", "System"

    # Public log id shown in admin audit UI (stable, not the PK)
    log_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    actor_label = models.CharField(
        max_length=150,
        blank=True,
        help_text="Cached display label if the user is later deleted.",
    )
    category = models.CharField(max_length=32, choices=Category.choices, db_index=True)
    action = models.CharField(max_length=100)
    # Human-readable summary of what changed (field diffs, status transitions)
    changes = models.JSONField(default=dict, blank=True)
    object_type = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "audit log"
        verbose_name_plural = "audit logs"

    def __str__(self) -> str:
        return f"{self.log_id} · {self.action}"

    def save(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        # Compliance: existing audit rows are immutable
        if self.pk is not None:
            raise ValueError("AuditLog rows are append-only and cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs) -> tuple[int, dict[str, int]]:  # type: ignore[no-untyped-def]
        raise ValueError("AuditLog rows are append-only and cannot be deleted.")
