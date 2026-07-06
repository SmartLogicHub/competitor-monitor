# SKU Matching v1.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make mature-product price collection SKU-aware so rows sharing one item link are not filled with the page's default selected SKU price.

**Architecture:** Add a pure matching module for model/SKU text normalization and confidence scoring. Extend the collector to optionally select matched SKU options before extracting visible prices. Keep Excel writing and business flow unchanged except for passing `expected_model` when a product URL is shared by multiple Excel model rows.

**Tech Stack:** Python, rebrowser-playwright-compatible Playwright API, openpyxl, unittest.

---

### Task 1: Pure SKU Matching

**Files:**
- Create: `competitor_monitor/sku_service.py`
- Test: `competitor_monitor/tests/test_sku_service.py`

- [ ] Write failing tests for `S6S proII` matching `Pro2...` options and `S6S ultra` matching `Ultra...` options.
- [ ] Implement normalization for spaces, case, roman numeral/proII variants, and token scoring.
- [ ] Verify unmatched/ambiguous low-confidence options return an empty list.

### Task 2: Collector SKU Selection

**Files:**
- Modify: `competitor_monitor/collector.py`
- Test: `competitor_monitor/tests/test_collector.py`

- [ ] Write failing tests with a fake Playwright page that exposes SKU option texts and prices after click.
- [ ] Add optional `expected_model` to `collect_from_page`.
- [ ] When `expected_model` is provided, collect all confidently matched SKU options, click each option, extract price, and return a compact labeled price summary.
- [ ] If no SKU matches, return `price=None` and preserve recognized activities from the page text.

### Task 3: Main Flow Integration

**Files:**
- Modify: `competitor_monitor/main.py`
- Modify: `competitor_monitor/config.yaml`
- Test: `competitor_monitor/tests/test_main.py`

- [ ] Add `enable_sku_matching: true`.
- [ ] For duplicate item-id rows, pass the Excel model name as `expected_model` instead of skipping.
- [ ] Keep the old hard skip path when `enable_sku_matching` is false.
- [ ] Verify duplicate-link rows call collection with their own model names.

### Task 4: Verification

**Commands:**
- `python -m unittest discover -s tests -v`
- `python -X "pycache_prefix=$env:TEMP\codex_pycache_check" -m py_compile activity_service.py bi_service.py browser_service.py collector.py config_service.py credential_service.py date_service.py excel_service.py logger_service.py main.py new_product_service.py new_product_writer.py sku_service.py`
- `python competitor_monitor\main.py --mode daily_price --dry-run --date 2026-07-03`

