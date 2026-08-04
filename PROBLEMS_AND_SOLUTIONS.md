# TestDeck — Problems & Solutions

This document records the main product problems TestDeck was built to solve, and how each one is addressed in the app today.

---

## 1. Xray is hard to use like TestRail

**Problem**  
Xray in Jira does not present Test Plans / Executions the way TestRail does (section tree, per-case status grid, quick overview). SQA still needed that workflow while staying on Jira/Xray data.

**Solution**  
Built **TestDeck**, a Django UI over Jira/Xray APIs:
- Overview pie chart + PASS / FAIL / TODO counts
- Plan View with section tree and case table
- Execution detail pages with filters, pagination, and columns such as `test_src_map_id`
- Technology / stack / release filters (e.g. WLAN + BLE)

---

## 2. Slow loads on large executions

**Problem**  
Pulling every case from Xray for big runs was too slow for day-to-day use.

**Solution**
- Short-lived caching of execution case payloads
- Pagination in the case table
- **Refresh** control when a fresh pull is required
- Background jobs with progress for long plan exports and bulk result applies

---

## 3. Cannot update status without leaving TestDeck

**Problem**  
Marking PASS/FAIL/TODO had to be done in Xray’s UI, case by case.

**Solution**
- Per-row status editing in the execution table
- **Bulk select** + bulk status update (TestRail-style toolbar)
- Optional assignee updates (single and bulk)

---

## 4. Result posting from automation HTML reports

**Problem**  
Automation produces pytest HTML reports. Mapping results into Xray by hand was error-prone. Failures must not overwrite Xray incorrectly.

**Solution — Results Update page**
- Dedicated **Results Update** page (not mixed into Plan View)
- Separate import tabs (no overlapping pickers):
  - **Import HTML** — multi-select HTML files
  - **Import Folder** — folder of HTML (browser) and/or server path
  - **Import ZIP** — multi-select ZIP archives
  - **Import Excel** — OverAllStatus workbook
- Map via `test_src_map_id` / case id; **PASS only** written to Xray; FAIL skipped; already-PASS left untouched
- Progress bar for apply jobs (done / left / %)

---

## 5. Test Run custom fields hard to set

**Problem**  
Fields like Host Platform, Interface type, Test Mode, Test Execution Method needed to be set per run, with correct Xray option values — hard-coding was brittle.

**Solution**
- Results Update panel loads Test Run custom fields from Xray APIs
- Dropdowns populated from live option lists
- Generic field discovery where possible (IDs still configurable in `.env`)
- Values posted through Xray Test Run custom-field endpoints

---

## 6. Need Excel dumps for runs and whole plans

**Problem**  
Teams need offline Excel with cases, status, defects, references, and related Jira details — for a single run and for an entire Test Plan (variable number of executions).

**Solution**
- Centralized **Export Excel** tab on Results Update (not duplicated on every page)
- **This Test Execution** — full case dump (title, status, defects, references, steps, etc.)
- **Entire Test Plan** — all linked executions in one workbook
  - Progress bar while loading
  - **Cancel** that stops promptly
- Extra sheets/columns as needed: defect status/priority, reference descriptions, milestone parsed from run naming, Jira lists, multi-line cells without noisy separators
- Coverage-oriented sheets (cases, pass/fail counts and %)

---

## 7. Failure triage after report upload

**Problem**  
After uploading reports, engineers need a **preview** of failures: reason, similar Jiras, and a downloadable summary — **without** writing to Jira/Xray from triage.

**Solution — Failure triage panel** (after HTML / ZIP / Excel preview)
- Includes:
  - **Xray TODO / untested only** (matches Untested count)
  - Report FAIL/ERROR details attached when the upload has them
  - Already **PASS** in Xray skipped
- Extracts useful failure **reason** / API info (skips noisy traceback headers)
- Suggests similar bugs from configured JQL pools (e.g. Coex SQA project + SI91X)
- Pick a Jira (or type a key); selection remembered for later uploads of the same case
- **Download triage Excel**, including a **Jira summary** sheet:

  | Issue Type | Issue key | No of TCs Impacted | Summary | Status | Priority | Assignee |
  |------------|-----------|--------------------|---------|--------|----------|----------|

  (plus case-level detail sheets as needed)

---

## 8. Link Execution Defects when failing from the UI

**Problem**  
Failing a case in TestDeck needed the same **Execution Defects** behavior as Xray: attach existing Jira issue keys to the test run.

**Solution**
- Execution Defects column + modal when marking FAIL
- Accept issue keys or browse URLs (key extracted)
- Xray associate-by-key APIs (PUT/POST with verify via GET)
- **Bulk add defects** to selected cases: search-as-you-type issue picker, chips, paste keys/URLs

---

## 9. Status/search filters still showed empty sections

**Problem**  
Filtering by FAIL (or search) left empty section folders in the tree, which was noisy and confusing.

**Solution**  
Section tree is built from **filtered** cases only. Sections with zero matching cases are hidden. All Tests counts and links preserve the active status/search filters.

---

## 10. FAIL dump should match triage Jira summary (not a full case dump)

**Problem**  
A “FAIL + Jiras” export that dumped every FAIL case row was cluttered. For failed cases, the need was the same **Jira summary** layout used in triage (and in offline Automation failures reports).

**Solution**
- Cleaned Export UI into three clear cards:
  1. This Test Execution  
  2. **FAIL Jira summary**  
  3. Entire Test Plan  
- Removed duplicate “Download FAIL + Jiras” buttons from filter bars
- **FAIL Jira summary** download (`/executions/<key>/fail-jiras.xlsx`) produces:
  - **Jira summary** sheet — Type, Issue key, No of TCs Impacted, Summary, Status, Priority, Assignee (+ Total)
  - Compact **FAIL cases** sheet — case → linked Jiras map

---

## 11. Credentials and local launch

**Problem**  
Developers needed a simple way to run TestDeck with Jira auth without committing secrets.

**Solution**
- `python run.py` prompts for username/password, validates against Jira, then starts Django
- Browser **Sign in** page if session/env credentials are missing
- `.env.example` documents URLs, project keys, field IDs, and triage JQL (leave passwords blank)

---

## Quick reference — where to do what

| Need | Where |
|------|--------|
| Browse plan / sections / status | Plan View |
| Fail case + attach defect | Execution table → status + Execution Defects |
| Bulk link Jiras | Select cases → Add defects to selected |
| Import HTML / ZIP / Excel | Results Update → Import tabs |
| Preview failures + triage Excel | Results Update → after Preview |
| Full run Excel | Results Update → Export → Download run Excel |
| FAIL Jira summary Excel | Results Update → Export → Download FAIL Jira summary |
| Whole plan Excel | Results Update → Export → Download plan Excel |

---

*Last updated: July 2026*
