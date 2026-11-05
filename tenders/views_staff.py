"""Staff tender management: projects, RFQs, sealed quotations, and awards."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from audit.models import AuditLog
from audit.services import write_audit
from documents.storage import open_stored
from staff.decorators import (
    can_approve,
    can_evaluate,
    director_required,
    procurement_required,
    staff_required,
)
from tenders.documents import store_rfq_document
from tenders.forms import ProjectForm, RFQForm
from tenders.models import RFQ, Project, Quotation, TenderAward
from tenders.services import (
    _notify_eligible_vendors,
    cancel_project,
    decide_award,
    next_rfq_code,
    publish_project,
    recommend_award,
)


def pdf_response(*, path: str, backend: str, filename: str) -> HttpResponse:
    data = open_stored(path=path, backend=backend)
    response = HttpResponse(data, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename.replace(chr(34), "")}"'
    return response


def _project_with_rfqs(pk: int) -> Project:
    rfq_qs = RFQ.objects.prefetch_related(
        Prefetch("awards", queryset=TenderAward.objects.select_related("quotation__company", "recommended_by", "decided_by")),
        Prefetch("quotations", queryset=Quotation.objects.select_related("company")),
    )
    return get_object_or_404(Project.objects.prefetch_related(Prefetch("rfqs", queryset=rfq_qs)), pk=pk)


@login_required
@staff_required
def tender_list(request: HttpRequest) -> HttpResponse:
    q = (request.GET.get("q") or "").strip()
    qs = Project.objects.annotate(
        rfq_count=Count("rfqs", distinct=True),
        quote_count=Count(
            "rfqs__quotations",
            filter=Q(rfqs__quotations__status=Quotation.Status.SUBMITTED),
            distinct=True,
        ),
    ).prefetch_related("rfqs__awards")
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(reference__icontains=q))
    return render(
        request,
        "tenders/staff/tender_list.html",
        {
            "page_title": "Tenders",
            "projects": qs,
            "q": q,
            "can_evaluate": can_evaluate(request.user),
        },
    )


@login_required
@procurement_required
def project_create(request: HttpRequest) -> HttpResponse:
    form = ProjectForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        project = form.save(commit=False)
        project.created_by = request.user
        project.save()
        write_audit(
            category=AuditLog.Category.PROJECT,
            action="project_created",
            actor=request.user,
            request=request,
            changes={"title": project.title},
            object_type="Project",
            object_id=project.pk,
        )
        messages.success(request, "Project created. Add its RFQs, then publish.")
        return redirect("tenders:tender_detail", pk=project.pk)
    return render(
        request,
        "tenders/staff/project_form.html",
        {"page_title": "New project", "form": form, "project": None},
    )


@login_required
@procurement_required
def project_edit(request: HttpRequest, pk: int) -> HttpResponse:
    project = get_object_or_404(Project, pk=pk)
    if not project.is_editable:
        messages.error(request, "Published projects cannot be edited — cancel and re-issue instead.")
        return redirect("tenders:tender_detail", pk=pk)
    form = ProjectForm(request.POST or None, instance=project)
    if request.method == "POST" and form.is_valid():
        form.save()
        write_audit(
            category=AuditLog.Category.PROJECT,
            action="project_updated",
            actor=request.user,
            request=request,
            changes={"fields": form.changed_data},
            object_type="Project",
            object_id=project.pk,
        )
        messages.success(request, "Project updated.")
        return redirect("tenders:tender_detail", pk=pk)
    return render(
        request,
        "tenders/staff/project_form.html",
        {"page_title": "Edit project", "form": form, "project": project},
    )


@login_required
@staff_required
def tender_detail(request: HttpRequest, pk: int) -> HttpResponse:
    project = _project_with_rfqs(pk)
    rfqs = list(project.rfqs.all())
    rows = []
    for rfq in rfqs:
        submitted = [q for q in rfq.quotations.all() if q.status == Quotation.Status.SUBMITTED]
        rows.append(
            {
                "rfq": rfq,
                "quote_count": len(submitted),
                # Compliance: sealed — never pass quotation objects to the template before closing
                "quotations": [] if project.is_sealed else sorted(submitted, key=lambda q: q.total_price),
                "active_award": rfq.active_award,
                "history": [a for a in rfq.awards.all() if a.status == TenderAward.Status.REJECTED],
            }
        )
    return render(
        request,
        "tenders/staff/tender_detail.html",
        {
            "page_title": project.reference or "Draft project",
            "project": project,
            "rows": rows,
            "rfq_form": RFQForm() if project.can_add_rfq else None,
            "can_evaluate": can_evaluate(request.user),
            "can_approve": can_approve(request.user),
        },
    )


@login_required
@procurement_required
def rfq_save(request: HttpRequest, pk: int, rfq_pk: int | None = None) -> HttpResponse:
    project = get_object_or_404(Project, pk=pk)
    rfq = get_object_or_404(RFQ, pk=rfq_pk, project=project) if rfq_pk else None
    adding = rfq is None
    if adding and not project.can_add_rfq:
        messages.error(request, "RFQs can only be added while the project is open for quotations.")
        return redirect("tenders:tender_detail", pk=pk)
    if not adding and not project.is_editable:
        messages.error(request, "Published RFQs cannot be edited.")
        return redirect("tenders:tender_detail", pk=pk)
    form = RFQForm(request.POST or None, request.FILES or None, instance=rfq)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            obj = form.save(commit=False)
            obj.project = project
            if rfq is None:
                obj.code, obj.position = next_rfq_code(project)
            if form.cleaned_data.get("document"):
                store_rfq_document(rfq=obj, uploaded=form.cleaned_data["document"])
            obj.save()
            write_audit(
                category=AuditLog.Category.RFQ,
                action="rfq_updated" if rfq else "rfq_added",
                actor=request.user,
                request=request,
                changes={"code": obj.code, "title": obj.title},
                object_type="RFQ",
                object_id=obj.pk,
            )
            # Draft RFQs are covered by the publish email. A package added after
            # publish is a new tender, so eligible vendors are emailed then.
            if adding and project.status == Project.Status.OPEN:
                _notify_eligible_vendors(
                    project=project,
                    dedupe_key=f"tender-rfq-{obj.pk}",
                    title=f"New tender available — {obj.code}",
                    body=(
                        f"{obj.title} was added to {project.reference or project.title}. "
                        f"Quotations close "
                        f"{timezone.localtime(project.closing_at):%d %b %Y %H:%M}."
                    ),
                )
        messages.success(request, f"{obj.code} saved.")
        return redirect("tenders:tender_detail", pk=pk)
    if request.method == "POST":
        messages.error(request, "Please fix the RFQ errors below.")
    return render(
        request,
        "tenders/staff/rfq_form.html",
        {"page_title": "RFQ", "form": form, "project": project, "rfq": rfq},
    )


@login_required
@procurement_required
@require_POST
def rfq_delete(request: HttpRequest, pk: int, rfq_pk: int) -> HttpResponse:
    project = get_object_or_404(Project, pk=pk)
    rfq = get_object_or_404(RFQ, pk=rfq_pk, project=project)
    if not project.is_editable:
        messages.error(request, "RFQs can only be removed while the project is a draft.")
    else:
        write_audit(
            category=AuditLog.Category.RFQ,
            action="rfq_deleted",
            actor=request.user,
            request=request,
            changes={"code": rfq.code, "title": rfq.title},
            object_type="RFQ",
            object_id=rfq.pk,
        )
        rfq.delete()
        messages.success(request, f"{rfq.code} removed.")
    return redirect("tenders:tender_detail", pk=pk)


@login_required
@procurement_required
@require_POST
def project_publish(request: HttpRequest, pk: int) -> HttpResponse:
    project = get_object_or_404(Project, pk=pk)
    try:
        publish_project(project=project, actor=request.user, request=request)
        messages.success(request, "Project published. Eligible vendors have been notified.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("tenders:tender_detail", pk=pk)


@login_required
@procurement_required
@require_POST
def project_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    project = get_object_or_404(Project, pk=pk)
    try:
        cancel_project(
            project=project, actor=request.user, reason=request.POST.get("note", ""), request=request
        )
        messages.success(request, "Project cancelled.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("tenders:tender_detail", pk=pk)


@login_required
@procurement_required
@require_POST
def award_recommend(request: HttpRequest, rfq_pk: int) -> HttpResponse:
    rfq = get_object_or_404(RFQ, pk=rfq_pk)
    quotation = get_object_or_404(Quotation, pk=request.POST.get("quotation") or 0, rfq=rfq)
    try:
        recommend_award(
            rfq=rfq, quotation=quotation, actor=request.user, note=request.POST.get("note", ""), request=request
        )
        messages.success(request, f"Award for {rfq.code} sent to the Director.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("tenders:tender_detail", pk=rfq.project_id)


@login_required
@director_required
@require_POST
def award_decide(request: HttpRequest, award_pk: int) -> HttpResponse:
    award = get_object_or_404(TenderAward, pk=award_pk)
    approve = (request.POST.get("decision") or "").strip().lower() == "approve"
    try:
        decide_award(
            award=award, actor=request.user, approve=approve, note=request.POST.get("note", ""), request=request
        )
        messages.success(request, "Award approved and bidders notified." if approve else "Recommendation rejected.")
    except ValueError as exc:
        messages.error(request, str(exc))
    next_url = request.POST.get("next") or ""
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect("staff:approval_queue")


@login_required
@staff_required
@require_GET
def rfq_document(request: HttpRequest, rfq_pk: int) -> HttpResponse:
    rfq = get_object_or_404(RFQ, pk=rfq_pk)
    if not rfq.document_path:
        raise Http404("No tender document.")
    return pdf_response(path=rfq.document_path, backend=rfq.document_backend, filename=rfq.document_filename)


@login_required
@staff_required
@require_GET
def quotation_document(request: HttpRequest, pk: int) -> HttpResponse:
    quotation = get_object_or_404(Quotation.objects.select_related("rfq__project"), pk=pk)
    # Compliance: sealed bidding — staff cannot open vendor files before closing
    if quotation.rfq.project.is_sealed:
        raise Http404("Quotations are sealed until closing.")
    return pdf_response(
        path=quotation.document_path, backend=quotation.document_backend, filename=quotation.document_filename
    )
