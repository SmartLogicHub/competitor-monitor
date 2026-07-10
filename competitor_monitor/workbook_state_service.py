from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from excel_service import ExcelService, WorkbookLockedError
from state_file_service import atomic_write_json


SYNCED = "synced"
PENDING_SYNC = "pending_sync"
SYNC_FAILED = "sync_failed"


class WorkbookStateService:
    """Persist and resolve the latest workbook used by Web/EXE runs."""

    def __init__(self, base_dir: Path | str, web_state_dir: Path | str | None = None):
        self.base_dir = Path(base_dir).resolve()
        self.web_state_dir = Path(web_state_dir).resolve() if web_state_dir else self.base_dir / "competitor_monitor" / "web_state"
        self.state_path = self.web_state_dir / "workbook_state.json"
        self.latest_dir = self.base_dir / "output" / "latest"
        self.runs_dir = self.base_dir / "output" / "runs"

    def status_payload(self, primary_path: Path | str) -> dict[str, Any]:
        primary = self._resolve(primary_path)
        state = self._state_for_primary(primary)
        sync_status = str(state.get("sync_status") or SYNCED)
        active = self._active_from_state(primary, state)
        pending = self._optional_path(state.get("pending_sync_path"))
        return {
            "workbook_sync_status": sync_status,
            "workbook_sync_status_text": self._status_text(sync_status),
            "primary_workbook_path": str(primary),
            "active_workbook_path": str(active),
            "pending_sync_path": str(pending) if pending else None,
            "last_workbook_sync_at": state.get("last_sync_at"),
            "last_workbook_sync_error": state.get("last_sync_error"),
            "run_workbook_count": self.count_run_workbooks(),
        }

    def get_active_workbook_path(self, primary_path: Path | str) -> Path:
        primary = self._resolve(primary_path)
        return self._active_from_state(primary, self._state_for_primary(primary))

    def prepare_active_for_run(self, primary_path: Path | str) -> Path:
        primary = self._resolve(primary_path)
        active = self.get_active_workbook_path(primary)
        if active == primary:
            return active
        if not active.exists():
            raise FileNotFoundError(f"当前最新工作簿不存在：{active}")
        try:
            ExcelService.assert_workbook_writable(active)
            return active
        except WorkbookLockedError as exc:
            run_path = self.next_run_path(primary)
            run_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(active, run_path)
            self.mark_pending_sync(run_path, primary, str(exc))
            return run_path.resolve()

    def mark_pending_sync(self, active_path: Path | str, primary_path: Path | str, error: str | None = None) -> None:
        primary = self._resolve(primary_path)
        active = self._resolve(active_path)
        self._write_state(
            {
                "primary_path": str(primary),
                "active_path": str(active),
                "pending_sync_path": str(active),
                "sync_status": PENDING_SYNC,
                "last_sync_at": None,
                "last_sync_error": error,
                "updated_at": self._now_text(),
            }
        )

    def mark_synced(self, primary_path: Path | str) -> None:
        primary = self._resolve(primary_path)
        self._write_state(
            {
                "primary_path": str(primary),
                "active_path": str(primary),
                "pending_sync_path": None,
                "sync_status": SYNCED,
                "last_sync_at": self._now_text(),
                "last_sync_error": None,
                "updated_at": self._now_text(),
            }
        )

    def try_sync_latest_to_primary(self, primary_path: Path | str) -> dict[str, Any]:
        primary = self._resolve(primary_path)
        active = self.get_active_workbook_path(primary)
        if active == primary:
            self.mark_synced(primary)
            self.cleanup_runs(primary)
            return {"message": "主模板已同步", "sync_status": SYNCED}
        if not active.exists():
            error = f"当前最新工作簿不存在：{active}"
            self._mark_sync_failed(active, primary, error)
            return {"message": "主模板仍未同步", "sync_status": SYNC_FAILED, "error": error}

        primary.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            temp = tempfile.NamedTemporaryFile(delete=False, suffix=primary.suffix or ".xlsx", dir=primary.parent)
            temp_path = Path(temp.name)
            temp.close()
            shutil.copy2(active, temp_path)
            ExcelService._replace_file_with_retry(temp_path, primary, attempts=3, delay_seconds=0.2)
            self.mark_synced(primary)
            latest = self.latest_path(primary)
            if latest.exists() and latest.resolve() != primary:
                try:
                    latest.unlink()
                except OSError:
                    pass
            self.cleanup_runs(primary)
            return {"message": "主模板已同步", "sync_status": SYNCED}
        except Exception as exc:
            error = str(exc)
            self.mark_pending_sync(active, primary, error)
            return {"message": "主模板仍被占用，稍后可重试", "sync_status": PENDING_SYNC, "error": error}
        finally:
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def save_temp_to_fallback(self, temp_path: Path | str, primary_path: Path | str, error: Exception | str | None = None) -> Path:
        source = Path(temp_path)
        primary = self._resolve(primary_path)
        latest = self.latest_path(primary)
        latest.parent.mkdir(parents=True, exist_ok=True)
        try:
            ExcelService._replace_file_with_retry(source, latest, attempts=1, delay_seconds=0)
            self.mark_pending_sync(latest, primary, str(error) if error else None)
            return latest.resolve()
        except WorkbookLockedError:
            run_path = self.next_run_path(primary)
            run_path.parent.mkdir(parents=True, exist_ok=True)
            ExcelService._replace_file_with_retry(source, run_path, attempts=1, delay_seconds=0)
            self.mark_pending_sync(run_path, primary, str(error) if error else None)
            return run_path.resolve()

    def latest_path(self, primary_path: Path | str) -> Path:
        primary = self._resolve(primary_path)
        return (self.latest_dir / primary.name).resolve()

    def next_run_path(self, primary_path: Path | str) -> Path:
        primary = self._resolve(primary_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        candidate = self.runs_dir / f"{primary.stem}_{timestamp}{primary.suffix or '.xlsx'}"
        index = 1
        while candidate.exists():
            candidate = self.runs_dir / f"{primary.stem}_{timestamp}_{index:02d}{primary.suffix or '.xlsx'}"
            index += 1
        return candidate.resolve()

    def cleanup_runs(self, primary_path: Path | str, keep: int = 10) -> None:
        if not self.runs_dir.exists():
            return
        primary = self._resolve(primary_path)
        state = self._state_for_primary(primary)
        protected = {primary}
        for key in ("active_path", "pending_sync_path"):
            value = self._optional_path(state.get(key))
            if value:
                protected.add(value)
        run_paths = sorted(self.runs_dir.glob("*.xlsx"), key=lambda path: path.stat().st_mtime, reverse=True)
        recent = set(path.resolve() for path in run_paths[: max(0, keep)])
        for path in run_paths:
            resolved = path.resolve()
            if resolved in protected or resolved in recent:
                continue
            try:
                path.unlink()
            except OSError:
                pass

    def count_run_workbooks(self) -> int:
        if not self.runs_dir.exists():
            return 0
        return sum(1 for _ in self.runs_dir.glob("*.xlsx"))

    def _active_from_state(self, primary: Path, state: dict[str, Any]) -> Path:
        sync_status = str(state.get("sync_status") or SYNCED)
        if sync_status in {PENDING_SYNC, SYNC_FAILED}:
            active = self._optional_path(state.get("active_path")) or self._optional_path(state.get("pending_sync_path"))
            if active:
                return active
        return primary.resolve()

    def _state_for_primary(self, primary: Path) -> dict[str, Any]:
        state = self._read_state()
        sync_status = str(state.get("sync_status") or SYNCED)
        if sync_status not in {PENDING_SYNC, SYNC_FAILED}:
            return state
        active = self._optional_path(state.get("active_path")) or self._optional_path(state.get("pending_sync_path"))
        if active and not active.exists():
            self.mark_synced(primary)
            return self._read_state()
        return state

    def _mark_sync_failed(self, active: Path, primary: Path, error: str) -> None:
        self._write_state(
            {
                "primary_path": str(primary),
                "active_path": str(active),
                "pending_sync_path": str(active),
                "sync_status": SYNC_FAILED,
                "last_sync_at": None,
                "last_sync_error": error,
                "updated_at": self._now_text(),
            }
        )

    def _read_state(self) -> dict[str, Any]:
        try:
            if not self.state_path.exists():
                return {}
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _write_state(self, payload: dict[str, Any]) -> None:
        atomic_write_json(self.state_path, payload)

    def _optional_path(self, value: Any) -> Path | None:
        if not value:
            return None
        return self._resolve(value)

    def _resolve(self, value: Path | str) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = self.base_dir / path
        return path.resolve()

    @staticmethod
    def _status_text(sync_status: str) -> str:
        if sync_status == SYNCED:
            return "已同步"
        if sync_status == PENDING_SYNC:
            return "主模板待同步"
        if sync_status == SYNC_FAILED:
            return "同步失败"
        return sync_status or "-"

    @staticmethod
    def _now_text() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
