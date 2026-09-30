import json
import tempfile
import unittest
from pathlib import Path

from manual_login import run_taobao_login_browser


class ManualLoginTest(unittest.TestCase):
    def test_uses_collection_profile_and_persists_session_lifecycle(self):
        captured = {}

        class FakeBrowser:
            def __init__(self, **kwargs):
                captured["kwargs"] = kwargs
                self.polls = 0
                self.auth_states = iter(["login_required", "authenticated", "authenticated"])

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                captured["exited"] = True

            def open_manual_page(self, url):
                captured["url"] = url
                return "manual-page"

            def get_manual_page_auth_state(self, page):
                captured.setdefault("auth_pages", []).append(page)
                return next(self.auth_states)

            def persist_storage_state(self):
                captured["save_count"] = captured.get("save_count", 0) + 1
                return True

            def has_open_pages(self):
                self.polls += 1
                return self.polls <= 3

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            config_dir = base_dir / "competitor_monitor"
            config_dir.mkdir()
            config_path = config_dir / "config.yaml"
            config_path.write_text(
                '\n'.join(
                    [
                        'browser_user_data_dir: "competitor_monitor/browser_profile"',
                        'browser_storage_state_path: "competitor_monitor/browser_profile/storage_state.json"',
                        'timeout_ms: 12345',
                    ]
                ),
                encoding="utf-8",
            )

            result = run_taobao_login_browser(
                base_dir=base_dir,
                config_path=config_path,
                login_url="https://detail.tmall.com/item.htm?id=123",
                browser_factory=FakeBrowser,
                sleep_fn=lambda _seconds: None,
            )

            state_path = config_dir / "web_state" / "taobao_login_session.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(captured["kwargs"]["user_data_dir"], base_dir / "competitor_monitor" / "browser_profile")
        self.assertEqual(
            captured["kwargs"]["context_config"]["browser_storage_state_path"],
            str(base_dir / "competitor_monitor" / "browser_profile" / "storage_state.json"),
        )
        self.assertEqual(captured["url"], "https://detail.tmall.com/item.htm?id=123")
        self.assertEqual(captured["auth_pages"], ["manual-page"] * 3)
        self.assertEqual(captured["save_count"], 2)
        self.assertTrue(captured["exited"])
        self.assertEqual(result, 0)
        self.assertEqual(state["status"], "closed")
        self.assertEqual(state["auth_status"], "authenticated")


if __name__ == "__main__":
    unittest.main()
