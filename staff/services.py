"""Staff evaluation helpers — Procurement evaluates; Director approves."""

from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone

from accounts.models import Notification
from accounts.notifications import notify_event, staff_recipients
from accounts.roles import DIRECTOR
from audit.models import AuditLog
from audit.services import write_audit
from envelope1.checklist import (
    ALL_ITEMS,
    DECLARATIONS,
    LEAD_TIME_SEA_LABEL,
    LEAD_TIME_SEMENANJUNG_LABEL,
    MIN_FINANCIAL_STATEMENTS,
    REQUIRED_UPLOADS,
    STEP_ITEMS,
    YES_NO_UPLOADS,
)
from envelope1.models import (
    Envelope1Document,
    Envelope1Item,
    Envelope1Submission,
    WithdrawalRequest,
)
from envelope1.services import latest_docs_map
from staff.models import Envelope1ItemEvaluation

_FINAL_STATUSES = {
    Envelope1Submission.Status.APPROVED,
    Envelope1Submission.Status.REJECTED,
}


def _notify_vendor(
    submission: Envelope1Submission,
    *,
    topic: str,
    title: str,
    body: str,
    level: str = Notification.Level.INFO,
) -> None:
    """Tell the company owner about an Envelope 1 outcome (one inbox row per topic)."""
    company = submission.company
    notify_event(
        users=[company.owner],
        dedupe_key=f"e1-{submission.pk}-{topic}",
        title=f"{title} — {company.name}",
        body=body,
        level=level,
        link_url=reverse("envelope1:home"),
        link_label="Open Envelope 1",
    )


def _with_note(text: str, note: str) -> str:
    note = (note or "").strip()
    return f"{text}\n\nNote: {note}" if note else text


def all_required_doc_types() -> list[str]:
    """Checklist item keys Procurement must evaluate (name kept for existing callers)."""
    return list(ALL_ITEMS)


def ensure_evaluation_rows(submission: Envelope1Submission) -> list[Envelope1ItemEvaluation]:
    """Create pending evaluation rows for every checklist item."""
    rows: list[Envelope1ItemEvaluation] = []
    # Decided packs keep the checklist they were judged on — never add new pending items
    if submission.status in _FINAL_STATUSES:
        return list(Envelope1ItemEvaluation.objects.filter(submission=submission))
    for doc_type in all_required_doc_types():
        row, _ = Envelope1ItemEvaluation.objects.get_or_create(
            submission=submission,
            doc_type=doc_type,
            defaults={"result": Envelope1ItemEvaluation.Result.PENDING},
        )
        rows.append(row)
    return rows


def evaluation_progress(submission: Envelope1Submission) -> dict[str, int]:
    qs = Envelope1ItemEvaluation.objects.filter(submission=submission)
    total = qs.count() or len(all_required_doc_types())
    passed = qs.filter(result=Envelope1ItemEvaluation.Result.PASS).count()
    failed = qs.filter(result=Envelope1ItemEvaluation.Result.FAIL).count()
    pending = total - passed - failed
    return {"total": total, "passed": passed, "failed": failed, "pending": pending}


@transaction.atomic
def lock_for_evaluation(
    *,
    submission: Envelope1Submission,
    actor: AbstractBaseUser,
    request: HttpRequest | None = None,
) -> Envelope1Submission:
    """Procurement starts review — lock vendor edits and open checklist."""
    if submission.status not in {
        Envelope1Submission.Status.PENDING_EVALUATION,
        Envelope1Submission.Status.SUBMITTED,
        Envelope1Submission.Status.IN_PROGRESS,
    }:
        raise ValueError("This Envelope 1 is not awaiting procurement evaluation.")

    submission.locked_at = timezone.now()
    submission.locked_by = actor  # type: ignore[assignment]
    submission.status = Envelope1Submission.Status.IN_PROGRESS
    submission.save(update_fields=["locked_at", "locked_by", "status", "updated_at"])
    ensure_evaluation_rows(submission)
    write_audit(
        category=AuditLog.Category.EVALUATION,
        action="envelope1_locked_for_evaluation",
        actor=actor,
        request=request,
        changes={"status": submission.status},
        object_type="Envelope1Submission",
        object_id=submission.pk,
    )
    _notify_vendor(
        submission,
        topic="status",
        title="Envelope 1 under procurement check",
        body="Procurement has started checking your Envelope 1, so it is now locked. "
        "Need to make changes? Request a withdrawal from the Envelope 1 page.",
    )
    return submission


