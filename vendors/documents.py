"""Helpers to store versioned company registration PDFs."""

from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser
from django.core.files.uploadedfile import UploadedFile
from django.db.models import Max

from documents.storage import build_versioned_path, upload_bytes
from vendors.models import Company, CompanyDocument


def save_company_pdf(
    *,
    company: Company,
    doc_type: str,
    uploaded: UploadedFile,
    user: AbstractBaseUser | None,
    expiry_date=None,
) -> CompanyDocument:
    """Upload a new versioned PDF and index it on CompanyDocument."""
    latest = (
        company.documents.filter(doc_type=doc_type).aggregate(m=Max("version"))["m"]
        or 0
    )
    version = latest + 1
    path = build_versioned_path(
        company_id=company.pk,
        document_type=doc_type,
        filename=uploaded.name or f"{doc_type}.pdf",
        version=version,
    )
    stored = upload_bytes(
        path=path,
        content=uploaded,
        content_type=getattr(uploaded, "content_type", None) or "application/pdf",
    )
    return CompanyDocument.objects.create(
        company=company,
        doc_type=doc_type,
        storage_path=stored.path,
        storage_backend=stored.backend,
        original_filename=uploaded.name or f"{doc_type}.pdf",
        version=version,
        expiry_date=expiry_date,
        uploaded_by=user if user and getattr(user, "is_authenticated", False) else None,
    )
