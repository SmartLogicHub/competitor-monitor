# Current Date and Taobao Login Browser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Web manual runs always use the computer's current local date and add a safe button that opens the collection browser profile for buyer-account login without breaking automatic weekly-sheet creation.

**Architecture:** The Web UI will omit `run_date`, leaving the existing backend fallback (`today_provider`) as the authoritative local date while command-line explicit dates remain supported. A focused `manual_login.py` process will launch `BrowserService` with the same persistent profile, publish session state, periodically save storage state, and remain mutually exclusive with collection runs.

**Tech Stack:** Python 3.11, `unittest`, rebrowser-playwright, stdlib HTTP server/subprocess/threading, vanilla JavaScript/CSS, Node static tests, PyInstaller.

---

### Task 1: Restore the missing tracked source checkout

**Files:**
- Restore: `competitor_monitor/**`
- Restore: `web_frontend/**`
- Restore: `scripts/**`

- [ ] Copy only missing tracked source directories from the verified `f6f7756` local snapshot; preserve all existing Excel/config/runtime data.
- [ ] Compare restored files with the snapshot and list the workspace files before editing.

### Task 2: Lock Web manual runs to current local date

**Files:**
- Modify: `web_frontend/app.js`
- Modify: `web_frontend/index.html`
- Modify: `competitor_monitor/tests/test_web_api.py`
- Modify: `web_frontend/staticMarkup.test.cjs`
- Create or modify: `web_frontend/appBehavior.test.cjs`

- [ ] Write a failing frontend behavior test proving `buildRunPayload` omits `run_date` and the date field is current/read-only.
- [ ] Run the focused Node test and confirm the expected failure.
- [ ] Modify the UI so manual requests omit `run_date`; refresh the read-only date display using local calendar components.
- [ ] Write/adjust a backend test proving an omitted date uses injected `today_provider`, even when config contains an old date.
- [ ] Run the focused Node and Python tests and confirm they pass.

### Task 3: Preserve automatic current-week sheet creation

**Files:**
- Test: `competitor_monitor/tests/test_excel_service.py`
- Test: `competitor_monitor/tests/test_web_api.py`

- [ ] Add a regression test that starts from a workbook without the current-week sheet and verifies the existing `get_or_create_current_sheet` flow creates the expected sheet.
- [ ] Run the test before production changes to document that the behavior remains present.
- [ ] Keep Excel creation code unchanged unless the regression exposes a real defect.

### Task 4: Add the standalone Taobao login process

**Files:**
- Create: `competitor_monitor/manual_login.py`
- Modify: `competitor_monitor/browser_service.py`
- Create: `competitor_monitor/tests/test_manual_login.py`
- Modify: `competitor_monitor/tests/test_browser_service.py`

- [ ] Write failing tests for launching the same profile, opening Taobao, periodically saving storage state, and marking session closed on exit.
- [ ] Run focused tests and confirm they fail because the feature is absent.
- [ ] Add the smallest public BrowserService methods needed for a manual page and storage-state save.
- [ ] Implement the manual login loop and atomic state-file lifecycle.
- [ ] Run focused tests and confirm they pass.

### Task 5: Add backend session APIs and mutual exclusion

**Files:**
- Modify: `competitor_monitor/web_api.py`
- Modify: `competitor_monitor/web_server.py`
- Modify: `competitor_monitor/tests/test_web_api.py`
- Modify: `competitor_monitor/tests/test_web_server.py`

- [ ] Write failing tests for open/status endpoints, duplicate launch, launch while collecting, collection while login is open, process exit, and launch failure.
- [ ] Run focused tests and confirm expected failures.
- [ ] Add a process launcher that uses `web_server.py --manual-taobao-login` in source mode and the same Web EXE in frozen mode.
- [ ] Add shared session-state checks and clear Chinese error messages.
- [ ] Route `POST /api/session/open` and `GET /api/session/status`; add the internal CLI mode.
- [ ] Run focused tests and confirm they pass.

### Task 6: Add the account-card button and live status

**Files:**
- Modify: `web_frontend/index.html`
- Modify: `web_frontend/styles.css`
- Modify: `web_frontend/api.js`
- Modify: `web_frontend/app.js`
- Modify: `web_frontend/mockData.js`
- Modify: `web_frontend/staticMarkup.test.cjs`
- Modify: `web_frontend/mockData.test.cjs`

- [ ] Write failing static/API tests for the login button, status label, help copy, API call, and disabled states.
- [ ] Run focused Node tests and confirm expected failures.
- [ ] Add the button next to the existing reset action and implement loading, polling, toast, and mutual-exclusion UI states.
- [ ] Run all frontend tests and confirm they pass.

### Task 7: Verify packaging and the full system

**Files:**
- Modify if needed: `CompetitorMonitorWeb.spec`
- Modify: `competitor_monitor/tests/test_startup_scripts.py`
- Modify: `README.md`

- [ ] Add a packaging/startup regression test for the internal login mode.
- [ ] Update user documentation for current-date manual runs and buyer-account login.
- [ ] Run `python -m unittest discover -s competitor_monitor/tests -v`.
- [ ] Run every `web_frontend/*.test.cjs` file with Node.
- [ ] Run `python -m py_compile` on all modified Python modules.
- [ ] Inspect the final diff and verify no Excel, credentials, browser profiles, logs, or user runtime state were changed.
