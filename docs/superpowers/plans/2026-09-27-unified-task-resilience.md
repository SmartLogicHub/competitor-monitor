# 竞品监控统一容错实现计划

## 目标

修复 EXE 运行中的 Playwright 驱动断线级联失败、Web 手动周末 BI 静默跳过、权威空结果不写“无上新”、子任务失败仍显示成功，以及计划任务失败后不重启的问题，并重新构建两个 EXE。

## 任务 1：浏览器运行时恢复

涉及：`browser_service.py`、`main.py`、`tests/test_browser_service.py`、`tests/test_main.py`

1. 先增加断线分类、运行时重启、当前商品恢复成功与恢复耗尽致命停止的失败测试。
2. 为 `BrowserService` 拆出启动/停止生命周期，并实现 `restart_after_disconnect()`。
3. `collect_with_retry()` 仅对断线错误重启运行时并重试当前 URL；耗尽时抛出专用致命异常。
4. `run_collection()` 不吞掉专用致命异常，避免后续商品级联失败。

## 任务 2：周末 BI 手动执行与空结果语义

涉及：`web_frontend/app.js`、`main.py`、`bi_service.py`、`new_product_writer.py` 及对应测试。

1. 先增加 Web 手动 payload、非运行日手动执行、权威空结果覆盖旧区、失败店铺不写“无上新”的失败测试。
2. Web 手动请求携带 `manual_run=true`，后端仅在该标记存在时绕过运行日限制。
3. BI 店铺请求逐店有限重试并隔离，返回成功/失败店铺与失败详情。
4. 写表只对结果确定的空品牌写“无上新”，并统计已确认空品牌数和本次新写数。

## 任务 3：统一结果和补跑隔离

涉及：`web_api.py`、`run_web_task.py`、`web_frontend/uiState.js` 及对应测试。

1. 增加失败条目导致 `partial_success`、多日期补跑继续执行、前端部分成功文案和退出码测试。
2. Web 批次安全结束但存在失败项时标记 `partial_success`。
3. 每个补跑日期独立捕获并记录失败。
4. 后台执行器按成功、部分成功、失败、停止返回不同退出码。

## 任务 4：配置和 Windows 重启策略

涉及：`web_api.py`、`scripts/install_windows_tasks.ps1`、`config.example.yaml` 及对应测试。

1. 增加保存间隔规范化和两条计划任务生成路径的重启策略测试。
2. 持久化规范键 `save_every_n_products`，兼容旧键 `save_every`。
3. 计划任务设置 10 分钟重试、最多 3 次。
4. 增加浏览器和 BI 重试默认配置。

## 任务 5：验证和打包

1. 运行目标测试并确认全部通过。
2. 运行后端和前端全量测试。
3. 执行项目现有打包脚本构建 Web 控制台与 TaskRunner。
4. 检查产物、启动参数与配置排除规则，整理另一台电脑的保数据替换步骤。
