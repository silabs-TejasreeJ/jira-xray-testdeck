import os
import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

load_dotenv(".env")
base = os.getenv("JIRA_BASE_URL").rstrip("/")
auth = HTTPBasicAuth(os.getenv("JIRA_USERNAME"), os.getenv("JIRA_PASSWORD"))
headers = {"Accept": "application/json", "Content-Type": "application/json"}

exec_key = "SW_SQA_TE-30689"
# sample one test run
r = requests.get(
    f"{base}/rest/raven/1.0/api/testexec/{exec_key}/test",
    auth=auth,
    headers=headers,
    params={"limit": 1, "page": 1, "detailed": "true"},
    timeout=60,
)
print("tests", r.status_code, r.text[:400])
item = r.json()[0] if r.ok and r.json() else {}
print("item keys", item.keys())
run_id = item.get("id")
print("run_id", run_id, "key", item.get("key"), "status", item.get("status"))

# probe update endpoints (dry info only - OPTIONS/GET)
for path in [
    f"/rest/raven/1.0/api/testrun/{run_id}",
    f"/rest/raven/1.0/testrun/{run_id}",
    f"/rest/raven/1.0/api/testrun/{run_id}/status",
]:
    resp = requests.get(f"{base}{path}", auth=auth, headers=headers, timeout=30)
    print("GET", path, resp.status_code, resp.text[:200])
