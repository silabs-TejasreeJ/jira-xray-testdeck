from __future__ import annotations

import json
from urllib.parse import urlencode

import json as json_lib

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .credentials import set_request_credentials
from .jira_client import JiraClient, JiraError
from .services import EDITABLE_STATUSES, get_service

# Toggleable case-table columns (check/select column is always visible).
PLAN_CASE_COLUMNS = [
    {"key": "id", "label": "ID", "default": True},
    {"key": "case_id", "label": "Case ID", "default": True},
    {"key": "title", "label": "Title", "default": True},
    {"key": "assignee", "label": "Assigned To", "default": True},
    {"key": "priority", "label": "Priority", "default": False},
    {"key": "status", "label": "Status", "default": True},
    {"key": "defects", "label": "Linked Jira", "default": True},
    {"key": "section", "label": "Section", "default": False},
    {"key": "technology", "label": "Technology", "default": False},
]

EXECUTION_CASE_COLUMNS = [
    {"key": "id", "label": "ID", "default": True},
    {"key": "case_id", "label": "Case ID", "default": True},
    {"key": "title", "label": "Title", "default": True},
    {"key": "assignee", "label": "Assigned To", "default": True},
    {"key": "priority", "label": "Priority", "default": False},
    {"key": "status", "label": "Status", "default": True},
    {"key": "defects", "label": "Linked Jira", "default": True},
    {"key": "section", "label": "Section", "default": False},
    {"key": "technology", "label": "Technology", "default": False},
]


def _error_context(exc: Exception) -> dict:
    payload = getattr(exc, "payload", None)
    detail = str(exc)
    if isinstance(payload, dict):
        msgs = payload.get("errorMessages") or []
        if isinstance(msgs, list) and msgs:
            detail = f"{exc}: {'; '.join(str(m) for m in msgs if m)}"
    return {
        "error": detail,
        "error_status": getattr(exc, "status_code", None),
        "error_payload": payload,
    }


def _plan_picker_options(
    service,
    current_key: str = "",
    technology: str | None = None,
    stack_name: str | None = None,
    release_name: str | None = None,
) -> list[dict]:
    """Recent Test Plans for the plan dropdown; scoped by stack + release."""
    from django.core.cache import cache

    stack = (
        stack_name
        if stack_name is not None
        else getattr(settings, "DEFAULT_STACK_NAME", "") or ""
    )
    release = (
        release_name
        if release_name is not None
        else getattr(settings, "DEFAULT_RELEASE_NAME", "") or ""
    )
    stack_slug = (stack or "ALL").replace(" ", "_").replace("+", "plus")
    release_slug = (release or "ALL").replace(" ", "_").replace("+", "plus")
    cache_key = f"plan_picker_opts_v5:{stack_slug}:{release_slug}"
    plans = cache.get(cache_key)
    if not isinstance(plans, list):
        plans = service.list_test_plans(
            query="", limit=80, stack_name=stack, release_name=release
        )
        cache.set(cache_key, plans, max(settings.JIRA_CACHE_SECONDS, 300))
    plans = list(plans or [])
    current_key = (current_key or "").strip()
    if current_key and not any(p.get("key") == current_key for p in plans):
        try:
            resolved = service.resolve_plan_ref(
                current_key, stack_name=stack, release_name=release
            )
            plans = [
                {
                    "key": resolved.get("key") or current_key,
                    "summary": resolved.get("summary") or "(current)",
                }
            ] + plans
        except JiraError:
            plans = [{"key": current_key, "summary": "(current)"}] + plans
    return plans


def _plan_execution_options(
    service,
    plan_key: str,
    *,
    fallback_key: str = "",
    fallback_summary: str = "",
) -> list[dict]:
    """Linked Test Executions for a plan (Plan View table + dropdowns)."""
    from django.core.cache import cache

    if plan_key:
        cache_key = f"plan_exec_opts_v3:{plan_key}"
        cached = cache.get(cache_key)
        if isinstance(cached, list) and cached:
            return cached
        try:
            runs = [
                {
                    "key": r["key"],
                    "summary": r.get("summary") or "",
                    "status": "",
                    "updated": "",
                    "url": service.jira.browse_url(r["key"]),
                }
                for r in service.xray.get_test_plan_executions(plan_key)
                if r.get("key")
            ]
            # Enrich all rows with Jira summary/status/updated for the plan table.
            keys = [r["key"] for r in runs if r.get("key")]
            if keys:
                try:
                    by_key: dict[str, dict] = {}
                    for i in range(0, len(keys), 100):
                        batch = keys[i : i + 100]
                        quoted = ", ".join(f'"{k}"' for k in batch)
                        issues = service.jira.search_all(
                            jql=f"key in ({quoted})",
                            fields=["summary", "status", "updated"],
                            page_size=100,
                            hard_limit=len(batch) + 5,
                        )
                        for issue in issues or []:
                            k = (issue.get("key") or "").strip()
                            if not k:
                                continue
                            fields = issue.get("fields") or {}
                            by_key[k] = {
                                "summary": fields.get("summary") or "",
                                "status": ((fields.get("status") or {}).get("name") or ""),
                                "updated": fields.get("updated") or "",
                            }
                    for row in runs:
                        info = by_key.get(row["key"] or "") or {}
                        if info.get("summary"):
                            row["summary"] = info["summary"]
                        row["status"] = info.get("status") or row.get("status") or ""
                        row["updated"] = info.get("updated") or ""
                except JiraError:
                    pass

            def _exec_num(row: dict) -> int:
                try:
                    return int(str(row.get("key") or "").split("-")[-1])
                except Exception:
                    return 0

            runs.sort(key=_exec_num, reverse=True)
            if runs:
                cache.set(cache_key, runs, settings.JIRA_CACHE_SECONDS)
            return runs
        except JiraError:
            pass
    if fallback_key:
        return [
            {
                "key": fallback_key,
                "summary": fallback_summary or "",
                "status": "",
                "updated": "",
                "url": "",
            }
        ]
    return []


def login_view(request):
    next_url = request.GET.get("next") or request.POST.get("next") or "/"
    error = ""
    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""
        base_url = (request.POST.get("base_url") or settings.JIRA_BASE_URL).strip().rstrip("/")
        if not username or not password:
            error = "Username and password are required."
        else:
            set_request_credentials(username, password, base_url)
            client = JiraClient()
            try:
                me = client.get_myself()
                request.session["jira_username"] = username
                request.session["jira_password"] = password
                request.session["jira_base_url"] = base_url
                request.session["jira_display_name"] = (
                    me.get("displayName") or me.get("name") or username
                )
                return redirect(next_url)
            except JiraError as exc:
                error = f"Login failed: {exc}"

    return render(
        request,
        "dashboard/login.html",
        {
            "title": "Sign in",
            "page": "login",
            "error": error,
            "next": next_url,
            "base_url": settings.JIRA_BASE_URL,
            "username": request.POST.get("username", ""),
        },
    )


