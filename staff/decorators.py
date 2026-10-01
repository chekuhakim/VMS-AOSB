"""Access helpers for staff Phase 4 views."""

from __future__ import annotations

from functools import wraps
from typing import Callable

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect

from accounts.roles import (
    DIRECTOR,
    PROCUREMENT,
    SYSTEM_ADMIN,
    VIEWER,
    is_staff_user,
    user_in_group,
)


def staff_required(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    @wraps(view)
    def _wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:  # type: ignore[no-untyped-def]
        if not request.user.is_authenticated:
            return redirect("account_login")
        if not is_staff_user(request.user):
            return HttpResponseForbidden("Staff only.")
        return view(request, *args, **kwargs)

    return _wrapped


def can_evaluate(user) -> bool:  # type: ignore[no-untyped-def]
    return user.is_superuser or user_in_group(user, SYSTEM_ADMIN) or user_in_group(
        user, PROCUREMENT
    )


def can_approve(user) -> bool:  # type: ignore[no-untyped-def]
    return user.is_superuser or user_in_group(user, SYSTEM_ADMIN) or user_in_group(
        user, DIRECTOR
    )


def can_view_only(user) -> bool:  # type: ignore[no-untyped-def]
    return user_in_group(user, VIEWER) and not can_evaluate(user) and not can_approve(user)


def procurement_required(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    @wraps(view)
    def _wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:  # type: ignore[no-untyped-def]
        if not request.user.is_authenticated or not is_staff_user(request.user):
            return HttpResponseForbidden("Staff only.")
        if not can_evaluate(request.user):
            messages.error(request, "Procurement role required for this action.")
            return redirect("staff:admin_dashboard")
        return view(request, *args, **kwargs)

    return _wrapped


def director_required(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    @wraps(view)
    def _wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:  # type: ignore[no-untyped-def]
        if not request.user.is_authenticated or not is_staff_user(request.user):
            return HttpResponseForbidden("Staff only.")
        if not can_approve(request.user):
            messages.error(request, "Director role required for this action.")
            return redirect("staff:admin_dashboard")
        return view(request, *args, **kwargs)

    return _wrapped
