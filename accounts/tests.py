"""Notification inbox permissions, email delivery rules, expiry reminders, and email commands."""

from __future__ import annotations

from datetime import timedelta
from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.db import transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Notification
from accounts.notifications import expiry_stage, notify_event, upsert_notification
from core.testing import make_company, make_submission, make_user, pdf, vendor_client
from envelope1.documents import save_envelope1_pdf
from envelope1.models import Envelope1Document
from vendors.models import Company, CompanyDocument


class NotificationOwnershipTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.alice = make_user("alice")
        cls.bob = make_user("bob")
        cls.note = Notification.objects.create(user=cls.alice, title="Private", link_url="/")

    def test_cannot_read_dismiss_or_delete_someone_elses_notification(self) -> None:
        client = vendor_client(self.bob)
        for name in ("accounts:notification_read", "accounts:notification_dismiss", "accounts:notification_delete"):
            with self.subTest(view=name):
                self.assertEqual(client.post(reverse(name, args=[self.note.pk])).status_code, 404)
        self.note.refresh_from_db()
        self.assertIsNone(self.note.read_at)
        self.assertIsNone(self.note.dismissed_at)

    def test_mark_all_read_only_touches_own(self) -> None:
        vendor_client(self.bob).post(reverse("accounts:notifications_mark_all_read"))
        self.note.refresh_from_db()
        self.assertIsNone(self.note.read_at)

    def test_redirects_never_leave_the_site(self) -> None:
        client = vendor_client(self.alice)
        for evil in ("https://evil.example.com/", "//evil.example.com", "/\\evil.example.com"):
            with self.subTest(next=evil):
                response = client.post(
                    reverse("accounts:notification_dismiss", args=[self.note.pk]), {"next": evil}
                )
                self.assertEqual(response["Location"], "/")
        response = client.post(reverse("accounts:notifications_mark_all_read"), {"next": "https://evil.example.com/"})
        self.assertEqual(response["Location"], "/")

    def test_switch_company_redirect_stays_on_site(self) -> None:
        company = make_company(self.alice)
        response = vendor_client(self.alice).post(
            reverse("accounts:switch_company"), {"company_id": company.pk, "next": "/\\evil.example.com"}
        )
        self.assertEqual(response["Location"], "/")

    def test_cannot_switch_to_someone_elses_company(self) -> None:
        company = make_company(self.alice)
        response = vendor_client(self.bob).post(reverse("accounts:switch_company"), {"company_id": company.pk})
        self.assertEqual(response.status_code, 404)


class EmailDeliveryRuleTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.user = make_user("vendor")

    def test_upsert_emails_once(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            upsert_notification(user=self.user, dedupe_key="k", title="Hello")
            upsert_notification(user=self.user, dedupe_key="k", title="Hello")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Hello", mail.outbox[0].subject)

    def test_repeat_event_replaces_dismissed_copy(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            notify_event(users=[self.user], dedupe_key="e", title="Locked")
        Notification.objects.filter(dedupe_key="e").update(dismissed_at=timezone.now())
        with self.captureOnCommitCallbacks(execute=True):
            notify_event(users=[self.user], dedupe_key="e", title="Locked")
        rows = Notification.objects.filter(dedupe_key="e")
        self.assertEqual(rows.count(), 1)
        self.assertIsNone(rows.get().dismissed_at)
        self.assertEqual(len(mail.outbox), 2)

    def test_rolled_back_step_sends_nothing(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    notify_event(users=[self.user], dedupe_key="rb", title="Ghost")
                    raise RuntimeError
            except RuntimeError:
                pass
        self.assertEqual(mail.outbox, [])
        self.assertFalse(Notification.objects.filter(dedupe_key="rb").exists())

    def test_users_without_email_are_skipped(self) -> None:
        self.user.email = ""
        self.user.save(update_fields=["email"])
        with self.captureOnCommitCallbacks(execute=True):
            notify_event(users=[self.user], dedupe_key="ne", title="No inbox")
        self.assertEqual(mail.outbox, [])
        self.assertTrue(Notification.objects.filter(dedupe_key="ne").exists())

    def test_email_links_are_absolute(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            notify_event(users=[self.user], dedupe_key="ln", title="Link", link_url="/envelope-1/")
        self.assertIn("http", mail.outbox[0].body)
        self.assertIn("/envelope-1/", mail.outbox[0].body)


class ExpiryStageTests(TestCase):
    def test_stages(self) -> None:
        today = timezone.localdate()
        self.assertIsNone(expiry_stage(today + timedelta(days=31), today))
        self.assertEqual(expiry_stage(today + timedelta(days=30), today), "soon")
        self.assertEqual(expiry_stage(today + timedelta(days=8), today), "soon")
        self.assertEqual(expiry_stage(today + timedelta(days=7), today), "week")
        self.assertEqual(expiry_stage(today, today), "week")
        self.assertEqual(expiry_stage(today - timedelta(days=1), today), "expired")


class ExpiryReminderCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.vendor = make_user("vendor")
        cls.company = make_company(cls.vendor)

    def _set_ssm_expiry(self, days: int) -> None:
        CompanyDocument.objects.filter(company=self.company, doc_type=CompanyDocument.DocType.SSM).update(
            expiry_date=timezone.localdate() + timedelta(days=days)
        )

    def _run(self) -> str:
        out = StringIO()
        mail.outbox = []
        with self.captureOnCommitCallbacks(execute=True):
            call_command("send_expiry_reminders", stdout=out)
        return out.getvalue()

    @staticmethod
    def _expiry_mails() -> list:  # type: ignore[type-arg]
        return [m for m in mail.outbox if "expir" in m.subject]

    def _ssm_keys(self) -> list[str]:
        prefix = f"expiry-{self.company.pk}-{CompanyDocument.DocType.SSM}-"
        return list(Notification.objects.filter(dedupe_key__startswith=prefix).values_list("dedupe_key", flat=True))

    def test_each_stage_emails_once(self) -> None:
        self._set_ssm_expiry(20)
        output = self._run()
        self.assertIn("1 new expiry reminder", output)
        sent = self._expiry_mails()
        self.assertEqual(len(sent), 1)
        self.assertIn("expiring soon", sent[0].subject)

        self._run()
        self.assertEqual(mail.outbox, [], "re-running the same day must not re-send")

        self._set_ssm_expiry(5)
        self._run()
        self.assertEqual(len(self._expiry_mails()), 1)
        self.assertEqual(self._ssm_keys(), [f"expiry-{self.company.pk}-ssm-week"])

        self._set_ssm_expiry(-1)
        self._run()
        sent = self._expiry_mails()
        self.assertEqual(len(sent), 1)
        self.assertIn("expired", sent[0].subject)
        self.assertEqual(self._ssm_keys(), [f"expiry-{self.company.pk}-ssm-expired"])

    def test_renewed_document_clears_reminder(self) -> None:
        self._set_ssm_expiry(20)
        self._run()
        self._set_ssm_expiry(400)
        self._run()
        self.assertEqual(self._ssm_keys(), [])
        self.assertEqual(self._expiry_mails(), [])

    def test_draft_companies_are_not_reminded(self) -> None:
        Company.objects.filter(pk=self.company.pk).update(registration_status=Company.RegistrationStatus.DRAFT)
        self._set_ssm_expiry(5)
        self._run()
        self.assertEqual(self._expiry_mails(), [])

    def test_envelope1_car_insurance_is_tracked(self) -> None:
        submission = make_submission(self.company)
        save_envelope1_pdf(
            submission=submission,
            doc_type=Envelope1Document.DocType.CAR_INSURANCE,
            uploaded=pdf("car.pdf"),
            user=self.vendor,
            expiry_date=timezone.localdate() + timedelta(days=3),
        )
        self._run()
        self.assertTrue(
            Notification.objects.filter(dedupe_key=f"expiry-{self.company.pk}-car_insurance-week").exists()
        )
        self.assertTrue(any("expiring soon" in m.subject for m in mail.outbox))

    def test_dry_run_saves_and_sends_nothing(self) -> None:
        self._set_ssm_expiry(20)
        out = StringIO()
        mail.outbox = []
        with self.captureOnCommitCallbacks(execute=True):
            call_command("send_expiry_reminders", "--dry-run", stdout=out)
        self.assertIn("1 reminder(s) would be sent", out.getvalue())
        self.assertIn("SSM", out.getvalue())
        self.assertEqual(self._ssm_keys(), [])
        self.assertEqual(mail.outbox, [])

    def test_staff_are_skipped(self) -> None:
        from accounts.roles import PROCUREMENT

        staff = make_user("procurement", PROCUREMENT)
        make_company(staff)
        output = self._run()
        self.assertIn("Checked 1 vendor", output)


class SendTestEmailCommandTests(TestCase):
    def test_sends_one_branded_email(self) -> None:
        out = StringIO()
        call_command("send_test_email", "ops@example.com", stdout=out)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["ops@example.com"])
        self.assertIn("Alpha Orange", message.alternatives[0][0])
        self.assertIn("Test email sent", out.getvalue())
