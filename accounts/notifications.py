"""Create / refresh in-app notifications for vendors."""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import AbstractBaseUser
from django.urls import reverse
from django.utils import timezone

from accounts.models import Notification
from vendors.models import Company, CompanyDocument

SOON_DAYS = 30


def upsert_notification(
    *,
    user: AbstractBaseUser,
    dedupe_key: str,
    title: str,
    body: str = "",
    level: str = Notification.Level.INFO,
    link_url: str = "",
    link_label: str = "",
) -> Notification:
    """Insert or refresh a notification identified by dedupe_key.

    Inbox × / toast dismiss set dismissed_at and must stay sticky — never clear
    that flag on content refresh, or the same alert reappears after sync.
    """
    obj, created = Notification.objects.get_or_create(
        user=user,
        dedupe_key=dedupe_key,
        defaults={
            "title": title,
            "body": body,
            "level": level,
            "link_url": link_url,
            "link_label": link_label,
        },
    )
    if not created:
        # Already removed from inbox — leave it alone (do not resurrect)
        if obj.dismissed_at is not None:
            return obj
        changed = (
            obj.title != title
            or obj.body != body
            or obj.level != level
            or obj.link_url != link_url
            or obj.link_label != link_label
        )
        if changed:
            obj.title = title
            obj.body = body
            obj.level = level
            obj.link_url = link_url
            obj.link_label = link_label
            obj.save(
                update_fields=[
                    "title",
                    "body",
                    "level",
                    "link_url",
                    "link_label",
                ]
            )
    return obj


def clear_notification(*, user: AbstractBaseUser, dedupe_key: str) -> None:
    Notification.objects.filter(user=user, dedupe_key=dedupe_key).delete()


def _doc_expiry(company: Company, doc_type: str):
    doc = (
        CompanyDocument.objects.filter(company=company, doc_type=doc_type)
        .order_by("-version")
        .first()
    )
    if doc and doc.expiry_date:
        return doc.expiry_date
    if doc_type == CompanyDocument.DocType.SSM:
        return company.ssm_document_expiry
    if doc_type == CompanyDocument.DocType.CIDB:
        return company.cidb_certificate_expiry
    if doc_type == CompanyDocument.DocType.ST:
        return company.st_certificate_expiry
    return None


def sync_vendor_notifications(user: AbstractBaseUser) -> None:
    """Refresh condition-based notifications for the vendor's companies.

    Registration-form noise (draft progress, in-wizard expiry) is suppressed until
    the company has been submitted. Post-submit outcomes (rejected / approved /
    document expiry on a live registration) still notify.
    """
    companies = list(Company.objects.filter(owner=user).order_by("name"))
    today = timezone.localdate()
    soon = today + timedelta(days=SOON_DAYS)
    active_keys: set[str] = set()

    if not companies:
        active_keys.add("register-company")
        upsert_notification(
            user=user,
            dedupe_key="register-company",
            title="Register your company",
            body="Create a company profile to start pre-qualification with Alpha Orange.",
            level=Notification.Level.INFO,
            link_url=reverse("vendors:register_company"),
            link_label="Register company",
        )
    else:
        clear_notification(user=user, dedupe_key="register-company")

    for company in companies:
        status = company.registration_status

        # Never nag about in-progress drafts — only outcomes after submit.
        clear_notification(user=user, dedupe_key=f"company-{company.pk}-draft")

        if status == Company.RegistrationStatus.DRAFT:
            # Clear any leftover expiry alerts from mid-wizard field saves
            for doc_type, _label in CompanyDocument.DocType.choices:
                clear_notification(
                    user=user, dedupe_key=f"expiry-{company.pk}-{doc_type}-expired"
                )
                clear_notification(
                    user=user, dedupe_key=f"expiry-{company.pk}-{doc_type}-soon"
                )
            continue

        if status == Company.RegistrationStatus.REJECTED:
            key = f"company-{company.pk}-rejected"
            active_keys.add(key)
            upsert_notification(
                user=user,
                dedupe_key=key,
                title=f"Registration rejected — {company.name}",
                body="Review the rejection reasons and update your company registration.",
                level=Notification.Level.DANGER,
                link_url=reverse("vendors:company_detail", kwargs={"pk": company.pk}),
                link_label="View company",
            )
        elif status == Company.RegistrationStatus.APPROVED:
            key = f"company-{company.pk}-envelope1"
            active_keys.add(key)
            upsert_notification(
                user=user,
                dedupe_key=key,
                title=f"Envelope 1 is next — {company.name}",
                body="Company registration is approved. Complete Envelope 1 when it opens.",
                level=Notification.Level.INFO,
                link_url=reverse("envelope1:home"),
                link_label="Open Envelope 1",
            )
        else:
            # submitted — waiting on rules / already evaluated path
            clear_notification(user=user, dedupe_key=f"company-{company.pk}-rejected")
            clear_notification(user=user, dedupe_key=f"company-{company.pk}-envelope1")

        # Expiry alerts only after registration has left draft
        for doc_type, label in CompanyDocument.DocType.choices:
            expiry = _doc_expiry(company, doc_type)
            if not expiry:
                clear_notification(
                    user=user, dedupe_key=f"expiry-{company.pk}-{doc_type}-expired"
                )
                clear_notification(
                    user=user, dedupe_key=f"expiry-{company.pk}-{doc_type}-soon"
                )
                continue

            if expiry < today:
                key = f"expiry-{company.pk}-{doc_type}-expired"
                active_keys.add(key)
                days = (today - expiry).days
                upsert_notification(
                    user=user,
                    dedupe_key=key,
                    title=f"{label} expired — {company.name}",
                    body=f"Expired {days} day{'s' if days != 1 else ''} ago. Upload a renewed PDF.",
                    level=Notification.Level.DANGER,
                    link_url=reverse("envelope1:vault"),
                    link_label="Document vault",
                )
                clear_notification(
                    user=user, dedupe_key=f"expiry-{company.pk}-{doc_type}-soon"
                )
            elif expiry <= soon:
                key = f"expiry-{company.pk}-{doc_type}-soon"
                active_keys.add(key)
                days = (expiry - today).days
                upsert_notification(
                    user=user,
                    dedupe_key=key,
                    title=f"{label} expiring soon — {company.name}",
                    body=f"Expires in {days} day{'s' if days != 1 else ''} ({expiry:%d %b %Y}).",
                    level=Notification.Level.WARNING,
                    link_url=reverse("envelope1:vault"),
                    link_label="Document vault",
                )
                clear_notification(
                    user=user, dedupe_key=f"expiry-{company.pk}-{doc_type}-expired"
                )
            else:
                clear_notification(
                    user=user, dedupe_key=f"expiry-{company.pk}-{doc_type}-expired"
                )
                clear_notification(
                    user=user, dedupe_key=f"expiry-{company.pk}-{doc_type}-soon"
                )

    for note in Notification.objects.filter(user=user).exclude(dedupe_key=""):
        if note.dedupe_key.startswith(
            ("register-company", "company-", "expiry-")
        ) and note.dedupe_key not in active_keys:
            note.delete()
