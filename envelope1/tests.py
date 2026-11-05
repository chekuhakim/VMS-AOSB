"""Permission tests: vendors only reach their own Envelope 1; submitted / locked packs can't be edited."""

from __future__ import annotations

from django.test import TestCase
from django.urls import reverse

from accounts.roles import PROCUREMENT
from core.testing import make_company, make_submission, make_user, pdf, staff_client, vendor_client
from envelope1.documents import save_envelope1_pdf
from envelope1.msa import (
    build_draft_msa_pdf,
    build_no_advance_pdf,
    msa_download_filename,
    no_advance_download_filename,
    render_draft_msa_html,
    render_no_advance_html,
)
from envelope1.models import (
    Envelope1Document,
    Envelope1Submission,
    FinancialStatement,
)

S = Envelope1Submission.Status


class VendorIsolationTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.alice = make_user("alice")
        cls.bob = make_user("bob")
        cls.alice_co = make_company(cls.alice)
        cls.bob_co = make_company(cls.bob)
        cls.alice_sub = make_submission(cls.alice_co)
        cls.alice_doc = save_envelope1_pdf(
            submission=cls.alice_sub,
            doc_type=Envelope1Document.DocType.ORG_CHART,
            uploaded=pdf("alice-org.pdf"),
            user=cls.alice,
        )

    def setUp(self) -> None:
        self.bob_client = vendor_client(self.bob, self.bob_co)

    def test_other_vendor_cannot_open_wizard(self) -> None:
        response = self.bob_client.get(reverse("envelope1:wizard", args=[self.alice_sub.pk, 1]))
        self.assertRedirects(response, reverse("envelope1:home"), fetch_redirect_response=False)

    def test_other_vendor_cannot_post_to_wizard(self) -> None:
        self.bob_client.post(
            reverse("envelope1:wizard", args=[self.alice_sub.pk, 5]), {"site_supervisor_name": "Hijack"}
        )
        self.alice_sub.refresh_from_db()
        self.assertNotEqual(self.alice_sub.site_supervisor_name, "Hijack")

    def test_other_vendor_cannot_open_document(self) -> None:
        url = reverse("envelope1:view_envelope1_document", args=[self.alice_doc.pk])
        self.assertEqual(self.bob_client.get(url).status_code, 404)
        self.assertEqual(vendor_client(self.alice, self.alice_co).get(url).status_code, 200)

    def test_other_vendor_cannot_download_draft_msa_or_reopen(self) -> None:
        response = self.bob_client.get(reverse("envelope1:draft_msa", args=[self.alice_sub.pk]))
        self.assertRedirects(response, reverse("envelope1:home"), fetch_redirect_response=False)
        Envelope1Submission.objects.filter(pk=self.alice_sub.pk).update(status=S.PENDING_EVALUATION)
        self.bob_client.post(reverse("envelope1:reopen", args=[self.alice_sub.pk]))
        self.alice_sub.refresh_from_db()
        self.assertEqual(self.alice_sub.status, S.PENDING_EVALUATION)

    def test_switching_session_to_foreign_company_is_ignored(self) -> None:
        client = vendor_client(self.bob, self.alice_co)
        response = client.get(reverse("envelope1:wizard", args=[self.alice_sub.pk, 1]))
        self.assertRedirects(response, reverse("envelope1:home"), fetch_redirect_response=False)

    def test_staff_cannot_use_vendor_wizard(self) -> None:
        procurement = make_user("procurement", PROCUREMENT)
        response = staff_client(procurement).get(reverse("envelope1:wizard", args=[self.alice_sub.pk, 1]))
        self.assertEqual(response.status_code, 403)

    def test_unapproved_company_cannot_start_envelope1(self) -> None:
        carol = make_user("carol")
        draft_co = make_company(carol, status="submitted")
        response = vendor_client(carol, draft_co).get(reverse("envelope1:home"))
        self.assertRedirects(
            response, reverse("vendors:company_detail", args=[draft_co.pk]), fetch_redirect_response=False
        )


