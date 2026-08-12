"""Xray Server/DC (Raven) REST client."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import quote

from .jira_client import JiraClient, JiraError


class XrayClient:
    """Thin wrapper around Xray Raven REST APIs hosted on Jira Server/DC."""

    PAGE_SIZE = 200

    def __init__(self, jira: JiraClient | None = None) -> None:
        self.jira = jira or JiraClient()

    def _try_paths(self, paths: list[str], **kwargs: Any) -> Any:
        last_error: Exception | None = None
        for path in paths:
            try:
                return self.jira.get(path, **kwargs)
            except JiraError as exc:
                last_error = exc
                if exc.status_code not in {404, 405}:
                    raise
        if last_error:
            raise last_error
        raise JiraError("No Xray endpoint available")

    def _normalize_list(self, data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for candidate in (
                "tests",
                "values",
                "data",
                "testRuns",
                "testExecutions",
                "executions",
                "entries",
                "results",
                "issues",
            ):
                if isinstance(data.get(candidate), list):
                    return data[candidate]
        return []

    @staticmethod
    def _execution_key_from_item(item: Any) -> str:
        """Best-effort key extraction from Xray test-plan execution payloads."""
        if isinstance(item, str):
            return item.strip()
        if not isinstance(item, dict):
            return ""
        for key in ("key", "issueKey", "testExecutionKey", "executionKey"):
            val = item.get(key)
            if val:
                return str(val).strip()
        for nested in ("testExecution", "execution", "issue", "test"):
            node = item.get(nested)
            if isinstance(node, dict):
                for key in ("key", "issueKey"):
                    val = node.get(key)
                    if val:
                        return str(val).strip()
            elif isinstance(node, str) and node.strip():
                return node.strip()
        return ""

    def get_test_execution_tests(
        self,
        test_exec_key: str,
        detailed: bool = False,
        limit: int | None = None,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "detailed": str(detailed).lower(),
            "limit": limit if limit is not None else self.PAGE_SIZE,
            "page": page,
        }
        key = quote(test_exec_key)
        paths = [
            f"/rest/raven/1.0/api/testexec/{key}/test",
            f"/rest/raven/2.0/api/testexec/{key}/test",
        ]
        try:
            data = self._try_paths(paths, params=params)
        except JiraError as exc:
            # Large executions often 500 with detailed=true on Silabs Xray.
            if detailed and exc.status_code in {500, 502, 503, 504}:
                params = {**params, "detailed": "false"}
                data = self._try_paths(paths, params=params)
            else:
                raise
        return self._normalize_list(data)

    def get_all_test_execution_tests(
        self,
        test_exec_key: str,
        detailed: bool = False,
        hard_limit: int = 5000,
        only_keys: set[str] | None = None,
        max_workers: int = 6,
        page_size: int | None = None,
    ) -> list[dict[str, Any]]:
        size = page_size or self.PAGE_SIZE
        first = self.get_test_execution_tests(
            test_exec_key,
            detailed=detailed,
            limit=size,
            page=1,
        )
        if not first:
            return []

        results = list(first)
        if len(first) < size:
            return self._filter_keys(results, only_keys)[:hard_limit]

        # Speculatively fetch more pages in parallel, then stop at short page.
        max_pages = max(1, (hard_limit + size - 1) // size)
        pages_to_fetch = list(range(2, min(max_pages, 80) + 1))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(
                    self.get_test_execution_tests,
                    test_exec_key,
                    detailed,
                    size,
                    page,
                ): page
                for page in pages_to_fetch
            }
            page_map: dict[int, list[dict[str, Any]]] = {}
            for fut in as_completed(futures):
                page = futures[fut]
                try:
                    page_map[page] = fut.result() or []
                except JiraError:
                    page_map[page] = []

        for page in sorted(page_map):
            batch = page_map[page]
            if not batch:
                break
            results.extend(batch)
            if len(batch) < size:
                # ignore higher speculative pages
                break
            if len(results) >= hard_limit:
                break

        return self._filter_keys(results, only_keys)[:hard_limit]

    @staticmethod
    def _filter_keys(
        rows: list[dict[str, Any]], only_keys: set[str] | None
    ) -> list[dict[str, Any]]:
        if only_keys is None:
            return rows
        out = []
        for item in rows:
            key = item.get("key") or item.get("testKey")
            if key in only_keys:
                out.append(item)
        return out

    def get_test_plan_tests(
        self,
        test_plan_key: str,
        limit: int = 200,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        key = quote(test_plan_key)
        data = self._try_paths(
            [
                f"/rest/raven/1.0/api/testplan/{key}/test",
                f"/rest/raven/2.0/api/testplan/{key}/test",
            ],
            params={"limit": limit, "page": page},
        )
        return self._normalize_list(data)

    def get_all_test_plan_tests(
        self,
        test_plan_key: str,
        hard_limit: int = 5000,
        max_workers: int = 6,
        page_size: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all tests in a plan; parallelize pages after the first."""
        size = page_size or self.PAGE_SIZE
        first = self.get_test_plan_tests(test_plan_key, limit=size, page=1)
        if not first:
            return []

        results = list(first)
        if len(first) < size:
            return results[:hard_limit]

        max_pages = max(1, (hard_limit + size - 1) // size)
        pages_to_fetch = list(range(2, min(max_pages, 80) + 1))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(
                    self.get_test_plan_tests, test_plan_key, size, page
                ): page
                for page in pages_to_fetch
            }
            page_map: dict[int, list[dict[str, Any]]] = {}
            for fut in as_completed(futures):
                page = futures[fut]
                try:
                    page_map[page] = fut.result() or []
                except JiraError:
                    page_map[page] = []

        for page in sorted(page_map):
            batch = page_map[page]
            if not batch:
                break
            results.extend(batch)
            if len(batch) < size:
                break
            if len(results) >= hard_limit:
                break

        return results[:hard_limit]

    def get_test_plan_executions(self, test_plan_key: str) -> list[dict[str, Any]]:
        """Return Test Executions linked to a Test Plan (normalized key/summary rows)."""
        key = quote(test_plan_key)
        raw: list[dict[str, Any]] = []
        try:
            data = self._try_paths(
                [
                    f"/rest/raven/1.0/api/testplan/{key}/testexecution",
                    f"/rest/raven/2.0/api/testplan/{key}/testexecution",
                    f"/rest/raven/1.0/api/testplan/{key}/testexecutions",
                    f"/rest/raven/2.0/api/testplan/{key}/testexecutions",
                ]
            )
            raw = self._normalize_list(data)
        except JiraError:
            raw = []

        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in raw:
            exec_key = self._execution_key_from_item(item)
            if not exec_key or exec_key in seen:
                continue
            seen.add(exec_key)
            summary = ""
            if isinstance(item, dict):
                nested_exec = item.get("testExecution")
                nested_issue = item.get("issue")
                summary = (
                    item.get("summary")
                    or item.get("testExecutionSummary")
                    or (
                        nested_exec.get("summary")
                        if isinstance(nested_exec, dict)
                        else ""
                    )
                    or (
                        nested_issue.get("summary")
                        if isinstance(nested_issue, dict)
                        else ""
                    )
                    or ""
                )
            rows.append({"key": exec_key, "summary": str(summary or "")})

        # JQL fallback when Raven list is empty / unexpected shape.
        if not rows:
            for jql in (
                f'issue in testPlanTestExecutions("{test_plan_key}") ORDER BY updated DESC',
                f'issue in testPlanTestExecutions({test_plan_key}) ORDER BY updated DESC',
            ):
                try:
                    issues = self.jira.search_all(
                        jql=jql,
                        fields=["summary", "updated", "status"],
                        page_size=100,
                        hard_limit=500,
                    )
                except JiraError:
                    continue
                for issue in issues or []:
                    exec_key = (issue.get("key") or "").strip()
                    if not exec_key or exec_key in seen:
                        continue
                    seen.add(exec_key)
                    fields = issue.get("fields") or {}
                    rows.append(
                        {
                            "key": exec_key,
                            "summary": fields.get("summary") or "",
                        }
                    )
                if rows:
                    break
        return rows

    def update_test_run_status(self, test_run_id: int | str, status: str) -> Any:
        """
        Update an individual test run status inside a Test Execution.
        Confirmed: PUT /rest/raven/1.0/api/testrun/{id} {"status":"PASS"}
        """
        return self.update_test_run(test_run_id, status=status)

    def get_test_run_defects(self, test_run_id: int | str) -> list[str]:
        """Return linked Execution Defect issue keys for a Test Run."""
        run_id = quote(str(test_run_id))
        last_error: Exception | None = None
        for path in (
            f"/rest/raven/1.0/api/testrun/{run_id}/defect",
            f"/rest/raven/2.0/api/testrun/{run_id}/defect",
        ):
            try:
                data = self.jira.get(path)
                break
            except JiraError as exc:
                last_error = exc
                if exc.status_code not in {404, 405}:
                    raise
                data = None
        else:
            if last_error:
                raise last_error
            return []

        keys: list[str] = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = (
                data.get("defects")
                or data.get("issues")
                or data.get("keys")
                or []
            )
        else:
            items = []
        for item in items:
            if isinstance(item, str) and item.strip():
                keys.append(item.strip().upper())
            elif isinstance(item, dict):
                key = item.get("key") or item.get("id") or item.get("defectKey")
                if key:
                    keys.append(str(key).strip().upper())
        return list(dict.fromkeys(keys))

    def add_test_run_defects(
        self, test_run_id: int | str, issue_keys: list[str]
    ) -> list[str]:
        """
        Link existing Jira issue(s) to a Test Run by key/ID only
        (Xray Execution Defects — associate, do not create issues).

        Confirmed Server/DC patterns:
        - PUT /api/testrun/{id} {"defects": {"add": ["KEY-1"], "remove": []}}
        - POST /api/testrun/{id}/defect  ["KEY-1", "KEY-2"]
        """
        keys = [
            str(k).strip().upper()
            for k in (issue_keys or [])
            if k is not None and str(k).strip()
        ]
        keys = list(dict.fromkeys(keys))
        if not keys:
            return []

        run_id = quote(str(test_run_id))
        put_path = f"/rest/raven/1.0/api/testrun/{run_id}"
        post_paths = (
            f"/rest/raven/1.0/api/testrun/{run_id}/defect",
            f"/rest/raven/2.0/api/testrun/{run_id}/defect",
        )
        attempts: list[tuple[str, str, Any]] = [
            ("put", put_path, {"defects": {"add": keys, "remove": []}}),
            ("put", put_path, {"defects": keys}),
            ("post", post_paths[0], keys),
            ("post", post_paths[0], {"keys": keys}),
            ("post", post_paths[0], {"issues": keys}),
            ("post", post_paths[1], keys),
        ]
        # Per-key POST as last resort (some Xray builds accept a single key only).
        for key in keys:
            attempts.append(("post", post_paths[0], [key]))
            attempts.append(("post", post_paths[0], key))

        last_error: Exception | None = None
        linked_before = set()
        try:
            linked_before = set(self.get_test_run_defects(test_run_id))
        except JiraError:
            linked_before = set()

        for method, path, body in attempts:
            try:
                getattr(self.jira, method)(path, json=body)
            except JiraError as exc:
                last_error = exc
                if exc.status_code in {401, 403}:
                    raise
                continue
            # Confirm the keys are actually associated (link-by-ID, not create).
            try:
                linked_after = set(self.get_test_run_defects(test_run_id))
            except JiraError:
                # Write may have worked even if GET is unavailable.
                return keys
            missing = [k for k in keys if k not in linked_after]
            if not missing:
                return sorted(linked_after)
            # Partial progress — keep trying remaining strategies for leftovers.
            if linked_after - linked_before:
                keys = missing
                continue

        if last_error:
            raise last_error
        raise JiraError(
            f"Unable to link defect key(s) {', '.join(issue_keys)} to test run {test_run_id}"
        )

    @staticmethod
    def _normalize_custom_fields(
        custom_fields: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        cleaned: list[dict[str, Any]] = []
        for item in custom_fields or []:
            field_id = item.get("id")
            if field_id is None or field_id == "":
                continue
            try:
                field_id = int(field_id)
            except (TypeError, ValueError):
                pass
            cleaned.append({"id": field_id, "value": item.get("value", "")})
        return cleaned

    def set_test_run_custom_field(
        self,
        test_run_id: int | str,
        custom_field_id: int | str,
        value: Any,
    ) -> Any:
        """
        Set one Test Run custom field.

        Confirmed from Silabs Jira Network capture:
        POST /rest/raven/1.0/customFields/testRunValues
          ?testRunId={id}&customFieldId={fieldId}
        Body: JSON string value, e.g. "Automation first run"
        Status: 201 Created
        """
        import json as json_lib

        # Body must be a JSON string value, e.g. "Automation first run" (Silabs Network capture).
        if isinstance(value, (dict, list)):
            payload = value
        else:
            payload = str(value)
        params = f"testRunId={quote(str(test_run_id))}&customFieldId={quote(str(custom_field_id))}"
        paths = (
            f"/rest/raven/1.0/customFields/testRunValues?{params}",
            f"/rest/raven/1.0/api/customFields/testRunValues?{params}",
        )
        last_error: Exception | None = None
        for path in paths:
            # Silabs uses POST (201); keep PUT as fallback.
            for method in ("post", "put"):
                try:
                    return getattr(self.jira, method)(path, json=payload)
                except JiraError as exc:
                    last_error = exc
                    if exc.status_code in {401, 403}:
                        raise
                    # Retry alternate encodings on 400.
                    if exc.status_code == 400:
                        try:
                            return getattr(self.jira, method)(
                                path,
                                data=json_lib.dumps(payload),
                                headers={"Content-Type": "application/json"},
                            )
                        except JiraError as exc2:
                            last_error = exc2
                    if exc.status_code not in {404, 405, 400}:
                        continue
        if last_error:
            raise last_error
        raise JiraError("Unable to set test run custom field")

    def update_test_run(
        self,
        test_run_id: int | str,
        *,
        status: str | None = None,
        custom_fields: list[dict[str, Any]] | None = None,
    ) -> Any:
        """
        Update a test run status and/or Test Run custom fields.

        Status: PUT /api/testrun/{id}
        Custom fields: per-field testRunValues?testRunId=&customFieldId= (Silabs Xray)
        """
        run_id = quote(str(test_run_id))
        cleaned = self._normalize_custom_fields(custom_fields)
        status_result = None
        if status is not None:
            normalized = (status or "").strip().upper()
            if not normalized:
                raise JiraError("Status is required")
            status_result = self.jira.put(
                f"/rest/raven/1.0/api/testrun/{run_id}",
                json={"status": normalized},
            )

        if cleaned:
            for item in cleaned:
                self.set_test_run_custom_field(
                    test_run_id, item["id"], item.get("value", "")
                )
            return status_result

        if status is None and not cleaned:
            raise JiraError("Nothing to update on test run")
        return status_result

    def import_execution_results(
        self,
        test_execution_key: str,
        tests: list[dict[str, Any]],
    ) -> Any:
        """POST Xray JSON results (status + test-run custom fields)."""
        if not test_execution_key:
            raise JiraError("testExecutionKey is required")
        if not tests:
            raise JiraError("tests are required")
        payload = {
            "testExecutionKey": test_execution_key,
            "tests": tests,
        }
        last_error: Exception | None = None
        for path in (
            "/rest/raven/1.0/api/import/execution",
            "/rest/raven/1.0/import/execution",
            "/rest/raven/2.0/api/import/execution",
        ):
            try:
                return self.jira.post(path, json=payload)
            except JiraError as exc:
                last_error = exc
                if exc.status_code not in {404, 405}:
                    raise
        if last_error:
            raise last_error
        raise JiraError("No Xray import/execution endpoint available")

    def get_test_run(self, test_run_id: int | str) -> dict[str, Any]:
        run_id = quote(str(test_run_id))
        data = self.jira.get(f"/rest/raven/1.0/api/testrun/{run_id}")
        return data if isinstance(data, dict) else {}

    def get_test_steps(self, test_key: str) -> list[dict[str, Any]]:
        """Return manual test steps for an Xray Test (Action / Data / Expected Result)."""
        key = quote((test_key or "").strip())
        if not key:
            return []
        last_error: Exception | None = None
        for path in (
            f"/rest/raven/1.0/api/test/{key}/step",
            f"/rest/raven/2.0/api/test/{key}/steps",
        ):
            try:
                data = self.jira.get(path)
            except JiraError as exc:
                last_error = exc
                if exc.status_code in {401, 403}:
                    raise
                if exc.status_code not in {404, 405}:
                    continue
                continue
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                steps = data.get("steps")
                if isinstance(steps, list):
                    return steps
                return [data] if data else []
        if last_error and getattr(last_error, "status_code", None) not in {404, 405}:
            raise last_error
        return []

    def get_test_run_assignee(self, test_run_id: int | str) -> Any:
        """GET /rest/raven/1.0/api/testrun/{id}/assignee"""
        run_id = quote(str(test_run_id))
        last_error: Exception | None = None
        for path in (
            f"/rest/raven/1.0/api/testrun/{run_id}/assignee",
            f"/rest/raven/1.0/testrun/{run_id}/assignee",
        ):
            try:
                return self.jira.get(path)
            except JiraError as exc:
                last_error = exc
                if exc.status_code in {401, 403}:
                    raise
                if exc.status_code not in {404, 405}:
                    continue
        if last_error:
            raise last_error
        return None

    def set_test_run_assignee(self, test_run_id: int | str, user: str) -> Any:
        """
        PUT /rest/raven/1.0/api/testrun/{id}/assignee?user=<jiraUserKey>
        `user` is the Jira username / user key (not display name).
        """
        user = (user or "").strip()
        if not user:
            raise JiraError("Assignee user is required")
        run_id = quote(str(test_run_id))
        last_error: Exception | None = None
        for path_base in (
            f"/rest/raven/1.0/api/testrun/{run_id}/assignee",
            f"/rest/raven/1.0/testrun/{run_id}/assignee",
        ):
            for param in ("user", "assignee", "accountId"):
                path = f"{path_base}?{param}={quote(user)}"
                try:
                    return self.jira.put(path)
                except JiraError as exc:
                    last_error = exc
                    if exc.status_code in {401, 403}:
                        raise
                    if exc.status_code not in {404, 405, 400}:
                        continue
        if last_error:
            raise last_error
        raise JiraError(f"Unable to set assignee for test run {test_run_id}")

    def get_test_run_custom_field_values(self, test_run_id: int | str) -> list[dict[str, Any]]:
        """
        List Test Run custom fields (id/name/value) for one run.

        Silabs write path uses the same resource:
        GET /rest/raven/1.0/customFields/testRunValues?testRunId={id}
        """
        run_id = quote(str(test_run_id))
        paths = (
            f"/rest/raven/1.0/customFields/testRunValues?testRunId={run_id}",
            f"/rest/raven/1.0/api/customFields/testRunValues?testRunId={run_id}",
            f"/rest/raven/1.0/api/testrun/{run_id}/customFields",
            f"/rest/raven/1.0/api/testrun/{run_id}/customfields",
        )
        last_error: Exception | None = None
        for path in paths:
            try:
                data = self.jira.get(path)
            except JiraError as exc:
                last_error = exc
                if exc.status_code in {401, 403}:
                    raise
                continue
            parsed = self._parse_test_run_custom_field_values(data)
            if parsed:
                return parsed
            # Some instances nest values under the test-run payload.
            if isinstance(data, dict):
                for key in ("customFields", "customfields", "values", "fields"):
                    nested = self._parse_test_run_custom_field_values(data.get(key))
                    if nested:
                        return nested
        if last_error and getattr(last_error, "status_code", None) not in {404, 405}:
            raise last_error
        return []

    @staticmethod
    def _parse_test_run_custom_field_values(data: Any) -> list[dict[str, Any]]:
        """Normalize GET testRunValues / customFields payloads into [{id,name,value,options}]."""
        rows: list[dict[str, Any]] = []

        from .testrun_fields import is_valid_trcf_id, normalize_trcf_value

        def _push(
            field_id: Any,
            name: Any = "",
            value: Any = "",
            options: Any = None,
        ) -> None:
            if not is_valid_trcf_id(field_id):
                return
            opt_list: list[Any] = []
            if isinstance(options, list):
                for opt in options:
                    if isinstance(opt, dict):
                        text = normalize_trcf_value(
                            opt.get("value") or opt.get("name") or opt.get("label") or opt
                        )
                    else:
                        text = normalize_trcf_value(opt)
                    if text:
                        opt_list.append(text)
            rows.append(
                {
                    "id": int(field_id),
                    "customFieldId": int(field_id),
                    "name": str(name or "").strip(),
                    "value": normalize_trcf_value(value),
                    "options": opt_list,
                }
            )

        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                field_id = (
                    item.get("customFieldId")
                    or item.get("cfId")
                    or item.get("fieldId")
                    or item.get("id")
                )
                name = (
                    item.get("name")
                    or item.get("label")
                    or item.get("customFieldName")
                    or item.get("fieldName")
                    or ""
                )
                # Skip anonymous junk rows (no name and no usable value) — often nested debris.
                if not str(name).strip() and not normalize_trcf_value(item.get("value")):
                    if not is_valid_trcf_id(field_id):
                        continue
                _push(
                    field_id,
                    name,
                    item.get("value"),
                    item.get("options") or item.get("allowedValues"),
                )
            return rows

        if isinstance(data, dict):
            # Shape: {"18": "Automation first run", "22": "EFR"}
            scalar_map = True
            for key, value in data.items():
                if isinstance(value, (dict, list)):
                    scalar_map = False
                    break
                if not str(key).isdigit():
                    scalar_map = False
                    break
            if scalar_map and data:
                for key, value in data.items():
                    _push(key, "", value)
                return rows

            # Shape: {"customFields":[...]} already handled by caller; also
            # {"fields":[{"id":18,"name":"..."}]} etc.
            for key_name in ("customFields", "customfields", "values", "fields", "data"):
                nested = data.get(key_name)
                if nested is not None:
                    parsed = XrayClient._parse_test_run_custom_field_values(nested)
                    if parsed:
                        return parsed

            # Single field object
            field_id = data.get("customFieldId") or data.get("cfId") or data.get("id")
            name = data.get("name") or data.get("label") or data.get("customFieldName")
            if is_valid_trcf_id(field_id) and (name or "value" in data):
                _push(field_id, name or "", data.get("value"), data.get("options"))
        return rows

    def list_test_run_custom_field_settings(
        self,
        project_keys: list[str] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Best-effort fetch of Test Run custom field definitions.

        Returns (fields, probe_log). Tries execution + test projects.
        """
        from django.conf import settings as dj_settings

        keys: list[str] = []
        for key in project_keys or []:
            key = (key or "").strip()
            if key and key not in keys:
                keys.append(key)
        for key in (
            getattr(dj_settings, "JIRA_PROJECT_KEY", ""),
            getattr(dj_settings, "JIRA_TEST_PROJECT_KEY", ""),
        ):
            key = (key or "").strip()
            if key and key not in keys:
                keys.append(key)

        paths: list[str] = []
        for project_key in keys:
            key = quote(project_key)
            paths.extend(
                [
                    f"/rest/raven/1.0/api/project/{key}/settings/customfields/testruns",
                    f"/rest/raven/2.0/api/project/{key}/settings/customfields/testruns",
                    f"/rest/raven/1.0/api/project/{key}/settings/customFields/testRuns",
                    f"/rest/raven/1.0/api/project/{key}/testruncustomfields",
                    f"/rest/raven/1.0/api/settings/{key}/testruncustomfields",
                ]
            )
            try:
                project = self.jira.get(f"/rest/api/2/project/{key}")
                project_id = project.get("id") if isinstance(project, dict) else None
                if project_id:
                    pid = quote(str(project_id))
                    paths.extend(
                        [
                            f"/rest/raven/1.0/api/project/{pid}/settings/customfields/testruns",
                            f"/rest/raven/2.0/api/project/{pid}/settings/customfields/testruns",
                            f"/rest/raven/2.0/api/project/{pid}/settings/customFields/testRuns",
                        ]
                    )
            except JiraError:
                pass

        paths.extend(
            [
                "/rest/raven/1.0/api/settings/testrun/customfields",
                "/rest/raven/1.0/api/settings/testRunCustomFields",
                "/rest/raven/1.0/api/settings/customfields/testruns",
                "/rest/raven/1.0/settings/testrun/customfields",
                "/rest/raven/1.0/api/testruncustomfields",
            ]
        )

        def _parse_fields(data: Any) -> list[dict[str, Any]]:
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict)]
            if isinstance(data, dict):
                for key_name in (
                    "fields",
                    "values",
                    "data",
                    "customFields",
                    "testRunCustomFields",
                ):
                    if isinstance(data.get(key_name), list):
                        return [x for x in data[key_name] if isinstance(x, dict)]
                from .testrun_fields import extract_named_ids

                return extract_named_ids(data)
            return []

        def _probe(path: str) -> tuple[str, list[dict[str, Any]], int | None, bool]:
            try:
                data = self.jira.get(path)
                fields = _parse_fields(data)
                return path, fields, 200, True
            except JiraError as exc:
                return path, [], exc.status_code, False

        # Probe most likely endpoints first, in parallel batches, stop early.
        preferred = [p for p in paths if "/settings/customfields/testruns" in p.lower()]
        remaining = [p for p in paths if p not in preferred]
        ordered = preferred + remaining
        probe_log: list[dict[str, Any]] = []
        from concurrent.futures import ThreadPoolExecutor, as_completed

        batch_size = 6
        for start in range(0, len(ordered), batch_size):
            batch = ordered[start : start + batch_size]
            with ThreadPoolExecutor(max_workers=min(6, len(batch))) as pool:
                futures = [pool.submit(_probe, path) for path in batch]
                for fut in as_completed(futures):
                    path, fields, status, ok = fut.result()
                    probe_log.append(
                        {
                            "path": path,
                            "status": status,
                            "ok": ok,
                            "count": len(fields),
                        }
                    )
                    if fields:
                        return fields, probe_log
        return [], probe_log
