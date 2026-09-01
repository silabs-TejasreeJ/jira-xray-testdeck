"""Jira Server/DC REST client (basic auth)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import quote

import requests
from django.conf import settings
from requests.auth import HTTPBasicAuth

from .credentials import get_active_credentials


class JiraError(Exception):
    def __init__(self, message: str, status_code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class JiraClient:
    def __init__(self) -> None:
        creds = get_active_credentials()
        self.base_url = creds["base_url"].rstrip("/")
        self.username = creds["username"]
        self.password = creds["password"]
        self.verify_ssl = settings.JIRA_VERIFY_SSL
        self.session = requests.Session()
        if self.username and self.password:
            self.session.auth = HTTPBasicAuth(self.username, self.password)
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.username and self.password)

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{self.base_url}{path}"

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        if not self.configured:
            raise JiraError(
                "Jira credentials are not configured. Copy .env.example to .env and set "
                "JIRA_USERNAME / JIRA_PASSWORD."
            )

        kwargs.setdefault("verify", self.verify_ssl)
        kwargs.setdefault("timeout", 180)
        try:
            response = self.session.request(method, self._url(path), **kwargs)
        except requests.Timeout as exc:
            raise JiraError(f"Jira request timed out for {path}: {exc}") from exc
        except requests.RequestException as exc:
            raise JiraError(f"Jira request failed for {path}: {exc}") from exc

        if response.status_code >= 400:
            detail: Any
            try:
                detail = response.json()
            except Exception:
                detail = response.text
            raise JiraError(
                f"Jira API error {response.status_code} for {path}",
                status_code=response.status_code,
                payload=detail,
            )

        # 201 Created (Xray testRunValues) and 204 often have empty/non-JSON bodies.
        if response.status_code in {201, 204} or not response.content:
            if not response.content:
                return None
            try:
                return response.json()
            except Exception:
                return response.text
        try:
            return response.json()
        except Exception:
            return response.text

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Any:
        return self.request("PUT", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self.request("DELETE", path, **kwargs)

    def get_myself(self) -> dict[str, Any]:
        return self.get("/rest/api/2/myself")

    def get_issue(self, key: str, fields: str | None = None, expand: str | None = None) -> dict[str, Any]:
        params: dict[str, str] = {}
        if fields:
            params["fields"] = fields
        if expand:
            params["expand"] = expand
        return self.get(f"/rest/api/2/issue/{quote(key)}", params=params)

    def search(
        self,
        jql: str,
        fields: list[str] | None = None,
        max_results: int = 50,
        start_at: int = 0,
        expand: list[str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "jql": jql,
            "startAt": start_at,
            "maxResults": max_results,
        }
        if fields is not None:
            payload["fields"] = fields
        if expand:
            payload["expand"] = expand
        return self.request("POST", "/rest/api/2/search", json=payload)

    def search_all(
        self,
        jql: str,
        fields: list[str] | None = None,
        page_size: int = 200,
        hard_limit: int = 2000,
        max_workers: int = 6,
    ) -> list[dict[str, Any]]:
        first = self.search(
            jql=jql,
            fields=fields,
            max_results=min(page_size, hard_limit),
            start_at=0,
        )
        issues = list(first.get("issues") or [])
        total = min(int(first.get("total") or 0), hard_limit)
        if len(issues) >= total or not issues:
            return issues[:hard_limit]

        starts = list(range(page_size, total, page_size))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(
                    self.search,
                    jql=jql,
                    fields=fields,
                    max_results=page_size,
                    start_at=start,
                ): start
                for start in starts
            }
            pages: dict[int, list[dict[str, Any]]] = {}
            for fut in as_completed(futures):
                start = futures[fut]
                pages[start] = list((fut.result() or {}).get("issues") or [])
        for start in sorted(pages):
            issues.extend(pages[start])
        return issues[:hard_limit]

    def get_fields(self) -> list[dict[str, Any]]:
        return self.get("/rest/api/2/field")

    def search_users(self, query: str, max_results: int = 15) -> list[dict[str, Any]]:
        """Search Jira users for assignee picker."""
        query = (query or "").strip()
        if not query:
            return []
        data = self.get(
            "/rest/api/2/user/search",
            params={"username": query, "maxResults": max_results},
        )
        if not isinstance(data, list):
            return []
        out: list[dict[str, Any]] = []
        for user in data:
            if not isinstance(user, dict):
                continue
            name = (user.get("name") or user.get("key") or "").strip()
            display = (user.get("displayName") or name).strip()
            if not name:
                continue
            out.append(
                {
                    "name": name,
                    "key": user.get("key") or name,
                    "displayName": display,
                    "emailAddress": user.get("emailAddress") or "",
                }
            )
        return out

    def issue_picker(self, query: str, max_results: int = 20) -> list[dict[str, Any]]:
        """
        Jira issue picker (same backend Xray uses for “Choose issue to associate”).
        Returns issue key + summary rows for linking by ID.
        """
        query = (query or "").strip()
        if not query:
            return []
        data = self.get(
            "/rest/api/2/issue/picker",
            params={
                "query": query,
                "currentJQL": "",
                "showSubTasks": "true",
                "showSubTaskParent": "true",
            },
        )
        if not isinstance(data, dict):
            return []
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        sections = data.get("sections") or []
        if not isinstance(sections, list):
            return []
        for section in sections:
            if not isinstance(section, dict):
                continue
            for issue in section.get("issues") or []:
                if not isinstance(issue, dict):
                    continue
                key = (issue.get("key") or "").strip()
                if not key or key in seen:
                    continue
                seen.add(key)
                summary = (
                    (issue.get("summaryText") or issue.get("summary") or "")
                    .strip()
                )
                # keyHtml / summary often include markup — prefer plain fields.
                rows.append(
                    {
                        "key": key,
                        "summary": summary,
                        "issuetype": "",
                        "status": "",
                        "label": f"{key} — {summary}".strip(" —") if summary else key,
                    }
                )
                if len(rows) >= max_results:
                    return rows
        return rows

    def browse_url(self, key: str) -> str:
        return f"{self.base_url}/browse/{key}"
