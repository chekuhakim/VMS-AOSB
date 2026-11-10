"""Move MSA party data out of Envelope 1 and renumber the remaining steps."""

from django.db import migrations


STEP_MAP = {1: 1, 2: 1, 3: 1, 4: 2, 5: 3, 6: 4}


def forwards(apps, schema_editor):
    Company = apps.get_model("vendors", "Company")
    CompanyDocument = apps.get_model("vendors", "CompanyDocument")
    Envelope1Submission = apps.get_model("envelope1", "Envelope1Submission")
    Envelope1Document = apps.get_model("envelope1", "Envelope1Document")
    Envelope1ItemEvaluation = apps.get_model("staff", "Envelope1ItemEvaluation")

    for submission in Envelope1Submission.objects.select_related("company").order_by("pk"):
        company = submission.company
        changed = []
        if not company.principal_address and submission.principal_address:
            company.principal_address = submission.principal_address
            changed.append("principal_address")
        if not company.msa_signatory_name and submission.msa_signatory_name:
            company.msa_signatory_name = submission.msa_signatory_name
            changed.append("msa_signatory_name")
        if not company.msa_signatory_designation and submission.msa_signatory_designation:
            company.msa_signatory_designation = submission.msa_signatory_designation
            changed.append("msa_signatory_designation")
        if changed:
            company.save(update_fields=changed)

        if Envelope1Document.objects.filter(
            submission=submission, doc_type="signed_msa"
        ).exists() and not CompanyDocument.objects.filter(
            company=company, doc_type="signed_msa"
        ).exists():
            source = (
                Envelope1Document.objects.filter(
                    submission=submission, doc_type="signed_msa"
                )
                .order_by("-version")
                .first()
            )
            CompanyDocument.objects.create(
                company=company,
                doc_type="signed_msa",
                storage_path=source.storage_path,
                storage_backend=source.storage_backend,
                original_filename=source.original_filename,
                version=source.version,
                uploaded_by=source.uploaded_by,
            )

        new_step = STEP_MAP.get(submission.wizard_step, 1)
        if submission.wizard_step != new_step:
            Envelope1Submission.objects.filter(pk=submission.pk).update(
                wizard_step=new_step
            )

    # The signed MSA is no longer an Envelope 1 checklist item.
    Envelope1ItemEvaluation.objects.filter(doc_type="signed_msa").delete()


def backwards(apps, schema_editor):
    # Recreating the old MSA steps is intentionally not supported.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("envelope1", "0006_envelope1submission_correction_round_and_more"),
        ("vendors", "0007_company_msa_signatory_designation_and_more"),
        ("staff", "0003_questionnaire_redesign"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
