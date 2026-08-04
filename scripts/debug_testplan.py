import os
import json
import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

load_dotenv(".env")
base = os.getenv("JIRA_BASE_URL").rstrip("/")
auth = HTTPBasicAuth(os.getenv("JIRA_USERNAME"), os.getenv("JIRA_PASSWORD"))
headers = {"Accept": "application/json", "Content-Type": "application/json"}

# Find a recent test plan
r = requests.post(
    f"{base}/rest/api/2/search",
    auth=auth,
    headers=headers,
    json={
        "jql": 'project = SW_SQA_TE AND issuetype = "Xray Test Plan" ORDER BY updated DESC',
        "maxResults": 5,
        "fields": ["summary", "status"],
    },
    timeout=60,
)
plans = r.json().get("issues", [])
print("plans", [(p["key"], p["fields"]["summary"]) for p in plans])
key = plans[0]["key"] if plans else None
print("using", key)

if key:
    paths = [
        f"/rest/raven/1.0/api/testplan/{key}/test",
        f"/rest/raven/1.0/api/testplan/{key}/testexecution",
        f"/rest/raven/2.0/api/testplan/{key}/test",
        f"/rest/raven/1.0/api/testplan/{key}",
    ]
    for path in paths:
        resp = requests.get(f"{base}{path}", auth=auth, headers=headers, timeout=60)
        print("---", path, resp.status_code, resp.text[:400])

# Technology field
fields = requests.get(f"{base}/rest/api/2/field", auth=auth, timeout=60).json()
for f in fields:
    name = (f.get("name") or "").lower()
    if "technology" in name or "wlan" in name or "test area" in name or "test_area" in name:
        print("FIELD", f.get("id"), f.get("name"))

# Sample JQL for WLAN + BLE
for jql in [
    'project = SW_SQA_TE AND issuetype = "Xray Test Execution" AND Technology = "WLAN + BLE" ORDER BY updated DESC',
    'project = SW_SQA_TE AND issuetype = "Xray Test Plan" AND Technology = "WLAN + BLE" ORDER BY updated DESC',
    'project = SW_SQA_TE AND issuetype = "Xray Test Execution" AND "Technology" = "WLAN + BLE" ORDER BY updated DESC',
]:
    resp = requests.post(
        f"{base}/rest/api/2/search",
        auth=auth,
        headers=headers,
        json={"jql": jql, "maxResults": 3, "fields": ["summary"]},
        timeout=60,
    )
    print("JQL", resp.status_code, jql[:80], "total", resp.json().get("total") if resp.ok else resp.text[:200])
