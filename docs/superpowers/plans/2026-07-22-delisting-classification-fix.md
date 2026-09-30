# 商品下架误判修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The user explicitly prohibited subagents, so execute inline.

**Goal:** 修复普通单型号商品因 SKU 未重复型号数字而被写成 `/` 的回归，同时保留多型号和具体礼盒的精确匹配保护。

**Architecture:** `ProductCollector` 负责把页面分类为正常、明确下架或具体礼盒/套餐缺失；`main.run_collection` 只根据明确分类决定是否写 `/`。普通页面型号无法确认时转为未确认失败，不再冒充下架。

**Tech Stack:** Python 3、unittest、openpyxl、Playwright 既有页面抽象、PyInstaller 既有构建脚本。

---

### Task 1: 用失败测试复现普通数字型号误判

**Files:**
- Modify: `competitor_monitor/tests/test_collector.py`
- Test: `competitor_monitor/tests/test_collector.py`

- [ ] 添加 `WH-1000XM5` 标题匹配但 SKU 只有颜色的测试，期望能读取页面优惠价且 `model_variant_missing=False`。
- [ ] 添加普通数字型号不产生具体礼盒/套餐标记的测试，覆盖 `A30S PRO`、`W04`、`WH-CH520`。
- [ ] 运行 `python -X utf8 -m unittest tests.test_collector.ProductCollectorTest.<new_test>`，确认测试因当前数字 SKU 强制检查失败。

### Task 2: 收窄具体子型号标记

**Files:**
- Modify: `competitor_monitor/collector.py:434-448`
- Modify: `competitor_monitor/collector.py:618-638`
- Test: `competitor_monitor/tests/test_collector.py`

- [ ] 让 `specific_model_variant_tokens()` 仅在 `requires_specific_package()` 为真时返回数字与礼盒/套餐标记。
- [ ] 保留 `S7S Ultra 520告白礼盒` 的 `520 + 礼盒` 检查。
- [ ] 运行新增测试和现有 `test_collector.py`，确认普通单型号通过且礼盒、多型号回归不退化。

### Task 3: 区分明确下架与型号未确认

**Files:**
- Modify: `competitor_monitor/collector.py:11-23`
- Modify: `competitor_monitor/collector.py:72-110`
- Modify: `competitor_monitor/main.py:700-760`
- Modify: `competitor_monitor/tests/test_collector.py`
- Modify: `competitor_monitor/tests/test_main.py`

- [ ] 添加明确下架正文识别的失败测试。
- [ ] 给 `ProductSnapshot` 添加 `explicitly_unavailable` 并从页面正文计算。
- [ ] 添加运行层测试：明确下架写 `/`；普通型号未确认不写 `/`，结果为失败；具体礼盒缺失仍写 `/`。
- [ ] 修改 `run_collection()` 的分支和日志，使三种状态分别处理。
- [ ] 修改重试条件，使明确下架和已确认具体子型号缺失不做无意义的空价格重试。
- [ ] 运行新增定向测试，确认红—绿过程。

### Task 4: 全量验证

**Files:**
- Verify: `competitor_monitor/tests/`
- Verify: `competitor_monitor/collector.py`
- Verify: `competitor_monitor/main.py`

- [ ] 运行 `python -X utf8 -m unittest discover -s tests`，要求零失败。
- [ ] 运行 `python -X utf8 -m py_compile collector.py main.py`，要求退出码为 0。
- [ ] 检查改动范围，确认没有修改 Excel、Cookie、浏览器状态或用户日志。

### Task 5: 构建新部署包

**Files:**
- Build: `CompetitorMonitorWeb.spec`
- Build: `CompetitorMonitorTaskRunner.spec`
- Create: `release/CompetitorMonitor_20260722_delisting_fix/`
- Create: `release/竞品监控_另一台电脑部署包_20260722_下架误判修复.zip`

- [ ] 使用项目既有 PyInstaller 构建命令重新生成 Web 与 TaskRunner。
- [ ] 检查构建目录包含两个 EXE 和部署说明。
- [ ] 扫描 ZIP，确认不包含 `browser_profile`、`storage_state.json`、Cookie、账号密码、日志、Excel、输出目录。
- [ ] 计算并报告 SHA-256。
