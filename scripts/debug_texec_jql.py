import os
import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

load_dotenv(".env")
base = os.getenv("JIRA_BASE_URL").rstrip("/")
auth = HTTPBasicAuth(os.getenv("JIRA_USERNAME"), os.getenv("JIRA_PASSWORD"))
jql = 'issue in testExecutionTests(SW_SQA_TE-30689) AND Technology = "WLAN + BLE"'
r = requests.post(
    f"{base}/rest/api/2/search",
    auth=auth,
    json={"jql": jql, "maxResults": 3, "fields": ["summary"]},
    timeout=60,
)
print(r.status_code, r.json().get("total"), r.json().get("errorMessages"))
