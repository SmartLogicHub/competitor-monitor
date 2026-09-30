# 型号价格选择 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从页面 SKU 中按已确认的基础款、Pro、Ultra 和礼盒规则取得可写价格。

**Architecture:** `ProductCollector` 已能读取初始 SKU JSON；扩展其套餐与型号筛选，而不改变 Excel 布局或页面活动识别。测试使用现有初始 SKU HTML 构造器模拟页面套餐与型号维度。

**Tech Stack:** Python 3、unittest、openpyxl（既有 Excel 层）、Playwright（既有浏览器层）。

---

### Task 1: 型号/套餐筛选回归测试

**Files:**
- Modify: `competitor_monitor/tests/test_collector.py`
- Test: `competitor_monitor/tests/test_collector.py`

- [ ] 写失败测试：基础 `S7S` 在 `AI2`、`Ultra` SKU 同时存在时选基础 `AI2`。
- [ ] 写失败测试：`S7S Ultra` 在 SKU 标签只写 `Ultra` 时选 Ultra。
- [ ] 写失败测试：礼盒套餐存在时优先选礼盒 Ultra；缺少礼盒套餐时选官方标配 Ultra。
- [ ] 写失败测试：`S7S Ultra 520告白礼盒` 缺少具体礼盒套餐时写入 `/`。
- [ ] 运行 `python -X utf8 -m unittest discover -s tests -p test_collector.py`，确认新增测试因现有精确型号匹配/固定官方标配逻辑失败。

### Task 2: 最小型号与套餐选择实现

**Files:**
- Modify: `competitor_monitor/collector.py`
- Test: `competitor_monitor/tests/test_collector.py`

- [ ] 增加“基础/升级型号”和“礼盒套餐偏好”辅助函数。
- [ ] 让初始 SKU 数据按礼盒优先选择套餐；缺少具体礼盒套餐时标记目标子型号不存在并写入 `/`。
- [ ] 让基础型号排除 Pro/Ultra，Pro/Ultra 可按升级标记匹配，不要求重复基础型号文本。
- [ ] 运行同一测试命令，确认新增与原有测试通过。

### Task 3: 全量验证与交付准备

**Files:**
- Verify: `competitor_monitor/tests/`
- Verify: `CompetitorMonitorWeb.spec`

- [ ] 运行 `python -X utf8 -m unittest discover -s tests`。
- [ ] 重新打包 Web EXE，并核对其中包含最新 collector 逻辑。
- [ ] 不启动全量商品任务；只交付新部署包并标注旧 EXE 不可再使用。
