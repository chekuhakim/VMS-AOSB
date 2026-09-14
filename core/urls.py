"""URL routes for the shell — remaining placeholders (company routes live in vendors)."""

from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("envelope-1/", views.envelope1, name="envelope1"),
    path("document-vault/", views.document_vault, name="document_vault"),
    path("project/", views.project, name="project"),
    path("your-bid/", views.your_bid, name="your_bid"),
    path("admin-dashboard/", views.admin_dashboard, name="admin_dashboard"),
    path("registered-company/", views.registered_company, name="registered_company"),
    path("submitted-envelope-1/", views.submitted_envelope1, name="submitted_envelope1"),
    path(
        "qualification-checklist/",
        views.qualification_checklist,
        name="qualification_checklist",
    ),
    path("approval/", views.approval, name="approval"),
    path("audit-log/", views.audit_log, name="audit_log"),
    path("tender/", views.tender, name="tender"),
]
