(function () {
  const now = new Date();
  const today = toDateInput(now);
  const monday = startOfWorkWeek(now);
  const friday = addDays(monday, 4);
  const sheetName = `${monday.getMonth() + 1}.${monday.getDate()}-${friday.getMonth() + 1}.${friday.getDate()}`;
  const periodStart = toDateInput(monday);
  const periodEnd = toDateInput(friday);
  const firstMissingDate = toDateInput(monday);
  const currentTimestampText = `${today} 10:18:40`;

  window.CompetitorMonitorMock = {
    today,
    config: {
      excel_path: "竞品监控.xlsx",
      daily_run_time: "10:00",
      bi_run_saturday: true,
      bi_run_sunday: true,
      auto_backfill_missing_daily_prices_before_weekly_new: true,
      wecom_enabled: true,
      wecom_send_summary: true,
      wecom_send_excel_file: true,
      wecom_webhook_set: true,
      taobao_status: "已保存凭据",
      bi_status: "已保存凭据",
      taobao_login_status: "运行时检测",
      taobao_credential_status: "已保存凭据",
      taobao_username_masked: "188****6603",
      taobao_password_set: true,
      bi_login_status: "运行时检测",
      bi_credential_status: "已保存凭据",
      bi_username_masked: "188****6603",
      bi_password_set: true,
      mode: "daily_price",
      run_date: today,
      dry_run: true,
      test_one: true,
      rows: "",
      limit: "",
      save_every: 5,
      updated_at: currentTimestampText
    },

    tasksStatus: {
      system_status: "idle",
      template_name: "竞品监控.xlsx",
      template_path: "竞品监控.xlsx",
      target_sheet_name: sheetName,
      target_period_range: `${periodStart} 至 ${periodEnd}`,
      progress_total: 86,
      progress_done: 0,
      success_count: 0,
      failed_count: 0,
      skipped_count: 0,
      current_step: "待命",
      last_saved_at: currentTimestampText,
      last_sent_at: "",
      last_notify_text_status: "not_sent",
      last_notify_file_status: "not_sent",
      last_notify_time: null,
      last_notify_error: null,
      last_sent_file_name: null,
      workflow: [
        { key: "detect_date", title: "识别日期", state: "done" },
        { key: "locate_sheet", title: "定位 sheet", state: "done" },
        { key: "write_template", title: "写入模板", state: "pending" },
        { key: "backfill", title: "补跑缺失", state: "pending" },
        { key: "save", title: "保存模板", state: "pending" },
        { key: "notify", title: "推送企微", state: "pending" }
      ],
      tasks: [
        {
          id: "daily_price",
          title: "每日价格采集",
          status: "idle",
          status_text: "待命",
          last_run: "",
          last_result: "等待运行",
          template_status: sheetName,
          notify_status: "not_sent"
        },
        {
          id: "weekly_new",
          title: "周末 BI 上新采集",
          status: "idle",
          status_text: "待命",
          last_run: "",
          last_result: "等待运行",
          template_status: sheetName,
          notify_status: "not_sent",
          precheck: "价格完整性待检查"
        }
      ],
      maintenance: { logs: 4, backups: 3, exports: 0, sessions: 2 },
      ui: { primary_action: "backfill" }
    },

    completeness: {
      sheet_name: sheetName,
      period_start: periodStart,
      period_end: periodEnd,
      complete: false,
      energy_percent: 80,
      missing_dates: [firstMissingDate],
      days: Array.from({ length: 5 }, (_, index) => {
        const day = addDays(monday, index);
        const date = toDateInput(day);
        const complete = index > 0;
        return {
          date,
          label: `周${"一二三四五"[index]}`,
          status: complete ? "complete" : "missing",
          state: complete ? "complete" : "missing",
          filled_count: complete ? 86 : 0,
          total_count: 86,
          missing_rows: complete ? [] : [4, 5, 24]
        };
      })
    },

    logs: [
      log("info", `系统识别运行日期为 ${today}。`, `目标周期：${periodStart} 至 ${periodEnd}`),
      log("warning", `模板完整性检查发现缺失日期：${firstMissingDate}。`, "系统会先补跑每日价格，再写入后续数据。"),
      log("success", "主模板已保存。", "竞品监控.xlsx"),
      log("success", "企业微信摘要和主模板已发送。", "发送文件：竞品监控.xlsx")
    ],

    results: [
      result("daily_price", sheetName, "塞那", "S6S proII", "success", "268.52", `${today} 10:12:20`),
      result("daily_price", sheetName, "塞那", "S6S Ultra", "success", "305.24", `${today} 10:13:44`),
      result("daily_price", sheetName, "水月雨", "太空漫游2", "success", "149", `${today} 10:15:01`),
      result("daily_price", sheetName, "金运", "A5", "failed", "", `${today} 10:16:19`, "未匹配到明确 A5 SKU，已留空"),
      result("weekly_new", sheetName, "绿联", "S6PRO", "success", "199", `${today} 10:21:12`)
    ]
  };

  function result(mode, sheet, brand, model, status, output, time, errorReason = "") {
    return {
      id: `${mode}-${brand}-${model}`,
      mode,
      sheet,
      brand,
      model,
      status,
      output,
      error_reason: errorReason,
      time,
      detail: {
        brand,
        model,
        sheet,
        output,
        note: errorReason || "处理完成",
        webhook: "******",
        password: "******"
      }
    };
  }

  function log(level, message, detail) {
    return {
      id: `${level}-${message}`,
      time: currentTimestampText,
      level,
      message,
      detail
    };
  }

  function startOfWorkWeek(date) {
    const copy = new Date(date);
    const day = copy.getDay() || 7;
    copy.setDate(copy.getDate() - day + 1);
    copy.setHours(0, 0, 0, 0);
    return copy;
  }

  function addDays(date, days) {
    const copy = new Date(date);
    copy.setDate(copy.getDate() + days);
    return copy;
  }

  function toDateInput(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }
})();
