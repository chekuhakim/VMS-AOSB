"""Public auth URLs with allauth's global URL names (no app namespace)."""

from allauth.account import views as allauth_views
from django.urls import include, path, re_path

from accounts import views as accounts_views

urlpatterns = [
    path("register/", allauth_views.signup, name="account_signup"),
    path(
        "register/confirm-email/",
        allauth_views.email_verification_sent,
        name="account_email_verification_sent",
    ),
    # Escape hatch: clear pending verification before leaving confirm-email
    path(
        "register/confirm-email/abort/",
        accounts_views.abort_email_verification,
        name="account_abort_email_verification",
    ),
    path("login/", allauth_views.login, name="account_login"),
    path("logout/", allauth_views.logout, name="account_logout"),
    path(
        "login/forgot-password/",
        allauth_views.password_reset,
        name="account_reset_password",
    ),
    path(
        "login/forgot-password/done/",
        allauth_views.password_reset_done,
        name="account_reset_password_done",
    ),
    re_path(
        r"^login/forgot-password/key/(?P<uidb36>[0-9A-Za-z]+)-(?P<key>.+)/$",
        allauth_views.password_reset_from_key,
        name="account_reset_password_from_key",
    ),
    path(
        "login/forgot-password/key/done/",
        allauth_views.password_reset_from_key_done,
        name="account_reset_password_from_key_done",
    ),
    path("accounts/", include("allauth.socialaccount.urls")),
]