def logout_view(request):
    for key in ("jira_username", "jira_password", "jira_base_url", "jira_display_name"):
        request.session.pop(key, None)
    return redirect("login")


def _tech(request) -> str:
    # Prefer explicit query param; only fall back to settings if param omitted.
    if "technology" in request.GET:
        raw = request.GET.get("technology") or ""
    else:
        raw = settings.DEFAULT_TECHNOLOGY or ""
    # Repair common mangling of "WLAN + BLE" via unescaped '+' in query strings
    if raw and "BLE" in raw.upper() and "WLAN" in raw.upper() and "+" not in raw:
        collapsed = " ".join(raw.split())
        if collapsed.upper() in {"WLAN BLE", "WLAN  BLE"}:
            return "WLAN + BLE"
    if raw:
        return " ".join(raw.split())
    return raw or ""


def _stack(request) -> str:
    if "stack" in request.GET or "stack_name" in request.GET:
        raw = request.GET.get("stack") or request.GET.get("stack_name") or ""
    else:
        raw = getattr(settings, "DEFAULT_STACK_NAME", "") or ""
    if raw:
        return " ".join(str(raw).split())
    return ""


def _release(request) -> str:
    if "release" in request.GET or "release_name" in request.GET:
        raw = request.GET.get("release") or request.GET.get("release_name") or ""
    else:
        raw = getattr(settings, "DEFAULT_RELEASE_NAME", "") or ""
    if raw:
        return " ".join(str(raw).split())
    return ""


def _case_filters(request) -> dict:
    """Parse All Tests filter query params (status/search/assignee/linked/priority)."""
    assignees = [a.strip() for a in request.GET.getlist("assignee") if a and a.strip()]
    if not assignees:
        raw = (request.GET.get("assignees") or "").strip()
        if raw:
            assignees = [p.strip() for p in raw.split(",") if p.strip()]
    priorities = [p.strip() for p in request.GET.getlist("priority") if p and p.strip()]
    if not priorities:
        raw_p = (request.GET.get("priorities") or "").strip()
        if raw_p:
            priorities = [p.strip() for p in raw_p.split(",") if p.strip()]
    return {
        "status": (request.GET.get("status") or "").strip(),
        "search": (request.GET.get("search") or "").strip(),
        "assignees": assignees,
        "linked_jira": (request.GET.get("linked_jira") or "").strip(),
        "priorities": priorities,
    }


def _redirect_with_params(path: str, **params: str):
    clean = {k: v for k, v in params.items() if v is not None and v != ""}
    return redirect(f"{path}?{urlencode(clean)}")


@require_GET
def home(request):
    service = get_service()
    tech = _tech(request)
    stack = _stack(request)
    release = _release(request)
    context = {
        "page": "overview",
        "title": "Overview",
        "technology": tech,
        "stack_name": stack,
        "release_name": release,
        "default_plan_key": settings.DEFAULT_PLAN_KEY,
    }
    try:
        overview = service.get_overview()
        context.update(overview)
    except JiraError as exc:
        context.update(_error_context(exc))
        context.setdefault("connection", {"ok": False, "message": str(exc)})
        context.setdefault("executions", [])
        context.setdefault("plans", [])

    # Shortcuts should not break the pie chart overview
    for key, loader in (
        (
            "coex_plans",
            lambda: service.list_test_plans(
                query="Coex", limit=10, stack_name=stack, release_name=release
            ),
        ),
        (
            "wlan_plans",
            lambda: service.list_test_plans(
                query="wlan", limit=10, stack_name=stack, release_name=release
            ),
        ),
        ("coex_executions", lambda: service.list_test_executions(query="Coex", limit=10)),
    ):
        try:
            context[key] = loader()
        except JiraError:
            context[key] = []

    try:
        # Optional overview chart only when a plan is explicitly configured/selected.
        plan_key = (request.GET.get("plan") or settings.DEFAULT_PLAN_KEY or "").strip()
        if plan_key:
            runs = [
                r
                for r in service.xray.get_test_plan_executions(plan_key)
                if r.get("key")
            ]

            def _rank(item: dict) -> tuple[int, int]:
                summary = (item.get("summary") or "").lower()
                relevance = 2 if ("wlan" in summary or "coex" in summary) else 0
                try:
                    num = int(str(item["key"]).split("-")[-1])
                except Exception:
                    num = 0
                return (relevance, num)

            execution_key = (request.GET.get("execution") or "").strip()
            if not execution_key and runs:
                execution_key = sorted(runs, key=_rank, reverse=True)[0]["key"]
            plan_data = service.get_test_plan_dashboard(
                plan_key=plan_key,
                technology=tech,
                execution_key=execution_key,
                page=1,
            )
            context["plan"] = plan_data.get("plan")
            context["selected_execution"] = execution_key
            overview_summary = (
                plan_data.get("overall_summary") or plan_data.get("summary") or {}
            )
            context["summary"] = overview_summary
            context["summary_json"] = json.dumps(overview_summary)
            context["case_count"] = plan_data.get(
                "total_cases", plan_data.get("case_count", 0)
            )
            context.pop("error", None)
            context.pop("error_status", None)
            context.pop("error_payload", None)
    except JiraError as exc:
        context.update(_error_context(exc))
        context.setdefault(
            "summary",
            {
                "counts": {},
                "total": 0,
                "passed": 0,
                "failed": 0,
                "todo": 0,
                "pass_pct": 0,
                "todo_pct": 0,
                "chart": [],
            },
        )
        context.setdefault("summary_json", "{}")
    return render(request, "dashboard/home.html", context)


@require_GET
def executions(request):
    service = get_service()
    query = request.GET.get("q", "")
    tech = _tech(request)
    context = {
        "page": "executions",
        "title": "Test Executions",
        "query": query,
        "technology": tech,
    }
    try:
        context["executions"] = service.list_test_executions(query=query, limit=50)
        context["connection"] = service.connection_status()
    except JiraError as exc:
        context.update(_error_context(exc))
        context["executions"] = []
        context["connection"] = {"ok": False, "message": str(exc)}
    return render(request, "dashboard/executions.html", context)


