"""Permission tests: staff pages and ISO 9001 segregation of duties (Procurement evaluates, Director approves)."""

from __future__ import annotations

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Notification
from accounts.roles import DIRECTOR, PROCUREMENT, SYSTEM_ADMIN, VIEWER
from core.testing import (
    make_company,
    make_open_project,
    make_quotation,
    make_submission,
    make_user,
    staff_client,
    vendor_client,
)
from envelope1.models import Envelope1Item, Envelope1Submission, WithdrawalRequest
from staff.models import Envelope1ItemEvaluation
from tenders.models import TenderAward

STAFF_PAGES = [
    "staff:admin_dashboard",
    "staff:company_list",
    "staff:envelope1_list",
    "staff:approval_queue",
    "staff:withdrawal_list",
    "staff:audit_log",
    "tenders:tender_list",
]

S = Envelope1Submission.Status


class StaffPageAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.vendor = make_user("vendor")
        cls.viewer = make_user("viewer", VIEWER)

    def test_anonymous_is_sent_to_login(self) -> None:
        for name in STAFF_PAGES:
            with self.subTest(page=name):
                response = Client().get(reverse(name))
                self.assertEqual(response.status_code, 302)
                self.assertIn("login", response["Location"])

    def test_vendor_is_forbidden(self) -> None:
        client = vendor_client(self.vendor)
        for name in STAFF_PAGES:
            with self.subTest(page=name):
                self.assertEqual(client.get(reverse(name)).status_code, 403)

    def test_viewer_can_read_every_staff_page(self) -> None:
        client = staff_client(self.viewer)
        for name in STAFF_PAGES:
            with self.subTest(page=name):
                self.assertEqual(client.get(reverse(name)).status_code, 200)

    def test_hidden_company_is_not_listed(self) -> None:
        company = make_company(self.vendor)
        company.is_hidden = True
        company.save(update_fields=["is_hidden"])
        page = staff_client(self.viewer).get(reverse("staff:company_list"))
        self.assertNotContains(page, company.name)

    def test_vendor_cannot_open_staff_company_or_envelope_pages(self) -> None:
        company = make_company(self.vendor)
        submission = make_submission(company, S.PENDING_EVALUATION)
        client = vendor_client(self.vendor, company)
        self.assertEqual(client.get(reverse("staff:company_detail", args=[company.pk])).status_code, 403)
        self.assertEqual(client.get(reverse("staff:envelope1_detail", args=[submission.pk])).status_code, 403)


class EnvelopeSegregationOfDutiesTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.vendor = make_user("vendor")
        cls.viewer = make_user("viewer", VIEWER)
        cls.procurement = make_user("procurement", PROCUREMENT)
        cls.director = make_user("director", DIRECTOR)
        cls.admin = make_user("sysadmin", SYSTEM_ADMIN)

    def setUp(self) -> None:
        self.company = make_company(self.vendor)
        self.submission = make_submission(self.company, S.PENDING_EVALUATION)

    def _lock_as(self, user) -> None:  # type: ignore[no-untyped-def]
        staff_client(user).post(reverse("staff:envelope1_lock", args=[self.submission.pk]))
        self.submission.refresh_from_db()

    def test_vendor_cannot_lock(self) -> None:
        response = vendor_client(self.vendor).post(reverse("staff:envelope1_lock", args=[self.submission.pk]))
        self.assertEqual(response.status_code, 403)
        self.submission.refresh_from_db()
        self.assertFalse(self.submission.is_locked)

    def test_viewer_cannot_lock(self) -> None:
        self._lock_as(self.viewer)
        self.assertFalse(self.submission.is_locked)

    def test_director_cannot_lock(self) -> None:
        self._lock_as(self.director)
        self.assertFalse(self.submission.is_locked)

    def test_procurement_can_lock(self) -> None:
        self._lock_as(self.procurement)
        self.assertTrue(self.submission.is_locked)
        self.assertEqual(self.submission.status, S.IN_PROGRESS)

    def test_system_admin_can_lock(self) -> None:
        self._lock_as(self.admin)
        self.assertTrue(self.submission.is_locked)

    def test_lock_requires_post(self) -> None:
        response = staff_client(self.procurement).get(reverse("staff:envelope1_lock", args=[self.submission.pk]))
        self.assertEqual(response.status_code, 405)

    def test_procurement_cannot_approve_as_director(self) -> None:
        Envelope1Submission.objects.filter(pk=self.submission.pk).update(status=S.PENDING_DIRECTOR)
        staff_client(self.procurement).post(
            reverse("staff:approval_decide", args=[self.submission.pk]), {"decision": "approve"}
        )
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, S.PENDING_DIRECTOR)

    def test_viewer_cannot_approve(self) -> None:
        Envelope1Submission.objects.filter(pk=self.submission.pk).update(status=S.PENDING_DIRECTOR)
        staff_client(self.viewer).post(
            reverse("staff:approval_decide", args=[self.submission.pk]), {"decision": "approve"}
        )
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, S.PENDING_DIRECTOR)

    def test_finished_evaluation_shows_checkmark_without_director_field(self) -> None:
        Envelope1Submission.objects.filter(pk=self.submission.pk).update(
            status=S.PENDING_DIRECTOR, locked_at=self.submission.updated_at
        )
        page = staff_client(self.procurement).get(
            reverse("staff:envelope1_evaluate", args=[self.submission.pk, 4])
        )
        self.assertContains(page, "Evaluation complete")
        self.assertContains(page, reverse("staff:envelope1_reopen_eval", args=[self.submission.pk]))
        self.assertNotContains(page, "Director decision")
        self.assertNotContains(page, 'name="decision"')

    def test_procurement_can_reopen_evaluation(self) -> None:
        Envelope1Submission.objects.filter(pk=self.submission.pk).update(status=S.PENDING_DIRECTOR)
        staff_client(self.procurement).post(
            reverse("staff:envelope1_reopen_eval", args=[self.submission.pk])
        )
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, S.IN_PROGRESS)

    def test_director_reviews_read_only_and_decides_on_the_last_step(self) -> None:
        Envelope1Submission.objects.filter(pk=self.submission.pk).update(status=S.PENDING_DIRECTOR)
        client = staff_client(self.director)
        queue = client.get(reverse("staff:approval_queue"))
        review = reverse("staff:envelope1_evaluate", args=[self.submission.pk, 1]) + "?review=1"
        self.assertContains(queue, review)
        self.assertNotContains(queue, 'name="decision"')
        first = client.get(review)
        self.assertContains(first, "Read-only evaluation")
        self.assertNotContains(first, 'name="decision"')
        last = client.get(reverse("staff:envelope1_evaluate", args=[self.submission.pk, 4]) + "?review=1")
        self.assertContains(last, "Approve")
        self.assertContains(last, "Reject")
        self.assertNotContains(last, "Save Progress")

    def test_director_can_approve(self) -> None:
        Envelope1Submission.objects.filter(pk=self.submission.pk).update(status=S.PENDING_DIRECTOR)
        staff_client(self.director).post(
            reverse("staff:approval_decide", args=[self.submission.pk]), {"decision": "approve"}
        )
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, S.APPROVED)

    def test_director_approval_note_stays_internal(self) -> None:
        Envelope1Submission.objects.filter(pk=self.submission.pk).update(status=S.PENDING_DIRECTOR)
        staff_client(self.director).post(
            reverse("staff:approval_decide", args=[self.submission.pk]),
            {"decision": "approve", "note": "be careful with this vendor"},
        )
        note = Notification.objects.get(
            user=self.vendor, dedupe_key=f"e1-{self.submission.pk}-status"
        )
        self.assertIn("pre-qualified", note.body)
        self.assertNotIn("be careful with this vendor", note.body)

    def test_director_rejection_note_stays_internal(self) -> None:
        Envelope1Submission.objects.filter(pk=self.submission.pk).update(status=S.PENDING_DIRECTOR)
        staff_client(self.director).post(
            reverse("staff:approval_decide", args=[self.submission.pk]),
            {"decision": "reject", "note": "internal legal concern"},
        )
        note = Notification.objects.get(
            user=self.vendor, dedupe_key=f"e1-{self.submission.pk}-status"
        )
        self.assertIn("did not approve", note.body)
        self.assertNotIn("internal legal concern", note.body)

    def test_director_cannot_reject_at_evaluation(self) -> None:
        Envelope1Submission.objects.filter(pk=self.submission.pk).update(status=S.IN_PROGRESS)
        staff_client(self.director).post(
            reverse("staff:envelope1_reject_eval", args=[self.submission.pk]), {"note": "no"}
        )
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, S.IN_PROGRESS)

    def test_return_for_correction_requires_a_failed_item(self) -> None:
        self._lock_as(self.procurement)
        self.submission.item_evaluations.update(result=Envelope1ItemEvaluation.Result.PASS)
        staff_client(self.procurement).post(
            reverse("staff:envelope1_return_correction", args=[self.submission.pk]),
            {"note": ""},
        )
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, S.IN_PROGRESS)

    def test_failed_items_are_returned_and_only_those_are_reopened(self) -> None:
        self._lock_as(self.procurement)
        self.submission.item_evaluations.update(result=Envelope1ItemEvaluation.Result.PASS)
        self.submission.item_evaluations.filter(
            doc_type=Envelope1Item.SITE_SUPERVISOR
        ).update(
            result=Envelope1ItemEvaluation.Result.FAIL,
            note="Upload a clearer supervisor CV.",
        )

        eval_page = staff_client(self.procurement).get(
            reverse("staff:envelope1_evaluate", args=[self.submission.pk, 4])
        )
        self.assertContains(eval_page, "Return for correction")

        response = staff_client(self.procurement).post(
            reverse("staff:envelope1_return_correction", args=[self.submission.pk]),
            {"note": "Please fix the returned item."},
        )
        self.assertRedirects(
            response,
            reverse("staff:envelope1_evaluate", args=[self.submission.pk, 4]),
        )
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, S.RETURNED_FOR_CORRECTION)
        self.assertFalse(self.submission.is_locked)
        self.assertEqual(self.submission.returned_note, "Please fix the returned item.")

        vendor = vendor_client(self.vendor, self.company)
        page = vendor.get(reverse("envelope1:corrections", args=[self.submission.pk]))
        self.assertContains(page, "Dedicated site supervisor")
        self.assertContains(page, "Upload a clearer supervisor CV.")
        self.assertContains(
            page, reverse("envelope1:resubmit_correction", args=[self.submission.pk])
        )

        resubmit = vendor.post(
            reverse("envelope1:resubmit_correction", args=[self.submission.pk])
        )
        self.assertRedirects(
            resubmit, reverse("envelope1:home"), fetch_redirect_response=False
        )
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, S.PENDING_EVALUATION)
        self.assertEqual(self.submission.correction_round, 1)
        self.assertEqual(
            self.submission.item_evaluations.get(
                doc_type=Envelope1Item.SITE_SUPERVISOR
            ).result,
            Envelope1ItemEvaluation.Result.PENDING,
        )
        self.assertEqual(
            self.submission.item_evaluations.get(
                doc_type=Envelope1Item.ORG_CHART
            ).result,
            Envelope1ItemEvaluation.Result.PASS,
        )

    def test_correction_mode_blocks_steps_without_returned_items(self) -> None:
        self._lock_as(self.procurement)
        self.submission.item_evaluations.update(result=Envelope1ItemEvaluation.Result.PASS)
        self.submission.item_evaluations.filter(
            doc_type=Envelope1Item.SITE_SUPERVISOR
        ).update(result=Envelope1ItemEvaluation.Result.FAIL, note="Fix this.")
        staff_client(self.procurement).post(
            reverse("staff:envelope1_return_correction", args=[self.submission.pk])
        )
        vendor = vendor_client(self.vendor, self.company)
        self.assertRedirects(
            vendor.get(reverse("envelope1:wizard", args=[self.submission.pk, 2])),
            reverse("envelope1:corrections", args=[self.submission.pk]),
        )
        allowed = vendor.get(reverse("envelope1:wizard", args=[self.submission.pk, 3]))
        self.assertEqual(allowed.status_code, 200)
        self.assertContains(allowed, "Correction mode")
        self.assertContains(allowed, "Needs correction", count=1)

    def test_only_procurement_decides_withdrawals(self) -> None:
        Envelope1Submission.objects.filter(pk=self.submission.pk).update(status=S.IN_PROGRESS)
        withdrawal = WithdrawalRequest.objects.create(
            submission=self.submission, requested_by=self.vendor, reason="typo"
        )
        url = reverse("staff:withdrawal_decide", args=[withdrawal.pk])
        for user in (self.director, self.viewer):
            staff_client(user).post(url, {"decision": "approve"})
            withdrawal.refresh_from_db()
            self.assertEqual(withdrawal.status, WithdrawalRequest.Status.PENDING, user.username)
        self.assertEqual(vendor_client(self.vendor).post(url, {"decision": "approve"}).status_code, 403)
        staff_client(self.procurement).post(url, {"decision": "approve"})
        withdrawal.refresh_from_db()
        self.assertEqual(withdrawal.status, WithdrawalRequest.Status.APPROVED)


class AwardSegregationOfDutiesTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.vendor = make_user("vendor")
        cls.procurement = make_user("procurement", PROCUREMENT)
        cls.director = make_user("director", DIRECTOR)
        cls.company = make_company(cls.vendor)

    def setUp(self) -> None:
        from datetime import timedelta

        self.project, self.rfq = make_open_project(self.procurement)
        self.quote = make_quotation(self.rfq, self.company)
        # Closed project so awards are allowed
        self.project.closing_at = self.project.closing_at - timedelta(days=4)
        self.project.save(update_fields=["closing_at"])

    def test_director_cannot_recommend(self) -> None:
        staff_client(self.director).post(
            reverse("tenders:award_recommend", args=[self.rfq.pk]), {"quotation": self.quote.pk, "note": "x"}
        )
        self.assertFalse(TenderAward.objects.exists())

    def test_procurement_cannot_approve_own_recommendation(self) -> None:
        staff_client(self.procurement).post(
            reverse("tenders:award_recommend", args=[self.rfq.pk]), {"quotation": self.quote.pk, "note": "Lowest"}
        )
        award = TenderAward.objects.get()
        staff_client(self.procurement).post(reverse("tenders:award_decide", args=[award.pk]), {"decision": "approve"})
        award.refresh_from_db()
        self.assertEqual(award.status, TenderAward.Status.PENDING_DIRECTOR)
        staff_client(self.director).post(reverse("tenders:award_decide", args=[award.pk]), {"decision": "approve"})
        award.refresh_from_db()
        self.assertEqual(award.status, TenderAward.Status.APPROVED)

    def test_director_cannot_create_projects(self) -> None:
        client = staff_client(self.director)
        response = client.get(reverse("tenders:project_create"))
        self.assertRedirects(response, reverse("staff:admin_dashboard"), fetch_redirect_response=False)
