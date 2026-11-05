"""Permission tests: vendors only see / edit their own company; registration alerts Procurement."""

from __future__ import annotations

from datetime import timedelta

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Notification
from accounts.roles import DIRECTOR, PROCUREMENT
from core.testing import make_company, make_user, pdf, vendor_client
from vendors.models import Company, CompanyDocument
from vendors.rules import evaluate_company_registration


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


class RegistrationUploadKeptTests(TestCase):
    def test_cidb_pdf_survives_a_missing_grade(self) -> None:
        owner = make_user("cidb-owner")
        company = make_company(owner, status=Company.RegistrationStatus.DRAFT)
        company.documents.filter(doc_type=CompanyDocument.DocType.CIDB).delete()
        company.cidb_grade = ""
        company.save(update_fields=["cidb_grade"])
        expiry = (timezone.localdate() + timedelta(days=40)).isoformat()
        response = vendor_client(owner, company).post(
            reverse("vendors:wizard_step", args=[company.pk, 3]),
            {
                "cidb_registration_number": "CIDB-KEEP-1",
                "cidb_grade": "",
                "cidb_certificate_expiry": expiry,
                "cidb_pdf": pdf("cidb-cert.pdf"),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CIDB PDF already on file")
        self.assertTrue(
            company.documents.filter(
                doc_type=CompanyDocument.DocType.CIDB,
                original_filename="cidb-cert.pdf",
            ).exists()
        )

    def test_no_cidb_registration_skips_certificate_fields(self) -> None:
        owner = make_user("no-cidb-owner")
        company = make_company(owner, status=Company.RegistrationStatus.DRAFT)
        self.assertTrue(company.documents.filter(doc_type=CompanyDocument.DocType.CIDB).exists())
        response = vendor_client(owner, company).post(
            reverse("vendors:wizard_step", args=[company.pk, 3]),
            {"no_cidb_registration": "on"},
        )
        self.assertEqual(response.status_code, 302)
        company.refresh_from_db()
        self.assertTrue(company.no_cidb_registration)
        self.assertEqual(company.cidb_registration_number, "")
        self.assertEqual(company.cidb_grade, "")
        self.assertIsNone(company.cidb_certificate_expiry)
        self.assertFalse(company.documents.filter(doc_type=CompanyDocument.DocType.CIDB).exists())

    def test_declared_no_cidb_can_pass_registration_rules(self) -> None:
        owner = make_user("no-cidb-rules")
        company = make_company(owner, status=Company.RegistrationStatus.DRAFT)
        company.no_cidb_registration = True
        company.cidb_registration_number = ""
        company.cidb_grade = ""
        company.cidb_certificate_expiry = None
        company.declaration_accepted = True
        company.declaration_text_version = "test"
        company.save()
        company.documents.filter(doc_type=CompanyDocument.DocType.CIDB).delete()
        result = evaluate_company_registration(company)
        self.assertNotIn("incomplete_cidb", result.reason_codes)
        self.assertNotIn("missing_cidb_document", result.reason_codes)
        self.assertTrue(result.approved)


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