@require_GET
@ensure_csrf_cookie
def execution_detail(request, key: str):
    service = get_service()
    section = request.GET.get("section", "")
    case_filters = _case_filters(request)
    tech = _tech(request)
    page = int(request.GET.get("page") or 1)
    force_refresh = request.GET.get("refresh") == "1"

    context = {
        "page": "execution",
        "title": key,
        "execution_key": key,
        "technology": tech,
    }
    try:
        data = service.get_execution_dashboard(
            execution_key=key,
            section_path=section,
            status_filter=case_filters["status"],
            search=case_filters["search"],
            technology=tech,
            page=page,
            force_refresh=force_refresh,
            assignees=case_filters["assignees"],
            linked_jira=case_filters["linked_jira"],
            priorities=case_filters["priorities"],
        )
        context.update(data)
        context["summary_json"] = json.dumps(data["summary"])
        context["overall_summary_json"] = json.dumps(
            data.get("overall_summary") or data.get("summary") or {}
        )
        context["status_colors_json"] = json.dumps(data["status_colors"])
        context["plan_executions"] = []
        context["enable_status_filters"] = True
        context["case_columns"] = EXECUTION_CASE_COLUMNS
        if request.GET.get("partial") == "cases":
            return render(request, "dashboard/_cases_partial.html", context)
    except Exception as exc:
        if isinstance(exc, JiraError):
            context.update(_error_context(exc))
        else:
            context["error"] = f"{type(exc).__name__}: {exc}"
        context.update(
            {
                "execution": {
                    "key": key,
                    "summary": "",
                    "url": f"{service.jira.base_url}/browse/{key}",
                },
                "sections": [],
                "cases": [],
                "summary": {
                    "counts": {},
                    "total": 0,
                    "passed": 0,
                    "failed": 0,
                    "todo": 0,
                    "pass_pct": 0,
                    "todo_pct": 0,
                    "chart": [],
                },
                "overall_summary": {"total": 0, "pass_pct": 0, "todo": 0, "chart": []},
                "defects": [],
                "coverage": {"rows": [], "total_sections": 0, "total_tests": 0},
                "section_name": "All Tests",
                "section_path": section,
                "case_count": 0,
                "total_cases": 0,
                "pagination": {
                    "page": 1,
                    "page_size": settings.UI_PAGE_SIZE,
                    "total_pages": 1,
                    "showing_from": 0,
                    "showing_to": 0,
                },
                "editable_statuses": list(EDITABLE_STATUSES),
                "filters": {
                    "status": case_filters["status"],
                    "search": case_filters["search"],
                    "technology": tech,
                    "assignees": case_filters["assignees"],
                    "linked_jira": case_filters["linked_jira"],
                    "priorities": case_filters["priorities"],
                    "qs": "",
                },
                "filter_options": {
                    "assignees": [],
                    "has_unassigned": False,
                    "priorities": [],
                },
                "summary_json": "{}",
                "overall_summary": {
                    "counts": {},
                    "total": 0,
                    "passed": 0,
                    "failed": 0,
                    "todo": 0,
                    "pass_pct": 0,
                    "todo_pct": 0,
                    "chart": [],
                },
                "overall_summary_json": "{}",
                "status_colors_json": "{}",
                "plan_executions": [],
            }
        )
    context["case_columns"] = EXECUTION_CASE_COLUMNS
    context["enable_status_filters"] = True
    # Partial nav must always get the fragment — never a full page HTML shell.
    if request.GET.get("partial") == "cases":
        return render(request, "dashboard/_cases_partial.html", context)
    return render(request, "dashboard/execution.html", context)


@require_GET
def plans(request):
    """Plan View: browse all plans with pass/fail/untested results bars."""
    service = get_service()
    query = request.GET.get("q", "")
    tech = _tech(request)
    stack = _stack(request)
    release = _release(request)
    context = {
        "page": "plans",
        "title": "Plan View",
        "query": query,
        "technology": tech,
        "stack_name": stack,
        "release_name": release,
    }
    try:
        plan_rows = service.list_test_plans(
            query=query, limit=50, stack_name=stack, release_name=release
        )
        # Instant bars for anything already cached; JS batches the rest.
        cached = service.get_cached_plan_status_summaries(
            [p.get("key") or "" for p in plan_rows]
        )
        for row in plan_rows:
            key = row.get("key") or ""
            row["results"] = cached.get(key)
        context["plans"] = plan_rows
        context["connection"] = service.connection_status()
    except JiraError as exc:
        context.update(_error_context(exc))
        context["plans"] = []
        context["connection"] = {"ok": False, "message": str(exc)}
    return render(request, "dashboard/plans.html", context)


@require_GET
@ensure_csrf_cookie
def plan_home(request):
    """Case Grid: pick a plan + Test Execution, then open the case table."""
    service = get_service()
    tech = _tech(request)
    stack = _stack(request)
    release = _release(request)
    plan_key = (request.GET.get("plan") or "").strip()
    execution_key = (request.GET.get("execution") or "").strip()

    # Plan + specific run → case grid for that execution.
    if plan_key and execution_key:
        return _redirect_with_params(
            f"/plans/{plan_key}/",
            technology=tech,
            stack=stack,
            release=release,
            execution=execution_key,
        )

    context = {
        "page": "case_grid",
        "title": "Case Grid",
        "technology": tech,
        "stack_name": stack,
        "release_name": release,
        "plan_key": plan_key,
        "selected_execution": execution_key,
        "recent_plans": [],
        "executions": [],
    }
    try:
        context["connection"] = service.connection_status()
    except JiraError as exc:
        context["connection"] = {"ok": False, "message": str(exc)}
    try:
        context["recent_plans"] = _plan_picker_options(
            service,
            plan_key,
            technology=tech,
            stack_name=stack,
            release_name=release,
        )
    except JiraError as exc:
        context.update(_error_context(exc))
        context["recent_plans"] = (
            [{"key": plan_key, "summary": ""}] if plan_key else []
        )
    if plan_key:
        try:
            context["executions"] = _plan_execution_options(service, plan_key)
        except JiraError as exc:
            context.update(_error_context(exc))
            context["executions"] = []
    return render(request, "dashboard/plan_home.html", context)


