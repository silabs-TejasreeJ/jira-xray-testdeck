# TestDeck

TestDeck is a Django web app that gives Silicon Labs SQA a **TestRail-like** view over **Jira / Xray** — plans, executions, sections, case status, result imports, failure triage, and Excel exports.

Default Jira: `https://jira.silabs.com` · project: `SW_SQA_TE`

---

## Features

### Browse & filter
- **Overview** — pie chart + PASS / FAIL / TODO counts (overall run, not skewed by section filters)
- **Plan View / Execution** — section tree, case table, technology / stack / release filters
- Click overview chips (FAIL / PASS / TODO) to filter the case grid
- Status dropdown auto-filters; search debounces as you type; **Clear** when filters are active
- Empty sections hide when a status/search filter has no matching cases
- Section / filter / pagination refresh the **cases panel only** (no full page reload)
- **Continue last run** on Plan View (remembers last plan + execution)

### Edit from the UI
- Per-row and **bulk** status / assignee updates (bulk bar appears only when rows are selected)
- **PASS / FAIL** opens a dialog for **execution details** (Test Run custom fields: Host Platform, Interface type, etc.)
- **Jira defects only on FAIL** — optional link by key or browse URL (search-as-you-type picker)
- **Linked Jira** column is display-only (shows keys already linked on the run)
- Toasts for success/errors; pie/summary refreshes without reloading the page

### Results Update (dedicated page)
| Tab | What it does |
|-----|----------------|
| **Export Excel** | Run dump · FAIL Jira summary (triage-style) · full plan dump (progress + cancel) |
| **Import HTML** | One or more `.htm`/`.html` files (**PASS only** write) |
| **Import Folder** | Browser folder of HTML and/or server folder path (**PASS only** write) |
| **Import ZIP** | One or more `.zip` archives of HTML (**PASS only** write) |
| **Import Excel** | OverAllStatus workbook (**PASS only** write) |

After any import **preview**, **Failure triage** appears (read-only — does not write to Jira/Xray):
- **TODO / untested in Xray only** (one triage row each); report FAIL/ERROR details when present; already PASS skipped
- Similar-bug suggestions + pick/remember Jira; download triage Excel with **Jira summary** sheet

### Excel exports
1. **This Test Execution** — full case dump (references, status, defects, steps)
2. **FAIL Jira summary** — triage layout: Type · Issue key · No of TCs Impacted · Summary · Status · Priority · Assignee (+ FAIL case → Jira map)
3. **Entire Test Plan** — all linked runs, with progress bar and cancel

---

## Quick start

```bash
cd xray-testrail-dashboard
python -m venv .venv

# Windows
.venv\Scripts\activate

pip install -r requirements.txt
copy .env.example .env
python manage.py migrate
```

### Recommended: launch with credential prompt

```bash
python run.py
```

Prompts for Jira username/password, verifies them, then starts the server.

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).  
If credentials are missing, TestDeck shows a **Sign in** page in the browser.

Configure field IDs and triage JQL in `.env` (see `.env.example`).

---

## Main pages

| Page | Path | Purpose |
|------|------|---------|
| Overview | `/` | Status pie + Coex/WLAN shortcuts |
| Plan View | `/plan/`, `/plans/<key>/` | Section tree + cases for a plan/run |
| Results Update | `/results-update/` | Export / import / triage hub |
| Executions | `/executions/`, `/executions/<key>/` | List and open a run |
| Plans / Repository / Coverage / Defects | `/plans/`, `/tests/`, `/coverage/`, `/defects/` | Browse supporting data |

---

## Notes

- Large executions are cached briefly; field maps are cached longer across requests
- Use **Refresh** on a run when you need a fresh pull from Jira/Xray
- ZIP / Excel imports update **PASS** only; FAIL/ERROR are for triage preview, not Xray writes
- Defect linking uses issue **keys** (or browse URLs that contain keys)
- Author credit is configurable via `SITE_CREDIT_NAME` in `.env`

See [PROBLEMS_AND_SOLUTIONS.md](PROBLEMS_AND_SOLUTIONS.md) for problem → solution history.
