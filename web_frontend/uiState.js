(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.CompetitorMonitorUIState = api;
})(typeof window !== "undefined" ? window : globalThis, function () {
  const workflowMap = [
    { key: "detect_date", aliases: ["date", "detect_date"], title: "识别日期", detail: "确认目标日期和周期" },
    { key: "locate_sheet", aliases: ["sheet", "locate_sheet"], title: "定位 sheet", detail: "找到或创建 5 天周期表" },
    { key: "write_template", aliases: ["write", "write_template"], title: "写入模板", detail: "写入主 Excel 模板" },
    { key: "backfill", aliases: ["backfill", "check"], title: "补跑缺失", detail: "补齐缺失日期后继续" },
    { key: "save", aliases: ["save"], title: "保存模板", detail: "保存并保留格式" },
    { key: "notify", aliases: ["notify"], title: "推送企微", detail: "发送摘要和 Excel 文件" }
  ];

  function buildAutomationView(tasksStatus = {}, completeness = {}) {
    const missingDates = Array.isArray(completeness.missing_dates) ? completeness.missing_dates : [];
    const systemStatus = tasksStatus.system_status || "idle";
    const running = isLiveStatus(systemStatus);
    const complete = Boolean(completeness.complete) && missingDates.length === 0;
    const energyPercent = completeness.energy_percent ?? calculateEnergyPercent(completeness.days || []);
    const tone = running ? "active" : complete ? "success" : missingDates.length ? "warning" : statusTone(systemStatus);
    const primaryAction = running ? "none" : missingDates.length ? "backfill" : complete ? "send_template" : "run_daily";
    const statusLabel = running ? statusText(systemStatus) : complete ? "完整" : missingDates.length ? `缺 ${missingDates.length} 天` : statusText(systemStatus);
    return {
      sheetName: completeness.sheet_name || "未创建 sheet",
      periodLabel: periodLabel(completeness),
      energyPercent,
      tone,
      isLive: running,
      statusLabel,
      primaryAction,
      missingDates,
      days: normalizeDays(completeness.days || [], running),
      steps: normalizeWorkflow(tasksStatus.workflow || [], systemStatus),
      message: automationMessage(systemStatus, complete, missingDates)
    };
  }

  function calculateEnergyPercent(days) {
    const totals = days.reduce(
      (acc, day) => {
        const total = Number(day.total_count || 0);
        const filled = Number(day.filled_count || 0);
        acc.total += total;
        acc.filled += Math.max(0, Math.min(filled, total || filled));
        return acc;
      },
      { filled: 0, total: 0 }
    );
    if (!totals.total) return 0;
    return Math.round((totals.filled / totals.total) * 100);
  }

  function normalizeDays(days, running) {
    return days.map(day => {
      const state = day.state || (running && day.status !== "complete" ? "running" : day.status || "pending");
      return {
        ...day,
        state,
        tone: statusTone(state),
        label: day.label || "",
        shortDate: formatDay(day.date)
      };
    });
  }

  function normalizeWorkflow(rawSteps, systemStatus) {
    return workflowMap.map(template => {
      const found = rawSteps.find(step => template.aliases.includes(step.key));
      let state = found ? found.state : "pending";
      if (systemStatus === "running" && template.key === "write_template") state = "active";
      if (systemStatus === "backfilling" && template.key === "backfill") state = "active";
      if (systemStatus === "saving" && template.key === "save") state = "active";
      if (systemStatus === "sending" && template.key === "notify") state = "active";
      return {
        key: template.key,
        title: template.title,
        detail: (found && found.detail) || template.detail,
        state,
        tone: statusTone(state)
      };
    });
  }

  function automationMessage(systemStatus, complete, missingDates) {
    if (systemStatus === "running") return "任务正在执行，系统会持续写入主 Excel 模板。";
    if (systemStatus === "backfilling") return "正在补跑缺失日期，完成后继续后续任务。";
    if (systemStatus === "saving") return "主模板正在保存。";
    if (systemStatus === "sending") return "正在发送企业微信摘要和 Excel 文件。";
    if (systemStatus === "failed") return "任务失败，请查看最近日志中的失败原因。";
    if (complete) return "周一到周五价格列已完整，可以发送当前模板。";
    if (missingDates.length) return `缺失日期：${missingDates.join("、")}，建议先补跑。`;
    return "系统待命，等待下一次自动任务。";
  }

  function periodLabel(completeness) {
    if (!completeness.period_start || !completeness.period_end) return "-";
    return `${completeness.period_start} 至 ${completeness.period_end}`;
  }

  function statusTone(status) {
    if (["active", "running", "backfilling", "saving", "sending"].includes(status)) return "active";
    if (["ok", "success", "complete", "done"].includes(status)) return "success";
    if (["warning", "partial", "missing", "missing_sheet", "empty_template", "stopped"].includes(status)) return "warning";
    if (["danger", "failed", "error", "template_error"].includes(status)) return "danger";
    return "neutral";
  }

  function isLiveStatus(status) {
    return ["running", "backfilling", "saving", "sending"].includes(status);
  }

  function activeTaskId(tasksStatus = {}) {
    if (!isLiveStatus(tasksStatus.system_status)) return null;
    const mode = tasksStatus.active_mode;
    if (mode === "weekly_new") return "weekly_new";
    if (mode === "price_trend") return "price_trend";
    return "daily_price";
  }

  function statusText(status) {
    const map = {
      idle: "待命",
      running: "运行中",
      backfilling: "补缺中",
      saving: "保存中",
      sending: "推送中",
      success: "成功",
      failed: "失败",
      stopped: "已停止",
      complete: "完整",
      partial: "部分缺失",
      missing: "缺失",
      missing_sheet: "缺 sheet",
      empty_template: "无商品行",
      template_error: "模板异常",
      done: "完成",
      active: "进行中",
      pending: "未开始",
      warning: "待处理",
      skipped: "跳过"
    };
    return map[status] || status || "-";
  }

  function formatDay(dateText) {
    const parts = String(dateText || "").split("-");
    if (parts.length !== 3) return dateText || "-";
    return `${Number(parts[1])}.${Number(parts[2])}`;
  }

  function formatDayFillText(day = {}) {
    const state = day.state || day.status || "pending";
    if (["complete", "done", "success"].includes(state)) return "已填完整";
    if (["missing", "missing_sheet", "empty_template"].includes(state)) return "待补跑";
    if (state === "partial") return "部分已填";
    if (state === "running") return "写入中";
    if (state === "template_error") return "模板异常";
    return "未开始";
  }

  function formatDayFillPercent(day = {}) {
    const total = Number(day.total_count || 0);
    const filled = Number(day.filled_count || 0);
    if (!total || filled <= 0) return 0;
    return Math.round((Math.min(filled, total) / total) * 100);
  }

  return {
    buildAutomationView,
    calculateEnergyPercent,
    statusTone,
    statusText,
    isLiveStatus,
    activeTaskId,
    formatDay,
    formatDayFillText,
    formatDayFillPercent
  };
});
