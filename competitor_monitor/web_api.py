from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import subprocess
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from config_service import load_config
from credential_service import load_bi_credentials, load_taobao_credentials, save_account_credentials
from date_service import build_sheet_name, get_work_week, parse_sheet_range
from excel_service import ExcelService, TemplateCompleteness, WorkbookLockedError, backup_excel
from notification_formatter import format_wecom_summary
from state_file_service import atomic_write_json
from wecom_service import WeComNotifyError, send_wecom_template
from workbook_state_service import SYNCED, WorkbookStateService


SECRET_PLACEHOLDER = "******"
RUNTIME_PATH_KEYS = (
    "excel_path",
    "backup_dir",
    "log_dir",
    "browser_user_data_dir",
    "browser_storage_state_path",
    "taobao_credentials_path",
    "bi_browser_user_data_dir",
    "bi_credentials_path",
)
Runner = Callable[["RunContext"], None]
Notifier = Callable[[dict[str, Any], Path, str], dict[str, str | None]]
SchedulerSyncer = Callable[[dict[str, Any]], None]
TodayProvider = Callable[[], date]


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


class SharedStopEvent:
    """A threading.Event-compatible stop signal shared through web_state."""

    def __init__(self, service: "WebApiService") -> None:
        self.service = service
        self._local = threading.Event()

    def is_set(self) -> bool:
        return self._local.is_set() or self.service._shared_stop_requested()

    def set(self) -> None:
        self._local.set()
        self.service._persist_stop_request(True)

    def clear(self) -> None:
        self._local.clear()
        self.service._persist_stop_request(False)


