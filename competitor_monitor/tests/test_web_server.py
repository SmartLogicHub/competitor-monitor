import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from web_api import WebApiService
from web_server import create_server


class WebServerTest(unittest.TestCase):
    def test_serves_static_frontend_and_json_api(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            web_root = base_dir / "web_frontend"
            web_root.mkdir()
            (web_root / "index.html").write_text("<!doctype html><title>竞品监控</title>", encoding="utf-8")
            service = WebApiService(base_dir=base_dir)
            server = create_server("127.0.0.1", 0, service, web_root)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                root = f"http://127.0.0.1:{server.server_address[1]}"
                html = urlopen(f"{root}/", timeout=2).read().decode("utf-8")
                status = json.loads(urlopen(f"{root}/api/tasks/status", timeout=2).read().decode("utf-8"))

                self.assertIn("竞品监控", html)
                self.assertEqual(status["system_status"], "idle")
            finally:
                server.shutdown()
                server.server_close()

    def test_serves_health_endpoint_for_startup_checks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = WebApiService(base_dir=Path(tmpdir))
            server = create_server("127.0.0.1", 0, service, Path(tmpdir))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                root = f"http://127.0.0.1:{server.server_address[1]}"
                health = json.loads(urlopen(f"{root}/api/health", timeout=2).read().decode("utf-8"))

                self.assertEqual(health["status"], "ok")
                self.assertEqual(health["service"], "competitor-monitor-web")
            finally:
                server.shutdown()
                server.server_close()

    def test_routes_post_json_to_service(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = WebApiService(base_dir=Path(tmpdir), runner=lambda context: None)
            server = create_server("127.0.0.1", 0, service, Path(tmpdir))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                root = f"http://127.0.0.1:{server.server_address[1]}"
                request = Request(
                    f"{root}/api/tasks/run",
                    data=json.dumps({"mode": "daily_price", "run_date": "2026-07-03"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                response = json.loads(urlopen(request, timeout=2).read().decode("utf-8"))

                self.assertEqual(response["message"], "任务已启动")
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
