"""Forms for the Envelope 1 wizard (MSA steps + questionnaire steps 3–6)."""

from __future__ import annotations

from typing import Any

from django import forms
from django.contrib.auth.models import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.form_labels import mark_required_labels, required_label
from envelope1.checklist import (
    DECLARATIONS,
    EXPIRY_REQUIRED_TYPES,
    ITEM_HELP,
    LEAD_TIME_SEA_LABEL,
    LEAD_TIME_SEMENANJUNG_LABEL,
    MIN_FINANCIAL_STATEMENTS,
    QUESTIONS,
    REQUIRED_UPLOADS,
    YES_NO_UPLOADS,
)
from envelope1.documents import save_envelope1_pdf
from envelope1.models import (
    Envelope1Document,
    Envelope1Item,
    Envelope1Submission,
    FinancialStatement,
    PastProject,
    PrimarySupplier,
    WithdrawalRequest,
)
from vendors.forms import validate_pdf_upload

_INPUT = {
    "class": (
        "mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 "
        "text-sm shadow-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
    )
}
_CELL_INPUT = {
    "class": (
        "w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm "
        "focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
    )
}
_TEXTAREA = {
    "class": (
        "mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 "
        "text-sm shadow-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
    ),
    "rows": 3,
}
_FILE = {
    "class": (
        "mt-1.5 block w-full text-sm text-slate-600 file:mr-3 file:rounded-lg "
        "file:border-0 file:bg-brand-50 file:px-3 file:py-2 file:text-sm "
        "file:font-medium file:text-brand"
    ),
    "accept": "application/pdf",
}
_CELL_FILE = {
    "class": (
        "block w-full text-sm text-slate-600 file:mr-3 file:rounded-lg file:border-0 "
        "file:bg-brand-50 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-brand"
    ),
    "accept": "application/pdf",
}
_DAYS = {
    "class": (
        "w-24 rounded-lg border border-slate-200 bg-white px-3 py-2 text-center text-sm "
        "shadow-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
    ),
    "min": 1,
    "max": 365,
    "inputmode": "numeric",
}

YES_NO_CHOICES = (("yes", "Yes"), ("no", "No"))

UPLOAD_LABELS: dict[str, str] = {
    Envelope1Document.DocType.NO_ADVANCE: "Signed declaration (PDF)",
    Envelope1Document.DocType.CAR_INSURANCE: "CAR insurance certificate (PDF)",
    Envelope1Document.DocType.ORG_CHART: "Organisation chart (PDF)",
}


def _yes_no_field(label: str) -> forms.TypedChoiceField:
    return forms.TypedChoiceField(
        label=label,
        choices=YES_NO_CHOICES,
        coerce=lambda value: value == "yes",
        empty_value=None,
        widget=forms.RadioSelect,
        error_messages={"required": "Please select Yes or No."},
    )


def _yes_no_initial(value: bool | None) -> str | None:
    if value is None:
        return None
    return "yes" if value else "no"


def _set_bound_value(form: forms.Form, name: str, value: object) -> None:
    """Put a value into a bound form so the re-rendered page keeps it."""
    data = form.data.copy()
    data[form.add_prefix(name)] = "" if value is None else str(value)
    form.data = data


def pdf_field_name(doc_type: str) -> str:
    return f"{doc_type}_pdf"


def expiry_field_name(doc_type: str) -> str:
    return f"{doc_type}_expiry"


class Step1MSAPartyForm(forms.ModelForm):
    class Meta:
        model = Envelope1Submission
        fields = (
            "legal_name",
            "ssm_registration_number",
            "principal_address",
            "contact_name",
            "contact_email",
            "msa_signatory_name",
            "msa_signatory_designation",
        )
        labels = {
            "legal_name": "Contractor / Company Legal Name",
            "ssm_registration_number": "Company SSM Registration Number",
            "principal_address": "Registered / Principal Address",
            "contact_name": "Contact Name",
            "contact_email": "Contact Email",
            "msa_signatory_name": "MSA Signatory Name",
            "msa_signatory_designation": "MSA Signatory Designation",
        }
        widgets = {
            "legal_name": forms.TextInput(attrs=_INPUT),
            "ssm_registration_number": forms.TextInput(attrs=_INPUT),
            "principal_address": forms.Textarea(attrs=_TEXTAREA),
            "contact_name": forms.TextInput(attrs=_INPUT),
            "contact_email": forms.EmailInput(attrs=_INPUT),
            "msa_signatory_name": forms.TextInput(attrs=_INPUT),
            "msa_signatory_designation": forms.TextInput(attrs=_INPUT),
        }

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = True
        mark_required_labels(self)


