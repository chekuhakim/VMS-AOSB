"""Document storage abstraction: local media now, Supabase when configured.

ISO 9001: callers must pass a unique versioned path — never overwrite blobs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone


@dataclass(frozen=True)
class StoredObject:
    """Result of a successful upload."""

    path: str
    backend: str  # "local" | "supabase"
    bucket: str


def build_versioned_path(
    *,
    company_id: int,
    document_type: str,
    filename: str,
    version: int,
) -> str:
    """Build a unique object key that includes company, type, version, and uuid."""
    safe_name = Path(filename).name.replace(" ", "_")
    stamp = timezone.now().strftime("%Y%m%d")
    return (
        f"companies/{company_id}/{document_type}/"
        f"v{version}_{stamp}_{uuid4().hex[:8]}_{safe_name}"
    )


def supabase_configured() -> bool:
    """True when Supabase URL + service role key are present in the environment."""
    return bool(settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY)


def upload_bytes(
    *,
    path: str,
    content: BinaryIO | bytes,
    content_type: str = "application/pdf",
) -> StoredObject:
    """Store file bytes. Uses Supabase when configured; otherwise local MEDIA_ROOT."""
    data = content if isinstance(content, (bytes, bytearray)) else content.read()

    if supabase_configured():
        return _upload_supabase(path=path, data=bytes(data), content_type=content_type)

    # Local fallback for Phase 0 / offline without Supabase credentials
    saved = default_storage.save(path, ContentFile(bytes(data)))
    return StoredObject(
        path=saved,
        backend="local",
        bucket="local-media",
    )


def open_stored(*, path: str, backend: str) -> bytes:
    """Read stored PDF bytes (local MEDIA or Supabase)."""
    if backend == "supabase":
        return _download_supabase(path=path)
    with default_storage.open(path, "rb") as handle:
        return handle.read()


def _download_supabase(*, path: str) -> bytes:
    from supabase import create_client

    client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    bucket = settings.SUPABASE_STORAGE_BUCKET
    data = client.storage.from_(bucket).download(path)
    return bytes(data)


def _upload_supabase(*, path: str, data: bytes, content_type: str) -> StoredObject:
    """Upload to the configured Supabase Storage bucket via the official client."""
    from supabase import create_client

    client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    bucket = settings.SUPABASE_STORAGE_BUCKET
    client.storage.from_(bucket).upload(
        path,
        data,
        file_options={"content-type": content_type, "upsert": "false"},
    )
    return StoredObject(path=path, backend="supabase", bucket=bucket)
