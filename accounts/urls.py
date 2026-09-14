"""Namespaced account routes (company switcher, etc.)."""

from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("switch-company/", views.switch_company, name="switch_company"),
]
