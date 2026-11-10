"""Vendor company registration routes."""

from django.urls import path

from . import views

app_name = "vendors"

urlpatterns = [
    path("your-company/", views.your_company, name="your_company"),
    path("your-company/<int:pk>/", views.company_detail, name="company_detail"),
    path(
        "your-company/<int:pk>/delete/",
        views.delete_company,
        name="delete_company",
    ),
    path(
        "your-company/<int:pk>/draft-msa/",
        views.download_company_msa,
        name="draft_msa",
    ),
    path("register-company/", views.register_company, name="register_company"),
    path(
        "register-company/<int:pk>/step/<int:step>/",
        views.wizard_step,
        name="wizard_step",
    ),
]
