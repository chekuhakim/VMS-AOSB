"""Permission tests: vendors only see / edit their own company; registration alerts Procurement."""

from __future__ import annotations

from datetime import timedelta

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Notification
from accounts.roles import DIRECTOR, PROCUREMENT
from core.testing import make_company, make_user, pdf, staff_client, vendor_client
from vendors.models import Company, CompanyDocument, VendorInvitation
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


class VendorInvitationTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.procurement = make_user("invite-procurement", PROCUREMENT)
        cls.director = make_user("invite-director", DIRECTOR)

    def _invite(self, **overrides):
        data = {
            "company_name": "Invited Vendor Sdn Bhd",
            "email": "invited@example.com",
            "note": "Please register",
        }
        data.update(overrides)
        return staff_client(self.procurement).post(
            reverse("staff:vendor_invitations"), data
        )

    def test_procurement_can_send_invitation(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            response = self._invite()
        self.assertRedirects(response, reverse("staff:vendor_invitations"))
        invitation = VendorInvitation.objects.get(email="invited@example.com")
        self.assertEqual(invitation.company_name, "Invited Vendor Sdn Bhd")
        self.assertTrue(invitation.is_pending)
        self.assertEqual([m.to for m in mail.outbox], [["invited@example.com"]])
        self.assertIn("invite", mail.outbox[0].body)

    def test_director_cannot_send_invitation(self) -> None:
        response = staff_client(self.director).post(
            reverse("staff:vendor_invitations"),
            {"company_name": "No Invite Sdn Bhd", "email": "no@example.com"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(VendorInvitation.objects.filter(email="no@example.com").exists())

    def test_staff_email_cannot_be_invited(self) -> None:
        response = self._invite(email=self.procurement.email)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "belongs to a staff account")
        self.assertFalse(
            VendorInvitation.objects.filter(email=self.procurement.email).exists()
        )

    def test_invite_link_starts_signup_for_new_email(self) -> None:
        invitation = VendorInvitation.objects.create(
            company_name="New Vendor Sdn Bhd",
            email="newvendor@example.com",
            invited_by=self.procurement,
            expires_at=timezone.now() + timedelta(days=7),
        )
        response = self.client.get(
            reverse("vendors:accept_invitation", args=[invitation.token])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/register/", response["Location"])
        self.assertIn("email=newvendor%40example.com", response["Location"])

    def test_accepting_invitation_creates_company(self) -> None:
        vendor = make_user("invited-vendor")
        vendor.email = "accept@example.com"
        vendor.save(update_fields=["email"])
        invitation = VendorInvitation.objects.create(
            company_name="Accepted Vendor Sdn Bhd",
            email=vendor.email,
            invited_by=self.procurement,
            expires_at=timezone.now() + timedelta(days=7),
        )
        client = vendor_client(vendor)
        page = client.get(reverse("vendors:accept_invitation", args=[invitation.token]))
        self.assertEqual(page.status_code, 200)
        response = client.post(
            reverse("vendors:accept_invitation", args=[invitation.token])
        )
        company = Company.objects.get(owner=vendor, name="Accepted Vendor Sdn Bhd")
        self.assertRedirects(
            response, reverse("vendors:wizard_step", args=[company.pk, 1])
        )
        invitation.refresh_from_db()
        self.assertTrue(invitation.is_accepted)
        self.assertEqual(invitation.company, company)
        self.assertEqual(company.registration_status, Company.RegistrationStatus.DRAFT)


class RegistrationMsaAndIcTests(TestCase):
    def _company(self, name: str) -> Company:
        owner = make_user(name)
        return make_company(owner, status=Company.RegistrationStatus.DRAFT)

    def test_signed_msa_is_uploaded_in_the_final_step(self) -> None:
        company = self._company("msa-upload")
        company.documents.filter(doc_type=CompanyDocument.DocType.SIGNED_MSA).delete()
        response = vendor_client(company.owner, company).post(
            reverse("vendors:wizard_step", args=[company.pk, 6]),
            {"signed_msa_pdf": pdf("signed-msa.pdf")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            company.documents.filter(
                doc_type=CompanyDocument.DocType.SIGNED_MSA,
                original_filename="signed-msa.pdf",
            ).exists()
        )

    def test_msa_download_is_blocked_until_all_fields_are_complete(self) -> None:
        company = self._company("msa-incomplete")
        Company.objects.filter(pk=company.pk).update(principal_address="")
        response = vendor_client(company.owner, company).get(
            reverse("vendors:draft_msa", args=[company.pk])
        )
        self.assertRedirects(
            response,
            reverse("vendors:wizard_step", args=[company.pk, 6]),
            fetch_redirect_response=False,
        )

    def test_enterprise_requires_ic_and_accepts_image(self) -> None:
        company = self._company("ic-upload")
        company.documents.filter(doc_type=CompanyDocument.DocType.IC).delete()
        company.registration_type = Company.RegistrationType.ENTERPRISE
        company.save(update_fields=["registration_type"])
        url = reverse("vendors:wizard_step", args=[company.pk, 2])
        data = {
            "ssm_registration_number": company.ssm_registration_number,
            "date_of_incorporation": company.date_of_incorporation.isoformat(),
            "ssm_document_expiry": (
                timezone.localdate() + timedelta(days=30)
            ).isoformat(),
            "ic_number": "880101-12-3456",
        }
        missing = vendor_client(company.owner, company).post(url, data)
        self.assertEqual(missing.status_code, 200)
        self.assertContains(missing, "Upload the owner")

        data["ic_pdf"] = SimpleUploadedFile(
            "owner-ic.jpg", b"fake-image-bytes", content_type="image/jpeg"
        )
        uploaded = vendor_client(company.owner, company).post(url, data)
        self.assertRedirects(uploaded, reverse("vendors:wizard_step", args=[company.pk, 3]))
        company.refresh_from_db()
        self.assertEqual(company.ic_number, "880101-12-3456")
        self.assertTrue(
            company.documents.filter(
                doc_type=CompanyDocument.DocType.IC,
                original_filename="owner-ic.jpg",
            ).exists()
        )

    def test_individual_registers_with_ic_only(self) -> None:
        company = self._company("ic-only")
        company.registration_type = Company.RegistrationType.INDIVIDUAL
        company.save(update_fields=["registration_type"])
        company.documents.filter(doc_type=CompanyDocument.DocType.SSM).delete()
        url = reverse("vendors:wizard_step", args=[company.pk, 2])
        response = vendor_client(company.owner, company).post(
            url,
            {
                "ic_number": "890202-14-5678",
                "ic_pdf": SimpleUploadedFile(
                    "ic-only.jpg", b"fake-image", content_type="image/jpeg"
                ),
            },
        )
        self.assertRedirects(response, reverse("vendors:wizard_step", args=[company.pk, 3]))
        company.refresh_from_db()
        self.assertEqual(company.registration_type, Company.RegistrationType.INDIVIDUAL)
        self.assertEqual(company.ssm_registration_number, "")
        self.assertIsNone(company.date_of_incorporation)
        self.assertEqual(company.ic_number, "890202-14-5678")
        self.assertTrue(
            company.documents.filter(doc_type=CompanyDocument.DocType.IC).exists()
        )
        self.assertFalse(
            company.documents.filter(doc_type=CompanyDocument.DocType.SSM).exists()
        )

    def test_individual_registration_can_be_approved_without_ssm(self) -> None:
        company = self._company("ic-only-rules")
        company.registration_type = Company.RegistrationType.INDIVIDUAL
        company.ic_number = "890202-14-5678"
        company.lhdn_tin = ""
        company.no_cidb_registration = True
        company.cidb_registration_number = ""
        company.cidb_grade = ""
        company.cidb_certificate_expiry = None
        company.includes_electrical_work = False
        company.st_license_number = ""
        company.st_certificate_expiry = None
        company.declaration_accepted = True
        company.declaration_text_version = "test"
        company.save()
        company.documents.filter(doc_type=CompanyDocument.DocType.SSM).delete()
        result = evaluate_company_registration(company)
        self.assertTrue(result.approved, result.reason_codes)
        self.assertNotIn("incomplete_ssm", result.reason_codes)
        self.assertNotIn("missing_ssm_document", result.reason_codes)
        self.assertNotIn("incomplete_lhdn", result.reason_codes)


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
