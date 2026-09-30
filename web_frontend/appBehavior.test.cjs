const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const app = fs.readFileSync(path.join(__dirname, "app.js"), "utf8");
const html = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");

function functionSource(name, nextName) {
  const start = app.indexOf(`function ${name}(`);
  const end = app.indexOf(`function ${nextName}(`, start + 1);
  assert.notEqual(start, -1, `${name} should exist`);
  assert.notEqual(end, -1, `${nextName} should follow ${name}`);
  return app.slice(start, end);
}

test("manual run always delegates its date to the backend clock", () => {
  const buildPayload = functionSource("buildRunPayload", "defaultRunDate");
  assert.doesNotMatch(buildPayload, /run_date\s*:/);
  assert.match(html, /id="cfg-run-date"[^>]*readonly/);
});

test("displayed current date uses the local calendar instead of UTC", () => {
  const currentDate = functionSource("defaultRunDate", "openDetail");
  assert.match(currentDate, /getFullYear\(\)/);
  assert.match(currentDate, /getMonth\(\)/);
  assert.match(currentDate, /getDate\(\)/);
  assert.doesNotMatch(currentDate, /toISOString\(\)/);
});

test("taobao account card exposes the shared-profile login browser action", () => {
  const api = fs.readFileSync(path.join(__dirname, "api.js"), "utf8");
  assert.match(html, /id="btn-open-taobao-login"/);
  assert.match(html, /id="taobao-login-browser-status"/);
  assert.match(html, /真实天猫商品页/);
  assert.match(api, /\/api\/session\/open/);
  assert.match(api, /\/api\/session\/status/);
  assert.match(app, /btn-open-taobao-login"\)\.addEventListener\("click", openTaobaoLogin\)/);
  assert.match(app, /async function openTaobaoLogin\(\)/);
  assert.match(app, /function renderLoginSessionStatus\(\)/);
});

test("taobao account card imports a local cookie json file", () => {
  const api = fs.readFileSync(path.join(__dirname, "api.js"), "utf8");
  assert.match(html, /id="taobao-cookie-upload-input"/);
  assert.match(html, /id="btn-import-taobao-cookies"/);
  assert.match(api, /API\.importTaobaoCookies = async function \(file\)/);
  assert.match(api, /\/api\/session\/import-cookies/);
  assert.match(app, /btn-import-taobao-cookies"\)\.addEventListener\("click", importTaobaoCookies\)/);
  assert.match(app, /async function importTaobaoCookies\(\)/);
});

test("taobao login browser renders the real authentication state", () => {
  const renderStatus = functionSource("renderLoginSessionStatus", "setTaskCardRunning");
  assert.match(renderStatus, /auth_status/);
  assert.match(renderStatus, /正在检查淘宝登录状态/);
  assert.match(renderStatus, /淘宝尚未登录/);
  assert.match(renderStatus, /淘宝需要人工验证/);
  assert.match(renderStatus, /淘宝已登录/);
});
