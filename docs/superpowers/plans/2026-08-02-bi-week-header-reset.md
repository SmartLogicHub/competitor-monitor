# BI Week Header Reset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure automatically copied weekly sheets update BI date headers and clear all copied BI runtime data.

**Architecture:** Extend `ExcelService.prepare_copied_sheet()` to update the five BI date headers in the copied sheet while retaining the existing row-4-and-below BI clear. Protect the behavior with an end-to-end workbook-copy regression test and visually verify a generated sample.

**Tech Stack:** Python 3.11, openpyxl application runtime, unittest, `@oai/artifact-tool` for final workbook visual verification, PyInstaller.

---

### Task 1: Reproduce the stale BI header

**Files:**
- Modify: `competitor_monitor/tests/test_excel_service.py`

- [ ] Expand the sample template with BI headers in `J1:S3` and old BI data in rows 4-5.
- [ ] Assert a copied week updates both `C3:G3` and `N3:R3`.
- [ ] Assert copied BI data in `J4:S5` is blank while header cells remain intact.
- [ ] Run the focused test and confirm it fails specifically because `N3:R3` retains the prior week.

### Task 2: Update BI date headers

**Files:**
- Modify: `competitor_monitor/excel_service.py`

- [ ] Locate the BI live-price date header cells inside the right-side region.
- [ ] Write the same five target-week labels used by the mature-product section.
- [ ] Raise `WorkbookLayoutError` when a BI region exists but five date headers cannot be identified.
- [ ] Run the focused test and confirm it passes.

### Task 3: Verify and package

**Files:**
- Rebuild: `dist/CompetitorMonitorWeb/`
- Rebuild: `dist/CompetitorMonitorTaskRunner/`
- Create: `竞品监控_另一台电脑部署包_20260802.zip`

- [ ] Run all Python and frontend tests plus syntax checks.
- [ ] Generate a copied future-week sheet from the supplied workbook in a separate output file and visually verify the top region.
- [ ] Rebuild both EXEs with the existing packaging script.
- [ ] Create and fully read the new ZIP, checking both primary EXEs and absence of runtime credentials/session files.

