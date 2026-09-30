# Taobao Login Flash Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the Taobao manual-login page from flashing once per second while reporting the real authentication state in the Web console.

**Architecture:** Keep the persistent Chrome profile as the primary session store. Poll authentication state without navigation, export storage only on the first authenticated transition and once on shutdown, then pass `auth_status` through the existing session-status API to the frontend.

**Tech Stack:** Python 3.11, rebrowser-playwright, unittest, vanilla JavaScript/Node tests, PyInstaller.

---

### Task 1: Lock the backend behavior with failing tests

**Files:**
- Modify: `competitor_monitor/tests/test_manual_login.py`
- Modify: `competitor_monitor/tests/test_web_api.py`

- [ ] Add a fake browser that remains open for several polls and changes from `login_required` to `authenticated`.
- [ ] Assert there is no state export on every poll, one export on authentication, and one shutdown attempt.
- [ ] Assert `auth_status` is written to and returned from the session state.
- [ ] Run the focused tests and confirm failure because the current loop exports every second and omits `auth_status`.

### Task 2: Implement non-refreshing authentication monitoring

**Files:**
- Modify: `competitor_monitor/browser_service.py`
- Modify: `competitor_monitor/manual_login.py`
- Modify: `competitor_monitor/web_api.py`

- [ ] Add a side-effect-free method that returns the current manual page authentication state.
- [ ] Replace per-second export with state polling.
- [ ] Export once when state first becomes authenticated and once during shutdown.
- [ ] Persist and return `auth_status`, retaining compatibility with older state files.
- [ ] Run focused backend tests and confirm they pass.

### Task 3: Display the real status in the Web console

**Files:**
- Modify: `web_frontend/app.js`
- Modify: `web_frontend/appBehavior.test.cjs`

- [ ] Add failing assertions for checking, login-required, verification-required, and authenticated labels.
- [ ] Map API `auth_status` values to concise Chinese text beside the button.
- [ ] Run frontend tests and confirm pass after the minimal implementation.

### Task 4: Verify and package

**Files:**
- Modify generated artifacts under `dist/`
- Replace: `竞品监控_另一台电脑部署包_20260721.zip`

- [ ] Run all Python tests.
- [ ] Run all frontend Node tests and syntax checks.
- [ ] Build both PyInstaller applications with the existing packaging script.
- [ ] Create a new ZIP containing both complete application folders and deployment instructions.
- [ ] Open and read every ZIP entry; assert both primary EXEs exist and no runtime credentials/session state are included.

