import os
import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

load_dotenv(".env")
base = os.getenv("JIRA_BASE_URL").rstrip("/")
auth = HTTPBasicAuth(os.getenv("JIRA_USERNAME"), os.getenv("JIRA_PASSWORD"))
headers = {"Accept": "application/json"}

key = "SW_SQA_TE-30689"
for params in [
    {"limit": 50, "page": 1},
    {"limit": 50, "page": 1, "detailed": "true"},
    {"limit": 200, "page": 1},
]:
    resp = requests.get(
        f"{base}/rest/raven/1.0/api/testexec/{key}/test",
        auth=auth,
        headers=headers,
        params=params,
        timeout=120,
    )
    data = resp.json() if resp.ok else resp.text
    print(params, resp.status_code, "len", len(data) if isinstance(data, list) else data[:120])

plan = "SW_SQA_TE-28392"
for params in [{"limit": 50, "page": 1}, {"limit": 200, "page": 1}]:
    resp = requests.get(
        f"{base}/rest/raven/1.0/api/testplan/{plan}/test",
        auth=auth,
        headers=headers,
        params=params,
        timeout=120,
    )
    data = resp.json() if resp.ok else resp.text
    print("plan", params, resp.status_code, "len", len(data) if isinstance(data, list) else str(data)[:120])
    if isinstance(data, list) and data:
        print(" sample", data[0])
