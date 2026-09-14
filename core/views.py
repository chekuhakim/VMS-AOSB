"""Core views: shell routes matching the planned URL map (login required)."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    """Vendor homepage at `/`."""
    from vendors.models import Company

    company_count = (
        Company.objects.filter(owner=request.user).count()
        if request.user.is_authenticated
        else 0
    )
    return render(
        request,
        "core/dashboard.html",
        {
            "page_title": "Dashboard",
            "stats": [
                {
                    "label": "Active companies",
                    "value": str(company_count),
                    "hint": "Your registered companies",
                },
                {"label": "Envelope 1 status", "value": "—", "hint": "Phase 3"},
                {"label": "Open projects", "value": "—", "hint": "Phase 5"},
            ],
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
    return _placeholder(
        request,
        "Envelope 1",
        "Envelope 1 submission wizard arrives in Phase 3.",
    )


@login_required
def document_vault(request: HttpRequest) -> HttpResponse:
    return _placeholder(
        request,
        "Document vault",
        "All uploaded PDFs will be listed here in Phase 3.",
    )


@login_required
def project(request: HttpRequest) -> HttpResponse:
    return _placeholder(
        request,
        "Project",
        "Vendor project / tender browse unlocks in Phase 5 after Envelope 1 approval.",
    )


@login_required
def your_bid(request: HttpRequest) -> HttpResponse:
    return _placeholder(
        request,
        "Your bid",
        "RFQ submission list and drill-down arrive in Phase 5.",
    )


@login_required
def admin_dashboard(request: HttpRequest) -> HttpResponse:
    return _placeholder(
        request,
        "Admin dashboard",
        "Vendor onboarding pipeline and live audit summary arrive in Phase 4.",
    )


@login_required
def registered_company(request: HttpRequest) -> HttpResponse:
    return _placeholder(
        request,
        "Registered company",
        "Staff company registry arrives in Phase 4.",
    )


@login_required
def submitted_envelope1(request: HttpRequest) -> HttpResponse:
    return _placeholder(
        request,
        "Submitted Envelope 1",
        "Searchable Envelope 1 table arrives in Phase 4.",
    )


@login_required
def qualification_checklist(request: HttpRequest) -> HttpResponse:
    return _placeholder(
        request,
        "Qualification checklist",
        "Procurement per-item pass/fail UI arrives in Phase 4.",
    )


@login_required
def approval(request: HttpRequest) -> HttpResponse:
    return _placeholder(
        request,
        "Approval",
        "Director approve/reject queue arrives in Phase 4.",
    )


@login_required
def audit_log(request: HttpRequest) -> HttpResponse:
    return _placeholder(
        request,
        "Audit log",
        "Append-only audit trail UI arrives in Phase 4 (model is ready now).",
    )


@login_required
def tender(request: HttpRequest) -> HttpResponse:
    return _placeholder(
        request,
        "Tender",
        "Admin project / RFQ management arrives in Phase 5.",
    )
