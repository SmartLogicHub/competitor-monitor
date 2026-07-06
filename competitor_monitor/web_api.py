from __future__ import annotations

import csv
import io
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from config_service import load_config
from credential_service import load_bi_credentials, load_taobao_credentials, save_account_credentials
from date_service import build_sheet_name, get_work_week
from excel_service import ExcelService, TemplateCompleteness
from wecom_service import WeComNotifyError, send_wecom_template


SECRET_PLACEHOLDER = "******"
Runner = Callable[["RunContext"], None]
Notifier = Callable[[dict[str, Any], Path, str], dict[str, str | None]]


@dataclass
class RunContext:
    service: "WebApiService"
    payload: dict[str, Any]
    stop_event: threading.Event

    def stop_requested(self) -> bool:
        return self.stop_event.is_set()

    def set_total(self, total: int) -> None:
        self.service.set_progress_total(total)

    def set_step(self, step: str) -> None:
        self.service.set_current_step(step)

    def record_result(self, result: dict[str, Any]) -> None:
        self.service.record_result(result)

    def log(self, level: str, message: str, detail: str = "") -> None:
        self.service.log(level, message, detail)


class WebApiService:
    def __init__(
        self,
        base_dir: Path | str | None = None,
        config_path: Path | str | None = None,
        runner: Runner | None = None,
        notifier: Notifier | None = None,
    ) -> None:
        self.base_dir = Path(base_dir or Path.cwd()).resolve()
        self.config_path = Path(config_path) if config_path else self.base_dir / "competitor_monitor" / "config.yaml"
        if not self.config_path.is_absolute():
            self.config_path = self.base_dir / self.config_path
        self.runner = runner or self._default_runner
        self.notifier = notifier or send_wecom_template
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.current_thread: threading.Thread | None = None
        self.logs: list[dict[str, Any]] = []
        self.results: list[dict[str, Any]] = []
        self.session_status = {"taobao": None, "bi": None}
        self.status: dict[str, Any] = self._initial_status()

    def get_tasks_status(self) -> dict[str, Any]:
        with self.lock:
            config = self._load_config()
            status = dict(self.status)
            excel_path = self._resolve_path(config.get("excel_path", "竞品监控.xlsx"))
            status.update(
                {
                    "template_name": excel_path.name,
                    "template_path": self._display_path(excel_path),
                    "maintenance": self._maintenance_counts(config),
                    "tasks": self._task_cards(config),
                    "workflow": self._workflow(status["system_status"]),
                    "ui": {"primary_action": self._primary_action(status["system_status"])},
                    "notify_enabled": bool(config.get("wecom_enabled", False)),
                }
            )
            return self._sanitize(status)

    def get_template_completeness(self, date_text: str | None = None) -> dict[str, Any]:
        reference_date = _parse_date(date_text) if date_text else date.today()
        config = self._load_config()
        excel_path = self._resolve_path(config.get("excel_path", "竞品监控.xlsx"))
        if excel_path.exists():
            try:
                excel = ExcelService(excel_path)
                workbook = excel.load_workbook()
                return self._template_completeness_to_dict(excel.check_weekly_price_completeness(workbook, reference_date))
            except Exception as exc:
                self.log("error", "模板完整性检查失败", str(exc))

        week = get_work_week(reference_date)
        days = []
        for offset in range(5):
            current = week.monday.toordinal() + offset
            current_date = date.fromordinal(current)
            days.append(
                {
                    "date": current_date.isoformat(),
                    "label": f"{current_date.month}.{current_date.day}",
                    "status": "missing_sheet",
                    "state": "missing_sheet",
                    "filled_count": 0,
                    "total_count": 0,
                    "missing_rows": [],
                }
            )
        return {
            "sheet_name": None,
            "period_start": week.monday.isoformat(),
            "period_end": week.friday.isoformat(),
            "complete": False,
            "energy_percent": 0,
            "missing_dates": [day["date"] for day in days],
            "days": days,
        }

    def run_task(self, payload: dict[str, Any]) -> dict[str, str]:
        with self.lock:
            if self._is_running_locked():
                return {"message": "已有任务正在运行"}
            self.stop_event.clear()
            now = _now_text()
            mode = payload.get("mode") or "daily_price"
            run_date = _parse_date(payload.get("run_date")) if payload.get("run_date") else date.today()
            week = get_work_week(run_date)
            self.status.update(
                {
                    "system_status": "running",
                    "progress_total": 0,
                    "progress_done": 0,
                    "success_count": 0,
                    "failed_count": 0,
                    "skipped_count": 0,
                    "current_step": "任务启动中",
                    "started_at": now,
                    "finished_at": None,
                    "duration": "-",
                    "last_error": None,
                    "target_sheet_name": build_sheet_name(week),
                    "target_period_range": f"{week.monday.isoformat()} 至 {week.friday.isoformat()}",
                    "active_mode": mode,
                }
            )
            context = RunContext(self, dict(payload), self.stop_event)
            self.current_thread = threading.Thread(target=self._run_in_thread, args=(context,), daemon=True)
            self.current_thread.start()
            self.log("info", "任务已启动", f"mode={mode} run_date={run_date.isoformat()}")
            return {"message": "任务已启动"}

    def stop_task(self) -> dict[str, str]:
        with self.lock:
            if not self._is_running_locked():
                return {"message": "当前没有正在运行的任务"}
            self.stop_event.set()
            self.status["current_step"] = "已请求停止，等待当前步骤结束"
            self.log("info", "已请求停止当前任务", "任务会在安全位置停止")
            return {"message": "已请求停止当前任务"}

    def wait_for_current_task(self, timeout: float | None = None) -> None:
        thread = self.current_thread
        if thread:
            thread.join(timeout=timeout)

    def backfill_template(self, payload: dict[str, Any]) -> dict[str, Any]:
        dates = payload.get("dates") or []
        self.log("info", "已提交缺失日期补跑", "、".join(dates))
        return {"message": "补跑任务已提交", "backfilled_dates": dates}

    def send_template(self) -> dict[str, str]:
        config = self._load_config()
        excel_path = self._resolve_path(config.get("excel_path", "竞品监控.xlsx"))
        summary = self._build_summary()
        try:
            result = self.notifier(config, excel_path, summary)
            with self.lock:
                self.status["last_notify_text_status"] = result.get("text_status") or "success"
                self.status["last_notify_file_status"] = result.get("file_status") or "success"
                self.status["last_notify_time"] = _now_text()
                self.status["last_notify_error"] = None
                self.status["last_sent_file_name"] = result.get("file_name") or excel_path.name
                self.status["last_sent_at"] = self.status["last_notify_time"]
            self.log("success", "企业微信已发送", f"发送文件：{excel_path.name}")
            return {"message": "当前模板已发送"}
        except WeComNotifyError as exc:
            with self.lock:
                self.status["last_notify_text_status"] = "failed"
                self.status["last_notify_file_status"] = "failed"
                self.status["last_notify_time"] = _now_text()
                self.status["last_notify_error"] = str(exc)
            self.log("error", "企业微信发送失败", str(exc))
            return {"message": "企业微信发送失败", "error": str(exc)}

    def get_config(self) -> dict[str, Any]:
        config = self._load_config()
        taobao_credentials = load_taobao_credentials(config)
        bi_credentials = load_bi_credentials(config)
        public = {
            "excel_path": config.get("excel_path", "竞品监控.xlsx"),
            "daily_run_time": config.get("daily_run_time", "10:00"),
            "bi_run_saturday": 5 in _weekdays(config.get("new_product_allowed_weekdays", [5, 6])),
            "bi_run_sunday": 6 in _weekdays(config.get("new_product_allowed_weekdays", [5, 6])),
            "auto_backfill_missing_daily_prices_before_weekly_new": bool(
                config.get("auto_backfill_missing_daily_prices_before_weekly_new", True)
            ),
            "wecom_enabled": bool(config.get("wecom_enabled", False)),
            "wecom_send_summary": bool(config.get("wecom_send_summary", True)),
            "wecom_send_excel_file": bool(config.get("wecom_send_excel_file", True)),
            "wecom_webhook_set": bool(config.get("wecom_webhook")),
            "taobao_status": self._login_status("taobao", config),
            "bi_status": self._login_status("bi", config),
            "taobao_login_status": self._browser_login_status("taobao"),
            "taobao_credential_status": "已保存凭据" if taobao_credentials else "未保存凭据",
            "taobao_username_masked": _mask_account(taobao_credentials.username if taobao_credentials else ""),
            "taobao_password_set": bool(taobao_credentials),
            "bi_login_status": self._browser_login_status("bi"),
            "bi_credential_status": "已保存凭据" if bi_credentials else "未保存凭据",
            "bi_username_masked": _mask_account(bi_credentials.username if bi_credentials else ""),
            "bi_password_set": bool(bi_credentials),
            "mode": config.get("mode", "daily_price"),
            "run_date": config.get("run_date", ""),
            "dry_run": bool(config.get("dry_run", False)),
            "test_one": bool(config.get("test_one", False)),
            "rows": config.get("rows", ""),
            "limit": config.get("limit", ""),
            "save_every": config.get("save_every", config.get("save_every_n_products", 5)),
            "updated_at": config.get("updated_at"),
        }
        return public

    def save_config(self, payload: dict[str, Any]) -> dict[str, str]:
        config = self._load_config()
        for key in [
            "excel_path",
            "daily_run_time",
            "auto_backfill_missing_daily_prices_before_weekly_new",
            "wecom_enabled",
            "wecom_send_summary",
            "wecom_send_excel_file",
            "mode",
            "run_date",
            "dry_run",
            "test_one",
            "rows",
            "limit",
            "save_every",
        ]:
            if key in payload:
                config[key] = payload[key]

        if "bi_run_saturday" in payload or "bi_run_sunday" in payload:
            weekdays = []
            if bool(payload.get("bi_run_saturday")):
                weekdays.append(5)
            if bool(payload.get("bi_run_sunday")):
                weekdays.append(6)
            config["new_product_allowed_weekdays"] = weekdays

        webhook = str(payload.get("wecom_webhook") or "").strip()
        if webhook and webhook != SECRET_PLACEHOLDER:
            config["wecom_webhook"] = webhook

        self._save_credentials_if_present(config, payload, "taobao")
        self._save_credentials_if_present(config, payload, "bi")
        config["updated_at"] = _now_text()
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(_dump_yaml(config), encoding="utf-8")
        self.log("success", "配置已保存", "Web 控制台配置已写入")
        return {"message": "配置已保存"}

    def get_logs(self, level: str = "all", query: str = "") -> list[dict[str, Any]]:
        with self.lock:
            items = list(self.logs)
        if level and level != "all":
            items = [item for item in items if item["level"] == level]
        if query:
            needle = query.lower()
            items = [
                item
                for item in items
                if needle in str(item.get("message", "")).lower() or needle in str(item.get("detail", "")).lower()
            ]
        return [self._sanitize(item) for item in items[:500]]

    def get_results(self, status: str = "all", mode: str = "all", query: str = "") -> list[dict[str, Any]]:
        with self.lock:
            items = list(self.results)
        if status and status != "all":
            items = [item for item in items if item.get("status") == status]
        if mode and mode != "all":
            items = [item for item in items if item.get("mode") == mode]
        if query:
            needle = query.lower()
            items = [
                item
                for item in items
                if needle in str(item.get("brand", "")).lower() or needle in str(item.get("model", "")).lower()
            ]
        return [self._sanitize(item) for item in items]

    def export_results_csv(self) -> str:
        output = io.StringIO()
        fieldnames = ["time", "mode", "sheet", "brand", "model", "status", "output", "error_reason"]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for item in reversed(self.results):
            writer.writerow({key: item.get(key, "") for key in fieldnames})
        return output.getvalue()

    def cleanup_maintenance(self, scope: str) -> dict[str, str]:
        if scope == "logs":
            with self.lock:
                self.logs.clear()
            return {"message": "当前视图日志已清空"}
        return {"message": "清理请求已记录"}

    def reset_session(self, target: str) -> dict[str, str]:
        if target not in {"taobao", "bi"}:
            return {"message": "未知登录状态类型"}
        with self.lock:
            self.session_status[target] = "需重新登录"
        self.log("warning", "登录状态已重置", f"{target} 下次运行会重新检查登录")
        return {"message": "登录状态已重置"}

    def set_progress_total(self, total: int) -> None:
        with self.lock:
            self.status["progress_total"] = int(total)

    def set_current_step(self, step: str) -> None:
        with self.lock:
            self.status["current_step"] = step

    def record_result(self, result: dict[str, Any]) -> None:
        with self.lock:
            item = dict(result)
            item.setdefault("id", f"result-{len(self.results) + 1}")
            item.setdefault("time", _now_text())
            item.setdefault("status", "success")
            item.setdefault("mode", self.status.get("active_mode") or "daily_price")
            self.results.insert(0, item)
            if self.status.get("system_status") == "running":
                self.status["progress_done"] = int(self.status.get("progress_done") or 0) + 1
                if item["status"] == "failed":
                    self.status["failed_count"] = int(self.status.get("failed_count") or 0) + 1
                elif item["status"] == "skipped":
                    self.status["skipped_count"] = int(self.status.get("skipped_count") or 0) + 1
                else:
                    self.status["success_count"] = int(self.status.get("success_count") or 0) + 1

    def record_task_summary(
        self,
        mode: str,
        title: str,
        output: str,
        status: str = "success",
        error_reason: str = "",
    ) -> None:
        with self.lock:
            current_total = int(self.status.get("progress_total") or 0)
            self.status["progress_total"] = current_total + 1
        self.record_result(
            {
                "mode": mode,
                "sheet": self.status.get("target_sheet_name"),
                "brand": "",
                "model": title,
                "status": status,
                "output": output,
                "error_reason": error_reason,
            }
        )

    def log(self, level: str, message: str, detail: str = "") -> None:
        with self.lock:
            self.logs.insert(
                0,
                {
                    "id": f"log-{len(self.logs) + 1}",
                    "time": _now_text(),
                    "level": level,
                    "message": message,
                    "detail": detail,
                },
            )

    def _run_in_thread(self, context: RunContext) -> None:
        try:
            self.runner(context)
            with self.lock:
                if self.stop_event.is_set():
                    self.status["system_status"] = "stopped"
                    self.status["current_step"] = "已停止"
                else:
                    self.status["system_status"] = "success"
                    self.status["current_step"] = "任务完成"
                self.status["finished_at"] = _now_text()
                self.status["duration"] = _duration_text(self.status.get("started_at"), self.status["finished_at"])
            if not self.stop_event.is_set():
                config = self._load_config()
                if bool(config.get("wecom_enabled", False)):
                    is_dry_run = bool(context.payload.get("dry_run", config.get("dry_run", False)))
                    if is_dry_run:
                        self.log("info", "Dry-run 已跳过企业微信自动发送", "测试运行不会发送摘要或 Excel 文件")
                    else:
                        self.send_template()
        except Exception as exc:
            with self.lock:
                self.status["system_status"] = "failed"
                self.status["current_step"] = "任务失败"
                self.status["last_error"] = str(exc)
                self.status["finished_at"] = _now_text()
                self.status["duration"] = _duration_text(self.status.get("started_at"), self.status["finished_at"])
            self.log("error", "任务失败", str(exc))

    def _default_runner(self, context: RunContext) -> None:
        import main as cli_main
        from excel_service import backup_excel
        from logger_service import setup_logger

        config = self._load_config()
        run_date = _parse_date(context.payload.get("run_date")) if context.payload.get("run_date") else date.today()
        mode = context.payload.get("mode") or "daily_price"
        excel_path = self._resolve_path(config.get("excel_path", "竞品监控.xlsx"))
        log_dir = self._resolve_path(config.get("log_dir", "competitor_monitor/logs"))
        backup_dir = self._resolve_path(config.get("backup_dir", "competitor_monitor/backup"))
        logger, log_path = setup_logger(log_dir)
        context.log("info", "日志文件已创建", self._display_path(log_path))
        context.set_step("正在备份 Excel")
        backup_excel(excel_path, backup_dir)
        excel = ExcelService(excel_path)
        workbook = excel.load_workbook()

        if mode in {"daily_price", "all"}:
            context.set_step("正在采集每日价格")
            cli_main.run_daily_price_job(
                config=config,
                logger=logger,
                excel=excel,
                workbook=workbook,
                run_date=run_date,
                dry_run=bool(context.payload.get("dry_run", False)),
                test_one=bool(context.payload.get("test_one", False)),
                limit=_optional_int(context.payload.get("limit")),
                row_filter=cli_main.parse_row_filter(context.payload.get("rows")),
                save_every=_optional_int(context.payload.get("save_every")),
                excel_path=excel_path,
                stop_event=context.stop_event,
                progress_callback=lambda event: self._record_collection_progress(mode, event),
            )
        if context.stop_requested():
            return
        if mode in {"weekly_new", "all"}:
            context.set_step("正在处理周末 BI 上新")
            weekly_stats = cli_main.run_weekly_new_products(
                config,
                logger,
                excel,
                workbook,
                run_date,
                bool(context.payload.get("dry_run", False)),
                excel_path,
            )
            self.record_task_summary(
                "weekly_new",
                "周末 BI 上新",
                (
                    f"写入 {weekly_stats.written}，重复 {weekly_stats.skipped_duplicates}，"
                    f"无上新 {weekly_stats.no_data_written}，失败 {weekly_stats.failed}"
                ),
                status="failed" if weekly_stats.failed else "success",
                error_reason="；".join(weekly_stats.failure_details),
            )
        if context.stop_requested():
            return
        if mode == "price_trend":
            context.set_step("正在更新价格情况")
            trend_stats = cli_main.run_price_trend_job(
                config,
                logger,
                excel,
                workbook,
                run_date,
                bool(context.payload.get("dry_run", False)),
                excel_path,
            )
            self.record_task_summary(
                "price_trend",
                "价格情况分析",
                (
                    f"共 {trend_stats.total} 行，写入 {trend_stats.written}，"
                    f"已存在 {trend_stats.skipped_existing}，不完整 {trend_stats.skipped_incomplete}，"
                    f"未分类 {trend_stats.skipped_unclassified}"
                ),
            )

    def _record_collection_progress(self, mode: str, event: dict[str, Any]) -> None:
        self.set_progress_total(int(event.get("total") or 0))
        self.set_current_step(f"正在处理第 {event.get('processed', 0)}/{event.get('total', 0)} 条：{event.get('model') or '-'}")
        warning = event.get("warning") or ""
        if warning:
            self.log("warning", "价格异常波动，需人工复核", str(warning))
        self.record_result(
            {
                "mode": mode,
                "sheet": event.get("sheet") or self.status.get("target_sheet_name"),
                "brand": event.get("brand") or "",
                "model": event.get("model") or "",
                "status": event.get("status") or "success",
                "output": event.get("price") or "",
                "error_reason": event.get("error") or warning,
                "row": event.get("row"),
                "url": event.get("url"),
            }
        )

    def _initial_status(self) -> dict[str, Any]:
        return {
            "system_status": "idle",
            "progress_total": 0,
            "progress_done": 0,
            "success_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
            "current_step": "待命",
            "started_at": None,
            "finished_at": None,
            "duration": "-",
            "last_error": None,
            "target_sheet_name": "-",
            "target_period_range": "-",
            "last_saved_at": None,
            "last_sent_at": None,
            "notify_enabled": False,
            "last_notify_text_status": "not_sent",
            "last_notify_file_status": "not_sent",
            "last_notify_time": None,
            "last_notify_error": None,
            "last_sent_file_name": None,
            "active_mode": None,
        }

    def _load_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {}
        return load_config(self.config_path)

    def _is_running_locked(self) -> bool:
        return self.status.get("system_status") in {"running", "backfilling", "saving", "sending"}

    def _task_cards(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "id": "daily_price",
                "title": "每日价格采集",
                "status": self.status["system_status"] if self.status.get("active_mode") == "daily_price" else "idle",
                "status_text": self.status_text(self.status["system_status"] if self.status.get("active_mode") == "daily_price" else "idle"),
                "last_run": self.status.get("finished_at") or "-",
                "last_result": self.status.get("current_step") or "-",
                "template_status": self.status.get("target_sheet_name") or "-",
                "notify_status": self.status.get("last_notify_file_status") or "not_sent",
            },
            {
                "id": "weekly_new",
                "title": "周末 BI 上新采集",
                "status": self.status["system_status"] if self.status.get("active_mode") == "weekly_new" else "idle",
                "status_text": self.status_text(self.status["system_status"] if self.status.get("active_mode") == "weekly_new" else "idle"),
                "last_run": self.status.get("finished_at") or "-",
                "last_result": self.status.get("current_step") or "-",
                "template_status": self.status.get("target_sheet_name") or "-",
                "notify_status": self.status.get("last_notify_file_status") or "not_sent",
                "precheck": "价格完整性待检查",
            },
        ]

    def _workflow(self, status: str) -> list[dict[str, str]]:
        active = status == "running"
        return [
            {"key": "detect_date", "state": "done" if active else "pending"},
            {"key": "locate_sheet", "state": "active" if active else "pending"},
            {"key": "write_template", "state": "pending"},
            {"key": "backfill", "state": "pending"},
            {"key": "save", "state": "pending"},
            {"key": "notify", "state": "pending"},
        ]

    def _primary_action(self, status: str) -> str:
        if status == "running":
            return "none"
        if status == "success":
            return "send_template"
        return "run_daily"

    def _maintenance_counts(self, config: dict[str, Any]) -> dict[str, int]:
        return {
            "logs": len(list(self._resolve_path(config.get("log_dir", "competitor_monitor/logs")).glob("*.log"))),
            "backups": len(list(self._resolve_path(config.get("backup_dir", "competitor_monitor/backup")).glob("*.xlsx"))),
            "exports": 0,
            "sessions": 2,
        }

    def _template_completeness_to_dict(self, completeness: TemplateCompleteness) -> dict[str, Any]:
        days = []
        for day in completeness.days:
            days.append(
                {
                    "date": day.date.isoformat(),
                    "label": f"{day.date.month}.{day.date.day}",
                    "status": day.status,
                    "state": day.status,
                    "filled_count": day.filled_count,
                    "total_count": day.total_count,
                    "missing_rows": list(day.missing_rows),
                }
            )
        missing_dates = [day["date"] for day in days if day["status"] != "complete"]
        total = sum(day["total_count"] for day in days)
        filled = sum(day["filled_count"] for day in days)
        return {
            "sheet_name": completeness.sheet_name,
            "period_start": completeness.week_start.isoformat(),
            "period_end": completeness.week_end.isoformat(),
            "complete": completeness.is_complete,
            "energy_percent": round((filled / total) * 100) if total else 0,
            "missing_dates": missing_dates,
            "days": days,
        }

    def _save_credentials_if_present(self, config: dict[str, Any], payload: dict[str, Any], target: str) -> None:
        username = str(payload.get(f"{target}_username") or "").strip()
        password = str(payload.get(f"{target}_password") or "")
        if not username or not password or password == SECRET_PLACEHOLDER:
            return
        key = f"{target}_credentials_path"
        default = f"competitor_monitor/secrets/{target}_credentials.json"
        credentials_path = self._resolve_path(config.get(key, default))
        save_account_credentials(credentials_path, username, password)
        config[key] = self._display_path(credentials_path)

    def _login_status(self, target: str, config: dict[str, Any]) -> str:
        if self.session_status.get(target):
            return str(self.session_status[target])
        credentials = load_taobao_credentials(config) if target == "taobao" else load_bi_credentials(config)
        return "已保存凭据" if credentials else "未配置"

    def _browser_login_status(self, target: str) -> str:
        if self.session_status.get(target):
            return str(self.session_status[target])
        return "运行时检测"

    def _build_summary(self) -> str:
        lines = [
            "竞品监控任务完成\n"
            f"状态：{self.status_text(self.status.get('system_status'))}\n"
            f"成功：{self.status.get('success_count', 0)}，失败：{self.status.get('failed_count', 0)}，跳过：{self.status.get('skipped_count', 0)}"
        ]
        warnings = [
            item
            for item in self.logs
            if item.get("level") == "warning" and "价格异常波动" in str(item.get("message", ""))
        ][:5]
        if warnings:
            lines.append("\n需人工复核的价格异常：")
            for item in warnings:
                lines.append(f"- {item.get('detail') or item.get('message')}")
        return "\n".join(lines)

    def _resolve_path(self, value: Any) -> Path:
        path = Path(str(value))
        return path if path.is_absolute() else self.base_dir / path

    def _display_path(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.base_dir).as_posix()
        except ValueError:
            return str(path)

    def _sanitize(self, value):
        if isinstance(value, dict):
            return {
                key: (SECRET_PLACEHOLDER if _is_secret_key(key) else self._sanitize(item))
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._sanitize(item) for item in value]
        return value

    @staticmethod
    def status_text(status: Any) -> str:
        return {
            "idle": "待命",
            "running": "运行中",
            "success": "成功",
            "failed": "失败",
            "stopped": "已停止",
        }.get(str(status), str(status or "-"))


