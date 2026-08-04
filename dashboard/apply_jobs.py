"""Background Results Update apply jobs with progress tracking."""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from django.core.cache import cache

from .credentials import clear_request_credentials, get_active_credentials, set_request_credentials

_JOB_TTL = 60 * 60
_lock = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}


def _job_key(job_id: str) -> str:
    return f"apply_job:{job_id}"


def _save_job(job: dict[str, Any]) -> None:
    _JOBS[job["id"]] = job
    cache.set(_job_key(job["id"]), job, _JOB_TTL)


def get_apply_job(job_id: str) -> dict[str, Any] | None:
    data = _JOBS.get(job_id)
    if isinstance(data, dict):
        return data
    data = cache.get(_job_key(job_id))
    if isinstance(data, dict):
        _JOBS[job_id] = data
        return data
    return None


def _estimate_eta(job: dict[str, Any]) -> int | None:
    total = int(job.get("total") or 0)
    done = int(job.get("done") or 0)
    started = float(job.get("started_at") or 0)
    if total <= 0 or done <= 0 or started <= 0:
        return None
    elapsed = max(0.1, time.time() - started)
    rate = done / elapsed
    remaining = max(0, total - done)
    if rate <= 0:
        return None
    return int(remaining / rate) + 2


def update_apply_job(job_id: str, **fields: Any) -> dict[str, Any] | None:
    with _lock:
        job = get_apply_job(job_id)
        if not job:
            return None
        job.update(fields)
        job["updated_at"] = time.time()
        job["eta_seconds"] = _estimate_eta(job)
        total = int(job.get("total") or 0)
        done = int(job.get("done") or 0)
        if job.get("status") == "done":
            job["percent"] = 100
        elif job.get("status") == "error":
            pass
        elif total > 0:
            job["percent"] = min(99, int((done / total) * 100))
        else:
            job["percent"] = int(job.get("percent") or 0)
        left = max(0, total - done)
        job["left"] = left
        _save_job(job)
        return job


def _run_pass_apply(
    service,
    *,
    execution: str,
    updates: list[dict[str, Any]],
    custom_field_values: dict[str, Any] | None,
    progress_cb: Any | None = None,
) -> dict[str, Any]:
    """Prepare custom fields and apply PASS updates (shared by sync API + jobs)."""
    catalog_data = service.get_test_run_custom_field_catalog(execution)
    if not catalog_data.get("mapped_ids"):
        catalog_data = service.get_test_run_custom_field_catalog(
            execution, force_refresh=True
        )
    catalog = catalog_data.get("fields") or []
    selected = custom_field_values if isinstance(custom_field_values, dict) else {}
    custom_fields_error = ""
    custom_fields: list = []
    skipped_fields: list = []
    if selected:
        custom_fields, skipped_fields = service.build_custom_field_payload(
            selected, catalog
        )
        if skipped_fields:
            custom_fields_error = (
                "Skipped (no Xray field ID yet): "
                + ", ".join(skipped_fields)
                + ". Mapped fields were still posted when possible."
            )

    if callable(progress_cb):
        progress_cb(
            {
                "phase": "updating",
                "message": f"Updating 0/{len(updates)}…",
                "total": len(updates),
                "done": 0,
                "left": len(updates),
            }
        )

    result = service.apply_html_import(
        execution_key=execution,
        updates=updates,
        pass_only=True,
        custom_fields=custom_fields or None,
        progress_cb=progress_cb,
    )
    result["custom_fields_posted"] = len(custom_fields)
    result["custom_fields_selected"] = list(selected.keys()) if selected else []
    result["custom_fields_skipped"] = skipped_fields
    result["custom_field_ids"] = [item.get("id") for item in custom_fields]
    if selected and not custom_fields:
        custom_fields_error = (
            "Custom fields were selected but none had mapped Xray IDs "
            f"({', '.join(skipped_fields) or 'unknown'}). "
            "Send customFieldId from Network for those fields."
        )
        result["ok"] = False
    if custom_fields_error:
        result["custom_fields_error"] = custom_fields_error
        if custom_fields and skipped_fields:
            result["ok"] = result.get("ok", True)
        elif not custom_fields:
            result["ok"] = False
        result["remote_field_names"] = catalog_data.get("remote_field_names") or []
        result["probe_log"] = catalog_data.get("probe_log") or []
    return result


