"""Staff Phase 4 routes (admin evaluation / approval / audit)."""

from django.urls import path

from . import views

app_name = "staff"

urlpatterns = [
    path("admin-dashboard/", views.admin_dashboard, name="admin_dashboard"),
    path("admin-dashboard/audit-feed/", views.audit_feed, name="audit_feed"),
    path("registered-company/", views.company_list, name="company_list"),
    path(
        "registered-company/<int:pk>/",
        views.company_detail,
        name="company_detail",
    ),
    path(
        "registered-company/documents/<int:pk>/",
        views.view_company_document,
        name="view_company_document",
    ),
    path("submitted-envelope-1/", views.envelope1_list, name="envelope1_list"),
    path(
        "submitted-envelope-1/<int:pk>/",
        views.envelope1_detail,
        name="envelope1_detail",
    ),
    path(
        "submitted-envelope-1/<int:pk>/lock/",
        views.envelope1_lock,
        name="envelope1_lock",
    ),
    path(
        "submitted-envelope-1/<int:pk>/step/<int:step>/",
        views.envelope1_evaluate,
        name="envelope1_evaluate",
    ),
    path(
        "submitted-envelope-1/<int:pk>/send-director/",
        views.envelope1_send_director,
        name="envelope1_send_director",
    ),
    path(
        "submitted-envelope-1/<int:pk>/reject/",
        views.envelope1_reject_eval,
        name="envelope1_reject_eval",
    ),
    path(
        "submitted-envelope-1/documents/<int:pk>/",
        views.view_envelope1_document,
        name="view_envelope1_document",
    ),
    path(
        "qualification-checklist/",
        views.qualification_checklist_redirect,
        name="qualification_checklist",
    ),
    path("approval/", views.approval_queue, name="approval_queue"),
    path("approval/<int:pk>/", views.approval_decide, name="approval_decide"),
    path("withdrawals/", views.withdrawal_list, name="withdrawal_list"),
    path(
        "withdrawals/<int:pk>/",
        views.withdrawal_decide,
        name="withdrawal_decide",
    ),
    path("audit-log/", views.audit_log, name="audit_log"),
]
