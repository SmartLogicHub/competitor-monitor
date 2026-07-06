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
