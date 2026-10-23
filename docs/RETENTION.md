# Record retention — AOSB VMS

Status: **draft for management / compliance approval.** The periods below are proposals; confirm them
against current Malaysian law and the AOSB ISO 9001 document-control procedure before go-live.

## What the system stores

| Record | Where | Contains personal data |
|---|---|---|
| User accounts (vendor + staff) | Postgres `auth_user`, allauth email tables | Yes — name, email |
| Company registration | `vendors.Company` | Yes — contact name, phone, email, bank account |
| Registration PDFs (SSM, CIDB, ST…) | `vendors.CompanyDocument` row + file in Supabase Storage | Possibly (signatories) |
| Envelope 1 pack, answers, evaluations | `envelope1.*`, `staff.Envelope1ItemEvaluation` | Yes — signatory, site supervisor |
| Envelope 1 PDFs | `envelope1.Envelope1Document` row + file in Supabase Storage | Possibly |
| Withdrawal requests | `envelope1.WithdrawalRequest` | Minimal |
| Tender projects, RFQs, quotations, awards | `tenders.*` + quotation PDFs in Supabase Storage | Minimal (commercial) |
| Audit log | `audit.AuditLog` | Yes — actor, IP address |
| In-app notifications | `accounts.Notification` | Minimal |

## Protections already built in

- **Audit log is append-only.** `AuditLog.save()` refuses updates and `delete()` always raises
  (`audit/models.py`). Rows can only be removed directly in the database.
- **PDFs are versioned, never overwritten.** Every upload gets a new path with version + date + random
  suffix (`documents/storage/__init__.py::build_versioned_path`); Supabase uploads use `upsert=false`.
- **Vendors can only delete draft companies.** Once a registration is submitted, the Delete button is
  hidden and the server refuses (`vendors/views.py::delete_company`), so registration, Envelope 1, and bid
  history are kept.
- **Sealed quotations keep their declaration snapshot** (wording version, time, IP) on the quotation row.

## Proposed retention periods

| Record | Keep for | Basis to confirm |
|---|---|---|
| Company registration + its PDFs | Life of the vendor relationship + 7 years | Companies Act 2016 s.245 / Income Tax Act 1967 s.82 (7-year record keeping); ISO 9001 cl. 7.5.3 |
| Envelope 1 packs, evaluations, PDFs | 7 years after the pack is decided | ISO 9001 cl. 8.4 (supplier evaluation evidence) |
| Tender projects, quotations, awards | 7 years after award or cancellation | Procurement audit trail; Income Tax Act 1967 s.82 |
| Audit log | 7 years | Supports all of the above |
| In-app notifications | 12 months | Operational only |
| Inactive vendor accounts (never registered a company) | 24 months of inactivity | PDPA 2010 retention principle (s.10) — don't keep personal data longer than needed |

## Rules for staff and administrators

1. **Deactivate, don't delete, user accounts.** Deleting a user cascades to their companies, Envelope 1
   packs, and quotations. In Django admin untick *Active* instead.
2. **Don't delete companies, projects, or quotations in Django admin.** Use statuses (rejected,
   cancelled) — the records are evidence.
3. **Never edit audit rows in the database.**

## Known gaps (not automated yet)

- **No automatic purge.** Nothing deletes records when a period ends; this is a manual, approved task for
  now. A purge command (with dry-run) can be added once the periods are approved.
- **Orphaned files.** Deleting a draft company removes its `CompanyDocument` rows but not the PDF files in
  Supabase Storage. Low volume (drafts only), but a periodic storage clean-up is needed.
- **Backups.** Supabase backup retention follows the Supabase plan settings; align it with this policy.
