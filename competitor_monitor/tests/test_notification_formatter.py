import unittest

from notification_formatter import format_wecom_summary


class NotificationFormatterTest(unittest.TestCase):
    def test_formats_price_alerts_as_chinese_business_summary(self):
        summary = format_wecom_summary(
            status={
                "system_status": "success",
                "active_mode": "daily_price",
                "run_date": "2026-07-07",
                "target_sheet_name": "7.6-7.10",
                "target_period_range": "2026-07-06 至 2026-07-10",
                "success_count": 10,
                "failed_count": 0,
                "skipped_count": 0,
            },
            logs=[
                {
                    "level": "warning",
                    "message": "价格异常波动，需人工复核",
                    "detail": "row=24 商品=A5 历史价=79.9 本次写入=109.65",
                }
            ],
            results=[],
        )

        self.assertIn("竞品监控每日价格采集完成", summary)
        self.assertIn("目标表格：7.6-7.10", summary)
        self.assertIn("本次日期：2026-07-07", summary)
        self.assertNotIn("目标周期：2026-07-06 至 2026-07-10", summary)
        self.assertIn("本次处理：成功 10 条，失败 0 条，跳过 0 条", summary)
        self.assertIn("Excel 第 24 行｜A5", summary)
        self.assertIn("历史价格：79.9", summary)
        self.assertIn("本次写入：109.65", summary)
        self.assertNotIn("row=", summary)
        self.assertNotIn("中文编码正常", summary)
        self.assertNotIn("不应出现问号乱码", summary)

    def test_formats_weekly_new_failures_as_template_issues(self):
        summary = format_wecom_summary(
            status={
                "system_status": "success",
                "active_mode": "weekly_new",
                "target_sheet_name": "6.29-7.3",
                "target_period_range": "2026-06-29 至 2026-07-03",
                "success_count": 0,
                "failed_count": 1,
                "skipped_count": 0,
            },
            logs=[],
            results=[
                {
                    "mode": "weekly_new",
                    "status": "failed",
                    "error_reason": "索尼影音 H9: 品牌区域 80-83 没有空行",
                }
            ],
        )

        self.assertIn("竞品监控上新填报完成", summary)
        self.assertIn("数据来源：边界 BI", summary)
        self.assertIn("索尼影音 H9", summary)
        self.assertIn("模板区域需要扩展", summary)
        self.assertNotIn("row=", summary)
        self.assertNotIn("周末 BI 上新采集验证", summary)

    def test_daily_summary_uses_started_date_when_run_date_is_missing(self):
        summary = format_wecom_summary(
            status={
                "system_status": "success",
                "active_mode": "daily_price",
                "started_at": "2026-07-07 14:21:01",
                "target_sheet_name": "7.6-7.10",
                "target_period_range": "2026-07-06 至 2026-07-10",
                "success_count": 100,
                "failed_count": 0,
                "skipped_count": 0,
            },
            logs=[],
            results=[],
        )

        self.assertIn("本次日期：2026-07-07", summary)
        self.assertNotIn("目标周期：2026-07-06 至 2026-07-10", summary)


if __name__ == "__main__":
    unittest.main()