@require_GET
@ensure_csrf_cookie
def plan_detail(request, key: str):
    service = get_service()
    section = request.GET.get("section", "")
    case_filters = _case_filters(request)
    tech = _tech(request)
    stack = _stack(request)
    release = _release(request)
    execution_key = request.GET.get("execution", "")
    page = int(request.GET.get("page") or 1)
    force_refresh = request.GET.get("refresh") == "1"

    # Do not auto-pick a run — user selects the Test Execution explicitly.
    context = {
        "page": "case_grid",
        "title": key,
        "plan_key": key,
        "technology": tech,
        "stack_name": stack,
        "release_name": release,
        "recent_plans": [],
    }
    try:
        if not execution_key:
            # Landed without a run — send user back to the chooser (no heavy fetch).
            return _redirect_with_params(
                "/plan/",
                technology=tech,
                stack=stack,
                release=release,
                plan=key,
            )
        # Skip plan-picker + full execution list — run is already chosen.
        data = service.get_test_plan_dashboard(
            plan_key=key,
            section_path=section,
            status_filter=case_filters["status"],
            search=case_filters["search"],
            technology=tech,
            execution_key=execution_key,
            page=page,
            force_refresh=force_refresh,
            include_execution_list=False,
            assignees=case_filters["assignees"],
            linked_jira=case_filters["linked_jira"],
            priorities=case_filters["priorities"],
            stack_name=stack,
            release_name=release,
        )
        context.update(data)
        context.setdefault("selected_execution", execution_key)
        context["summary_json"] = json.dumps(data.get("summary") or {})
        context["overall_summary_json"] = json.dumps(
            data.get("overall_summary") or data.get("summary") or {}
        )
        context["status_colors_json"] = json.dumps(
            data.get("status_colors") or {}
        )
        context["enable_status_filters"] = True
        if request.GET.get("partial") == "cases":
            context["case_columns"] = PLAN_CASE_COLUMNS
            return render(request, "dashboard/_cases_partial.html", context)
    except Exception as exc:
        if isinstance(exc, JiraError):
            context.update(_error_context(exc))
        else:
            context["error"] = f"{type(exc).__name__}: {exc}"
        context.update(
            {
                "plan": {
                    "key": key,
                    "summary": "",
                    "url": f"{service.jira.base_url}/browse/{key}",
                },
                "executions": [],
                "sections": [],
                "cases": [],
                "summary": {
                    "counts": {},
                    "total": 0,
                    "passed": 0,
                    "failed": 0,
                    "todo": 0,
                    "pass_pct": 0,
                    "todo_pct": 0,
                    "chart": [],
                },
                "overall_summary": {
                    "total": 0,
                    "pass_pct": 0,
                    "todo": 0,
                    "chart": [],
                },
                "defects": [],
                "coverage": {
                    "rows": [],
                    "total_sections": 0,
                    "total_tests": 0,
                },
                "section_name": "All Tests",
                "section_path": section,
                "selected_execution": execution_key,
                "case_count": 0,
                "total_cases": 0,
                "pagination": {
                    "page": 1,
                    "page_size": settings.UI_PAGE_SIZE,
                    "total_pages": 1,
                    "showing_from": 0,
                    "showing_to": 0,
                },
                "editable_statuses": list(EDITABLE_STATUSES),
                "filters": {
                    "status": case_filters["status"],
                    "search": case_filters["search"],
                    "technology": tech,
                    "assignees": case_filters["assignees"],
                    "linked_jira": case_filters["linked_jira"],
                    "priorities": case_filters["priorities"],
                    "qs": "",
                },
                "filter_options": {
                    "assignees": [],
                    "has_unassigned": False,
                    "priorities": [],
                },
                "summary_json": "{}",
                "overall_summary_json": "{}",
                "status_colors_json": "{}",
            }
        )
    context["case_columns"] = PLAN_CASE_COLUMNS
    context["enable_status_filters"] = True
    # Partial nav must always get the fragment — never a full page HTML shell.
    if request.GET.get("partial") == "cases":
        return render(request, "dashboard/_cases_partial.html", context)
    return render(request, "dashboard/plan.html", context)


@require_GET
@ensure_csrf_cookie
def results_update(request):
    """Dedicated page for HTML/ZIP PASS-only results import."""
    service = get_service()
    tech = _tech(request)
    stack = _stack(request)
    release = _release(request)
    plan_key = (request.GET.get("plan") or "").strip()
    execution_key = (request.GET.get("execution") or "").strip()
    context = {
        "page": "results_update",
        "title": "Results Update",
        "plan_key": plan_key,
        "technology": tech,
        "stack_name": stack,
        "release_name": release,
        "selected_execution": execution_key,
        "executions": [],
        "recent_plans": [],
        "custom_fields": [],
        "custom_fields_json": "[]",
    }
    # Fast first paint: seed dropdowns locally; field IDs load async via API.
    from .testrun_fields import empty_field_catalog

    context["custom_fields"] = empty_field_catalog()
    context["custom_fields_json"] = json.dumps(context["custom_fields"])
    context["custom_fields_meta"] = {"mapped_ids": 0, "discovered_from": []}
    try:
        try:
            context["recent_plans"] = _plan_picker_options(
                service,
                plan_key,
                technology=tech,
                stack_name=stack,
                release_name=release,
            )
        except JiraError:
            context["recent_plans"] = (
                [{"key": plan_key, "summary": ""}] if plan_key else []
            )
        executions = _plan_execution_options(service, plan_key) if plan_key else []
        context["executions"] = executions
        # Cache-only on render (no network probe). Async JS loads/refreshes IDs.
        cached = service.get_test_run_custom_field_catalog(
            execution_key or "", cache_only=True
        )
        if cached.get("mapped_ids"):
            context["custom_fields"] = cached.get("fields") or context["custom_fields"]
            context["custom_fields_json"] = json.dumps(context["custom_fields"])
            context["custom_fields_meta"] = {
                "mapped_ids": cached.get("mapped_ids", 0),
                "discovered_from": cached.get("discovered_from") or [],
            }
        if execution_key:
            cases = service.load_execution_cases(execution_key, technology=tech)
            overall = service._summarize_statuses(cases)
            context["overall_summary"] = (
                overall.to_dict() if hasattr(overall, "to_dict") else overall
            )
            context["overall_summary_json"] = json.dumps(context["overall_summary"])
    except JiraError as exc:
        context.update(_error_context(exc))
        context["executions"] = []
    if "overall_summary" not in context:
        context["overall_summary"] = {
            "counts": {},
            "total": 0,
            "passed": 0,
            "failed": 0,
            "todo": 0,
            "pass_pct": 0,
            "todo_pct": 0,
            "chart": [],
        }
        context["overall_summary_json"] = json.dumps(context["overall_summary"])
    return render(request, "dashboard/results_update.html", context)


@require_GET
def tests(request):
    service = get_service()
    folder = request.GET.get("folder", "")
    search = request.GET.get("search", "")
    tech = _tech(request)
    context = {
        "page": "tests",
        "title": "Test Repository",
        "folder": folder,
        "search": search,
        "technology": tech,
    }
    try:
        data = service.get_repository_tests(
            folder_hint=folder, search=search, technology=tech, limit=200
        )
        context.update(data)
        context["connection"] = service.connection_status()
    except JiraError as exc:
        context.update(_error_context(exc))
        context.update({"tests": [], "sections": [], "count": 0, "jql": ""})
        context["connection"] = {"ok": False, "message": str(exc)}
    return render(request, "dashboard/tests.html", context)


