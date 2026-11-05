"""ModelForms for the 6-step company registration wizard."""

from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from core.form_labels import mark_required_labels, required_label
from vendors.declarations import DECLARATION_TEXT, DECLARATION_VERSION
from vendors.models import (
    UNIQUE_IDENTIFIER_FIELDS,
    Company,
    identifier_key,
    normalize_identifier,
)

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

MAX_PDF_BYTES = 100 * 1024 * 1024  # 100 MB
MAX_PDF_MB = MAX_PDF_BYTES // (1024 * 1024)

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
        raise ValidationError(f"PDF must be {MAX_PDF_MB} MB or smaller.")
    pos = uploaded.tell()
    header = uploaded.read(5)
    uploaded.seek(pos)
    if header and not header.startswith(b"%PDF"):
        raise ValidationError("File does not look like a valid PDF.")


def _mark_required_labels(form: forms.BaseForm) -> None:
    """Append a red * to labels of required fields for template display."""
    mark_required_labels(form)


def _check_unique_identifier(form: forms.ModelForm, cleaned: dict, field: str) -> None:
    """Normalize a government identifier and reject it if another company holds it."""
    value = normalize_identifier(cleaned.get(field))
    cleaned[field] = value
    if not value:
        return
    key = value.replace("-", "")
    clash = Company.objects.annotate(_key=identifier_key(field)).filter(
        ~Q(**{field: ""}), _key=key
    )
    if form.instance.pk:
        clash = clash.exclude(pk=form.instance.pk)
    if clash.exists():
        form.add_error(
            field,
            f"This {UNIQUE_IDENTIFIER_FIELDS[field]} is already registered to another company. "
            "Contact Procurement if you believe this is a mistake.",
        )


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
        self.fields["ssm_document_expiry"].label = required_label("SSM Document Expiry")

    def clean_ssm_pdf(self):
        pdf = self.cleaned_data.get("ssm_pdf")
        if pdf:
            validate_pdf_upload(pdf)
        return pdf

    def clean(self) -> dict:
        cleaned = super().clean()
        _check_unique_identifier(self, cleaned, "ssm_registration_number")
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

    class Meta:
        model = Company
        fields = (
            "no_cidb_registration",
            "cidb_registration_number",
            "cidb_grade",
            "cidb_certificate_expiry",
        )
        labels = {
            "no_cidb_registration": "This company does not hold a CIDB registration",
            "cidb_registration_number": "CIDB Registration Number",
            "cidb_grade": "CIDB Grade",
            "cidb_certificate_expiry": "CIDB Certificate Expiry",
        }
        widgets = {
            "no_cidb_registration": forms.CheckboxInput(attrs=_CHECK),
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
        self.fields["no_cidb_registration"].required = False
        # Detail fields are required only when the company holds a registration (clean + UI).
        for name in ("cidb_registration_number", "cidb_grade", "cidb_certificate_expiry", "cidb_pdf"):
            self.fields[name].required = False
        _require_future_or_today(self.fields["cidb_certificate_expiry"])
        _mark_required_labels(self)
        for name in ("cidb_registration_number", "cidb_grade", "cidb_certificate_expiry"):
            self.fields[name].label = required_label(self.fields[name].label or name)
        if self.require_pdf:
            self.fields["cidb_pdf"].label = required_label("CIDB certificate (PDF)")

    def _opted_out(self) -> bool:
        return bool(self.data.get("no_cidb_registration"))

    def clean_cidb_pdf(self):
        if self._opted_out():
            return None
        pdf = self.cleaned_data.get("cidb_pdf")
        if pdf:
            validate_pdf_upload(pdf)
        return pdf

    def clean_cidb_certificate_expiry(self):
        if self._opted_out():
            return None
        expiry = self.cleaned_data.get("cidb_certificate_expiry")
        if expiry and expiry < timezone.localdate():
            raise ValidationError("CIDB certificate is already expired.")
        return expiry

    def clean(self) -> dict:
        cleaned = super().clean()
        if cleaned.get("no_cidb_registration"):
            cleaned["cidb_registration_number"] = ""
            cleaned["cidb_grade"] = ""
            cleaned["cidb_certificate_expiry"] = None
            cleaned["cidb_pdf"] = None
            return cleaned
        for field in ("cidb_registration_number", "cidb_grade", "cidb_certificate_expiry"):
            if not cleaned.get(field):
                self.add_error(field, "Required unless this company does not hold a CIDB registration.")
        if self.require_pdf and not cleaned.get("cidb_pdf"):
            self.add_error("cidb_pdf", "CIDB certificate PDF is required.")
        _check_unique_identifier(self, cleaned, "cidb_registration_number")
        return cleaned

    def save(self, commit: bool = True) -> Company:
        company = super().save(commit=False)
        if self.cleaned_data.get("no_cidb_registration"):
            company.cidb_registration_number = ""
            company.cidb_grade = ""
            company.cidb_certificate_expiry = None
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
            "st_license_number",
            "st_certificate_expiry",
        )
        labels = {
            "includes_electrical_work": "Does your scope include electrical work?",
            "st_license_number": "ST License Number",
            "st_certificate_expiry": "ST Certificate Expiry",
        }
        widgets = {
            "includes_electrical_work": forms.RadioSelect(
                choices=((True, "Yes"), (False, "No")),
                attrs=_RADIO,
            ),
            "st_license_number": forms.TextInput(attrs=_INPUT),
            "st_certificate_expiry": forms.DateInput(attrs={**_INPUT, "type": "date"}),
        }

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.require_pdf = kwargs.pop("require_pdf", False)
        super().__init__(*args, **kwargs)
        self.fields["includes_electrical_work"].required = True
        # Detail fields only required when Yes (clean + UI)
        for name in ("st_license_number", "st_certificate_expiry", "st_pdf"):
            self.fields[name].required = False
        _require_future_or_today(self.fields["st_certificate_expiry"])
        _mark_required_labels(self)
        for name in ("st_license_number", "st_certificate_expiry"):
            self.fields[name].label = required_label(self.fields[name].label or name)
        if self.require_pdf:
            self.fields["st_pdf"].label = required_label("ST license (PDF)")

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
            for field in ("st_license_number", "st_certificate_expiry"):
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
            # Only checked when in scope — the field is cleared below when the answer is No
            _check_unique_identifier(self, cleaned, "st_license_number")
        else:
            # Clear ST details when scope is No
            cleaned["st_license_number"] = ""
            cleaned["st_certificate_expiry"] = None
            cleaned["st_pdf"] = None
        return cleaned

    def save(self, commit: bool = True) -> Company:
        company = super().save(commit=False)
        if not self.cleaned_data.get("includes_electrical_work"):
            company.st_license_number = ""
            company.st_certificate_expiry = None
        if commit:
            company.save()
        return company


