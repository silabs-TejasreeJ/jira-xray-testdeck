"""Smoke-test pytest-html parsing against the sample Desktop report."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dashboard.html_results import (  # noqa: E402
    collect_html_paths,
    merge_reports,
    parse_html_path,
    parse_locations,
)

sample = Path(r"c:\Users\tejammul\Desktop\first_run_autojoin.HTM")
assert sample.exists(), sample

report = parse_html_path(sample)
print("source", report.source)
print("rows", len(report.rows))
print("mapped", len(report.by_map_id), sorted(report.by_map_id.items())[:5])
print("errors", report.errors)
assert len(report.rows) == 18
assert len(report.by_map_id) == 18
assert report.by_map_id["C769724"] == "FAIL"
assert any(v == "PASS" for v in report.by_map_id.values())
assert any(v == "TODO" for v in report.by_map_id.values())

file_reports = parse_locations([str(sample)])
merged = merge_reports(file_reports)
paths = collect_html_paths(str(sample))
assert paths == [sample]
assert merged["C769724"] == "FAIL"
print("merged", len(merged))
print("OK")
