import unittest
from pathlib import Path


class StartupScriptsTest(unittest.TestCase):
    def test_one_click_startup_scripts_exist_and_check_health(self):
        project_root = Path(__file__).resolve().parents[2]
        bat_path = project_root / "启动Web.bat"

        self.assertTrue(bat_path.exists())

        bat_text = bat_path.read_text(encoding="utf-8-sig")

        self.assertIn("competitor_monitor\\web_server.py", bat_text)
        self.assertIn("/api/health", bat_text)
        self.assertIn("127.0.0.1:8765", bat_text)
        self.assertIn("Start-Process", bat_text)


if __name__ == "__main__":
    unittest.main()
