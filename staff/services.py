"""Staff evaluation helpers — Procurement evaluates; Director approves."""

from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone

from audit.models import AuditLog
from audit.services import write_audit
from envelope1.checklist import STEP_DOC_TYPES
from envelope1.models import Envelope1Document, Envelope1Submission, WithdrawalRequest
from envelope1.services import latest_docs_map
from staff.models import Envelope1ItemEvaluation


def all_required_doc_types() -> list[str]:
    types: list[str] = []
    for step_types in STEP_DOC_TYPES.values():
        types.extend(step_types)
    return types


def ensure_evaluation_rows(submission: Envelope1Submission) -> list[Envelope1ItemEvaluation]:
    """Create pending evaluation rows for every required doc type."""
    rows: list[Envelope1ItemEvaluation] = []
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
    return withdrawal


def step_checklist(submission: Envelope1Submission, step: int) -> list[dict]:
    """Checklist items for one wizard step, in the vendor's upload order."""
    ensure_evaluation_rows(submission)
    doc_types = list(STEP_DOC_TYPES.get(step, []))
    if not doc_types:
        return []
    docs = latest_docs_map(submission)
    labels = dict(Envelope1Document.DocType.choices)
    by_type = {
        ev.doc_type: ev
        for ev in Envelope1ItemEvaluation.objects.filter(
            submission=submission, doc_type__in=doc_types
        )
    }
    return [
        {
            "evaluation": by_type[doc_type],
            "label": labels.get(doc_type, doc_type),
            "document": docs.get(doc_type),
        }
        for doc_type in doc_types
        if doc_type in by_type
    ]


def step_statuses(submission: Envelope1Submission) -> dict[int, str]:
    """Per-step stepper state: "fail" if any item failed, "pass" if all passed, else "pending"."""
    results: dict[str, str] = dict(
        Envelope1ItemEvaluation.objects.filter(submission=submission).values_list(
            "doc_type", "result"
        )
    )
    statuses: dict[int, str] = {}
    for step, doc_types in STEP_DOC_TYPES.items():
        step_results = [results.get(t, Envelope1ItemEvaluation.Result.PENDING) for t in doc_types]
        if Envelope1ItemEvaluation.Result.FAIL in step_results:
            statuses[step] = "fail"
        elif step_results and all(r == Envelope1ItemEvaluation.Result.PASS for r in step_results):
            statuses[step] = "pass"
        else:
            statuses[step] = "pending"
    return statuses


def checklist_rows(submission: Envelope1Submission) -> list[dict]:
    """Pack evaluation rows with latest uploaded document (if any)."""
    ensure_evaluation_rows(submission)
    docs = latest_docs_map(submission)
    labels = dict(Envelope1Document.DocType.choices)
    rows = []
    for evaluation in Envelope1ItemEvaluation.objects.filter(
        submission=submission
    ).order_by("doc_type"):
        rows.append(
            {
                "evaluation": evaluation,
                "label": labels.get(evaluation.doc_type, evaluation.doc_type),
                "document": docs.get(evaluation.doc_type),
            }
        )
    return rows
