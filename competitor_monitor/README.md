# 竞品监控 Excel 自动填报系统

本项目用于自动填报「竞品监控.xlsx」：

- 工作日采集成熟单品淘宝 / 天猫展示价格与活动。
- 周末从边界 BI 采集上新数据并写入上新监控区域。
- 周五或补跑时自动分析周一到周五价格情况。
- 运行前自动备份 Excel，运行后生成日志。
- Web 控制台可启动任务、查看状态、查看日志、导出结果，并发送当前 Excel 模板到企业微信群。

## 安装依赖

```bash
pip install -r competitor_monitor/requirements.txt
```

浏览器自动化使用 `rebrowser-playwright`。首次运行淘宝 / 天猫或边界 BI 时，可能需要在弹出的浏览器里人工登录一次；后续会复用 `browser_profile` 登录状态。

## 命令行运行

在项目根目录运行：

```bash
python competitor_monitor/main.py --mode daily_price --dry-run --date 2026-07-03
python competitor_monitor/main.py --mode daily_price --test-one --date 2026-07-03
python competitor_monitor/main.py --mode weekly_new --date 2026-07-05
python competitor_monitor/main.py --mode price_trend --date 2026-07-05
```

常用参数：

- `--mode daily_price`：成熟单品每日价格采集。
- `--mode weekly_new`：周末 BI 上新监控填报。
- `--mode price_trend`：价格情况分析。
- `--mode all`：同时运行每日价格和上新任务。
- `--dry-run`：只检查 Excel、sheet、表头和商品列表，不打开浏览器。
- `--limit 10`：只跑前 10 条。
- `--rows 24,54,60-62`：只跑指定 Excel 行。

## Web 控制台

推荐方式：在项目根目录双击：

```text
启动Web.bat
```

脚本会自动启动本地 Web 服务、等待 `/api/health` 健康检查通过，然后打开：

```text
http://127.0.0.1:8765
```

如果已经有 Web 服务在运行，脚本会直接打开控制台，不会重复启动。

也可以手动启动本地 Web 服务：

```bash
python competitor_monitor/web_server.py
```

然后打开：

```text
http://127.0.0.1:8765
```

Web 控制台支持：

- 查看当前任务状态、目标 sheet、目标周期和执行进度。
- 启动每日价格采集、周末 BI 上新任务。
- 请求停止当前任务。停止是安全软停止：当前单条商品处理完后停止后续处理。
- 查看日志、结果、失败原因。
- 导出本次结果 CSV。
- 保存常用配置。
- 手动发送当前 Excel 模板到企业微信群。

双击 `web_frontend/index.html` 会进入 mock 预览模式，不连接后端。

## 后台自动运行

Web 页面只负责展示和手动控制，不负责触发自动通知。真正用于 Windows 定时任务的后台入口是：

```bash
python competitor_monitor/run_web_task.py --mode daily_price
python competitor_monitor/run_web_task.py --mode weekly_new
python competitor_monitor/run_web_task.py --mode price_trend
```

该入口复用 Web 后端服务层，任务完成后会根据配置自动发送企业微信摘要和 Excel 文件。

推荐定时安排：

- 周一到周五每天运行 `daily_price`。
- 周六运行 `weekly_new`，目标是上一完整周一到周五周期。
- 周五收盘后或周六补跑 `price_trend`。

项目根目录提供：

- `scripts/install_windows_tasks.ps1`：安装 Windows 定时任务。
- `scripts/remove_windows_tasks.ps1`：删除 Windows 定时任务。
- `打包EXE.bat`：生成 Web 控制台和后台任务执行器 exe。

## 企业微信发送

企业微信通知由后端触发：

- 任务完成后，后端根据配置自动发送运行摘要和 Excel 文件。
- 前端只展示发送状态。
- 前端「发送当前模板」按钮只用于手动补发。

配置建议放在 `competitor_monitor/config.yaml`：

```yaml
wecom_enabled: true
wecom_webhook: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
wecom_send_summary: true
wecom_send_excel_file: true
```

Webhook 不要写进日志，不要截图外发。

## 凭据保存

淘宝和 BI 账号密码不要写进代码。默认保存在：

- `competitor_monitor/secrets/taobao_credentials.json`
- `competitor_monitor/secrets/bi_credentials.json`

也可以用环境变量覆盖：

```powershell
$env:TAOBAO_USER="你的淘宝账号"
$env:TAOBAO_PASSWORD="你的淘宝密码"
$env:BI_USER="边界 BI 账号"
$env:BI_PASSWORD="边界 BI 密码"
```

遇到验证码、滑块或安全验证时，程序只会暂停等待人工处理，不会绕过验证。

## 验证命令

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

编译检查：

```bash
python -m py_compile competitor_monitor\*.py
```
