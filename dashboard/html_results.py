"""Parse pytest-html (and similar) result documents for TestDeck import."""

from __future__ import annotations

import hashlib
import html as html_lib
import io
import re
import zipfile
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

# Full pytest-html result block (header row + optional extras/log row).
TBODY_RE = re.compile(
    r'<tbody class="([a-z]+) results-table-row">(.*?)</tbody>',
    re.IGNORECASE | re.DOTALL,
)
RESULT_RE = re.compile(
    r'<td class="col-result">(.*?)</td>', re.IGNORECASE | re.DOTALL
)
NAME_RE = re.compile(
    r'<td class="col-name">(.*?)</td>', re.IGNORECASE | re.DOTALL
)
LOG_RE = re.compile(r'<div class="log">(.*?)</div>', re.IGNORECASE | re.DOTALL)


def _cell_plain_text(raw: str) -> str:
    """Strip tags/entities from a table cell (pytest-html may nest spans)."""
    text = re.sub(r"<br\s*/?>", "\n", raw or "", flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return html_lib.unescape(text).replace("\xa0", " ").strip()

# Legacy fallback: header cells only (no extras/log).
ROW_RE = re.compile(
    r'<tbody class="([a-z]+) results-table-row">\s*<tr>\s*'
    r"(?:<td class=\"col-time\">[^<]*</td>\s*)?"
    r'<td class="col-result">([^<]+)</td>\s*'
    r'<td class="col-name">([^<]+)</td>',
    re.IGNORECASE,
)

# Case IDs embedded in node ids, e.g. ..._C769724[profiles0] or ..._c767047::setup
CID_RE = re.compile(
    r"(?:^|[_\-\.\[/])C(\d{4,})(?:$|[\]_\-\.:\[])|_C(\d{4,})\b|\bC(\d{5,})\b",
    re.IGNORECASE,
)

# Unix timestamp in filenames (seconds 10 digits, or ms 13 digits)
UNIX_TS_RE = re.compile(r"(?<!\d)(\d{10,13})(?!\d)")
# Roughly year 2000–2100 in seconds
_UNIX_TS_MIN = 946_684_800
_UNIX_TS_MAX = 4_102_444_800

HTML_STATUS_MAP = {
    "PASSED": "PASS",
    "PASS": "PASS",
    "XPASSED": "PASS",
    "FAILED": "FAIL",
    "FAIL": "FAIL",
    "ERROR": "FAIL",
    "XFAILED": "TODO",
    "SKIPPED": "TODO",
    "SKIP": "TODO",
    "RERUN": "TODO",
}

# Higher wins when the same case appears in multiple phases/rows
STATUS_RANK = {
    "FAIL": 40,
    "EXECUTING": 30,
    "BLOCKED": 25,
    "ABORTED": 20,
    "PASS": 15,
    "TODO": 10,
    "NA": 5,
}

PHASE_RANK = {
    "call": 30,
    "": 20,
    "setup": 10,
    "teardown": 5,
}

HTML_SUFFIXES = {".htm", ".html", ".HTM", ".HTML"}


@dataclass
class HtmlResultRow:
    source: str
    outcome_class: str
    result_text: str
    test_name: str
    test_src_map_id: str
    status: str
    phase: str = "call"
    key_error: str = ""
    explanation: str = ""
    failed_api: str = ""
    failed_command: str = ""
    status_code: str = ""
    failure_context: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ParsedHtmlReport:
    source: str
    rows: list[HtmlResultRow] = field(default_factory=list)
    by_map_id: dict[str, str] = field(default_factory=dict)
    winning_rows: dict[str, HtmlResultRow] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    timestamp: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "timestamp": self.timestamp,
            "row_count": len(self.rows),
            "mapped_count": len(self.by_map_id),
            "status_counts": _count_statuses(self.by_map_id.values()),
            "errors": self.errors,
        }


def normalize_map_id(value: str | None) -> str:
    raw = (value or "").strip().upper()
    if not raw:
        return ""
    m = re.search(r"C?(\d{4,})", raw)
    if m:
        return f"C{m.group(1)}"
    return raw


