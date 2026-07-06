const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

test("automation page keeps the required local tool controls", () => {
  const html = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
  const app = fs.readFileSync(path.join(__dirname, "app.js"), "utf8");

  assert.match(html, /竞品监控 Web 控制台/);
  assert.match(html, /数据采集流水线/);
  assert.match(html, /id="btn-stop-task"/);
  assert.match(html, /请求停止/);
  assert.match(html, /发送当前模板/);
  assert.match(html, /导出本次结果/);
  assert.match(html, /企业微信/);
  assert.match(html, /id="cfg-run-date"/);
  assert.match(html, /id="cfg-dry-run"/);
  assert.match(html, /id="cfg-test-one"/);
  assert.match(html, /id="cfg-taobao-login-status"/);
  assert.match(html, /id="cfg-taobao-credential-status"/);
  assert.match(html, /id="cfg-bi-login-status"/);
  assert.match(html, /id="cfg-bi-credential-status"/);
  assert.match(html, /清除淘宝浏览器状态/);
  assert.match(html, /清除 BI 浏览器状态/);
  assert.match(app, /taobao_username_masked/);
  assert.match(app, /bi_username_masked/);
  assert.doesNotMatch(html, /下载报表|手动触发推送/);
  assert.doesNotMatch(html, /绔炲搧|鎺у埗|閰嶇疆|鍙戦|鏃ュ織|妯℃澘/);
  assert.doesNotMatch(html, /营销|会员|权限管理|数据大屏/);
});
