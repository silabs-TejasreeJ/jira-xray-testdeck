# TestDeck

TestDeck is a Django web app that gives Silicon Labs SQA a **TestRail-like** view over **Jira / Xray** — plans, executions, the **Test Repository** (test cases, not runs), case status, result imports, failure triage, and Excel exports.

| | |
|---|---|
| **Jira** | `https://jira.silabs.com` |
| **Executions / plans** | `SW_SQA_TE` |
| **Test cases (repository)** | `SW_SQA_TC` |
| **Repo** | [silabs-TejasreeJ/jira-xray-testdeck](https://github.com/silabs-TejasreeJ/jira-xray-testdeck) |
| **Author** | Teja Sree Jammulamadaka |

---

## Table of contents

1. [Prerequisites](#1-prerequisites)
2. [Clone](#2-clone)
3. [Configure](#3-configure)
4. [Run](#4-run)
5. [Browse](#5-browse)
6. [Import & failure triage](#6-import--failure-triage)
7. [Export](#7-export)
8. [Edit status & defects from the UI](#8-edit-status--defects-from-the-ui)
9. [Contribute via Issues](#9-contribute-via-issues)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Prerequisites

- **Python 3.11+** (3.12 recommended)
- Network access to Jira (typically **VPN** when off-site)
- A Jira account that can read/write Xray Test Executions in `SW_SQA_TE` and browse Test issues in `SW_SQA_TC` (or your projects)
- Git

Optional: HTML/ZIP/Excel result files from your automation runs for import.

---

## 2. Clone

```bash
git clone https://github.com/silabs-TejasreeJ/jira-xray-testdeck.git
cd jira-xray-testdeck
```

Create and activate a virtualenv, then install dependencies:

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
# source .venv/bin/activate

pip install -r requirements.txt
```

---

## 3. Configure

Copy the example env file and edit as needed:

```bash
# Windows
copy .env.example .env

# macOS / Linux
# cp .env.example .env
```

### Minimum setup

| Variable | Purpose |
|----------|---------|
| `JIRA_BASE_URL` | Default `https://jira.silabs.com` |
| `JIRA_PROJECT_KEY` | Executions/plans project (`SW_SQA_TE`) |
| `JIRA_TEST_PROJECT_KEY` | Test case / repository project (`SW_SQA_TC`) |
| `DJANGO_SECRET_KEY` | Change from the placeholder for anything beyond local use |

**Do not put your password in `.env` for day-to-day use.** Prefer `python run.py` (prompts each launch) or the browser **Sign in** page.

Leave `JIRA_USERNAME` / `JIRA_PASSWORD` blank unless you intentionally want env-based auth.

### Field IDs & triage JQL

`.env.example` already includes the Coex / SWSQAT custom field IDs and similar-bug JQL used for failure triage. Adjust only if your Jira field map differs:

- `XRAY_*_FIELD` — Test **issue** custom fields
- `XRAY_TRCF_*` — Test **Run** custom field numeric IDs (Host Platform, Interface type, etc.)
- `JIRA_SIMILAR_BUG_*` — read-only JQL pools for “similar bug” suggestions

Then initialize the local DB (required once — login fails with `no such table: django_session` if you skip this):

```bash
python manage.py migrate
```

---

## 4. Run

### Recommended: launcher with credential prompt

```bash
python run.py
```

1. Enter Jira URL (default from `.env`)
2. Enter username and password
3. Credentials are verified against Jira
4. Server starts at [http://127.0.0.1:8000](http://127.0.0.1:8000)

Press `Ctrl+C` to stop.

### Alternative: Django directly

```bash
python manage.py runserver
```

If credentials are not in the environment, open the app and use the **Sign in** page in the browser.

---

## 5. Browse

| Page | Path | What to do |
|------|------|------------|
| **Overview** | `/` | Pie chart + PASS / FAIL / TODO counts; Coex/WLAN shortcuts |
| **Plan View** | `/plans/` | All Test Plans with Latest Status bars |
| **Case Grid** | `/plan/`, `/plans/<key>/` | Pick a plan → see **all linked Test Executions** → open one run’s case table |
| **Results Update** | `/results-update/` | Export / import / triage hub |
| **Executions** | `/executions/`, `/executions/<key>/` | List runs and open a case table |
| **Repository** | `/tests/`, `/tests/<key>/` | Browse **Test issues** by Xray folder (not an execution) |
| **Coverage / Defects** | `/coverage/`, `/defects/` | Supporting browse views |

### Plan View / Case Grid tips

1. On **Plan View**, browse plans. On **Case Grid**, select a **Test Plan** and Submit — every linked **Test Execution** is listed.
2. Open one run for the case grid (status, assignee, Linked Jira).
3. Use **technology / stack / release** filters and the status dropdown.
4. Click overview chips (**FAIL** / **PASS** / **TODO**) to filter the case grid.
5. Search debounces as you type; use **Clear** when filters are active.
6. Empty sections hide when the current filter has no matching cases.
7. Section / filter / pagination refresh the **cases panel only** (no full page reload).
8. Use **Continue last run** to reopen the last plan + execution.
9. Use **Refresh** on a run when you need a fresh pull from Jira/Xray (executions are cached briefly).

### Test Repository

Repository is the Xray **test definition** tree (`SW_SQA_TC-…`), not a Test Execution.

1. Open **Repository**. Set the test project (default `SW_SQA_TC`) and optional **Technology** (e.g. `WLAN + BLE`).
2. Expand / collapse folders in the left tree (**Expand all** / **Collapse all**). Parent counts include tests in child folders (IOTREQs).
3. Click a folder to list its tests. Listing uses Xray JQL of the form  
   `issue in TestRepositoryFolderTests(SW_SQA_TC,'<folder path>','true') AND Technology = "WLAN + BLE"`.
4. **Steps** opens the case in TestDeck (status, folder, labels, description, action / data / expected). **Jira** opens the issue.

This is browse-only. Status and defects are edited on a Test Execution in **Case Grid**.

---

## 6. Import & failure triage

Open **Results Update** → `/results-update/`.

### Import tabs

| Tab | Input | Writes to Xray? |
|-----|--------|-----------------|
| **Import HTML** | One or more `.htm` / `.html` files | **PASS only** |
| **Import Folder** | Browser folder of HTML reports | **PASS only** |
| **Import ZIP** | One or more `.zip` archives containing HTML | **PASS only** |
| **Import Excel** | OverAllStatus workbook | **PASS only** |

### Recommended flow

1. Select the target **Test Execution** (same as Plan View context).
2. Choose an import tab and select files or a folder.
3. Run **Preview** — review matched cases and status counts (including TODO / report FAIL chips).
4. Review **Failure triage** (appears after preview; **read-only** — does not write to Jira/Xray).
5. If you want to apply passes, confirm the **PASS apply** step.
6. Re-run preview after apply if you need an updated triage list (remaining TODOs only).

### Failure triage rules

- One triage row per case that is still **TODO / untested in Xray**
- If the report has **FAIL/ERROR** details for that case, they enrich the triage row (reason / API)
- Cases already **PASS** in Xray are **skipped** (not listed)
- Similar-bug suggestions use the JQL pools in `.env`; pick or type a Jira key (remembered for the session)
- Download triage Excel (includes a **Jira summary** sheet) from the triage panel

**Important:** Import never marks FAIL in Xray from HTML/ZIP/Excel. FAIL/ERROR in reports are for triage preview only. Mark FAIL (and link defects) from the case table UI when needed.

---

## 7. Export

On **Results Update** → **Export Excel**:

| Export | Contents |
|--------|----------|
| **This Test Execution** | Full case dump (references, status, defects, steps) |
| **FAIL Jira summary** | Triage-style sheet: Type · Issue key · No of TCs Impacted · Summary · Status · Priority · Assignee (+ FAIL case → Jira map) |
| **Entire Test Plan** | All linked runs; shows a progress bar and supports cancel |

You can also download triage Excel from the failure-triage panel after an import preview.

---

## 8. Edit status & defects from the UI

On Plan View / Execution case tables:

- Update **status** / **assignee** per row, or select rows and use the **bulk** bar
- Setting **PASS** or **FAIL** opens a dialog for **execution details** (Test Run custom fields: Host Platform, Interface type, etc.)
- On **FAIL**, you can optionally link Jira defects in that same dialog
- **Linked Jira** on the case row: **+** links a defect anytime (status unchanged); **×** unlinks one
- Toasts confirm success/errors; pie/summary refresh without a full page reload

---

## 9. Contribute via Issues

Suggestions, bugs, and improvement ideas are welcome.

1. Open [silabs-TejasreeJ/jira-xray-testdeck](https://github.com/silabs-TejasreeJ/jira-xray-testdeck)
2. Go to **Issues** → **New issue**
3. Include:
   - What you were doing (browse / import / triage / export)
   - Expected vs actual behavior
   - Screenshots or sample HTML filenames if relevant (no passwords / tokens)
4. Issues will be triaged one by one

For deep dives on past bugs and fixes, see [PROBLEMS_AND_SOLUTIONS.md](PROBLEMS_AND_SOLUTIONS.md).

---

## 10. Troubleshooting

| Symptom | What to try |
|---------|-------------|
| Cannot reach Jira / launcher fails | Connect VPN; confirm `JIRA_BASE_URL`; check username/password |
| Browser Sign in loop | Clear site data for `127.0.0.1:8000`; restart with `python run.py` |
| Empty Plan View / no executions | Confirm project key and that your user can see the Xray issues in Jira |
| `OperationalError: no such table: django_session` | Run `python manage.py migrate` from the project root, then start the server again |
| Repository folder tree empty | Confirm `JIRA_TEST_PROJECT_KEY` (`SW_SQA_TC`) and that Xray Test Repository is enabled for that project |
| Repository folder lists the wrong tests | Use the exact folder path from the tree; keep Technology set if you filtered (e.g. WLAN + BLE) |
| First load of a large execution is slow | Expected once; later visits use a short cache. Click **Refresh** only when you need a new pull |
| Stale statuses after Jira change | Click **Refresh** on the run |
| Triage empty after re-upload | Expected if remaining cases are Xray **PASS**; triage lists **TODO** only |
| Import “applied” but FAIL still open | Imports write **PASS only**; set FAIL from the case table |
| SSL errors to Jira | Only if your admin says so: `JIRA_VERIFY_SSL=false` (self-signed) |

---

## Feature summary

- Overview pie + filters that do not skew overall counts
- Plan View Latest Status bars; Case Grid lists all executions for a plan
- Test Repository folder browse, Technology filter, expand/collapse, case + steps view
- Results Update: Export · Import HTML · Import Folder · Import ZIP · Import Excel
- Failure triage for Xray TODOs with similar-bug picker and Excel download
- Bulk / per-row status updates; link or unlink Execution Defects anytime from Linked Jira