def html_result_to_xray(result_text: str, outcome_class: str = "") -> str:
    for raw in (result_text, outcome_class):
        key = (raw or "").strip().upper()
        if not key:
            continue
        mapped = HTML_STATUS_MAP.get(key)
        if mapped:
            return mapped
        # Noisy cells / variants: "Error: …", "Failed …"
        if key.startswith(("FAIL", "ERROR")):
            return "FAIL"
        if key.startswith("PASS"):
            return "PASS"
        if key.startswith(("SKIP", "XFAIL", "RERUN")):
            return "TODO"
    return "TODO"


def extract_map_id(test_name: str) -> str:
    m = CID_RE.search(test_name or "")
    if not m:
        return ""
    digits = next((g for g in m.groups() if g), "")
    return f"C{digits}" if digits else ""


def detect_phase(test_name: str) -> str:
    name = (test_name or "").rstrip()
    if name.endswith("::setup"):
        return "setup"
    if name.endswith("::teardown"):
        return "teardown"
    return "call"


def _log_html_to_text(raw: str, *, max_chars: int = 12000) -> str:
    """Convert pytest-html div.log inner HTML into plain text."""
    text = re.sub(r"<br\s*/?>", "\n", raw or "", flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_lib.unescape(text).replace("\xa0", " ").strip()
    if max_chars and len(text) > max_chars:
        # Keep both head (often has assert) and tail (final exception).
        head = max_chars // 2
        tail = max_chars - head
        text = text[:head] + "\n…\n" + text[-tail:]
    return text


_EXC_LINE_RE = re.compile(
    r"^(?:E\s+)?([A-Za-z_][\w\.]*(?:Error|Exception|Failure))\s*:\s*(.*)$"
)
_LOG_NOISE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}\s|\[(?:INFO|DEBUG|WARNING|WARN|ERROR)\]|site-packages|"
    r"^File |^Traceback|^During handling|^The above exception|^raise ",
    re.I,
)


def _primary_failure_chunk(log_text: str) -> str:
    """Prefer the root exception chunk before 'During handling of the above…'."""
    text = log_text or ""
    parts = re.split(
        r"\nDuring handling of the above exception[^\n]*\n",
        text,
        maxsplit=1,
        flags=re.I,
    )
    return parts[0] if parts else text


def _clean_reason_text(text: str) -> str:
    """Strip traceback headers / frames from a reason string."""
    raw = (text or "").strip()
    if not raw:
        return ""
    # Glued cases: "...status:-0x1Traceback (most recent call last):"
    raw = re.split(r"(?i)Traceback\s*\(most recent call last\)", raw, maxsplit=1)[0]
    raw = re.split(r"(?i)\nDuring handling of the above exception", raw, maxsplit=1)[0]
    cleaned: list[str] = []
    for ln in raw.splitlines():
        s = ln.strip()
        if not s:
            if cleaned:
                break
            continue
        if re.match(r'(?i)^File\s+"', s) or s.startswith("Traceback"):
            break
        cleaned.append(s)
    out = " ".join(cleaned).strip() if cleaned else raw.strip()
    out = re.sub(r"\s+", " ", out).strip()
    return out[:800]


def extract_key_error_from_log(log_text: str) -> str:
    """Pick a short failure reason from a pytest traceback / log blob."""
    primary = _primary_failure_chunk(log_text)
    lines = [ln.rstrip() for ln in primary.splitlines() if ln.strip()]
    if not lines:
        lines = [ln.rstrip() for ln in (log_text or "").splitlines() if ln.strip()]
    if not lines:
        return ""

    # 1) pytest "E   AssertionError: ..." lines (best signal)
    e_lines: list[str] = []
    for ln in lines:
        stripped = ln.lstrip()
        if stripped.startswith("E ") or stripped.startswith("E\t"):
            e_lines.append(stripped[1:].strip())
    for ln in reversed(e_lines):
        if re.search(r"(Error|Exception|Failure|Failed|assert)\b", ln, re.I):
            return _clean_reason_text(ln)
    if e_lines:
        return _clean_reason_text(e_lines[-1])

    # 2) Any Exception/AssertionError line — prefer first AssertionError in root chunk
    exc_hits: list[str] = []
    for ln in lines:
        m = _EXC_LINE_RE.match(ln.strip())
        if m:
            exc_hits.append(f"{m.group(1)}: {m.group(2)}".strip()[:800])
    if exc_hits:
        for ln in exc_hits:
            if ln.startswith("AssertionError"):
                return _clean_reason_text(ln)
        return _clean_reason_text(exc_hits[-1])

    # 3) Last non-noise line
    for ln in reversed(lines):
        s = ln.strip()
        if _LOG_NOISE_RE.search(s):
            continue
        return _clean_reason_text(s)
    return _clean_reason_text(lines[-1])


