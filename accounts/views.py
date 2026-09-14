"""Views for session company switching and auth escape hatches."""

from __future__ import annotations

from allauth.account.internal.flows.email_verification_by_code import (
    EmailVerificationProcess,
)
from allauth.account.internal.stagekit import clear_login
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_GET, require_POST

from accounts.company_context import set_active_company_id
from audit.models import AuditLog
from audit.services import write_audit
from vendors.models import Company

# Only allow these destinations after abandoning email verification
_ABORT_ALLOWED_NEXT = {
    "signup": "/register/",
    "login": "/login/",
}


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
    next_url = request.POST.get("next") or "/"

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
