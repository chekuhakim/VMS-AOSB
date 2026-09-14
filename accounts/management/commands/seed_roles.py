"""Seed Django Groups used for staff RBAC and fix the Sites framework entry."""

from __future__ import annotations

from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand

from accounts.roles import STAFF_GROUP_NAMES, ensure_role_groups


class Command(BaseCommand):
    help = "Create staff role groups and set Site domain for local allauth."

    def handle(self, *args, **options) -> None:  # type: ignore[no-untyped-def]
        groups = ensure_role_groups()
        names = ", ".join(g.name for g in groups)
        self.stdout.write(self.style.SUCCESS(f"Role groups ready: {names}"))
        self.stdout.write(
            self.style.NOTICE(f"Expected: {', '.join(STAFF_GROUP_NAMES)}")
        )

        site = Site.objects.get_or_create(pk=1)[0]
        site.domain = "localhost:8000"
        site.name = "Alpha Orange VMS"
        site.save(update_fields=["domain", "name"])
        self.stdout.write(self.style.SUCCESS(f"Site set to {site.domain}"))
