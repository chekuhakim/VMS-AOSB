"""Account-side profiles linking Django users to the VMS domain."""

from __future__ import annotations

from django.conf import settings
from django.db import models


class VendorProfile(models.Model):
    """One-to-one profile for vendor (supplier) accounts."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="vendor_profile",
    )
    # Display name shown in audit logs / UI; may differ from username
    display_name = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "vendor profile"
        verbose_name_plural = "vendor profiles"

    def __str__(self) -> str:
        return self.display_name or self.user.get_username()


class Notification(models.Model):
    """In-app vendor notification — toast for 7s + inbox via header bell."""

    class Level(models.TextChoices):
        INFO = "info", "Info"
        SUCCESS = "success", "Success"
        WARNING = "warning", "Warning"
        DANGER = "danger", "Danger"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    level = models.CharField(
        max_length=20,
        choices=Level.choices,
        default=Level.INFO,
    )
    link_url = models.CharField(max_length=300, blank=True)
    link_label = models.CharField(max_length=80, blank=True)
    # Stable key so sync jobs upsert instead of flooding the inbox
    dedupe_key = models.CharField(max_length=120, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    dismissed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "notification"
        verbose_name_plural = "notifications"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "dedupe_key"],
                condition=~models.Q(dedupe_key=""),
                name="uniq_notification_dedupe_per_user",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}: {self.title}"

    @property
    def is_unread(self) -> bool:
        return self.read_at is None
