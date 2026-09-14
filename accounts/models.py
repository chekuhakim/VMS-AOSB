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
