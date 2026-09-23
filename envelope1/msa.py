"""Generate a simple draft MSA PDF from saved party details."""

from __future__ import annotations

from io import BytesIO

from envelope1.models import Envelope1Submission


def build_draft_msa_pdf(submission: Envelope1Submission) -> bytes:
    """Return a minimal PDF embedding MSA party fields (no external PDF lib)."""
    lines = [
        "ALPHA ORANGE SDN BHD — DRAFT MASTER SERVICE AGREEMENT",
        "",
        f"Company (cycle {submission.cycle_number})",
        f"Legal name: {submission.legal_name or '—'}",
        f"SSM registration: {submission.ssm_registration_number or '—'}",
        f"Principal address: {(submission.principal_address or '—').replace(chr(10), ' ')}",
        f"Contact name: {submission.contact_name or '—'}",
        f"Contact email: {submission.contact_email or '—'}",
        f"MSA signatory: {submission.msa_signatory_name or '—'}",
        f"Signatory designation: {submission.msa_signatory_designation or '—'}",
        "",
        "This draft is generated from your saved MSA party details.",
        "Sign and upload the completed MSA in Envelope 1 Step 2.",
        "This is not a legally binding executed agreement until signed.",
    ]
    # Escape PDF literal string specials
    safe = []
    for line in lines:
        safe.append(line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)"))

    content_lines = ["BT", "/F1 10 Tf", "50 750 Td", "14 TL"]
    for i, line in enumerate(safe):
        if i == 0:
            content_lines.append(f"({line}) Tj")
        else:
            content_lines.append("T*")
            content_lines.append(f"({line}) Tj")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1", errors="replace")

    objects: list[bytes] = []
    objects.append(b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n")
    objects.append(b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n")
    objects.append(
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n"
    )
    objects.append(
        f"4 0 obj<< /Length {len(stream)} >>stream\n".encode()
        + stream
        + b"\nendstream\nendobj\n"
    )
    objects.append(b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n")

    out = BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(out.tell())
        out.write(obj)
    xref_pos = out.tell()
    out.write(f"xref\n0 {len(offsets)}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(
        f"trailer<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    )
    return out.getvalue()
