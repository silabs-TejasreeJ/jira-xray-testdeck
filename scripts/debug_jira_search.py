import json
import os

import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

load_dotenv(".env")

base = os.getenv("JIRA_BASE_URL", "").rstrip("/")
auth = HTTPBasicAuth(os.getenv("JIRA_USERNAME"), os.getenv("JIRA_PASSWORD"))
headers = {"Accept": "application/json", "Content-Type": "application/json"}

print("myself", requests.get(f"{base}/rest/api/2/myself", auth=auth, timeout=60).status_code)

payloads = [
    {
        "jql": "project = SW_SQA_TE ORDER BY updated DESC",
        "startAt": 0,
        "maxResults": 5,
        "fields": ["summary", "status", "issuetype"],
    },
    {
        "jql": 'project = SW_SQA_TE AND issuetype = "Test Execution" ORDER BY updated DESC',
        "startAt": 0,
        "maxResults": 5,
        "fields": ["summary", "status", "issuetype"],
    },
    {
        "jql": 'project = "SW_SQA_TE" AND issuetype = "Test Execution" ORDER BY updated DESC',
        "startAt": 0,
        "maxResults": 5,
        "fields": ["summary", "status", "issuetype"],
    },
    {
        "jql": "project = SW_SQA_TE AND type = Test Execution ORDER BY updated DESC",
        "startAt": 0,
        "maxResults": 5,
        "fields": ["summary", "status", "issuetype"],
    },
]

for i, payload in enumerate(payloads):
    response = requests.post(
        f"{base}/rest/api/2/search",
        auth=auth,
        json=payload,
        timeout=60,
        headers=headers,
    )
    print(f"--- payload {i} status={response.status_code}")
    print(response.text[:800])

project = requests.get(f"{base}/rest/api/2/project/SW_SQA_TE", auth=auth, timeout=60)
print("project", project.status_code)
if project.ok:
    data = project.json()
    print("name", data.get("name"))
    print(
        "issueTypes",
        [(t.get("id"), t.get("name")) for t in (data.get("issueTypes") or [])],
    )
