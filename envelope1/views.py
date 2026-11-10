"""Vendor Envelope 1 wizard, MSA download, withdrawal, and vault listings."""

from __future__ import annotations

import mimetypes
from urllib.parse import quote

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from accounts.company_context import ensure_active_company, set_active_company_id
from accounts.models import Notification
from accounts.notifications import notify_event, staff_recipients
from accounts.roles import PROCUREMENT, is_vendor_user
from audit.models import AuditLog
from audit.services import write_audit
from documents.storage import open_stored
from envelope1.checklist import ITEM_HELP, LEAD_TIME_DESCRIPTION, STEP_ITEMS, STEP_META
from envelope1.forms import (
    BaseRowFormSet,
    QuestionnaireStepForm,
    Step3FinancialsForm,
    Step4LogisticsForm,
    Step5QualityForm,
    Step6TrackRecordForm,
    WithdrawalRequestForm,
    build_row_formset,
)
from envelope1.models import (
    Envelope1Document,
    Envelope1Item,
    Envelope1Submission,
    WithdrawalRequest,
)
from envelope1.msa import build_no_advance_pdf, no_advance_download_filename
from envelope1.services import (
    can_access_envelope1,
    get_or_create_draft,
    latest_docs_map,
    latest_submission,
    missing_items,
)

STEP_FORMS: dict[int, type[QuestionnaireStepForm]] = {
    1: Step3FinancialsForm,
    2: Step4LogisticsForm,
    3: Step5QualityForm,
    4: Step6TrackRecordForm,
}
STEP_TABLES: dict[int, str] = {
    1: "financial_statements",
    2: "primary_suppliers",
    4: "past_projects",
}
STEP_TABLE_ITEMS: dict[int, str] = {
    1: Envelope1Item.FINANCIAL_STATEMENTS,
    2: Envelope1Item.PRIMARY_SUPPLIERS,
    4: Envelope1Item.PAST_PROJECTS,
}
from vendors.models import Company, CompanyDocument


def _correction_failed_items(submission: Envelope1Submission) -> dict[str, dict]:
    from staff.services import failed_item_details

    return {row["item"]: row for row in failed_item_details(submission)}


def _staff_submitted_key(submission: Envelope1Submission) -> str:
    return f"staff-e1-{submission.pk}-submitted"


def _vendor_company(request: HttpRequest) -> Company | HttpResponse:
    if not is_vendor_user(request.user):
        return HttpResponseForbidden("Vendors only.")
    company = ensure_active_company(request)
    if company is None:
        messages.warning(request, "Register and get a company approved before Envelope 1.")
        return redirect("vendors:register_company")
    if not can_access_envelope1(company):
        messages.warning(
            request,
            "Envelope 1 unlocks after your company registration is approved.",
        )
        return redirect("vendors:company_detail", pk=company.pk)
    set_active_company_id(request, company.pk)
    return company


@login_required
def envelope1_home(request: HttpRequest) -> HttpResponse:
    """Open the company's single Envelope 1 form immediately (no start screen)."""
    company = _vendor_company(request)
    if not isinstance(company, Company):
        return company

    submission, created = get_or_create_draft(company)
    if created:
        write_audit(
            category=AuditLog.Category.COMPANY,
            action="envelope1_draft_opened",
            actor=request.user,
            request=request,
            changes={"cycle": submission.cycle_number, "company_id": company.pk},
            object_type="Envelope1Submission",
            object_id=submission.pk,
        )

    if submission.is_returned_for_correction:
        return redirect("envelope1:corrections", pk=submission.pk)
    step = submission.wizard_step if submission.wizard_step in STEP_META else 1
    return redirect("envelope1:wizard", pk=submission.pk, step=step)


@login_required
@require_http_methods(["POST"])
def envelope1_start(request: HttpRequest) -> HttpResponse:
    """Legacy start URL — same as home (one Envelope 1 per company)."""
    return envelope1_home(request)


