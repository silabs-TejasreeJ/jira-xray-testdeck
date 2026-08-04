"""Background Excel export jobs with progress tracking."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.cache import cache

from .credentials import clear_request_credentials, get_active_credentials, set_request_credentials

_JOB_TTL = 60 * 60  # 1 hour
_EXPORT_DIR = Path(settings.BASE_DIR) / ".export_jobs"
_lock = threading.Lock()
# In-process store so threaded progress updates are always visible to pollers
# (LocMemCache alone can miss cross-thread updates under runserver).
_JOBS: dict[str, dict[str, Any]] = {}


class ExportCancelled(Exception):
    """Raised when a user cancels a running export job."""


def _job_key(job_id: str) -> str:
    return f"export_job:{job_id}"


def _job_path(job_id: str) -> Path:
    return _EXPORT_DIR / f"{job_id}.json"


def _write_job_disk(job: dict[str, Any]) -> None:
    """Persist job metadata so cancel/status survive Django runserver reloads."""
    try:
        _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        path = _job_path(str(job["id"]))
        tmp = path.with_suffix(".json.tmp")
        # Don't require path for public status; keep it for download.
        payload = dict(job)
        tmp.write_text(json.dumps(payload, default=str), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


def _read_job_disk(job_id: str) -> dict[str, Any] | None:
    path = _job_path(job_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and data.get("id") else None
    except Exception:
        return None


def _save_job(job: dict[str, Any]) -> None:
    _JOBS[job["id"]] = job
    cache.set(_job_key(job["id"]), job, _JOB_TTL)
    _write_job_disk(job)


def _mark_orphaned_if_needed(job: dict[str, Any]) -> dict[str, Any]:
    """If the server process restarted, in-memory workers are gone — fail the job."""
    status = job.get("status") or ""
    if status not in {"queued", "running", "cancelling"}:
        return job
    worker_pid = job.get("worker_pid")
    if worker_pid and int(worker_pid) != os.getpid():
        job["status"] = "error"
        job["phase"] = "error"
        job["message"] = "Export interrupted"
        job["error"] = "Server restarted during export. Please start the export again."
        job["eta_seconds"] = None
        job["updated_at"] = time.time()
        _save_job(job)
    return job


def get_job(job_id: str) -> dict[str, Any] | None:
    job_id = (job_id or "").strip()
    if not job_id:
        return None
    data = _JOBS.get(job_id)
    if isinstance(data, dict):
        return _mark_orphaned_if_needed(data)
    data = cache.get(_job_key(job_id))
    if isinstance(data, dict):
        _JOBS[job_id] = data
        return _mark_orphaned_if_needed(data)
    data = _read_job_disk(job_id)
    if isinstance(data, dict):
        _JOBS[job_id] = data
        cache.set(_job_key(job_id), data, _JOB_TTL)
        return _mark_orphaned_if_needed(data)
    return None


def is_cancel_requested(job_id: str) -> bool:
    # Always re-check disk so a cancel from a reloaded process is visible.
    job = get_job(job_id)
    if job and job.get("cancel_requested"):
        return True
    disk = _read_job_disk(job_id)
    return bool(disk and disk.get("cancel_requested"))


def request_cancel_job(job_id: str) -> dict[str, Any]:
    """Cancel immediately. If the job is already gone, return a cancelled stub."""
    job_id = (job_id or "").strip()
    with _lock:
        job = get_job(job_id)
        if not job:
            stub = {
                "id": job_id or "unknown",
                "kind": "plan",
                "status": "cancelled",
                "phase": "cancelled",
                "message": "Export cancelled",
                "current": "",
                "total": 0,
                "done": 0,
                "percent": 0,
                "eta_seconds": None,
                "error": "",
                "filename": "",
                "path": "",
                "cancel_requested": True,
                "updated_at": time.time(),
            }
            if job_id:
                _save_job(stub)
            return stub
        status = job.get("status") or ""
        if status in {"done", "error", "cancelled"}:
            # Still mark cancel so any late worker stops writing a file.
            if status != "done":
                job["cancel_requested"] = True
                if status != "cancelled":
                    job["status"] = "cancelled"
                    job["phase"] = "cancelled"
                    job["message"] = "Export cancelled"
                _save_job(job)
            return job
        job["cancel_requested"] = True
        job["status"] = "cancelled"
        job["phase"] = "cancelled"
        job["message"] = "Export cancelled"
        job["error"] = ""
        job["updated_at"] = time.time()
        job["eta_seconds"] = None
        _save_job(job)
        return job


def _estimate_eta(job: dict[str, Any]) -> int | None:
    if job.get("cancel_requested") or job.get("status") in {
        "cancelling",
        "cancelled",
    }:
        return None
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
    # Add a little buffer for workbook build.
    return int(remaining / rate) + (8 if done < total else 3)


def update_job(job_id: str, **fields: Any) -> dict[str, Any] | None:
    with _lock:
        job = get_job(job_id)
        if not job:
            return None
        # Don't let progress callbacks overwrite a terminal cancel/error/done.
        if job.get("status") in {"cancelled", "done", "error"} and "status" not in fields:
            return job
        # Once cancelled, ignore further progress updates from orphaned workers.
        if job.get("status") == "cancelled" and fields.get("status") != "cancelled":
            return job
        if job.get("cancel_requested") and fields.get("status") not in {
            "cancelled",
            "error",
            "done",
        }:
            return job
        job.update(fields)
        job["updated_at"] = time.time()
        job["eta_seconds"] = _estimate_eta(job)
        pct = 0
        total = int(job.get("total") or 0)
        done = int(job.get("done") or 0)
        phase = job.get("phase") or ""
        status = job.get("status") or ""
        if status == "done":
            pct = 100
        elif status == "cancelled":
            pct = min(99, int(job.get("percent") or 0))
        elif phase == "listing":
            pct = 2
        elif phase == "building":
            pct = 92 if total else 90
        elif total > 0:
            # Reserve ~8% for workbook build.
            pct = min(90, int((done / total) * 90) + 2)
        job["percent"] = pct
        _save_job(job)
        return job


def start_plan_export_job(
    *,
    plan_key: str,
    technology: str = "",
    force_refresh: bool = False,
    include_steps: bool = False,
) -> dict[str, Any]:
    from .services import get_service

    job_id = uuid.uuid4().hex
    now = time.time()
    job = {
        "id": job_id,
        "kind": "plan",
        "plan_key": plan_key,
        "status": "queued",
        "phase": "queued",
        "message": "Queued…",
        "current": "",
        "total": 0,
        "done": 0,
        "percent": 0,
        "eta_seconds": None,
        "error": "",
        "filename": "",
        "path": "",
        "cancel_requested": False,
        "worker_pid": os.getpid(),
        "started_at": now,
        "updated_at": now,
    }
    _save_job(job)

    creds = get_active_credentials()

    def _worker() -> None:
        set_request_credentials(
            creds.get("username") or "",
            creds.get("password") or "",
            creds.get("base_url") or "",
        )
        try:
            if is_cancel_requested(job_id):
                raise ExportCancelled("Export cancelled by user")

            update_job(
                job_id,
                status="running",
                phase="listing",
                message="Listing Test Executions…",
                started_at=time.time(),
                worker_pid=os.getpid(),
            )

            def on_progress(payload: dict[str, Any]) -> None:
                if is_cancel_requested(job_id):
                    raise ExportCancelled("Export cancelled by user")
                update_job(job_id, **payload)

            service = get_service()
            data = service.export_plan_xlsx(
                plan_key=plan_key,
                technology=technology,
                force_refresh=force_refresh,
                include_steps=include_steps,
                progress_cb=on_progress,
                is_cancelled=lambda: is_cancel_requested(job_id),
            )

            if is_cancel_requested(job_id):
                raise ExportCancelled("Export cancelled by user")

            update_job(
                job_id,
                phase="building",
                message="Writing Excel file…",
                percent=95,
            )
            _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in plan_key) or "plan"
            filename = f"{safe}_all_executions.xlsx"
            path = _EXPORT_DIR / f"{job_id}_{filename}"
            path.write_bytes(data)

            if is_cancel_requested(job_id):
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass
                raise ExportCancelled("Export cancelled by user")

            update_job(
                job_id,
                status="done",
                phase="done",
                message="Ready to download",
                percent=100,
                eta_seconds=0,
                filename=filename,
                path=str(path),
                done=int((get_job(job_id) or {}).get("total") or 0),
            )
        except ExportCancelled:
            update_job(
                job_id,
                status="cancelled",
                phase="cancelled",
                message="Export cancelled",
                error="",
                eta_seconds=None,
                cancel_requested=True,
            )
        except Exception as exc:  # noqa: BLE001
            if is_cancel_requested(job_id):
                update_job(
                    job_id,
                    status="cancelled",
                    phase="cancelled",
                    message="Export cancelled",
                    error="",
                    eta_seconds=None,
                )
            else:
                update_job(
                    job_id,
                    status="error",
                    phase="error",
                    message="Export failed",
                    error=str(exc),
                    eta_seconds=None,
                )
        finally:
            clear_request_credentials()

    threading.Thread(target=_worker, name=f"export-{job_id[:8]}", daemon=True).start()
    return job


def job_public_view(job: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe progress payload (no filesystem path)."""
    status = job.get("status")
    return {
        "id": job.get("id"),
        "kind": job.get("kind"),
        "plan_key": job.get("plan_key"),
        "status": status,
        "phase": job.get("phase"),
        "message": job.get("message"),
        "current": job.get("current"),
        "total": job.get("total") or 0,
        "done": job.get("done") or 0,
        "percent": job.get("percent") or 0,
        "eta_seconds": job.get("eta_seconds"),
        "error": job.get("error") or "",
        "filename": job.get("filename") or "",
        "cancel_requested": bool(job.get("cancel_requested")),
        "cancellable": status in {"queued", "running"},
        "download_ready": status == "done" and bool(job.get("path")),
    }
