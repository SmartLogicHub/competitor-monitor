# 竞品监控 Web 控制台前端

本目录是「竞品监控 Excel 自动填报系统」的本地工具型 Web 控制台前端，使用原生 HTML/CSS/JavaScript，不需要 Node 构建。

## 打开方式

1. 双击 `index.html`：进入 mock 预览模式，不连接后端。
2. 运行后端服务：在项目根目录执行 `python competitor_monitor/web_server.py`，然后打开 `http://127.0.0.1:8765`。

`api.js` 会自动判断：

- `file://` 打开时使用 mock 数据。
- `http://127.0.0.1:8765` 打开时调用真实后端 API。

## 安全运行参数

配置页「调试参数」里提供三个真实运行前必须核对的字段：

- `运行日期`：用于确定目标 sheet 和目标周期。
- `只做安全检查 dry-run`：开启后只做识别、备份、日志等检查，不执行真实采集写入。
- `只测试一条 test-one`：开启后只跑一条商品链接，适合登录、页面结构和 SKU 价格校验。

建议真实验收顺序：

1. 先开启 `dry-run`，确认目标 sheet、目标周期、日志和备份正常。
2. 再关闭 `dry-run`，开启 `test-one`，只验证一条真实链接。
3. 再使用 `行范围` 或 `限制数量` 做小批量测试。
4. 最后再对测试 Excel 全量运行，不直接冒险改正式原文件。

## 后端 API

当前前端使用以下接口：

- `GET /api/tasks/status`
- `POST /api/tasks/run`
- `POST /api/tasks/stop`
- `GET /api/template/completeness`
- `POST /api/template/backfill`
- `POST /api/notify/send-template`
- `GET /api/config`
- `POST /api/config`
- `GET /api/logs`
- `GET /api/results`
- `GET /api/results/export`
- `POST /api/maintenance/cleanup`
- `POST /api/session/reset`

## 企业微信边界

自动企业微信通知由后端任务完成后触发，前端只展示发送状态。前端按钮「发送当前模板」只用于手动补发，由后端决定是否发送文字摘要、Excel 文件或两者。

## 安全规则

- Webhook、淘宝密码、BI 密码默认不明文展示。
- 配置保存时，`******` 不会覆盖后端已保存的敏感值。
- 结果详情展示前会做敏感字段脱敏。
- “清空当前视图日志”只清空页面视图，不物理删除 `logs/` 文件夹。