@transaction.atomic
def set_item_result(
    *,
    evaluation: Envelope1ItemEvaluation,
    result: str,
    note: str,
    actor: AbstractBaseUser,
    request: HttpRequest | None = None,
) -> Envelope1ItemEvaluation:
    if result not in {
        Envelope1ItemEvaluation.Result.PASS,
        Envelope1ItemEvaluation.Result.FAIL,
        Envelope1ItemEvaluation.Result.PENDING,
    }:
        raise ValueError("Invalid evaluation result.")
    evaluation.result = result
    evaluation.note = (note or "").strip()
    evaluation.evaluated_by = actor  # type: ignore[assignment]
    evaluation.evaluated_at = timezone.now()
    evaluation.save(
        update_fields=["result", "note", "evaluated_by", "evaluated_at", "updated_at"]
    )
    write_audit(
        category=AuditLog.Category.EVALUATION,
        action="envelope1_item_evaluated",
        actor=actor,
        request=request,
        changes={
            "doc_type": evaluation.doc_type,
            "result": result,
            "note": evaluation.note[:200],
        },
        object_type="Envelope1ItemEvaluation",
        object_id=evaluation.pk,
    )
    return evaluation


@transaction.atomic
def send_to_director(
    *,
    submission: Envelope1Submission,
    actor: AbstractBaseUser,
    request: HttpRequest | None = None,
) -> Envelope1Submission:
    """Procurement recommends approval — all items must be PASS."""
    ensure_evaluation_rows(submission)
    progress = evaluation_progress(submission)
    if progress["pending"] > 0:
        raise ValueError("Evaluate every checklist item before sending to the Director.")
    if progress["failed"] > 0:
        raise ValueError("Failed items remain — reject at evaluation or re-check them.")
    submission.status = Envelope1Submission.Status.PENDING_DIRECTOR
    submission.save(update_fields=["status", "updated_at"])
    write_audit(
        category=AuditLog.Category.EVALUATION,
        action="envelope1_sent_to_director",
        actor=actor,
        request=request,
        changes={"status": submission.status, **progress},
        object_type="Envelope1Submission",
        object_id=submission.pk,
    )
    notify_event(
        users=staff_recipients(DIRECTOR, exclude=actor),
        dedupe_key=f"staff-e1-{submission.pk}-director",
        title=f"Envelope 1 awaiting your approval — {submission.company.name}",
        body="Procurement has passed every checklist item and recommends approval.",
        link_url=reverse("staff:approval_queue"),
        link_label="Open approval queue",
    )
    return submission


@transaction.atomic
def reject_at_evaluation(
    *,
    submission: Envelope1Submission,
    actor: AbstractBaseUser,
    note: str = "",
    request: HttpRequest | None = None,
) -> Envelope1Submission:
    submission.status = Envelope1Submission.Status.REJECTED
    submission.save(update_fields=["status", "updated_at"])
    write_audit(
        category=AuditLog.Category.EVALUATION,
        action="envelope1_rejected_by_procurement",
        actor=actor,
        request=request,
        changes={"status": submission.status, "note": (note or "")[:300]},
        object_type="Envelope1Submission",
        object_id=submission.pk,
    )
    _notify_vendor(
        submission,
        topic="status",
        title="Envelope 1 not approved",
        body=_with_note("Procurement did not approve your Envelope 1.", note),
        level=Notification.Level.DANGER,
    )
    return submission


@transaction.atomic
def director_decide(
    *,
    submission: Envelope1Submission,
    actor: AbstractBaseUser,
    approve: bool,
    note: str = "",
    request: HttpRequest | None = None,
) -> Envelope1Submission:
    if submission.status != Envelope1Submission.Status.PENDING_DIRECTOR:
        raise ValueError("This Envelope 1 is not in the director approval queue.")
    submission.status = (
        Envelope1Submission.Status.APPROVED
        if approve
        else Envelope1Submission.Status.REJECTED
    )
    submission.save(update_fields=["status", "updated_at"])
    write_audit(
        category=AuditLog.Category.APPROVAL,
        action="envelope1_director_approved" if approve else "envelope1_director_rejected",
        actor=actor,
        request=request,
        changes={"status": submission.status, "note": (note or "")[:300]},
        object_type="Envelope1Submission",
        object_id=submission.pk,
    )
    if approve:
        _notify_vendor(
            submission,
            topic="status",
            title="Envelope 1 approved",
            body=_with_note(
                "Congratulations — your company is pre-qualified and can now quote on open projects.",
                note,
            ),
            level=Notification.Level.SUCCESS,
        )
    else:
        _notify_vendor(
            submission,
            topic="status",
            title="Envelope 1 not approved",
            body=_with_note("The Director did not approve your Envelope 1.", note),
            level=Notification.Level.DANGER,
        )
    return submission


