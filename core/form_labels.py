"""Required-field label marker shared by every form (red asterisk)."""

from __future__ import annotations

from django import forms
from django.utils.html import format_html
from django.utils.safestring import SafeString

_MARK_CLASS = "text-rose-600"


def is_marked(label: object) -> bool:
    return isinstance(label, SafeString) and _MARK_CLASS in label


def required_label(label: object) -> SafeString:
    """Escape the label text and append a red `*` (templates render labels unescaped as HTML)."""
    if is_marked(label):
        return label  # type: ignore[return-value]
    text = str(label).rstrip()
    if text.endswith("*"):
        text = text[:-1].rstrip()
    return format_html('{} <span class="{}" aria-hidden="true">*</span>', text, _MARK_CLASS)


def mark_required_labels(form: forms.BaseForm) -> None:
    for field in form.fields.values():
        if field.required and field.label:
            field.label = required_label(field.label)
