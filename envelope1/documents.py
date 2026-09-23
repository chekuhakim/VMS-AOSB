"""Store versioned Envelope 1 PDFs."""

from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser
from django.core.files.uploadedfile import UploadedFile
from django.db.models import Max

from documents.storage import build_versioned_path, upload_bytes
from envelope1.models import Envelope1Document, Envelope1Submission


def save_envelope1_pdf(
    *,
    submission: Envelope1Submission,
    doc_type: str,
    uploaded: UploadedFile,
    user: AbstractBaseUser | None,
    expiry_date=None,
) -> Envelope1Document:
    latest = (
        submission.documents.filter(doc_type=doc_type).aggregate(m=Max("version"))["m"]
        or 0
    )
    version = latest + 1
    path = build_versioned_path(
        company_id=submission.company_id,
        document_type=f"e1_{doc_type}",
        filename=uploaded.name or f"{doc_type}.pdf",
        version=version,
    )
    stored = upload_bytes(
        path=path,
        content=uploaded,
        content_type=getattr(uploaded, "content_type", None) or "application/pdf",
    )
    return Envelope1Document.objects.create(
        submission=submission,
        doc_type=doc_type,
        storage_path=stored.path,
        storage_backend=stored.backend,
        original_filename=uploaded.name or f"{doc_type}.pdf",
        version=version,
        expiry_date=expiry_date,
        uploaded_by=user if user and getattr(user, "is_authenticated", False) else None,
    )
