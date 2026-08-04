import os
import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

load_dotenv(".env")
base = os.getenv("JIRA_BASE_URL").rstrip("/")
auth = HTTPBasicAuth(os.getenv("JIRA_USERNAME"), os.getenv("JIRA_PASSWORD"))
headers = {"Accept": "application/json", "Content-Type": "application/json"}

plan = "SW_SQA_TE-28392"
jqls = [
    f'issue in testPlanTests({plan}) AND Technology = "WLAN + BLE"',
    f'issue in testPlanTests("{plan}") AND Technology = "WLAN + BLE"',
    f'issue in testPlanTests({plan})',
]
for jql in jqls:
    resp = requests.post(
        f"{base}/rest/api/2/search",
        auth=auth,
        headers=headers,
        json={"jql": jql, "maxResults": 5, "fields": ["summary", "customfield_22640"]},
        timeout=120,
    )
    data = resp.json() if resp.content else {}
    print(jql)
    print(resp.status_code, "total", data.get("total"), data.get("errorMessages"), "sample", [i["key"] for i in data.get("issues", [])])
    print("---")
