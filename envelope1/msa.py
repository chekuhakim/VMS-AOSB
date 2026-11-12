"""Generate MSA and related declaration PDFs from HTML templates and saved party details."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.template import Context, Template
from django.utils import timezone
from weasyprint import HTML

MSA_DIR = Path(__file__).resolve().parent.parent / "MSA"
MSA_HTML = MSA_DIR / "msa.html"
NO_ADVANCE_HTML = MSA_DIR / "no-advance.html"


def _legal_name(party: Any) -> str:
    """Company uses `name`; legacy Envelope1Submission used `legal_name`."""
    return (getattr(party, "legal_name", "") or getattr(party, "name", "") or "").strip()


def _safe_company_label(party: Any) -> str:
    cleaned = "".join(" " if ch in '\\/:*?"<>|\r\n' else ch for ch in _legal_name(party))
    cleaned = " ".join(cleaned.split())
    return cleaned or "Company"


def msa_download_filename(party: Any) -> str:
    """Save-as name for the agreement: '{company name} - MSA.pdf'."""
    return f"{_safe_company_label(party)} - MSA.pdf"


def no_advance_download_filename(party: Any) -> str:
    """Save-as name: '{company name} - No Advance Payment Declaration.pdf'."""
    return f"{_safe_company_label(party)} - No Advance Payment Declaration.pdf"


def _party_context(party: Any) -> dict[str, str]:
    today = timezone.localdate()
    address = " ".join((getattr(party, "principal_address", "") or "").split())
    registration_type = getattr(party, "registration_type", None)
    if registration_type == "individual":
        company_no = getattr(party, "ic_number", "") or ""
    else:
        company_no = getattr(party, "ssm_registration_number", "") or ""
    return {
        "day": f"{today.day:02d}",
        "month": today.strftime("%B"),
        "year": str(today.year),
        "company_name": _legal_name(party),
        "company_no": company_no,
        "address": address,
        "registration_type": str(registration_type or ""),
        "signatory_name": getattr(party, "msa_signatory_name", "") or "",
        "signatory_designation": getattr(party, "msa_signatory_designation", "") or "",
    }


def build_draft_msa_pdf(party: Any) -> bytes:
    """Return the Master Service Agreement as a PDF, filled with saved party details."""
    html = render_draft_msa_html(party)
    return HTML(string=html, base_url=str(MSA_DIR)).write_pdf()


def render_draft_msa_html(party: Any) -> str:
    """Fill the agreement blanks from the vendor's saved MSA party details."""
    template = Template(MSA_HTML.read_text(encoding="utf-8"))
    ctx = _party_context(party)
    return template.render(
        Context(
            {
                k: v
                for k, v in ctx.items()
                if k in (
                    "day",
                    "month",
                    "year",
                    "company_name",
                    "company_no",
                    "address",
                    "registration_type",
                )
            }
        )
    )


def build_no_advance_pdf(party: Any) -> bytes:
    """Pre-filled 1.4 No Advance Payment Declaration for the vendor to sign and upload."""
    html = render_no_advance_html(party)
    return HTML(string=html, base_url=str(MSA_DIR)).write_pdf()


def render_no_advance_html(party: Any) -> str:
    template = Template(NO_ADVANCE_HTML.read_text(encoding="utf-8"))
    return template.render(Context(_party_context(party)))


# ---------------------------------------------------------------------------
# Legacy plain-text declaration (superseded by MSA/no-advance.html + WeasyPrint):
#
#   "1. The company does not require any advance payment..."
#   "2. The company has sufficient working capital..."
#   "3. Payment will only be claimed according to the agreed payment terms."
#   Footer: "Sign, stamp, and upload this declaration in Envelope 1, item 1.4."
# ---------------------------------------------------------------------------