class Step2SignedMSAForm(forms.Form):
    signed_msa_pdf = forms.FileField(
        label="Signed Master Service Agreement (PDF)",
        required=False,
        widget=forms.ClearableFileInput(attrs=_FILE),
    )

    def __init__(self, *args, require_pdf: bool = True, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.require_pdf = require_pdf
        super().__init__(*args, **kwargs)
        self.fields["signed_msa_pdf"].required = require_pdf
        mark_required_labels(self)
        self.help_msa = ITEM_HELP[Envelope1Item.SIGNED_MSA]

    def clean_signed_msa_pdf(self):  # type: ignore[no-untyped-def]
        pdf = self.cleaned_data.get("signed_msa_pdf")
        if pdf:
            validate_pdf_upload(pdf)
        return pdf


class QuestionnaireStepForm(forms.Form):
    """Shared behaviour for steps 3–6: Yes/No + conditional uploads and required uploads.

    Subclasses list their items; extra plain fields are added in `add_fields()` and
    persisted in `save_fields()`.
    """

    yes_no_items: tuple[str, ...] = ()
    required_upload_items: tuple[str, ...] = ()

    def __init__(  # type: ignore[no-untyped-def]
        self,
        *args,
        submission: Envelope1Submission,
        existing: dict[str, Envelope1Document],
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.submission = submission
        self.existing = existing

        for item in self.yes_no_items:
            answer, doc_type = YES_NO_UPLOADS[item]
            self.fields[answer] = _yes_no_field(QUESTIONS[item])
            self.initial.setdefault(answer, _yes_no_initial(getattr(submission, answer)))
            self.fields[pdf_field_name(doc_type)] = forms.FileField(
                label="Upload PDF",
                required=False,
                widget=forms.ClearableFileInput(attrs=_FILE),
            )

        for item in self.required_upload_items:
            doc_type = REQUIRED_UPLOADS[item]
            has_file = doc_type in existing
            self.fields[pdf_field_name(doc_type)] = forms.FileField(
                label=UPLOAD_LABELS[doc_type],
                required=not has_file,
                widget=forms.ClearableFileInput(attrs=_FILE),
            )
            if doc_type in EXPIRY_REQUIRED_TYPES:
                self.fields[expiry_field_name(doc_type)] = forms.DateField(
                    label="Expiry date",
                    required=True,
                    initial=existing[doc_type].expiry_date if has_file else None,
                    widget=forms.DateInput(attrs={**_INPUT, "type": "date"}),
                )

        self.add_fields()
        mark_required_labels(self)
        # Conditionally required (only when "Yes"): still flag them for the vendor
        for item in self.yes_no_items:
            _answer, doc_type = YES_NO_UPLOADS[item]
            field = self.fields[pdf_field_name(doc_type)]
            field.label = required_label(field.label)

    def add_fields(self) -> None:
        """Hook for step-specific fields."""

    def save_fields(self) -> list[str]:
        """Hook: copy step-specific answers onto the submission; return changed field names."""
        return []

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        for name, field in self.fields.items():
            if isinstance(field, forms.FileField) and cleaned.get(name):
                try:
                    validate_pdf_upload(cleaned[name])
                except ValidationError as exc:
                    self.add_error(name, exc)

        for item in self.yes_no_items:
            answer, doc_type = YES_NO_UPLOADS[item]
            pdf_name = pdf_field_name(doc_type)
            if (
                cleaned.get(answer) is True
                and not cleaned.get(pdf_name)
                and doc_type not in self.existing
                and pdf_name not in self.errors
            ):
                self.add_error(pdf_name, "Upload the PDF, or answer No.")

        today = timezone.localdate()
        for item in self.required_upload_items:
            doc_type = REQUIRED_UPLOADS[item]
            exp_name = expiry_field_name(doc_type)
            expiry = cleaned.get(exp_name)
            if exp_name in self.fields and expiry and expiry < today:
                self.add_error(exp_name, "Document is already expired.")
        return cleaned

    def save(self, *, user: AbstractBaseUser | None) -> None:
        submission = self.submission
        cleaned = self.cleaned_data
        changed: list[str] = []

        for item in self.yes_no_items:
            answer, doc_type = YES_NO_UPLOADS[item]
            setattr(submission, answer, cleaned[answer])
            changed.append(answer)
            pdf = cleaned.get(pdf_field_name(doc_type))
            # A file picked before switching to "No" is ignored
            if cleaned[answer] and pdf:
                save_envelope1_pdf(
                    submission=submission, doc_type=doc_type, uploaded=pdf, user=user
                )

        for item in self.required_upload_items:
            doc_type = REQUIRED_UPLOADS[item]
            pdf = cleaned.get(pdf_field_name(doc_type))
            expiry = cleaned.get(expiry_field_name(doc_type))
            if pdf:
                save_envelope1_pdf(
                    submission=submission,
                    doc_type=doc_type,
                    uploaded=pdf,
                    user=user,
                    expiry_date=expiry,
                )
            elif expiry and doc_type in self.existing:
                doc = self.existing[doc_type]
                doc.expiry_date = expiry
                doc.save(update_fields=["expiry_date"])

        changed.extend(self.save_fields())
        submission.save(update_fields=[*changed, "updated_at"] if changed else ["updated_at"])

    def persist_uploaded_files(self, *, user: AbstractBaseUser | None) -> None:
        """Store PDFs that already passed validation when the rest of the step did not.

        The browser cannot put a chosen file back into the input after an error,
        so a missing tick or date would otherwise force a full re-upload.
        """
        cleaned = self.cleaned_data
        for item in self.yes_no_items:
            answer, doc_type = YES_NO_UPLOADS[item]
            # "No" means the upload is intentionally discarded
            if cleaned.get(answer) is False:
                continue
            pdf_name = pdf_field_name(doc_type)
            pdf = cleaned.get(pdf_name)
            if pdf and pdf_name not in self.errors:
                self.existing[doc_type] = save_envelope1_pdf(
                    submission=self.submission, doc_type=doc_type, uploaded=pdf, user=user
                )
                self.fields[pdf_name].required = False

        for item in self.required_upload_items:
            doc_type = REQUIRED_UPLOADS[item]
            pdf_name = pdf_field_name(doc_type)
            pdf = cleaned.get(pdf_name)
            exp_name = expiry_field_name(doc_type)
            expiry = cleaned.get(exp_name) if exp_name not in self.errors else None
            if pdf and pdf_name not in self.errors:
                self.existing[doc_type] = save_envelope1_pdf(
                    submission=self.submission,
                    doc_type=doc_type,
                    uploaded=pdf,
                    user=user,
                    expiry_date=expiry,
                )
                self.fields[pdf_name].required = False
            elif expiry and doc_type in self.existing:
                doc = self.existing[doc_type]
                doc.expiry_date = expiry
                doc.save(update_fields=["expiry_date"])


class Step3FinancialsForm(QuestionnaireStepForm):
    yes_no_items = (Envelope1Item.BANK_FACILITY, Envelope1Item.SUPPLIER_CREDIT)
    required_upload_items = (Envelope1Item.NO_ADVANCE, Envelope1Item.CAR_INSURANCE)


class Step4LogisticsForm(QuestionnaireStepForm):
    def add_fields(self) -> None:
        self.fields["sabah_interest"] = _yes_no_field(QUESTIONS[Envelope1Item.SABAH_INTEREST])
        self.initial.setdefault("sabah_interest", _yes_no_initial(self.submission.sabah_interest))
        for name, label in (
            ("lead_time_sea_freight_days", LEAD_TIME_SEA_LABEL),
            ("lead_time_semenanjung_days", LEAD_TIME_SEMENANJUNG_LABEL),
        ):
            self.fields[name] = forms.IntegerField(
                label=label,
                required=False,
                min_value=1,
                max_value=365,
                widget=forms.NumberInput(attrs=_DAYS),
            )
            self.initial.setdefault(name, getattr(self.submission, name))

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        if (
            cleaned.get("lead_time_sea_freight_days") is None
            and cleaned.get("lead_time_semenanjung_days") is None
            and "lead_time_sea_freight_days" not in self.errors
            and "lead_time_semenanjung_days" not in self.errors
        ):
            self.add_error(
                "lead_time_sea_freight_days",
                "Fill in at least one lead time (sea freight or Semenanjung delivery).",
            )
        return cleaned

    def save_fields(self) -> list[str]:
        names = ["sabah_interest", "lead_time_sea_freight_days", "lead_time_semenanjung_days"]
        for name in names:
            setattr(self.submission, name, self.cleaned_data.get(name))
        return names


class Step5QualityForm(QuestionnaireStepForm):
    yes_no_items = (Envelope1Item.QUALITY_PLAN, Envelope1Item.HSE_PLAN)

    def add_fields(self) -> None:
        self.fields["site_supervisor_name"] = forms.CharField(
            label="Site supervisor full name",
            max_length=150,
            widget=forms.TextInput(attrs=_INPUT),
        )
        self.initial.setdefault("site_supervisor_name", self.submission.site_supervisor_name)
        for name, item in (
            ("accepts_timestamped_reporting", Envelope1Item.TIMESTAMPED_REPORTING),
            ("accepts_metmalaysia_eot", Envelope1Item.METMALAYSIA_EOT),
        ):
            # Compliance declarations: both must be ticked before the pack can be submitted
            self.fields[name] = forms.BooleanField(
                label=DECLARATIONS[item],
                required=True,
                error_messages={"required": "Please tick this declaration to continue."},
            )
            self.initial.setdefault(name, getattr(self.submission, name))

    def save_fields(self) -> list[str]:
        sub = self.submission
        sub.site_supervisor_name = self.cleaned_data["site_supervisor_name"].strip()
        newly_accepted = not (sub.accepts_timestamped_reporting and sub.accepts_metmalaysia_eot)
        sub.accepts_timestamped_reporting = True
        sub.accepts_metmalaysia_eot = True
        if newly_accepted or sub.declarations_accepted_at is None:
            sub.declarations_accepted_at = timezone.now()
        return [
            "site_supervisor_name",
            "accepts_timestamped_reporting",
            "accepts_metmalaysia_eot",
            "declarations_accepted_at",
        ]


class Step6TrackRecordForm(QuestionnaireStepForm):
    yes_no_items = (Envelope1Item.CLIENT_REFERENCES,)
    required_upload_items = (Envelope1Item.ORG_CHART,)

    def add_fields(self) -> None:
        self.fields["has_past_projects"] = _yes_no_field(QUESTIONS[Envelope1Item.PAST_PROJECTS])
        self.initial.setdefault(
            "has_past_projects", _yes_no_initial(self.submission.has_past_projects)
        )

    def save_fields(self) -> list[str]:
        self.submission.has_past_projects = self.cleaned_data["has_past_projects"]
        return ["has_past_projects"]


# ---------------------------------------------------------------------------
# Repeatable row tables ("+ Add row")
# ---------------------------------------------------------------------------


class _RowForm(forms.Form):
    """Every table column is required for a kept row, so every header gets the red *."""

    def mark_columns(self) -> None:
        for field in self.fields.values():
            if not field.widget.is_hidden and field.label:
                field.label = required_label(field.label)


class _FileRowForm(_RowForm):
    """Row with an optional existing record (row_id) and a PDF that is required for new rows."""

    row_id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    pdf = forms.FileField(
        label="PDF",
        required=False,
        widget=forms.ClearableFileInput(attrs=_CELL_FILE),
    )
    missing_pdf_message = "Upload the PDF."

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        pdf = cleaned.get("pdf")
        if pdf:
            try:
                validate_pdf_upload(pdf)
            except ValidationError as exc:
                self.add_error("pdf", exc)
        elif not cleaned.get("row_id"):
            self.add_error("pdf", self.missing_pdf_message)
        return cleaned


class FinancialStatementRowForm(_FileRowForm):
    year = forms.IntegerField(
        label="Year",
        widget=forms.NumberInput(attrs={**_CELL_INPUT, "placeholder": "e.g. 2025"}),
    )
    missing_pdf_message = "Upload the financial statement PDF."
    field_order = ["row_id", "pdf", "year"]

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.fields["pdf"].label = "Financial Statement"
        self.fields["year"].widget.attrs["max"] = timezone.localdate().year
        self.fields["year"].widget.attrs["min"] = 2000
        self.mark_columns()

    def clean_year(self) -> int:
        year = self.cleaned_data["year"]
        if not 2000 <= year <= timezone.localdate().year:
            raise ValidationError(f"Enter a year between 2000 and {timezone.localdate().year}.")
        return year


class PrimarySupplierRowForm(_RowForm):
    structure = forms.CharField(
        label="Structure",
        max_length=200,
        widget=forms.TextInput(attrs={**_CELL_INPUT, "placeholder": "e.g. Steel monopole"}),
    )
    supplier_name = forms.CharField(
        label="Name of Supplier",
        max_length=200,
        widget=forms.TextInput(attrs={**_CELL_INPUT, "placeholder": "Supplier company name"}),
    )

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.mark_columns()


class PastProjectRowForm(_FileRowForm):
    project_name = forms.CharField(
        label="Project Name",
        max_length=255,
        widget=forms.TextInput(attrs={**_CELL_INPUT, "placeholder": "Project title"}),
    )
    missing_pdf_message = "Upload the project's supporting PDF."
    field_order = ["row_id", "project_name", "pdf"]

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.fields["pdf"].label = "Supporting Document"
        self.mark_columns()


class BaseRowFormSet(forms.BaseFormSet):
    min_rows: int = 0
    min_rows_message: str = ""

    def __init__(self, *args, rows: dict[int, Any] | None = None, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.rows = rows or {}
        # Let templates show the saved file next to each existing row
        for form in self.forms:
            form.existing_row = self.rows.get(self._row_id(form))

    @staticmethod
    def _row_id(form: forms.Form) -> int | None:
        if "row_id" not in form.fields:
            return None
        raw = form["row_id"].value()
        try:
            return int(raw) if raw not in (None, "") else None
        except (TypeError, ValueError):
            return None

    def _is_deleted(self, form: forms.Form) -> bool:
        return self.can_delete and self._should_delete_form(form)

    def active_forms(self) -> list[forms.Form]:
        """Rows the vendor kept: saved/initial rows plus filled-in new rows."""
        return [
            form
            for i, form in enumerate(self.forms)
            if not self._is_deleted(form)
            and (i < self.initial_form_count() or form.has_changed())
        ]

    def clean(self) -> None:
        if any(self.errors):
            return
        if len(self.active_forms()) < self.min_rows:
            raise ValidationError(self.min_rows_message)

    def persist_uploaded_files(
        self, *, submission: Envelope1Submission, user: AbstractBaseUser | None
    ) -> None:
        """Keep complete uploaded rows when another row or field on the step fails."""
        return


class FinancialStatementFormSet(BaseRowFormSet):
    min_rows = MIN_FINANCIAL_STATEMENTS
    min_rows_message = (
        f"Add at least {MIN_FINANCIAL_STATEMENTS} financial statements (one per year)."
    )

    def clean(self) -> None:
        super().clean()
        if any(self.errors):
            return
        years = [form.cleaned_data.get("year") for form in self.active_forms()]
        if len(years) != len(set(years)):
            raise ValidationError("Each financial statement must be for a different year.")

    def save_rows(self, *, submission: Envelope1Submission, user: AbstractBaseUser | None) -> None:
        existing = {row.pk: row for row in submission.financial_statements.all()}
        for form in self.forms:
            row = existing.get(self._row_id(form))
            if self._is_deleted(form):
                if row:
                    row.delete()
                continue
            if form not in self.active_forms():
                continue
            pdf = form.cleaned_data.get("pdf")
            doc = (
                save_envelope1_pdf(
                    submission=submission,
                    doc_type=Envelope1Document.DocType.AUDITED_FINANCIALS,
                    uploaded=pdf,
                    user=user,
                )
                if pdf
                else None
            )
            if row:
                row.year = form.cleaned_data["year"]
                if doc:
                    row.document = doc
                row.save()
            elif doc:
                FinancialStatement.objects.create(
                    submission=submission, year=form.cleaned_data["year"], document=doc
                )

    def persist_uploaded_files(
        self, *, submission: Envelope1Submission, user: AbstractBaseUser | None
    ) -> None:
        for form in self.forms:
            if self._is_deleted(form):
                continue
            cleaned = getattr(form, "cleaned_data", {})
            pdf = cleaned.get("pdf")
            year = cleaned.get("year")
            if not pdf or "pdf" in form.errors or year is None or "year" in form.errors:
                continue
            row = submission.financial_statements.filter(pk=self._row_id(form)).first()
            doc = save_envelope1_pdf(
                submission=submission,
                doc_type=Envelope1Document.DocType.AUDITED_FINANCIALS,
                uploaded=pdf,
                user=user,
            )
            if row:
                row.year = year
                row.document = doc
                row.save()
            else:
                row = FinancialStatement.objects.create(
                    submission=submission, year=year, document=doc
                )
                _set_bound_value(form, "row_id", row.pk)
            form.existing_row = row


class PrimarySupplierFormSet(BaseRowFormSet):
    min_rows = 1
    min_rows_message = "Add at least one primary supplier."

    def save_rows(self, *, submission: Envelope1Submission, user: AbstractBaseUser | None) -> None:
        # Text-only rows: replace the whole list in the order shown
        submission.primary_suppliers.all().delete()
        for position, form in enumerate(self.active_forms()):
            PrimarySupplier.objects.create(
                submission=submission,
                structure=form.cleaned_data["structure"].strip(),
                supplier_name=form.cleaned_data["supplier_name"].strip(),
                position=position,
            )


class PastProjectFormSet(BaseRowFormSet):
    min_rows = 1
    min_rows_message = "Add at least one past project, or answer No."

    def save_rows(self, *, submission: Envelope1Submission, user: AbstractBaseUser | None) -> None:
        existing = {row.pk: row for row in submission.past_projects.all()}
        active = self.active_forms()
        for form in self.forms:
            row = existing.get(self._row_id(form))
            if self._is_deleted(form):
                if row:
                    row.delete()
                continue
            if form not in active:
                continue
            pdf = form.cleaned_data.get("pdf")
            doc = (
                save_envelope1_pdf(
                    submission=submission,
                    doc_type=Envelope1Document.DocType.PAST_PROJECTS,
                    uploaded=pdf,
                    user=user,
                )
                if pdf
                else None
            )
            position = active.index(form)
            name = form.cleaned_data["project_name"].strip()
            if row:
                row.project_name = name
                row.position = position
                if doc:
                    row.document = doc
                row.save()
            elif doc:
                PastProject.objects.create(
                    submission=submission, project_name=name, document=doc, position=position
                )

    def persist_uploaded_files(
        self, *, submission: Envelope1Submission, user: AbstractBaseUser | None
    ) -> None:
        for form in self.forms:
            if self._is_deleted(form):
                continue
            cleaned = getattr(form, "cleaned_data", {})
            pdf = cleaned.get("pdf")
            name = (cleaned.get("project_name") or "").strip()
            if not pdf or "pdf" in form.errors or not name or "project_name" in form.errors:
                continue
            row = submission.past_projects.filter(pk=self._row_id(form)).first()
            doc = save_envelope1_pdf(
                submission=submission,
                doc_type=Envelope1Document.DocType.PAST_PROJECTS,
                uploaded=pdf,
                user=user,
            )
            if row:
                row.project_name = name
                row.document = doc
                row.save()
            else:
                row = PastProject.objects.create(
                    submission=submission, project_name=name, document=doc, position=0
                )
                _set_bound_value(form, "row_id", row.pk)
            form.existing_row = row


_ROW_TABLES: dict[str, tuple[type[forms.Form], type[BaseRowFormSet], str, int]] = {
    # kind: (row form, formset class, prefix, starter rows on an empty table)
    "financial_statements": (
        FinancialStatementRowForm,
        FinancialStatementFormSet,
        "fs",
        MIN_FINANCIAL_STATEMENTS,
    ),
    "primary_suppliers": (PrimarySupplierRowForm, PrimarySupplierFormSet, "sup", 1),
    "past_projects": (PastProjectRowForm, PastProjectFormSet, "proj", 1),
}


def build_row_formset(
    kind: str,
    submission: Envelope1Submission,
    data: Any = None,
    files: Any = None,
) -> BaseRowFormSet:
    """Formset for one row table, pre-filled with the submission's saved rows."""
    row_form, formset_cls, prefix, starter = _ROW_TABLES[kind]
    if kind == "financial_statements":
        saved = list(submission.financial_statements.select_related("document"))
        initial = [{"row_id": r.pk, "year": r.year} for r in saved]
    elif kind == "primary_suppliers":
        saved = list(submission.primary_suppliers.all())
        initial = [{"structure": r.structure, "supplier_name": r.supplier_name} for r in saved]
    else:
        saved = list(submission.past_projects.select_related("document"))
        initial = [{"row_id": r.pk, "project_name": r.project_name} for r in saved]
    factory = forms.formset_factory(
        row_form,
        formset=formset_cls,
        extra=max(0, starter - len(initial)),
        can_delete=True,
    )
    return factory(
        data,
        files,
        prefix=prefix,
        initial=initial,
        rows={r.pk: r for r in saved},
    )


class WithdrawalRequestForm(forms.ModelForm):
    class Meta:
        model = WithdrawalRequest
        fields = ("reason",)
        labels = {"reason": "Reason for withdrawal request"}
        widgets = {"reason": forms.Textarea(attrs={**_TEXTAREA, "rows": 4})}

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.fields["reason"].required = True
        mark_required_labels(self)
