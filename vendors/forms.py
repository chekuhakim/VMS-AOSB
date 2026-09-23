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
    "class": "h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand",
}
_FILE = {
    "class": (
        "mt-1.5 block w-full text-sm text-slate-600 file:mr-3 file:rounded-lg "
        "file:border-0 file:bg-brand-50 file:px-3 file:py-2 file:text-sm "
        "file:font-medium file:text-brand"
    ),
    "accept": "application/pdf",
}
_RADIO = {"class": "h-4 w-4 border-slate-300 text-brand focus:ring-brand"}

MAX_PDF_BYTES = 10 * 1024 * 1024  # 10 MB

CIDB_GRADE_CHOICES = [
    ("", "Select CIDB grade"),
    ("G1", "G1"),
    ("G2", "G2"),
    ("G3", "G3"),
    ("G4", "G4"),
    ("G5", "G5"),
    ("G6", "G6"),
    ("G7", "G7"),
]


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
    pos = uploaded.tell()
    header = uploaded.read(5)
    uploaded.seek(pos)
    if header and not header.startswith(b"%PDF"):
        raise ValidationError("File does not look like a valid PDF.")


def _mark_required_labels(form: forms.BaseForm) -> None:
    """Append * to labels of required fields for template display."""
    for field in form.fields.values():
        if field.required and field.label and not str(field.label).endswith("*"):
            field.label = f"{field.label} *"


def _require_future_or_today(field: forms.Field) -> None:
    """HTML min=today so past expiry fails checkValidity (matches server clean())."""
    field.widget.attrs["min"] = timezone.localdate().isoformat()


class Step1ProfileForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = ("name", "primary_contact_name", "contact_number", "official_email")
        labels = {
            "name": "Registered Company Name",
            "primary_contact_name": "Primary Contact Person",
            "contact_number": "Contact Number",
            "official_email": "Official Email",
        }
        widgets = {
            "name": forms.TextInput(
                attrs={**_INPUT, "placeholder": "e.g. Cahaya Sdn Bhd"}
            ),
            "primary_contact_name": forms.TextInput(
                attrs={**_INPUT, "placeholder": "e.g. Abu bin Bakar"}
            ),
            "contact_number": forms.TextInput(
                attrs={**_INPUT, "placeholder": "e.g. 0123456789"}
            ),
            "official_email": forms.EmailInput(
                attrs={**_INPUT, "placeholder": "e.g. abu@cahaya.com.my"}
            ),
        }

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = True
        _mark_required_labels(self)


class Step2SSMForm(forms.ModelForm):
    ssm_pdf = forms.FileField(
        required=False,
        label="SSM document (PDF)",
        widget=forms.ClearableFileInput(attrs=_FILE),
    )

    class Meta:
        model = Company
        fields = (
            "ssm_registration_number",
            "date_of_incorporation",
            "is_enterprise",
            "ssm_document_expiry",
        )
        labels = {
            "ssm_registration_number": "SSM Registration Number",
            "date_of_incorporation": "Date of Incorporation",
            "is_enterprise": "This company is an enterprise (requires SSM document expiry)",
            "ssm_document_expiry": "SSM Document Expiry",
        }
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
        self.fields["is_enterprise"].required = False
        # Expiry only required when enterprise is checked (enforced in clean + UI)
        self.fields["ssm_document_expiry"].required = False
        self.fields["ssm_pdf"].required = self.require_pdf
        _require_future_or_today(self.fields["ssm_document_expiry"])
        _mark_required_labels(self)
        # Enterprise checkbox is optional — do not force * on its label
        self.fields["is_enterprise"].label = (
            "This company is an enterprise (requires SSM document expiry)"
        )
        # Expiry asterisk shown in template when visible; keep base label clean
        self.fields["ssm_document_expiry"].label = "SSM Document Expiry *"

    def clean_ssm_pdf(self):
        pdf = self.cleaned_data.get("ssm_pdf")
        if pdf:
            validate_pdf_upload(pdf)
        return pdf

    def clean(self) -> dict:
        cleaned = super().clean()
        if cleaned.get("is_enterprise"):
            expiry = cleaned.get("ssm_document_expiry")
            if not expiry:
                self.add_error("ssm_document_expiry", "Required for enterprises.")
            elif expiry < timezone.localdate():
                self.add_error("ssm_document_expiry", "Document is already expired.")
        else:
            cleaned["ssm_document_expiry"] = None
        return cleaned