@require_GET
def coverage(request):
    plan = request.GET.get("plan")
    key = request.GET.get("execution")
    tech = _tech(request)
    service = get_service()

    if plan:
        context = {
            "page": "coverage",
            "title": "Coverage",
            "plan_key": plan,
            "technology": tech,
        }
        try:
            data = service.get_test_plan_dashboard(plan_key=plan, technology=tech)
            context["execution"] = data["plan"]
            context["coverage"] = data["coverage"]
            context["summary"] = data["summary"]
        except JiraError as exc:
            context.update(_error_context(exc))
            context["coverage"] = {"rows": [], "total_sections": 0, "total_tests": 0}
            context["execution"] = {"key": plan}
        return render(request, "dashboard/coverage.html", context)

    if not key:
        try:
            executions = service.list_test_executions(limit=1)
            if executions:
                return redirect(
                    f"/coverage/?execution={executions[0]['key']}&technology={tech}"
                )
        except JiraError:
            pass
        return render(
            request,
            "dashboard/coverage.html",
            {
                "page": "coverage",
                "title": "Coverage",
                "coverage": {"rows": [], "total_sections": 0, "total_tests": 0},
                "execution": None,
                "technology": tech,
                "error": "Select a Test Plan or Test Execution to view coverage.",
            },
        )

    context = {
        "page": "coverage",
        "title": "Coverage",
        "execution_key": key,
        "technology": tech,
    }
    try:
        data = service.get_execution_dashboard(execution_key=key, technology=tech)
        context["execution"] = data["execution"]
        context["coverage"] = data["coverage"]
        context["summary"] = data["summary"]
    except JiraError as exc:
        context.update(_error_context(exc))
        context["coverage"] = {"rows": [], "total_sections": 0, "total_tests": 0}
        context["execution"] = {"key": key}
    return render(request, "dashboard/coverage.html", context)


@require_GET
def defects(request):
    plan = request.GET.get("plan")
    key = request.GET.get("execution")
    tech = _tech(request)
    service = get_service()

    if plan:
        context = {
            "page": "defects",
            "title": "Defects",
            "plan_key": plan,
            "technology": tech,
        }
        try:
            data = service.get_test_plan_dashboard(plan_key=plan, technology=tech)
            context["execution"] = data["plan"]
            context["defects"] = data["defects"]
            context["summary"] = data["summary"]
        except JiraError as exc:
            context.update(_error_context(exc))
            context["defects"] = []
            context["execution"] = {"key": plan}
        return render(request, "dashboard/defects.html", context)

    if not key:
        try:
            executions = service.list_test_executions(limit=1)
            if executions:
                return redirect(
                    f"/defects/?execution={executions[0]['key']}&technology={tech}"
                )
        except JiraError:
            pass
        return render(
            request,
            "dashboard/defects.html",
            {
                "page": "defects",
                "title": "Defects",
                "defects": [],
                "execution": None,
                "technology": tech,
                "error": "Select a Test Plan or Test Execution to view linked defects.",
            },
        )

    context = {
        "page": "defects",
        "title": "Defects",
        "execution_key": key,
        "technology": tech,
    }
    try:
        data = service.get_execution_dashboard(execution_key=key, technology=tech)
        context["execution"] = data["execution"]
        context["defects"] = data["defects"]
        context["summary"] = data["summary"]
    except JiraError as exc:
        context.update(_error_context(exc))
        context["defects"] = []
        context["execution"] = {"key": key}
    return render(request, "dashboard/defects.html", context)


@require_GET
def api_execution(request, key: str):
    service = get_service()
    case_filters = _case_filters(request)
    try:
        data = service.get_execution_dashboard(
            execution_key=key,
            section_path=request.GET.get("section", ""),
            status_filter=case_filters["status"],
            search=case_filters["search"],
            technology=_tech(request),
            assignees=case_filters["assignees"],
            linked_jira=case_filters["linked_jira"],
            priorities=case_filters["priorities"],
        )
        return JsonResponse(data)
    except JiraError as exc:
        return JsonResponse(_error_context(exc), status=exc.status_code or 502)


@require_GET
def api_execution_summary(request, key: str):
    """Lightweight overall status summary for pie/chip refresh without full page reload."""
    service = get_service()
    tech = _tech(request)
    force_refresh = request.GET.get("refresh") == "1"
    try:
        if force_refresh:
            service._bust_execution_case_cache(key)
        cases = service.load_execution_cases(
            key, technology=tech, force_refresh=force_refresh
        )
        overall = service._summarize_statuses(cases)
        payload = overall.to_dict() if hasattr(overall, "to_dict") else overall
        return JsonResponse({"overall_summary": payload, "execution": key})
    except JiraError as exc:
        return JsonResponse(_error_context(exc), status=exc.status_code or 502)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": str(exc)}, status=400)


@require_GET
def api_plan(request, key: str):
    service = get_service()
    case_filters = _case_filters(request)
    try:
        data = service.get_test_plan_dashboard(
            plan_key=key,
            section_path=request.GET.get("section", ""),
            status_filter=case_filters["status"],
            search=case_filters["search"],
            technology=_tech(request),
            execution_key=request.GET.get("execution", ""),
            assignees=case_filters["assignees"],
            linked_jira=case_filters["linked_jira"],
            priorities=case_filters["priorities"],
            stack_name=_stack(request),
            release_name=_release(request),
        )
        return JsonResponse(data)
    except JiraError as exc:
        return JsonResponse(_error_context(exc), status=exc.status_code or 502)


@require_GET
def api_plan_status_summary(request, key: str):
    """Pass / Fail / Untested rollup for one plan (Plan View Results column)."""
    service = get_service()
    force_refresh = request.GET.get("refresh") == "1"
    try:
        data = service.get_plan_status_summary(key, force_refresh=force_refresh)
        return JsonResponse({"ok": True, **data})
    except JiraError as exc:
        return JsonResponse(_error_context(exc), status=exc.status_code or 502)


@require_GET
def api_plan_status_summaries(request):
    """Batch pass/fail/untested bars for many plans (one round-trip)."""
    service = get_service()
    raw = (request.GET.get("keys") or "").strip()
    keys = [k.strip() for k in raw.replace(";", ",").split(",") if k.strip()]
    # Cap to keep the request bounded.
    keys = keys[:60]
    force_refresh = request.GET.get("refresh") == "1"
    if not keys:
        return JsonResponse({"ok": True, "summaries": {}})
    try:
        summaries = service.get_plan_status_summaries(
            keys, force_refresh=force_refresh, max_workers=8
        )
        return JsonResponse({"ok": True, "summaries": summaries})
    except JiraError as exc:
        return JsonResponse(_error_context(exc), status=exc.status_code or 502)


