"""Permission tests: vendors only see / edit their own company; registration alerts Procurement."""

from __future__ import annotations

from django.core import mail
from django.test import TestCase
from django.urls import reverse

from accounts.models import Notification
from accounts.roles import DIRECTOR, PROCUREMENT
from core.testing import make_company, make_user, vendor_client
from vendors.models import Company


class CompanyIsolationTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.alice = make_user("alice")
        cls.bob = make_user("bob")
        cls.alice_co = make_company(cls.alice, status=Company.RegistrationStatus.DRAFT)

    def setUp(self) -> None:
        self.bob_client = vendor_client(self.bob)

    def test_other_vendor_cannot_view_company(self) -> None:
        url = reverse("vendors:company_detail", args=[self.alice_co.pk])
        self.assertEqual(self.bob_client.get(url).status_code, 404)
        self.assertEqual(vendor_client(self.alice).get(url).status_code, 200)

    def test_other_vendor_cannot_open_or_post_wizard(self) -> None:
        url = reverse("vendors:wizard_step", args=[self.alice_co.pk, 1])
        self.assertEqual(self.bob_client.get(url).status_code, 404)
        self.assertEqual(self.bob_client.post(url, {"name": "Hijacked"}).status_code, 404)
        self.alice_co.refresh_from_db()
        self.assertNotEqual(self.alice_co.name, "Hijacked")

    def test_other_vendor_cannot_delete_company(self) -> None:
        response = self.bob_client.post(reverse("vendors:delete_company", args=[self.alice_co.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Company.objects.filter(pk=self.alice_co.pk).exists())

    def test_your_company_lists_only_own(self) -> None:
        make_company(self.bob, status=Company.RegistrationStatus.DRAFT)
        page = self.bob_client.get(reverse("vendors:your_company"))
        self.assertNotContains(page, reverse("vendors:company_detail", args=[self.alice_co.pk]))


class CompanyDeletionRetentionTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.vendor = make_user("vendor")

    def test_draft_company_can_be_deleted(self) -> None:
        company = make_company(self.vendor, status=Company.RegistrationStatus.DRAFT)
        vendor_client(self.vendor).post(reverse("vendors:delete_company", args=[company.pk]))
        self.assertFalse(Company.objects.filter(pk=company.pk).exists())

    def test_submitted_companies_are_kept(self) -> None:
        for status in (Company.RegistrationStatus.APPROVED, Company.RegistrationStatus.REJECTED):
            with self.subTest(status=status):
                company = make_company(self.vendor, status=status)
                vendor_client(self.vendor).post(reverse("vendors:delete_company", args=[company.pk]))
                self.assertTrue(Company.objects.filter(pk=company.pk).exists())

    def test_delete_button_only_on_drafts(self) -> None:
        draft = make_company(self.vendor, status=Company.RegistrationStatus.DRAFT)
        approved = make_company(self.vendor, status=Company.RegistrationStatus.APPROVED)
        page = vendor_client(self.vendor).get(reverse("vendors:your_company"))
        self.assertContains(page, reverse("vendors:delete_company", args=[draft.pk]))
        self.assertNotContains(page, reverse("vendors:delete_company", args=[approved.pk]))


class RegistrationNotificationTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.procurement = make_user("procurement", PROCUREMENT)
        cls.director = make_user("director", DIRECTOR)
        cls.vendor = make_user("vendor")

    def _submit(self, company: Company) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            vendor_client(self.vendor).post(
                reverse("vendors:wizard_step", args=[company.pk, 6]), {"declaration_accepted": "on"}
            )
        company.refresh_from_db()

    def test_approved_registration_alerts_procurement_only(self) -> None:
        company = make_company(self.vendor, status=Company.RegistrationStatus.DRAFT)
        self._submit(company)
        self.assertEqual(company.registration_status, Company.RegistrationStatus.APPROVED)
        note = Notification.objects.get(user=self.procurement, dedupe_key=f"staff-company-{company.pk}-registration")
        self.assertIn("New company registered", note.title)
        self.assertEqual([m.to for m in mail.outbox], [[self.procurement.email]])

    def test_rejected_registration_lists_readable_reasons(self) -> None:
        company = make_company(self.vendor, status=Company.RegistrationStatus.DRAFT)
        Company.objects.filter(pk=company.pk).update(bank_account_name="")
        self._submit(company)
        self.assertEqual(company.registration_status, Company.RegistrationStatus.REJECTED)
        note = Notification.objects.get(user=self.procurement, dedupe_key=f"staff-company-{company.pk}-registration")
        self.assertEqual(note.level, Notification.Level.WARNING)
        self.assertNotIn("incomplete_lhdn", note.body)
