# 竞品监控 Excel 自动填报系统

本项目是一个本地运行的竞品监控工具，用于自动维护竞品监控 Excel：

- 成熟单品每日价格采集和活动识别。
- 淘宝/天猫页面 SKU 匹配，避免同链接多型号串价。
- 价格异常提醒，便于人工复核。
- 边界 BI 上新监控和上新区域填报。
- 周一到周五价格趋势分析。
- 本地 Web 控制台启动任务、查看状态、日志和结果。
- 任务完成后可由后端推送企业微信摘要和 Excel 文件。

## 安装

```bash
pip install -r competitor_monitor/requirements.txt
```

首次使用前，把示例配置复制为本地配置：

```bash
copy competitor_monitor\config.example.yaml competitor_monitor\config.yaml
```

然后按本机实际文件位置、浏览器配置和企业微信配置修改 `competitor_monitor/config.yaml`。

## 运行

命令行运行：

```bash
python competitor_monitor/main.py --mode daily_price --dry-run
python competitor_monitor/main.py --mode daily_price --limit 10
python competitor_monitor/main.py --mode daily_price --rows 24,54 --force-overwrite
python competitor_monitor/main.py --mode weekly_new
python competitor_monitor/main.py --mode price_trend
python competitor_monitor/main.py --mode all
```

Web 控制台运行：

```text
双击 启动Web.bat
```

或手动启动：

```bash
python competitor_monitor/web_server.py
```

然后打开：

```text
http://127.0.0.1:8765
```

## 后台自动运行

Web 页面只是控制台，不是自动通知的触发源。真正的后台自动任务使用：

```bash
python competitor_monitor/run_web_task.py --mode daily_price
python competitor_monitor/run_web_task.py --mode weekly_new
python competitor_monitor/run_web_task.py --mode price_trend
```

这个入口会复用 Web 后端服务层。任务完成后，如果 `competitor_monitor/config.yaml` 中启用了企业微信，后端会自动发送运行摘要和 Excel 文件。

## Windows 定时任务

创建本机定时任务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_windows_tasks.ps1
```

默认会创建 4 个任务：

- `CompetitorMonitor-WebConsole`：Windows 登录后启动本地 Web 控制台。
- `CompetitorMonitor-DailyPrice`：周一到周五 `10:00` 运行 `daily_price`。
- `CompetitorMonitor-WeeklyNew`：周六 `09:30` 运行 `weekly_new`。
- `CompetitorMonitor-PriceTrend`：周五 `18:30` 运行 `price_trend`。

自定义时间：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_windows_tasks.ps1 -DailyTime "10:30" -WeeklyNewTime "09:30" -PriceTrendTime "18:30"
```

删除这些定时任务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\remove_windows_tasks.ps1
```

## 打包 exe

构建 exe：

```text
双击 打包EXE.bat
```

构建完成后会生成：

- `dist\CompetitorMonitorWeb\CompetitorMonitorWeb.exe`
- `dist\CompetitorMonitorTaskRunner\CompetitorMonitorTaskRunner.exe`

打包产物不会包含你的 Excel、浏览器登录态、secrets、日志和备份。正式使用前，需要在运行目录放置 Excel 文件，并按实际环境配置 `competitor_monitor/config.yaml`。

如果要让 Windows 定时任务使用 exe 版本：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_windows_tasks.ps1 -UseExe
```

## 安全说明

仓库默认不提交以下本地数据：

- Excel 原始文件、验收文件、导出文件。
- `competitor_monitor/config.yaml` 本地真实配置。
- `competitor_monitor/secrets/` 账号密码。
- `browser_profile*` 浏览器登录态。
- `logs/` 日志。
- `backup/` Excel 备份。

这些文件可能包含业务数据、账号、Cookie、登录状态或企业微信 Webhook，不应上传到 GitHub。

## 测试

前端静态测试：

```bash
node web_frontend\uiState.test.cjs
node web_frontend\mockData.test.cjs
node web_frontend\staticMarkup.test.cjs
node web_frontend\stylePalette.test.cjs
node web_frontend\uiStateFillText.test.cjs
```

后端测试：

```bash
cd competitor_monitor
python -m unittest discover -s tests -v
```