_TB_FRAME_RE = re.compile(
    r'File\s+"([^"]+)",\s+line\s+(\d+),\s+in\s+([A-Za-z_][\w]*)'
)
# Examples: "TX t 0 A wifi.init", "TX: t 1 B ble_get_device_state"
_TX_CMD_RE = re.compile(
    r"\bTX(?::|\s)[^\n]*?\bt\s+\d+\s+[A-Za-z]\s+([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*)",
    re.I,
)
_CLI_API_MENTION_RE = re.compile(
    r"\b("
    r"(?:wifi|ble|http_client|mqtt_client|net|socket|rsi_ble|bt)(?:\.[a-z][a-z0-9_]*)+"
    r"|[a-z]+_(?:get|set|init|scan|connect|start|stop|join|configure|load|write)[a-z0-9_]*"
    r")\b",
    re.I,
)
_STATUS_CODE_RE = re.compile(
    r"status\s*[:=]\s*(-?0x[0-9a-fA-F]+|-?\d+)|error_code\s*[:=]\s*(-?0x[0-9a-fA-F]+|-?\d+)",
    re.I,
)
_SKIP_API_FUNCS = {
    "verify_status",
    "issue_command_in_thread",
    "_issue_command_in_thread",
    "exception_handling",
    "new_f",
    "fun",
    "retry_decorator",
    "__retry_internal",
    "__run",
    "from_call",
    "pytest_runtest_call",
    "pytest_runtest_setup",
    "pytest_runtest_teardown",
    "_runtest_for",
    "_hookexec",
    "_inner_hookexec",
    "_multicall",
    "get_result",
    "run",
    "<lambda>",
    "create_connection",
    "_new_conn",
    "urlopen",
    "request",
    "connect",
}
_SKIP_CLI_CMDS = {
    "wifi.clear_ca_store",
    "wifi.set_performance_profile",
    "wifi.client.disconnect",
    "wifi.deinit",
    "http_client.deinit",
    "ble.deinit",
}


def _extract_cli_api(log_text: str, key_error: str, hint_funcs: list[str] | None = None) -> str:
    """Prefer exact DUT/CLI API (wifi.init / ble_get_device_state) over Python methods."""
    primary = _primary_failure_chunk(log_text)
    lines = [ln.rstrip() for ln in (primary or "").splitlines()]
    assert_idx = next(
        (
            i
            for i, ln in enumerate(lines)
            if "AssertionError" in ln
            or "Got exception" in ln
            or _EXC_LINE_RE.match(ln.strip())
        ),
        len(lines),
    )
    pre = "\n".join(lines[:assert_idx]) if assert_idx else primary
    tx_pre = [c.strip() for c in _TX_CMD_RE.findall(pre)]
    tx_all = [c.strip() for c in _TX_CMD_RE.findall(log_text or "")]

    # 1) If traceback points at a CLI-like method, prefer matching TX command.
    for func in reversed(hint_funcs or []):
        fl = func.lower()
        for cmd in reversed(tx_all):
            if cmd.lower() == fl or cmd.lower().endswith("." + fl):
                return cmd
        if re.search(
            r"_(?:get|set|init|scan|connect|start|stop|join|configure|load|write)",
            fl,
        ) or "." in fl:
            return func

    reason_l = (key_error or "").lower()
    # Reason-guided preference (e.g. BLE failures should not pick net.configure_ip).
    if "ble" in reason_l:
        for cmd in reversed(tx_all):
            cl = cmd.lower()
            if cl in _SKIP_CLI_CMDS:
                continue
            if cl.startswith("ble") or "ble." in cl or "ble_" in cl:
                return cmd
    if "dhcp" in reason_l or "ip address" in reason_l:
        for cmd in reversed(tx_pre or tx_all):
            cl = cmd.lower()
            if cl in _SKIP_CLI_CMDS:
                continue
            if "configure_ip" in cl or "client.connect" in cl or cl.endswith(".scan"):
                return cmd

    # 2) TX commands before the assertion (not teardown).
    for cmd in reversed(tx_pre):
        if cmd.lower() in _SKIP_CLI_CMDS:
            continue
        return cmd

    # 3) Mentions in reason / nearby text (e.g. "wifi.init command")
    for blob in (key_error, "\n".join(lines[max(0, assert_idx - 15) : assert_idx + 1])):
        mentions = _CLI_API_MENTION_RE.findall(blob or "")
        for cmd in reversed(mentions):
            if cmd.lower() in _SKIP_CLI_CMDS:
                continue
            return cmd

    # 4) Any non-teardown TX in the full log.
    for cmd in reversed(tx_all):
        if cmd.lower() not in _SKIP_CLI_CMDS:
            return cmd
    return ""


