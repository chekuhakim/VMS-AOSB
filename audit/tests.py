"""Audit log immutability (ISO 9001 evidence)."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from audit.models import AuditLog
from audit.services import write_audit


class AuditLogImmutabilityTests(TestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_user("actor", "actor@example.com", "x")
        self.entry = write_audit(category=AuditLog.Category.SYSTEM, action="test_event", actor=self.user)

    def test_rows_cannot_be_edited(self) -> None:
        self.entry.action = "tampered"
        with self.assertRaises(ValueError):
            self.entry.save()

    def test_rows_cannot_be_deleted_singly_or_in_bulk(self) -> None:
        with self.assertRaises(ValueError):
            self.entry.delete()
        with self.assertRaises(ValueError):
            AuditLog.objects.filter(pk=self.entry.pk).delete()
        self.assertTrue(AuditLog.objects.filter(pk=self.entry.pk).exists())

    def test_deleting_a_user_keeps_their_audit_trail(self) -> None:
        label = self.entry.actor_label
        self.user.delete()
        self.entry.refresh_from_db()
        self.assertIsNone(self.entry.actor_id)
        self.assertEqual(self.entry.actor_label, label)
