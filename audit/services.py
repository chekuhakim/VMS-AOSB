"""Helpers to write immutable audit events."""

from __future__ import annotations

from typing import Any

from django.contrib.auth.models import AbstractBaseUser
from django.http import HttpRequest

from .models import AuditLog


def client_ip(request: HttpRequest | None) -> str | None:
    """Best-effort client IP (honours X-Forwarded-For when behind a proxy)."""
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        # First hop is the original client in typical proxy setups
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def write_audit(
    *,
    category: str,
    action: str,
    actor: AbstractBaseUser | None = None,
    request: HttpRequest | None = None,
    changes: dict[str, Any] | None = None,
    object_type: str = "",
    object_id: str | int | None = "",
) -> AuditLog:
    """Append one audit event. Prefer calling this inside successful transactions."""
    label = ""
    if actor is not None and getattr(actor, "is_authenticated", False):
        label = getattr(actor, "get_username", lambda: "")() or str(actor)

    return AuditLog.objects.create(
        actor=actor if actor is not None and getattr(actor, "is_authenticated", False) else None,
        actor_label=label,
        category=category,
        action=action,
        changes=changes or {},
        object_type=object_type,
        object_id=str(object_id) if object_id not in (None, "") else "",
        ip_address=client_ip(request),
    )