def start_pass_apply_job(
    *,
    execution: str,
    updates: list[dict[str, Any]],
    custom_field_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .services import get_service

    job_id = uuid.uuid4().hex
    now = time.time()
    total = len(updates or [])
    job = {
        "id": job_id,
        "kind": "pass_apply",
        "execution": execution,
        "status": "queued",
        "phase": "queued",
        "message": "Queued…",
        "current": "",
        "total": total,
        "done": 0,
        "left": total,
        "percent": 0,
        "eta_seconds": None,
        "error": "",
        "updated_count": 0,
        "failed_count": 0,
        "custom_fields_posted": 0,
        "custom_fields_error": "",
        "custom_fields_skipped": [],
        "result": None,
        "started_at": now,
        "updated_at": now,
    }
    _save_job(job)

    creds = get_active_credentials()
    selected = custom_field_values if isinstance(custom_field_values, dict) else {}
    updates_copy = list(updates or [])

    def _worker() -> None:
        set_request_credentials(
            creds.get("username") or "",
            creds.get("password") or "",
            creds.get("base_url") or "",
        )
        try:
            update_apply_job(
                job_id,
                status="running",
                phase="preparing",
                message="Preparing updates…",
                started_at=time.time(),
            )
            service = get_service()

            def on_progress(payload: dict[str, Any]) -> None:
                update_apply_job(job_id, **payload)

            result = _run_pass_apply(
                service,
                execution=execution,
                updates=updates_copy,
                custom_field_values=selected,
                progress_cb=on_progress,
            )
            final_total = int((get_apply_job(job_id) or {}).get("total") or total)
            update_apply_job(
                job_id,
                status="done",
                phase="done",
                message=(
                    f"Done — updated {result.get('updated_count', 0)}, "
                    f"failed {result.get('failed_count', 0)}"
                ),
                percent=100,
                done=final_total,
                left=0,
                eta_seconds=0,
                updated_count=result.get("updated_count") or 0,
                failed_count=result.get("failed_count") or 0,
                custom_fields_posted=result.get("custom_fields_posted") or 0,
                custom_fields_error=result.get("custom_fields_error") or "",
                custom_fields_skipped=result.get("custom_fields_skipped") or [],
                result={
                    "ok": result.get("ok"),
                    "updated_count": result.get("updated_count"),
                    "failed_count": result.get("failed_count"),
                    "failed": (result.get("failed") or [])[:20],
                    "custom_fields_posted": result.get("custom_fields_posted"),
                    "custom_fields_error": result.get("custom_fields_error"),
                    "custom_fields_skipped": result.get("custom_fields_skipped"),
                },
            )
        except Exception as exc:  # noqa: BLE001
            update_apply_job(
                job_id,
                status="error",
                phase="error",
                message="Update failed",
                error=str(exc),
                eta_seconds=None,
            )
        finally:
            clear_request_credentials()

    threading.Thread(target=_worker, name=f"apply-{job_id[:8]}", daemon=True).start()
    return job


def apply_job_public_view(job: dict[str, Any]) -> dict[str, Any]:
    total = int(job.get("total") or 0)
    done = int(job.get("done") or 0)
    return {
        "id": job.get("id"),
        "kind": job.get("kind"),
        "execution": job.get("execution"),
        "status": job.get("status"),
        "phase": job.get("phase"),
        "message": job.get("message"),
        "current": job.get("current"),
        "total": total,
        "done": done,
        "left": int(job.get("left") if job.get("left") is not None else max(0, total - done)),
        "percent": job.get("percent") or 0,
        "eta_seconds": job.get("eta_seconds"),
        "error": job.get("error") or "",
        "updated_count": job.get("updated_count") or 0,
        "failed_count": job.get("failed_count") or 0,
        "custom_fields_posted": job.get("custom_fields_posted") or 0,
        "custom_fields_error": job.get("custom_fields_error") or "",
        "custom_fields_skipped": job.get("custom_fields_skipped") or [],
        "result": job.get("result"),
    }