@login_required
def envelope1_corrections(request: HttpRequest, pk: int) -> HttpResponse:
    """Vendor-facing list of items Procurement returned for correction."""
    company = _vendor_company(request)
    if not isinstance(company, Company):
        return company
    submission = Envelope1Submission.objects.filter(pk=pk, company=company).first()
    if submission is None:
        return redirect("envelope1:home")
    if not submission.is_returned_for_correction:
        return redirect("envelope1:home")

    from staff.services import failed_item_details

    failed = failed_item_details(submission)
    for row in failed:
        meta = STEP_META.get(row["step"] or 0, {})
        row["step_title"] = meta.get("title", "")
    return render(
        request,
        "envelope1/corrections.html",
        {
            "page_title": "Envelope 1 corrections",
            "company": company,
            "submission": submission,
            "failed_items": failed,
            "editable": True,
        },
    )


@login_required
@require_http_methods(["POST"])
def envelope1_resubmit_correction(request: HttpRequest, pk: int) -> HttpResponse:
    company = _vendor_company(request)
    if not isinstance(company, Company):
        return company
    submission = Envelope1Submission.objects.filter(pk=pk, company=company).first()
    if submission is None:
        return redirect("envelope1:home")
    if not submission.is_returned_for_correction:
        messages.error(request, "This Envelope 1 is not waiting for corrections.")
        return redirect("envelope1:home")

    from staff.services import resubmit_correction

    try:
        resubmit_correction(submission=submission, actor=request.user, request=request)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("envelope1:corrections", pk=submission.pk)
    messages.success(
        request, "Corrections sent back to Procurement. They will re-check the failed items."
    )
    return redirect("envelope1:home")


