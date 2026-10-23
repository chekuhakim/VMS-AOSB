# AOSB Vendor Management System (VMS)

ISO 9001-aligned vendor management for a Malaysian Towerco.

## Stack

- Django 5 + Python 3.11+
- Django HTML templates + Tailwind CSS
- PostgreSQL on Supabase (SQLite for local bootstrap)
- Supabase Storage for PDF documents

## Design system

- Brand orange `#FF6F00` (Alpha Orange)
- Cream `#FAF7F2` / peach `#FFE8D6` surfaces
- Borders `border-slate-200`, cards `shadow-sm`, Inter typography

## Quick start

```bash
# 1. Create / activate virtualenv
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # Windows PowerShell

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy env template
copy .env.example .env

# 4. Migrate + seed staff role groups + run
python manage.py migrate
python manage.py seed_roles
python manage.py runserver
```

Open http://127.0.0.1:8000/

## Project layout

```
config/          # Django project settings & root URLs
core/            # Shell routes + shared context
accounts/        # Roles, vendor profile, company switcher
vendors/         # Company registry
envelope1/       # Envelope 1 wizard, vault listings, withdrawal
staff/           # Phase 4 admin evaluation / approval / audit UI
tenders/         # Phase 5 projects, RFQs, sealed quotations, awards
documents/       # Storage helper + future vault
audit/           # Append-only AuditLog
templates/       # HTML + reusable components
static/          # CSS / JS assets
```

## Build phases

- **Phase 0 (done):** foundations — roles, audit model, company switcher, storage helper
- **Phase 1 (done):** vendor auth (`/register`, `/login`, confirm-email code, forgot-password, Google)
- **Phase 2 (done):** company registration wizard (6 steps, PDFs, rules auto approve/reject)
- **Phase 3 (done):** Envelope 1 vendor wizard + document vault + withdrawal request
- **Phase 4 (done):** admin evaluation / approval / audit UI
- **Phase 5 (done):** tender projects + RFQs (`/tender`), sealed vendor quotations (`/project`, `/your-bid`), Procurement → Director award approval. Declaration wording lives in `tenders/declaration.py`
- **Phase 6 (done):** hardening — permission test suite, daily expiry reminders, notification emails, open-redirect guard, draft-only company deletion, retention notes (`docs/RETENTION.md`)

## Tests

```bash
python manage.py test
```

Tests always run on a throwaway in-memory SQLite database with local file storage — they never touch
the Supabase database or bucket, whatever `.env` says (see the `TESTING` block in `config/settings.py`).
They cover role permissions and segregation of duties, vendor data isolation, sealed bidding,
notifications, expiry reminders, and audit-log immutability.

## Notification emails

Every workflow notification (bell icon) is also emailed once. With `DEBUG=True` and no mail settings,
emails are only printed in the `runserver` terminal. To deliver them, set in `.env`:

```
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.your-provider.com
EMAIL_PORT=587
EMAIL_HOST_USER=...
EMAIL_HOST_PASSWORD=...
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=noreply@your-domain.com
SITE_URL=https://your-public-domain   # used for links inside emails
```

Then check delivery with `python manage.py send_test_email you@example.com`.

## Daily expiry reminders

`python manage.py send_expiry_reminders` checks every submitted company's dated documents (SSM, CIDB,
ST, Envelope 1 CAR insurance) and reminds the vendor at 30 days, 7 days, and on expiry — each stage is
emailed once, so it is safe to run repeatedly. Add `--dry-run` to preview who would be reminded without
saving or emailing anything. Run it once a day:

- **Windows (Task Scheduler):** action `C:\path\to\VMS\.venv\Scripts\python.exe`, arguments
  `manage.py send_expiry_reminders`, start in `C:\path\to\VMS`, trigger daily at 08:00.
- **Linux (cron):** `0 8 * * * cd /srv/vms && .venv/bin/python manage.py send_expiry_reminders`

Reminder thresholds: `SOON_DAYS` / `FINAL_REMINDER_DAYS` in `accounts/notifications.py`.

## Record retention

See `docs/RETENTION.md` (draft for management approval). Vendors can only delete draft companies;
deactivate users in Django admin instead of deleting them.
