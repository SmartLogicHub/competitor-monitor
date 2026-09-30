# Tmall Explicit Delisting Variant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 识别天猫“商品已经下架啦”明确文案，避免把下架页残留价格写入 Excel。

**Architecture:** 在现有 `ProductCollector.page_is_explicitly_unavailable()` 精确文案列表中补充“已经下架”变体。保持 `ProductSnapshot.explicitly_unavailable` 与 `main.run_collection()` 的现有数据流不变，由现有下架分支写入 `/`。

**Tech Stack:** Python 3.11、`unittest`、rebrowser-playwright、PyInstaller。

---

### Task 1: 建立截图场景回归测试

**Files:**
- Modify: `competitor_monitor/tests/test_collector.py`
- Test: `competitor_monitor/tests/test_collector.py`

- [ ] **Step 1: 写入失败测试**

```python
def test_page_with_already_delisted_banner_ignores_stale_price(self):
    page = FakeSkuPage(
        {},
        base_text="Sony WH-1000XM4 ￥2499 商品已经下架啦~要不要瞧瞧别的~",
    )
    snapshot = self.collector.collect_from_page(page, expected_model="WH-1000XM4")
    self.assertTrue(snapshot.explicitly_unavailable)
    self.assertIsNone(snapshot.price)
```

- [ ] **Step 2: 验证测试因缺少文案匹配而失败**

Run: `python -m unittest tests.test_collector.ProductCollectorTest.test_page_with_already_delisted_banner_ignores_stale_price`

Expected: FAIL，`snapshot.explicitly_unavailable` 为 `False`。

### Task 2: 最小修复明确下架文案

**Files:**
- Modify: `competitor_monitor/collector.py:119-136`
- Test: `competitor_monitor/tests/test_collector.py`

- [ ] **Step 1: 在精确 marker 列表中加入四个“已经下架”变体**

```python
"商品已经下架",
"此商品已经下架",
"宝贝已经下架",
"此宝贝已经下架",
```

- [ ] **Step 2: 运行新增测试并确认通过**

Run: `python -m unittest tests.test_collector.ProductCollectorTest.test_page_with_already_delisted_banner_ignores_stale_price`

Expected: PASS。

- [ ] **Step 3: 运行相关下架与未确认型号测试**

Run: `python -m unittest tests.test_collector.ProductCollectorTest.test_page_with_explicit_delisting_marker_is_classified_as_unavailable tests.test_main.RunCollectionCheckpointTest.test_run_collection_writes_slash_only_for_explicitly_unavailable_page tests.test_main.RunCollectionCheckpointTest.test_run_collection_does_not_write_slash_when_page_model_is_unconfirmed`

Expected: 3 tests PASS。

### Task 3: 真实低速复测

**Files:**
- Read: 用户截图对应的 Excel 行和链接
- Modify: 仅测试副本

- [ ] **Step 1: 定位 WH-1000XM4 对应测试行和链接**
- [ ] **Step 2: 只运行该行，保留正常页面等待和商品间隔**
- [ ] **Step 3: 检查日志包含明确下架记录，Excel 价格和活动均为 `/`**

### Task 4: 完整验证与部署

**Files:**
- Rebuild: `dist/CompetitorMonitorWeb/`
- Rebuild: `dist/CompetitorMonitorTaskRunner/`
- Create/replace: `release/` 中最终部署包

- [ ] **Step 1: 运行完整 Python 测试与编译检查**

Run: `python -m unittest discover -s tests -p 'test_*.py'`（工作目录 `competitor_monitor`）

Run: `python -m py_compile collector.py main.py`

- [ ] **Step 2: 运行五个前端测试文件**

Run: `node uiState.test.cjs`、`node mockData.test.cjs`、`node staticMarkup.test.cjs`、`node stylePalette.test.cjs`、`node uiStateFillText.test.cjs`

- [ ] **Step 3: 执行 `打包EXE.bat` 并确认两个 EXE 构建成功**
- [ ] **Step 4: 压缩最终部署包，校验 SHA-256 与敏感文件数量为 0**