def extract_failure_details(log_text: str) -> dict[str, str]:
    """Extract CLI API/status/context from a pytest-html failure log."""
    key_error = extract_key_error_from_log(log_text)
    primary = _primary_failure_chunk(log_text)
    frames = _TB_FRAME_RE.findall(primary)
    call_frames: list[str] = []
    cli_hint_funcs: list[str] = []
    for path, _line, func in frames:
        if func in _SKIP_API_FUNCS:
            continue
        if func.startswith("pytest_") or func.startswith("<") or func.startswith("__"):
            continue
        call_frames.append(func)
        if "sl_wifi_test_agent_cli" in (path or "").replace("\\", "/"):
            cli_hint_funcs.append(func)

    # Exact API = DUT/CLI command (wifi.init), not a random Python helper method.
    failed_api = _extract_cli_api(log_text, key_error, hint_funcs=cli_hint_funcs)
    failed_command = failed_api

    status_code = ""
    status_m = _STATUS_CODE_RE.search(key_error) or _STATUS_CODE_RE.search(primary)
    if status_m:
        status_code = (status_m.group(1) or status_m.group(2) or "").strip()

    chain = call_frames[-4:] if call_frames else []
    context_bits: list[str] = []
    if failed_api:
        context_bits.append(f"API: {failed_api}")
    if status_code:
        context_bits.append(f"Status: {status_code}")
    if chain:
        context_bits.append("Call: " + " -> ".join(chain))

    explanation = ""
    lines = [ln.rstrip() for ln in primary.splitlines() if ln.strip()]
    assert_idx = next(
        (
            i
            for i, ln in enumerate(lines)
            if "AssertionError" in ln or _EXC_LINE_RE.match(ln.strip())
        ),
        -1,
    )
    if assert_idx >= 0:
        window = lines[max(0, assert_idx - 6) : assert_idx + 1]
        explanation = _clean_reason_text("\n".join(window))[:1200]
    elif key_error:
        explanation = key_error

    return {
        "key_error": key_error,
        "failed_api": failed_api,
        "failed_command": failed_command,
        "status_code": status_code,
        "failure_context": " | ".join(context_bits)[:500],
        "explanation": explanation,
    }


def _parse_tbody_rows(text: str, source: str) -> list[HtmlResultRow]:
    rows: list[HtmlResultRow] = []
    blocks = TBODY_RE.findall(text or "")
    if not blocks:
        # Legacy header-only match (no extras/log capture).
        for outcome_class, result_text, test_name in ROW_RE.findall(text or ""):
            map_id = extract_map_id(test_name)
            rows.append(
                HtmlResultRow(
                    source=source,
                    outcome_class=outcome_class.lower(),
                    result_text=result_text.strip(),
                    test_name=test_name.strip(),
                    test_src_map_id=map_id,
                    status=html_result_to_xray(result_text, outcome_class),
                    phase=detect_phase(test_name),
                )
            )
        return rows

    for outcome_class, body in blocks:
        result_m = RESULT_RE.search(body)
        name_m = NAME_RE.search(body)
        if not result_m or not name_m:
            continue
        result_text = _cell_plain_text(result_m.group(1))
        test_name = _cell_plain_text(name_m.group(1))
        map_id = extract_map_id(test_name)
        status = html_result_to_xray(result_text, outcome_class)
        log_m = LOG_RE.search(body)
        details: dict[str, str] = {}
        if log_m and status == "FAIL":
            full_log = _log_html_to_text(log_m.group(1), max_chars=0)
            details = extract_failure_details(full_log)
        rows.append(
            HtmlResultRow(
                source=source,
                outcome_class=outcome_class.lower(),
                result_text=result_text,
                test_name=test_name,
                test_src_map_id=map_id,
                status=status,
                phase=detect_phase(test_name),
                key_error=details.get("key_error") or "",
                explanation=details.get("explanation") or "",
                failed_api=details.get("failed_api") or "",
                failed_command=details.get("failed_command") or "",
                status_code=details.get("status_code") or "",
                failure_context=details.get("failure_context") or "",
            )
        )
    return rows


