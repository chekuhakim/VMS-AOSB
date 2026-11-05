"""Company registration wizard and company list views."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.company_context import get_active_company_id, set_active_company_id
from accounts.models import Notification
from accounts.notifications import notify_event, staff_recipients
from accounts.roles import PROCUREMENT, is_vendor_user
from audit.models import AuditLog
from audit.services import client_ip, write_audit
from vendors.declarations import DECLARATION_TEXT, DECLARATION_VERSION
from vendors.documents import save_company_pdf
from vendors.forms import (
    Step1ProfileForm,
    Step2SSMForm,
    Step3CIDBForm,
    Step4STForm,
    Step5LHDNForm,
    Step6DeclarationForm,
)
from vendors.models import Company, CompanyDocument
from vendors.rules import REASON_LABELS, evaluate_company_registration

STEP_META = {
    1: {
        "title": "Company Profile Info",
        "short": "Company Profile",
        "hint": (
            "Details must match your SSM records exactly — mismatches are the "
            "top cause of pre-qualification rejection."
        ),
        "form": Step1ProfileForm,
    },
    2: {
        "title": "SSM E-info",
        "short": "SSM E-info",
        "hint": "Upload your SSM document. Expiry is required only for enterprises.",
        "form": Step2SSMForm,
    },
    3: {
        "title": "CIDB Registration",
        "short": "CIDB Registration",
        "hint": "Provide your CIDB registration and certificate, or confirm that this company does not hold one.",
        "form": Step3CIDBForm,
    },
    4: {
        "title": "ST Licensing",
        "short": "ST Licensing",
        "hint": "Only required when your tender scope includes electrical work.",
        "form": Step4STForm,
    },
    5: {
        "title": "LHDN & Bank Details",
        "short": "LHDN & Bank",
        "hint": "Tax number and the bank account Alpha Orange will pay into.",
        "form": Step5LHDNForm,
    },
    6: {
        "title": "Declaration",
        "short": "Declaration",
        "hint": "Review your profile summary, then accept the declaration to submit.",
        "form": Step6DeclarationForm,
    },
}


def _vendor_gate(request: HttpRequest) -> HttpResponse | None:
    if not is_vendor_user(request.user):
        return HttpResponseForbidden("Vendors only.")
    return None


def _owned_company(request: HttpRequest, pk: int) -> Company:
    return get_object_or_404(Company, pk=pk, owner=request.user)


@login_required
def your_company(request: HttpRequest) -> HttpResponse:
    """List companies for the logged-in vendor."""
    blocked = _vendor_gate(request)
    if blocked:
        return blocked
    companies = Company.objects.filter(owner=request.user).order_by("-updated_at")
    return render(
        request,
        "vendors/your_company.html",
        {"page_title": "Your company", "companies": companies},
    )


@login_required
@require_http_methods(["POST"])
def delete_company(request: HttpRequest, pk: int) -> HttpResponse:
    """Delete an owned company after the vendor confirms in the UI."""
    blocked = _vendor_gate(request)
    if blocked:
        return blocked

    company = _owned_company(request, pk)
    # Retention: once submitted, registration / Envelope 1 / bid records must be kept (docs/RETENTION.md)
    if company.registration_status != Company.RegistrationStatus.DRAFT:
        messages.error(request, "Only draft companies can be deleted. Submitted registrations are kept on record.")
        return redirect("vendors:your_company")
    name = company.name
    company_id = company.pk

    with transaction.atomic():
        write_audit(
            category=AuditLog.Category.COMPANY,
            action="company_deleted",
            actor=request.user,
            request=request,
            changes={
                "name": name,
                "registration_status": company.registration_status,
            },
            object_type="Company",
            object_id=company_id,
        )
        company.delete()

    if get_active_company_id(request) == company_id:
        set_active_company_id(request, None)

    messages.success(request, f"“{name}” was deleted.")
    return redirect("vendors:your_company")


@login_required
@require_http_methods(["GET", "POST"])
def register_company(request: HttpRequest) -> HttpResponse:
    """Start a new draft company, then jump to step 1."""
    blocked = _vendor_gate(request)
    if blocked:
        return blocked

    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, "Enter a registered company name to start.")
            return redirect("vendors:register_company")
        if Company.objects.filter(owner=request.user, name__iexact=name).exists():
            messages.error(request, "You already have a company with that name.")
            return redirect("vendors:register_company")

        company = Company.objects.create(
            owner=request.user,
            name=name,
            wizard_step=1,
            registration_status=Company.RegistrationStatus.DRAFT,
        )
        set_active_company_id(request, company.pk)
        write_audit(
            category=AuditLog.Category.COMPANY,
            action="company_draft_created",
            actor=request.user,
            request=request,
            changes={"name": name},
            object_type="Company",
            object_id=company.pk,
        )
        return redirect("vendors:wizard_step", pk=company.pk, step=1)

    return render(
        request,
        "vendors/register_start.html",
        {"page_title": "Register company"},
    )


@login_required
def company_detail(request: HttpRequest, pk: int) -> HttpResponse:
    blocked = _vendor_gate(request)
    if blocked:
        return blocked
    company = _owned_company(request, pk)
    latest_docs = {}
    for d in company.documents.order_by("-version"):
        latest_docs.setdefault(d.doc_type, d)
    reason_messages = [REASON_LABELS.get(code, code) for code in company.evaluation_notes]
    return render(
        request,
        "vendors/company_detail.html",
        {
            "page_title": company.name,
            "company": company,
            "latest_docs": latest_docs,
            "reason_messages": reason_messages,
            "declaration_text": DECLARATION_TEXT,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def wizard_step(request: HttpRequest, pk: int, step: int) -> HttpResponse:
    blocked = _vendor_gate(request)
    if blocked:
        return blocked
    if step not in STEP_META:
        return redirect("vendors:your_company")

    company = _owned_company(request, pk)
    set_active_company_id(request, company.pk)
    meta = STEP_META[step]
    form_class = meta["form"]

    has_pdf = {
        CompanyDocument.DocType.SSM: company.documents.filter(
            doc_type=CompanyDocument.DocType.SSM
        ).exists(),
        CompanyDocument.DocType.CIDB: company.documents.filter(
            doc_type=CompanyDocument.DocType.CIDB
        ).exists(),
        CompanyDocument.DocType.ST: company.documents.filter(
            doc_type=CompanyDocument.DocType.ST
        ).exists(),
    }

    form_kwargs: dict = {"instance": company}
    if step == 2:
        form_kwargs["require_pdf"] = not has_pdf[CompanyDocument.DocType.SSM]
    elif step == 3:
        opted_out = company.no_cidb_registration
        if request.method == "POST":
            opted_out = request.POST.get("no_cidb_registration") in ("on", "true", "True", "1")
        form_kwargs["require_pdf"] = not opted_out and not has_pdf[CompanyDocument.DocType.CIDB]
    elif step == 4:
        electrical = company.includes_electrical_work is True
        if request.method == "POST":
            raw = request.POST.get("includes_electrical_work")
            electrical = raw in ("True", "true", "1", "on")
        form_kwargs["require_pdf"] = electrical and not has_pdf[CompanyDocument.DocType.ST]

    if request.method == "POST":
        form = form_class(request.POST, request.FILES, **form_kwargs)
        if form.is_valid():
            with transaction.atomic():
                company = form.save(commit=False)
                company.wizard_step = max(company.wizard_step, step)
                company.save()
                _maybe_store_pdfs(request, company, step, form)
                write_audit(
                    category=AuditLog.Category.COMPANY,
                    action=f"wizard_step_{step}_saved",
                    actor=request.user,
                    request=request,
                    changes={"step": step, "name": company.name},
                    object_type="Company",
                    object_id=company.pk,
                )

            # Stepper jump (goto_step) or Next → step+1 / final submit
            raw_goto = (request.POST.get("goto_step") or "").strip()
            if raw_goto.isdigit():
                goto = int(raw_goto)
                if goto in STEP_META and goto != step:
                    return redirect("vendors:wizard_step", pk=company.pk, step=goto)
            if step < 6:
                return redirect("vendors:wizard_step", pk=company.pk, step=step + 1)
            return _submit_registration(request, company)
        if _keep_registration_upload(request, company, step, form):
            has_pdf = {
                CompanyDocument.DocType.SSM: company.documents.filter(
                    doc_type=CompanyDocument.DocType.SSM
                ).exists(),
                CompanyDocument.DocType.CIDB: company.documents.filter(
                    doc_type=CompanyDocument.DocType.CIDB
                ).exists(),
                CompanyDocument.DocType.ST: company.documents.filter(
                    doc_type=CompanyDocument.DocType.ST
                ).exists(),
            }
    else:
        form = form_class(**form_kwargs)

    return render(
        request,
        "vendors/wizard_step.html",
        {
            "page_title": f"Step {step}: {meta['title']}",
            "company": company,
            "step": step,
            "steps": STEP_META,
            "form": form,
            "has_pdf": {
                "ssm": has_pdf[CompanyDocument.DocType.SSM],
                "cidb": has_pdf[CompanyDocument.DocType.CIDB],
                "st": has_pdf[CompanyDocument.DocType.ST],
            },
            "declaration_text": DECLARATION_TEXT if step == 6 else "",
            "declaration_version": DECLARATION_VERSION if step == 6 else "",
        },
    )


def _keep_registration_upload(request: HttpRequest, company: Company, step: int, form) -> bool:  # type: ignore[no-untyped-def]
    """Save a valid PDF even when another field on the step failed.

    Returns True when a file was stored, so the page can show it as already on file
    and the file input is no longer required.
    """
    cleaned = form.cleaned_data
    if step == 2 and cleaned.get("ssm_pdf") and "ssm_pdf" not in form.errors:
        save_company_pdf(
            company=company,
            doc_type=CompanyDocument.DocType.SSM,
            uploaded=cleaned["ssm_pdf"],
            user=request.user,
            expiry_date=cleaned.get("ssm_document_expiry")
            if "ssm_document_expiry" not in form.errors
            else None,
        )
        form.fields["ssm_pdf"].required = False
        return True
    if step == 3 and cleaned.get("no_cidb_registration"):
        return False
    if step == 3 and cleaned.get("cidb_pdf") and "cidb_pdf" not in form.errors:
        save_company_pdf(
            company=company,
            doc_type=CompanyDocument.DocType.CIDB,
            uploaded=cleaned["cidb_pdf"],
            user=request.user,
            expiry_date=cleaned.get("cidb_certificate_expiry")
            if "cidb_certificate_expiry" not in form.errors
            else None,
        )
        form.fields["cidb_pdf"].required = False
        return True
    if step == 4 and cleaned.get("st_pdf") and "st_pdf" not in form.errors:
        save_company_pdf(
            company=company,
            doc_type=CompanyDocument.DocType.ST,
            uploaded=cleaned["st_pdf"],
            user=request.user,
            expiry_date=cleaned.get("st_certificate_expiry")
            if "st_certificate_expiry" not in form.errors
            else None,
        )
        form.fields["st_pdf"].required = False
        return True
    return False


def _maybe_store_pdfs(request: HttpRequest, company: Company, step: int, form) -> None:  # type: ignore[no-untyped-def]
    if step == 2 and form.cleaned_data.get("ssm_pdf"):
        save_company_pdf(
            company=company,
            doc_type=CompanyDocument.DocType.SSM,
            uploaded=form.cleaned_data["ssm_pdf"],
            user=request.user,
            expiry_date=form.cleaned_data.get("ssm_document_expiry"),
        )
    elif step == 3 and form.cleaned_data.get("no_cidb_registration"):
        # The declaration replaces the certificate, so an earlier upload must not linger.
        company.documents.filter(doc_type=CompanyDocument.DocType.CIDB).delete()
    elif step == 3 and form.cleaned_data.get("cidb_pdf"):
        save_company_pdf(
            company=company,
            doc_type=CompanyDocument.DocType.CIDB,
            uploaded=form.cleaned_data["cidb_pdf"],
            user=request.user,
            expiry_date=form.cleaned_data.get("cidb_certificate_expiry"),
        )
    elif step == 4 and form.cleaned_data.get("includes_electrical_work") and form.cleaned_data.get("st_pdf"):
        save_company_pdf(
            company=company,
            doc_type=CompanyDocument.DocType.ST,
            uploaded=form.cleaned_data["st_pdf"],
            user=request.user,
            expiry_date=form.cleaned_data.get("st_certificate_expiry"),
        )


def _submit_registration(request: HttpRequest, company: Company) -> HttpResponse:
    """Apply declaration snapshot + rules engine; set approved/rejected."""
    company.declaration_accepted = True
    company.declaration_text_version = DECLARATION_VERSION
    company.declaration_accepted_at = timezone.now()
    company.declaration_ip = client_ip(request)
    company.submitted_at = timezone.now()
    company.wizard_step = 6

    result = evaluate_company_registration(company)
    company.evaluation_notes = result.reason_codes
    company.evaluated_at = timezone.now()
    if result.approved:
        company.registration_status = Company.RegistrationStatus.APPROVED
        messages.success(request, f"{company.name} was approved by the system rules check.")
    else:
        company.registration_status = Company.RegistrationStatus.REJECTED
        messages.warning(
            request,
            f"{company.name} was rejected. Review the reasons and edit your registration.",
        )
    company.save()

    write_audit(
        category=AuditLog.Category.COMPANY,
        action="company_registration_evaluated",
        actor=request.user,
        request=request,
        changes={
            "status": company.registration_status,
            "reasons": result.reason_codes,
            "declaration_version": DECLARATION_VERSION,
        },
        object_type="Company",
        object_id=company.pk,
    )
    if result.approved:
        title = f"New company registered — {company.name}"
        body = "Submitted and approved by the system rules check. It can now start Envelope 1."
        level = Notification.Level.INFO
    else:
        reasons = "; ".join(REASON_LABELS.get(code, code) for code in result.reason_codes)
        title = f"Company registration rejected — {company.name}"
        body = f"Submitted but rejected by the system rules check: {reasons}"
        level = Notification.Level.WARNING
    # One row per company: a resubmission after rejection replaces the earlier alert
    notify_event(
        users=staff_recipients(PROCUREMENT),
        dedupe_key=f"staff-company-{company.pk}-registration",
        title=title,
        body=body,
        level=level,
        link_url=reverse("staff:company_detail", args=[company.pk]),
        link_label="View company",
    )
    return redirect("vendors:company_detail", pk=company.pk)
