import unittest
from datetime import date

from bi_service import build_week_payload, normalize_shop_goods, wait_until_not_login_page
from date_service import WorkWeek
from new_product_service import NewProduct


class BIServiceTest(unittest.TestCase):
    def test_builds_week_payload_for_excel_period(self):
        week = WorkWeek(monday=date(2026, 6, 29), friday=date(2026, 7, 3))

        payload = build_week_payload(week)

        self.assertEqual(
            payload,
            {
                "platform": "TX",
                "startDate": "2026-06-29",
                "endDate": "2026-07-03",
                "daysType": 7,
            },
        )

    def test_normalizes_shop_goods_response_and_filters_week(self):
        week = WorkWeek(monday=date(2026, 6, 29), friday=date(2026, 7, 3))
        shop = {"shopName": "索尼影音旗舰店"}
        rows = [
            {
                "goodsId": "1",
                "goodsName": "Sony/索尼 LinkBuds Clip 耳夹耳机蓝牙开放式运动跑步",
                "goodsLink": "https://example.com/clip",
                "price": "999.00",
                "cateName": "蓝牙耳机",
                "onSaleTime": "2026-06-30",
            },
            {
                "goodsId": "2",
                "goodsName": "旧周期商品",
                "goodsLink": "https://example.com/old",
                "price": "199.00",
                "cateName": "蓝牙耳机",
                "onSaleTime": "2026-06-20",
            },
            {
                "goodsId": "3",
                "goodsName": "十度磁吸充电宝适用苹果17无线超薄小巧",
                "goodsLink": "https://example.com/power",
                "price": "316.00",
                "cateName": "移动电源",
                "onSaleTime": "2026-06-30",
            },
            {
                "goodsId": "4",
                "goodsName": "倍思适用苹果17充电线iPhone16ProMax数据线耳机Airpods4",
                "goodsLink": "https://example.com/cable",
                "price": "24.90",
                "cateName": "数据线",
                "onSaleTime": "2026-06-30",
            },
        ]

        products = normalize_shop_goods(shop, rows, week)

        self.assertEqual(
            products,
            [
                NewProduct(
                    brand="索尼影音旗舰店",
                    on_sale_date=date(2026, 6, 30),
                    model="LinkBuds Clip",
                    shape="耳夹式",
                    price="999.00",
                    link="https://example.com/clip",
                    selling_point="无",
                    source_id="1",
                    raw_name="Sony/索尼 LinkBuds Clip 耳夹耳机蓝牙开放式运动跑步",
                )
            ],
        )

    def test_waits_until_login_page_finishes(self):
        states = iter([True, True, False])
        sleeps = []

        finished = wait_until_not_login_page(
            page=object(),
            is_login_page=lambda _page: next(states),
            timeout_seconds=5,
            sleep_seconds=1,
            sleep_fn=sleeps.append,
        )

        self.assertTrue(finished)
        self.assertEqual(sleeps, [1, 1])


if __name__ == "__main__":
    unittest.main()
