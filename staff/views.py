"""Phase 4 staff UI — dashboard, companies, Envelope 1 evaluation, approval, audit."""

from __future__ import annotations

import mimetypes

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from audit.models import AuditLog
from documents.storage import open_stored
from envelope1.checklist import STEP_META
from envelope1.models import Envelope1Document, Envelope1Submission, WithdrawalRequest
from staff.decorators import (
    can_approve,
    can_evaluate,
    director_required,
    procurement_required,
    staff_required,
)
from staff.dashboard import (
    EXPIRY_WINDOW_DAYS,
    build_audit_feed,
    build_pipeline,
    build_recent_submissions,
    build_stat_cards,
)
from staff.eval_ui import ICONS, build_stepper, read_only_fields
from staff.forms import EvaluationStepForm
from staff.services import (
    director_decide,
    evaluation_progress,
    lock_for_evaluation,
    reject_at_evaluation,
    reopen_evaluation,
    return_to_vendor,
    review_withdrawal,
    send_to_director,
    set_item_result,
    step_checklist,
    step_statuses,
)
from tenders.services import pending_awards
from vendors.models import Company, CompanyDocument
from vendors.rules import REASON_LABELS


@login_required
@staff_required
def admin_dashboard(request: HttpRequest) -> HttpResponse:
    stage = (request.GET.get("stage") or "").strip()
    if stage not in ("", "envelope1", "registration"):
        stage = ""
    ctx = {
        "page_title": "Dashboard",
        "stats": build_stat_cards(),
        "submissions": build_recent_submissions(
            stage=stage,
            can_evaluate=can_evaluate(request.user),
            can_approve=can_approve(request.user),
        ),
        "stage": stage,
        "pipeline": build_pipeline(),
        "audit_feed": build_audit_feed(),
        "expiry_window_days": EXPIRY_WINDOW_DAYS,
    }
    return render(request, "staff/admin_dashboard.html", ctx)


@login_required
@staff_required
@require_GET
def audit_feed(request: HttpRequest) -> HttpResponse:
    """HTML fragment polled by the dashboard so the audit trail stays live."""
    return render(
        request,
        "staff/components/audit_feed.html",
        {"audit_feed": build_audit_feed()},
    )


@login_required
@staff_required
def company_list(request: HttpRequest) -> HttpResponse:
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    qs = (
        Company.objects.filter(is_hidden=False)
        .select_related("owner")
        .order_by("-updated_at")
    )
    if q:
        qs = qs.filter(
            Q(name__icontains=q)
            | Q(ssm_registration_number__icontains=q)
            | Q(official_email__icontains=q)
            | Q(owner__email__icontains=q)
        )
    if status in {c.value for c in Company.RegistrationStatus}:
        qs = qs.filter(registration_status=status)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "staff/company_list.html",
        {
            "page_title": "Registered companies",
            "page_obj": page,
            "q": q,
            "status": status,
            "status_choices": Company.RegistrationStatus.choices,
        },
    )


@login_required
@staff_required
def company_detail(request: HttpRequest, pk: int) -> HttpResponse:
    company = get_object_or_404(Company.objects.select_related("owner"), pk=pk)
    docs = []
    seen: set[str] = set()
    for doc in company.documents.order_by("-version"):
        if doc.doc_type in seen:
            continue
        seen.add(doc.doc_type)
        docs.append(doc)
    e1 = (
        Envelope1Submission.objects.filter(company=company)
        .order_by("-cycle_number")
        .first()
    )
    reason_labels = [
        REASON_LABELS.get(code, code) for code in (company.evaluation_notes or [])
    ]
    return render(
        request,
        "staff/company_detail.html",
        {
            "page_title": company.name,
            "company": company,
            "registration_docs": docs,
            "envelope1": e1,
            "reason_labels": reason_labels,
        },
    )


@login_required
@staff_required
@require_GET
def view_company_document(request: HttpRequest, pk: int) -> HttpResponse:
    doc = get_object_or_404(CompanyDocument, pk=pk)
    data = open_stored(path=doc.storage_path, backend=doc.storage_backend)
    filename = doc.original_filename or f"{doc.doc_type}.pdf"
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    response = HttpResponse(data, content_type=content_type)
    safe = filename.replace('"', "")
    response["Content-Disposition"] = f'inline; filename="{safe}"'
    return response