def _dump_yaml(value: dict[str, Any], indent: int = 0) -> str:
    lines: list[str] = []
    prefix = " " * indent
    for key, item in value.items():
        if isinstance(item, dict):
            lines.append(f"{prefix}{key}:")
            lines.append(_dump_yaml(item, indent + 2).rstrip("\n"))
        elif isinstance(item, list):
            lines.append(f"{prefix}{key}:")
            for child in item:
                lines.append(f"{prefix}  - {_format_scalar(child)}")
        else:
            lines.append(f"{prefix}{key}: {_format_scalar(item)}")
    return "\n".join(lines) + "\n"


def _format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if value is None:
        return '""'
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _parse_date(value: Any) -> date:
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _weekdays(value: Any) -> set[int]:
    try:
        return {int(item) for item in value}
    except TypeError:
        return set()


def _mask_account(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.isdigit() and len(text) >= 7:
        return f"{text[:3]}****{text[-4:]}"
    return "已保存账号"


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _duration_text(started_at: str | None, finished_at: str | None) -> str:
    if not started_at or not finished_at:
        return "-"
    try:
        seconds = int((datetime.strptime(finished_at, "%Y-%m-%d %H:%M:%S") - datetime.strptime(started_at, "%Y-%m-%d %H:%M:%S")).total_seconds())
    except ValueError:
        return "-"
    return time.strftime("%H:%M:%S", time.gmtime(max(0, seconds)))


def _is_secret_key(key: str) -> bool:
    lower = key.lower()
    return any(token in lower for token in ("secret", "password", "token", "cookie", "webhook"))
