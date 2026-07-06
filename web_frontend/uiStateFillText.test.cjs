const assert = require("node:assert/strict");
const test = require("node:test");

const { formatDayFillPercent, formatDayFillText } = require("./uiState.js");

test("day fill text avoids making mock row counts look fixed", () => {
  assert.equal(
    formatDayFillText({ state: "complete", filled_count: 86, total_count: 86 }),
    "\u5df2\u586b\u5b8c\u6574"
  );
  assert.equal(
    formatDayFillText({ state: "missing", filled_count: 0, total_count: 86 }),
    "\u5f85\u8865\u8dd1"
  );
  assert.equal(
    formatDayFillText({ state: "partial", filled_count: 52, total_count: 86 }),
    "\u90e8\u5206\u5df2\u586b"
  );
});

test("day fill percent follows the written row ratio", () => {
  assert.equal(formatDayFillPercent({ filled_count: 43, total_count: 86 }), 50);
  assert.equal(formatDayFillPercent({ filled_count: 86, total_count: 86 }), 100);
  assert.equal(formatDayFillPercent({ filled_count: 0, total_count: 86 }), 0);
  assert.equal(formatDayFillPercent({ filled_count: 90, total_count: 86 }), 100);
  assert.equal(formatDayFillPercent({ filled_count: 12, total_count: 0, state: "missing" }), 0);
});
