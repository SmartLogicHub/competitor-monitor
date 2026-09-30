# 淘宝登录页统一与 Cookie 导入设计

## 目标

让控制台“打开淘宝登录网页”与自动采集在同一浏览器资料目录中打开同类型的真实天猫商品详情页，并允许用户从本地导入仍有效的淘宝/天猫 Cookie，从而在 Cookie 有效时免输账号密码。

## 现状与根因

- 手动登录固定打开 `https://www.taobao.com/`。
- 自动采集打开 Excel 型号单元格中的 `https://detail.tmall.com/item.htm?...`。
- 两条路径解析到同一个 `browser_profile`，因此不是用户目录分叉；不一致来自验证 URL 和页面类型。
- 当前控制台没有 Cookie 导入入口，只能通过浏览器人工登录后保存 `storage_state.json`。

## 方案

### 登录验证页

Web 服务从当前有效 Excel 中读取成熟商品区域的第一个淘宝/天猫商品超链接，把它作为 `--login-url` 传给登录子进程。登录子进程优先打开该 URL。若工作簿不存在、无法读取或没有有效商品链接，则回退到 `https://www.tmall.com/`，不再使用淘宝首页作为默认验证页。

手动登录与自动采集继续共用现有 `browser_user_data_dir` 和 `browser_storage_state_path`。登录完成后仍由浏览器服务保存状态。

### Cookie 导入

控制台增加 JSON 文件选择框和“导入淘宝 Cookie”按钮。后端接受两类常见格式：

1. Playwright storage state：`{"cookies": [...], "origins": [...]}`。
2. Cookie-Editor 导出的 Cookie 数组：`[{"name": ..., "value": ..., "domain": ...}, ...]`。

后端只保留域名属于 `taobao.com` 或 `tmall.com` 的 Cookie，验证必需字段、规范化 `sameSite`、`expires` 等可选字段，然后原子写入配置指定的 `browser_storage_state_path`。不记录、不回显 Cookie 名称和值。导入成功只返回 Cookie 条数和“下次打开真实天猫页会验证是否仍有效”。

当手动登录窗口或采集任务正在运行时拒绝导入，避免浏览器同时写状态文件。

## 安全与失败处理

- JSON 无法解析、没有合法淘宝/天猫 Cookie、文件过大或格式不支持时拒绝写入，保留原状态文件。
- Cookie 失效、异地风控、滑块或二次验证仍需人工处理；导入不能绕过平台验证。
- Cookie 文件等同登录凭据，只在本机读取并写入本地运行目录，不出现在日志、结果或配置接口中。

## 验证

- 单元测试证明手动登录优先使用传入的真实商品 URL，缺失时回退天猫首页。
- API 测试证明从 Excel 解析登录 URL并传给登录子进程。
- Cookie 导入测试覆盖两种格式、域名过滤、拒绝无效文件和忙碌状态。
- HTTP 路由与前端静态测试覆盖新接口和控件。
- 运行完整 Python 与前端测试套件，随后重新构建 Web/TaskRunner 部署包并检查包内文件。
