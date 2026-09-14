"""Auth-related template context."""

from __future__ import annotations

from typing import Any

from django.conf import settings


def auth_extras(request) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """Expose whether Google OAuth is configured (hide button if not)."""
    return {
        "google_oauth_enabled": bool(
            getattr(settings, "GOOGLE_CLIENT_ID", "")
            and getattr(settings, "GOOGLE_CLIENT_SECRET", "")
        ),
    }
