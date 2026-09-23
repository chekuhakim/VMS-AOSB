"""Namespaced account routes (company switcher, etc.)."""

from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("switch-company/", views.switch_company, name="switch_company"),
    path(
        "notifications/<int:pk>/dismiss/",
        views.notification_dismiss,
        name="notification_dismiss",
    ),
    path(
        "notifications/<int:pk>/read/",
        views.notification_read,
        name="notification_read",
    ),
    path(
        "notifications/<int:pk>/delete/",
        views.notification_delete,
        name="notification_delete",
    ),
    path(
        "notifications/mark-all-read/",
        views.notifications_mark_all_read,
        name="notifications_mark_all_read",
    ),
]
