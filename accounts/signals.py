"""Drop the vendor notification-sync cache when the data it reads changes."""

from __future__ import annotations

from django.db.models.signals import post_delete, post_save

from accounts.notifications import invalidate_vendor_notification_sync


def _invalidate_owner(owner_id: int | None) -> None:
    if owner_id:
        invalidate_vendor_notification_sync(owner_id)


def _on_company(sender, instance, **kwargs) -> None:  # type: ignore[no-untyped-def]
    _invalidate_owner(instance.owner_id)


def _on_company_document(sender, instance, **kwargs) -> None:  # type: ignore[no-untyped-def]
    from vendors.models import Company

    owner_id = (
        Company.objects.filter(pk=instance.company_id)
        .values_list("owner_id", flat=True)
        .first()
    )
    _invalidate_owner(owner_id)


def _on_envelope_document(sender, instance, **kwargs) -> None:  # type: ignore[no-untyped-def]
    from envelope1.models import Envelope1Submission

    owner_id = (
        Envelope1Submission.objects.filter(pk=instance.submission_id)
        .values_list("company__owner_id", flat=True)
        .first()
    )
    _invalidate_owner(owner_id)


def connect_notification_sync_signals() -> None:
    from envelope1.models import Envelope1Document
    from vendors.models import Company, CompanyDocument

    post_save.connect(_on_company, sender=Company, dispatch_uid="vms_notif_company_save")
    post_delete.connect(_on_company, sender=Company, dispatch_uid="vms_notif_company_delete")
    post_save.connect(
        _on_company_document,
        sender=CompanyDocument,
        dispatch_uid="vms_notif_company_doc_save",
    )
    post_delete.connect(
        _on_company_document,
        sender=CompanyDocument,
        dispatch_uid="vms_notif_company_doc_delete",
    )
    post_save.connect(
        _on_envelope_document,
        sender=Envelope1Document,
        dispatch_uid="vms_notif_envelope_doc_save",
    )
    post_delete.connect(
        _on_envelope_document,
        sender=Envelope1Document,
        dispatch_uid="vms_notif_envelope_doc_delete",
    )
