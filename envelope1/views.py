"""Vendor Envelope 1 wizard, MSA download, withdrawal, and vault listings."""

from __future__ import annotations

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from accounts.company_context import ensure_active_company, set_active_company_id
from accounts.roles import is_vendor_user
from audit.models import AuditLog
from audit.services import write_audit
from documents.storage import open_stored
from envelope1.checklist import STEP_DOC_TYPES, STEP_META
from envelope1.documents import save_envelope1_pdf
from envelope1.forms import (
    DocumentPackForm,
    Step1MSAPartyForm,
    Step2SignedMSAForm,
    WithdrawalRequestForm,
)
from envelope1.models import Envelope1Document, Envelope1Submission, WithdrawalRequest
from envelope1.msa import build_draft_msa_pdf
from envelope1.services import (
    can_access_envelope1,
    get_or_create_draft,
    latest_docs_map,
    latest_submission,
    missing_required_docs,
)
from vendors.models import Company, CompanyDocument


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

    step = submission.wizard_step if submission.wizard_step in STEP_META else 1
    return redirect("envelope1:wizard", pk=submission.pk, step=step)


@login_required
@require_http_methods(["POST"])
def envelope1_start(request: HttpRequest) -> HttpResponse:
    """Legacy start URL — same as home (one Envelope 1 per company)."""
    return envelope1_home(request)


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
    editable = submission.is_editable

    if request.method == "POST" and not editable:
        messages.error(request, "This Envelope 1 cycle is locked. Request a withdrawal to edit.")
        return redirect("envelope1:wizard", pk=submission.pk, step=step)

    form: forms.BaseForm | None = None
    pack_form: DocumentPackForm | None = None

    if step == 1:
        if request.method == "POST":
            form = Step1MSAPartyForm(request.POST, instance=submission)
            if form.is_valid():
                with transaction.atomic():
                    obj = form.save(commit=False)
                    obj.msa_party_saved_at = timezone.now()
                    obj.wizard_step = max(obj.wizard_step, 1)
                    obj.save()
                    write_audit(
                        category=AuditLog.Category.COMPANY,
                        action="envelope1_step_1_saved",
                        actor=request.user,
                        request=request,
                        changes={"cycle": obj.cycle_number},
                        object_type="Envelope1Submission",
                        object_id=obj.pk,
                    )
                messages.success(request, "MSA party details saved.")
                if request.POST.get("action") == "continue":
                    return redirect("envelope1:wizard", pk=submission.pk, step=2)
                return redirect("envelope1:wizard", pk=submission.pk, step=1)
        else:
            form = Step1MSAPartyForm(instance=submission)

    elif step == 2:
        require_pdf = Envelope1Document.DocType.SIGNED_MSA not in docs
        if request.method == "POST":
            form = Step2SignedMSAForm(
                request.POST,
                request.FILES,
                require_pdf=require_pdf,
                initial={"msa_effective_date": submission.msa_effective_date},
            )
            if form.is_valid():
                with transaction.atomic():
                    submission.msa_effective_date = form.cleaned_data["msa_effective_date"]
                    submission.wizard_step = max(submission.wizard_step, 2)
                    submission.save(
                        update_fields=["msa_effective_date", "wizard_step", "updated_at"]
                    )
                    pdf = form.cleaned_data.get("signed_msa_pdf")
                    if pdf:
                        save_envelope1_pdf(
                            submission=submission,
                            doc_type=Envelope1Document.DocType.SIGNED_MSA,
                            uploaded=pdf,
                            user=request.user,
                        )
                    write_audit(
                        category=AuditLog.Category.COMPANY,
                        action="envelope1_step_2_saved",
                        actor=request.user,
                        request=request,
                        changes={"cycle": submission.cycle_number},
                        object_type="Envelope1Submission",
                        object_id=submission.pk,
                    )
                messages.success(request, "Signed MSA details saved.")
                return redirect("envelope1:wizard", pk=submission.pk, step=3)
        else:
            form = Step2SignedMSAForm(
                require_pdf=require_pdf,
                initial={"msa_effective_date": submission.msa_effective_date},
            )

    elif step in (3, 4, 5, 6):
        doc_types = STEP_DOC_TYPES[step]
        if request.method == "POST":
            pack_form = DocumentPackForm(
                request.POST,
                request.FILES,
                doc_types=doc_types,
                existing=docs,
            )
            if pack_form.is_valid():
                with transaction.atomic():
                    for meta in pack_form.doc_meta:
                        pdf = pack_form.cleaned_data.get(meta["pdf_name"])
                        expiry = (
                            pack_form.cleaned_data.get(meta["exp_name"])
                            if meta["needs_expiry"]
                            else None
                        )
                        if pdf:
                            save_envelope1_pdf(
                                submission=submission,
                                doc_type=meta["doc_type"],
                                uploaded=pdf,
                                user=request.user,
                                expiry_date=expiry,
                            )
                        elif meta["needs_expiry"] and expiry and meta["doc_type"] in docs:
                            doc = docs[meta["doc_type"]]
                            doc.expiry_date = expiry
                            doc.save(update_fields=["expiry_date"])
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

                if step < 6:
                    messages.success(request, f"Step {step} saved.")
                    return redirect("envelope1:wizard", pk=submission.pk, step=step + 1)

                # Step 6 — submit Envelope 1
                missing = missing_required_docs(submission)
                if missing or not submission.msa_party_saved_at or not submission.msa_effective_date:
                    messages.error(
                        request,
                        "Complete all required MSA details and document uploads before submitting.",
                    )
                    return redirect("envelope1:wizard", pk=submission.pk, step=6)

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
                # Confirmation shown as a SweetAlert on the next page load (not a toast)
                request.session["envelope1_just_submitted"] = submission.pk
                return redirect("envelope1:wizard", pk=submission.pk, step=6)
        else:
            pack_form = DocumentPackForm(doc_types=doc_types, existing=docs)

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
            "pack_form": pack_form,
            "docs": docs,
            "editable": editable,
            "msa_ready": bool(submission.msa_party_saved_at),
            "just_submitted": request.session.pop("envelope1_just_submitted", None)
            == submission.pk,
            "pending_withdrawal": submission.withdrawal_requests.filter(
                status=WithdrawalRequest.Status.PENDING
            ).first()
            if not editable
            else None,
        },
    )


@login_required
def download_draft_msa(request: HttpRequest, pk: int) -> HttpResponse:
    company = _vendor_company(request)
    if not isinstance(company, Company):
        return company
    submission = Envelope1Submission.objects.filter(pk=pk, company=company).first()
    if submission is None:
        return redirect("envelope1:home")
    if not submission.msa_party_saved_at:
        messages.error(request, "Save MSA party details before downloading the draft.")
        return redirect("envelope1:wizard", pk=submission.pk, step=1)
    pdf = build_draft_msa_pdf(submission)
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="draft-msa-cycle-{submission.cycle_number}.pdf"'
    )
    write_audit(
        category=AuditLog.Category.DOCUMENT,
        action="envelope1_draft_msa_downloaded",
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
    """Stream a stored PDF inline so the browser can display it."""
    data = open_stored(path=path, backend=backend)
    response = HttpResponse(data, content_type="application/pdf")
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
