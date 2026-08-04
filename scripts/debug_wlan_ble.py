import os
import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

load_dotenv(".env")
base = os.getenv("JIRA_BASE_URL").rstrip("/")
auth = HTTPBasicAuth(os.getenv("JIRA_USERNAME"), os.getenv("JIRA_PASSWORD"))
headers = {"Accept": "application/json", "Content-Type": "application/json"}

jqls = [
    'project = SW_SQA_TC AND issuetype = "Xray Test" AND Technology = "WLAN + BLE" ORDER BY updated DESC',
    'project = SW_SQA_TC AND Technology = "WLAN + BLE" ORDER BY updated DESC',
    'project = SW_SQA_TE AND summary ~ "Coex" AND issuetype = "Xray Test Plan" ORDER BY updated DESC',
    'project = SW_SQA_TE AND summary ~ "WLAN" AND issuetype = "Xray Test Plan" ORDER BY updated DESC',
    'project = SW_SQA_TE AND summary ~ "Coex" AND issuetype = "Xray Test Execution" ORDER BY updated DESC',
    'project = SW_SQA_TE AND issuetype = "Xray Test Execution" AND summary ~ "IoT_FreeRTOS" ORDER BY updated DESC',
    'cf[22640] = "WLAN + BLE" AND project = SW_SQA_TC ORDER BY updated DESC',
]

for jql in jqls:
    resp = requests.post(
        f"{base}/rest/api/2/search",
        auth=auth,
        headers=headers,
        json={"jql": jql, "maxResults": 3, "fields": ["summary", "customfield_22640"]},
        timeout=60,
    )
    data = resp.json() if resp.ok else {"error": resp.text[:300]}
    print("====")
    print(jql)
    print(resp.status_code, "total=", data.get("total"), "err=", data.get("errorMessages") or data.get("error"))
    for issue in data.get("issues", [])[:3]:
        print(" ", issue["key"], issue["fields"].get("summary"), "tech=", issue["fields"].get("customfield_22640"))

# Probe a Coex execution for tests+status
r = requests.post(
    f"{base}/rest/api/2/search",
    auth=auth,
    headers=headers,
    json={
        "jql": 'project = SW_SQA_TE AND issuetype = "Xray Test Execution" AND summary ~ "Coex" ORDER BY updated DESC',
        "maxResults": 1,
        "fields": ["summary"],
    },
    timeout=60,
)
issues = r.json().get("issues", [])
if issues:
    key = issues[0]["key"]
    print("execution", key, issues[0]["fields"]["summary"])
    for path in [
        f"/rest/raven/1.0/api/testexec/{key}/test",
        f"/rest/raven/1.0/api/testexec/{key}/test?detailed=true&limit=5",
    ]:
        resp = requests.get(f"{base}{path}", auth=auth, headers=headers, timeout=120)
        print(path, resp.status_code, resp.text[:600])

# Probe plan SW_SQA_TE-28392
plan = "SW_SQA_TE-28392"
resp = requests.get(
    f"{base}/rest/raven/1.0/api/testplan/{plan}/testexecution",
    auth=auth,
    headers=headers,
    timeout=60,
)
print("plan execs", plan, resp.status_code, len(resp.json()) if resp.ok else resp.text[:200])
if resp.ok and resp.json():
    print(resp.json()[:3])
resp = requests.get(
    f"{base}/rest/raven/1.0/api/testplan/{plan}/test",
    auth=auth,
    headers=headers,
    timeout=60,
)
print("plan tests", resp.status_code, (resp.text[:500] if resp.text else ""))