@login_required
@staff_required
def envelope1_list(request: HttpRequest) -> HttpResponse:
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    qs = (
        Envelope1Submission.objects.select_related("company", "company__owner")
        .exclude(status=Envelope1Submission.Status.DRAFT)
        .exclude(company__is_hidden=True)
        .order_by("-updated_at")
    )
    if q:
        qs = qs.filter(
            Q(company__name__icontains=q)
            | Q(legal_name__icontains=q)
            | Q(ssm_registration_number__icontains=q)
        )
    if status in {c.value for c in Envelope1Submission.Status}:
        qs = qs.filter(status=status)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "staff/envelope1_list.html",
        {
            "page_title": "Submitted Envelope 1",
            "page_obj": page,
            "q": q,
            "status": status,
            "status_choices": [
                c
                for c in Envelope1Submission.Status.choices
                if c[0] != Envelope1Submission.Status.DRAFT
            ],
            "can_evaluate": can_evaluate(request.user),
        },
    )


@login_required
@staff_required
def envelope1_detail(request: HttpRequest, pk: int) -> HttpResponse:
    get_object_or_404(Envelope1Submission, pk=pk)
    return redirect("staff:envelope1_evaluate", pk=pk, step=1)


_EVAL_LAST_STEP = max(STEP_META)


@login_required
@staff_required
def envelope1_evaluate(request: HttpRequest, pk: int, step: int) -> HttpResponse:
    """Step-by-step evaluation mirroring the vendor's 6-step Envelope 1 wizard."""
    submission = get_object_or_404(
        Envelope1Submission.objects.select_related("company", "locked_by"),
        pk=pk,
    )
    if step not in STEP_META:
        return redirect("staff:envelope1_evaluate", pk=pk, step=1)

    user_can_evaluate = can_evaluate(request.user)
    user_can_approve = can_approve(request.user)
    # Approvals opens the same wizard read-only; Procurement's own visit stays the done card
    director_review = (
        submission.status == Envelope1Submission.Status.PENDING_DIRECTOR
        and user_can_approve
        and (request.GET.get("review") == "1" or not user_can_evaluate)
    )
    procurement_done = (
        submission.status == Envelope1Submission.Status.PENDING_DIRECTOR
        and user_can_evaluate
        and not director_review
    )
    # ISO gate: scoring is only open while Procurement holds the lock
    editable = (
        user_can_evaluate
        and submission.is_locked
        and submission.status == Envelope1Submission.Status.IN_PROGRESS
    )
    items = step_checklist(submission, step)
    evaluations = [item["evaluation"] for item in items]

    if request.method == "POST":
        if not editable:
            messages.error(request, "This Envelope 1 is not open for evaluation.")
            return redirect("staff:envelope1_evaluate", pk=pk, step=step)
        form = EvaluationStepForm(request.POST, evaluations=evaluations)
        if form.is_valid():
            with transaction.atomic():
                for ev, result, note in form.changed_items():
                    set_item_result(
                        evaluation=ev,
                        result=result,
                        note=note,
                        actor=request.user,
                        request=request,
                    )
            action = request.POST.get("action", "save")
            if action == "next" and step < _EVAL_LAST_STEP:
                return redirect("staff:envelope1_evaluate", pk=pk, step=step + 1)
            if action == "back" and step > 1:
                return redirect("staff:envelope1_evaluate", pk=pk, step=step - 1)
            if action == "send_director":
                try:
                    send_to_director(submission=submission, actor=request.user, request=request)
                    messages.success(request, "Sent to Director for final approval.")
                except ValueError as exc:
                    messages.error(request, str(exc))
                return redirect("staff:envelope1_evaluate", pk=pk, step=step)
            messages.success(request, "Progress saved.")
            return redirect("staff:envelope1_evaluate", pk=pk, step=step)
        messages.error(request, "Please fix the highlighted remarks before saving.")
    else:
        form = EvaluationStepForm(evaluations=evaluations)

    for item in items:
        item.update(form.item_state(item["evaluation"]))

    company = submission.company
    return render(
        request,
        "staff/envelope1_evaluate.html",
        {
            "page_title": f"Envelope 1 Evaluation · {company.name}",
            "submission": submission,
            "company": company,
            "step": step,
            "step_meta": STEP_META[step],
            "last_step": _EVAL_LAST_STEP,
            "stepper": build_stepper(step_statuses(submission)),
            "fields": read_only_fields(submission, step),
            "doc_icon": ICONS["document"],
            "items": items,
            "form": form,
            "progress": evaluation_progress(submission),
            "editable": editable,
            "can_return": editable and evaluation_progress(submission)["failed"] > 0,
            "can_evaluate": user_can_evaluate,
            "can_approve": user_can_approve,
            "procurement_done": procurement_done,
            "director_review": director_review,
            "review_query": "review=1" if director_review else "",
            "can_lock": user_can_evaluate
            and submission.status
            in {
                Envelope1Submission.Status.SUBMITTED,
                Envelope1Submission.Status.PENDING_EVALUATION,
            },
            "pending_withdrawal": submission.withdrawal_requests.filter(
                status=WithdrawalRequest.Status.PENDING
            ).first(),
        },
    )