@require_GET
def api_health(request):
    service = get_service()
    status = service.connection_status()
    return JsonResponse(status, status=200 if status.get("ok") else 503)


@require_POST
def api_update_status(request, run_id: str):
    """Mark an individual test run status in Xray (optional defect keys on FAIL)."""
    service = get_service()
    try:
        payload = json_lib.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        payload = {}
    status = payload.get("status") or request.POST.get("status", "")
    execution_key = payload.get("execution") or request.POST.get("execution", "")
    defects = payload.get("defects")
    if defects is None:
        defects = request.POST.get("defects", "")
    custom_fields = payload.get("custom_fields") or payload.get("customFields")
    try:
        result = service.update_case_status(
            run_id,
            status,
            execution_key=execution_key,
            defects=defects,
            custom_fields=custom_fields,
        )
        # 200 even when status saved but defect link failed (see defect_error).
        return JsonResponse(result, status=200 if result.get("ok") else 207)
    except JiraError as exc:
        return JsonResponse(_error_context(exc), status=exc.status_code or 502)


@require_POST
def api_bulk_update_status(request):
    """Bulk-mark selected test run statuses in Xray (optional shared defect keys)."""
    service = get_service()
    try:
        payload = json_lib.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        payload = {}
    status = payload.get("status") or ""
    execution_key = payload.get("execution") or ""
    run_ids = payload.get("run_ids") or []
    defects = payload.get("defects")
    custom_fields = payload.get("custom_fields") or payload.get("customFields")
    if not isinstance(run_ids, list) or not run_ids:
        return JsonResponse({"error": "run_ids is required"}, status=400)
    if not status:
        return JsonResponse({"error": "status is required"}, status=400)
    try:
        result = service.update_case_statuses_bulk(
            run_ids=run_ids,
            status=status,
            execution_key=execution_key,
            defects=defects,
            custom_fields=custom_fields,
        )
        return JsonResponse(result, status=200 if result.get("ok") else 207)
    except JiraError as exc:
        return JsonResponse(_error_context(exc), status=exc.status_code or 502)


@require_POST
def api_add_defects(request, run_id: str):
    """Link Jira issue key(s) to a Test Run (Xray Execution Defects — associate by ID)."""
    service = get_service()
    try:
        payload = json_lib.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        payload = {}
    defects = payload.get("defects")
    if defects is None:
        defects = payload.get("keys") or request.POST.get("defects", "")
    execution_key = payload.get("execution") or request.POST.get("execution", "")
    try:
        result = service.add_case_defects(
            run_id, defects=defects, execution_key=execution_key
        )
        return JsonResponse(result)
    except JiraError as exc:
        return JsonResponse(_error_context(exc), status=exc.status_code or 502)


@require_POST
def api_bulk_add_defects(request):
    """Link the same Jira issue key(s) to many selected Test Runs."""
    service = get_service()
    try:
        payload = json_lib.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        payload = {}
    run_ids = payload.get("run_ids") or []
    defects = payload.get("defects")
    if defects is None:
        defects = payload.get("keys") or ""
    execution_key = payload.get("execution") or ""
    if not isinstance(run_ids, list) or not run_ids:
        return JsonResponse({"error": "run_ids is required"}, status=400)
    try:
        result = service.add_case_defects_bulk(
            run_ids=run_ids, defects=defects, execution_key=execution_key
        )
        return JsonResponse(result, status=200 if result.get("ok") else 207)
    except JiraError as exc:
        return JsonResponse(_error_context(exc), status=exc.status_code or 502)


@require_GET
def api_issue_search(request):
    """Search Jira issues by key/text for the Execution Defects picker."""
    service = get_service()
    query = (request.GET.get("q") or request.GET.get("query") or "").strip()
    try:
        limit = int(request.GET.get("limit") or 20)
    except (TypeError, ValueError):
        limit = 20
    try:
        issues = service.search_issues_for_defect_picker(query, limit=max(1, min(limit, 40)))
        return JsonResponse({"ok": True, "query": query, "issues": issues})
    except JiraError as exc:
        return JsonResponse(_error_context(exc), status=exc.status_code or 502)


@require_POST
def api_update_assignee(request, run_id: str):
    """Assign a Test Run to a Jira user (Xray Assignee column)."""
    service = get_service()
    try:
        payload = json_lib.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        payload = {}
    user = payload.get("user") or payload.get("assignee") or request.POST.get("user", "")
    execution_key = payload.get("execution") or request.POST.get("execution", "")
    try:
        result = service.update_case_assignee(run_id, user, execution_key=execution_key)
        return JsonResponse(result)
    except JiraError as exc:
        return JsonResponse(_error_context(exc), status=exc.status_code or 502)


@require_POST
def api_bulk_update_assignee(request):
    """Bulk-assign selected Test Runs to a Jira user."""
    service = get_service()
    try:
        payload = json_lib.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        payload = {}
    user = payload.get("user") or payload.get("assignee") or ""
    execution_key = payload.get("execution") or ""
    run_ids = payload.get("run_ids") or []
    if not isinstance(run_ids, list) or not run_ids:
        return JsonResponse({"error": "run_ids is required"}, status=400)
    if not str(user).strip():
        return JsonResponse({"error": "user is required"}, status=400)
    try:
        result = service.update_case_assignees_bulk(
            run_ids=run_ids, user=user, execution_key=execution_key
        )
        return JsonResponse(result, status=200 if result.get("ok") else 207)
    except JiraError as exc:
        return JsonResponse(_error_context(exc), status=exc.status_code or 502)


@require_GET
def api_user_search(request):
    """Search Jira users for the assignee picker."""
    service = get_service()
    query = (request.GET.get("q") or request.GET.get("query") or "").strip()
    try:
        return JsonResponse({"ok": True, "users": service.search_assignee_users(query)})
    except JiraError as exc:
        return JsonResponse(_error_context(exc), status=exc.status_code or 502)


@require_GET
def api_plan_resolve(request):
    """Resolve a Test Plan by key or summary/name (scoped by stack + release)."""
    service = get_service()
    query = (request.GET.get("q") or request.GET.get("plan") or "").strip()
    stack = _stack(request)
    release = _release(request)
    try:
        plan = service.resolve_plan_ref(
            query, stack_name=stack, release_name=release
        )
        return JsonResponse({"ok": True, **plan})
    except JiraError as exc:
        return JsonResponse(_error_context(exc), status=exc.status_code or 404)


