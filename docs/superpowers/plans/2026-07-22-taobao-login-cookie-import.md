# Taobao Login Page and Cookie Import Implementation Plan

> **For agentic workers:** Implement inline in this session because the user explicitly prohibited subagents. Follow test-first steps below.

**Goal:** Open a real monitored Tmall product page for manual login verification and support safe local import of Taobao/Tmall cookies.

**Architecture:** `WebApiService` resolves the first valid monitored product hyperlink and passes it to the existing manual-login subprocess. A focused cookie normalization/import function validates supported JSON formats and atomically updates the configured storage-state file. The local frontend uploads the selected JSON file through a dedicated endpoint.

**Tech Stack:** Python 3.11, `unittest`, `openpyxl`, local HTTP server, vanilla JavaScript/HTML, PyInstaller.

---

### Task 1: Manual login opens a monitored Tmall page

**Files:**
- Modify: `competitor_monitor/manual_login.py`
- Modify: `competitor_monitor/web_server.py`
- Modify: `competitor_monitor/web_api.py`
- Test: `competitor_monitor/tests/test_manual_login.py`
- Test: `competitor_monitor/tests/test_web_api.py`
- Test: `competitor_monitor/tests/test_web_server.py`

- [ ] Add failing tests for an explicit login URL and Tmall fallback.
- [ ] Add a failing test that the Web API selects the first valid Excel hyperlink and includes `--login-url` in the child command.
- [ ] Run targeted tests and confirm expected assertion failures.
- [ ] Implement URL validation, workbook hyperlink selection, CLI argument forwarding, and fallback.
- [ ] Run targeted tests and confirm they pass.

### Task 2: Safe Cookie import backend

**Files:**
- Create: `competitor_monitor/taobao_cookie_service.py`
- Modify: `competitor_monitor/web_api.py`
- Modify: `competitor_monitor/web_server.py`
- Test: `competitor_monitor/tests/test_taobao_cookie_service.py`
- Test: `competitor_monitor/tests/test_web_api.py`
- Test: `competitor_monitor/tests/test_web_server.py`

- [ ] Add failing tests for storage-state JSON, Cookie-Editor arrays, filtering, invalid JSON, and no eligible cookies.
- [ ] Run tests and verify failures are caused by missing behavior.
- [ ] Implement normalization and atomic storage-state replacement without logging secrets.
- [ ] Add the service method and multipart HTTP route, blocking import while login/collection is active.
- [ ] Run targeted backend tests and confirm they pass.

### Task 3: Cookie import controls

**Files:**
- Modify: `web_frontend/index.html`
- Modify: `web_frontend/api.js`
- Modify: `web_frontend/app.js`
- Modify: `web_frontend/staticMarkup.test.cjs`
- Modify: `web_frontend/appBehavior.test.cjs`

- [ ] Add failing static tests for the file input, import button, API call, and event handler.
- [ ] Run frontend tests and confirm expected failures.
- [ ] Add the local JSON picker, upload API method, handler, busy state, and success/error toast.
- [ ] Run frontend tests and confirm they pass.

### Task 4: Regression and deployment

**Files:**
- Modify if needed: `competitor_monitor/config.example.yaml`
- Rebuild: `release/CompetitorMonitor_20260722_login_cookie_fix/`
- Create: `release/竞品监控_另一台电脑部署包_20260722_登录与Cookie修复.zip`

- [ ] Run the full Python test suite.
- [ ] Run all frontend Node tests.
- [ ] Run Python syntax compilation.
- [ ] Build Web and TaskRunner executables using the existing PyInstaller process.
- [ ] Verify both executables, config example, frontend assets, and deployment instructions are in the ZIP.
- [ ] Do not include runtime `browser_profile`, `storage_state.json`, credentials, logs, backups, or output workbooks in the ZIP.
