"""Store RFQ tender documents and vendor quotation PDFs (never overwrite blobs)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from django.core.files.uploadedfile import UploadedFile
from django.utils import timezone

from documents.storage import StoredObject, build_versioned_path, upload_bytes
from tenders.models import RFQ, Quotation


def _upload(path: str, uploaded: UploadedFile) -> StoredObject:
    return upload_bytes(
        path=path,
        content=uploaded,
        content_type=getattr(uploaded, "content_type", None) or "application/pdf",
    )


def store_rfq_document(*, rfq: RFQ, uploaded: UploadedFile) -> None:
    """Attach a tender document to the RFQ (caller saves the RFQ)."""
    safe_name = Path(uploaded.name or "rfq.pdf").name.replace(" ", "_")
    stamp = timezone.now().strftime("%Y%m%d")
    path = f"projects/{rfq.project_id}/rfq/{stamp}_{uuid4().hex[:8]}_{safe_name}"
    stored = _upload(path, uploaded)
    rfq.document_path = stored.path
    rfq.document_backend = stored.backend
    rfq.document_filename = uploaded.name or "rfq.pdf"


def store_quotation_document(
    *, quotation: Quotation, uploaded: UploadedFile, version: int
) -> None:
    """Attach the vendor's quotation PDF (caller saves the quotation)."""
    path = build_versioned_path(
        company_id=quotation.company_id,
        document_type=f"quotation_rfq{quotation.rfq_id}",
        filename=uploaded.name or "quotation.pdf",
        version=version,
    )
    stored = _upload(path, uploaded)
    quotation.document_path = stored.path
    quotation.document_backend = stored.backend
    quotation.document_filename = uploaded.name or "quotation.pdf"
    quotation.version = version
