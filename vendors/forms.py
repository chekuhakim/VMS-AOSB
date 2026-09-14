"""ModelForms for the 6-step company registration wizard."""

from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from vendors.declarations import DECLARATION_TEXT, DECLARATION_VERSION
from vendors.models import Company

# Shared Tailwind-friendly widget attrs
_INPUT = {
    "class": (
        "mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 "
        "text-sm shadow-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
    )
}
_CHECK = {
    "class": "rounded border-slate-300 text-brand focus:ring-brand",
}
_FILE = {
    "class": "mt-1.5 block w-full text-sm text-slate-600 file:mr-3 file:rounded-lg "
    "file:border-0 file:bg-brand-50 file:px-3 file:py-2 file:text-sm file:font-medium file:text-brand",
    "accept": "application/pdf",
}

MAX_PDF_BYTES = 10 * 1024 * 1024  # 10 MB


def validate_pdf_upload(uploaded) -> None:  # type: ignore[no-untyped-def]
    """Reject non-PDFs and oversized files in Form.clean()."""
    if uploaded is None:
        return
    name = getattr(uploaded, "name", "") or ""
    content_type = getattr(uploaded, "content_type", "") or ""
    if not name.lower().endswith(".pdf") and content_type not in (
        "application/pdf",
        "application/x-pdf",
    ):
        raise ValidationError("Only PDF files are allowed.")
    if uploaded.size > MAX_PDF_BYTES:
        raise ValidationError("PDF must be 10 MB or smaller.")
    # Light magic-byte check when possible
    pos = uploaded.tell()
    header = uploaded.read(5)
    uploaded.seek(pos)
    if header and not header.startswith(b"%PDF"):
        raise ValidationError("File does not look like a valid PDF.")


class Step1ProfileForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = ("name", "primary_contact_name", "contact_number", "official_email")
        widgets = {
            "name": forms.TextInput(attrs=_INPUT),
            "primary_contact_name": forms.TextInput(attrs=_INPUT),
            "contact_number": forms.TextInput(attrs=_INPUT),
            "official_email": forms.EmailInput(attrs=_INPUT),
        }

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = True


class Step2SSMForm(forms.ModelForm):
    ssm_pdf = forms.FileField(required=False, widget=forms.ClearableFileInput(attrs=_FILE))

    class Meta:
        model = Company
        fields = (
            "ssm_registration_number",
            "date_of_incorporation",
            "is_enterprise",
            "ssm_document_expiry",
        )
        widgets = {
            "ssm_registration_number": forms.TextInput(attrs=_INPUT),
            "date_of_incorporation": forms.DateInput(attrs={**_INPUT, "type": "date"}),
            "is_enterprise": forms.CheckboxInput(attrs=_CHECK),
            "ssm_document_expiry": forms.DateInput(attrs={**_INPUT, "type": "date"}),
        }

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.require_pdf = kwargs.pop("require_pdf", True)
        super().__init__(*args, **kwargs)
        self.fields["ssm_registration_number"].required = True
        self.fields["date_of_incorporation"].required = True
        self.fields["ssm_pdf"].required = self.require_pdf

    def clean_ssm_pdf(self):
        pdf = self.cleaned_data.get("ssm_pdf")
        if pdf:
            validate_pdf_upload(pdf)
        return pdf

    def clean(self) -> dict:
        cleaned = super().clean()
        # Enterprises must supply a future (or today) expiry on the statutory pack
        if cleaned.get("is_enterprise"):
            expiry = cleaned.get("ssm_document_expiry")
            if not expiry:
                self.add_error("ssm_document_expiry", "Required for enterprises.")
            elif expiry < timezone.localdate():
                self.add_error("ssm_document_expiry", "Document is already expired.")
        return cleaned