@login_required
@require_http_methods(["GET", "POST"])
def envelope1_wizard(request: HttpRequest, pk: int, step: int) -> HttpResponse:
    company = _vendor_company(request)
    if not isinstance(company, Company):
        return company
    if step not in STEP_META:
        return redirect("envelope1:home")

    # Submission pk is per-company; after a company switch the old URL must not 404
    submission = Envelope1Submission.objects.filter(pk=pk, company=company).first()
    if submission is None:
        return redirect("envelope1:home")
    docs = latest_docs_map(submission)
    correction_mode = submission.is_returned_for_correction
    correction_failed = _correction_failed_items(submission) if correction_mode else {}
    correction_items = set(correction_failed)
    correction_steps = {
        row["step"] for row in correction_failed.values() if row["step"] is not None
    }
    if correction_mode and step not in correction_steps:
        messages.info(request, "Only the items returned for correction can be changed.")
        return redirect("envelope1:corrections", pk=submission.pk)
    editable = submission.is_editable or (correction_mode and step in correction_steps)

    if request.method == "POST" and not editable:
        if submission.can_reopen:
            messages.error(request, "This Envelope 1 is submitted. Click Edit to reopen it first.")
        elif correction_mode:
            messages.error(request, "Only the items returned for correction can be changed.")
            return redirect("envelope1:corrections", pk=submission.pk)
        else:
            messages.error(request, "This Envelope 1 cycle is locked. Request a withdrawal to edit.")
        return redirect("envelope1:wizard", pk=submission.pk, step=step)

    form: forms.BaseForm | None = None
    row_formset: BaseRowFormSet | None = None

    if step in STEP_FORMS:
        form_cls = STEP_FORMS[step]
        table_kind = STEP_TABLES.get(step)
        table_item = STEP_TABLE_ITEMS.get(step)
        table_allowed = not correction_mode or table_item in correction_items
        data = request.POST if request.method == "POST" else None
        files = request.FILES if request.method == "POST" else None
        form = form_cls(
            data,
            files,
            submission=submission,
            existing=docs,
            allowed_items=correction_items if correction_mode else None,
        )
        if table_kind and table_allowed:
            row_formset = build_row_formset(table_kind, submission, data, files)
        if request.method == "POST":
            # 4.1 table only matters when the vendor answers "Yes"
            table_in_use = table_allowed and row_formset is not None and (
                table_kind != "past_projects" or request.POST.get("has_past_projects") == "yes"
            )
            form_ok = form.is_valid()
            table_ok = row_formset.is_valid() if table_in_use else True
            if form_ok and table_ok:
                with transaction.atomic():
                    form.save(user=request.user)
                    if table_in_use:
                        row_formset.save_rows(submission=submission, user=request.user)
                    submission.wizard_step = max(submission.wizard_step, step)
                    submission.save(update_fields=["wizard_step", "updated_at"])
                    write_audit(
                        category=AuditLog.Category.COMPANY,
                        action=f"envelope1_step_{step}_saved",
                        actor=request.user,
                        request=request,
                        changes={"cycle": submission.cycle_number},
                        object_type="Envelope1Submission",
                        object_id=submission.pk,
                    )

                if correction_mode:
                    messages.success(request, "Correction saved. Resubmit when you are done.")
                    return redirect("envelope1:corrections", pk=submission.pk)
                if step < 4:
                    messages.success(request, f"Step {step} saved.")
                    return redirect("envelope1:wizard", pk=submission.pk, step=step + 1)

                # Final step — submit only when every checklist item is answered
                missing = missing_items(submission)
                if missing:
                    labels = dict(Envelope1Item.choices)
                    pending = [labels[item] for item in missing]
                    messages.error(
                        request,
                        "Complete these items before submitting: " + "; ".join(pending) + ".",
                    )
                    return redirect("envelope1:wizard", pk=submission.pk, step=4)

                submission.status = Envelope1Submission.Status.PENDING_EVALUATION
                submission.submitted_at = timezone.now()
                submission.save(
                    update_fields=["status", "submitted_at", "wizard_step", "updated_at"]
                )
                write_audit(
                    category=AuditLog.Category.COMPANY,
                    action="envelope1_submitted",
                    actor=request.user,
                    request=request,
                    changes={
                        "cycle": submission.cycle_number,
                        "status": submission.status,
                    },
                    object_type="Envelope1Submission",
                    object_id=submission.pk,
                )
                notify_event(
                    users=staff_recipients(PROCUREMENT),
                    dedupe_key=_staff_submitted_key(submission),
                    title=f"New Envelope 1 submitted — {company.name}",
                    body=f"Cycle {submission.cycle_number} is waiting for procurement evaluation.",
                    link_url=reverse("staff:envelope1_detail", args=[submission.pk]),
                    link_label="Review Envelope 1",
                )
                return redirect("envelope1:wizard", pk=submission.pk, step=6)
            # Keep PDFs that were valid. The browser cannot restore a file input
            # after this page is shown again with the other errors.
            form.persist_uploaded_files(user=request.user)
            if table_in_use:
                row_formset.persist_uploaded_files(submission=submission, user=request.user)
        if request.method == "POST":
            messages.error(request, "Please fix the highlighted fields.")

    return render(
        request,
        "envelope1/wizard_step.html",
        {
            "page_title": f"Envelope 1 · Step {step}",
            "company": company,
            "submission": submission,
            "step": step,
            "steps": STEP_META,
            "form": form,
            "row_formset": row_formset,
            "docs": docs,
            "item_help": {str(key.value): text for key, text in ITEM_HELP.items()},
            "item_labels": dict(Envelope1Item.choices),
            "lead_time_description": LEAD_TIME_DESCRIPTION,
            "editable": editable,
            "correction_mode": correction_mode,
            "correction_failed": correction_failed,
            "table_locked": bool(
                correction_mode
                and STEP_TABLE_ITEMS.get(step)
                and STEP_TABLE_ITEMS[step] not in correction_items
            ),
            "pending_withdrawal": submission.withdrawal_requests.filter(
                status=WithdrawalRequest.Status.PENDING
            ).first()
            if not editable
            else None,
        },
    )


