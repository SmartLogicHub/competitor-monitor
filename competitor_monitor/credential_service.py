from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_BI_CREDENTIALS_PATH = "competitor_monitor/secrets/bi_credentials.json"
DEFAULT_TAOBAO_CREDENTIALS_PATH = "competitor_monitor/secrets/taobao_credentials.json"


@dataclass(frozen=True)
class BICredentials:
    username: str
    password: str


@dataclass(frozen=True)
class AccountCredentials:
    username: str
    password: str


def load_bi_credentials(config: dict[str, Any] | None = None) -> BICredentials | None:
    config = config or {}
    credentials = _load_account_credentials(
        config=config,
        username_env=config.get("bi_username_env", "BI_USER"),
        password_env=config.get("bi_password_env", "BI_PASSWORD"),
        credentials_path=config.get("bi_credentials_path", DEFAULT_BI_CREDENTIALS_PATH),
    )
    if not credentials:
        return None
    return BICredentials(username=credentials.username, password=credentials.password)


def load_taobao_credentials(config: dict[str, Any] | None = None) -> AccountCredentials | None:
    config = config or {}
    return _load_account_credentials(
        config=config,
        username_env=config.get("taobao_username_env", "TAOBAO_USER"),
        password_env=config.get("taobao_password_env", "TAOBAO_PASSWORD"),
        credentials_path=config.get("taobao_credentials_path", DEFAULT_TAOBAO_CREDENTIALS_PATH),
    )


def _load_account_credentials(
    config: dict[str, Any],
    username_env: str,
    password_env: str,
    credentials_path: str,
) -> AccountCredentials | None:
    username = os.environ.get(username_env, "").strip()
    password = os.environ.get(password_env, "")
    if username and password:
        return AccountCredentials(username=username, password=password)

    path = Path(credentials_path)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    username = str(data.get("username") or "").strip()
    password = str(data.get("password") or "")
    if not username or not password:
        return None
    return AccountCredentials(username=username, password=password)


def save_account_credentials(path: Path | str, username: str, password: str) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"username": username, "password": password}
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def save_bi_credentials(path: Path | str, username: str, password: str) -> Path:
    return save_account_credentials(path, username, password)
