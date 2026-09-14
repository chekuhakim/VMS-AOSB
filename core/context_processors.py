"""Shared template context: design tokens, nav, and active company switcher."""

from __future__ import annotations

from typing import Any

from accounts.company_context import ensure_active_company
from accounts.roles import is_staff_user, is_vendor_user
from vendors.models import Company


def design_system(request) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """Expose brand tokens, role-aware nav, and company switcher data."""
    staff = is_staff_user(request.user)
    vendor = is_vendor_user(request.user)

    if staff:
        nav_items = [
            {"label": "Dashboard", "url_name": "core:admin_dashboard", "icon": "home"},
            {"label": "Companies", "url_name": "core:registered_company", "icon": "building"},
            {"label": "Envelope 1", "url_name": "core:submitted_envelope1", "icon": "file"},
            {"label": "Audit log", "url_name": "core:audit_log", "icon": "list"},
            {"label": "Tender", "url_name": "core:tender", "icon": "briefcase"},
        ]
    else:
        nav_items = [
            {"label": "Dashboard", "url_name": "core:dashboard", "icon": "home"},
            {"label": "Register company", "url_name": "vendors:register_company", "icon": "plus"},
            {"label": "Your company", "url_name": "vendors:your_company", "icon": "building"},
            {"label": "Envelope 1", "url_name": "core:envelope1", "icon": "file"},
            {"label": "Document vault", "url_name": "core:document_vault", "icon": "folder"},
            {"label": "Project", "url_name": "core:project", "icon": "briefcase"},
            {"label": "Your bid", "url_name": "core:your_bid", "icon": "tag"},
        ]

    companies: list[Company] = []
    active_company = None
    if vendor:
        companies = list(Company.objects.filter(owner=request.user).order_by("name"))
        active_company = ensure_active_company(request)

    return {
        "brand": {
            "name": "Alpha Orange",
            "legal_name": "Alpha Orange Sdn Bhd",
            "tagline": "Vendor Management System",
            "orange": "#FF6F00",
            "cream": "#FAF7F2",
            "peach": "#FFE8D6",
        },
        "nav_items": nav_items,
        "is_staff_user": staff,
        "is_vendor_user": vendor,
        "vendor_companies": companies,
        "active_company": active_company,
    }