@login_required
@require_http_methods(["POST"])
def reopen_submission(request: HttpRequest, pk: int) -> HttpResponse:
    """Pull a submitted (not yet locked) Envelope 1 back to Draft so the vendor can edit it."""
    company = _vendor_company(request)
    if not isinstance(company, Company):
        return company
    submission = Envelope1Submission.objects.filter(pk=pk, company=company).first()
    if submission is None:
        return redirect("envelope1:home")

    with transaction.atomic():
        # Row lock: Procurement may be locking this pack at the same moment
        submission = Envelope1Submission.objects.select_for_update().get(pk=submission.pk)
        if not submission.can_reopen:
            messages.error(
                request,
                "Procurement has already started checking this Envelope 1. "
                "Request a withdrawal to make changes.",
            )
            return redirect("envelope1:wizard", pk=submission.pk, step=submission.wizard_step or 1)
        previous_status = submission.status
        submission.status = Envelope1Submission.Status.DRAFT
        submission.submitted_at = None
        submission.save(update_fields=["status", "submitted_at", "updated_at"])
        write_audit(
            category=AuditLog.Category.COMPANY,
            action="envelope1_reopened",
            actor=request.user,
            request=request,
            changes={"cycle": submission.cycle_number, "from_status": previous_status},
            object_type="Envelope1Submission",
            object_id=submission.pk,
        )
        # Pack left the procurement queue — drop the stale "new submission" alert
        Notification.objects.filter(dedupe_key=_staff_submitted_key(submission)).delete()
    messages.info(request, "Envelope 1 is back in draft. Submit it again when your changes are done.")
    return redirect("envelope1:wizard", pk=submission.pk, step=1)


@login_required
def download_no_advance_declaration(request: HttpRequest, pk: int) -> HttpResponse:
    """1.4 template: pre-filled declaration the vendor signs and uploads back."""
    company = _vendor_company(request)
    if not isinstance(company, Company):
        return company
    submission = Envelope1Submission.objects.filter(pk=pk, company=company).first()
    if submission is None:
        return redirect("envelope1:home")
    filename = no_advance_download_filename(submission.company)
    response = HttpResponse(
        build_no_advance_pdf(submission.company), content_type="application/pdf"
    )
    response["Content-Disposition"] = (
        f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}"
    )
    write_audit(
        category=AuditLog.Category.DOCUMENT,
        action="envelope1_no_advance_template_downloaded",
        actor=request.user,
        request=request,
        changes={"cycle": submission.cycle_number},
        object_type="Envelope1Submission",
        object_id=submission.pk,
    )
    return response


@login_required
@require_http_methods(["GET", "POST"])
def withdrawal_request(request: HttpRequest, pk: int) -> HttpResponse:
    company = _vendor_company(request)
    if not isinstance(company, Company):
        return company
    submission = Envelope1Submission.objects.filter(pk=pk, company=company).first()
    if submission is None:
        return redirect("envelope1:home")
    if not submission.is_locked:
        messages.info(request, "This Envelope 1 is not locked — you can edit it directly.")
        return redirect("envelope1:wizard", pk=submission.pk, step=1)

    pending = submission.withdrawal_requests.filter(
        status=WithdrawalRequest.Status.PENDING
    ).first()
    if request.method == "POST":
        if pending:
            messages.warning(request, "A withdrawal request is already pending review.")
            return redirect("envelope1:withdrawal", pk=pk)
        form = WithdrawalRequestForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.submission = submission
            obj.requested_by = request.user
            obj.save()
            write_audit(
                category=AuditLog.Category.COMPANY,
                action="envelope1_withdrawal_requested",
                actor=request.user,
                request=request,
                changes={"cycle": submission.cycle_number},
                object_type="WithdrawalRequest",
                object_id=obj.pk,
            )
            notify_event(
                users=staff_recipients(PROCUREMENT),
                dedupe_key=f"staff-withdrawal-{obj.pk}",
                title=f"Withdrawal requested — {company.name}",
                body=f"Reason: {obj.reason}" if obj.reason else "The vendor asked to unlock their Envelope 1.",
                link_url=reverse("staff:withdrawal_list"),
                link_label="Review withdrawals",
            )
            messages.success(
                request,
                "Withdrawal request submitted. Procurement will review it (Phase 4).",
            )
            return redirect("envelope1:home")
    else:
        form = WithdrawalRequestForm()

    return render(
        request,
        "envelope1/withdrawal.html",
        {
            "page_title": "Withdrawal request",
            "company": company,
            "submission": submission,
            "form": form,
            "pending": pending,
        },
    )


