import unittest
from datetime import date

from new_product_service import (
    NewProduct,
    extract_model_name,
    get_previous_completed_work_week,
    infer_earphone_shape,
    is_weekly_new_run_day,
    normalize_bi_goods,
)


class NewProductServiceTest(unittest.TestCase):
    def test_infers_common_earphone_shapes(self):
        cases = {
            "绿联 S6PRO 耳夹式蓝牙耳机": "耳夹式",
            "JBL Q255 头戴式耳机有线电竞游戏": "头戴式",
            "某品牌 挂脖蓝牙耳机运动款": "挂脖式",
            "开放式挂耳蓝牙耳机": "挂耳式",
            "真无线入耳式降噪耳机": "入耳式",
            "半入耳蓝牙耳机": "半入耳",
        }

        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(infer_earphone_shape(name), expected)

    def test_extracts_model_from_mixed_english_chinese_names(self):
        self.assertEqual(extract_model_name("JBL LIVE BEAM4蓝牙耳机入耳式真无线主动降噪触控屏"), "BEAM4")
        self.assertEqual(extract_model_name("Sony/索尼 LinkBuds Clip 耳夹耳机蓝牙开放式运动跑步"), "LinkBuds Clip")
        self.assertEqual(extract_model_name("弱水时砂 ASTRO X 耳夹式开放式蓝牙耳机"), "ASTRO X")
        self.assertEqual(extract_model_name("漫步者花再 Auro Ace 真无线蓝牙耳机"), "Auro Ace")
        self.assertEqual(extract_model_name("小米 Redmi Buds8 蓝牙耳机"), "Buds8")
        self.assertEqual(extract_model_name("金运 A7Ultra 蓝牙耳机气骨传导运动"), "A7Ultra")

    def test_normalizes_bi_goods_to_excel_product(self):
        goods = {
            "goodsId": "1061669750670",
            "goodsName": "【新品上市】JBL Q255 头戴式耳机有线台式电脑电竞游戏吃鸡专用",
            "goodsLink": "http://a.m.taobao.com/i1061669750670.htm",
            "price": "399.00",
            "cateName": "有线游戏耳机",
            "onSaleTime": "2026-06-29",
        }

        product = normalize_bi_goods(goods, "JBL耳机旗舰店")

        self.assertEqual(
            product,
            NewProduct(
                brand="JBL耳机旗舰店",
                on_sale_date=date(2026, 6, 29),
                model="Q255",
                shape="头戴式",
                price="399.00",
                link="http://a.m.taobao.com/i1061669750670.htm",
                selling_point="无",
                source_id="1061669750670",
                raw_name="【新品上市】JBL Q255 头戴式耳机有线台式电脑电竞游戏吃鸡专用",
            ),
        )

    def test_previous_completed_work_week_for_weekend_run(self):
        week = get_previous_completed_work_week(date(2026, 7, 5))

        self.assertEqual(week.monday, date(2026, 6, 29))
        self.assertEqual(week.friday, date(2026, 7, 3))

    def test_previous_completed_work_week_for_monday_run(self):
        week = get_previous_completed_work_week(date(2026, 7, 6))

        self.assertEqual(week.monday, date(2026, 6, 29))
        self.assertEqual(week.friday, date(2026, 7, 3))

    def test_weekly_new_runs_on_weekend_by_default(self):
        self.assertTrue(is_weekly_new_run_day(date(2026, 7, 4)))
        self.assertTrue(is_weekly_new_run_day(date(2026, 7, 5)))
        self.assertFalse(is_weekly_new_run_day(date(2026, 7, 6)))

    def test_weekly_new_run_day_can_be_configured(self):
        self.assertTrue(is_weekly_new_run_day(date(2026, 7, 6), allowed_weekdays=[0]))
        self.assertFalse(is_weekly_new_run_day(date(2026, 7, 5), allowed_weekdays=[0]))


if __name__ == "__main__":
    unittest.main()
