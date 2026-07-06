from __future__ import annotations

import json
import mimetypes
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen


class WeComNotifyError(RuntimeError):
    pass


def send_wecom_template(config: dict[str, Any], excel_path: Path, summary: str) -> dict[str, str | None]:
    """Send the run summary and the current Excel file through a WeCom robot webhook."""
    if not bool(config.get("wecom_enabled", False)):
        return {"text_status": "not_sent", "file_status": "not_sent", "file_name": None}

    webhook = str(config.get("wecom_webhook") or "").strip()
    if not webhook or "qyapi.weixin.qq.com" not in webhook:
        raise WeComNotifyError("Webhook 无效")

    text_status = "not_sent"
    file_status = "not_sent"
    if bool(config.get("wecom_send_summary", True)):
        _post_json(webhook, {"msgtype": "text", "text": {"content": summary}})
        text_status = "success"

    if bool(config.get("wecom_send_excel_file", True)):
        if not excel_path.exists():
            raise WeComNotifyError("文件不存在")
        if excel_path.stat().st_size > int(config.get("wecom_file_size_limit_mb", 20)) * 1024 * 1024:
            raise WeComNotifyError("文件过大")
        media_id = _upload_file(webhook, excel_path)
        _post_json(webhook, {"msgtype": "file", "file": {"media_id": media_id}})
        file_status = "success"

    return {"text_status": text_status, "file_status": file_status, "file_name": excel_path.name}


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=data, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
    response = _load_json_response(request)
    if int(response.get("errcode", -1)) != 0:
        raise WeComNotifyError(f"企业微信接口返回错误: {response.get('errmsg') or response}")
    return response


def _upload_file(webhook: str, file_path: Path) -> str:
    upload_url = _build_upload_url(webhook)
    boundary = f"----competitor-monitor-{uuid.uuid4().hex}"
    body = _build_multipart_file_body(boundary, file_path)
    request = Request(
        upload_url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    response = _load_json_response(request)
    if int(response.get("errcode", -1)) != 0:
        raise WeComNotifyError(f"企业微信接口返回错误: {response.get('errmsg') or response}")
    media_id = response.get("media_id")
    if not media_id:
        raise WeComNotifyError("后端上传成功但未获得 media_id")
    return str(media_id)


def _build_upload_url(webhook: str) -> str:
    parsed = urlparse(webhook)
    query = parse_qs(parsed.query)
    key = (query.get("key") or [""])[0]
    if not key:
        raise WeComNotifyError("Webhook 无效")
    upload_query = urlencode({"key": key, "type": "file"})
    return urlunparse((parsed.scheme, parsed.netloc, "/cgi-bin/webhook/upload_media", "", upload_query, ""))


def _build_multipart_file_body(boundary: str, file_path: Path) -> bytes:
    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="media"; filename="{file_path.name}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    footer = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return header + file_path.read_bytes() + footer


def _load_json_response(request: Request) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except WeComNotifyError:
        raise
    except Exception as exc:  # pragma: no cover - network failures are environment-specific
        raise WeComNotifyError(f"网络失败: {exc}") from exc
