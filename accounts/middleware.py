"""Local-dev helpers for auth / OAuth host consistency."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponsePermanentRedirect


class PreferLocalhostMiddleware:
    """In DEBUG, redirect 127.0.0.1 → localhost so Google OAuth redirect_uri matches.

    Google treats http://127.0.0.1:8000/... and http://localhost:8000/... as different
    redirect URIs. runserver defaults to 127.0.0.1; our docs/Site use localhost.
    """

    def __init__(self, get_response) -> None:  # type: ignore[no-untyped-def]
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if settings.DEBUG and request.get_host().startswith("127.0.0.1"):
            port = ""
            if ":" in request.get_host():
                port = ":" + request.get_host().split(":", 1)[1]
            target = f"http://localhost{port}{request.get_full_path()}"
            return HttpResponsePermanentRedirect(target)
        return self.get_response(request)
