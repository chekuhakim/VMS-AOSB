"""Shared builders for the Django test suite (users per role, companies, Envelope 1, tenders)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser, Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from accounts.company_context import SESSION_KEY
from accounts.roles import ensure_role_groups
from envelope1.models import Envelope1Submission
from envelope1.services import get_or_create_draft
from tenders.models import RFQ, Project, Quotation
from vendors.models import Company
from vendors.sample_data import create_sample_company

PDF_BYTES = b"%PDF-1.4 test"


def pdf(name: str = "file.pdf") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, PDF_BYTES, content_type="application/pdf")


def make_user(username: str, *groups: str) -> AbstractBaseUser:
    """Active user with an email; staff roles given as group names (none = vendor)."""
    ensure_role_groups()
    user = get_user_model().objects.create_user(username, f"{username}@example.com", "x")
    for name in groups:
        user.groups.add(Group.objects.get(name=name))
    return user


def make_company(
    owner: AbstractBaseUser, status: str = Company.RegistrationStatus.APPROVED
) -> Company:
    company = create_sample_company(owner=owner)
    company.registration_status = status
    company.save(update_fields=["registration_status"])
    return company


def make_submission(
    company: Company,
    status: str = Envelope1Submission.Status.DRAFT,
    locked: bool = False,
) -> Envelope1Submission:
    submission, _ = get_or_create_draft(company)
    submission.status = status
    submission.locked_at = timezone.now() if locked else None
    submission.msa_party_saved_at = timezone.now()
    submission.save()
    return submission


def vendor_client(user: AbstractBaseUser, company: Company | None = None) -> Client:
    """Logged-in client; pins the active company like the header company switcher does."""
    client = Client()
    client.force_login(user)
    if company is not None:
        session = client.session
        session[SESSION_KEY] = company.pk
        session.save()
    return client


def staff_client(user: AbstractBaseUser) -> Client:
    client = Client()
    client.force_login(user)
    return client


def make_open_project(
    created_by: AbstractBaseUser, closes_in: timedelta = timedelta(days=3)
) -> tuple[Project, RFQ]:
    now = timezone.now()
    start = (now + timedelta(days=10)).date()
    project = Project.objects.create(
        title="Test Warehouse",
        scope="Build a warehouse",
        start_date=start,
        end_date=start + timedelta(days=90),
        closing_at=now + closes_in,
        status=Project.Status.OPEN,
        published_at=now,
        published_by=created_by,
        created_by=created_by,
        reference=f"PRJ-TEST-{Project.objects.count() + 1:04d}",
    )
    rfq = RFQ.objects.create(project=project, code="RFQ-01", title="Earthworks")
    return project, rfq


def make_quotation(rfq: RFQ, company: Company, price: str = "98765.43") -> Quotation:
    now = timezone.now()
    return Quotation.objects.create(
        rfq=rfq,
        company=company,
        total_price=Decimal(price),
        handover_date=rfq.project.end_date,
        document_path="test/quote.pdf",
        document_backend="local",
        document_filename="quote.pdf",
        declaration_version="test",
        declaration_text="test",
        declaration_accepted_at=now,
        submitted_at=now,
        submitted_by=company.owner,
    )
