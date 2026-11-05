"""Generate MSA and related declaration PDFs from HTML templates and saved party details."""

from __future__ import annotations

from pathlib import Path

from django.template import Context, Template
from django.utils import timezone
from weasyprint import HTML

from envelope1.models import Envelope1Submission

MSA_DIR = Path(__file__).resolve().parent.parent / "MSA"
MSA_HTML = MSA_DIR / "msa.html"
NO_ADVANCE_HTML = MSA_DIR / "no-advance.html"


def _safe_company_label(submission: Envelope1Submission) -> str:
    raw = (submission.legal_name or "").strip()
    cleaned = "".join(" " if ch in '\\/:*?"<>|\r\n' else ch for ch in raw)
    cleaned = " ".join(cleaned.split())
    return cleaned or "Company"


def msa_download_filename(submission: Envelope1Submission) -> str:
    """Save-as name for the agreement: '{company name} - MSA.pdf'."""
    return f"{_safe_company_label(submission)} - MSA.pdf"


def no_advance_download_filename(submission: Envelope1Submission) -> str:
    """Save-as name: '{company name} - No Advance Payment Declaration.pdf'."""
    return f"{_safe_company_label(submission)} - No Advance Payment Declaration.pdf"


def _party_context(submission: Envelope1Submission) -> dict[str, str]:
    today = timezone.localdate()
    address = " ".join((submission.principal_address or "").split())
    return {
        "day": f"{today.day:02d}",
        "month": today.strftime("%B"),
        "year": str(today.year),
        "company_name": submission.legal_name or "",
        "company_no": submission.ssm_registration_number or "",
        "address": address,
        "signatory_name": submission.msa_signatory_name or "",
        "signatory_designation": submission.msa_signatory_designation or "",
    }


def build_draft_msa_pdf(submission: Envelope1Submission) -> bytes:
    """Return the Master Service Agreement as a PDF, filled with this submission."""
    html = render_draft_msa_html(submission)
    return HTML(string=html, base_url=str(MSA_DIR)).write_pdf()


def render_draft_msa_html(submission: Envelope1Submission) -> str:
    """Fill the agreement blanks from the vendor's saved MSA party details."""
    template = Template(MSA_HTML.read_text(encoding="utf-8"))
    ctx = _party_context(submission)
    return template.render(Context({k: v for k, v in ctx.items() if k in ("day", "month", "year", "company_name", "company_no", "address")}))


def build_no_advance_pdf(submission: Envelope1Submission) -> bytes:
    """Pre-filled 1.4 No Advance Payment Declaration for the vendor to sign and upload."""
    html = render_no_advance_html(submission)
    return HTML(string=html, base_url=str(MSA_DIR)).write_pdf()


def render_no_advance_html(submission: Envelope1Submission) -> str:
    template = Template(NO_ADVANCE_HTML.read_text(encoding="utf-8"))
    return template.render(Context(_party_context(submission)))


# ---------------------------------------------------------------------------
# Legacy plain-text declaration (superseded by MSA/no-advance.html + WeasyPrint):
#
#   "1. The company does not require any advance payment..."
#   "2. The company has sufficient working capital..."
#   "3. Payment will only be claimed according to the agreed payment terms."
#   Footer: "Sign, stamp, and upload this declaration in Envelope 1, item 1.4."
# ---------------------------------------------------------------------------
