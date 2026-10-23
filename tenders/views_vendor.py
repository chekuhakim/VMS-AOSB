"""Vendor-facing tender pages: open projects, quotation submission, and bids."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from accounts.company_context import ensure_active_company
from accounts.roles import is_vendor_user
from tenders.forms import QuotationForm
from tenders.models import RFQ, Project, Quotation, TenderAward
from tenders.services import (
    company_prequalified,
    quote_blockers,
    requirement_issues,
    submit_quotation,
    withdraw_quotation,
)
from tenders.views_staff import pdf_response
from vendors.models import Company


def _vendor_company(request: HttpRequest) -> Company | HttpResponse:
    if not is_vendor_user(request.user):
        return HttpResponseForbidden("Vendors only.")
    company = ensure_active_company(request)
    if company is None:
        messages.warning(request, "Register your company before viewing projects.")
        return redirect("vendors:register_company")
    return company


def _quote_result(quote: Quotation) -> tuple[str, str]:
    """(label, tone) for a vendor's quotation status.

    Award outcomes are never shown to vendors — staff inform the winner outside the system.
    """
    project = quote.rfq.project
    if quote.status == Quotation.Status.WITHDRAWN:
        return "Withdrawn", "slate"
    if project.status == Project.Status.CANCELLED:
        return "Project cancelled", "slate"
    if project.accepting_quotations:
        return "Submitted — editable until closing", "sky"
    return "Closed", "amber"


def _rfq_prefetch() -> Prefetch:
    return Prefetch(
        "rfqs",
        queryset=RFQ.objects.prefetch_related(
            Prefetch("awards", queryset=TenderAward.objects.filter(status=TenderAward.Status.APPROVED))
        ),
    )


@login_required
def project_list(request: HttpRequest) -> HttpResponse:
    company = _vendor_company(request)
    if not isinstance(company, Company):
        return company
    if not company_prequalified(company):
        return render(
            request,
            "tenders/vendor/project_locked.html",
            {"page_title": "Projects", "company": company},
        )

    projects = (
        Project.objects.filter(status=Project.Status.OPEN, closing_at__gt=timezone.now())
        .prefetch_related("rfqs")
        .order_by("closing_at")
    )
    quoted = set(
        Quotation.objects.filter(company=company, status=Quotation.Status.SUBMITTED)
        .values_list("rfq__project_id", flat=True)
    )
    cards = [
        {
            "project": p,
            "issues": requirement_issues(company, p),
            "quoted": p.pk in quoted,
        }
        for p in projects
    ]
    return render(
        request,
        "tenders/vendor/project_list.html",
        {"page_title": "Projects", "company": company, "cards": cards},
    )


@login_required
def project_detail(request: HttpRequest, pk: int) -> HttpResponse:
    company = _vendor_company(request)
    if not isinstance(company, Company):
        return company
    project = get_object_or_404(Project.objects.prefetch_related(_rfq_prefetch()), pk=pk)
    mine = {
        q.rfq_id: q
        for q in Quotation.objects.filter(company=company, rfq__project=project).select_related("rfq__project")
    }
    if project.status == Project.Status.DRAFT or (not company_prequalified(company) and not mine):
        raise Http404("Project not available.")

    blockers = quote_blockers(company=company, project=project)
    rows = []
    for rfq in project.rfqs.all():
        quote = mine.get(rfq.pk)
        rows.append(
            {
                "rfq": rfq,
                "quote": quote,
                "result": _quote_result(quote) if quote else None,
            }
        )
    return render(
        request,
        "tenders/vendor/project_detail.html",
        {
            "page_title": project.title,
            "company": company,
            "project": project,
            "rows": rows,
            "blockers": blockers,
            "just_submitted": request.session.pop("tenders_just_submitted", None),
        },
    )


@login_required
def quotation_form(request: HttpRequest, pk: int, rfq_pk: int) -> HttpResponse:
    company = _vendor_company(request)
    if not isinstance(company, Company):
        return company
    rfq = get_object_or_404(RFQ.objects.select_related("project"), pk=rfq_pk, project_id=pk)
    project = rfq.project
    blockers = quote_blockers(company=company, project=project)
    if blockers:
        messages.error(request, blockers[0])
        return redirect("tenders:project_detail", pk=pk)

    existing = Quotation.objects.filter(rfq=rfq, company=company).first()
    initial = {}
    if existing:
        initial = {
            "total_price": existing.total_price,
            "handover_date": existing.handover_date,
            "remarks": existing.remarks,
        }
    form = QuotationForm(
        request.POST or None,
        request.FILES or None,
        initial=initial,
        company_name=company.name,
        has_existing_pdf=bool(existing and existing.document_path),
        project_end=project.end_date,
    )
    if request.method == "POST" and form.is_valid():
        try:
            submit_quotation(
                rfq=rfq,
                company=company,
                data=form.cleaned_data,
                uploaded=form.cleaned_data.get("quotation_pdf"),
                user=request.user,
                request=request,
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("tenders:project_detail", pk=pk)
        request.session["tenders_just_submitted"] = f"{rfq.code} · {rfq.title}"
        return redirect("tenders:project_detail", pk=pk)
    return render(
        request,
        "tenders/vendor/quotation_form.html",
        {
            "page_title": f"Quote {rfq.code}",
            "company": company,
            "project": project,
            "rfq": rfq,
            "form": form,
            "existing": existing,
        },
    )


@login_required
@require_POST
def quotation_withdraw(request: HttpRequest, pk: int) -> HttpResponse:
    company = _vendor_company(request)
    if not isinstance(company, Company):
        return company
    quotation = get_object_or_404(Quotation, pk=pk, company=company)
    try:
        withdraw_quotation(quotation=quotation, user=request.user, request=request)
        messages.success(request, "Quotation withdrawn. You can submit again before closing.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("tenders:project_detail", pk=quotation.rfq.project_id)


@login_required
def your_bids(request: HttpRequest) -> HttpResponse:
    company = _vendor_company(request)
    if not isinstance(company, Company):
        return company
    quotes = (
        Quotation.objects.filter(company=company)
        .select_related("rfq__project")
        .order_by("-submitted_at")
    )
    rows = [{"quote": q, "result": _quote_result(q)} for q in quotes]
    return render(
        request,
        "tenders/vendor/your_bids.html",
        {"page_title": "Your bids", "company": company, "rows": rows},
    )


@login_required
@require_GET
def vendor_rfq_document(request: HttpRequest, rfq_pk: int) -> HttpResponse:
    company = _vendor_company(request)
    if not isinstance(company, Company):
        return company
    rfq = get_object_or_404(RFQ.objects.select_related("project"), pk=rfq_pk)
    if rfq.project.status == Project.Status.DRAFT or not company_prequalified(company) or not rfq.document_path:
        raise Http404("Document not available.")
    return pdf_response(path=rfq.document_path, backend=rfq.document_backend, filename=rfq.document_filename)


@login_required
@require_GET
def vendor_quotation_document(request: HttpRequest, pk: int) -> HttpResponse:
    company = _vendor_company(request)
    if not isinstance(company, Company):
        return company
    quotation = get_object_or_404(Quotation, pk=pk, company=company)
    return pdf_response(
        path=quotation.document_path, backend=quotation.document_backend, filename=quotation.document_filename
    )