class UploadKeptOnValidationErrorTests(TestCase):
    """A valid PDF stays stored when another field on the same step fails."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.vendor = make_user("keeper")
        cls.company = make_company(cls.vendor)

    def setUp(self) -> None:
        self.client = vendor_client(self.vendor, self.company)
        self.submission = make_submission(self.company)

    def test_quality_plan_pdf_survives_a_missing_declaration(self) -> None:
        url = reverse("envelope1:wizard", args=[self.submission.pk, 5])
        response = self.client.post(
            url,
            {
                "has_quality_plan": "yes",
                "has_hse_plan": "no",
                "site_supervisor_name": "Siti Ahmad",
                "quality_plan_pdf": pdf("quality-plan.pdf"),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "quality-plan.pdf")
        self.assertContains(response, "Please fix the highlighted fields.")
        stored = Envelope1Document.objects.filter(
            submission=self.submission,
            doc_type=Envelope1Document.DocType.QUALITY_PLAN,
        )
        self.assertEqual(stored.count(), 1)

        # Submitting again without the file must not ask for it or store a second copy
        again = self.client.post(
            url,
            {
                "has_quality_plan": "yes",
                "has_hse_plan": "no",
                "site_supervisor_name": "Siti Ahmad",
                "accepts_timestamped_reporting": "on",
                "accepts_metmalaysia_eot": "on",
            },
        )
        self.assertRedirects(again, reverse("envelope1:wizard", args=[self.submission.pk, 6]))
        self.assertEqual(stored.count(), 1)

    def test_financial_statement_row_survives_when_a_second_year_is_missing(self) -> None:
        url = reverse("envelope1:wizard", args=[self.submission.pk, 3])
        response = self.client.post(
            url,
            {
                "fs-TOTAL_FORMS": "2",
                "fs-INITIAL_FORMS": "0",
                "fs-MIN_NUM_FORMS": "0",
                "fs-MAX_NUM_FORMS": "1000",
                "fs-0-row_id": "",
                "fs-0-year": "2024",
                "fs-0-DELETE": "",
                "fs-1-row_id": "",
                "fs-1-year": "",
                "fs-1-DELETE": "",
                "fs-0-pdf": pdf("statement-2024.pdf"),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "statement-2024.pdf")
        self.assertEqual(FinancialStatement.objects.filter(submission=self.submission).count(), 1)
        row = FinancialStatement.objects.get(submission=self.submission)
        self.assertEqual(row.year, 2024)
        self.assertContains(response, f'value="{row.pk}"')


class SubmittedPackLockTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.vendor = make_user("vendor")
        cls.company = make_company(cls.vendor)

    def setUp(self) -> None:
        self.client = vendor_client(self.vendor, self.company)
        self.submission = make_submission(self.company, S.PENDING_EVALUATION)
        self.wizard = reverse("envelope1:wizard", args=[self.submission.pk, 5])
        self.reopen = reverse("envelope1:reopen", args=[self.submission.pk])

    def test_submitted_pack_shows_overlay_and_rejects_edits(self) -> None:
        page = self.client.get(self.wizard)
        self.assertContains(page, "Envelope 1 submitted")
        self.assertContains(page, "You can still edit this submission until Procurement starts the check.")
        self.assertContains(page, self.reopen)
        self.assertNotContains(page, "site_supervisor_name")
        self.client.post(self.wizard, {"site_supervisor_name": "Changed"})
        self.submission.refresh_from_db()
        self.assertNotEqual(self.submission.site_supervisor_name, "Changed")

    def test_edit_moves_pack_back_to_draft(self) -> None:
        self.assertEqual(self.client.get(self.reopen).status_code, 405)
        self.client.post(self.reopen)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, S.DRAFT)
        self.assertIsNone(self.submission.submitted_at)
        self.assertNotContains(self.client.get(self.wizard), 'id="e1-overlay-title"')

    def test_locked_pack_cannot_be_reopened(self) -> None:
        Envelope1Submission.objects.filter(pk=self.submission.pk).update(status=S.IN_PROGRESS)
        self.submission.refresh_from_db()
        self.submission.locked_at = self.submission.updated_at
        self.submission.save(update_fields=["locked_at"])
        page = self.client.get(self.wizard)
        self.assertContains(page, "Envelope 1 is locked")
        self.assertContains(
            page,
            "Procurement has started the check, so this submission is locked.",
        )
        self.assertContains(page, "Request a withdrawal")
        self.assertContains(page, reverse("envelope1:withdrawal", args=[self.submission.pk]))
        self.assertNotContains(page, self.reopen)
        self.client.post(self.reopen)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, S.IN_PROGRESS)

    def test_withdrawal_only_for_locked_packs(self) -> None:
        response = self.client.post(
            reverse("envelope1:withdrawal", args=[self.submission.pk]), {"reason": "x"}
        )
        self.assertRedirects(
            response, reverse("envelope1:wizard", args=[self.submission.pk, 1]), fetch_redirect_response=False
        )
        self.assertFalse(self.submission.withdrawal_requests.exists())


class LeadTimeRangeTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.user = make_user("lead-time-vendor")
        cls.company = make_company(cls.user)
        cls.submission = make_submission(cls.company)
        cls.url = reverse("envelope1:wizard", args=[cls.submission.pk, 4])

    def setUp(self) -> None:
        self.client = vendor_client(self.user, self.company)

    def _post(self, **overrides: str):
        data = {
            "sabah_interest": "yes",
            "lead_time_range": "30_60",
            "sup-TOTAL_FORMS": "1",
            "sup-INITIAL_FORMS": "0",
            "sup-MIN_NUM_FORMS": "0",
            "sup-MAX_NUM_FORMS": "1000",
            "sup-0-structure": "Steel monopole",
            "sup-0-supplier_name": "Test Supplier Sdn Bhd",
        }
        data.update(overrides)
        return self.client.post(self.url, data)

    def test_sabah_interest_requires_a_lead_time_range(self) -> None:
        response = self._post(lead_time_range="")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Choose a lead-time range for Sabah work.")
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.lead_time_range, "")

    def test_sabah_interest_saves_the_selected_range(self) -> None:
        response = self._post(lead_time_range="60_90")
        self.assertRedirects(
            response, reverse("envelope1:wizard", args=[self.submission.pk, 5])
        )
        self.submission.refresh_from_db()
        self.assertTrue(self.submission.sabah_interest)
        self.assertEqual(self.submission.lead_time_range, "60_90")

    def test_no_sabah_interest_clears_the_range(self) -> None:
        response = self._post(sabah_interest="no", lead_time_range="30_60")
        self.assertRedirects(
            response, reverse("envelope1:wizard", args=[self.submission.pk, 5])
        )
        self.submission.refresh_from_db()
        self.assertFalse(self.submission.sabah_interest)
        self.assertEqual(self.submission.lead_time_range, "")


class DraftMsaPdfTests(TestCase):
    def test_download_is_the_agreement_filled_with_party_details(self) -> None:
        submission = Envelope1Submission(
            legal_name="Cahaya Unique Sdn Bhd",
            ssm_registration_number="202301234567",
            principal_address="7-1F, Jalan Setia Perdana",
            msa_signatory_name="Hakim bin Ahmad",
            msa_signatory_designation="Director",
        )
        html = render_draft_msa_html(submission)
        self.assertIn("MASTER SERVICE AGREEMENT", html)
        self.assertIn("Occupational Safety and Health Act 1994", html)
        self.assertIn("Malaysian Anti-Corruption Commission Act 2009", html)
        self.assertIn("Cahaya Unique Sdn Bhd", html)
        self.assertIn("202301234567", html)
        self.assertIn("7-1F, Jalan Setia Perdana", html)
        self.assertIn("Che Ku Mohamad Hakim bin Che Ku Abdullah", html)
        self.assertNotIn("[Contractor Company Name]", html)
        pdf = build_draft_msa_pdf(submission)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 10_000)
        self.assertEqual(msa_download_filename(submission), "Cahaya Unique Sdn Bhd - MSA.pdf")


class NoAdvanceDeclarationPdfTests(TestCase):
    def test_download_is_expanded_declaration_filled_with_party_details(self) -> None:
        submission = Envelope1Submission(
            legal_name="Cahaya Unique Sdn Bhd",
            ssm_registration_number="202301234567",
            principal_address="7-1F, Jalan Setia Perdana",
            msa_signatory_name="Hakim bin Ahmad",
            msa_signatory_designation="Director",
        )
        html = render_no_advance_html(submission)
        self.assertIn("Declaration of No Advance Payment", html)
        self.assertIn("NOW THE CONTRACTOR DECLARES", html)
        self.assertIn("mobilisation payment", html)
        self.assertIn("Section 4 of the Master Service Agreement", html)
        self.assertIn("Cahaya Unique Sdn Bhd", html)
        self.assertIn("Hakim bin Ahmad", html)
        self.assertNotIn("Envelope 1, item 1.4", html)
        pdf = build_no_advance_pdf(submission)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 8000)
        self.assertEqual(
            no_advance_download_filename(submission),
            "Cahaya Unique Sdn Bhd - No Advance Payment Declaration.pdf",
        )
