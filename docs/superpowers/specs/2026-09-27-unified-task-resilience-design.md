# 竞品监控统一容错设计

## 背景

另一台电脑运行 EXE 版时，价格采集进行到第 15/99 条后出现：

`BrowserContext.new_page: Connection closed while reading from the driver`

现有商品级循环会捕获异常并继续，但重试和后续商品仍复用已经断开的 Playwright 浏览器对象。因此界面看起来仍在运行，实际后续采集已经失去恢复能力。项目中还存在任务结果、补跑隔离、BI 店铺隔离、保存间隔配置和 Windows 计划任务策略不一致的问题。

## 目标

1. 浏览器驱动或 BrowserContext 断开时，自动重启浏览器运行时并重试当前商品。
2. 普通单商品、单补跑日期、单 BI 店铺失败时，记录失败并继续其余工作。
3. 浏览器连续恢复失败、Excel 无法加载或模板结构错误时，终止当前批次并报告明确的致命错误。
4. Web、命令行和定时 EXE 对任务结果使用同一语义：`success`、`partial_success`、`failed`、`stopped`。
5. 定时任务遇到非成功退出时，10 分钟后重启，最多 3 次。
6. 手动和定时运行统一使用同一个保存间隔配置。
7. 重新打包 Web 控制台和后台任务执行器；部署时保留另一台电脑的 Excel、配置、登录态、凭据、日志和状态文件。
8. Web 手动运行和“补跑上次 BI”必须真正执行目标周期，不受定时任务运行日开关限制。
9. BI 成功且权威地返回空结果时，目标品牌必须落入“无上新”；BI 请求失败时不得误写“无上新”。

## 非目标

- 不绕过淘宝或 BI 的验证码、安全验证和人工登录。
- 不无限重试，也不在无法确认写入状态时重复覆盖 Excel。
- 不重写现有采集、SKU 匹配或价格判断业务规则。
- 不逆向已有 EXE；源码是唯一修改来源。

## 失败分级

### 可恢复的浏览器传输失败

错误文本包含下列稳定特征之一时，判定为浏览器运行时已断开：

- `Connection closed while reading from the driver`
- `Target page, context or browser has been closed`
- `Browser has been closed`
- `BrowserContext.new_page` 与 `closed`/`connection` 的组合
- Playwright driver/connection closed 的等价错误

处理顺序：

1. 关闭残留 BrowserContext；异常忽略。
2. 停止残留 Playwright driver；异常忽略。
3. 按配置等待短暂随机退避。
4. 使用原 `user_data_dir`、storage state 和启动参数重新启动 Playwright 与持久化 Chrome context。
5. 按现有登录规则确认登录状态。
6. 重试当前商品，而不是直接进入下一条。

恢复次数受 `browser_restart_retry_count` 控制，默认 2 次。连续恢复失败后抛出专用致命异常，避免后续几十条商品在同一个失效对象上连续失败。

### 普通条目失败

超时、页面无明确价格、型号无法确认等普通条目错误沿用现有低频重试。重试耗尽后记录该商品失败并继续下一条。批次最终状态为 `partial_success`。

### 致命任务失败

以下错误立即终止当前批次：

- 浏览器运行时连续恢复失败。
- Excel 无法加载或安全保存。
- 模板结构无法识别。
- 配置无法解析或必要运行文件缺失。

任务状态为 `failed`，保留完整 traceback，后台 EXE 返回非零退出码。

## 浏览器生命周期

`BrowserService` 负责完整的 Playwright 生命周期，新增明确边界：

- `_start_runtime()`：启动 driver、persistent context 并恢复 storage state。
- `_stop_runtime()`：尽力关闭 context 和 driver，且始终清空旧引用。
- `restart_after_disconnect()`：停止旧运行时、退避、启动新运行时、按配置检查淘宝登录。
- `is_disconnect_error()`：集中识别断线错误，避免业务层散落字符串判断。
- `BrowserSessionUnavailableError`：恢复耗尽后的致命错误类型。

`collect_with_retry()` 在捕获断线错误后先调用恢复，再重试当前 URL。普通网络或页面错误继续走原有重试，不无条件重启整个浏览器。

## 任务结果语义

统一最终状态计算：

- `stopped`：收到人工停止请求。
- `failed`：任务抛出致命异常，未能安全完成批次。
- `partial_success`：批次安全结束，但 `failed_count > 0` 或子任务报告失败。
- `success`：批次安全结束且无失败项。

