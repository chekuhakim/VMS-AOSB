"""Permission tests: vendors only reach their own Envelope 1; submitted / locked packs can't be edited."""

from __future__ import annotations

from django.test import TestCase
from django.urls import reverse

from accounts.roles import PROCUREMENT
from core.testing import make_company, make_submission, make_user, pdf, staff_client, vendor_client
from envelope1.documents import save_envelope1_pdf
from envelope1.models import Envelope1Document, Envelope1Submission

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
        self.assertContains(page, self.reopen)
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
        self.assertContains(page, "Envelope 1 under procurement check")
        self.assertContains(page, reverse("envelope1:withdrawal", args=[self.submission.pk]))
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
