"""Staff forms — Envelope 1 per-step evaluation."""

from __future__ import annotations

from typing import Any

from django import forms

from staff.models import Envelope1ItemEvaluation

_RESULT_CHOICES = [
    (Envelope1ItemEvaluation.Result.PASS, "Pass"),
    (Envelope1ItemEvaluation.Result.FAIL, "Fail"),
]


class EvaluationStepForm(forms.Form):
    """Pass / Fail + remark for every checklist item on one wizard step."""

    def __init__(
        self,
        *args: Any,
        evaluations: list[Envelope1ItemEvaluation],
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.evaluations = evaluations
        for ev in evaluations:
            # Unselected radios post nothing — treated as "pending"
            self.fields[f"result_{ev.pk}"] = forms.ChoiceField(
                choices=_RESULT_CHOICES,
                required=False,
                initial=ev.result if ev.result != Envelope1ItemEvaluation.Result.PENDING else "",
            )
            self.fields[f"note_{ev.pk}"] = forms.CharField(
                required=False,
                initial=ev.note,
                max_length=2000,
            )

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        for ev in self.evaluations:
            result = cleaned.get(f"result_{ev.pk}") or Envelope1ItemEvaluation.Result.PENDING
            note = (cleaned.get(f"note_{ev.pk}") or "").strip()
            cleaned[f"result_{ev.pk}"] = result
            cleaned[f"note_{ev.pk}"] = note
            # Vendors see the remark as the reason — a Fail without one is not actionable
            if result == Envelope1ItemEvaluation.Result.FAIL and not note:
                self.add_error(f"note_{ev.pk}", "A remark is required when marking Fail.")
        return cleaned

    def item_state(self, ev: Envelope1ItemEvaluation) -> dict[str, Any]:
        """Current (posted or saved) values for rendering one item card."""
        rname, nname = f"result_{ev.pk}", f"note_{ev.pk}"
        if self.is_bound:
            result = self.data.get(rname, "") or Envelope1ItemEvaluation.Result.PENDING
            note = self.data.get(nname, "")
        else:
            result, note = ev.result, ev.note
        return {
            "result_name": rname,
            "note_name": nname,
            "selected": result,
            "note": note,
            "note_error": (self.errors.get(nname) or [""])[0],
        }

    def changed_items(self) -> list[tuple[Envelope1ItemEvaluation, str, str]]:
        """Items whose result or remark differs from what is stored (avoids audit noise)."""
        changes = []
        for ev in self.evaluations:
            result = self.cleaned_data[f"result_{ev.pk}"]
            note = self.cleaned_data[f"note_{ev.pk}"]
            if result != ev.result or note != (ev.note or ""):
                changes.append((ev, result, note))
        return changes