后台执行器退出码：

- `0`：`success`
- `2`：`partial_success`
- `1`：`failed`
- `3`：`stopped`

Web 页面把 `partial_success` 显示为“部分成功”，使用警告色，并提示重新运行会跳过已有结果、补采失败项。

## 补跑与 BI 隔离

多日期补跑在每个日期外围独立捕获异常。某天失败时：记录日期级失败结果和 traceback，然后继续下一个日期。最终根据失败数计算 `partial_success`。

BI 店铺查询在每个店铺外围独立捕获异常，并对请求做有限重试。失败店铺写入 `BICollectResult.failure_details`；其他店铺继续查询。写入统计合并 BI 查询失败，确保 Web 状态和企业微信摘要不会误报完全成功。

Web 发起的手动运行和“补跑上次 BI”在 payload 中携带 `manual_run=true`。该标记只绕过定时运行日限制，不绕过登录、模板、Excel 保存或 BI 请求校验。后台计划任务与 CLI 仍遵守 `new_product_allowed_weekdays`。

BI 写表区分三种情况：

- 店铺列表和相关店铺请求成功，某品牌无周期内商品：这是权威空结果，清理该品牌右侧旧数据并写“无上新”。
- 某品牌对应店铺请求失败：该品牌结果未知，不覆盖为“无上新”，记录失败详情并把任务标记为 `partial_success`。
- “无上新”已存在：计入已确认的无上新品牌数，但不重复改写单元格。Web 摘要同时展示“无上新品牌数”和“本次新写标记数”，避免再次出现 `0/0/0/0` 的假成功观感。

## 配置与计划任务

配置统一以 `save_every_n_products` 为持久化键，同时兼容读取旧的 `save_every`。Web 保存配置时同步写入规范键，手动和定时运行都读取相同值。

新增默认配置：

- `browser_restart_retry_count: 2`
- `browser_restart_min_delay_seconds: 3`
- `browser_restart_max_delay_seconds: 8`
- `bi_request_retry_count: 2`

Windows 计划任务统一设置：

- `RestartCount = 3`
- `RestartInterval = 10 分钟`
- `StartWhenAvailable`
- `MultipleInstances = IgnoreNew`
- `ExecutionTimeLimit = 8 小时`

安装脚本和 Web 配置同步路径使用相同设置。BI 运行日以 `new_product_allowed_weekdays` 为准；安装脚本默认与示例配置保持一致。

## 数据安全

- 浏览器恢复复用现有 profile 和 storage state，不打印 Cookie、账号或密码。
- Excel 仍通过现有临时文件/接管机制安全保存。
- 恢复前后的错误写入日志，但结果持久化继续清洗商品 URL 跟踪参数。
- 打包产物不包含真实 `config.yaml`、secrets、浏览器 profile、Excel 或日志。

## 测试与验收

必须先编写并观察失败的回归测试，再实现：

1. `BrowserService` 能识别截图中的 driver connection closed 错误。
2. 断线后关闭旧运行时、启动新运行时并复用 profile/storage state。
3. 当前商品断线一次后恢复并成功，下一商品继续正常处理。
4. 连续恢复失败时抛出致命异常，不产生大量级联商品失败。
5. Web 中 `failed_count > 0` 且无致命异常时为 `partial_success`。
6. 多日期补跑第一天失败时仍会执行后续日期。
7. BI 第一家店失败时仍会查询后续店铺，并报告部分失败。
8. 手动和定时运行读取相同保存间隔。
9. 两条计划任务创建路径都包含相同失败重启设置。
10. 周日未启用定时运行时，Web 手动 BI 仍会执行；计划任务仍会跳过。
11. BI 权威空结果会覆盖旧商品区为“无上新”，失败店铺对应品牌不会误写。
12. 后端、前端全量测试通过，两个 PyInstaller EXE 成功构建。

## 部署

另一台电脑先退出 Web 控制台和后台任务，只替换重新构建的程序文件。部署过程必须保留：

- `CompetitorMonitorWeb/competitor_monitor/config.yaml`
- Excel 主文件与运行副本
- `browser_profile*`
- `secrets/`
- `logs/`
- `web_state/`

替换后重新同步 Windows 计划任务，并用一条测试商品验证浏览器启动、登录态、Excel 保存和 Web 状态。
