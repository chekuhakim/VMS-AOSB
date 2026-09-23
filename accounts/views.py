"""Views for session company switching and auth escape hatches."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from allauth.account.internal.flows.email_verification_by_code import (
    EmailVerificationProcess,
)
from allauth.account.internal.stagekit import clear_login
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from accounts.company_context import set_active_company_id
from accounts.models import Notification
from audit.models import AuditLog
from audit.services import write_audit
from vendors.models import Company

# Only allow these destinations after abandoning email verification
_ABORT_ALLOWED_NEXT = {
    "signup": "/register/",
    "login": "/login/",
}

# Paths that embed a company-/submission-specific id — unsafe to reuse after switch
_SCOPED_NEXT_REDIRECTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^/envelope-1/\d+/"), "envelope1:home"),
    (re.compile(r"^/register-company/\d+/"), "vendors:your_company"),
    (re.compile(r"^/your-company/\d+"), "vendors:your_company"),
]


def _next_after_company_switch(next_url: str) -> str:
    """Drop object-scoped return URLs so the new active company is not 404'd."""
    parsed = urlparse(next_url or "/")
    # Reject absolute external URLs (open-redirect guard)
    if parsed.scheme or parsed.netloc:
        return "/"
    path = parsed.path or "/"
    for pattern, route_name in _SCOPED_NEXT_REDIRECTS:
        if pattern.match(path):
            return reverse(route_name)
    return path


@require_GET
def abort_email_verification(request: HttpRequest) -> HttpResponse:
    """Clear pending email-code verification so the user can leave confirm-email.

    allauth keeps a login stage in the session after signup. Visiting /register/
    or /login/ then redirects back to confirm-email — which feels "stuck".
    This view aborts that stage first, then redirects to sign up or sign in.
    """
    process = EmailVerificationProcess.resume(request)
    if process is not None:
        process.abort()
    else:
        clear_login(request)

    dest = request.GET.get("next", "signup")
    return redirect(_ABORT_ALLOWED_NEXT.get(dest, "/register/"))


@login_required
@require_POST
def switch_company(request: HttpRequest) -> HttpResponse:
    """Set the active company in session after verifying ownership."""
    company_id = request.POST.get("company_id")
    next_url = _next_after_company_switch(request.POST.get("next") or "/")

    company = get_object_or_404(Company, pk=company_id, owner=request.user)
    set_active_company_id(request, company.pk)

    write_audit(
        category=AuditLog.Category.COMPANY,
        action="switch_active_company",
        actor=request.user,
        request=request,
        changes={"active_company_id": company.pk, "name": company.name},
        object_type="Company",
        object_id=company.pk,
    )
    messages.success(request, f"Switched to {company.name}.")
    return redirect(next_url)


@login_required
@require_POST
def notification_dismiss(request: HttpRequest, pk: int) -> HttpResponse:
    """Dismiss toast and hide from the inbox; sync will not resurrect it."""
    note = get_object_or_404(Notification, pk=pk, user=request.user)
    now = timezone.now()
    note.dismissed_at = now
    if note.read_at is None:
        note.read_at = now
    note.save(update_fields=["dismissed_at", "read_at"])
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True})
    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or "/"
    return redirect(next_url)


@login_required
@require_POST
def notification_read(request: HttpRequest, pk: int) -> HttpResponse:
    note = get_object_or_404(Notification, pk=pk, user=request.user)
    if note.read_at is None:
        note.read_at = timezone.now()
        note.save(update_fields=["read_at"])
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True})
    if note.link_url:
        return redirect(note.link_url)
    return redirect(request.POST.get("next") or "/")


@login_required
@require_POST
def notification_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Remove from the inbox (soft). Sync must not resurrect dismissed alerts."""
    note = get_object_or_404(Notification, pk=pk, user=request.user)
    now = timezone.now()
    note.dismissed_at = now
    if note.read_at is None:
        note.read_at = now
    note.save(update_fields=["dismissed_at", "read_at"])
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True})
    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or "/"
    return redirect(next_url)


@login_required
@require_POST
def notifications_mark_all_read(request: HttpRequest) -> HttpResponse:
    Notification.objects.filter(user=request.user, read_at__isnull=True).update(
        read_at=timezone.now()
    )
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True})
    return redirect(request.POST.get("next") or "/")