@login_required
@procurement_required
@require_POST
def envelope1_lock(request: HttpRequest, pk: int) -> HttpResponse:
    submission = get_object_or_404(Envelope1Submission, pk=pk)
    try:
        lock_for_evaluation(submission=submission, actor=request.user, request=request)
        messages.success(request, "Envelope 1 locked for procurement evaluation.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("staff:envelope1_detail", pk=pk)


@login_required
@procurement_required
@require_POST
def envelope1_send_director(request: HttpRequest, pk: int) -> HttpResponse:
    submission = get_object_or_404(Envelope1Submission, pk=pk)
    try:
        send_to_director(submission=submission, actor=request.user, request=request)
        messages.success(request, "Sent to Director for final approval.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("staff:envelope1_evaluate", pk=pk, step=_EVAL_LAST_STEP)


@login_required
@procurement_required
@require_POST
def envelope1_return_correction(request: HttpRequest, pk: int) -> HttpResponse:
    submission = get_object_or_404(Envelope1Submission, pk=pk)
    note = (request.POST.get("note") or "").strip()
    try:
        return_to_vendor(
            submission=submission, actor=request.user, note=note, request=request
        )
        messages.success(request, "Envelope 1 returned to the vendor for correction.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("staff:envelope1_evaluate", pk=pk, step=_EVAL_LAST_STEP)


@login_required
@procurement_required
@require_POST
def envelope1_reopen_eval(request: HttpRequest, pk: int) -> HttpResponse:
    submission = get_object_or_404(Envelope1Submission, pk=pk)
    try:
        reopen_evaluation(submission=submission, actor=request.user, request=request)
        messages.info(request, "Evaluation is open again. Send it to the Director when you are done.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("staff:envelope1_evaluate", pk=pk, step=_EVAL_LAST_STEP)


@login_required
@procurement_required
@require_POST
def envelope1_reject_eval(request: HttpRequest, pk: int) -> HttpResponse:
    submission = get_object_or_404(Envelope1Submission, pk=pk)
    note = (request.POST.get("note") or "").strip()
    if not note:
        messages.error(request, "A reason is required to reject this Envelope 1.")
        return redirect("staff:envelope1_evaluate", pk=pk, step=_EVAL_LAST_STEP)
    try:
        reject_at_evaluation(
            submission=submission, actor=request.user, note=note, request=request
        )
        messages.success(request, "Envelope 1 rejected at evaluation.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("staff:envelope1_evaluate", pk=pk, step=_EVAL_LAST_STEP)


@login_required
@staff_required
@require_GET
def view_envelope1_document(request: HttpRequest, pk: int) -> HttpResponse:
    doc = get_object_or_404(Envelope1Document, pk=pk)
    data = open_stored(path=doc.storage_path, backend=doc.storage_backend)
    response = HttpResponse(data, content_type="application/pdf")
    safe = (doc.original_filename or f"{doc.doc_type}.pdf").replace('"', "")
    response["Content-Disposition"] = f'inline; filename="{safe}"'
    return response


@login_required
@staff_required
def approval_queue(request: HttpRequest) -> HttpResponse:
    qs = (
        Envelope1Submission.objects.select_related("company")
        .filter(status=Envelope1Submission.Status.PENDING_DIRECTOR, company__is_hidden=False)
        .order_by("updated_at")
    )
    return render(
        request,
        "staff/approval_queue.html",
        {
            "page_title": "Director approval",
            "submissions": qs,
            "awards": pending_awards(),
            "can_approve": can_approve(request.user),
        },
    )


@login_required
@director_required
@require_POST
def approval_decide(request: HttpRequest, pk: int) -> HttpResponse:
    submission = get_object_or_404(Envelope1Submission, pk=pk)
    decision = (request.POST.get("decision") or "").strip().lower()
    note = request.POST.get("note") or ""
    try:
        director_decide(
            submission=submission,
            actor=request.user,
            approve=decision == "approve",
            note=note,
            request=request,
        )
        messages.success(
            request,
            "Envelope 1 approved." if decision == "approve" else "Envelope 1 rejected.",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("staff:approval_queue")


@login_required
@staff_required
def withdrawal_list(request: HttpRequest) -> HttpResponse:
    qs = (
        WithdrawalRequest.objects.select_related(
            "submission", "submission__company", "requested_by"
        )
        .exclude(submission__company__is_hidden=True)
        .order_by("-created_at")
    )
    status = (request.GET.get("status") or "pending").strip()
    if status in {c.value for c in WithdrawalRequest.Status}:
        qs = qs.filter(status=status)
    return render(
        request,
        "staff/withdrawal_list.html",
        {
            "page_title": "Withdrawal requests",
            "withdrawals": qs[:50],
            "status": status,
            "can_evaluate": can_evaluate(request.user),
        },
    )


@login_required
@procurement_required
@require_POST
def withdrawal_decide(request: HttpRequest, pk: int) -> HttpResponse:
    withdrawal = get_object_or_404(WithdrawalRequest, pk=pk)
    decision = (request.POST.get("decision") or "").strip().lower()
    note = request.POST.get("note") or ""
    try:
        review_withdrawal(
            withdrawal=withdrawal,
            actor=request.user,
            approve=decision == "approve",
            review_note=note,
            request=request,
        )
        messages.success(
            request,
            "Withdrawal approved — vendor may edit again."
            if decision == "approve"
            else "Withdrawal rejected.",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("staff:withdrawal_list")


@login_required
@staff_required
def audit_log(request: HttpRequest) -> HttpResponse:
    q = (request.GET.get("q") or "").strip()
    category = (request.GET.get("category") or "").strip()
    qs = AuditLog.objects.select_related("actor").order_by("-created_at")
    if q:
        qs = qs.filter(
            Q(action__icontains=q)
            | Q(actor_label__icontains=q)
            | Q(object_type__icontains=q)
            | Q(object_id__icontains=q)
        )
    if category in {c.value for c in AuditLog.Category}:
        qs = qs.filter(category=category)
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    return render(
        request,
        "staff/audit_log.html",
        {
            "page_title": "Audit log",
            "page_obj": page,
            "q": q,
            "category": category,
            "category_choices": AuditLog.Category.choices,
        },
    )


@login_required
@staff_required
def qualification_checklist_redirect(request: HttpRequest) -> HttpResponse:
    """Legacy nav target — send procurement to in-progress / pending Envelope 1 work."""
    submission = (
        Envelope1Submission.objects.filter(
            status=Envelope1Submission.Status.IN_PROGRESS,
            company__is_hidden=False,
        )
        .order_by("-updated_at")
        .first()
    )
    if submission is None:
        submission = (
            Envelope1Submission.objects.filter(
                status__in=[
                    Envelope1Submission.Status.PENDING_EVALUATION,
                    Envelope1Submission.Status.SUBMITTED,
                ],
                company__is_hidden=False,
            )
            .order_by("-updated_at")
            .first()
        )
    if submission:
        return redirect("staff:envelope1_detail", pk=submission.pk)
    messages.info(request, "No Envelope 1 packs are awaiting checklist review.")
    return redirect("staff:envelope1_list")
