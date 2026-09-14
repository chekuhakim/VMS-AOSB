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
documents/       # Storage helper + future vault
audit/           # Append-only AuditLog
templates/       # HTML + reusable components
static/          # CSS / JS assets
```

## Build phases

- **Phase 0 (done):** foundations — roles, audit model, company switcher, storage helper
- **Phase 1 (done):** vendor auth (`/register`, `/login`, confirm-email code, forgot-password)
- Phase 2: company registration wizard
- Phase 3: Envelope 1 + document vault
- Phase 4: admin evaluation / approval / audit UI
- Phase 5: tender / project / RFQ
- Phase 6: hardening
