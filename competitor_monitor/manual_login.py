from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from browser_service import BrowserService
from config_service import load_config
from state_file_service import atomic_write_json


SESSION_FILENAME = "taobao_login_session.json"
TMALL_LOGIN_FALLBACK_URL = "https://www.tmall.com/"


def run_taobao_login_browser(
    base_dir: Path | str,
    config_path: Path | str | None = None,
    login_url: str | None = None,
    browser_factory: Callable[..., Any] = BrowserService,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> int:
    base_dir = Path(base_dir).resolve()
    config_path = Path(config_path) if config_path else base_dir / "competitor_monitor" / "config.yaml"
    if not config_path.is_absolute():
        config_path = base_dir / config_path
    config = load_config(config_path) if config_path.exists() else {}
    runtime_config = _resolve_browser_paths(config, base_dir)
    user_data_dir = Path(
        runtime_config.get("browser_user_data_dir") or base_dir / "competitor_monitor" / "browser_profile"
    )
    state_path = base_dir / "competitor_monitor" / "web_state" / SESSION_FILENAME
    auth_status = "checking"
    _write_state(state_path, "running", pid=os.getpid(), auth_status=auth_status)

    try:
        with browser_factory(
            headless=False,
            timeout_ms=int(runtime_config.get("timeout_ms", 30000)),
            user_data_dir=user_data_dir,
            context_config=runtime_config,
            taobao_credentials=None,
        ) as browser:
            page = browser.open_manual_page(
                login_url
                or runtime_config.get("taobao_manual_login_url")
                or TMALL_LOGIN_FALLBACK_URL
            )
            poll_seconds = max(0.25, float(runtime_config.get("manual_login_poll_seconds", 1.0)))
            authenticated_export_attempted = False
            while browser.has_open_pages():
                detected_status = browser.get_manual_page_auth_state(page)
                if detected_status in {
                    "checking",
                    "login_required",
                    "manual_action_required",
                    "authenticated",
                } and detected_status != auth_status:
                    auth_status = detected_status
                    _write_state(state_path, "running", pid=os.getpid(), auth_status=auth_status)
                if auth_status == "authenticated" and not authenticated_export_attempted:
                    authenticated_export_attempted = True
                    browser.persist_storage_state()
                sleep_fn(poll_seconds)
            browser.persist_storage_state()
        _write_state(state_path, "closed", pid=os.getpid(), auth_status=auth_status)
        return 0
    except Exception as exc:
        _write_state(state_path, "failed", pid=os.getpid(), error=str(exc), auth_status=auth_status)
        return 1


def _resolve_browser_paths(config: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    resolved = dict(config)
    for key in ("browser_user_data_dir", "browser_storage_state_path"):
        value = resolved.get(key)
        if value in (None, ""):
            continue
        path = Path(str(value))
        resolved[key] = str(path if path.is_absolute() else base_dir / path)
    return resolved


def _write_state(
    path: Path,
    status: str,
    pid: int | None = None,
    error: str | None = None,
    auth_status: str = "checking",
) -> None:
    atomic_write_json(
        path,
        {
            "status": status,
            "auth_status": auth_status,
            "pid": pid,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "error": error,
        },
    )
