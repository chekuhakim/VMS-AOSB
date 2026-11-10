"""Vendor invitation email helpers."""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse

from vendors.models import VendorInvitation

logger = logging.getLogger(__name__)


def invitation_url(invitation: VendorInvitation) -> str:
    base = (settings.SITE_URL or "").rstrip("/")
    return f"{base}{reverse('vendors:accept_invitation', args=[invitation.token])}"


def send_vendor_invitation(invitation: VendorInvitation) -> None:
    """Email the secure invitation link to the vendor."""
    url = invitation_url(invitation)
    context = {
        "invitation": invitation,
        "invite_url": url,
        "brand_name": settings.EMAIL_FROM_NAME,
    }
    subject = f"You're invited to register with {settings.EMAIL_FROM_NAME}"
    text = render_to_string("vendors/email/vendor_invitation.txt", context)
    html = render_to_string("vendors/email/vendor_invitation.html", context)
    message = EmailMultiAlternatives(
        subject,
        text,
        to=[invitation.email],
    )
    message.attach_alternative(html, "text/html")

    def send() -> None:
        try:
            message.send()
        except Exception:
            logger.exception("Vendor invitation email failed for %s", invitation.email)

    transaction.on_commit(send)
