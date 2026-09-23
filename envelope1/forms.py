"""ModelForms for Envelope 1 wizard steps."""

from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from envelope1.checklist import DOC_HELP, EXPIRY_REQUIRED_TYPES, STEP_DOC_TYPES
from envelope1.models import Envelope1Document, Envelope1Submission, WithdrawalRequest
from vendors.forms import MAX_PDF_BYTES, validate_pdf_upload

_INPUT = {
    "class": (
        "mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 "
        "text-sm shadow-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
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


def _mark_required(form: forms.BaseForm) -> None:
    for field in form.fields.values():
        if field.required and field.label and not str(field.label).endswith("*"):
            field.label = f"{field.label} *"


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
        _mark_required(self)


class Step2SignedMSAForm(forms.Form):
    msa_effective_date = forms.DateField(
        label="MSA effective date *",
        widget=forms.DateInput(attrs={**_INPUT, "type": "date"}),
    )
    signed_msa_pdf = forms.FileField(
        label="Signed MSA (PDF)",
        required=False,
        widget=forms.ClearableFileInput(attrs=_FILE),
    )

    def __init__(self, *args, require_pdf: bool = True, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.require_pdf = require_pdf
        super().__init__(*args, **kwargs)
        self.fields["signed_msa_pdf"].required = require_pdf
        if require_pdf:
            self.fields["signed_msa_pdf"].label = "Signed MSA (PDF) *"
        self.help_msa = DOC_HELP[Envelope1Document.DocType.SIGNED_MSA]

    def clean_signed_msa_pdf(self):
        pdf = self.cleaned_data.get("signed_msa_pdf")
        if pdf:
            validate_pdf_upload(pdf)
        return pdf

    def clean_msa_effective_date(self):
        value = self.cleaned_data["msa_effective_date"]
        if value > timezone.localdate():
            raise ValidationError("Effective date cannot be in the future.")
        return value


class DocumentPackForm(forms.Form):
    """Dynamic PDF (+ optional expiry) fields for steps 3–6."""

    def __init__(  # type: ignore[no-untyped-def]
        self,
        *args,
        doc_types: list[str],
        existing: dict[str, Envelope1Document],
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.doc_types = doc_types
        self.existing = existing
        self.doc_meta: list[dict] = []

        for doc_type in doc_types:
            label = dict(Envelope1Document.DocType.choices).get(doc_type, doc_type)
            has_file = doc_type in existing
            pdf_name = f"pdf_{doc_type}"
            exp_name = f"expiry_{doc_type}"
            needs_expiry = doc_type in EXPIRY_REQUIRED_TYPES

            self.fields[pdf_name] = forms.FileField(
                label=f"{label}" + (" *" if not has_file else ""),
                required=not has_file,
                widget=forms.ClearableFileInput(attrs=_FILE),
            )
            if needs_expiry:
                initial_exp = existing[doc_type].expiry_date if has_file else None
                self.fields[exp_name] = forms.DateField(
                    label=f"{label} expiry *",
                    required=True,
                    initial=initial_exp,
                    widget=forms.DateInput(attrs={**_INPUT, "type": "date"}),
                )
            self.doc_meta.append(
                {
                    "doc_type": doc_type,
                    "label": label,
                    "help": DOC_HELP.get(doc_type, ""),
                    "pdf_name": pdf_name,
                    "exp_name": exp_name if needs_expiry else "",
                    "has_file": has_file,
                    "needs_expiry": needs_expiry,
                }
            )

    def clean(self) -> dict:
        cleaned = super().clean()
        today = timezone.localdate()
        for meta in self.doc_meta:
            pdf = cleaned.get(meta["pdf_name"])
            if pdf:
                try:
                    validate_pdf_upload(pdf)
                except ValidationError as exc:
                    self.add_error(meta["pdf_name"], exc)
            if meta["needs_expiry"]:
                expiry = cleaned.get(meta["exp_name"])
                if expiry and expiry < today:
                    self.add_error(meta["exp_name"], "Document is already expired.")
                if pdf or not meta["has_file"]:
                    if not expiry:
                        self.add_error(meta["exp_name"], "Expiry date is required.")
        return cleaned


class WithdrawalRequestForm(forms.ModelForm):
    class Meta:
        model = WithdrawalRequest
        fields = ("reason",)
        labels = {"reason": "Reason for withdrawal request *"}
        widgets = {"reason": forms.Textarea(attrs={**_TEXTAREA, "rows": 4})}

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.fields["reason"].required = True