class Step3CIDBForm(forms.ModelForm):
    cidb_pdf = forms.FileField(required=False, widget=forms.ClearableFileInput(attrs=_FILE))
    # Multi-select presented as comma-separated or multiple checkboxes in template
    cidb_categories_input = forms.MultipleChoiceField(
        required=True,
        choices=[
            ("CE", "Civil Engineering (CE)"),
            ("B", "Building (B)"),
            ("ME", "Mechanical & Electrical (ME)"),
            ("PW", "Plant & Machinery / Works"),
        ],
        widget=forms.CheckboxSelectMultiple(attrs={"class": "space-y-2"}),
    )

    class Meta:
        model = Company
        fields = (
            "cidb_registration_number",
            "cidb_grade",
            "cidb_certificate_expiry",
        )
        widgets = {
            "cidb_registration_number": forms.TextInput(attrs=_INPUT),
            "cidb_grade": forms.TextInput(attrs={**_INPUT, "placeholder": "e.g. G7"}),
            "cidb_certificate_expiry": forms.DateInput(attrs={**_INPUT, "type": "date"}),
        }

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.require_pdf = kwargs.pop("require_pdf", True)
        super().__init__(*args, **kwargs)
        for name in ("cidb_registration_number", "cidb_grade", "cidb_certificate_expiry"):
            self.fields[name].required = True
        self.fields["cidb_pdf"].required = self.require_pdf
        if self.instance and self.instance.cidb_categories:
            self.fields["cidb_categories_input"].initial = self.instance.cidb_categories

    def clean_cidb_pdf(self):
        pdf = self.cleaned_data.get("cidb_pdf")
        if pdf:
            validate_pdf_upload(pdf)
        return pdf

    def clean_cidb_certificate_expiry(self):
        expiry = self.cleaned_data["cidb_certificate_expiry"]
        if expiry and expiry < timezone.localdate():
            raise ValidationError("CIDB certificate is already expired.")
        return expiry

    def save(self, commit: bool = True) -> Company:
        company = super().save(commit=False)
        company.cidb_categories = self.cleaned_data.get("cidb_categories_input") or []
        if commit:
            company.save()
        return company


class Step4STForm(forms.ModelForm):
    st_pdf = forms.FileField(required=False, widget=forms.ClearableFileInput(attrs=_FILE))

    class Meta:
        model = Company
        fields = (
            "includes_electrical_work",
            "st_contractor_class",
            "st_license_number",
            "st_certificate_expiry",
            "chargeman_name",
        )
        widgets = {
            "includes_electrical_work": forms.RadioSelect(
                choices=((True, "Yes — includes electrical work"), (False, "No"))
            ),
            "st_contractor_class": forms.TextInput(attrs=_INPUT),
            "st_license_number": forms.TextInput(attrs=_INPUT),
            "st_certificate_expiry": forms.DateInput(attrs={**_INPUT, "type": "date"}),
            "chargeman_name": forms.TextInput(attrs=_INPUT),
        }

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.require_pdf = kwargs.pop("require_pdf", False)
        super().__init__(*args, **kwargs)
        self.fields["includes_electrical_work"].required = True

    def clean(self) -> dict:
        cleaned = super().clean()
        if cleaned.get("includes_electrical_work"):
            for field in (
                "st_contractor_class",
                "st_license_number",
                "st_certificate_expiry",
                "chargeman_name",
            ):
                if not cleaned.get(field):
                    self.add_error(field, "Required when electrical work is in scope.")
            pdf = cleaned.get("st_pdf")
            if self.require_pdf and not pdf:
                self.add_error("st_pdf", "ST license PDF is required.")
            if pdf:
                try:
                    validate_pdf_upload(pdf)
                except ValidationError as exc:
                    self.add_error("st_pdf", exc)
            expiry = cleaned.get("st_certificate_expiry")
            if expiry and expiry < timezone.localdate():
                self.add_error("st_certificate_expiry", "ST license is already expired.")
        return cleaned


class Step5LHDNForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = (
            "lhdn_tin",
            "sst_registration_number",
            "myinvois_readiness",
            "bank_account_for_payment",
        )
        widgets = {
            "lhdn_tin": forms.TextInput(attrs=_INPUT),
            "sst_registration_number": forms.TextInput(attrs=_INPUT),
            "myinvois_readiness": forms.Select(attrs=_INPUT),
            "bank_account_for_payment": forms.TextInput(attrs=_INPUT),
        }

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = True


class Step6HSEForm(forms.ModelForm):
    declaration_accepted = forms.BooleanField(
        required=True,
        label="I agree to the declaration above",
        widget=forms.CheckboxInput(attrs=_CHECK),
    )

    class Meta:
        model = Company
        fields = (
            "hse_representative_name",
            "public_liability_coverage",
            "declaration_accepted",
        )
        widgets = {
            "hse_representative_name": forms.TextInput(attrs=_INPUT),
            "public_liability_coverage": forms.TextInput(
                attrs={**_INPUT, "placeholder": "e.g. RM 1,000,000"}
            ),
        }

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.fields["hse_representative_name"].required = True
        self.fields["public_liability_coverage"].required = True
        self.declaration_text = DECLARATION_TEXT
        self.declaration_version = DECLARATION_VERSION
