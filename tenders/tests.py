"""Permission tests: sealed bidding, vendor bid isolation, and tender eligibility."""

from __future__ import annotations

from datetime import timedelta

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Notification
from accounts.roles import PROCUREMENT
from core.testing import (
    make_company,
    make_open_project,
    make_quotation,
    make_submission,
    make_user,
    pdf,
    staff_client,
    vendor_client,
)
from envelope1.models import Envelope1Submission
from tenders.models import Project, Quotation, RFQ


class SealedBiddingTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.procurement = make_user("procurement", PROCUREMENT)
        cls.vendor = make_user("vendor")
        cls.company = make_company(cls.vendor)

    def setUp(self) -> None:
        self.project, self.rfq = make_open_project(self.procurement)
        self.quote = make_quotation(self.rfq, self.company, price="98765.43")
        self.staff = staff_client(self.procurement)

    def _close(self) -> None:
        self.project.closing_at = self.project.closing_at - timedelta(days=4)
        self.project.save(update_fields=["closing_at"])

    def test_staff_cannot_see_price_or_bidder_before_closing(self) -> None:
        page = self.staff.get(reverse("tenders:tender_detail", args=[self.project.pk]))
        self.assertEqual(page.status_code, 200)
        for secret in ("98,765.43", "98765.43", self.company.name):
            self.assertNotContains(page, secret)

    def test_staff_cannot_open_quotation_file_before_closing(self) -> None:
        url = reverse("tenders:quotation_document", args=[self.quote.pk])
        self.assertEqual(self.staff.get(url).status_code, 404)

    def test_prices_visible_after_closing(self) -> None:
        self._close()
        page = self.staff.get(reverse("tenders:tender_detail", args=[self.project.pk]))
        self.assertContains(page, "98,765.43")

    def test_award_cannot_be_recommended_while_sealed(self) -> None:
        self.staff.post(
            reverse("tenders:award_recommend", args=[self.rfq.pk]), {"quotation": self.quote.pk, "note": "x"}
        )
        self.assertFalse(self.rfq.awards.exists())


class VendorBidIsolationTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.procurement = make_user("procurement", PROCUREMENT)
        cls.alice = make_user("alice")
        cls.bob = make_user("bob")
        cls.alice_co = make_company(cls.alice)
        cls.bob_co = make_company(cls.bob)
        for company in (cls.alice_co, cls.bob_co):
            make_submission(company, Envelope1Submission.Status.APPROVED)

    def setUp(self) -> None:
        self.project, self.rfq = make_open_project(self.procurement)
        self.alice_quote = make_quotation(self.rfq, self.alice_co)
        self.bob_client = vendor_client(self.bob, self.bob_co)

    def test_vendor_cannot_withdraw_someone_elses_bid(self) -> None:
        response = self.bob_client.post(reverse("tenders:quotation_withdraw", args=[self.alice_quote.pk]))
        self.assertEqual(response.status_code, 404)
        self.alice_quote.refresh_from_db()
        self.assertEqual(self.alice_quote.status, Quotation.Status.SUBMITTED)

    def test_vendor_cannot_download_someone_elses_bid(self) -> None:
        url = reverse("tenders:vendor_quotation_document", args=[self.alice_quote.pk])
        self.assertEqual(self.bob_client.get(url).status_code, 404)

    def test_your_bids_lists_only_own(self) -> None:
        page = self.bob_client.get(reverse("tenders:your_bids"))
        self.assertNotContains(page, "98,765.43")

    def test_vendor_blocked_from_staff_tender_pages(self) -> None:
        for url in (
            reverse("tenders:tender_list"),
            reverse("tenders:tender_detail", args=[self.project.pk]),
            reverse("tenders:quotation_document", args=[self.alice_quote.pk]),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.bob_client.get(url).status_code, 403)

    def test_unqualified_vendor_cannot_quote(self) -> None:
        carol = make_user("carol")
        carol_co = make_company(carol)  # registration approved but no approved Envelope 1
        client = vendor_client(carol, carol_co)
        client.post(
            reverse("tenders:quotation_form", args=[self.project.pk, self.rfq.pk]),
            {"total_price": "1000", "handover_date": self.project.end_date.isoformat(),
             "declaration": "on", "quotation_pdf": pdf()},
        )
        self.assertFalse(Quotation.objects.filter(company=carol_co).exists())


