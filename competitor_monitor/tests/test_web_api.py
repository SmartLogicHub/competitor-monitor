import csv
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from credential_service import load_bi_credentials, load_taobao_credentials, save_account_credentials
from web_api import RunContext, WebApiService


class WebApiServiceTest(unittest.TestCase):
    def test_config_masks_and_preserves_sensitive_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            config_path = base_dir / "config.yaml"
            taobao_path = base_dir / "secrets" / "taobao.json"
            bi_path = base_dir / "secrets" / "bi.json"
            save_account_credentials(taobao_path, "test-taobao-user", "old-pass")
            save_account_credentials(bi_path, "test-bi-user", "old-bi-pass")
            config_path.write_text(
                "\n".join(
                    [
                        'excel_path: "竞品监控.xlsx"',
                        f'taobao_credentials_path: "{taobao_path.as_posix()}"',
                        f'bi_credentials_path: "{bi_path.as_posix()}"',
                        'wecom_webhook: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=old"',
                        "wecom_enabled: true",
                        'run_date: "2026-07-06"',
                        "dry_run: true",
                        "test_one: true",
                    ]
                ),
                encoding="utf-8",
            )
            service = WebApiService(base_dir=base_dir, config_path=config_path)

            public_config = service.get_config()

            self.assertEqual(public_config["excel_path"], "竞品监控.xlsx")
            self.assertTrue(public_config["wecom_webhook_set"])
            self.assertNotIn("wecom_webhook", public_config)
            self.assertEqual(public_config["run_date"], "2026-07-06")
            self.assertTrue(public_config["dry_run"])
            self.assertTrue(public_config["test_one"])
            self.assertEqual(public_config["taobao_login_status"], "运行时检测")
            self.assertEqual(public_config["taobao_credential_status"], "已保存凭据")
            self.assertEqual(public_config["taobao_username_masked"], "已保存账号")
            self.assertTrue(public_config["taobao_password_set"])
            self.assertEqual(public_config["bi_login_status"], "运行时检测")
            self.assertEqual(public_config["bi_credential_status"], "已保存凭据")
            self.assertEqual(public_config["bi_username_masked"], "已保存账号")
            self.assertTrue(public_config["bi_password_set"])
            self.assertNotIn("test-taobao-user", json.dumps(public_config, ensure_ascii=False))
            self.assertNotIn("test-bi-user", json.dumps(public_config, ensure_ascii=False))

            service.save_config(
                {
                    "excel_path": "竞品监控_验收测试.xlsx",
                    "wecom_webhook": "******",
                    "taobao_username": "new-taobao",
                    "taobao_password": "new-pass",
                    "bi_username": "new-bi",
                    "bi_password": "new-bi-pass",
                    "run_date": "2026-07-07",
                    "dry_run": False,
                    "test_one": False,
                }
            )

            saved_text = config_path.read_text(encoding="utf-8")
            self.assertIn('excel_path: "竞品监控_验收测试.xlsx"', saved_text)
            self.assertIn('run_date: "2026-07-07"', saved_text)
            self.assertIn("dry_run: false", saved_text)
            self.assertIn("test_one: false", saved_text)
            self.assertIn("key=old", saved_text)
            self.assertNotIn("new-pass", saved_text)
            self.assertEqual(load_taobao_credentials({"taobao_credentials_path": str(taobao_path)}).username, "new-taobao")
            self.assertEqual(load_bi_credentials({"bi_credentials_path": str(bi_path)}).password, "new-bi-pass")

    def test_config_masks_non_phone_taobao_account_without_exposing_fragments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            config_path = base_dir / "config.yaml"
            taobao_path = base_dir / "secrets" / "taobao.json"
            save_account_credentials(taobao_path, "漫步者官方旗舰店:金", "old-pass")
            config_path.write_text(
                "\n".join(
                    [
                        'excel_path: "竞品监控.xlsx"',
                        f'taobao_credentials_path: "{taobao_path.as_posix()}"',
                    ]
                ),
                encoding="utf-8",
            )
            service = WebApiService(base_dir=base_dir, config_path=config_path)

            public_config = service.get_config()
            public_json = json.dumps(public_config, ensure_ascii=False)

            self.assertEqual(public_config["taobao_username_masked"], "已保存账号")
            self.assertNotIn("漫步者", public_json)
            self.assertNotIn("旗舰店", public_json)

    def test_run_task_reports_progress_results_and_honors_stop_request(self):
        started = threading.Event()

        def runner(context: RunContext) -> None:
            context.set_total(2)
            context.set_step("正在采集")
            context.record_result(
                {
                    "mode": context.payload["mode"],
                    "sheet": "6.29-7.3",
                    "brand": "塞那",
                    "model": "S6S Ultra",
                    "status": "success",
                    "output": "268.52",
                }
            )
            started.set()
            while not context.stop_requested():
                time.sleep(0.01)
            context.log("warning", "收到停止请求", "下一条商品开始前停止")

        with tempfile.TemporaryDirectory() as tmpdir:
            service = WebApiService(base_dir=Path(tmpdir), runner=runner)

            response = service.run_task({"mode": "daily_price", "run_date": "2026-07-03"})
            self.assertEqual(response["message"], "任务已启动")
            self.assertTrue(started.wait(1))

            running_status = service.get_tasks_status()
            self.assertEqual(running_status["system_status"], "running")
            self.assertEqual(running_status["progress_done"], 1)
            self.assertEqual(running_status["success_count"], 1)

            stop_response = service.stop_task()
            self.assertEqual(stop_response["message"], "已请求停止当前任务")
            service.wait_for_current_task(timeout=1)

            stopped_status = service.get_tasks_status()
            self.assertEqual(stopped_status["system_status"], "stopped")
            self.assertEqual(stopped_status["last_error"], None)
            self.assertEqual(service.get_results()[0]["model"], "S6S Ultra")
            self.assertEqual(service.get_logs(level="warning")[0]["message"], "收到停止请求")

    def test_template_completeness_and_export_results_are_frontend_ready(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            config_path = base_dir / "config.yaml"
            config_path.write_text('excel_path: "missing.xlsx"\n', encoding="utf-8")
            service = WebApiService(base_dir=base_dir, config_path=config_path)
            service.record_result(
                {
                    "mode": "weekly_new",
                    "sheet": "6.29-7.3",
                    "brand": "绿联",
                    "model": "S6PRO",
                    "status": "skipped",
                    "error_reason": "重复商品",
                }
            )

            completeness = service.get_template_completeness("2026-07-03")
            self.assertEqual(completeness["sheet_name"], None)
            self.assertEqual(completeness["period_start"], "2026-06-29")
            self.assertFalse(completeness["complete"])
            self.assertEqual(completeness["missing_dates"], ["2026-06-29", "2026-06-30", "2026-07-01", "2026-07-02", "2026-07-03"])

            rows = list(csv.DictReader(service.export_results_csv().splitlines()))

            self.assertEqual(rows[0]["mode"], "weekly_new")
            self.assertEqual(rows[0]["brand"], "绿联")
            self.assertEqual(rows[0]["status"], "skipped")

    def test_summary_results_are_visible_for_non_itemized_web_tasks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = WebApiService(base_dir=Path(tmpdir))
            service.status["system_status"] = "running"

            service.record_task_summary("price_trend", "价格情况分析", "共 100 行，写入 97 行")

            status = service.get_tasks_status()
            results = service.get_results()

            self.assertEqual(status["progress_total"], 1)
            self.assertEqual(status["progress_done"], 1)
            self.assertEqual(status["success_count"], 1)
            self.assertEqual(results[0]["mode"], "price_trend")
            self.assertEqual(results[0]["model"], "价格情况分析")
            self.assertEqual(results[0]["output"], "共 100 行，写入 97 行")

    def test_dry_run_task_does_not_send_wecom_template(self):
        notify_calls = []

        def runner(context: RunContext) -> None:
            context.set_total(1)
            context.record_result({"mode": "daily_price", "model": "S6S proII", "status": "skipped"})

        def notifier(config, excel_path, summary):
            notify_calls.append((config, excel_path, summary))
            return {"file_name": excel_path.name, "text_status": "success", "file_status": "success"}

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            config_path = base_dir / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        'excel_path: "missing.xlsx"',
                        "wecom_enabled: true",
                        'wecom_webhook: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=secret"',
                    ]
                ),
                encoding="utf-8",
            )
            service = WebApiService(base_dir=base_dir, config_path=config_path, runner=runner, notifier=notifier)

            service.run_task({"mode": "daily_price", "run_date": "2026-07-06", "dry_run": True})
            service.wait_for_current_task(timeout=1)

            status = service.get_tasks_status()
            self.assertEqual(status["system_status"], "success")
            self.assertEqual(notify_calls, [])
            self.assertEqual(status["last_notify_file_status"], "not_sent")

    def test_notify_and_session_endpoints_update_public_state_without_exposing_secrets(self):
        def fake_notifier(config, excel_path, summary):
            return {"file_name": excel_path.name, "text_status": "success", "file_status": "success"}

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            excel_path = base_dir / "竞品监控.xlsx"
            excel_path.write_bytes(b"fake excel")
            config_path = base_dir / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        f'excel_path: "{excel_path.as_posix()}"',
                        'wecom_enabled: true',
                        'wecom_webhook: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=secret"',
                    ]
                ),
                encoding="utf-8",
            )
            service = WebApiService(base_dir=base_dir, config_path=config_path, notifier=fake_notifier)

            notify = service.send_template()
            session = service.reset_session("taobao")
            status = service.get_tasks_status()
            config = service.get_config()

            self.assertEqual(notify["message"], "当前模板已发送")
            self.assertEqual(status["last_notify_file_status"], "success")
            self.assertEqual(status["last_sent_file_name"], "竞品监控.xlsx")
            self.assertEqual(session["message"], "登录状态已重置")
            self.assertEqual(config["taobao_status"], "需重新登录")
            self.assertNotIn("secret", json.dumps(status, ensure_ascii=False))

    def test_wecom_summary_includes_price_alerts_for_manual_review(self):
        summaries = []

        def fake_notifier(config, excel_path, summary):
            summaries.append(summary)
            return {"file_name": excel_path.name, "text_status": "success", "file_status": "success"}

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            excel_path = base_dir / "竞品监控.xlsx"
            excel_path.write_bytes(b"fake excel")
            config_path = base_dir / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        f'excel_path: "{excel_path.as_posix()}"',
                        'wecom_enabled: true',
                        'wecom_webhook: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=secret"',
                    ]
                ),
                encoding="utf-8",
            )
            service = WebApiService(base_dir=base_dir, config_path=config_path, notifier=fake_notifier)
            service.log("warning", "价格异常波动，需人工复核", "row=24 商品=A5 历史价=109.65 本次写入=79.9")

            service.send_template()

            self.assertTrue(summaries)
            self.assertIn("需人工复核的价格异常", summaries[0])
            self.assertIn("A5", summaries[0])
            self.assertIn("109.65", summaries[0])


if __name__ == "__main__":
    unittest.main()
