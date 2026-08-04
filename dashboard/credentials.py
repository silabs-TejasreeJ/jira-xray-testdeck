"""Request-scoped Jira credentials (session or environment)."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from django.conf import settings

_creds_ctx: ContextVar[dict[str, str] | None] = ContextVar("jira_creds", default=None)


def set_request_credentials(
    username: str = "",
    password: str = "",
    base_url: str = "",
) -> None:
    _creds_ctx.set(
        {
            "username": username or "",
            "password": password or "",
            "base_url": (base_url or settings.JIRA_BASE_URL or "").rstrip("/"),
        }
    )


def clear_request_credentials() -> None:
    _creds_ctx.set(None)


def get_active_credentials() -> dict[str, str]:
    ctx = _creds_ctx.get()
    if ctx and ctx.get("username") and ctx.get("password"):
        return {
            "username": ctx["username"],
            "password": ctx["password"],
            "base_url": (ctx.get("base_url") or settings.JIRA_BASE_URL).rstrip("/"),
        }
    return {
        "username": settings.JIRA_USERNAME or "",
        "password": settings.JIRA_PASSWORD or "",
        "base_url": (settings.JIRA_BASE_URL or "").rstrip("/"),
    }


def credentials_configured() -> bool:
    creds = get_active_credentials()
    return bool(creds["username"] and creds["password"] and creds["base_url"])


def apply_session_credentials(session: Any) -> None:
    username = session.get("jira_username") or ""
    password = session.get("jira_password") or ""
    base_url = session.get("jira_base_url") or settings.JIRA_BASE_URL
    if username and password:
        set_request_credentials(username, password, base_url)
    else:
        clear_request_credentials()