class Step3CIDBForm(forms.ModelForm):
    cidb_pdf = forms.FileField(
        required=False,
        label="CIDB certificate (PDF)",
        widget=forms.ClearableFileInput(attrs=_FILE),
    )
    cidb_categories_input = forms.MultipleChoiceField(
        required=True,
        label="CIDB Categories",
        choices=[
            ("CE", "Civil Engineering (CE)"),
            ("B", "Building (B)"),
            ("ME", "Mechanical & Electrical (ME)"),
            ("PW", "Plant & Machinery / Works"),
        ],
        widget=forms.CheckboxSelectMultiple(
            attrs={"class": "space-y-2 text-sm text-slate-700"}
        ),
    )

    class Meta:
        model = Company
        fields = (
            "cidb_registration_number",
            "cidb_grade",
            "cidb_certificate_expiry",
        )
        labels = {
            "cidb_registration_number": "CIDB Registration Number",
            "cidb_grade": "CIDB Grade",
            "cidb_certificate_expiry": "CIDB Certificate Expiry",
        }
        widgets = {
            "cidb_registration_number": forms.TextInput(attrs=_INPUT),
            "cidb_grade": forms.Select(attrs=_INPUT, choices=CIDB_GRADE_CHOICES),
            "cidb_certificate_expiry": forms.DateInput(attrs={**_INPUT, "type": "date"}),
        }

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.require_pdf = kwargs.pop("require_pdf", True)
        super().__init__(*args, **kwargs)
        self.fields["cidb_grade"].widget = forms.Select(
            attrs=_INPUT, choices=CIDB_GRADE_CHOICES
        )
        self.fields["cidb_grade"].choices = CIDB_GRADE_CHOICES
        for name in ("cidb_registration_number", "cidb_grade", "cidb_certificate_expiry"):
            self.fields[name].required = True
        self.fields["cidb_pdf"].required = self.require_pdf
        _require_future_or_today(self.fields["cidb_certificate_expiry"])
        if self.instance and self.instance.cidb_categories:
            self.fields["cidb_categories_input"].initial = self.instance.cidb_categories
        _mark_required_labels(self)

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
    st_pdf = forms.FileField(
        required=False,
        label="ST license (PDF)",
        widget=forms.ClearableFileInput(attrs=_FILE),
    )

    class Meta:
        model = Company
        fields = (
            "includes_electrical_work",
            "st_contractor_class",
            "st_license_number",
            "st_certificate_expiry",
            "chargeman_name",
        )
        labels = {
            "includes_electrical_work": "Does your scope include electrical work?",
            "st_contractor_class": "ST Contractor Class",
            "st_license_number": "ST License Number",
            "st_certificate_expiry": "ST Certificate Expiry",
            "chargeman_name": "Chargeman Name",
        }
        widgets = {
            "includes_electrical_work": forms.RadioSelect(
                choices=((True, "Yes"), (False, "No")),
                attrs=_RADIO,
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
        # Detail fields only required when Yes (clean + UI)
        for name in (
            "st_contractor_class",
            "st_license_number",
            "st_certificate_expiry",
            "chargeman_name",
            "st_pdf",
        ):
            self.fields[name].required = False
        _require_future_or_today(self.fields["st_certificate_expiry"])
        _mark_required_labels(self)
        for name in (
            "st_contractor_class",
            "st_license_number",
            "st_certificate_expiry",
            "chargeman_name",
        ):
            label = self.fields[name].label or name
            if not str(label).endswith("*"):
                self.fields[name].label = f"{label} *"
        if self.require_pdf:
            self.fields["st_pdf"].label = "ST license (PDF) *"

    def clean(self) -> dict:
        cleaned = super().clean()
        # BooleanField(null=True) accepts empty as None even when required=True
        electrical = cleaned.get("includes_electrical_work")
        if electrical is None:
            self.add_error(
                "includes_electrical_work",
                "Please select Yes or No.",
            )
            return cleaned
        if electrical:
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
        else:
            # Clear ST details when scope is No
            cleaned["st_contractor_class"] = ""
            cleaned["st_license_number"] = ""
            cleaned["st_certificate_expiry"] = None
            cleaned["chargeman_name"] = ""
            cleaned["st_pdf"] = None
        return cleaned

    def save(self, commit: bool = True) -> Company:
        company = super().save(commit=False)
        if not self.cleaned_data.get("includes_electrical_work"):
            company.st_contractor_class = ""
            company.st_license_number = ""
            company.st_certificate_expiry = None
            company.chargeman_name = ""
        if commit:
            company.save()
        return company


class Step5LHDNForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = (
            "lhdn_tin",
            "sst_registration_number",
            "myinvois_readiness",
            "bank_account_for_payment",
        )
        labels = {
            "lhdn_tin": "LHDN TIN",
            "sst_registration_number": "SST Registration Number",
            "myinvois_readiness": "MyInvois Readiness",
            "bank_account_for_payment": "Bank Account for Payment",
        }
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
        _mark_required_labels(self)


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
        labels = {
            "hse_representative_name": "HSE Representative Name",
            "public_liability_coverage": "Public Liability Coverage",
        }
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
        _mark_required_labels(self)
