from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from state_file_service import atomic_write_json


class CookieImportError(ValueError):
    pass


def normalize_taobao_cookie_export(content: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CookieImportError("Cookie 文件不是有效的 JSON") from exc

    if isinstance(payload, dict):
        raw_cookies = payload.get("cookies")
    elif isinstance(payload, list):
        raw_cookies = payload
    else:
        raw_cookies = None
    if not isinstance(raw_cookies, list):
        raise CookieImportError("仅支持 storage_state.json 或 Cookie-Editor JSON 数组")

    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for raw in raw_cookies:
        cookie = _normalize_cookie(raw)
        if cookie is None:
            continue
        key = (cookie["name"], cookie["domain"].lower(), cookie["path"])
        if key in seen:
            continue
        seen.add(key)
        normalized.append(cookie)
    if not normalized:
        raise CookieImportError("文件中没有可导入的淘宝或天猫 Cookie")
    return {"cookies": normalized, "origins": []}


def import_taobao_cookie_export(content: bytes, target: Path | str) -> int:
    state = normalize_taobao_cookie_export(content)
    atomic_write_json(target, state)
    return len(state["cookies"])


def _normalize_cookie(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    value = raw.get("value")
    domain = str(raw.get("domain") or raw.get("host") or "").strip().lower()
    if not name or value is None or not _is_taobao_or_tmall_domain(domain):
        return None
    cookie: dict[str, Any] = {
        "name": name,
        "value": str(value),
        "domain": domain,
        "path": str(raw.get("path") or "/"),
    }
    expires = raw.get("expires", raw.get("expirationDate"))
    if isinstance(expires, (int, float)):
        cookie["expires"] = expires
    for key in ("httpOnly", "secure"):
        if key in raw:
            cookie[key] = bool(raw[key])
    same_site = _normalize_same_site(raw.get("sameSite"))
    if same_site:
        cookie["sameSite"] = same_site
    return cookie


def _is_taobao_or_tmall_domain(domain: str) -> bool:
    host = domain.lstrip(".").lower()
    return host == "taobao.com" or host.endswith(".taobao.com") or host == "tmall.com" or host.endswith(".tmall.com")


def _normalize_same_site(value: Any) -> str | None:
    normalized = str(value or "").strip().lower().replace("-", "_")
    return {
        "strict": "Strict",
        "lax": "Lax",
        "none": "None",
        "no_restriction": "None",
    }.get(normalized)