def _row_failure_meta(row: HtmlResultRow | None, source: str = "") -> dict[str, str]:
    if not row:
        return {
            "test_name": "",
            "source": source or "",
            "key_error": "",
            "explanation": "",
            "failed_api": "",
            "failed_command": "",
            "status_code": "",
            "failure_context": "",
        }
    return {
        "test_name": row.test_name or "",
        "source": source or row.source or "",
        "key_error": row.key_error or "",
        "explanation": row.explanation or "",
        "failed_api": row.failed_api or "",
        "failed_command": row.failed_command or "",
        "status_code": row.status_code or "",
        "failure_context": row.failure_context or "",
    }


def parse_html_text(text: str, source: str = "upload") -> ParsedHtmlReport:
    report = ParsedHtmlReport(source=source)
    if not text:
        report.errors.append("Empty HTML content")
        return report

    parsed_rows = _parse_tbody_rows(text, source)
    if not parsed_rows and "results-table" not in text and "col-result" not in text:
        report.errors.append(
            "Unrecognized HTML report format (expected pytest-html results table)"
        )
        return report

    candidates: dict[str, list[tuple[int, int, HtmlResultRow]]] = defaultdict(list)
    for row in parsed_rows:
        report.rows.append(row)
        if not row.test_src_map_id:
            continue
        status_rank = STATUS_RANK.get(row.status, 0)
        phase_rank = PHASE_RANK.get(row.phase, 0)
        # Prefer rows that actually captured a failure reason when ranks tie.
        reason_boost = 1 if row.key_error else 0
        candidates[row.test_src_map_id].append(
            (status_rank, phase_rank, reason_boost, row)
        )

    for map_id, items in candidates.items():
        items.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
        winner = items[0][3]
        report.by_map_id[map_id] = winner.status
        report.winning_rows[map_id] = winner

    if not report.rows:
        report.errors.append("No result rows found in HTML")
    return report


def parse_html_bytes(data: bytes, source: str = "upload") -> ParsedHtmlReport:
    text = data.decode("utf-8", errors="replace")
    report = parse_html_text(text, source=source)
    if report.timestamp is None:
        report.timestamp = extract_unix_timestamp(source)
    return report


def parse_html_path(path: str | Path) -> ParsedHtmlReport:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        report = ParsedHtmlReport(source=str(p), timestamp=extract_unix_timestamp(str(p)))
        report.errors.append(f"Unable to read {p}: {exc}")
        return report
    report = parse_html_text(text, source=str(p))
    if report.timestamp is None:
        report.timestamp = extract_unix_timestamp(str(p))
    return report


def blob_basename(name: str) -> str:
    """Basename for upload/ZIP entry labels (safe with zip:: prefixes on Windows)."""
    text = (name or "upload").replace("\\", "/")
    if "::" in text:
        text = text.split("::", 1)[-1]
    base = text.rsplit("/", 1)[-1].strip()
    return (base or "upload").casefold()