class HandoverDateTests(TestCase):
    """Estimated Project Handover Date must fall between today and the project end date."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.procurement = make_user("procurement", PROCUREMENT)
        cls.vendor = make_user("vendor")
        cls.company = make_company(cls.vendor)
        make_submission(cls.company, Envelope1Submission.Status.APPROVED)

    def setUp(self) -> None:
        self.project, self.rfq = make_open_project(self.procurement)
        self.client = vendor_client(self.vendor, self.company)
        self.url = reverse("tenders:quotation_form", args=[self.project.pk, self.rfq.pk])

    def _post(self, handover: str):  # type: ignore[no-untyped-def]
        return self.client.post(
            self.url,
            {"total_price": "1000", "handover_date": handover, "declaration": "on", "quotation_pdf": pdf()},
        )

    def test_form_shows_new_field_only(self) -> None:
        page = self.client.get(self.url)
        self.assertContains(page, "Estimated Project Handover Date")
        self.assertContains(page, f'max="{self.project.end_date.isoformat()}"')
        self.assertNotContains(page, "Validity")
        self.assertNotContains(page, "lead time")

    def test_date_after_project_end_rejected(self) -> None:
        response = self._post((self.project.end_date + timedelta(days=1)).isoformat())
        self.assertContains(response, "on or before the project end date")
        self.assertFalse(Quotation.objects.exists())

    def test_past_date_rejected(self) -> None:
        from django.utils import timezone

        response = self._post((timezone.localdate() - timedelta(days=1)).isoformat())
        self.assertContains(response, "cannot be in the past")
        self.assertFalse(Quotation.objects.exists())

    def test_project_end_date_accepted_and_shown_to_staff_after_closing(self) -> None:
        self._post(self.project.end_date.isoformat())
        quote = Quotation.objects.get()
        self.assertEqual(quote.handover_date, self.project.end_date)
        self.project.closing_at = self.project.closing_at - timedelta(days=4)
        self.project.save(update_fields=["closing_at"])
        page = staff_client(self.procurement).get(reverse("tenders:tender_detail", args=[self.project.pk]))
        self.assertContains(page, self.project.end_date.strftime("%d %b %Y"))


class AwardStaysInternalTests(TestCase):
    """Staff inform winners themselves: vendors never see award outcomes in the system."""

    @classmethod
    def setUpTestData(cls) -> None:
        from accounts.roles import DIRECTOR

        cls.procurement = make_user("procurement", PROCUREMENT)
        cls.director = make_user("director", DIRECTOR)
        cls.winner = make_user("winner")
        cls.loser = make_user("loser")
        cls.winner_co = make_company(cls.winner)
        cls.loser_co = make_company(cls.loser)

    def setUp(self) -> None:
        from tenders.models import TenderAward

        self.project, self.rfq = make_open_project(self.procurement)
        self.win_quote = make_quotation(self.rfq, self.winner_co, "1000.00")
        make_quotation(self.rfq, self.loser_co, "2000.00")
        self.project.closing_at = self.project.closing_at - timedelta(days=4)
        self.project.save(update_fields=["closing_at"])
        staff_client(self.procurement).post(
            reverse("tenders:award_recommend", args=[self.rfq.pk]), {"quotation": self.win_quote.pk, "note": "Lowest"}
        )
        award = TenderAward.objects.get()
        mail.outbox = []
        with self.captureOnCommitCallbacks(execute=True):
            staff_client(self.director).post(reverse("tenders:award_decide", args=[award.pk]), {"decision": "approve"})
        award.refresh_from_db()
        self.assertEqual(award.status, TenderAward.Status.APPROVED)

    def test_vendors_get_no_award_message(self) -> None:
        for vendor in (self.winner, self.loser):
            self.assertFalse(Notification.objects.filter(user=vendor, dedupe_key__startswith="tender-award").exists())
            self.assertFalse([m for m in mail.outbox if vendor.email in m.to])

    def test_procurement_is_told_who_to_inform(self) -> None:
        note = Notification.objects.get(user=self.procurement, dedupe_key=f"staff-award-decision-{self.rfq.pk}")
        self.assertIn(self.winner_co.name, note.body)
        self.assertIn("inform the vendor", note.body)
        self.assertEqual(len([m for m in mail.outbox if self.procurement.email in m.to]), 1)

    def test_vendor_pages_show_closed_not_awarded(self) -> None:
        for user, company in ((self.winner, self.winner_co), (self.loser, self.loser_co)):
            client = vendor_client(user, company)
            for url in (reverse("tenders:your_bids"), reverse("tenders:project_detail", args=[self.project.pk])):
                with self.subTest(user=user.username, url=url):
                    page = client.get(url)
                    self.assertContains(page, "Closed")
                    self.assertNotContains(page, "Awarded")
                    self.assertNotContains(page, "Not awarded")

    def test_staff_still_see_award(self) -> None:
        page = staff_client(self.procurement).get(reverse("tenders:tender_detail", args=[self.project.pk]))
        self.assertContains(page, f"Awarded to {self.winner_co.name}")


class QuotationNotificationTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.procurement = make_user("procurement", PROCUREMENT)
        cls.vendor = make_user("vendor")
        cls.company = make_company(cls.vendor)
        make_submission(cls.company, Envelope1Submission.Status.APPROVED)

    def test_new_bid_alerts_procurement_without_sealed_details(self) -> None:
        project, rfq = make_open_project(self.procurement)
        client = vendor_client(self.vendor, self.company)
        with self.captureOnCommitCallbacks(execute=True):
            client.post(
                reverse("tenders:quotation_form", args=[project.pk, rfq.pk]),
                {"total_price": "54321.00", "handover_date": project.end_date.isoformat(),
                 "declaration": "on", "quotation_pdf": pdf()},
            )
        self.assertTrue(Quotation.objects.filter(company=self.company).exists())
        note = Notification.objects.get(user=self.procurement, dedupe_key=f"staff-quotes-{rfq.pk}")
        self.assertIn("1 vendor has quoted", note.body)
        sent = [m for m in mail.outbox if self.procurement.email in m.to]
        self.assertEqual(len(sent), 1)
        everything = note.title + note.body + sent[0].body + sent[0].alternatives[0][0]
        for secret in (self.company.name, "54321", "54,321"):
            self.assertNotIn(secret, everything)


class AddRfqAfterPublishTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.procurement = make_user("procurement", PROCUREMENT)
        cls.vendor = make_user("vendor")
        cls.company = make_company(cls.vendor)
        make_submission(cls.company, Envelope1Submission.Status.APPROVED)

    def test_open_project_accepts_another_rfq_and_emails_vendors(self) -> None:
        project, _rfq = make_open_project(self.procurement)
        client = staff_client(self.procurement)
        page = client.get(reverse("tenders:tender_detail", args=[project.pk]))
        self.assertContains(page, "Add RFQ")
        with self.captureOnCommitCallbacks(execute=True):
            response = client.post(
                reverse("tenders:rfq_add", args=[project.pk]),
                {"title": "Steel works"},
            )
        self.assertRedirects(response, reverse("tenders:tender_detail", args=[project.pk]))
        added = project.rfqs.get(title="Steel works")
        self.assertEqual(added.code, "RFQ-02")
        note = Notification.objects.get(
            user=self.vendor, dedupe_key=f"tender-rfq-{added.pk}-{self.company.pk}"
        )
        self.assertIn("New tender available", note.title)
        sent = [message for message in mail.outbox if self.vendor.email in message.to]
        self.assertEqual(len(sent), 1)
        self.assertIn("Steel works", sent[0].body)

    def test_published_rfq_cannot_be_edited(self) -> None:
        project, rfq = make_open_project(self.procurement)
        client = staff_client(self.procurement)
        response = client.post(
            reverse("tenders:rfq_edit", args=[project.pk, rfq.pk]),
            {"title": "Changed"},
        )
        self.assertRedirects(response, reverse("tenders:tender_detail", args=[project.pk]))
        rfq.refresh_from_db()
        self.assertEqual(rfq.title, "Earthworks")

    def test_publishing_emails_eligible_vendors(self) -> None:
        now = timezone.now()
        start = (now + timedelta(days=10)).date()
        project = Project.objects.create(
            title="Published tender",
            scope="Scope",
            start_date=start,
            end_date=start + timedelta(days=30),
            closing_at=now + timedelta(days=3),
            created_by=self.procurement,
        )
        RFQ.objects.create(project=project, code="RFQ-01", title="Piling")
        client = staff_client(self.procurement)
        with self.captureOnCommitCallbacks(execute=True):
            response = client.post(reverse("tenders:project_publish", args=[project.pk]))
        self.assertRedirects(response, reverse("tenders:tender_detail", args=[project.pk]))
        project.refresh_from_db()
        self.assertEqual(project.status, Project.Status.OPEN)
        sent = [message for message in mail.outbox if self.vendor.email in message.to]
        self.assertEqual(len(sent), 1)
        self.assertIn("New tender available", sent[0].subject)

    def test_closed_project_rejects_a_new_rfq(self) -> None:
        project, _rfq = make_open_project(self.procurement, closes_in=timedelta(days=-1))
        client = staff_client(self.procurement)
        response = client.post(
            reverse("tenders:rfq_add", args=[project.pk]),
            {"title": "Too late"},
        )
        self.assertRedirects(response, reverse("tenders:tender_detail", args=[project.pk]))
        self.assertFalse(project.rfqs.filter(title="Too late").exists())
