#!/usr/bin/env python
"""Start TestDeck after prompting for Jira credentials."""

from __future__ import annotations

import getpass
import os
import subprocess
import sys
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth


ROOT = Path(__file__).resolve().parent


def _prompt(label: str, default: str = "", secret: bool = False) -> str:
    if default and not secret:
        shown = f"{label} [{default}]: "
    else:
        shown = f"{label}: "
    while True:
        value = getpass.getpass(shown) if secret else input(shown)
        value = (value or "").strip() or default
        if value:
            return value
        print("This value is required.")


def _validate(base_url: str, username: str, password: str) -> str:
    url = f"{base_url.rstrip('/')}/rest/api/2/myself"
    try:
        response = requests.get(
            url,
            auth=HTTPBasicAuth(username, password),
            timeout=30,
            verify=os.getenv("JIRA_VERIFY_SSL", "true").lower()
            in {"1", "true", "yes", "on"},
        )
    except requests.RequestException as exc:
        raise SystemExit(
            f"Could not reach Jira at {base_url}.\n"
            f"Details: {exc}\n"
            "Check VPN / network, then try again."
        ) from exc

    if response.status_code >= 400:
        raise SystemExit(
            f"Jira login failed (HTTP {response.status_code}). "
            "Check username/password and try again."
        )
    data = response.json()
    return data.get("displayName") or data.get("name") or username


def main() -> int:
    print("==============================")
    print("        TestDeck Launcher")
    print("==============================")
    print("Enter Jira credentials to start the local server.\n")

    base_url = _prompt("Jira URL", os.getenv("JIRA_BASE_URL", "https://jira.silabs.com"))
    username = _prompt("Jira username", os.getenv("JIRA_USERNAME", ""))
    password = _prompt("Jira password", secret=True)

    print("\nVerifying credentials...")
    display = _validate(base_url, username, password)
    print(f"Connected as {display}\n")

    env = os.environ.copy()
    env["JIRA_BASE_URL"] = base_url.rstrip("/")
    env["JIRA_USERNAME"] = username
    env["JIRA_PASSWORD"] = password

    print("Starting TestDeck at http://127.0.0.1:8000 ...")
    print("Press Ctrl+C to stop.\n")
    try:
        return subprocess.call(
            [sys.executable, "manage.py", "runserver", "8000"],
            cwd=str(ROOT),
            env=env,
        )
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