def dedupe_named_blobs(
    items: list[tuple[str, bytes]],
    *,
    by_basename: bool = True,
) -> tuple[list[tuple[str, bytes]], list[dict[str, str]]]:
    """Drop duplicate uploads; later filename unix timestamp wins.

    A file is duplicate when another kept file shares the same SHA-256 content,
    or (when by_basename=True) the same basename (case-insensitive).

    For multi-ZIP HTML entries, use by_basename=False so run1.zip::report.html
    (FAIL) is not discarded when run2.zip::report.html (PASS) shares the leaf
    name — chronological/worst merges still resolve the final status.
    """
    decorated: list[tuple[int, int, str, bytes]] = []
    for idx, (name, data) in enumerate(items or []):
        ts = extract_unix_timestamp(name) or -1
        decorated.append((ts, idx, name or "upload", data or b""))
    decorated.sort()

    kept: list[tuple[str, bytes]] = []
    index_by_base: dict[str, int] = {}
    index_by_hash: dict[str, int] = {}
    skipped: list[dict[str, str]] = []

    for _ts, _idx, name, data in decorated:
        base = blob_basename(name)
        digest = hashlib.sha256(data).hexdigest()
        replace_at: int | None = None
        reason = ""
        if digest in index_by_hash:
            replace_at = index_by_hash[digest]
            reason = "duplicate_content"
        elif by_basename and base in index_by_base:
            replace_at = index_by_base[base]
            reason = "duplicate_filename"

        if replace_at is not None:
            old_name, old_data = kept[replace_at]
            skipped.append(
                {"name": old_name, "reason": reason, "kept": name}
            )
            old_base = blob_basename(old_name)
            old_digest = hashlib.sha256(old_data).hexdigest()
            if index_by_base.get(old_base) == replace_at:
                del index_by_base[old_base]
            if index_by_hash.get(old_digest) == replace_at:
                del index_by_hash[old_digest]
            kept[replace_at] = (name, data)
            index_by_base[base] = replace_at
            index_by_hash[digest] = replace_at
        else:
            index_by_base[base] = len(kept)
            index_by_hash[digest] = len(kept)
            kept.append((name, data))

    return kept, skipped


def collect_html_paths(location: str, recursive: bool = True) -> list[Path]:
    """Resolve a file or folder path into HTML report files."""
    root = Path(location).expanduser()
    if not root.exists():
        raise FileNotFoundError(f"Path not found: {root}")
    if root.is_file():
        if root.suffix.lower() not in {".htm", ".html"}:
            raise ValueError(f"Not an HTML file: {root}")
        return [root]
    pattern = "**/*" if recursive else "*"
    files = [
        p
        for p in root.glob(pattern)
        if p.is_file() and p.suffix.lower() in {".htm", ".html"}
    ]
    return sorted(files)


def parse_locations(locations: Iterable[str], recursive: bool = True) -> list[ParsedHtmlReport]:
    reports: list[ParsedHtmlReport] = []
    for location in locations:
        loc = (location or "").strip()
        if not loc:
            continue
        try:
            paths = collect_html_paths(loc, recursive=recursive)
        except (FileNotFoundError, ValueError, OSError) as exc:
            bad = ParsedHtmlReport(source=loc)
            bad.errors.append(str(exc))
            reports.append(bad)
            continue
        if not paths:
            empty = ParsedHtmlReport(source=loc)
            empty.errors.append("No .htm/.html files found")
            reports.append(empty)
            continue
        for path in paths:
            reports.append(parse_html_path(path))
    return reports


def merge_reports(reports: list[ParsedHtmlReport]) -> dict[str, str]:
    """Merge map_id -> status across reports; worst status wins."""
    statuses, _meta = merge_reports_detailed(reports)
    return statuses