@transaction.atomic
def review_withdrawal(
    *,
    withdrawal: WithdrawalRequest,
    actor: AbstractBaseUser,
    approve: bool,
    review_note: str = "",
    request: HttpRequest | None = None,
) -> WithdrawalRequest:
    if withdrawal.status != WithdrawalRequest.Status.PENDING:
        raise ValueError("This withdrawal request was already reviewed.")
    withdrawal.status = (
        WithdrawalRequest.Status.APPROVED
        if approve
        else WithdrawalRequest.Status.REJECTED
    )
    withdrawal.reviewed_by = actor  # type: ignore[assignment]
    withdrawal.review_note = (review_note or "").strip()
    withdrawal.reviewed_at = timezone.now()
    withdrawal.save(
        update_fields=["status", "reviewed_by", "review_note", "reviewed_at"]
    )
    if approve:
        submission = withdrawal.submission
        submission.locked_at = None
        submission.locked_by = None
        if submission.status not in {
            Envelope1Submission.Status.APPROVED,
            Envelope1Submission.Status.REJECTED,
        }:
            submission.status = Envelope1Submission.Status.PENDING_EVALUATION
        submission.save(
            update_fields=["locked_at", "locked_by", "status", "updated_at"]
        )
    write_audit(
        category=AuditLog.Category.EVALUATION,
        action="envelope1_withdrawal_approved"
        if approve
        else "envelope1_withdrawal_rejected",
        actor=actor,
        request=request,
        changes={"note": withdrawal.review_note[:300]},
        object_type="WithdrawalRequest",
        object_id=withdrawal.pk,
    )
    if approve:
        _notify_vendor(
            withdrawal.submission,
            topic="withdrawal",
            title="Withdrawal approved",
            body=_with_note(
                "Your Envelope 1 is unlocked. Click Edit on the Envelope 1 page, make your changes, then submit again."
                if withdrawal.submission.can_reopen
                else "Your Envelope 1 is unlocked.",
                withdrawal.review_note,
            ),
            level=Notification.Level.SUCCESS,
        )
    else:
        _notify_vendor(
            withdrawal.submission,
            topic="withdrawal",
            title="Withdrawal rejected",
            body=_with_note(
                "Your Envelope 1 stays locked while Procurement continues checking it.",
                withdrawal.review_note,
            ),
            level=Notification.Level.WARNING,
        )
    return withdrawal


def _yes_no(value: bool | None) -> str:
    if value is None:
        return ""
    return "Yes" if value else "No"


