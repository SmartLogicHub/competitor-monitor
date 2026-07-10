import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_web_task


class RunWebTaskTest(unittest.TestCase):
    def test_runtime_base_dir_can_be_overridden_for_shared_web_runtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict("os.environ", {"COMPETITOR_MONITOR_RUNTIME_DIR": tmpdir}):
                self.assertEqual(run_web_task.runtime_base_dir(), Path(tmpdir))

    def test_ensure_local_config_copies_example_for_exe_runtime_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            config_dir = base_dir / "competitor_monitor"
            config_dir.mkdir()
            example = config_dir / "config.example.yaml"
            example.write_text('excel_path: "竞品监控.xlsx"\nwecom_enabled: false\n', encoding="utf-8")

            config_path = run_web_task.ensure_local_config(base_dir)

            self.assertEqual(config_path, config_dir / "config.yaml")
            self.assertTrue(config_path.exists())
            self.assertEqual(config_path.read_text(encoding="utf-8"), example.read_text(encoding="utf-8"))

    def test_task_runner_exe_prefers_sibling_web_runtime_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dist_dir = Path(tmpdir)
            web_dir = dist_dir / "CompetitorMonitorWeb"
            task_dir = dist_dir / "CompetitorMonitorTaskRunner"
            (web_dir / "competitor_monitor").mkdir(parents=True)
            task_dir.mkdir()
            (web_dir / "competitor_monitor" / "config.yaml").write_text(
                'excel_path: "竞品监控.xlsx"\n',
                encoding="utf-8",
            )

            selected = run_web_task.select_runtime_base_dir(task_dir / "CompetitorMonitorTaskRunner.exe", frozen=True)

            self.assertEqual(selected, web_dir)


if __name__ == "__main__":
    unittest.main()