def _html_import_inputs(request) -> tuple[str, list[str], list[tuple[str, bytes]], str, bool]:
    content_type = (request.content_type or "").lower()
    if "multipart/form-data" in content_type or request.FILES:
        execution = (request.POST.get("execution") or "").strip()
        technology = request.POST.get("technology", settings.DEFAULT_TECHNOLOGY)
        only_changed = (request.POST.get("only_changed") or "1") not in {"0", "false", "False"}
        folder_raw = (request.POST.get("folder_path") or "").strip()
        folder_paths = [p.strip() for p in folder_raw.splitlines() if p.strip()]
        if not folder_paths and request.POST.get("path"):
            folder_paths = [request.POST.get("path").strip()]
        uploaded = []
        seen_names: set[str] = set()
        for field_name in ("files", "file", "folder_files"):
            for f in request.FILES.getlist(field_name):
                name = getattr(f, "name", "upload.htm") or "upload.htm"
                # Lightweight request-level skip; content-hash dedupe happens in service.
                key = f"{name}:{getattr(f, 'size', 0)}"
                if key in seen_names:
                    continue
                seen_names.add(key)
                uploaded.append((name, f.read()))
        return execution, folder_paths, uploaded, technology, only_changed

    try:
        payload = json_lib.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        payload = {}
    execution = (payload.get("execution") or "").strip()
    technology = payload.get("technology", settings.DEFAULT_TECHNOLOGY)
    only_changed = payload.get("only_changed", True)
    folder_paths = payload.get("folder_paths") or payload.get("paths") or []
    if isinstance(folder_paths, str):
        folder_paths = [p.strip() for p in folder_paths.splitlines() if p.strip()]
    single = (payload.get("folder_path") or payload.get("path") or "").strip()
    if single:
        folder_paths = list(folder_paths) + [single]
    return execution, list(folder_paths), [], technology, bool(only_changed)


@require_POST
def api_html_import_preview(request):
    """Parse HTML reports and preview status updates for an execution."""
    service = get_service()
    execution, folder_paths, uploaded, technology, only_changed = _html_import_inputs(request)
    if not execution:
        return JsonResponse({"error": "execution is required"}, status=400)
    try:
        result = service.preview_html_import(
            execution_key=execution,
            folder_paths=folder_paths,
            uploaded_files=uploaded,
            technology=technology,
            only_changed=only_changed,
        )
        return JsonResponse(result)
    except JiraError as exc:
        return JsonResponse(_error_context(exc), status=exc.status_code or 400)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": str(exc)}, status=400)


def _start_pass_apply_response(request):
    """Start a background PASS apply job and return its id for progress polling."""
    from .apply_jobs import apply_job_public_view, start_pass_apply_job

    try:
        payload = json_lib.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        payload = {}
    execution = (payload.get("execution") or "").strip()
    updates = payload.get("updates") or []
    if not execution:
        return JsonResponse({"error": "execution is required"}, status=400)
    if not isinstance(updates, list) or not updates:
        return JsonResponse({"error": "updates is required"}, status=400)
    custom_field_values = payload.get("custom_fields") or payload.get("customFields") or {}
    try:
        job = start_pass_apply_job(
            execution=execution,
            updates=updates,
            custom_field_values=custom_field_values
            if isinstance(custom_field_values, dict)
            else {},
        )
        return JsonResponse(apply_job_public_view(job))
    except JiraError as exc:
        return JsonResponse(_error_context(exc), status=exc.status_code or 400)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": str(exc)}, status=400)


@require_POST
def api_html_import_apply(request):
    """Start HTML-import PASS updates (async; poll apply-jobs for progress)."""
    return _start_pass_apply_response(request)


@require_GET
def api_apply_job_status(request, job_id: str):
    """Poll Results Update apply job progress."""
    from .apply_jobs import apply_job_public_view, get_apply_job

    job = get_apply_job(job_id)
    if not job:
        return JsonResponse({"error": "Job not found"}, status=404)
    return JsonResponse(apply_job_public_view(job))


@require_GET
def api_results_update_fields(request):
    """Return discovered Test Run custom field catalog for Results Update."""
    service = get_service()
    execution = (request.GET.get("execution") or "").strip()
    force = (request.GET.get("refresh") or "") in {"1", "true", "True"}
    try:
        return JsonResponse(
            service.get_test_run_custom_field_catalog(
                execution, force_refresh=force
            )
        )
    except JiraError as exc:
        return JsonResponse(_error_context(exc), status=exc.status_code or 400)


@require_POST
def api_zip_import_preview(request):
    """Parse one or more ZIPs of HTML reports and preview PASS-only updates."""
    service = get_service()
    execution = (request.POST.get("execution") or "").strip()
    zip_files: list[tuple[str, bytes]] = []
    seen: set[str] = set()
    for field_name in ("zips", "zip", "files", "file", "folder_files"):
        for upload in request.FILES.getlist(field_name):
            name = getattr(upload, "name", "upload.zip") or "upload.zip"
            key = f"{name}:{getattr(upload, 'size', 0)}"
            if key in seen:
                continue
            seen.add(key)
            zip_files.append((name, upload.read()))
    if not execution:
        return JsonResponse({"error": "execution is required"}, status=400)
    if not zip_files:
        return JsonResponse({"error": "ZIP file is required"}, status=400)
    try:
        result = service.preview_zip_pass_import(
            execution_key=execution,
            zip_files=zip_files,
        )
        return JsonResponse(result)
    except JiraError as exc:
        return JsonResponse(_error_context(exc), status=exc.status_code or 400)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": str(exc)}, status=400)


@require_POST
def api_zip_import_apply(request):
    """Start ZIP-import PASS updates (async; poll apply-jobs for progress)."""
    return _start_pass_apply_response(request)


@require_POST
def api_excel_import_preview(request):
    """Parse an OverAllStatus Excel report and preview PASS-only updates."""
    service = get_service()
    execution = (request.POST.get("execution") or "").strip()
    upload = request.FILES.get("excel") or request.FILES.get("file") or request.FILES.get("xlsx")
    if not execution:
        return JsonResponse({"error": "execution is required"}, status=400)
    if not upload:
        return JsonResponse({"error": "Excel file is required"}, status=400)
    try:
        result = service.preview_excel_pass_import(
            execution_key=execution,
            excel_bytes=upload.read(),
            excel_name=getattr(upload, "name", "upload.xlsx") or "upload.xlsx",
        )
        return JsonResponse(result)
    except JiraError as exc:
        return JsonResponse(_error_context(exc), status=exc.status_code or 400)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": str(exc)}, status=400)


@require_POST
def api_excel_import_apply(request):
    """Start Excel-import PASS updates (async; poll apply-jobs for progress)."""
    return _start_pass_apply_response(request)


