"""Core views: shell routes matching the planned URL map (login required)."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from accounts.company_context import ensure_active_company
from accounts.roles import is_vendor_user
from core.dashboard import (
    build_expiry_warnings,
    build_progress_stages,
    build_quick_actions,
)
from envelope1.services import latest_submission


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    """Vendor homepage at `/`. Staff land on the admin pipeline dashboard."""
    from accounts.roles import is_staff_user
    from vendors.models import Company

    if is_staff_user(request.user):
        return redirect("staff:admin_dashboard")

    company = None
    if is_vendor_user(request.user):
        company = ensure_active_company(request)
        if company is None:
            company = (
                Company.objects.filter(owner=request.user, is_hidden=False)
                .order_by("-updated_at")
                .first()
            )

    return render(
        request,
        "core/dashboard.html",
        {
            "page_title": "Dashboard",
            "dashboard_company": company,
            "progress_stages": build_progress_stages(company),
            "quick_actions": build_quick_actions(company),
            "expiry_warnings": build_expiry_warnings(company),
        },
    )


def _placeholder(request: HttpRequest, page_title: str, message: str) -> HttpResponse:
    return render(
        request,
        "core/placeholder.html",
        {"page_title": page_title, "message": message},
    )


@login_required
def envelope1(request: HttpRequest) -> HttpResponse:
    return redirect("envelope1:home")


@login_required
def document_vault(request: HttpRequest) -> HttpResponse:
    return redirect("envelope1:vault")


@login_required
def admin_dashboard(request: HttpRequest) -> HttpResponse:
    return redirect("staff:admin_dashboard")


@login_required
def registered_company(request: HttpRequest) -> HttpResponse:
    return redirect("staff:company_list")


@login_required
def submitted_envelope1(request: HttpRequest) -> HttpResponse:
    return redirect("staff:envelope1_list")


@login_required
def qualification_checklist(request: HttpRequest) -> HttpResponse:
    return redirect("staff:qualification_checklist")


@login_required
def approval(request: HttpRequest) -> HttpResponse:
    return redirect("staff:approval_queue")


@login_required
def audit_log(request: HttpRequest) -> HttpResponse:
    return redirect("staff:audit_log")
