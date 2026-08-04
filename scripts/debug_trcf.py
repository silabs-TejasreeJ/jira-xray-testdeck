"""Discover Xray Test Run custom field IDs (generic) for Results Update."""

from __future__ import annotations

import json
import os
import sys

import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

load_dotenv(".env")
base = (os.getenv("JIRA_BASE_URL") or "").rstrip("/")
user = os.getenv("JIRA_USERNAME") or ""
password = os.getenv("JIRA_PASSWORD") or ""
if not base or not user or not password:
    print("Set JIRA_BASE_URL / JIRA_USERNAME / JIRA_PASSWORD in .env")
    sys.exit(1)

auth = HTTPBasicAuth(user, password)
headers = {"Accept": "application/json", "Content-Type": "application/json"}
project = os.getenv("JIRA_PROJECT_KEY", "SW_SQA_TE")
exec_key = sys.argv[1] if len(sys.argv) > 1 else "SW_SQA_TE-30689"

print("=== project settings probes ===")
paths = [
    f"/rest/raven/1.0/api/project/{project}/settings/customfields/testruns",
    f"/rest/raven/2.0/api/project/{project}/settings/customfields/testruns",
    "/rest/raven/1.0/api/settings/testrun/customfields",
]
for path in paths:
    resp = requests.get(f"{base}{path}", auth=auth, headers=headers, timeout=60)
    print("GET", path, resp.status_code)
    if resp.ok:
        print(json.dumps(resp.json(), indent=2)[:4000])
        break

print("\n=== execution sample + testRunValues ===")
tests = requests.get(
    f"{base}/rest/raven/1.0/api/testexec/{exec_key}/test",
    auth=auth,
    headers=headers,
    params={"limit": 1, "page": 1, "detailed": "true"},
    timeout=60,
)
print("tests", tests.status_code)
if not tests.ok or not tests.json():
    sys.exit(0)

item = tests.json()[0]
run_id = item.get("id")
print("run_id", run_id, "key", item.get("key"))

for path in (
    f"/rest/raven/1.0/customFields/testRunValues?testRunId={run_id}",
    f"/rest/raven/1.0/api/customFields/testRunValues?testRunId={run_id}",
    f"/rest/raven/1.0/api/testrun/{run_id}",
):
    resp = requests.get(f"{base}{path}", auth=auth, headers=headers, timeout=60)
    print("\nGET", path, resp.status_code)
    if not resp.ok:
        print(resp.text[:500])
        continue
    data = resp.json()
    print(json.dumps(data, indent=2)[:6000])