@require_POST
def api_failure_triage_download(request):
    """Download Failure triage Excel built from the last import preview rows."""
    service = get_service()
    try:
        payload = json_lib.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        payload = {}
    execution = (payload.get("execution") or "").strip()
    failures = payload.get("failures") or []
    unmatched = payload.get("unmatched_failures") or []
    todo_cases = payload.get("todo_cases") or []
    if not execution:
        return JsonResponse({"error": "execution is required"}, status=400)
    if not isinstance(failures, list):
        return JsonResponse({"error": "failures must be a list"}, status=400)
    if not isinstance(unmatched, list):
        unmatched = []
    if not isinstance(todo_cases, list):
        todo_cases = []
    if not failures and not unmatched and not todo_cases:
        return JsonResponse({"error": "No triage rows to download"}, status=400)
    try:
        data = service.build_failure_triage_xlsx(
            execution_key=execution,
            failures=failures,
            unmatched_failures=unmatched,
            todo_cases=todo_cases,
        )
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in execution)
        return _xlsx_response(data, f"{safe}_failure_triage.xlsx")
    except JiraError as exc:
        return JsonResponse(_error_context(exc), status=exc.status_code or 400)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": str(exc)}, status=400)


def _xlsx_response(data: bytes, filename: str) -> HttpResponse:
    response = HttpResponse(
        data,
        content_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@require_GET
def export_execution_xlsx(request, key: str):
    """Download the selected Test Execution as an Excel workbook."""
    service = get_service()
    section = request.GET.get("section", "")
    case_filters = _case_filters(request)
    # Full run by default; pass technology=... only when explicitly requested.
    tech = (request.GET.get("technology") or "").strip()
    if request.GET.get("all") in {"1", "true", "yes"}:
        tech = ""
    force_refresh = request.GET.get("refresh") == "1"
    include_steps = request.GET.get("steps", "1") not in {"0", "false", "no"}
    try:
        data = service.export_execution_xlsx(
            execution_key=key,
            section_path=section,
            status_filter=case_filters["status"],
            search=case_filters["search"],
            technology=tech,
            force_refresh=force_refresh,
            include_steps=include_steps,
            assignees=case_filters["assignees"],
            linked_jira=case_filters["linked_jira"],
            priorities=case_filters["priorities"],
        )
    except JiraError as exc:
        return JsonResponse(_error_context(exc), status=exc.status_code or 400)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": str(exc)}, status=400)

    safe_key = "".join(c if c.isalnum() or c in "-_" else "_" for c in key) or "execution"
    return _xlsx_response(data, f"{safe_key}_cases.xlsx")


@require_GET
def export_fail_jira_summary_xlsx(request, key: str):
    """Download triage-style Jira summary for FAIL cases in a Test Execution."""
    service = get_service()
    tech = (request.GET.get("technology") or "").strip()
    if request.GET.get("all") in {"1", "true", "yes"}:
        tech = ""
    force_refresh = request.GET.get("refresh") == "1"
    try:
        data = service.export_fail_jira_summary_xlsx(
            execution_key=key,
            technology=tech,
            force_refresh=force_refresh,
        )
    except JiraError as exc:
        return JsonResponse(_error_context(exc), status=exc.status_code or 400)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": str(exc)}, status=400)

    safe_key = "".join(c if c.isalnum() or c in "-_" else "_" for c in key) or "execution"
    return _xlsx_response(data, f"{safe_key}_fail_jira_summary.xlsx")


@require_GET
def export_plan_xlsx(request, key: str):
    """Download all Test Executions under a Test Plan as one Excel workbook."""
    service = get_service()
    tech = (request.GET.get("technology") or "").strip()
    if request.GET.get("all") in {"1", "true", "yes"}:
        tech = ""
    force_refresh = request.GET.get("refresh") == "1"
    # Steps are expensive across many runs — off unless explicitly requested.
    include_steps = request.GET.get("steps") in {"1", "true", "yes"}
    try:
        data = service.export_plan_xlsx(
            plan_key=key,
            technology=tech,
            force_refresh=force_refresh,
            include_steps=include_steps,
        )
    except JiraError as exc:
        return JsonResponse(_error_context(exc), status=exc.status_code or 400)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": str(exc)}, status=400)

    safe_key = "".join(c if c.isalnum() or c in "-_" else "_" for c in key) or "plan"
    return _xlsx_response(data, f"{safe_key}_all_executions.xlsx")


@require_POST
def api_plan_export_start(request, key: str):
    """Start a background plan Excel export and return a job id for progress polling."""
    from .export_jobs import job_public_view, start_plan_export_job

    try:
        payload = json_lib.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        payload = {}
    tech = (payload.get("technology") or request.POST.get("technology") or "").strip()
    if payload.get("all") in {1, "1", True, "true", "yes"} or request.POST.get("all") in {
        "1",
        "true",
        "yes",
    }:
        tech = ""
    force_refresh = str(payload.get("refresh") or request.POST.get("refresh") or "") in {
        "1",
        "true",
        "yes",
    }
    include_steps = str(payload.get("steps") or request.POST.get("steps") or "") in {
        "1",
        "true",
        "yes",
    }
    if not (key or "").strip():
        return JsonResponse({"error": "plan is required"}, status=400)
    job = start_plan_export_job(
        plan_key=key.strip(),
        technology=tech,
        force_refresh=force_refresh,
        include_steps=include_steps,
    )
    return JsonResponse(job_public_view(job))


@require_GET
def api_export_job_status(request, job_id: str):
    from .export_jobs import get_job, job_public_view

    job = get_job(job_id)
    if not job:
        return JsonResponse({"error": "Job not found or expired"}, status=404)
    return JsonResponse(job_public_view(job))


@require_GET
def api_export_job_download(request, job_id: str):
    from pathlib import Path

    from django.http import FileResponse

    from .export_jobs import get_job

    job = get_job(job_id)
    if not job:
        return JsonResponse({"error": "Job not found or expired"}, status=404)
    if job.get("status") != "done":
        return JsonResponse({"error": "Export is not ready yet"}, status=409)
    path = Path(job.get("path") or "")
    if not path.is_file():
        return JsonResponse({"error": "Export file missing"}, status=404)
    filename = job.get("filename") or path.name
    response = FileResponse(
        path.open("rb"),
        as_attachment=True,
        filename=filename,
        content_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )
    return response


@require_POST
def api_export_job_cancel(request, job_id: str):
    """Request cancellation of a running plan Excel export job."""
    from .export_jobs import job_public_view, request_cancel_job

    # Always succeed from the UI's perspective (missing job ⇒ already stopped).
    job = request_cancel_job(job_id)
    return JsonResponse(job_public_view(job))
