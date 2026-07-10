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

    def test_delivery_scripts_exist_and_keep_runtime_data_local(self):
        project_root = Path(__file__).resolve().parents[2]
        build_script = project_root / "打包EXE.bat"
        install_tasks_script = project_root / "scripts" / "install_windows_tasks.ps1"
        remove_tasks_script = project_root / "scripts" / "remove_windows_tasks.ps1"

        self.assertTrue(build_script.exists())
        self.assertTrue(install_tasks_script.exists())
        self.assertTrue(remove_tasks_script.exists())

        build_text = build_script.read_text(encoding="utf-8-sig")
        install_text = install_tasks_script.read_text(encoding="utf-8-sig")
        remove_text = remove_tasks_script.read_text(encoding="utf-8-sig")

        self.assertIn("pyinstaller", build_text.lower())
        self.assertIn("Checking runtime dependencies", build_text)
        self.assertIn("import openpyxl, yaml, rebrowser_playwright", build_text)
        self.assertIn('set "PYTHONNOUSERSITE=1"', build_text)
        self.assertIn('set "PYTHONUSERBASE=%CD%\\.py_user_base"', build_text)
        self.assertIn("competitor_monitor\\web_server.py", build_text)
        self.assertIn("CompetitorMonitorWeb", build_text)
        self.assertIn("CompetitorMonitorTaskRunner", build_text)
        self.assertIn("--noconsole --name \"%WEB_APP_NAME%\"", build_text)
        self.assertIn("--noconsole --name \"%TASK_APP_NAME%\"", build_text)
        self.assertIn("rebrowser_playwright", build_text)
        self.assertIn("driver", build_text)
        self.assertIn("Register-ScheduledTask", install_text)
        self.assertIn("CompetitorMonitorWeb.exe", install_text)
        self.assertIn("--config", install_text)
        self.assertIn('New-ScheduledTaskAction -Execute "powershell.exe"', install_text)
        self.assertIn("-WindowStyle Hidden", install_text)
        self.assertIn("-EncodedCommand $encodedCommand", install_text)
        self.assertIn("Start-Process -FilePath", install_text)
        self.assertIn("-WindowStyle Hidden -Wait -PassThru", install_text)
        self.assertNotIn('New-ScheduledTaskAction -Execute $runnerExe -Argument $exeArgument', install_text)
        self.assertNotIn("New-ScheduledTaskPrincipal", install_text)
        self.assertNotIn("RunLevel LeastPrivilege", install_text)
        self.assertIn("*Web.bat", install_text)
        self.assertIn("daily_price", install_text)
        self.assertIn("weekly_new", install_text)
        self.assertIn("price_trend", install_text)
        self.assertIn("CompetitorMonitor-DailyPrice", install_text)
        self.assertIn("Unregister-ScheduledTask", remove_text)


if __name__ == "__main__":
    unittest.main()