def item_detail(
    submission: Envelope1Submission,
    item: str,
    docs: dict[str, Envelope1Document],
) -> dict:
    """What the vendor answered for one checklist item, shaped for the staff card.

    Keys: answer (Yes/No/Accepted…), lines (text), files (documents), headers + rows
    (tables; each row has `cells` and optional `document`), missing (incomplete).
    """
    detail: dict = {
        "answer": "",
        "lines": [],
        "files": [],
        "headers": [],
        "rows": [],
        "missing": False,
    }
    if item in REQUIRED_UPLOADS:
        doc = docs.get(REQUIRED_UPLOADS[item])
        detail["files"] = [doc] if doc else []
        detail["missing"] = doc is None
    elif item in YES_NO_UPLOADS:
        answer_field, doc_type = YES_NO_UPLOADS[item]
        answer = getattr(submission, answer_field)
        doc = docs.get(doc_type)
        detail["answer"] = _yes_no(answer)
        if answer and doc:
            detail["files"] = [doc]
        detail["missing"] = answer is None or (answer is True and doc is None)
    elif item == Envelope1Item.FINANCIAL_STATEMENTS:
        rows = list(submission.financial_statements.select_related("document"))
        detail["headers"] = ["Year", "Financial statement"]
        detail["rows"] = [
            {"cells": [str(r.year)], "document": r.document} for r in rows
        ]
        detail["missing"] = len(rows) < MIN_FINANCIAL_STATEMENTS
    elif item == Envelope1Item.SABAH_INTEREST:
        detail["answer"] = _yes_no(submission.sabah_interest)
        detail["missing"] = submission.sabah_interest is None
    elif item == Envelope1Item.PRIMARY_SUPPLIERS:
        rows = list(submission.primary_suppliers.all())
        detail["headers"] = ["Structure", "Name of supplier"]
        detail["rows"] = [{"cells": [r.structure, r.supplier_name]} for r in rows]
        detail["missing"] = not rows
    elif item == Envelope1Item.LEAD_TIME:
        sea = submission.lead_time_sea_freight_days
        semenanjung = submission.lead_time_semenanjung_days
        if sea:
            detail["lines"].append(f"{LEAD_TIME_SEA_LABEL} = {sea} days")
        if semenanjung:
            detail["lines"].append(f"{LEAD_TIME_SEMENANJUNG_LABEL} = {semenanjung} days")
        detail["missing"] = not (sea or semenanjung)
    elif item == Envelope1Item.SITE_SUPERVISOR:
        name = submission.site_supervisor_name.strip()
        detail["lines"] = [name] if name else []
        detail["missing"] = not name
    elif item in DECLARATIONS:
        accepted = (
            submission.accepts_timestamped_reporting
            if item == Envelope1Item.TIMESTAMPED_REPORTING
            else submission.accepts_metmalaysia_eot
        )
        detail["answer"] = "Accepted" if accepted else "Not accepted"
        detail["lines"] = [DECLARATIONS[item]]
        detail["missing"] = not accepted
    elif item == Envelope1Item.PAST_PROJECTS:
        detail["answer"] = _yes_no(submission.has_past_projects)
        rows = (
            list(submission.past_projects.select_related("document"))
            if submission.has_past_projects
            else []
        )
        detail["headers"] = ["Project name", "Supporting document"] if rows else []
        detail["rows"] = [{"cells": [r.project_name], "document": r.document} for r in rows]
        detail["missing"] = submission.has_past_projects is None or (
            submission.has_past_projects is True and not rows
        )
    return detail


def step_checklist(submission: Envelope1Submission, step: int) -> list[dict]:
    """Checklist items for one wizard step, in the vendor's wizard order."""
    ensure_evaluation_rows(submission)
    items = list(STEP_ITEMS.get(step, []))
    if not items:
        return []
    docs = latest_docs_map(submission)
    labels = dict(Envelope1Item.choices)
    by_item = {
        ev.doc_type: ev
        for ev in Envelope1ItemEvaluation.objects.filter(
            submission=submission, doc_type__in=items
        )
    }
    return [
        {
            "evaluation": by_item[item],
            "label": labels.get(item, item),
            **item_detail(submission, item, docs),
        }
        for item in items
        if item in by_item
    ]


def step_statuses(submission: Envelope1Submission) -> dict[int, str]:
    """Per-step stepper state: "fail" if any item failed, "pass" if all passed, else "pending"."""
    results: dict[str, str] = dict(
        Envelope1ItemEvaluation.objects.filter(submission=submission).values_list(
            "doc_type", "result"
        )
    )
    statuses: dict[int, str] = {}
    for step, doc_types in STEP_ITEMS.items():
        step_results = [results.get(t, Envelope1ItemEvaluation.Result.PENDING) for t in doc_types]
        if Envelope1ItemEvaluation.Result.FAIL in step_results:
            statuses[step] = "fail"
        elif step_results and all(r == Envelope1ItemEvaluation.Result.PASS for r in step_results):
            statuses[step] = "pass"
        else:
            statuses[step] = "pending"
    return statuses


def checklist_rows(submission: Envelope1Submission) -> list[dict]:
    """All evaluation rows with the vendor's answers (checklist order)."""
    ensure_evaluation_rows(submission)
    docs = latest_docs_map(submission)
    labels = dict(Envelope1Item.choices)
    order = {item: i for i, item in enumerate(ALL_ITEMS)}
    evaluations = sorted(
        Envelope1ItemEvaluation.objects.filter(submission=submission),
        key=lambda ev: order.get(ev.doc_type, len(order)),
    )
    return [
        {
            "evaluation": ev,
            "label": labels.get(ev.doc_type, ev.doc_type),
            **item_detail(submission, ev.doc_type, docs),
        }
        for ev in evaluations
    ]
