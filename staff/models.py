"""Staff-side evaluation records for Envelope 1 document checklist."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from envelope1.models import Envelope1Item, Envelope1Submission


class Envelope1ItemEvaluation(models.Model):
    """Procurement pass/fail for one Envelope 1 checklist item (keyed by Envelope1Item)."""

    class Result(models.TextChoices):
        PENDING = "pending", "Pending"
        PASS = "pass", "Pass"
        FAIL = "fail", "Fail"

    submission = models.ForeignKey(
        Envelope1Submission,
        on_delete=models.CASCADE,
        related_name="item_evaluations",
    )
    doc_type = models.CharField(
        max_length=40,
        choices=Envelope1Item.choices,
        db_index=True,
    )
    result = models.CharField(
        max_length=20,
        choices=Result.choices,
        default=Result.PENDING,
        db_index=True,
    )
    note = models.TextField(blank=True)
    evaluated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="envelope1_item_evaluations",
    )
    evaluated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["doc_type"]
        verbose_name = "Envelope 1 item evaluation"
        verbose_name_plural = "Envelope 1 item evaluations"
        constraints = [
            models.UniqueConstraint(
                fields=["submission", "doc_type"],
                name="uniq_e1_item_eval_per_submission",
            ),
        ]

    def __str__(self) -> str:
        return f"E1 {self.submission_id} · {self.doc_type} · {self.result}"
