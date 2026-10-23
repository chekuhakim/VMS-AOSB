"""Send undecided Envelope 1 packs back to Draft so vendors answer the new questionnaire.

Old per-document Pass/Fail rows no longer match the checklist items, so they are removed.
Uploaded files are kept. Approved / rejected packs are left untouched.
Reverse is a no-op: restore from the JSON backup taken before migrating.
"""

from django.db import migrations

UNDECIDED = (
    "draft",
    "submitted",
    "pending_evaluation",
    "in_progress",
    "pending_director_approval",
)


def reset_packs(apps, schema_editor) -> None:
    Submission = apps.get_model("envelope1", "Envelope1Submission")
    Evaluation = apps.get_model("staff", "Envelope1ItemEvaluation")
    for sub in Submission.objects.filter(status__in=UNDECIDED):
        Evaluation.objects.filter(submission=sub).delete()
        sub.status = "draft"
        sub.wizard_step = min(sub.wizard_step, 3)
        sub.locked_at = None
        sub.locked_by = None
        sub.submitted_at = None
        sub.save(
            update_fields=["status", "wizard_step", "locked_at", "locked_by", "submitted_at"]
        )


class Migration(migrations.Migration):
    dependencies = [
        ("envelope1", "0003_questionnaire_redesign"),
        ("staff", "0003_questionnaire_redesign"),
    ]

    operations = [
        migrations.RunPython(reset_packs, migrations.RunPython.noop),
    ]
