from __future__ import annotations

import json
import mimetypes
import shutil
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from web_api import WebApiService


def create_server(host: str, port: int, service: WebApiService, web_root: Path | str) -> ThreadingHTTPServer:
    handler = _build_handler(service, Path(web_root))
    return ThreadingHTTPServer((host, port), handler)


def run_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    project_root = runtime_base_dir()
    config_path = ensure_local_config(project_root)
    service = WebApiService(base_dir=project_root, config_path=config_path)
    server = create_server(host, port, service, find_web_root(project_root))
    print(f"Web 控制台已启动：http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nWeb 控制台已停止")
    finally:
        server.server_close()


def runtime_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def find_web_root(base_dir: Path) -> Path:
    candidates = [base_dir / "web_frontend"]
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        candidates.append(Path(bundled_root) / "web_frontend")
    candidates.append(Path(__file__).resolve().parents[1] / "web_frontend")
    for candidate in candidates:
        if (candidate / "index.html").exists():
            return candidate
    return candidates[0]


def ensure_local_config(base_dir: Path) -> Path:
    config_path = base_dir / "competitor_monitor" / "config.yaml"
    if config_path.exists():
        return config_path
    example_candidates = [base_dir / "competitor_monitor" / "config.example.yaml"]
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        example_candidates.append(Path(bundled_root) / "competitor_monitor" / "config.example.yaml")
    for example_path in example_candidates:
        if example_path.exists():
            config_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(example_path, config_path)
            return config_path
    return config_path


def _build_handler(service: WebApiService, web_root: Path):
    class CompetitorMonitorHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            try:
                if parsed.path.startswith("/api/"):
                    self._handle_api_get(parsed.path, parse_qs(parsed.query))
                else:
                    self._serve_static(parsed.path)
            except Exception as exc:
                self._send_json({"message": "请求失败", "error": str(exc)}, status=500)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            try:
                payload = self._read_json()
                if parsed.path == "/api/tasks/run":
                    self._send_json(service.run_task(payload))
                elif parsed.path == "/api/tasks/stop":
                    self._send_json(service.stop_task())
                elif parsed.path == "/api/template/backfill":
                    self._send_json(service.backfill_template(payload))
                elif parsed.path == "/api/notify/send-template":
                    self._send_json(service.send_template())
                elif parsed.path == "/api/config":
                    self._send_json(service.save_config(payload))
                elif parsed.path == "/api/maintenance/cleanup":
                    self._send_json(service.cleanup_maintenance(str(payload.get("scope") or "")))
                elif parsed.path == "/api/session/reset":
                    self._send_json(service.reset_session(str(payload.get("target") or "")))
                else:
                    self._send_json({"message": "接口不存在"}, status=404)
            except Exception as exc:
                self._send_json({"message": "请求失败", "error": str(exc)}, status=500)

        def do_DELETE(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/logs":
                self._send_json(service.cleanup_maintenance("logs"))
            else:
                self._send_json({"message": "接口不存在"}, status=404)

        def log_message(self, fmt: str, *args) -> None:
            return

        def _handle_api_get(self, path: str, query: dict[str, list[str]]) -> None:
            if path == "/api/health":
                self._send_json({"status": "ok", "service": "competitor-monitor-web"})
            elif path == "/api/tasks/status":
                self._send_json(service.get_tasks_status())
            elif path == "/api/template/completeness":
                self._send_json(service.get_template_completeness(_query_one(query, "date")))
            elif path == "/api/config":
                self._send_json(service.get_config())
            elif path == "/api/logs":
                self._send_json(service.get_logs(_query_one(query, "level", "all"), _query_one(query, "q", "")))
            elif path == "/api/results":
                self._send_json(
                    service.get_results(
                        _query_one(query, "status", "all"),
                        _query_one(query, "mode", "all"),
                        _query_one(query, "q", ""),
                    )
                )
            elif path == "/api/results/export":
                self._send_text(
                    service.export_results_csv(),
                    "text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="competitor-monitor-results.csv"'},
                )
            elif path == "/api/notify/status":
                status = service.get_tasks_status()
                self._send_json(
                    {
                        "notify_enabled": status.get("notify_enabled"),
                        "last_notify_text_status": status.get("last_notify_text_status"),
                        "last_notify_file_status": status.get("last_notify_file_status"),
                        "last_notify_time": status.get("last_notify_time"),
                        "last_notify_error": status.get("last_notify_error"),
                        "last_sent_file_name": status.get("last_sent_file_name"),
                    }
                )
            else:
                self._send_json({"message": "接口不存在"}, status=404)

        def _serve_static(self, path: str) -> None:
            relative = "index.html" if path in {"", "/"} else path.lstrip("/")
            target = (web_root / relative).resolve()
            root = web_root.resolve()
            if root not in target.parents and target != root:
                self._send_json({"message": "路径不允许"}, status=403)
                return
            if target.is_dir():
                target = target / "index.html"
            if not target.exists():
                self._send_json({"message": "文件不存在"}, status=404)
                return
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", _with_charset(content_type))
            self.end_headers()
            self.wfile.write(target.read_bytes())

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            raw = self.rfile.read(length).decode("utf-8")
            return json.loads(raw) if raw else {}

        def _send_json(self, payload, status: int = 200) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_text(self, text: str, content_type: str, headers: dict[str, str] | None = None) -> None:
            data = text.encode("utf-8-sig")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

    return CompetitorMonitorHandler


def _query_one(query: dict[str, list[str]], key: str, default: str | None = None) -> str | None:
    values = query.get(key)
    if not values:
        return default
    return values[0]


def _with_charset(content_type: str) -> str:
    if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
        return f"{content_type}; charset=utf-8"
    return content_type


if __name__ == "__main__":
    run_server()
