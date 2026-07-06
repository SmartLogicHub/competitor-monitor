const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function loadMockDataAt(isoDateTime) {
  const source = fs.readFileSync(path.join(__dirname, "mockData.js"), "utf8");
  const fixedTime = new Date(isoDateTime).getTime();

  class FixedDate extends Date {
    constructor(...args) {
      super(args.length ? args[0] : fixedTime);
    }

    static now() {
      return fixedTime;
    }
  }

  FixedDate.UTC = Date.UTC;
  FixedDate.parse = Date.parse;

  const context = { window: {}, Date: FixedDate, Math, console };
  vm.runInNewContext(source, context);
  return { mock: context.window.CompetitorMonitorMock, source };
}

test("mock completeness follows the current work week after July 6", () => {
  const { mock } = loadMockDataAt("2026-07-06T09:00:00+08:00");

  assert.equal(mock.completeness.sheet_name, "7.6-7.10");
  assert.equal(mock.completeness.period_start, "2026-07-06");
  assert.equal(mock.completeness.period_end, "2026-07-10");
  assert.deepEqual(Array.from(mock.completeness.missing_dates), ["2026-07-06"]);
});

test("mock data uses earphone competitors and no local absolute path", () => {
  const { mock, source } = loadMockDataAt("2026-07-06T09:00:00+08:00");
  const models = mock.results.map(item => item.model);

  assert.ok(models.includes("S6S Ultra"));
  assert.ok(models.includes("太空漫游2"));
  assert.doesNotMatch(source, /G:\\\\桌面/);
  assert.doesNotMatch(source, /Nike|Adidas|跑鞋/);
  assert.doesNotMatch(source, /绔炲搧|鎺ㄩ|鏃ユ湡/);
});