def merge_reports_detailed(
    reports: list[ParsedHtmlReport],
) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Merge map_id -> status (worst wins) plus test_name/source meta."""
    merged: dict[str, str] = {}
    meta: dict[str, dict[str, str]] = {}
    for report in reports:
        for map_id, status in report.by_map_id.items():
            prev = merged.get(map_id)
            row = (report.winning_rows or {}).get(map_id)
            if prev is None or STATUS_RANK.get(status, 0) > STATUS_RANK.get(prev, 0):
                merged[map_id] = status
                meta[map_id] = _row_failure_meta(row, report.source or "")
            elif (
                prev == status
                and row
                and row.key_error
                and not (meta.get(map_id) or {}).get("key_error")
            ):
                meta[map_id] = _row_failure_meta(row, report.source or "")
    return merged, meta


def extract_unix_timestamp(filename: str) -> int | None:
    """Return the best unix-seconds timestamp found in a report filename."""
    # Prefer the leaf name after optional zip:: prefix (Path is unsafe with ':' on Windows).
    text = (filename or "").replace("\\", "/")
    if "::" in text:
        text = text.split("::", 1)[-1]
    name = text.rsplit("/", 1)[-1] or text
    candidates: list[int] = []
    for match in UNIX_TS_RE.finditer(name):
        value = int(match.group(1))
        if value >= 1_000_000_000_000:  # milliseconds
            value //= 1000
        if _UNIX_TS_MIN <= value <= _UNIX_TS_MAX:
            candidates.append(value)
    return max(candidates) if candidates else None


def extract_zip_html_blobs(
    data: bytes, zip_name: str = "upload.zip"
) -> tuple[list[tuple[str, bytes]], list[str]]:
    """Extract HTML entry bytes from a ZIP. Returns (blobs, errors)."""
    label = zip_name or "upload.zip"
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        return [], [f"Invalid ZIP file ({label}): {exc}"]

    blobs: list[tuple[str, bytes]] = []
    errors: list[str] = []
    with archive:
        names = sorted(archive.namelist())
        html_names = [
            name
            for name in names
            if not name.endswith("/")
            and "__MACOSX" not in name
            and not Path(name).name.startswith(".")
            and Path(name).suffix.lower() in {".htm", ".html"}
        ]
        if not html_names:
            return [], [f"No .htm/.html files found in ZIP ({label})"]
        for name in html_names:
            # Prefix with zip name so multi-ZIP previews show the winning archive.
            source = f"{label}::{name}" if label else name
            try:
                raw = archive.read(name)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Unable to read ZIP entry {name} in {label}: {exc}")
                continue
            blobs.append((source, raw))
    return blobs, errors


def parse_zip_bytes(data: bytes, source: str = "upload.zip") -> list[ParsedHtmlReport]:
    """Extract and parse all .htm/.html reports from a ZIP archive."""
    blobs, errors = extract_zip_html_blobs(data, zip_name=source)
    reports: list[ParsedHtmlReport] = []
    if errors and not blobs:
        bad = ParsedHtmlReport(source=source, timestamp=extract_unix_timestamp(source))
        bad.errors.extend(errors)
        return [bad]
    for name, raw in blobs:
        report = parse_html_bytes(raw, source=name)
        if report.timestamp is None:
            report.timestamp = extract_unix_timestamp(name)
        reports.append(report)
    for err in errors:
        bad = ParsedHtmlReport(source=source, timestamp=extract_unix_timestamp(source))
        bad.errors.append(err)
        reports.append(bad)
    return reports


def parse_zip_files(
    zip_files: list[tuple[str, bytes]],
) -> tuple[list[ParsedHtmlReport], list[dict[str, str]]]:
    """Parse one or more ZIPs; dedupe ZIP archives and HTML entries.

    Returns (reports, skipped_duplicates).
    """
    zips, skipped_zips = dedupe_named_blobs(list(zip_files or []))
    html_blobs: list[tuple[str, bytes]] = []
    zip_errors: list[str] = []
    for zip_name, zip_data in zips:
        blobs, errors = extract_zip_html_blobs(zip_data, zip_name=zip_name or "upload.zip")
        html_blobs.extend(blobs)
        zip_errors.extend(errors)

    # Content-hash only: same leaf name across ZIPs/reruns must not drop FAIL HTML.
    html_blobs, skipped_html = dedupe_named_blobs(html_blobs, by_basename=False)
    reports: list[ParsedHtmlReport] = []
    for name, raw in html_blobs:
        report = parse_html_bytes(raw, source=name)
        if report.timestamp is None:
            report.timestamp = extract_unix_timestamp(name)
        reports.append(report)
    for err in zip_errors:
        bad = ParsedHtmlReport(source="zip")
        bad.errors.append(err)
        reports.append(bad)
    return reports, skipped_zips + skipped_html


def merge_reports_chronological(
    reports: list[ParsedHtmlReport],
) -> tuple[dict[str, str], dict[str, str]]:
    """Merge map_id -> status; later report (by filename unix timestamp) wins.

    Returns (statuses, winning_source_by_map_id).
    """
    statuses, meta = merge_reports_chronological_detailed(reports)
    sources = {mid: (info.get("source") or "") for mid, info in meta.items()}
    return statuses, sources


def merge_reports_chronological_detailed(
    reports: list[ParsedHtmlReport],
) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Like merge_reports_chronological, also returning test_name/source meta."""
    ordered = sorted(
        reports,
        key=lambda r: (r.timestamp if r.timestamp is not None else -1, r.source or ""),
    )
    merged: dict[str, str] = {}
    meta: dict[str, dict[str, str]] = {}
    for report in ordered:
        for map_id, status in report.by_map_id.items():
            row = (report.winning_rows or {}).get(map_id)
            merged[map_id] = status
            meta[map_id] = _row_failure_meta(row, report.source or "")
    return merged, meta


def _count_statuses(statuses: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for status in statuses:
        counts[status] += 1
    return dict(counts)
