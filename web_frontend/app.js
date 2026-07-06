(function () {
  const API = window.CompetitorMonitorAPI;
  const UIState = window.CompetitorMonitorUIState;
  const SECRET_PLACEHOLDER = "******";
  const state = {
    tasks: null,
    completeness: null,
    config: null,
    logs: [],
    results: [],
    resultQuick: "all",
    pollTimer: null
  };

  const pageTitles = {
    "tab-console": ["自动任务中心", "识别日期、写入主 Excel 模板、检查完整性并推送企业微信"],
    "tab-logs": ["运行日志", "查看运行过程、错误和失败原因"],
    "tab-results": ["结果记录", "查看成功、失败、跳过记录并导出本次结果"],
    "tab-config": ["系统配置", "修改运行前真正需要的参数"]
  };

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    bindEvents();
    API.onConnectionError(() => document.getElementById("offline-banner").classList.add("visible"));
    API.onConnectionRestore(() => document.getElementById("offline-banner").classList.remove("visible"));
    refreshAll();
    state.pollTimer = setInterval(refreshStatusOnly, 2500);
  }

  function bindEvents() {
    document.querySelectorAll("[data-tab]").forEach(button => {
      button.addEventListener("click", () => switchTab(button.dataset.tab));
    });
    document.getElementById("btn-refresh").addEventListener("click", refreshAll);
    document.getElementById("btn-run-daily").addEventListener("click", () => runTask("daily_price"));
    document.getElementById("btn-run-weekly").addEventListener("click", () => runTask("weekly_new"));
    document.getElementById("btn-stop-task").addEventListener("click", stopTask);
    document.getElementById("btn-backfill-missing").addEventListener("click", backfillMissingDates);
    document.getElementById("btn-loop-primary").addEventListener("click", handleLoopPrimaryAction);
    document.getElementById("btn-loop-check").addEventListener("click", loadCompleteness);
    document.getElementById("btn-send-template-main").addEventListener("click", sendTemplate);
    document.getElementById("btn-download-excel").addEventListener("click", downloadExcel);
    document.getElementById("log-filter-level").addEventListener("change", renderLogs);
    document.getElementById("log-search-query").addEventListener("input", debounce(renderLogs, 200));
    document.getElementById("btn-clear-logs").addEventListener("click", cleanupLogs);
    document.getElementById("result-filter-status").addEventListener("change", renderResults);
    document.getElementById("result-filter-mode").addEventListener("change", renderResults);
    document.getElementById("result-search-query").addEventListener("input", debounce(renderResults, 200));
    document.getElementById("btn-export-results").addEventListener("click", exportResults);
    document.getElementById("config-form").addEventListener("submit", saveConfig);
    document.getElementById("btn-reset-taobao").addEventListener("click", () => resetSession("taobao"));
    document.getElementById("btn-reset-bi").addEventListener("click", () => resetSession("bi"));
    document.getElementById("btn-close-detail").addEventListener("click", closeDetail);
    document.querySelectorAll(".btn-toggle-password").forEach(button => {
      button.addEventListener("click", () => togglePasswordVisibility(button));
    });
    const backdrop = document.getElementById("drawer-backdrop");
    if (backdrop) backdrop.addEventListener("click", closeDetail);
    document.querySelectorAll("[data-result-quick]").forEach(button => {
      button.addEventListener("click", () => {
        document.querySelectorAll("[data-result-quick]").forEach(item => item.classList.remove("active"));
        button.classList.add("active");
        state.resultQuick = button.dataset.resultQuick;
        renderResults();
      });
    });
  }

  function switchTab(tabId) {
    document.querySelectorAll(".nav-item").forEach(item => item.classList.toggle("active", item.dataset.tab === tabId));
    document.querySelectorAll(".tab-panel").forEach(panel => panel.classList.toggle("active", panel.id === tabId));
    const [title, subtitle] = pageTitles[tabId] || pageTitles["tab-console"];
    text("page-display-title", title);
    text("page-subtitle", subtitle);
  }

  async function refreshAll() {
    await Promise.allSettled([loadStatus(), loadCompleteness(), loadConfig(), loadLogs(), loadResults()]);
  }

  async function refreshStatusOnly() {
    await Promise.allSettled([loadStatus(), loadCompleteness(), loadLogs(), loadResults()]);
  }

  async function loadStatus() {
    state.tasks = await API.getTasksStatus();
    renderStatus();
  }

  async function loadCompleteness() {
    state.completeness = await API.getTemplateCompleteness();
    renderCompleteness();
  }

  async function loadConfig() {
    state.config = await API.getConfig();
    renderConfig();
  }

  async function loadLogs() {
    const level = document.getElementById("log-filter-level").value;
    const query = document.getElementById("log-search-query").value.trim();
    state.logs = await API.getLogs(level, query);
    renderLogsFromState();
    renderConsoleLogs();
  }

  async function loadResults() {
    const status = document.getElementById("result-filter-status").value;
    const mode = document.getElementById("result-filter-mode").value;
    const query = document.getElementById("result-search-query").value.trim();
    state.results = await API.getResults(status, mode, query);
    renderResultsFromState();
  }

  function renderStatus() {
    const data = state.tasks || {};
    const daily = (data.tasks || []).find(task => task.id === "daily_price") || {};
    const weekly = (data.tasks || []).find(task => task.id === "weekly_new") || {};
    const running = data.system_status === "running";
    badge("global-status-badge", UIState.statusText(data.system_status), UIState.statusTone(data.system_status));
    text("side-template-name", data.template_name || "竞品监控.xlsx");
    text("side-health-text", UIState.statusText(data.system_status));
    
    // 渲染全局 KPI 模块 (采集进度、吞吐、备份数、session数)
    text("kpi-progress-done", data.progress_done || "0");
    text("kpi-progress-total", data.progress_total || "0");
    text("kpi-success", data.success_count || "0");
    text("kpi-failed", data.failed_count || "0");
    text("kpi-backup-count", data.maintenance ? data.maintenance.backups : "0");
    text("kpi-session-count", data.maintenance ? data.maintenance.sessions : "0");

    // 渲染爬虫健康通道状态 (读取保存的配置信息)
    if (state.config) {
      const tbText = state.config.taobao_credential_status || "待检测";
      const biText = state.config.bi_credential_status || "待检测";
      badge("kpi-tb-status", tbText, tbText.includes("已保存") || tbText.includes("正常") ? "success" : "warning");
      badge("kpi-bi-status", biText, biText.includes("已保存") || biText.includes("正常") ? "success" : "warning");
    }

    text("today-task-chip", todayTaskLabel(daily, weekly));
    text("daily-last-result", daily.last_result || "-");
    text("daily-template-status", data.target_sheet_name || daily.template_status || "-");
    text("daily-next-run", data.current_step || "-");
    text("weekly-target-period", data.target_period_range || "-");
    text("weekly-precheck", weekly.precheck || "-");
    text("weekly-notify-status", data.last_notify_file_status || "-");
    text("loop-target-sheet", data.target_sheet_name || "-");
    text("loop-target-period", data.target_period_range || "-");
    text("loop-saved-at", data.last_saved_at || "-");
    text("loop-sent-at", data.last_sent_at || "-");
    text("notify-text-status", data.last_notify_text_status || "not_sent");
    text("notify-file-status", data.last_notify_file_status || "not_sent");
    text("notify-time", data.last_notify_time || "-");
    text("notify-file-name", data.last_sent_file_name || "-");
    text("notify-error", data.last_notify_error || "-");
    badge("daily-status", daily.status_text || UIState.statusText(daily.status), UIState.statusTone(daily.status));
    badge("weekly-status", weekly.status_text || UIState.statusText(weekly.status), UIState.statusTone(weekly.status));

    // 动态显示或隐藏任务运行遮罩 (蒙版)
    const dailyOverlay = document.getElementById("daily-overlay");
    const weeklyOverlay = document.getElementById("weekly-overlay");
    if (dailyOverlay) dailyOverlay.style.display = (daily.status === "running") ? "flex" : "none";
    if (weeklyOverlay) weeklyOverlay.style.display = (weekly.status === "running") ? "flex" : "none";

    setDisabled("btn-run-daily", running);
    setDisabled("btn-run-weekly", running);
    setDisabled("btn-stop-task", !running);
    setDisabled("btn-backfill-missing", running);
    setDisabled("btn-loop-primary", running);
  }

  function renderCompleteness() {
    const view = UIState.buildAutomationView(state.tasks || {}, state.completeness || {});
    text("template-state-chip", `模板：${view.statusLabel}`);
    text("side-energy-text", `${view.energyPercent}%`);
    const fill = document.getElementById("side-energy-fill");
    if (fill) fill.style.width = `${view.energyPercent}%`;
    const strip = document.getElementById("global-energy-strip");
    if (strip) {
      strip.className = `global-energy-strip ${view.tone}`;
      const span = strip.querySelector("span");
      if (span) span.style.width = `${view.energyPercent}%`;
    }

    // 渲染 KPI 数据链路完整率进度条和数值
    text("kpi-completeness-pct", `${view.energyPercent}%`);
    const kpiBar = document.getElementById("kpi-completeness-bar");
    if (kpiBar) kpiBar.style.width = `${view.energyPercent}%`;

    document.getElementById("energy-cells").innerHTML = view.days
      .map(day => `<div class="pipeline-date-card ${day.tone}"><strong>${escapeHtml(day.shortDate)}</strong><span style="width:${UIState.formatDayFillPercent(day)}%"></span><small>${escapeHtml(UIState.formatDayFillText(day))}</small></div>`)
      .join("");
    const workflowList = document.getElementById("workflow-list");
    const data = state.tasks || {};
    const running = data.system_status === "running";
    if (workflowList) {
      workflowList.innerHTML = view.steps
        .map(step => `<div class="workflow-item ${step.tone}"><strong>${escapeHtml(step.title)}</strong><span>${escapeHtml(step.detail)}</span></div>`)
        .join("");
      workflowList.classList.toggle("running", running);
    }
    const primary = document.getElementById("btn-loop-primary");
    primary.dataset.action = view.primaryAction;
    primary.textContent = view.primaryAction === "send_template" ? "发送当前模板" : view.primaryAction === "run_daily" ? "运行每日价格" : "补跑缺失日期";
  }

  function renderConfig() {
    const config = state.config || {};
    value("cfg-daily-time", config.daily_run_time || "10:00");
    value("cfg-bi-sat", String(Boolean(config.bi_run_saturday)));
    value("cfg-bi-sun", String(Boolean(config.bi_run_sunday)));
    value("cfg-auto-backfill", String(Boolean(config.auto_backfill_missing_daily_prices_before_weekly_new)));
    value("cfg-wecom-enabled", String(Boolean(config.wecom_enabled)));
    value("cfg-wecom-summary", String(Boolean(config.wecom_send_summary)));
    value("cfg-wecom-template", String(Boolean(config.wecom_send_excel_file)));
    value("cfg-wecom-webhook", config.wecom_webhook_set ? SECRET_PLACEHOLDER : "");
    value("cfg-excel-path", config.excel_path || "竞品监控.xlsx");
    value("cfg-taobao-login-status", config.taobao_login_status || "运行时检测");
    value("cfg-taobao-credential-status", config.taobao_credential_status || "未保存凭据");
    value("cfg-bi-login-status", config.bi_login_status || "运行时检测");
    value("cfg-bi-credential-status", config.bi_credential_status || "未保存凭据");
    value("cfg-taobao-username", "");
    value("cfg-taobao-password", "");
    value("cfg-bi-username", "");
    value("cfg-bi-password", "");
    placeholder("cfg-taobao-username", config.taobao_username_masked ? `已保存：${config.taobao_username_masked}` : "需要修改时填写");
    placeholder("cfg-taobao-password", config.taobao_password_set ? "已保存：******" : "需要修改时填写");
    placeholder("cfg-bi-username", config.bi_username_masked ? `已保存：${config.bi_username_masked}` : "需要修改时填写");
    placeholder("cfg-bi-password", config.bi_password_set ? "已保存：******" : "需要修改时填写");
    value("cfg-mode", config.mode || "daily_price");
    value("cfg-run-date", config.run_date || defaultRunDate());
    value("cfg-dry-run", String(Boolean(config.dry_run)));
    value("cfg-test-one", String(Boolean(config.test_one)));
    value("cfg-rows", config.rows || "");
    value("cfg-limit", config.limit || "");
    value("cfg-save-every", config.save_every ?? 5);
    text("daily-schedule", `每天 ${config.daily_run_time || "10:00"}`);
    text("weekly-schedule", [config.bi_run_saturday ? "周六" : "", config.bi_run_sunday ? "周日" : ""].filter(Boolean).join(" / ") || "未启用");
  }

  async function renderLogs() {
    await loadLogs();
  }

  function renderLogsFromState() {
    const wrap = document.getElementById("logs-table-body");
    wrap.innerHTML = state.logs.map(logItemHtml).join("");
    document.getElementById("logs-empty-state").style.display = state.logs.length ? "none" : "block";
    const autoScroll = document.getElementById("log-auto-scroll");
    if (autoScroll && autoScroll.checked && wrap) {
      wrap.scrollTop = wrap.scrollHeight;
    }
  }

  function renderConsoleLogs() {
    document.getElementById("console-log-preview").innerHTML = state.logs.slice(0, 5).map(logItemHtml).join("");
  }

  async function renderResults() {
    await loadResults();
  }

  function renderResultsFromState() {
    const list = applyResultQuickFilter(state.results);
    const wrap = document.getElementById("results-table-body");
    wrap.innerHTML = list
      .map(
        item => `
        <div class="result-row ${escapeHtml(item.status)}">
          <div><strong>${escapeHtml(item.brand || "-")} ${escapeHtml(item.model || "-")}</strong><span>${escapeHtml(item.sheet || "-")} · ${escapeHtml(item.mode || "-")}</span></div>
          <div><span>${escapeHtml(item.output || item.error_reason || "-")}</span><small>${escapeHtml(item.time || "-")}</small></div>
          <span class="badge ${UIState.statusTone(item.status)}">${escapeHtml(item.status || "-")}</span>
          <button class="btn ghost small" type="button" data-detail-id="${escapeHtml(item.id)}">详情</button>
        </div>`
      )
      .join("");
    wrap.querySelectorAll("[data-detail-id]").forEach(button => {
      button.addEventListener("click", () => openDetail(button.dataset.detailId));
    });
    document.getElementById("results-empty-state").style.display = list.length ? "none" : "block";
  }

  async function runTask(mode) {
    const payload = buildRunPayload(mode);
    await withButtonLoading(mode === "weekly_new" ? "btn-run-weekly" : "btn-run-daily", async () => {
      await API.runTask(payload);
      toast("任务已提交，页面会自动刷新状态", "success");
      await refreshAll();
    });
  }

  // 模拟下载 Excel 报表的主出口函数
  function downloadExcel() {
    const data = state.tasks || {};
    const fileName = data.template_name || "竞品监控.xlsx";
    toast(`已触发浏览器下载: ${fileName}，正在准备本地缓存...`, "success");
    
    // 创建一个临时下载锚点
    const a = document.createElement("a");
    a.href = "data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,UEsDBBQAAAAIA...";
    a.download = fileName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  async function stopTask() {
    if (!confirm("确认请求停止当前任务？当前正在处理的单条商品会先安全结束，然后停止后续处理。")) return;
    await withButtonLoading("btn-stop-task", async () => {
      await API.stopTask();
      toast("已请求停止当前任务", "warning");
      await refreshAll();
    });
  }

  async function backfillMissingDates() {
    const missing = state.completeness ? state.completeness.missing_dates : [];
    if (!missing.length) {
      toast("模板已完整，无需补跑", "success");
      return;
    }
    await withButtonLoading("btn-backfill-missing", async () => {
      await API.backfillTemplate({ dates: missing });
      toast("缺失日期已提交补跑", "success");
      await refreshAll();
    });
  }

  async function handleLoopPrimaryAction() {
    const action = document.getElementById("btn-loop-primary").dataset.action;
    if (action === "send_template") return sendTemplate();
    if (action === "run_daily") return runTask("daily_price");
    return backfillMissingDates();
  }

  async function sendTemplate() {
    if (!confirm("确认发送当前已保存的 Excel 模板到企业微信群？")) return;
    await withButtonLoading("btn-loop-send", async () => {
      const response = await API.sendTemplate();
      toast(response.message || "当前模板已发送", response.error ? "error" : "success");
      await refreshAll();
    });
  }

  async function saveConfig(event) {
    event.preventDefault();
    const payload = {
      daily_run_time: document.getElementById("cfg-daily-time").value,
      bi_run_saturday: document.getElementById("cfg-bi-sat").value === "true",
      bi_run_sunday: document.getElementById("cfg-bi-sun").value === "true",
      auto_backfill_missing_daily_prices_before_weekly_new: document.getElementById("cfg-auto-backfill").value === "true",
      wecom_enabled: document.getElementById("cfg-wecom-enabled").value === "true",
      wecom_send_summary: document.getElementById("cfg-wecom-summary").value === "true",
      wecom_send_excel_file: document.getElementById("cfg-wecom-template").value === "true",
      excel_path: document.getElementById("cfg-excel-path").value.trim(),
      mode: document.getElementById("cfg-mode").value,
      run_date: document.getElementById("cfg-run-date").value,
      dry_run: document.getElementById("cfg-dry-run").value === "true",
      test_one: document.getElementById("cfg-test-one").value === "true",
      rows: document.getElementById("cfg-rows").value.trim(),
      limit: document.getElementById("cfg-limit").value,
      save_every: Number(document.getElementById("cfg-save-every").value || 0)
    };
    addSecret(payload, "wecom_webhook", "cfg-wecom-webhook");
    addSecret(payload, "taobao_password", "cfg-taobao-password");
    addSecret(payload, "bi_password", "cfg-bi-password");
    addOptional(payload, "taobao_username", "cfg-taobao-username");
    addOptional(payload, "bi_username", "cfg-bi-username");
    await withButtonLoading("btn-save-config", async () => {
      await API.saveConfig(payload);
      toast("配置已保存", "success");
      await loadConfig();
    });
  }

  async function exportResults() {
    const blob = await API.exportResults();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "competitor-monitor-results.csv";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async function cleanupLogs() {
    if (!confirm("只清空当前 Web 页面展示的日志视图，不会物理删除 logs/ 文件夹。确认继续？")) return;
    await API.cleanupMaintenance("logs");
    toast("当前视图日志已清空", "success");
    await loadLogs();
  }

  async function resetSession(target) {
    await API.resetSession(target);
    toast("登录状态已重置", "warning");
    await loadConfig();
  }

  function buildRunPayload(mode) {
    const payload = {
      mode,
      run_date: document.getElementById("cfg-run-date").value || defaultRunDate(),
      dry_run: document.getElementById("cfg-dry-run").value === "true",
      test_one: document.getElementById("cfg-test-one").value === "true",
      rows: document.getElementById("cfg-rows").value.trim(),
      limit: document.getElementById("cfg-limit").value,
      save_every: Number(document.getElementById("cfg-save-every").value || 0)
    };
    Object.keys(payload).forEach(key => {
      if (payload[key] === "" || payload[key] === 0) delete payload[key];
    });
    return payload;
  }

  function defaultRunDate() {
    return window.CompetitorMonitorMock ? window.CompetitorMonitorMock.today : new Date().toISOString().slice(0, 10);
  }

  function openDetail(id) {
    const item = state.results.find(result => String(result.id) === String(id));
    const drawer = document.getElementById("detail-drawer");
    const backdrop = document.getElementById("drawer-backdrop");
    document.getElementById("detail-content").textContent = JSON.stringify(sanitizeDetail(item || {}), null, 2);
    drawer.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
    if (backdrop) backdrop.style.display = "block";
  }

  function closeDetail() {
    const drawer = document.getElementById("detail-drawer");
    const backdrop = document.getElementById("drawer-backdrop");
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
    if (backdrop) backdrop.style.display = "none";
  }

  function sanitizeDetail(value) {
    if (Array.isArray(value)) return value.map(sanitizeDetail);
    if (value && typeof value === "object") {
      return Object.fromEntries(
        Object.entries(value).map(([key, item]) => {
          const lower = key.toLowerCase();
          if (["secret", "password", "token", "cookie", "webhook", "account", "username"].some(word => lower.includes(word))) {
            return [key, SECRET_PLACEHOLDER];
          }
          return [key, sanitizeDetail(item)];
        })
      );
    }
    return value;
  }

  function applyResultQuickFilter(list) {
    if (state.resultQuick === "failed") return list.filter(item => item.status === "failed");
    if (state.resultQuick === "today") {
      const today = window.CompetitorMonitorMock ? window.CompetitorMonitorMock.today : new Date().toISOString().slice(0, 10);
      return list.filter(item => String(item.time || "").startsWith(today));
    }
    return list;
  }

  function logItemHtml(item) {
    return `
      <div class="log-item timeline-item ${escapeHtml(item.level)}">
        <div class="log-topline"><span>${escapeHtml(item.time)}</span><span>${escapeHtml(String(item.level || "").toUpperCase())}</span></div>
        <div class="log-message">${escapeHtml(item.message)}</div>
        ${item.detail ? `<div class="log-detail">${escapeHtml(item.detail)}</div>` : ""}
      </div>
    `;
  }

  function todayTaskLabel(daily, weekly) {
    const day = new Date().getDay();
    if (day === 6 || day === 0) return `今日任务：${weekly.title || "周末 BI"}`;
    return `今日任务：${daily.title || "每日价格"}`;
  }

  function addSecret(payload, key, id) {
    const value = document.getElementById(id).value.trim();
    if (value && value !== SECRET_PLACEHOLDER) payload[key] = value;
  }

  function addOptional(payload, key, id) {
    const value = document.getElementById(id).value.trim();
    if (value) payload[key] = value;
  }

  async function withButtonLoading(id, fn) {
    const button = document.getElementById(id);
    if (button) {
      button.disabled = true;
      button.classList.add("saving-loading");
    }
    try {
      await fn();
    } catch (error) {
      toast(error.message || "操作失败", "error");
    } finally {
      if (button) {
        button.disabled = false;
        button.classList.remove("saving-loading");
      }
    }
  }

  function setDisabled(id, disabled) {
    const element = document.getElementById(id);
    if (element) element.disabled = disabled;
  }

  function badge(id, label, tone) {
    const element = document.getElementById(id);
    if (!element) return;
    element.textContent = label || "-";
    element.className = `badge ${tone || "neutral"}`;
  }

  function text(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value ?? "-";
  }

  function value(id, nextValue) {
    const element = document.getElementById(id);
    if (element) element.value = nextValue ?? "";
  }

  function placeholder(id, nextValue) {
    const element = document.getElementById(id);
    if (element) element.placeholder = nextValue ?? "";
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function toast(message, type = "success") {
    const item = document.createElement("div");
    item.className = `toast ${type}`;
    item.textContent = message;
    document.getElementById("toast-container").appendChild(item);
    setTimeout(() => item.remove(), 3200);
  }

  function debounce(fn, wait) {
    let timer = null;
    return function () {
      clearTimeout(timer);
      timer = setTimeout(fn, wait);
    };
  }
  function togglePasswordVisibility(button) {
    const targetId = button.dataset.target;
    const input = document.getElementById(targetId);
    if (input) {
      const isPassword = input.type === "password";
      input.type = isPassword ? "text" : "password";
      button.textContent = isPassword ? "🙈" : "👁️";
    }
  }
})();
