"""Envelope 1 vendor routes."""

from django.urls import path

from . import views

app_name = "envelope1"

urlpatterns = [
    path("envelope-1/", views.envelope1_home, name="home"),
    path("envelope-1/start/", views.envelope1_start, name="start"),
    path(
        "envelope-1/<int:pk>/step/<int:step>/",
        views.envelope1_wizard,
        name="wizard",
    ),
    path(
        "envelope-1/<int:pk>/corrections/",
        views.envelope1_corrections,
        name="corrections",
    ),
    path(
        "envelope-1/<int:pk>/corrections/resubmit/",
        views.envelope1_resubmit_correction,
        name="resubmit_correction",
    ),
    path(
        "envelope-1/<int:pk>/no-advance-declaration/",
        views.download_no_advance_declaration,
        name="no_advance_template",
    ),
    path(
        "envelope-1/<int:pk>/reopen/",
        views.reopen_submission,
        name="reopen",
    ),
    path(
        "envelope-1/<int:pk>/withdrawal/",
        views.withdrawal_request,
        name="withdrawal",
    ),
    path("document-vault/", views.document_vault, name="vault"),
    path(
        "document-vault/registration/<int:pk>/",
        views.view_registration_document,
        name="view_registration_document",
    ),
    path(
        "document-vault/envelope-1/<int:pk>/",
        views.view_envelope1_document,
        name="view_envelope1_document",
    ),
]
