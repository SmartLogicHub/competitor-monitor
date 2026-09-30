# Tmall Promotion Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collect explicit Tmall promotional prices and activity labels only after their asynchronous DOM content has rendered, then produce a verified replacement deployment package.

**Architecture:** `ProductCollector` will poll the page body for labelled promotion-price markers or configured activity keywords for a bounded period. The settled body text drives both activity recognition and the explicit promotional-price candidate, which takes precedence over the matched SKU initial-data/base price only when the page includes a recognised price label.

**Tech Stack:** Python 3.11, rebrowser-playwright, unittest, PyInstaller.

---

### Task 1: Establish failing collector regressions

**Files:**

- Modify: `competitor_monitor/tests/test_collector.py`
- Modify: `competitor_monitor/tests/test_main.py` only if an end-to-end flow assertion is needed

- [ ] **Step 1: Write a fake page whose body promotion text appears on a later read**

  Model a T6magic-like sequence: the first body read contains only title/SKU
  text; a later read contains `平台加补后 ¥170 起` plus `超级立减` and
  `首单礼金`.

- [ ] **Step 2: Add the failing behavior tests**

  Assert that the collector waits for the delayed content, writes `170` rather
  than an initial SKU base price such as `279`, and recognises both activities.
  Add a no-promotion timeout test proving SKU/base-price fallback remains
  available.

- [ ] **Step 3: Run the focused tests and confirm RED**

  Run: `python -m unittest competitor_monitor.tests.test_collector`

  Expected: the newly added delayed-promotion assertions fail because the
  current collector reads the first body snapshot and returns SKU base price.

### Task 2: Add bounded promotion-readiness collection

**Files:**

- Modify: `competitor_monitor/collector.py`
- Modify: `competitor_monitor/config.example.yaml`

- [ ] **Step 1: Add a small polling helper**

  The helper must read body text at a configured interval, stop as soon as an
  explicit price marker or configured activity keyword appears, and return the
  latest text on timeout. It must not require a promotion for ordinary products.

- [ ] **Step 2: Use the settled text throughout `collect_from_page`**

  Use the settled text for activity recognition and calculate the explicit
  priority price before SKU lookup. When such a labelled price exists, it wins
  over the SKU initial-data price; otherwise retain current SKU behavior.

- [ ] **Step 3: Add conservative configuration defaults**

  Add a 12-second maximum wait and 0.5-second poll interval with clear names.

- [ ] **Step 4: Run the focused tests and confirm GREEN**

  Run: `python -m unittest competitor_monitor.tests.test_collector`

  Expected: all collector tests pass, including new delayed-content and
  no-promotion fallback tests.

### Task 3: Verify collection flow and package output

**Files:**

- Modify only if required by Task 2 test failures
- Build output: `dist/`, `竞品监控_另一台电脑部署包_20260721*.zip`

- [ ] **Step 1: Run the affected main-flow tests**

  Run: `python -m unittest competitor_monitor.tests.test_main`

- [ ] **Step 2: Run the project regression suite**

  Run: `python -m unittest discover -s competitor_monitor/tests`

- [ ] **Step 3: Repeat the authenticated T6magic DOM probe**

  Verify the page still adds promotion markers after the initial DOM state and
  that the new collector waits for them rather than taking the early SKU price.

- [ ] **Step 4: Rebuild executables and deployment archive**

  Run the existing `打包EXE.bat`, verify the two EXEs and package timestamps,
  and create one new, date-stamped deployment ZIP without replacing the
  previous package.

- [ ] **Step 5: Deliver deployment instructions**

  Explain that the old runtime `config.yaml` and browser profile should be
  preserved, while the two application folders are replaced as a matched pair.
