"""Forms for tender projects, RFQ work packages, and vendor quotations."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from django import forms
from django.utils import timezone

from core.form_labels import mark_required_labels
from tenders.declaration import declaration_text
from tenders.models import RFQ, Project
from vendors.forms import CIDB_GRADE_CHOICES, validate_pdf_upload

_INPUT_CLASS = (
    "mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 "
    "text-sm shadow-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
)
_INPUT = {"class": _INPUT_CLASS}
_FILE = {
    "class": (
        "mt-1.5 block w-full text-sm text-slate-600 file:mr-3 file:rounded-lg "
        "file:border-0 file:bg-brand-50 file:px-3 file:py-2 file:text-sm "
        "file:font-medium file:text-brand"
    ),
    "accept": "application/pdf",
}


def _mark_required(form: forms.BaseForm) -> None:
    mark_required_labels(form)


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = [
            "title",
            "scope",
            "start_date",
            "end_date",
            "closing_at",
            "min_cidb_grade",
        ]
        labels = {
            "title": "Project name",
            "scope": "Scope of work",
            "start_date": "Project start date",
            "end_date": "Project end date",
            "closing_at": "Quotation closing date & time",
            "min_cidb_grade": "Minimum CIDB grade",
        }
        widgets = {
            "title": forms.TextInput(attrs=_INPUT),
            "scope": forms.Textarea(attrs={**_INPUT, "rows": 5}),
            "start_date": forms.DateInput(attrs={**_INPUT, "type": "date"}, format="%Y-%m-%d"),
            "end_date": forms.DateInput(attrs={**_INPUT, "type": "date"}, format="%Y-%m-%d"),
            "closing_at": forms.DateTimeInput(
                attrs={**_INPUT, "type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["min_cidb_grade"] = forms.ChoiceField(
            required=False,
            label="Minimum CIDB grade",
            choices=[("", "Any grade")] + CIDB_GRADE_CHOICES[1:],
            widget=forms.Select(attrs=_INPUT),
        )
        self.fields["closing_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        _mark_required(self)

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        start = cleaned.get("start_date")
        end = cleaned.get("end_date")
        closing = cleaned.get("closing_at")
        if start and end and end < start:
            self.add_error("end_date", "End date cannot be before the start date.")
        if closing and closing <= timezone.now():
            self.add_error("closing_at", "Closing date & time must be in the future.")
        # Quotations must close before work begins so the award can be made in time
        if closing and start and timezone.localtime(closing).date() > start:
            self.add_error("closing_at", "Quotations must close on or before the project start date.")
        return cleaned


class RFQForm(forms.ModelForm):
    document = forms.FileField(
        required=False,
        label="Tender document (PDF, optional)",
        widget=forms.ClearableFileInput(attrs=_FILE),
    )

    class Meta:
        model = RFQ
        fields = ["title", "description", "quantity", "unit"]
        labels = {"title": "RFQ title", "description": "Description / specification"}
        widgets = {
            "title": forms.TextInput(attrs=_INPUT),
            "description": forms.Textarea(attrs={**_INPUT, "rows": 3}),
            "quantity": forms.NumberInput(attrs={**_INPUT, "step": "0.01", "min": "0"}),
            "unit": forms.TextInput(attrs={**_INPUT, "placeholder": "e.g. lot, m², unit"}),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        _mark_required(self)

    def clean_quantity(self) -> Decimal | None:
        qty = self.cleaned_data.get("quantity")
        if qty is not None and qty <= 0:
            raise forms.ValidationError("Quantity must be greater than zero.")
        return qty

    def clean_document(self) -> Any:
        doc = self.cleaned_data.get("document")
        if doc:
            validate_pdf_upload(doc)
        return doc


class QuotationForm(forms.Form):
    total_price = forms.DecimalField(
        label="Quoted total price (RM)",
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.01"),
        widget=forms.NumberInput(attrs={**_INPUT, "step": "0.01", "min": "0.01"}),
    )
    handover_date = forms.DateField(
        label="Estimated Project Handover Date",
        widget=forms.DateInput(attrs={**_INPUT, "type": "date"}, format="%Y-%m-%d"),
    )
    remarks = forms.CharField(
        label="Remarks",
        required=False,
        widget=forms.Textarea(attrs={**_INPUT, "rows": 3}),
    )
    quotation_pdf = forms.FileField(
        label="Quotation PDF",
        widget=forms.ClearableFileInput(attrs=_FILE),
    )
    declaration = forms.BooleanField(
        required=True,
        error_messages={"required": "You must accept the declaration to submit."},
    )

    def __init__(
        self, *args: Any, company_name: str, has_existing_pdf: bool, project_end: date, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.project_end = project_end
        self.fields["handover_date"].widget.attrs.update(
            {"min": timezone.localdate().isoformat(), "max": project_end.isoformat()}
        )
        self.fields["handover_date"].help_text = f"On or before the project end date, {project_end:%d %b %Y}."
        # Re-quoting keeps the stored PDF unless a new one is uploaded
        self.fields["quotation_pdf"].required = not has_existing_pdf
        if has_existing_pdf:
            self.fields["quotation_pdf"].label = "Replace quotation PDF (optional)"
        _mark_required(self)
        self.declaration_text = declaration_text(company_name)
        self.fields["declaration"].label = self.declaration_text

    def clean_handover_date(self) -> date:
        handover: date = self.cleaned_data["handover_date"]
        if handover < timezone.localdate():
            raise forms.ValidationError("The handover date cannot be in the past.")
        # Business rule: handover must fit inside the project window set by staff when opening the tender
        if handover > self.project_end:
            raise forms.ValidationError(
                f"The handover date must be on or before the project end date ({self.project_end:%d %b %Y})."
            )
        return handover

    def clean_quotation_pdf(self) -> Any:
        pdf = self.cleaned_data.get("quotation_pdf")
        if pdf:
            validate_pdf_upload(pdf)
        return pdf