def _pdf_response(*, path: str, backend: str, filename: str) -> HttpResponse:
    """Stream a stored document inline so the browser can display it."""
    data = open_stored(path=path, backend=backend)
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    response = HttpResponse(data, content_type=content_type)
    safe_name = filename.replace('"', "")
    response["Content-Disposition"] = f'inline; filename="{safe_name}"'
    response["Content-Length"] = str(len(data))
    return response


@login_required
@require_GET
def view_registration_document(request: HttpRequest, pk: int) -> HttpResponse:
    """Open a company-registration PDF owned by the vendor's active company."""
    if not is_vendor_user(request.user):
        return HttpResponseForbidden("Vendors only.")
    company = ensure_active_company(request)
    if company is None:
        messages.info(request, "Register a company to use the document vault.")
        return redirect("vendors:register_company")
    doc = get_object_or_404(CompanyDocument, pk=pk, company=company)
    return _pdf_response(
        path=doc.storage_path,
        backend=doc.storage_backend,
        filename=doc.original_filename or f"{doc.doc_type}.pdf",
    )


@login_required
@require_GET
def view_envelope1_document(request: HttpRequest, pk: int) -> HttpResponse:
    """Open an Envelope 1 PDF for the active company's submission."""
    if not is_vendor_user(request.user):
        return HttpResponseForbidden("Vendors only.")
    company = ensure_active_company(request)
    if company is None:
        messages.info(request, "Register a company to use the document vault.")
        return redirect("vendors:register_company")
    doc = get_object_or_404(
        Envelope1Document,
        pk=pk,
        submission__company=company,
    )
    return _pdf_response(
        path=doc.storage_path,
        backend=doc.storage_backend,
        filename=doc.original_filename or f"{doc.doc_type}.pdf",
    )


@login_required
def document_vault(request: HttpRequest) -> HttpResponse:
    """Index of registration + Envelope 1 PDFs for the active company."""
    if not is_vendor_user(request.user):
        return HttpResponseForbidden("Vendors only.")
    company = ensure_active_company(request)
    if company is None:
        messages.info(request, "Register a company to use the document vault.")
        return redirect("vendors:register_company")

    reg_docs = []
    seen: set[str] = set()
    for doc in company.documents.order_by("-version"):
        if doc.doc_type in seen:
            continue
        seen.add(doc.doc_type)
        reg_docs.append(doc)

    e1_docs = []
    submission = latest_submission(company)
    if submission:
        e1_seen: set[str] = set()
        for doc in submission.documents.order_by("-version"):
            if doc.doc_type in e1_seen:
                continue
            e1_seen.add(doc.doc_type)
            e1_docs.append(doc)

    return render(
        request,
        "envelope1/vault.html",
        {
            "page_title": "Document vault",
            "company": company,
            "registration_docs": reg_docs,
            "envelope1_docs": e1_docs,
            "envelope1_submission": submission,
            "doc_type_labels": dict(CompanyDocument.DocType.choices),
            "e1_type_labels": dict(Envelope1Document.DocType.choices),
        },
    )
