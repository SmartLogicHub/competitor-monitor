const assert = require("node:assert/strict");
const test = require("node:test");

const { buildAutomationView, statusTone, statusText } = require("./uiState.js");

const baseTasks = {
  system_status: "idle",
  workflow: [
    { key: "detect_date", state: "done" },
    { key: "locate_sheet", state: "done" },
    { key: "write_template", state: "pending" },
    { key: "backfill", state: "pending" },
    { key: "save", state: "pending" },
    { key: "notify", state: "pending" }
  ]
};

const missingFriday = {
  sheet_name: "6.29-7.3",
  period_start: "2026-06-29",
  period_end: "2026-07-03",
  complete: false,
  missing_dates: ["2026-07-03"],
  days: [
    { date: "2026-06-29", label: "周一", status: "complete", filled_count: 86, total_count: 86 },
    { date: "2026-06-30", label: "周二", status: "complete", filled_count: 86, total_count: 86 },
    { date: "2026-07-01", label: "周三", status: "complete", filled_count: 86, total_count: 86 },
    { date: "2026-07-02", label: "周四", status: "complete", filled_count: 86, total_count: 86 },
    { date: "2026-07-03", label: "周五", status: "missing", filled_count: 0, total_count: 86 }
  ]
};

test("missing template dates choose backfill as the primary action", () => {
  const view = buildAutomationView(baseTasks, missingFriday);

  assert.equal(view.energyPercent, 80);
  assert.equal(view.tone, "warning");
  assert.equal(view.primaryAction, "backfill");
  assert.equal(view.statusLabel, "缺 1 天");
  assert.equal(view.steps.map(step => step.key).join(">"), "detect_date>locate_sheet>write_template>backfill>save>notify");
});

test("complete template promotes send-template", () => {
  const complete = {
    ...missingFriday,
    complete: true,
    missing_dates: [],
    days: missingFriday.days.map(day => ({ ...day, status: "complete", filled_count: day.total_count }))
  };

  const view = buildAutomationView({ ...baseTasks, system_status: "success" }, complete);

  assert.equal(view.energyPercent, 100);
  assert.equal(view.tone, "success");
  assert.equal(view.primaryAction, "send_template");
  assert.equal(view.statusLabel, "完整");
});

test("status helpers expose the shared feedback language", () => {
  assert.equal(statusTone("running"), "active");
  assert.equal(statusTone("template_error"), "danger");
  assert.equal(statusText("sending"), "推送中");
});
