"""Active company session helpers for the header company switcher.

Vendors can own multiple companies; Envelope 1 / vault / projects are scoped
to the session's active_company_id (plan decision 3A).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.http import HttpRequest

if TYPE_CHECKING:
    from vendors.models import Company

SESSION_KEY = "active_company_id"


def get_active_company_id(request: HttpRequest) -> int | None:
    """Return the active company PK from the session, if set."""
    raw = request.session.get(SESSION_KEY)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def set_active_company_id(request: HttpRequest, company_id: int | None) -> None:
    """Persist or clear the active company in the session."""
    if company_id is None:
        request.session.pop(SESSION_KEY, None)
    else:
        request.session[SESSION_KEY] = int(company_id)


def get_active_company(request: HttpRequest) -> Company | None:
    """Resolve the active company for the current user, or None.

    Clears a stale session id if the company is missing or not owned by the user.
    """
    from vendors.models import Company

    company_id = get_active_company_id(request)
    if company_id is None or not request.user.is_authenticated:
        return None

    company = (
        Company.objects.filter(pk=company_id, owner=request.user)
        .only("id", "name", "registration_status")
        .first()
    )
    if company is None:
        # Stale or unauthorized id — drop it so the UI does not lie
        set_active_company_id(request, None)
        return None
    return company


def ensure_active_company(request: HttpRequest) -> Company | None:
    """If none is selected, auto-select the vendor's first company."""
    active = get_active_company(request)
    if active is not None:
        return active
    if not request.user.is_authenticated:
        return None

    from vendors.models import Company

    first = Company.objects.filter(owner=request.user).order_by("name").first()
    if first is not None:
        set_active_company_id(request, first.pk)
    return first
