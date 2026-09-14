"""django-allauth adapters for VMS auth redirects and vendor profiles."""

from __future__ import annotations

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.http import HttpRequest

from accounts.roles import is_staff_user
from audit.models import AuditLog
from audit.services import write_audit


class VMSAccountAdapter(DefaultAccountAdapter):
    """Vendor self-signup + role-aware redirects after login."""

    def get_login_redirect_url(self, request: HttpRequest) -> str:
        if is_staff_user(request.user):
            return "/admin-dashboard/"
        return "/"

    def get_signup_redirect_url(self, request: HttpRequest) -> str:
        # Email verification stage usually intercepts before this matters
        return self.get_login_redirect_url(request)

    def save_user(self, request, user, form, commit: bool = True):  # type: ignore[no-untyped-def]
        user = super().save_user(request, user, form, commit=commit)
        if commit:
            self._ensure_vendor_profile(user)
            write_audit(
                category=AuditLog.Category.AUTH,
                action="vendor_registered",
                actor=user,
                request=request,
                changes={"username": user.get_username(), "email": user.email},
                object_type="User",
                object_id=user.pk,
            )
        return user

    def _ensure_vendor_profile(self, user) -> None:  # type: ignore[no-untyped-def]
        from accounts.models import VendorProfile

        VendorProfile.objects.get_or_create(
            user=user,
            defaults={"display_name": user.get_username()},
        )


class VMSSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Google (and other social) sign-ups become vendor accounts."""

    def is_open_for_signup(self, request, sociallogin) -> bool:  # type: ignore[no-untyped-def]
        return True

    def save_user(self, request, sociallogin, form=None):  # type: ignore[no-untyped-def]
        user = super().save_user(request, sociallogin, form=form)
        from accounts.models import VendorProfile

        VendorProfile.objects.get_or_create(
            user=user,
            defaults={"display_name": user.get_username() or user.email},
        )
        write_audit(
            category=AuditLog.Category.AUTH,
            action="vendor_registered_social",
            actor=user,
            request=request,
            changes={
                "provider": sociallogin.account.provider,
                "email": user.email,
            },
            object_type="User",
            object_id=user.pk,
        )
        return user
