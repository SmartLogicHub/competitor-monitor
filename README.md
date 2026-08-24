# 竞品监控 Excel 自动填报系统

一个本地运行的竞品监控系统，用于维护业务 Excel：采集淘宝/天猫商品价格与活动、匹配 SKU、识别价格异常、同步 BI 上新信息，并通过本地 Web 控制台或 Windows 定时任务持续运行。

> [!IMPORTANT]
> 本项目会访问电商页面并改写本地 Excel。请仅处理已获授权的数据，遵守相关平台规则，并先使用 `--dry-run` 或小范围行号验证配置。验证码、登录确认与平台风控必须由人工处理。

## 适用场景

- 成熟单品的工作日价格采集与活动识别；
- 同一商品链接下的 SKU 匹配，减少型号串价；
- 价格变动异常提醒与人工复核；
- BI 新品监控和上新区域填报；
- 周一至周五价格趋势分析；
- 企业微信运行摘要与结果文件通知；
- 本地 Web 控制台和 Windows 后台定时执行。

如果只需要上传一张表，补齐商品价格和耳机形态，可以使用更轻量的 [淘天竞品监控控制台](https://github.com/SmartLogicHub/taotian-competitor-monitor)。

| 项目 | 本仓库 | 淘天竞品监控控制台 |
| --- | --- | --- |
| 使用方式 | 配置驱动、长期运行 | 上传表格、单次补全 |
| 数据范围 | 价格、活动、SKU、BI 上新、趋势 | 页面显示价、耳机形态 |
| 调度 | 命令行、Web、Windows 定时任务 | 本地 Web 手动启动 |
| 通知 | 可选企业微信摘要与文件 | 以本地结果文件为主 |

## 安装

建议在 Windows 上使用 Python 虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r competitor_monitor\requirements.txt
Copy-Item competitor_monitor\config.example.yaml competitor_monitor\config.yaml
```

然后按实际环境修改 `competitor_monitor/config.yaml`，重点检查：

- `excel_path`、备份和日志目录；
- 浏览器 profile、Chrome 路径和人工操作等待时间；
- 淘宝、BI 登录方式与本地凭据路径；
- 价格异常阈值、SKU 匹配和覆盖策略；
- 企业微信 Webhook 与文件发送开关；
- 各任务允许运行的星期和时间。

真实配置可能包含业务路径与 Webhook，不应提交到 GitHub。

## 命令行运行

首次执行建议使用演练模式：

```powershell
python competitor_monitor\main.py --mode daily_price --dry-run
```

常用命令：

```powershell
python competitor_monitor\main.py --mode daily_price --limit 10

python competitor_monitor\main.py --mode daily_price --rows 24,54

python competitor_monitor\main.py --mode daily_price
python competitor_monitor\main.py --mode weekly_new
python competitor_monitor\main.py --mode price_trend
python competitor_monitor\main.py --mode all
```

`--force-overwrite` 会改变原有单元格覆盖策略，只有在确认目标行与备份有效后再使用。

## Web 控制台

双击 `启动Web.bat`，或手动运行：

```powershell
python competitor_monitor\web_server.py
```

浏览器打开 `http://127.0.0.1:8765`，即可启动任务、查看状态、日志和结果。

Web 页面只是控制台。用于后台调度的入口是：

```powershell
python competitor_monitor\run_web_task.py --mode daily_price
python competitor_monitor\run_web_task.py --mode weekly_new
python competitor_monitor\run_web_task.py --mode price_trend
```

启用企业微信后，后台入口会在任务完成时发送摘要，并可附带结果 Excel。

## Windows 定时任务

安装默认任务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_windows_tasks.ps1
```

默认计划：

| 任务 | 时间 |
| --- | --- |
| `CompetitorMonitor-WebConsole` | Windows 登录后启动 |
| `CompetitorMonitor-DailyPrice` | 周一至周五 10:00 |
| `CompetitorMonitor-WeeklyNew` | 周六 09:30 |
| `CompetitorMonitor-PriceTrend` | 周五 18:30 |

可通过脚本参数自定义时间；删除任务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\remove_windows_tasks.ps1
```

## 构建 EXE

双击 `打包EXE.bat`，构建：

```text
dist\CompetitorMonitorWeb\CompetitorMonitorWeb.exe
dist\CompetitorMonitorTaskRunner\CompetitorMonitorTaskRunner.exe
```

如需让 Windows 定时任务使用 EXE：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_windows_tasks.ps1 -UseExe
```

构建产物默认不包含 Excel、浏览器登录态、密钥、日志或备份。部署后仍需提供本机配置和业务文件。

## 数据安全与结果确认

以下本地内容已被仓库忽略，也不应手工提交：

- Excel 原始文件、验收文件、导出文件与备份；
- `competitor_monitor/config.yaml`；
- `competitor_monitor/secrets`；
- `browser_profile*`；
- `logs`。

这些文件可能包含账号、Cookie、登录状态、业务数据或企业微信 Webhook。每次运行前应确认输入文件、模式、行范围和覆盖策略；运行后抽查 Excel 结果及平台页面，不能只以日志或通知作为成功依据。

## 测试

```powershell
node web_frontend\uiState.test.cjs
node web_frontend\mockData.test.cjs
node web_frontend\staticMarkup.test.cjs
node web_frontend\stylePalette.test.cjs
node web_frontend\uiStateFillText.test.cjs

cd competitor_monitor
python -m unittest discover -s tests -v
```

## 发布与许可证

仓库当前没有公开 GitHub Release，也尚未提供明确的开源许可证。在获得作者授权前，不应默认拥有复制、修改或分发代码的权利。
