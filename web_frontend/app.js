(function () {
  const API = window.CompetitorMonitorAPI;
  const UIState = window.CompetitorMonitorUIState;
  const SECRET_PLACEHOLDER = "******";
  const CONFIG_SAVE_BUTTON_IDS = ["btn-save-config", "btn-save-identity-config"];
  const state = {
    tasks: null,
    completeness: null,
    config: null,
    logs: [],
    results: [],
    resultQuick: "all",
    clearedLogKeys: new Set(),
    configDirty: false,
    pollTimer: null,
    pollTick: 0
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
    state.pollTimer = setInterval(refreshStatusOnly, 1200);
  }

  function bindEvents() {
    document.querySelectorAll("[data-tab]").forEach(button => {
      button.addEventListener("click", () => switchTab(button.dataset.tab));
    });
    document.getElementById("btn-refresh").addEventListener("click", refreshAll);
    document.getElementById("btn-run-daily").addEventListener("click", () => handleTaskPrimary("daily_price"));
    document.getElementById("btn-run-weekly").addEventListener("click", () => handleTaskPrimary("weekly_new"));
    document.getElementById("btn-stop-task").addEventListener("click", stopTask);
    document.getElementById("btn-backfill-missing").addEventListener("click", backfillMissingDates);
    document.getElementById("btn-loop-primary").addEventListener("click", handleLoopPrimaryAction);
    document.getElementById("btn-loop-check").addEventListener("click", loadCompleteness);
    document.getElementById("btn-send-template-main").addEventListener("click", () => sendTemplate("btn-send-template-main"));
    document.getElementById("btn-download-template").addEventListener("click", () => downloadTemplate("btn-download-template"));
    document.getElementById("btn-upload-template").addEventListener("click", uploadTemplate);
    document.getElementById("btn-download-template-config").addEventListener("click", () => downloadTemplate("btn-download-template-config"));
    document.getElementById("btn-sync-template").addEventListener("click", () => syncTemplate("btn-sync-template"));
    document.getElementById("btn-sync-template-main").addEventListener("click", () => syncTemplate("btn-sync-template-main"));
    document.getElementById("log-filter-level").addEventListener("change", renderLogs);
    document.getElementById("log-search-query").addEventListener("input", debounce(renderLogs, 200));
    document.getElementById("btn-clear-logs").addEventListener("click", cleanupLogs);
    document.getElementById("result-filter-status").addEventListener("change", renderResults);
    document.getElementById("result-filter-mode").addEventListener("change", renderResults);
    document.getElementById("result-search-query").addEventListener("input", debounce(renderResults, 200));
    document.getElementById("btn-export-results").addEventListener("click", exportResults);
    document.getElementById("btn-clear-results").addEventListener("click", cleanupResults);
    const configForm = document.getElementById("config-form");
    configForm.addEventListener("submit", saveConfig);
    configForm.querySelectorAll("input, select").forEach(control => {
      if (control.type === "file" || control.readOnly) return;
      control.addEventListener("input", () => setConfigDirty(true));
      control.addEventListener("change", () => setConfigDirty(true));
    });
    window.addEventListener("beforeunload", event => {
      if (!state.configDirty) return;
      event.preventDefault();
      event.returnValue = "";
    });
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
    state.pollTick += 1;
    const tasks = [loadStatus()];
    if (state.pollTick % 4 === 0) {
      tasks.push(loadLogs(), loadResults());
    }
    if (state.pollTick % 12 === 0) {
      tasks.push(loadCompleteness());
    }
    await Promise.allSettled(tasks);
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
    const logs = await API.getLogs(level, query);
    state.logs = logs.filter(item => !state.clearedLogKeys.has(logKey(item)));
    renderLogsFromState();
    renderConsoleLogs();
  }

  async function loadResults() {
    const status = document.getElementById("result-filter-status").value;
    const mode = document.getElementById("result-filter-mode").value;
    const query = document.getElementById("result-search-query").value.trim();
    state.results = await API.getResults(status, mode, query);
    renderResultsFromState();
    renderConsoleResults();
  }

  function renderStatus() {
    const data = state.tasks || {};
    const daily = (data.tasks || []).find(task => task.id === "daily_price") || {};
    const weekly = (data.tasks || []).find(task => task.id === "weekly_new") || {};
    const running = UIState.isLiveStatus(data.system_status);
    const activeTask = UIState.activeTaskId(data);
    const progressDone = Number(data.progress_done || 0);
    const progressTotal = Number(data.progress_total || 0);
    const progressPercent = progressTotal > 0 ? Math.max(0, Math.min(100, Math.round((progressDone / progressTotal) * 100))) : 0;
    document.body.classList.toggle("task-is-running", running);
    const runningBanner = document.getElementById("running-banner");
    if (runningBanner) {
      runningBanner.hidden = !running;
      text("running-banner-title", "后台任务正在运行");
      text("running-banner-step", data.current_step || "正在处理任务");
      text("running-banner-mode", modeLabel(data.active_mode || "daily_price"));
      text("running-banner-progress", progressTotal ? `${progressDone} / ${progressTotal}` : "正在启动");
      const runningProgressBar = document.getElementById("running-banner-progress-bar");
      if (runningProgressBar) {
        runningProgressBar.style.width = progressTotal ? `${progressPercent}%` : "100%";
        runningProgressBar.classList.toggle("is-indeterminate", !progressTotal);
      }
    }
    const syncStatus = data.workbook_sync_status || "synced";
    const syncBanner = document.getElementById("workbook-sync-banner");
    if (syncBanner) {
      const showSyncBanner = syncStatus && syncStatus !== "synced";
      syncBanner.hidden = !showSyncBanner;
      syncBanner.classList.toggle("danger", syncStatus === "sync_failed");
      text("workbook-sync-banner-title", workbookSyncStatusLabel(syncStatus));
      text("workbook-sync-banner-detail", data.last_workbook_sync_error || "当前最新工作簿已保存，主模板释放后可同步。");
    }
    badge("global-status-badge", UIState.statusText(data.system_status), UIState.statusTone(data.system_status));
    text("side-template-name", data.template_name || "竞品监控.xlsx");
    text("side-health-text", UIState.statusText(data.system_status));
    const sideHealthDot = document.getElementById("side-health-dot");
    if (sideHealthDot) sideHealthDot.className = `status-dot ${running ? "active" : data.system_status === "failed" ? "danger" : "ok"}`;
    
    // 渲染全局 KPI 模块。
    text("kpi-progress-done", data.progress_done || "0");
    text("kpi-progress-total", data.progress_total || "0");
    text("kpi-success", data.success_count || "0");
    text("kpi-failed", data.failed_count || "0");
    // 渲染登录状态 (读取保存的配置信息)
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
    text("weekly-notify-status", notifyStatusLabel(data.last_notify_file_status, data.notify_enabled));
    text("loop-target-sheet", data.target_sheet_name || "-");
    text("loop-target-period", data.target_period_range || "-");
    text("loop-saved-at", data.last_saved_at || "-");
    text("loop-sent-at", data.last_sent_at || "-");
    text("notify-text-status", notifyStatusLabel(data.last_notify_text_status, data.notify_enabled));
    text("notify-file-status", notifyStatusLabel(data.last_notify_file_status, data.notify_enabled));
    text("notify-time", data.last_notify_time || "-");
    text("notify-file-name", data.last_sent_file_name || "-");
    text("notify-error", data.last_notify_error || "-");
    badge("daily-status", daily.status_text || UIState.statusText(daily.status), UIState.statusTone(daily.status));
    badge("weekly-status", weekly.status_text || UIState.statusText(weekly.status), UIState.statusTone(weekly.status));

    // 动态显示任务运行提示。定时任务来自独立进程时，以全局 active_mode 为准。
    setTaskCardRunning("daily-task-card", "daily-running-note", running && activeTask === "daily_price", data, progressPercent);
    setTaskCardRunning("weekly-task-card", "weekly-running-note", running && activeTask === "weekly_new", data, progressPercent);
    const stopRequested = Boolean(data.stop_requested);
    text("btn-run-daily", running && activeTask === "daily_price" ? (stopRequested ? "停止请求已发送" : "请求停止") : "手动运行");
    text("btn-run-weekly", running && activeTask === "weekly_new" ? (stopRequested ? "停止请求已发送" : "请求停止") : "手动运行 BI");
    text("btn-stop-task", stopRequested ? "停止请求已发送" : "请求停止");

    setDisabled("btn-run-daily", running && activeTask !== "daily_price" || stopRequested);
    setDisabled("btn-run-weekly", running && activeTask !== "weekly_new" || stopRequested);
    setDisabled("btn-stop-task", !running || stopRequested);
    setDisabled("btn-backfill-missing", running);
    setDisabled("btn-loop-primary", running);
  }

  function setTaskCardRunning(cardId, noteId, running, data = {}, progressPercent = 0) {
    const card = document.getElementById(cardId);
    const note = document.getElementById(noteId);
    if (card) {
      card.classList.toggle("task-card-running", running);
      card.classList.toggle("active", running);
    }
    if (!note) return;
    note.hidden = !running;
    if (!running) return;
    const progressTotal = Number(data.progress_total || 0);
    const progressDone = Number(data.progress_done || 0);
    const step = note.querySelector("[data-running-step]");
    const progress = note.querySelector("[data-running-progress]");
    const bar = note.querySelector("[data-running-bar]");
    if (step) step.textContent = data.current_step || "正在处理任务";
    if (progress) progress.textContent = progressTotal ? `${progressDone} / ${progressTotal}` : "正在启动";
    if (bar) {
      bar.style.width = progressTotal ? `${progressPercent}%` : "100%";
      bar.classList.toggle("is-indeterminate", !progressTotal);
    }
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

    // 渲染本周价格完整度进度条和数值。
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
      const filled = Number((state.completeness || {}).filled_count || 0);
      const total = Number((state.completeness || {}).total_count || 0);
      const missingDates = Array.isArray(view.missingDates) ? view.missingDates : [];
      const summaryItems = [
        { tone: total && filled === total ? "success" : missingDates.length ? "warning" : "neutral", title: "本周填报", detail: total ? `${filled}/${total} 个价格单元格已填写` : "当前模板暂未识别到价格单元格" },
        { tone: missingDates.length ? "warning" : "success", title: "缺失日期", detail: missingDates.length ? missingDates.join("、") : "周一到周五价格列已完整" }
      ];
      workflowList.innerHTML = summaryItems
        .map(item => `<div class="workflow-item ${item.tone}"><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.detail)}</span></div>`)
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
    value("cfg-weekly-new-time", config.weekly_new_time || "09:30");
    value("cfg-price-trend-time", config.price_trend_time || "18:30");
    value("cfg-bi-sat", String(Boolean(config.bi_run_saturday)));
    value("cfg-bi-sun", String(Boolean(config.bi_run_sunday)));
    value("cfg-auto-backfill", String(Boolean(config.auto_backfill_missing_daily_prices_before_weekly_new)));
    value("cfg-wecom-enabled", String(Boolean(config.wecom_enabled)));
    value("cfg-wecom-summary", String(Boolean(config.wecom_send_summary)));
    value("cfg-wecom-template", String(Boolean(config.wecom_send_excel_file)));
    value("cfg-wecom-webhook", config.wecom_webhook_set ? SECRET_PLACEHOLDER : "");
    value("cfg-excel-path", config.excel_path || "竞品监控.xlsx");
    text("template-current-name", config.template_name || "竞品监控.xlsx");
    text("template-current-path", config.template_path || config.excel_path || "项目根目录/竞品监控.xlsx");
    text("template-validation-status", config.template_validation_status || "待验证");
    text("template-uploaded-at", config.template_uploaded_at || "-");
    badge("template-sync-status", config.workbook_sync_status_text || workbookSyncStatusLabel(config.workbook_sync_status), workbookSyncTone(config.workbook_sync_status));
    text("template-primary-path", config.primary_workbook_path || "-");
    text("template-active-path", config.active_workbook_path || config.template_path || "-");
    text("template-last-sync-at", config.last_workbook_sync_at || "-");
    text("template-last-sync-error", config.last_workbook_sync_error || "-");
    text("template-run-workbook-count", config.run_workbook_count ?? 0);
    const pendingSync = config.workbook_sync_status && config.workbook_sync_status !== "synced";
    const pendingHint = document.getElementById("template-pending-sync-hint");
    if (pendingHint) pendingHint.hidden = !pendingSync;
    setDisabled("template-upload-input", Boolean(pendingSync));
    setDisabled("btn-upload-template", Boolean(pendingSync));
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
    const weeklyDays = [config.bi_run_saturday ? "周六" : "", config.bi_run_sunday ? "周日" : ""].filter(Boolean).join(" / ");
    text("weekly-schedule", weeklyDays ? `${weeklyDays} ${config.weekly_new_time || "09:30"}` : "未启用");
    setConfigDirty(false);
  }

  async function renderLogs() {
    await loadLogs();
  }

  function renderLogsFromState() {
    const wrap = document.getElementById("logs-table-body");
    wrap.innerHTML = state.logs.map(logItemHtml).join("");
    document.getElementById("logs-empty-state").style.display = state.logs.length ? "none" : "flex";
    const autoScroll = document.getElementById("log-auto-scroll");
    if (autoScroll && autoScroll.checked && wrap) {
      wrap.scrollTop = wrap.scrollHeight;
    }
  }

  function renderConsoleLogs() {
    document.getElementById("console-log-preview").innerHTML = state.logs.slice(0, 3).map(logItemHtml).join("");
  }

  function renderConsoleResults() {
    const wrap = document.getElementById("console-result-preview");
    if (!wrap) return;
    const items = state.results.slice(0, 3);
    wrap.innerHTML = items.length
      ? items.map(resultPreviewHtml).join("")
      : `<div class="summary-empty">暂无结果记录</div>`;
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
          <div><strong>${escapeHtml(item.brand || "-")} ${escapeHtml(item.model || "-")}</strong><span>${escapeHtml(item.sheet || "-")} · ${escapeHtml(modeLabel(item.mode))}</span></div>
          <div><span>${escapeHtml(item.output || item.error_reason || "-")}</span><small>${escapeHtml(item.time || "-")}</small></div>
          <span class="badge ${UIState.statusTone(item.status)}">${escapeHtml(resultStatusLabel(item.status))}</span>
          <button class="btn ghost small" type="button" data-detail-id="${escapeHtml(item.id)}">详情</button>
        </div>`
      )
      .join("");
    wrap.querySelectorAll("[data-detail-id]").forEach(button => {
      button.addEventListener("click", () => openDetail(button.dataset.detailId));
    });
    document.getElementById("results-empty-state").style.display = list.length ? "none" : "flex";
  }

  async function handleTaskPrimary(mode) {
    const data = state.tasks || {};
    const running = UIState.isLiveStatus(data.system_status);
    const activeTask = UIState.activeTaskId(data);
    if (running && activeTask === mode) {
      await stopTask(mode === "weekly_new" ? "btn-run-weekly" : "btn-run-daily");
      return;
    }
    if (running) {
      toast("已有任务正在运行，请先停止或等待完成", "warning");
      return;
    }
    await runTask(mode);
  }

  async function runTask(mode) {
    const payload = buildRunPayload(mode);
    await withButtonLoading(mode === "weekly_new" ? "btn-run-weekly" : "btn-run-daily", async () => {
      await API.runTask(payload);
      toast("任务已提交，页面会自动刷新状态", "success");
      await refreshAll();
    });
  }

  async function downloadTemplate(buttonId = "btn-download-template") {
    await withButtonLoading(buttonId, async () => {
      const blob = await API.downloadTemplate();
      const data = state.tasks || {};
      const fileName = data.template_name || (state.config && state.config.template_name) || "竞品监控.xlsx";
      downloadBlob(blob, fileName);
      toast(`已开始下载当前模板：${fileName}`, "success");
    });
  }

  async function uploadTemplate() {
    if (state.config && state.config.workbook_sync_status && state.config.workbook_sync_status !== "synced") {
      toast("主模板待同步，请先同步主模板后再上传新模板", "warning");
      return;
    }
    const input = document.getElementById("template-upload-input");
    const file = input && input.files ? input.files[0] : null;
    if (!file) {
      toast("请先选择一个 .xlsx 模板文件", "warning");
      return;
    }
    if (!file.name.toLowerCase().endsWith(".xlsx")) {
      toast("只支持上传 .xlsx 模板文件", "error");
      return;
    }
    if (!confirm(`确认上传并替换当前主模板？\n\n文件：${file.name}\n\n后端会先校验模板，校验通过后备份旧模板再替换。`)) return;
    await withButtonLoading("btn-upload-template", async () => {
      const response = await API.uploadTemplate(file);
      toast(response.message || "模板已上传", response.error ? "error" : "success");
      if (!response.error && input) input.value = "";
      await refreshAll();
    });
  }

  async function stopTask(buttonId = "btn-stop-task") {
    if (!confirm("确认请求停止当前任务？当前正在处理的单条商品会先安全结束，然后停止后续处理。")) return;
    await withButtonLoading(buttonId, async () => {
      await API.stopTask();
      state.tasks = {
        ...(state.tasks || {}),
        stop_requested: true,
        current_step: "已请求停止，等待当前商品安全结束"
      };
      renderStatus();
      toast("已请求停止当前任务", "warning");
      await loadStatus();
    });
  }

  async function backfillMissingDates() {
    const missing = state.completeness ? state.completeness.missing_dates : [];
    if (!missing.length) {
      toast("模板已完整，无需补跑", "success");
      return;
    }
    if (!confirm(`确认补跑缺失日期？\n\n缺失日期：${missing.join("、")}\n\n补跑会启动后端安全任务，运行中不能重复启动。`)) return;
    await withButtonLoading("btn-backfill-missing", async () => {
      await API.backfillTemplate({ dates: missing });
      toast("缺失日期已提交补跑", "success");
      await refreshAll();
    });
  }

  async function handleLoopPrimaryAction() {
    const action = document.getElementById("btn-loop-primary").dataset.action;
    if (action === "send_template") return sendTemplate("btn-loop-primary");
    if (action === "run_daily") return runTask("daily_price");
    return backfillMissingDates();
  }

  async function sendTemplate(buttonId = "btn-send-template-main") {
    if (!confirm("确认发送当前已保存的 Excel 模板到企业微信群？")) return;
    await withButtonLoading(buttonId, async () => {
      const response = await API.sendTemplate();
      toast(response.message || "当前模板已发送", response.error ? "error" : "success");
      await refreshAll();
    });
  }

  async function syncTemplate(buttonId = "btn-sync-template") {
    if (!confirm("确认将当前最新工作簿同步回主模板？\n\n如果主模板仍被 Excel/WPS 占用，本次同步会保留待同步状态，稍后可以重试。")) return;
    await withButtonLoading(buttonId, async () => {
      const response = await API.syncTemplate();
      toast(response.message || "同步请求已提交", response.error ? "warning" : "success");
      await refreshAll();
    });
  }

  async function saveConfig(event) {
    event.preventDefault();
    const saveButtonId = event.submitter && event.submitter.id ? event.submitter.id : "btn-save-config";
    const payload = {
      daily_run_time: document.getElementById("cfg-daily-time").value,
      weekly_new_time: document.getElementById("cfg-weekly-new-time").value,
      price_trend_time: document.getElementById("cfg-price-trend-time").value,
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
    await withConfigSaveLoading(saveButtonId, async () => {
      await API.saveConfig(payload);
      setConfigDirty(false);
      toast("配置已保存，计划任务正在后台同步", "success");
      await loadConfig();
    });
  }

  async function exportResults() {
    await withButtonLoading("btn-export-results", async () => {
      const blob = await API.exportResults();
      downloadBlob(blob, "竞品监控结果记录.csv");
      toast("本次结果已开始导出", "success");
    });
  }

  async function cleanupResults() {
    if (!confirm("只清空 Web 控制台保存的结果记录，不会删除 Excel、日志或备份文件。确认继续？")) return;
    await withButtonLoading("btn-clear-results", async () => {
      const response = await API.cleanupMaintenance("results");
      state.results = [];
      renderResultsFromState();
      renderConsoleResults();
      toast(response.message || "结果记录已清空", "success");
    });
  }

  async function cleanupLogs() {
    if (!confirm("只清空当前 Web 页面展示的日志视图，不会物理删除 logs/ 文件夹。确认继续？")) return;
    state.logs.forEach(item => state.clearedLogKeys.add(logKey(item)));
    state.logs = [];
    renderLogsFromState();
    renderConsoleLogs();
    toast("当前视图日志已清空", "success");
  }

  async function resetSession(target) {
    const label = target === "taobao" ? "淘宝" : "BI";
    if (!confirm(`确认清除 ${label} 浏览器登录状态？\n\n清除后下次运行可能需要重新登录或人工验证。`)) return;
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

  function notifyStatusLabel(status, enabled) {
    if (!enabled) return "未启用";
    const map = {
      not_sent: "未发送",
      success: "发送成功",
      failed: "发送失败"
    };
    return map[status] || status || "未发送";
  }

  function workbookSyncStatusLabel(status) {
    const map = {
      synced: "已同步",
      pending_sync: "主模板待同步",
      sync_failed: "同步失败"
    };
    return map[status] || status || "已同步";
  }

  function workbookSyncTone(status) {
    if (status === "synced" || !status) return "success";
    if (status === "sync_failed") return "danger";
    return "warning";
  }

  function resultStatusLabel(status) {
    const map = {
      success: "成功",
      failed: "失败",
      skipped: "跳过",
      warning: "需复核"
    };
    return map[status] || status || "-";
  }

  function modeLabel(mode) {
    const map = {
      daily_price: "每日价格",
      weekly_new: "周末 BI",
      price_trend: "价格情况",
      all: "全部任务"
    };
    return map[mode] || mode || "-";
  }

  function downloadBlob(blob, fileName) {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = fileName;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  }

  function applyResultQuickFilter(list) {
    if (state.resultQuick === "failed") return list.filter(item => item.status === "failed");
    if (state.resultQuick === "today") {
      const today = window.CompetitorMonitorMock ? window.CompetitorMonitorMock.today : new Date().toISOString().slice(0, 10);
      return list.filter(item => String(item.time || "").startsWith(today));
    }
    return list;
  }

  function logKey(item) {
    return [item.id, item.time, item.level, item.message, item.detail].map(value => String(value ?? "")).join("|");
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

  function resultPreviewHtml(item) {
    return `
      <div class="result-preview-item ${escapeHtml(item.status)}">
        <div>
          <strong>${escapeHtml(item.brand || "-")} ${escapeHtml(item.model || "-")}</strong>
          <span>${escapeHtml(item.sheet || "-")} · ${escapeHtml(modeLabel(item.mode))}</span>
        </div>
        <span class="badge ${UIState.statusTone(item.status)}">${escapeHtml(resultStatusLabel(item.status))}</span>
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

  function setConfigDirty(dirty) {
    state.configDirty = Boolean(dirty);
    const status = document.getElementById("config-save-state");
    if (!status) return;
    status.textContent = state.configDirty ? "有未保存修改" : "已保存";
    status.className = `config-save-state ${state.configDirty ? "dirty" : "saved"}`;
  }

  async function withConfigSaveLoading(activeId, fn) {
    const activeButtonId = CONFIG_SAVE_BUTTON_IDS.includes(activeId) ? activeId : "btn-save-config";
    const buttons = CONFIG_SAVE_BUTTON_IDS
      .map(id => document.getElementById(id))
      .filter(Boolean);
    buttons.forEach(button => {
      button.disabled = true;
      button.classList.toggle("saving-loading", button.id === activeButtonId);
    });
    try {
      await fn();
    } catch (error) {
      toast(error.message || "操作失败", "error");
    } finally {
      buttons.forEach(button => {
        button.disabled = false;
        button.classList.remove("saving-loading");
      });
    }
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
      button.textContent = isPassword ? "隐藏" : "显示";
    }
  }
})();