class Step5LHDNForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = (
            "lhdn_tin",
            "bank_name",
            "bank_name_other",
            "bank_account_number",
            "bank_account_name",
        )
        labels = {
            "lhdn_tin": "LHDN TIN",
            "bank_name": "Bank Name",
            "bank_name_other": "Other Bank Name",
            "bank_account_number": "Bank Account Number",
            "bank_account_name": "Bank Account Name",
        }
        widgets = {
            "lhdn_tin": forms.TextInput(attrs=_INPUT),
            "bank_name": forms.Select(attrs=_INPUT),
            "bank_name_other": forms.TextInput(attrs=_INPUT),
            "bank_account_number": forms.TextInput(
                attrs={**_INPUT, "inputmode": "numeric", "placeholder": "e.g. 5642 1234 5678"}
            ),
            "bank_account_name": forms.TextInput(
                attrs={**_INPUT, "placeholder": "As printed on the bank statement"}
            ),
        }

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        for name in ("lhdn_tin", "bank_name", "bank_account_number", "bank_account_name"):
            self.fields[name].required = True
        self.fields["bank_name"].choices = [("", "Select bank")] + list(Company.Bank.choices)
        self.fields["bank_name_other"].required = False
        _mark_required_labels(self)
        self.fields["bank_name_other"].label = required_label("Other Bank Name")

    def clean_bank_account_number(self) -> str:
        # Payment runs need a clean numeric account number; spaces/dashes are display-only
        raw = self.cleaned_data.get("bank_account_number") or ""
        digits = raw.replace(" ", "").replace("-", "")
        if not digits.isdigit() or not 6 <= len(digits) <= 20:
            raise ValidationError("Enter 6–20 digits (spaces and dashes are allowed).")
        return digits

    def clean(self) -> dict:
        cleaned = super().clean()
        _check_unique_identifier(self, cleaned, "lhdn_tin")
        if cleaned.get("bank_name") == Company.Bank.OTHER:
            if not (cleaned.get("bank_name_other") or "").strip():
                self.add_error("bank_name_other", "Enter the bank name.")
        else:
            cleaned["bank_name_other"] = ""
        return cleaned


class Step6DeclarationForm(forms.ModelForm):
    declaration_accepted = forms.BooleanField(
        required=True,
        label="I agree to the declaration above",
        widget=forms.CheckboxInput(attrs=_CHECK),
    )

    class Meta:
        model = Company
        fields = ("declaration_accepted",)

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.declaration_text = DECLARATION_TEXT
        self.declaration_version = DECLARATION_VERSION
