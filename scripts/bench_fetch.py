import os
import time

import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

load_dotenv(".env")
base = os.getenv("JIRA_BASE_URL").rstrip("/")
auth = HTTPBasicAuth(os.getenv("JIRA_USERNAME"), os.getenv("JIRA_PASSWORD"))
h = {"Accept": "application/json", "Content-Type": "application/json"}

t0 = time.time()
r = requests.get(
    f"{base}/rest/raven/1.0/api/testrun",
    auth=auth,
    headers=h,
    params={"testExecIssueKey": "SW_SQA_TE-30689", "testIssueKey": "SW_SQA_TC-14859"},
    timeout=30,
)
print("lookup", r.status_code, r.text[:250], "dt", round(time.time() - t0, 2))

t0 = time.time()
for page in range(1, 5):
    r = requests.get(
        f"{base}/rest/raven/1.0/api/testexec/SW_SQA_TE-30689/test",
        auth=auth,
        headers=h,
        params={"limit": 200, "page": page, "detailed": "false"},
        timeout=60,
    )
    print("page", page, r.status_code, len(r.json()) if r.ok else r.text[:80])
print("4 pages dt", round(time.time() - t0, 2))

t0 = time.time()
r = requests.post(
    f"{base}/rest/api/2/search",
    auth=auth,
    headers=h,
    json={
        "jql": 'issue in testExecutionTests(SW_SQA_TE-30689) AND Technology = "WLAN + BLE" ORDER BY key ASC',
        "maxResults": 200,
        "fields": ["summary", "customfield_32360", "labels"],
    },
    timeout=60,
)
data = r.json()
print(
    "search200",
    r.status_code,
    "total",
    data.get("total"),
    "returned",
    len(data.get("issues", [])),
    "dt",
    round(time.time() - t0, 2),
)
