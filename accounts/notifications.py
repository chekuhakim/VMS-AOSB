"""In-app notifications (header bell + toast), mirrored to email when first created."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from accounts.models import Notification
from vendors.models import Company, CompanyDocument

logger = logging.getLogger(__name__)

# Expiry reminder stages (days before expiry); each stage emails the vendor once
SOON_DAYS = 30
FINAL_REMINDER_DAYS = 7


def _absolute_url(path: str) -> str:
    if not path or path.startswith(("http://", "https://")):
        return path
    return settings.SITE_URL.rstrip("/") + path


def queue_notification_email(note: Notification) -> None:
    """Email a copy of the notification once the surrounding transaction commits."""
    address = (getattr(note.user, "email", "") or "").strip()
    if not address:
        return
    context = {
        "note": note,
        "link": _absolute_url(note.link_url),
        "current_site": {"name": settings.EMAIL_FROM_NAME, "domain": settings.SITE_URL},
    }
    subject = f"{settings.EMAIL_FROM_NAME}: {note.title}"
    text = render_to_string("notifications/email/notification.txt", context)
    html = render_to_string("notifications/email/notification.html", context)
    user_id = note.user_id

    def send() -> None:
        message = EmailMultiAlternatives(subject, text, to=[address])
        message.attach_alternative(html, "text/html")
        try:
            message.send()
        except Exception:
            # Best-effort: the in-app notification is already saved; a mail outage must not break the workflow
            logger.exception("Notification email failed for user %s", user_id)

    # on_commit: no email for a workflow step that later rolls back
    transaction.on_commit(send)


def staff_recipients(
    group_name: str, *, exclude: AbstractBaseUser | None = None
) -> list[AbstractBaseUser]:
    """Active users in a staff role group, minus the person who triggered the event."""
    users = get_user_model().objects.filter(is_active=True, groups__name=group_name).distinct()
    if exclude is not None and exclude.pk:
        users = users.exclude(pk=exclude.pk)
    return list(users)


def notify_event(
    *,
    users: Iterable[AbstractBaseUser],
    dedupe_key: str,
    title: str,
    body: str = "",
    level: str = Notification.Level.INFO,
    link_url: str = "",
    link_label: str = "",
) -> None:
    """Send a one-off workflow event (in-app + email).

    Unlike upsert_notification, a repeat of the same event (e.g. a second lock after a
    withdrawal) replaces the earlier copy — including a dismissed one — so it shows
    unread again; the key still keeps one row per event type in the inbox.
    """
    for user in users:
        Notification.objects.filter(user=user, dedupe_key=dedupe_key).delete()
        note = Notification.objects.create(
            user=user,
            dedupe_key=dedupe_key,
            title=title,
            body=body,
            level=level,
            link_url=link_url,
            link_label=link_label,
        )
        queue_notification_email(note)


def upsert_notification(
    *,
    user: AbstractBaseUser,
    dedupe_key: str,
    title: str,
    body: str = "",
    level: str = Notification.Level.INFO,
    link_url: str = "",
    link_label: str = "",
    email: bool = True,
) -> Notification:
    """Insert or refresh a notification identified by dedupe_key.

    Inbox × / toast dismiss set dismissed_at and must stay sticky — never clear
    that flag on content refresh, or the same alert reappears after sync.
    Email goes out only on first insert, so page-load syncs never re-send it.
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
    if created and email:
        queue_notification_email(obj)
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


def _tracked_expiries(company: Company) -> list[tuple[str, str, date]]:
    """(doc_type, label, expiry) for every dated document the vendor must keep valid."""
    from envelope1.checklist import EXPIRY_REQUIRED_TYPES
    from envelope1.models import Envelope1Document
    from envelope1.services import latest_docs_map, latest_submission

    tracked: list[tuple[str, str, date]] = []
    for doc_type, label in CompanyDocument.DocType.choices:
        expiry = _doc_expiry(company, doc_type)
        if expiry:
            tracked.append((doc_type, label, expiry))
    submission = latest_submission(company)
    if submission is not None:
        labels = dict(Envelope1Document.DocType.choices)
        for doc_type, doc in latest_docs_map(submission).items():
            if doc_type in EXPIRY_REQUIRED_TYPES and doc.expiry_date:
                tracked.append((doc_type, labels.get(doc_type, doc_type), doc.expiry_date))
    return tracked


def expiry_stage(expiry: date, today: date) -> str | None:
    """Reminder stage for a document: 30 days out, 7 days out, then expired.

    Each stage has its own dedupe key, so the vendor is emailed once per stage.
    """
    if expiry < today:
        return "expired"
    if expiry <= today + timedelta(days=FINAL_REMINDER_DAYS):
        return "week"
    if expiry <= today + timedelta(days=SOON_DAYS):
        return "soon"
    return None


def _expiry_message(stage: str, label: str, company_name: str, expiry: date, today: date) -> dict[str, str]:
    if stage == "expired":
        days = (today - expiry).days
        return {
            "title": f"{label} expired — {company_name}",
            "body": f"Expired {days} day{'s' if days != 1 else ''} ago ({expiry:%d %b %Y}). Upload a renewed PDF.",
            "level": Notification.Level.DANGER,
        }
    days = (expiry - today).days
    when = "today" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
    return {
        "title": f"{label} expiring soon — {company_name}",
        "body": f"Expires {when} ({expiry:%d %b %Y}). Upload a renewed PDF before it lapses.",
        "level": Notification.Level.WARNING,
    }


def sync_vendor_notifications(user: AbstractBaseUser) -> None:
    """Refresh condition-based notifications for the vendor's companies.

    Registration-form noise (draft progress, in-wizard expiry) is suppressed until
    the company has been submitted. Post-submit outcomes (rejected / approved /
    document expiry on a live registration) still notify.
    """
    companies = list(Company.objects.filter(owner=user).order_by("name"))
    today = timezone.localdate()
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
            email=False,
        )
    else:
        clear_notification(user=user, dedupe_key="register-company")

    for company in companies:
        status = company.registration_status

        # Never nag about in-progress drafts — only outcomes after submit.
        clear_notification(user=user, dedupe_key=f"company-{company.pk}-draft")

        if status == Company.RegistrationStatus.DRAFT:
            # Leftover expiry alerts from mid-wizard saves are removed by the sweep below
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
        for doc_type, label, expiry in _tracked_expiries(company):
            stage = expiry_stage(expiry, today)
            if stage is None:
                continue
            key = f"expiry-{company.pk}-{doc_type}-{stage}"
            active_keys.add(key)
            upsert_notification(
                user=user,
                dedupe_key=key,
                **_expiry_message(stage, label, company.name, expiry, today),
                link_url=reverse("envelope1:vault"),
                link_label="Document vault",
            )

    # Sweep: alerts whose condition no longer holds (renewed doc, next stage reached, draft) go away
    for note in Notification.objects.filter(user=user).exclude(dedupe_key=""):
        if note.dedupe_key.startswith(
            ("register-company", "company-", "expiry-")
        ) and note.dedupe_key not in active_keys:
            note.delete()
