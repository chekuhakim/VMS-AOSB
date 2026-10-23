"""Send one branded test email to check the SMTP settings in .env.

    python manage.py send_test_email you@example.com
"""

from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.template.loader import render_to_string

from accounts.models import Notification


class Command(BaseCommand):
    help = "Send a test notification email using the configured EMAIL_* settings."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("recipient", help="Address to send the test email to")

    def handle(self, *args, **options) -> None:  # type: ignore[no-untyped-def]
        recipient: str = options["recipient"]
        backend = settings.EMAIL_BACKEND
        self.stdout.write(f"Backend: {backend}")
        if backend.endswith("console.EmailBackend"):
            self.stdout.write(
                self.style.WARNING(
                    "Console backend: the email is printed below, not delivered. "
                    "Set EMAIL_BACKEND and EMAIL_HOST* in .env to send for real."
                )
            )
        else:
            self.stdout.write(f"Server: {settings.EMAIL_HOST}:{settings.EMAIL_PORT} (TLS={settings.EMAIL_USE_TLS})")

        note = Notification(
            title="Test email from Alpha Orange VMS",
            body="If you can read this, notification emails are configured correctly.",
            link_url=settings.SITE_URL,
            link_label="Open VMS",
        )
        context = {
            "note": note,
            "link": settings.SITE_URL,
            "current_site": {"name": settings.EMAIL_FROM_NAME, "domain": settings.SITE_URL},
        }
        message = EmailMultiAlternatives(
            f"{settings.EMAIL_FROM_NAME}: {note.title}",
            render_to_string("notifications/email/notification.txt", context),
            to=[recipient],
        )
        message.attach_alternative(
            render_to_string("notifications/email/notification.html", context), "text/html"
        )
        try:
            message.send()
        except Exception as exc:
            # Surface the SMTP error (bad password, blocked port…) instead of a traceback
            raise CommandError(f"Sending failed: {exc}") from exc
        self.stdout.write(self.style.SUCCESS(f"Test email sent to {recipient} from {settings.DEFAULT_FROM_EMAIL}"))
