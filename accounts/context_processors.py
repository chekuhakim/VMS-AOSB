"""Auth-related template context."""

from __future__ import annotations

from typing import Any

from django.conf import settings

from accounts.models import Notification
from accounts.notifications import (
    sync_vendor_notifications,
    vendor_notification_sync_is_fresh,
)
from accounts.roles import is_vendor_user


def auth_extras(request) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """Expose Google OAuth flag + notification inbox for authenticated users."""
    ctx: dict[str, Any] = {
        "google_oauth_enabled": bool(
            getattr(settings, "GOOGLE_CLIENT_ID", "")
            and getattr(settings, "GOOGLE_CLIENT_SECRET", "")
        ),
        "user_notifications": [],
        "unread_notification_count": 0,
        "toast_notifications": [],
    }
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return ctx

    if is_vendor_user(user) and not vendor_notification_sync_is_fresh(user.pk):
        sync_vendor_notifications(user)

    # Inbox hides items the vendor closed with × (dismissed_at sticky across sync)
    qs = (
        Notification.objects.filter(user=user, dismissed_at__isnull=True)
        .order_by("-created_at")[:20]
    )
    notifications = list(qs)
    unread = [n for n in notifications if n.read_at is None]
    toast = [n for n in unread if n.dismissed_at is None][:2]

    ctx["user_notifications"] = notifications
    ctx["unread_notification_count"] = len(unread)
    ctx["toast_notifications"] = toast
    return ctx
