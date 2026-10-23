"""Daily job: remind vendors about expiring / expired documents (in-app + email).

Schedule once a day (Windows Task Scheduler, cron, or the host's scheduler):
    python manage.py send_expiry_reminders
Safe to re-run: each reminder stage is emailed once per document.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction
from django.utils import timezone

from accounts.models import Notification
from accounts.notifications import sync_vendor_notifications
from accounts.roles import is_vendor_user
from vendors.models import Company


class Command(BaseCommand):
    help = "Create expiry reminders (30 days, 7 days, expired) for every vendor and email new ones."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List the reminders that would be sent, then roll back (no rows saved, no emails).",
        )

    def handle(self, *args, **options) -> None:  # type: ignore[no-untyped-def]
        dry_run: bool = options["dry_run"]
        with transaction.atomic():
            self._run(dry_run)
            if dry_run:
                # Emails are queued with on_commit, so rolling back also cancels them
                transaction.set_rollback(True)

    def _run(self, dry_run: bool) -> None:
        started = timezone.now()
        owners = (
            get_user_model()
            .objects.filter(
                is_active=True,
                companies__in=Company.objects.exclude(
                    registration_status=Company.RegistrationStatus.DRAFT
                ),
            )
            .distinct()
        )
        checked = 0
        for user in owners:
            if not is_vendor_user(user):
                continue
            sync_vendor_notifications(user)
            checked += 1

        created = list(
            Notification.objects.filter(dedupe_key__startswith="expiry-", created_at__gte=started)
            .select_related("user")
            .order_by("user__username")
        )
        if dry_run:
            for note in created:
                self.stdout.write(f"  would notify {note.user.email or note.user.get_username()}: {note.title}")
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: checked {checked} vendor(s); {len(created)} reminder(s) would be sent. Nothing saved."
                )
            )
            return
        self.stdout.write(
            self.style.SUCCESS(
                f"Checked {checked} vendor(s); {len(created)} new expiry reminder(s) sent."
            )
        )
