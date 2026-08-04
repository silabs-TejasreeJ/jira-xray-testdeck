from __future__ import annotations

from django.shortcuts import redirect
from django.urls import reverse

from .credentials import apply_session_credentials, clear_request_credentials, credentials_configured


class JiraCredentialsMiddleware:
    """
    Load Jira credentials from the session for each request.
    Redirect to the login page when none are available.
    """

    EXEMPT_PREFIXES = (
        "/login",
        "/logout",
        "/static/",
        "/admin/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or "/"
        exempt = any(path.startswith(p) for p in self.EXEMPT_PREFIXES)

        apply_session_credentials(request.session)

        if not exempt and not credentials_configured():
            login_url = reverse("login")
            if path != login_url:
                return redirect(f"{login_url}?next={path}")

        try:
            response = self.get_response(request)
        finally:
            clear_request_credentials()
        return response
