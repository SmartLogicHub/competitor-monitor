(function () {
  const API = {};
  API.USE_MOCK = window.location.protocol === "file:";
  API.BASE_URL = "";

  let connectionErrorCallback = null;
  let connectionRestoreCallback = null;
  let isOffline = false;

  API.onConnectionError = function (callback) {
    connectionErrorCallback = callback;
  };

  API.onConnectionRestore = function (callback) {
    connectionRestoreCallback = callback;
  };

  async function request(url, method = "GET", body = null) {
    const options = {
      method,
      headers: { "Content-Type": "application/json" }
    };
    if (body) options.body = JSON.stringify(body);

    try {
      const response = await fetch(`${API.BASE_URL}${url}`, options);
      if (isOffline) {
        isOffline = false;
        if (connectionRestoreCallback) connectionRestoreCallback();
      }
      if (!response.ok) {
        let message = `HTTP ${response.status}`;
        try {
          const payload = await response.json();
          message = payload.message || payload.error || message;
        } catch (_) {}
        throw new Error(message);
      }
      if (url.includes("/export")) return response.blob();
      return response.json();
    } catch (error) {
      if (error instanceof TypeError && error.message.includes("fetch")) {
        if (!isOffline) {
          isOffline = true;
          if (connectionErrorCallback) connectionErrorCallback();
        }
      }
      throw error;
    }
  }

  API.getTasksStatus = async function () {
    if (API.USE_MOCK) return mockDelay(() => clone(window.CompetitorMonitorMock.tasksStatus));
    return request("/api/tasks/status");
  };

  API.getTemplateCompleteness = async function (date) {
    if (API.USE_MOCK) return mockDelay(() => clone(window.CompetitorMonitorMock.completeness));
    const query = date ? `?date=${encodeURIComponent(date)}` : "";
    return request(`/api/template/completeness${query}`);
  };

  API.backfillTemplate = async function (payload = {}) {
    if (API.USE_MOCK) {
      return mockDelay(() => {
        const mock = window.CompetitorMonitorMock;
        const targetDates = payload.dates && payload.dates.length ? payload.dates : mock.completeness.missing_dates;
        mock.completeness.days = mock.completeness.days.map(day =>
          targetDates.includes(day.date)
            ? { ...day, status: "complete", state: "complete", filled_count: day.total_count || 86, missing_rows: [] }
            : day
        );
        mock.completeness.missing_dates = mock.completeness.days.filter(day => day.status !== "complete").map(day => day.date);
        mock.completeness.complete = mock.completeness.missing_dates.length === 0;
        mock.completeness.energy_percent = mock.completeness.complete ? 100 : mock.completeness.energy_percent;
        mock.logs.unshift(makeLog("success", `已补跑缺失日期：${targetDates.join("、")}`, "补跑结果已写入并保存到主 Excel 模板。"));
        return { message: "补跑完成", backfilled_dates: targetDates };
      });
    }
    return request("/api/template/backfill", "POST", payload);
  };

  API.runTask = async function (payload = {}) {
    if (API.USE_MOCK) {
      return mockDelay(() => {
        const mock = window.CompetitorMonitorMock;
        const mode = payload.mode || "daily_price";
        mock.tasksStatus.system_status = "success";
        mock.tasksStatus.progress_done = mock.tasksStatus.progress_total || 86;
        mock.tasksStatus.success_count = Math.max(1, mock.tasksStatus.progress_done - 1);
        mock.tasksStatus.failed_count = mode === "daily_price" ? 1 : 0;
        mock.tasksStatus.current_step = "任务完成";
        mock.tasksStatus.last_saved_at = currentTimestamp();
        mock.tasksStatus.last_sent_at = currentTimestamp();
        mock.tasksStatus.last_notify_text_status = "success";
        mock.tasksStatus.last_notify_file_status = "success";
        mock.tasksStatus.last_notify_time = currentTimestamp();
        mock.tasksStatus.last_sent_file_name = "竞品监控.xlsx";
        const safety = [payload.dry_run ? "dry-run" : "", payload.test_one ? "test-one" : ""].filter(Boolean).join(" / ") || "正式运行";
        mock.logs.unshift(makeLog("success", `任务完成：${mode}`, `运行日期：${payload.run_date || "-"}；模式：${safety}；后端完成保存后自动触发企业微信发送。`));
        return { message: "任务已启动" };
      });
    }
    return request("/api/tasks/run", "POST", payload);
  };

  API.stopTask = async function () {
    if (API.USE_MOCK) {
      return mockDelay(() => {
        window.CompetitorMonitorMock.tasksStatus.system_status = "stopped";
        window.CompetitorMonitorMock.tasksStatus.current_step = "已请求停止";
        window.CompetitorMonitorMock.logs.unshift(makeLog("warning", "已请求停止当前任务", "任务会在安全位置停止。"));
        return { message: "已请求停止当前任务" };
      });
    }
    return request("/api/tasks/stop", "POST");
  };

  API.sendTemplate = async function () {
    if (API.USE_MOCK) {
      return mockDelay(() => {
        const mock = window.CompetitorMonitorMock;
        mock.tasksStatus.last_sent_at = currentTimestamp();
        mock.tasksStatus.last_notify_text_status = "success";
        mock.tasksStatus.last_notify_file_status = "success";
        mock.tasksStatus.last_notify_time = currentTimestamp();
        mock.tasksStatus.last_sent_file_name = "竞品监控.xlsx";
        mock.logs.unshift(makeLog("success", "已发送当前模板", "摘要和 Excel 文件已提交企业微信。"));
        return { message: "当前模板已发送" };
      });
    }
    return request("/api/notify/send-template", "POST");
  };

  API.getConfig = async function () {
    if (API.USE_MOCK) return mockDelay(() => clone(window.CompetitorMonitorMock.config));
    return request("/api/config");
  };

  API.saveConfig = async function (config) {
    if (API.USE_MOCK) {
      return mockDelay(() => {
        Object.assign(window.CompetitorMonitorMock.config, config, { updated_at: currentTimestamp() });
        window.CompetitorMonitorMock.logs.unshift(makeLog("success", "配置已保存", "自动计划、企业微信和模板路径已更新。"));
        return { message: "配置已保存" };
      });
    }
    return request("/api/config", "POST", config);
  };

  API.getLogs = async function (level = "all", query = "") {
    if (API.USE_MOCK) {
      return mockDelay(() => filterLogs(level, query));
    }
    return request(`/api/logs?level=${encodeURIComponent(level)}&q=${encodeURIComponent(query)}`);
  };

  API.getResults = async function (status = "all", mode = "all", query = "") {
    if (API.USE_MOCK) {
      return mockDelay(() => filterResults(status, mode, query));
    }
    return request(`/api/results?status=${encodeURIComponent(status)}&mode=${encodeURIComponent(mode)}&q=${encodeURIComponent(query)}`);
  };

  API.exportResults = async function () {
    if (API.USE_MOCK) {
      const rows = ["time,mode,sheet,brand,model,status,output,error_reason"];
      window.CompetitorMonitorMock.results.forEach(item => {
        rows.push([item.time, item.mode, item.sheet, item.brand, item.model, item.status, item.output, item.error_reason || ""].map(csvCell).join(","));
      });
      return mockDelay(() => new Blob([rows.join("\n")], { type: "text/csv;charset=utf-8" }));
    }
    return request("/api/results/export");
  };

  API.cleanupMaintenance = async function (scope) {
    if (API.USE_MOCK) {
      return mockDelay(() => {
        if (scope === "logs") window.CompetitorMonitorMock.logs = [];
        return { message: scope === "logs" ? "当前视图日志已清空" : "清理请求已记录" };
      });
    }
    return request("/api/maintenance/cleanup", "POST", { scope });
  };

  API.resetSession = async function (target) {
    if (API.USE_MOCK) {
      return mockDelay(() => {
        if (target === "taobao") {
          window.CompetitorMonitorMock.config.taobao_status = "需重新登录";
          window.CompetitorMonitorMock.config.taobao_login_status = "需重新登录";
        }
        if (target === "bi") {
          window.CompetitorMonitorMock.config.bi_status = "需重新登录";
          window.CompetitorMonitorMock.config.bi_login_status = "需重新登录";
        }
        window.CompetitorMonitorMock.logs.unshift(makeLog("warning", `已重置登录状态：${target}`, "下次运行会重新检查登录。"));
        return { message: "登录状态已重置" };
      });
    }
    return request("/api/session/reset", "POST", { target });
  };

  function filterLogs(level, query) {
    let list = clone(window.CompetitorMonitorMock.logs);
    if (level && level !== "all") list = list.filter(item => item.level === level);
    if (query) {
      const q = query.toLowerCase();
      list = list.filter(item => item.message.toLowerCase().includes(q) || item.detail.toLowerCase().includes(q));
    }
    return list;
  }

  function filterResults(status, mode, query) {
    let list = clone(window.CompetitorMonitorMock.results);
    if (status && status !== "all") list = list.filter(item => item.status === status);
    if (mode && mode !== "all") list = list.filter(item => item.mode === mode);
    if (query) {
      const q = query.toLowerCase();
      list = list.filter(item => item.brand.toLowerCase().includes(q) || item.model.toLowerCase().includes(q));
    }
    return list;
  }

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function mockDelay(fn) {
    return new Promise((resolve, reject) => {
      setTimeout(() => {
        try {
          resolve(fn());
        } catch (error) {
          reject(error);
        }
      }, 180);
    });
  }

  function makeLog(level, message, detail) {
    return {
      id: `${Date.now()}-${Math.random()}`,
      time: currentTimestamp(),
      level,
      message,
      detail
    };
  }

  function currentTimestamp() {
    const now = new Date();
    const pad = value => String(value).padStart(2, "0");
    return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
  }

  function csvCell(value) {
    return `"${String(value ?? "").replaceAll('"', '""')}"`;
  }

  window.CompetitorMonitorAPI = API;
})();