class WebApiService:
    def __init__(
        self,
        base_dir: Path | str | None = None,
        config_path: Path | str | None = None,
        runner: Runner | None = None,
        notifier: Notifier | None = None,
        scheduler_syncer: SchedulerSyncer | None = None,
        today_provider: TodayProvider | None = None,
    ) -> None:
        self.base_dir = Path(base_dir or Path.cwd()).resolve()
        self.config_path = Path(config_path) if config_path else self.base_dir / "competitor_monitor" / "config.yaml"
        if not self.config_path.is_absolute():
            self.config_path = self.base_dir / self.config_path
        self.runner = runner or self._default_runner
        self.notifier = notifier or send_wecom_template
        self.scheduler_syncer = scheduler_syncer or self._sync_windows_scheduled_tasks
        self.today_provider = today_provider or date.today
        self.web_state_dir = self.base_dir / "competitor_monitor" / "web_state"
        self.results_path = self.web_state_dir / "results.jsonl"
        self.status_path = self.web_state_dir / "status.json"
        self.stop_request_path = self.web_state_dir / "stop_request.json"
        self.workbook_state = WorkbookStateService(self.base_dir, self.web_state_dir)
        self.lock = threading.RLock()
        self.scheduler_lock = threading.Lock()
        self.stop_event = SharedStopEvent(self)
        self.current_thread: threading.Thread | None = None
        self.schedule_thread: threading.Thread | None = None
        self.log_view_cleared_at: datetime | None = None
        self.logs: list[dict[str, Any]] = []
        self.results: list[dict[str, Any]] = self._load_persisted_results()
        self.session_status = {"taobao": None, "bi": None}
        self.status: dict[str, Any] = self._initial_status()

    def get_tasks_status(self) -> dict[str, Any]:
        with self.lock:
            config = self._load_config()
            self._refresh_status_from_shared_state_locked()
            status = dict(self.status)
            if status.get("system_status") not in {"running", "backfilling", "saving", "sending"}:
                week = get_work_week(self.today_provider())
                status["target_sheet_name"] = build_sheet_name(week)
                status["target_period_range"] = f"{week.monday.isoformat()} 至 {week.friday.isoformat()}"
            primary_path = self._primary_workbook_path(config)
            active_path = self.workbook_state.get_active_workbook_path(primary_path)
            workbook_payload = self._workbook_status_payload(config)
            status.update(
                {
                    "template_name": active_path.name,
                    "template_path": self._display_path(active_path),
                    "maintenance": self._maintenance_counts(config),
                    "tasks": self._task_cards(config, status),
                    "workflow": self._workflow(status["system_status"]),
                    "ui": {"primary_action": self._primary_action(status["system_status"])},
                    "notify_enabled": bool(config.get("wecom_enabled", False)),
                }
            )
            status.update(workbook_payload)
            return self._sanitize(status)

    def get_template_completeness(self, date_text: str | None = None) -> dict[str, Any]:
        reference_date = _parse_date(date_text) if date_text else date.today()
        config = self._load_config()
        excel_path = self._active_workbook_path(config)
        if excel_path.exists():
            workbook = None
            try:
                excel = ExcelService(excel_path)
                workbook = excel.load_workbook()
                return self._template_completeness_to_dict(excel.check_weekly_price_completeness(workbook, reference_date))
            except Exception as exc:
                self.log("error", "模板完整性检查失败", str(exc))
            finally:
                self._close_workbook(workbook)

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
            "filled_count": 0,
            "total_count": 0,
            "energy_percent": 0,
            "missing_dates": [day["date"] for day in days],
            "days": days,
        }

    def run_task(self, payload: dict[str, Any]) -> dict[str, str]:
        with self.lock:
            self._refresh_status_from_shared_state_locked()
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
                    "run_date": run_date.isoformat(),
                    "active_mode": mode,
                    "stop_requested": False,
                    "stop_requested_at": None,
                    "runner_pid": os.getpid(),
                }
            )
            self._persist_status_locked()
            context = RunContext(self, dict(payload), self.stop_event)
            self.current_thread = threading.Thread(target=self._run_in_thread, args=(context,), daemon=True)
            self.current_thread.start()
            self.log("info", "任务已启动", f"mode={mode} run_date={run_date.isoformat()}")
            return {"message": "任务已启动"}

    def stop_task(self) -> dict[str, str]:
        with self.lock:
            self._refresh_status_from_shared_state_locked()
            if not self._is_running_locked():
                return {"message": "当前没有正在运行的任务"}
            self.stop_event.set()
            self.status["stop_requested"] = True
            self.status["stop_requested_at"] = _now_text()
            self.status["current_step"] = "已请求停止，等待当前步骤结束"
            self._persist_status_locked()
            self.log("info", "已请求停止当前任务", "任务会在安全位置停止")
            return {"message": "已请求停止当前任务"}

    def wait_for_current_task(self, timeout: float | None = None) -> None:
        thread = self.current_thread
        if thread:
            thread.join(timeout=timeout)

    def get_template_file(self) -> Path:
        config = self._load_config()
        excel_path = self._active_workbook_path(config)
        if not excel_path.exists() or not excel_path.is_file():
            raise FileNotFoundError(f"当前主 Excel 文件不存在：{self._display_path(excel_path)}")
        return excel_path

    def upload_template(self, filename: str, content: bytes) -> dict[str, Any]:
        if not filename.lower().endswith(".xlsx"):
            return {"message": "模板上传失败", "error": "只支持 .xlsx 模板文件"}
        if not content:
            return {"message": "模板上传失败", "error": "上传文件为空"}

        config = self._load_config()
        excel_path = self._resolve_path(config.get("excel_path", "竞品监控.xlsx"))
        sync_status = self.workbook_state.status_payload(excel_path)["workbook_sync_status"]
        if sync_status != SYNCED:
            return {"message": "主模板待同步，暂不能上传新模板", "error": "请先同步主模板，避免覆盖未同步的最新结果"}
        backup_dir = self._resolve_path(config.get("backup_dir", "competitor_monitor/backup"))
        excel_path.parent.mkdir(parents=True, exist_ok=True)
        self.web_state_dir.mkdir(parents=True, exist_ok=True)

        temp_file = NamedTemporaryFile(delete=False, suffix=".xlsx", dir=self.web_state_dir)
        temp_path = Path(temp_file.name)
        try:
            temp_file.write(content)
            temp_file.close()
            validation = self._validate_template_file(temp_path)
            backup_path = backup_excel(excel_path, backup_dir) if excel_path.exists() else None
            shutil.copy2(temp_path, excel_path)
            now = _now_text()
            with self.lock:
                self.status["template_uploaded_at"] = now
                self.status["template_validation_status"] = "模板可用"
                self.status["target_sheet_name"] = validation.get("sheet_name") or self.status.get("target_sheet_name")
                self._persist_status_locked()
            self.workbook_state.mark_synced(excel_path)
            self.log(
                "success",
                "模板已上传并替换当前主 Excel",
                f"文件={filename}；目标={self._display_path(excel_path)}；备份={self._display_path(backup_path) if backup_path else '-'}",
            )
            return {
                "message": "模板已上传并替换当前主 Excel",
                "file_name": excel_path.name,
                "template_path": self._display_path(excel_path),
                "backup_path": self._display_path(backup_path) if backup_path else None,
                "validation": validation,
            }
        except Exception as exc:
            with self.lock:
                self.status["template_validation_status"] = f"模板不可用：{exc}"
                self._persist_status_locked()
            self.log("error", "模板上传失败", str(exc))
            return {"message": "模板上传失败", "error": str(exc)}
        finally:
            if not temp_file.closed:
                temp_file.close()
            if temp_path.exists():
                temp_path.unlink()

    def backfill_template(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            self._refresh_status_from_shared_state_locked()
            if self._is_running_locked():
                return {"message": "已有任务正在运行"}
            dates = [str(item) for item in (payload.get("dates") or []) if str(item).strip()]
            if not dates:
                completeness = self.get_template_completeness(payload.get("date"))
                dates = list(completeness.get("missing_dates") or [])
            if not dates:
                return {"message": "没有需要补跑的日期", "backfilled_dates": []}
            self.stop_event.clear()
            first_date = _parse_date(dates[0])
            week = get_work_week(first_date)
            self.status.update(
                {
                    "system_status": "running",
                    "progress_total": len(dates),
                    "progress_done": 0,
                    "success_count": 0,
                    "failed_count": 0,
                    "skipped_count": 0,
                    "current_step": "补跑缺失日期",
                    "started_at": _now_text(),
                    "finished_at": None,
                    "duration": "-",
                    "last_error": None,
                    "target_sheet_name": build_sheet_name(week),
                    "target_period_range": f"{week.monday.isoformat()} 至 {week.friday.isoformat()}",
                    "active_mode": "daily_price",
                    "stop_requested": False,
                    "stop_requested_at": None,
                    "runner_pid": os.getpid(),
                }
            )
            self._persist_status_locked()
            self.current_thread = threading.Thread(target=self._run_backfill_in_thread, args=(dates,), daemon=True)
            self.current_thread.start()
            self.log("info", "补跑任务已启动", "、".join(dates))
            return {"message": "补跑任务已启动", "backfilled_dates": dates}

    def send_template(self) -> dict[str, str]:
        config = self._load_config()
        excel_path = self._active_workbook_path(config)
        summary = self._build_summary()
        try:
            result = self.notifier(config, excel_path, summary)
            text_status = result.get("text_status") or "success"
            file_status = result.get("file_status") or "success"
            if text_status == "not_sent" and file_status == "not_sent":
                with self.lock:
                    self.status["last_notify_text_status"] = "not_sent"
                    self.status["last_notify_file_status"] = "not_sent"
                    self.status["last_notify_error"] = None
                    self.status["last_sent_file_name"] = None
                    self._persist_status_locked()
                self.log("info", "企业微信未发送", "企业微信未启用或发送项未开启")
                return {"message": "企业微信未启用，未发送"}
            with self.lock:
                self.status["last_notify_text_status"] = text_status
                self.status["last_notify_file_status"] = file_status
                self.status["last_notify_time"] = _now_text()
                self.status["last_notify_error"] = None
                self.status["last_sent_file_name"] = result.get("file_name") or excel_path.name
                self.status["last_sent_at"] = self.status["last_notify_time"]
                self._persist_status_locked()
            self.log("success", "企业微信已发送", f"发送文件：{excel_path.name}")
            return {"message": "当前模板已发送"}
        except WeComNotifyError as exc:
            with self.lock:
                self.status["last_notify_text_status"] = "failed"
                self.status["last_notify_file_status"] = "failed"
                self.status["last_notify_time"] = _now_text()
                self.status["last_notify_error"] = str(exc)
                self._persist_status_locked()
            self.log("error", "企业微信发送失败", str(exc))
            return {"message": "企业微信发送失败", "error": str(exc)}

    def sync_latest_template(self) -> dict[str, Any]:
        config = self._load_config()
        primary_path = self._primary_workbook_path(config)
        result = self.workbook_state.try_sync_latest_to_primary(primary_path)
        if result.get("sync_status") == SYNCED:
            self.log("success", "主模板已同步", self._display_path(primary_path))
        else:
            self.log("warning", "主模板同步失败", str(result.get("error") or ""))
        return result

    def get_config(self) -> dict[str, Any]:
        with self.lock:
            self._refresh_status_from_shared_state_locked()
            status = dict(self.status)
        config = self._load_config()
        taobao_credentials = load_taobao_credentials(config)
        bi_credentials = load_bi_credentials(config)
        primary_path = self._primary_workbook_path(config)
        active_path = self.workbook_state.get_active_workbook_path(primary_path)
        public = {
            "excel_path": config.get("excel_path", "竞品监控.xlsx"),
            "template_name": active_path.name,
            "template_path": self._display_path(active_path),
            "template_uploaded_at": status.get("template_uploaded_at"),
            "template_validation_status": status.get("template_validation_status") or "待验证",
            "daily_run_time": config.get("daily_run_time", "10:00"),
            "weekly_new_time": config.get("weekly_new_time", "09:30"),
            "price_trend_time": config.get("price_trend_time", "18:30"),
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
        public.update(self._workbook_status_payload(config))
        return public

    def save_config(self, payload: dict[str, Any]) -> dict[str, str]:
        config = self._load_config()
        for key in [
            "excel_path",
            "daily_run_time",
            "weekly_new_time",
            "price_trend_time",
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
        if _has_schedule_change(payload):
            self._sync_scheduler_async(config)
        self.log("success", "配置已保存", "Web 控制台配置已写入")
        return {"message": "配置已保存"}

    def wait_for_schedule_sync(self, timeout: float | None = None) -> bool:
        thread = self.schedule_thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def get_logs(self, level: str = "all", query: str = "") -> list[dict[str, Any]]:
        with self.lock:
            items = list(self.logs)
            cleared_at = self.log_view_cleared_at
        items.extend(self._recent_log_file_items(self._load_config()))
        if cleared_at:
            items = [
                item
                for item in items
                if (parsed_time := _parse_log_time(item.get("time"))) is not None and parsed_time > cleared_at
            ]
        if level and level != "all":
            items = [item for item in items if item["level"] == level]
        if query:
            needle = query.lower()
            items = [
                item
                for item in items
                if needle in str(item.get("message", "")).lower() or needle in str(item.get("detail", "")).lower()
            ]
        items.sort(key=lambda item: str(item.get("time") or ""), reverse=True)
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
        fieldnames = ["时间", "任务", "Sheet", "Excel行", "品牌", "型号", "状态", "价格/结果", "失败原因", "人工复核提示"]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for item in reversed(self.results):
            error_reason = str(item.get("error_reason") or "")
            writer.writerow(
                {
                    "时间": item.get("time", ""),
                    "任务": item.get("mode", ""),
                    "Sheet": item.get("sheet", ""),
                    "Excel行": item.get("row", ""),
                    "品牌": item.get("brand", ""),
                    "型号": item.get("model", ""),
                    "状态": _result_status_text(item.get("status")),
                    "价格/结果": item.get("output", ""),
                    "失败原因": error_reason,
                    "人工复核提示": error_reason if _needs_manual_review(error_reason) else "",
                }
            )
        return output.getvalue()

    def cleanup_maintenance(self, scope: str) -> dict[str, str]:
        if scope == "results":
            with self.lock:
                self.results.clear()
                if self.results_path.exists():
                    self.results_path.unlink()
            return {"message": "结果记录已清空，Excel、日志和备份文件未删除"}
        if scope == "logs":
            with self.lock:
                self.log_view_cleared_at = datetime.now()
                self.logs.clear()
            return {"message": "当前视图日志已清空，磁盘 logs/ 文件未删除"}
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
            self._persist_status_locked()

    def set_current_step(self, step: str) -> None:
        with self.lock:
            self.status["current_step"] = step
            self._persist_status_locked()

    def record_result(self, result: dict[str, Any]) -> None:
        with self.lock:
            item = dict(result)
            item.setdefault("id", f"result-{len(self.results) + 1}")
            item.setdefault("time", _now_text())
            item.setdefault("status", "success")
            item.setdefault("mode", self.status.get("active_mode") or "daily_price")
            item = self._sanitize_result_for_storage(item)
            self.results.insert(0, item)
            self._append_result(item)
            if self.status.get("system_status") == "running":
                self.status["progress_done"] = int(self.status.get("progress_done") or 0) + 1
                if item["status"] == "failed":
                    self.status["failed_count"] = int(self.status.get("failed_count") or 0) + 1
                elif item["status"] == "skipped":
                    self.status["skipped_count"] = int(self.status.get("skipped_count") or 0) + 1
                else:
                    self.status["success_count"] = int(self.status.get("success_count") or 0) + 1
            self._persist_status_locked()

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
            self._persist_status_locked()
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
                self._persist_status_locked()
            if not self.stop_event.is_set():
                config = self._load_config()
                if bool(config.get("wecom_enabled", False)):
                    is_dry_run = bool(context.payload.get("dry_run", config.get("dry_run", False)))
                    if is_dry_run:
                        self.log("info", "Dry-run 已跳过企业微信自动发送", "测试运行不会发送摘要或 Excel 文件")
                    else:
                        self.send_template()
            self.stop_event.clear()
        except Exception as exc:
            with self.lock:
                self.status["system_status"] = "failed"
                self.status["current_step"] = "任务失败"
                self.status["last_error"] = str(exc)
                self.status["finished_at"] = _now_text()
                self.status["duration"] = _duration_text(self.status.get("started_at"), self.status["finished_at"])
                self._persist_status_locked()
            self.log("error", "任务失败", str(exc))
            self._persist_task_failure("任务失败", exc)
            self.stop_event.clear()

    def _run_backfill_in_thread(self, dates: list[str]) -> None:
        try:
            for date_text in dates:
                if self.stop_event.is_set():
                    break
                self.set_current_step(f"正在补跑 {date_text}")
                context = RunContext(
                    self,
                    {
                        "mode": "daily_price",
                        "run_date": date_text,
                        "dry_run": False,
                    },
                    self.stop_event,
                )
                self.runner(context)
            with self.lock:
                if self.stop_event.is_set():
                    self.status["system_status"] = "stopped"
                    self.status["current_step"] = "已停止"
                else:
                    self.status["system_status"] = "success"
                    self.status["current_step"] = "补跑完成"
                self.status["finished_at"] = _now_text()
                self.status["duration"] = _duration_text(self.status.get("started_at"), self.status["finished_at"])
                self._persist_status_locked()
            self.stop_event.clear()
        except Exception as exc:
            with self.lock:
                self.status["system_status"] = "failed"
                self.status["current_step"] = "补跑失败"
                self.status["last_error"] = str(exc)
                self.status["finished_at"] = _now_text()
                self.status["duration"] = _duration_text(self.status.get("started_at"), self.status["finished_at"])
                self._persist_status_locked()
            self.log("error", "补跑失败", str(exc))
            self._persist_task_failure("补跑失败", exc)
            self.stop_event.clear()

    def _default_runner(self, context: RunContext) -> None:
        import main as cli_main
        from logger_service import setup_logger

        config = self._runtime_config(self._load_config())
        run_date = _parse_date(context.payload.get("run_date")) if context.payload.get("run_date") else date.today()
        mode = context.payload.get("mode") or "daily_price"
        primary_excel_path = self._resolve_path(config.get("excel_path", "竞品监控.xlsx"))
        self.workbook_state.try_sync_latest_to_primary(primary_excel_path)
        excel_path = self.workbook_state.prepare_active_for_run(primary_excel_path)
        log_dir = self._resolve_path(config.get("log_dir", "competitor_monitor/logs"))
        backup_dir = self._resolve_path(config.get("backup_dir", "competitor_monitor/backup"))
        logger = None
        workbook = None
        context.set_step("正在检查 Excel 文件")
        startup_lock_check_seconds = max(0.0, float(config.get("startup_excel_writable_check_seconds", 3)))
        if startup_lock_check_seconds:
            try:
                ExcelService.wait_workbook_writable(
                    excel_path,
                    timeout_seconds=startup_lock_check_seconds,
                    delay_seconds=1,
                    on_wait=lambda _attempt, _remaining: context.set_step("正在短暂检查 Excel 文件占用"),
                )
            except WorkbookLockedError as exc:
                context.log(
                    "warning",
                    "启动前检测到 Excel 可能被占用",
                    f"{exc}；已继续尝试，保存时会使用最新工作簿接管机制。",
                )
        logger, log_path = setup_logger(log_dir)
        context.log("info", "日志文件已创建", self._display_path(log_path))
        try:
            context.set_step("正在备份 Excel")
            if context.stop_requested():
                return
            backup_excel(excel_path, backup_dir)
            excel = ExcelService(excel_path, save_fallback=self._save_fallback_handler(primary_excel_path))
            workbook = excel.load_workbook()
        except Exception:
            self._close_workbook(workbook)
            self._close_logger(logger)
            raise
        try:
            if context.stop_requested():
                return
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
            if not bool(context.payload.get("dry_run", False)):
                with self.lock:
                    self.status["last_saved_at"] = _now_text()
                    self._persist_status_locked()
                sync_result = self.workbook_state.try_sync_latest_to_primary(primary_excel_path)
                if sync_result.get("sync_status") != SYNCED:
                    context.log("warning", "主模板待同步", str(sync_result.get("error") or "请稍后在 Web 控制台点击同步主模板"))
                self.workbook_state.cleanup_runs(primary_excel_path)
        finally:
            self._close_workbook(workbook)
            self._close_logger(logger)

    def _persist_task_failure(self, title: str, exc: Exception) -> None:
        try:
            config = self._load_config()
            log_dir = self._resolve_path(config.get("log_dir", "competitor_monitor/logs"))
            log_dir.mkdir(parents=True, exist_ok=True)
            failure_path = log_dir / "web_task_failures.log"
            text = (
                f"{_now_text()} [{title}] {exc}\n"
                f"{''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))}\n"
            )
            with failure_path.open("a", encoding="utf-8") as handle:
                handle.write(text)
        except Exception:
            pass

    def _persist_status_locked(self) -> None:
        try:
            self.status["state_updated_at"] = _now_text()
            atomic_write_json(self.status_path, self.status)
        except Exception:
            pass

    def _persist_stop_request(self, requested: bool) -> None:
        try:
            payload = {
                "stop_requested": bool(requested),
                "requested_at": _now_text() if requested else None,
            }
            atomic_write_json(self.stop_request_path, payload)
        except Exception:
            pass

    def _shared_stop_requested(self) -> bool:
        try:
            if not self.stop_request_path.exists():
                return False
            payload = json.loads(self.stop_request_path.read_text(encoding="utf-8"))
            return bool(isinstance(payload, dict) and payload.get("stop_requested"))
        except Exception:
            return False

    def _refresh_status_from_shared_state_locked(self) -> None:
        try:
            if not self.status_path.exists():
                return
            shared = json.loads(self.status_path.read_text(encoding="utf-8"))
            if not isinstance(shared, dict):
                return
            local_updated = _parse_log_time(self.status.get("state_updated_at"))
            shared_updated = _parse_log_time(shared.get("state_updated_at"))
            if shared_updated and (not local_updated or shared_updated >= local_updated):
                self.status.update(shared)
                self._clear_stale_running_status_locked()
        except Exception:
            return

    def _clear_stale_running_status_locked(self) -> None:
        if not self._is_running_locked():
            return
        runner_pid = _coerce_pid(self.status.get("runner_pid"))
        if runner_pid and _process_exists(runner_pid):
            return
        if not runner_pid and not self._active_status_is_stale_without_pid():
            return
        self.status["system_status"] = "stopped"
        self.status["current_step"] = "上次任务已中断，可重新启动"
        self.status["finished_at"] = _now_text()
        self.status["duration"] = _duration_text(self.status.get("started_at"), self.status["finished_at"])
        self.status["stop_requested"] = False
        self.status["stop_requested_at"] = None
        self.status["runner_pid"] = None
        self.current_thread = None
        self.stop_event.clear()
        self._persist_status_locked()
        self.log("warning", "检测到上次任务已中断", "已清理残留停止状态，可以重新启动任务")

    def _active_status_is_stale_without_pid(self) -> bool:
        updated_at = _parse_log_time(self.status.get("state_updated_at"))
        if not updated_at:
            return False
        return (datetime.now() - updated_at).total_seconds() > 30 * 60

    def _record_collection_progress(self, mode: str, event: dict[str, Any]) -> None:
        if event.get("event") == "phase":
            with self.lock:
                if "total" in event:
                    self.status["progress_total"] = int(event.get("total") or 0)
                step = str(event.get("step") or "").strip()
                if step:
                    self.status["current_step"] = step
                self._persist_status_locked()
            return
        self.set_progress_total(int(event.get("total") or 0))
        if self.stop_event.is_set():
            self.set_current_step(
                f"已请求停止，正在等待当前商品结束：第 {event.get('processed', 0)}/{event.get('total', 0)} 条"
            )
        else:
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
            "run_date": None,
            "last_saved_at": None,
            "last_sent_at": None,
            "notify_enabled": False,
            "last_notify_text_status": "not_sent",
            "last_notify_file_status": "not_sent",
            "last_notify_time": None,
            "last_notify_error": None,
            "last_sent_file_name": None,
            "active_mode": None,
            "stop_requested": False,
            "stop_requested_at": None,
            "runner_pid": None,
            "template_uploaded_at": None,
            "template_validation_status": "待验证",
        }

    def _load_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {}
        return load_config(self.config_path)

    def _sync_windows_scheduled_tasks(self, config: dict[str, Any]) -> None:
        runner_path = self._task_runner_path()
        if not runner_path.exists():
            raise FileNotFoundError(f"Task runner exe not found: {runner_path}")

        daily_time = _schedule_time(config.get("daily_run_time"), "10:00")
        weekly_time = _schedule_time(config.get("weekly_new_time"), "09:30")
        trend_time = _schedule_time(config.get("price_trend_time"), "18:30")
        weekly_days = _schedule_day_names(_weekdays(config.get("new_product_allowed_weekdays", [5, 6])))
        runner_dir = runner_path.parent
        config_path = self.config_path.resolve()

        script = f"""
$ErrorActionPreference = "Stop"
function Register-CompetitorRunnerTask {{
    param(
        [string]$TaskName,
        [string]$Description,
        [string]$Mode,
        [string[]]$Days,
        [string]$AtTime
    )
    $runnerExe = { _ps_quote(str(runner_path)) }
    $runnerDir = { _ps_quote(str(runner_dir)) }
    $configPath = { _ps_quote(str(config_path)) }
    $runnerCommand = @"
`$ErrorActionPreference = "Stop"
`$runnerArgs = @("--mode", "$Mode", "--config", "$configPath")
`$process = Start-Process -FilePath "$runnerExe" -ArgumentList `$runnerArgs -WorkingDirectory "$runnerDir" -WindowStyle Hidden -Wait -PassThru
exit `$process.ExitCode
"@
    $encodedCommand = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($runnerCommand))
    $actionArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -EncodedCommand $encodedCommand"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $actionArgs -WorkingDirectory $runnerDir
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Days -At $AtTime
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 8)
    Register-ScheduledTask -TaskName $TaskName -Description $Description -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
}}
Register-CompetitorRunnerTask -TaskName "CompetitorMonitor-DailyPrice" -Description "Run daily mature-product price collection and backend WeCom notification" -Mode "daily_price" -Days @("Monday","Tuesday","Wednesday","Thursday","Friday") -AtTime { _ps_quote(daily_time) }
Register-CompetitorRunnerTask -TaskName "CompetitorMonitor-PriceTrend" -Description "Run Friday price trend analysis" -Mode "price_trend" -Days @("Friday") -AtTime { _ps_quote(trend_time) }
"""
        if weekly_days:
            days = ",".join(_ps_quote(day) for day in weekly_days)
            script += f"""
Register-CompetitorRunnerTask -TaskName "CompetitorMonitor-WeeklyNew" -Description "Run weekly BI new-product monitoring for the previous complete work week" -Mode "weekly_new" -Days @({days}) -AtTime { _ps_quote(weekly_time) }
"""
        else:
            script += """
$task = Get-ScheduledTask -TaskName "CompetitorMonitor-WeeklyNew" -ErrorAction SilentlyContinue
if ($null -ne $task) { Unregister-ScheduledTask -TaskName "CompetitorMonitor-WeeklyNew" -Confirm:$false }
"""

        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            cwd=str(self.base_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            **_hidden_subprocess_kwargs(),
        )
        if completed.returncode != 0:
            error = (completed.stderr or completed.stdout or "unknown scheduled task sync error").strip()
            raise RuntimeError(error)

    def _sync_scheduler_async(self, config: dict[str, Any]) -> None:
        config_snapshot = dict(config)

        def worker() -> None:
            with self.scheduler_lock:
                try:
                    self.scheduler_syncer(config_snapshot)
                    self.log("success", "系统计划任务已同步", "Windows 计划任务时间已按当前配置更新")
                except Exception as exc:
                    self.log("warning", "系统计划任务同步失败", str(exc))

        self.log("info", "系统计划任务正在后台同步", "配置已保存，计划任务会在后台更新")
        self.schedule_thread = threading.Thread(target=worker, daemon=True)
        self.schedule_thread.start()

    def _task_runner_path(self) -> Path:
        sibling_runner = self.base_dir.parent / "CompetitorMonitorTaskRunner" / "CompetitorMonitorTaskRunner.exe"
        if sibling_runner.exists():
            return sibling_runner
        project_runner = self.base_dir / "dist" / "CompetitorMonitorTaskRunner" / "CompetitorMonitorTaskRunner.exe"
        if project_runner.exists():
            return project_runner
        return sibling_runner

    def _validate_template_file(self, path: Path) -> dict[str, Any]:
        excel = ExcelService(path)
        workbook = None
        try:
            workbook = excel.load_workbook()
            if not workbook.sheetnames:
                raise ValueError("Excel 模板没有任何工作表")
            worksheet = excel.find_sheet_for_date(workbook, date.today())
            if worksheet is None:
                worksheet = excel.find_latest_template_sheet(workbook)
            week = parse_sheet_range(worksheet.title, date.today().year) or get_work_week(date.today())
            layout = excel.detect_layout(worksheet, week.monday)
            products = excel.list_mature_products(worksheet, layout.model_column, layout.data_start_row)
            if not products:
                raise ValueError("模板中没有识别到成熟单品链接")
            return {
                "sheet_name": worksheet.title,
                "product_count": len(products),
                "model_column": layout.model_column,
                "price_columns": list(layout.date_price_columns),
            }
        finally:
            self._close_workbook(workbook)

    @staticmethod
    def _close_workbook(workbook: Any) -> None:
        if workbook is None:
            return
        close = getattr(workbook, "close", None)
        if callable(close):
            close()

    @staticmethod
    def _close_logger(logger: Any) -> None:
        if logger is None:
            return
        for handler in list(getattr(logger, "handlers", [])):
            handler.close()
            logger.removeHandler(handler)

    def _load_persisted_results(self) -> list[dict[str, Any]]:
        if not self.results_path.exists():
            return []
        items: list[dict[str, Any]] = []
        try:
            for line in self.results_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                if isinstance(item, dict):
                    items.append(self._sanitize_result_for_storage(item))
        except (OSError, json.JSONDecodeError):
            return []
        return list(reversed(items[-1000:]))

    def _append_result(self, item: dict[str, Any]) -> None:
        self.results_path.parent.mkdir(parents=True, exist_ok=True)
        with self.results_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    def _recent_log_file_items(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        log_dir = self._resolve_path(config.get("log_dir", "competitor_monitor/logs"))
        if not log_dir.exists():
            return []
        items: list[dict[str, Any]] = []
        for log_path in sorted(log_dir.glob("*.log"), key=lambda item: item.stat().st_mtime, reverse=True)[:5]:
            try:
                lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
            except OSError:
                continue
            for index, line in enumerate(lines):
                parsed = _parse_log_line(line)
                if not parsed:
                    continue
                parsed["id"] = f"file:{log_path.name}:{index}"
                parsed["detail"] = parsed.get("detail") or self._display_path(log_path)
                items.append(parsed)
        return items

    def _sanitize_result_for_storage(self, item: dict[str, Any]) -> dict[str, Any]:
        cleaned = dict(item)
        for key in list(cleaned.keys()):
            if _is_url_key(key):
                cleaned[key] = _public_url(cleaned[key])
        return cleaned

    def _is_running_locked(self) -> bool:
        return self.status.get("system_status") in {"running", "backfilling", "saving", "sending"}

    def _task_cards(self, config: dict[str, Any], status: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        status = status or self.status
        return [
            {
                "id": "daily_price",
                "title": "每日价格采集",
                "status": status["system_status"] if status.get("active_mode") == "daily_price" else "idle",
                "status_text": self.status_text(status["system_status"] if status.get("active_mode") == "daily_price" else "idle"),
                "last_run": status.get("finished_at") or "-",
                "last_result": status.get("current_step") or "-",
                "template_status": status.get("target_sheet_name") or "-",
                "notify_status": status.get("last_notify_file_status") or "not_sent",
            },
            {
                "id": "weekly_new",
                "title": "周末 BI 上新采集",
                "status": status["system_status"] if status.get("active_mode") == "weekly_new" else "idle",
                "status_text": self.status_text(status["system_status"] if status.get("active_mode") == "weekly_new" else "idle"),
                "last_run": status.get("finished_at") or "-",
                "last_result": status.get("current_step") or "-",
                "template_status": status.get("target_sheet_name") or "-",
                "notify_status": status.get("last_notify_file_status") or "not_sent",
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
            "results": len(self.results),
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
            "filled_count": filled,
            "total_count": total,
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
        with self.lock:
            status = dict(self.status)
            logs = list(self.logs)
            results = list(self.results)
        return format_wecom_summary(status=status, logs=logs, results=results)

    def _primary_workbook_path(self, config: dict[str, Any]) -> Path:
        return self._resolve_path(config.get("excel_path", "竞品监控.xlsx")).resolve()

    def _active_workbook_path(self, config: dict[str, Any]) -> Path:
        return self.workbook_state.get_active_workbook_path(self._primary_workbook_path(config))

    def _workbook_status_payload(self, config: dict[str, Any]) -> dict[str, Any]:
        return self.workbook_state.status_payload(self._primary_workbook_path(config))

    def _save_fallback_handler(self, primary_path: Path):
        def save_fallback(temp_path: Path, _target_path: Path, error: Exception) -> Path:
            fallback_path = self.workbook_state.save_temp_to_fallback(temp_path, primary_path, error)
            self.log("info", "已保存到当前最新工作簿", self._display_path(fallback_path))
            return fallback_path

        return save_fallback

    def _resolve_path(self, value: Any) -> Path:
        path = Path(str(value))
        return path if path.is_absolute() else self.base_dir / path

    def _runtime_config(self, config: dict[str, Any]) -> dict[str, Any]:
        resolved = dict(config)
        for key in RUNTIME_PATH_KEYS:
            value = resolved.get(key)
            if value not in (None, ""):
                resolved[key] = str(self._resolve_path(value))
        return resolved

    def _display_path(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.base_dir).as_posix()
        except ValueError:
            return str(path)

    def _sanitize(self, value):
        if isinstance(value, dict):
            return {
                key: (
                    SECRET_PLACEHOLDER
                    if _is_secret_key(key)
                    else _public_url(item)
                    if _is_url_key(key)
                    else self._sanitize(item)
                )
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


def _has_schedule_change(payload: dict[str, Any]) -> bool:
    return any(
        key in payload
        for key in (
            "daily_run_time",
            "weekly_new_time",
            "price_trend_time",
            "bi_run_saturday",
            "bi_run_sunday",
        )
    )


def _schedule_time(value: Any, default: str) -> str:
    text = str(value or default).strip()
    try:
        return datetime.strptime(text, "%H:%M").strftime("%H:%M")
    except ValueError:
        return datetime.strptime(default, "%H:%M").strftime("%H:%M")


def _schedule_day_names(days: set[int]) -> list[str]:
    mapping = {
        0: "Monday",
        1: "Tuesday",
        2: "Wednesday",
        3: "Thursday",
        4: "Friday",
        5: "Saturday",
        6: "Sunday",
    }
    return [mapping[day] for day in sorted(days) if day in mapping]


def _ps_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _hidden_subprocess_kwargs() -> dict[str, Any]:
    if os.name != "nt":
        return {}
    kwargs: dict[str, Any] = {}
    creation_flag = getattr(subprocess, "CREATE_NO_WINDOW", None)
    if creation_flag is not None:
        kwargs["creationflags"] = creation_flag
    startupinfo_type = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_type is not None:
        startupinfo = startupinfo_type()
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        kwargs["startupinfo"] = startupinfo
    return kwargs


def _coerce_pid(value: Any) -> int | None:
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, int(pid))
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return True


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


def _is_url_key(key: str) -> bool:
    lower = key.lower()
    return lower in {"url", "link", "商品链接"} or lower.endswith("_url")


def _public_url(value: Any) -> Any:
    text = str(value or "")
    if not text.startswith(("http://", "https://")):
        return value
    parsed = urlparse(text)
    query = parse_qs(parsed.query)
    public_query = {}
    for key in ("id", "item_id", "itemId"):
        if query.get(key):
            public_query[key] = query[key][0]
            break
    return urlunparse(parsed._replace(query=urlencode(public_query, doseq=False), fragment=""))


def _parse_log_line(line: str) -> dict[str, Any] | None:
    text = str(line or "").strip()
    if not text:
        return None
    match = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+\[(\w+)\]\s+(.*)$", text)
    if not match:
        return None
    return {
        "time": match.group(1),
        "level": match.group(2).lower(),
        "message": _localize_log_message(match.group(3)),
        "detail": "",
    }


def _parse_log_time(value: Any) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def _result_status_text(value: Any) -> str:
    return {
        "success": "成功",
        "failed": "失败",
        "skipped": "跳过",
        "warning": "需复核",
    }.get(str(value or ""), str(value or ""))


def _needs_manual_review(text: str) -> bool:
    return any(token in text for token in ("人工复核", "价格异常", "异常波动", "需复核"))


def _localize_log_message(message: str) -> str:
    text = str(message or "")
    patterns = [
        (r"^Saved Excel: (.+)$", "Excel 已保存：{0}"),
        (r"^Price trend sheet: (.+)$", "价格情况 Sheet：{0}"),
        (r"^Price trend period start date: (.+)$", "价格情况周期开始：{0}"),
        (r"^Price trend period end date: (.+)$", "价格情况周期结束：{0}"),
        (r"^Price trend status column: (.+)$", "价格情况写入列：{0}"),
        (r"^Price trend total rows: (.+)$", "价格情况总行数：{0}"),
        (r"^Price trend written count: (.+)$", "价格情况写入数量：{0}"),
        (r"^Price trend skipped existing count: (.+)$", "价格情况已存在跳过：{0}"),
        (r"^Price trend skipped incomplete count: (.+)$", "价格不完整跳过：{0}"),
        (r"^Price trend skipped unclassified count: (.+)$", "未分类跳过：{0}"),
        (r"^Current sheet: (.+)$", "当前 Sheet：{0}"),
        (r"^Current period start date: (.+)$", "目标周期开始：{0}"),
        (r"^Current period end date: (.+)$", "目标周期结束：{0}"),
        (r"^Current period sheet name: (.+)$", "目标周期 Sheet：{0}"),
        (r"^New-product brand count: (.+)$", "上新监控品牌数：{0}"),
        (r"^BI shop total count: (.+)$", "BI 店铺总数：{0}"),
        (r"^BI queried shop count: (.+)$", "BI 已查询店铺数：{0}"),
        (r"^BI raw new-product count: (.+)$", "BI 原始上新数量：{0}"),
        (r"^Matched current-period new-product count: (.+)$", "匹配当前周期上新数量：{0}"),
        (r"^Unmatched new-product count ignored by Excel brand mapping: (.+)$", "未匹配品牌已忽略数量：{0}"),
        (r"^Dry-run mode: BI browser collection and new-product writes are skipped$", "dry-run：已跳过 BI 浏览器采集和上新写入"),
        (r"^Dry-run mode: browser collection and workbook writes are skipped$", "dry-run：已跳过浏览器采集和 Excel 写入"),
        (r"^Dry-run mode: price trend workbook writes are skipped$", "dry-run：已跳过价格情况写入保存"),
    ]
    for pattern, template in patterns:
        match = re.match(pattern, text)
        if match:
            return template.format(*match.groups())
    return text
