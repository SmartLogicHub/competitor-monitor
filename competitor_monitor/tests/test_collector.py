import json
import unittest

from activity_service import ActivityService
from collector import ProductCollector


class ProductCollectorTest(unittest.TestCase):
    def setUp(self):
        activity = ActivityService({"国补": ["政府补贴"], "超级立减": ["超级立减"]})
        self.collector = ProductCollector(activity)

    def test_extracts_platform_subsidy_price_first(self):
        text = "页面主价格 ￥399 平台加补后 ￥268.52 起 到手价 ￥288"

        self.assertEqual(self.collector.extract_price(text), "268.52")

    def test_extracts_store_discount_price_before_original_price(self):
        text = "优惠前 ￥2999 店铺优惠后 ￥1699 超级爆款"

        self.assertEqual(self.collector.extract_price(text), "1699")

    def test_keeps_price_range_with_slash(self):
        text = "补贴后 ￥268.52-￥305.17 起"

        self.assertEqual(self.collector.extract_price(text), "268.52/305.17")

    def test_falls_back_to_main_price(self):
        text = "商品详情 颜色分类 ￥199.90"

        self.assertEqual(self.collector.extract_price(text), "199.90")

    def test_collects_prices_for_matched_sku_options(self):
        page = FakeSkuPage(
            {
                "Pro2无尽黑 | 千元级二代钛动圈": "305.17",
                "Ultra星芒紫 | 四代金穹钛动圈": "343.36",
                "Ultra无尽黑 | 四代金穹钛动圈": "321.47",
            },
            base_text="政府补贴 超级立减",
        )

        snapshot = self.collector.collect_from_page(page, expected_model="S6S ultra")

        self.assertEqual(snapshot.price, "321.47")
        self.assertEqual(
            page.clicked_options,
            [
                "Ultra星芒紫 | 四代金穹钛动圈",
                "Ultra无尽黑 | 四代金穹钛动圈",
            ],
        )

    def test_returns_no_price_when_expected_model_has_no_sku_match(self):
        page = FakeSkuPage({"黑色": "199.00", "白色": "199.00"})

        snapshot = self.collector.collect_from_page(page, expected_model="S7S Ultra")

        self.assertIsNone(snapshot.price)
        self.assertEqual(page.clicked_options, [])

    def test_collects_prices_from_tmall_initial_sku_data_without_clicking(self):
        page = FakeInitialDataPage(
            build_tmall_initial_sku_html(
                [
                    ("5919063:6536025;1627207:pro-purple", "sku-pro-purple"),
                    ("5919063:6536025;1627207:pro-black", "sku-pro-black"),
                    ("5919063:6536025;1627207:pro-pink", "sku-pro-pink"),
                    ("5919063:3266779;1627207:pro-purple", "sku-package-pro-purple"),
                    ("5919063:6536025;1627207:ultra-purple", "sku-ultra-purple"),
                ],
                {
                    "5919063:6536025": "官方标配 全球TOP1",
                    "5919063:3266779": "套餐一 星迹钻扣",
                    "1627207:pro-purple": "Pro2星芒紫丨千元级二代钛动圈",
                    "1627207:pro-black": "Pro2无尽黑丨千元级二代钛动圈",
                    "1627207:pro-pink": "Pro2玫瑰金丨千元级二代钛动圈",
                    "1627207:ultra-purple": "Ultra星芒紫丨四代金穹钛动圈",
                },
                {
                    "sku-pro-purple": "268.52",
                    "sku-pro-black": "268.52",
                    "sku-pro-pink": "305.17",
                    "sku-package-pro-purple": "308.52",
                    "sku-ultra-purple": "305.24",
                },
            ),
            base_text="政府补贴 超级立减",
        )

        snapshot = self.collector.collect_from_page(page, expected_model="S6S proII")

        self.assertEqual(snapshot.price, "268.52")
        self.assertEqual(page.clicked_options, [])

    def test_initial_sku_data_filters_ultra_art_and_recommendation_for_ultra_model(self):
        page = FakeInitialDataPage(
            build_tmall_initial_sku_html(
                [
                    ("5919063:6536025;1627207:ultra-recommend", "sku-recommend"),
                    ("5919063:6536025;1627207:ultra-purple", "sku-purple"),
                    ("5919063:6536025;1627207:ultra-black", "sku-black"),
                    ("5919063:6536025;1627207:ultra-pink", "sku-pink"),
                    ("5919063:6536025;1627207:ultra-art-white", "sku-art-white"),
                ],
                {
                    "5919063:6536025": "官方标配 全球TOP1",
                    "1627207:ultra-recommend": "推荐购买Ultra版本，声场提升200%",
                    "1627207:ultra-purple": "Ultra星芒紫丨四代金穹钛动圈",
                    "1627207:ultra-black": "Ultra无尽黑丨四代金穹钛动圈",
                    "1627207:ultra-pink": "Ultra玫瑰金丨四代金穹钛动圈",
                    "1627207:ultra-art-white": "Ultra Art星钻白丨原创星钻设计",
                },
                {
                    "sku-recommend": "409.62",
                    "sku-purple": "305.24",
                    "sku-black": "305.24",
                    "sku-pink": "343.36",
                    "sku-art-white": "399.41",
                },
            )
        )

        snapshot = self.collector.collect_from_page(page, expected_model="S6S ultra")

        self.assertEqual(snapshot.price, "305.24")
        self.assertEqual(page.clicked_options, [])

    def test_collects_chinese_numeric_model_price_from_sku_data(self):
        page = FakeInitialDataPage(
            build_tmall_initial_sku_html(
                [
                    ("5919063:6536025;1627207:space-white", "sku-white"),
                    ("5919063:6536025;1627207:space-black", "sku-black"),
                    ("5919063:6536025;1627207:space-case", "sku-case"),
                ],
                {
                    "5919063:6536025": "\u5b98\u65b9\u6807\u914d",
                    "1627207:space-white": "\u592a\u7a7a\u6f2b\u6e382\u3010\u767d\u6a59\u3011\u5347\u7ea7\u6b3e",
                    "1627207:space-black": "\u592a\u7a7a\u6f2b\u6e382\u3010\u9ed1\u7eff\u3011\u5347\u7ea7\u6b3e",
                    "1627207:space-case": "\u592a\u7a7a\u6f2b\u6e382\u3010\u767d\u6a59\u3011\u5347\u7ea7\u6b3e+\u78c1\u5438\u4fdd\u62a4\u5957",
                },
                {
                    "sku-white": "149",
                    "sku-black": "149",
                    "sku-case": "249",
                },
            ),
            base_text="\u5238\u540e \uffe5249",
        )

        snapshot = self.collector.collect_from_page(page, expected_model="\u592a\u7a7a\u6f2b\u6e382")

        self.assertEqual(snapshot.price, "149")
        self.assertEqual(page.clicked_options, [])

    def test_returns_no_price_when_risky_variant_skus_do_not_match_expected_model(self):
        page = FakeSkuPage(
            {
                "\u3010Ultra\u9ed1\u3011\u5f71\u9662\u5168\u666f\u97f3": "124",
                "\u3010\u9876\u914d\u767d\u3011HiFi\u7ea7\u97f3\u8d28": "79.9",
                "\u3010\u81f3\u5c0a\u767d\u3011\u675c\u6bd4\u5168\u666f\u73af\u7ed5": "109.65",
            },
            base_text="\u653f\u5e9c\u8865\u8d34\u91d1\u8fd0A5 \u5e73\u53f0\u52a0\u8865\u540e \uffe579.9 \u8d77",
        )

        snapshot = self.collector.collect_from_page(page, expected_model="A5")

        self.assertIsNone(snapshot.price)
        self.assertEqual(page.clicked_options, [])

    def test_unique_short_model_without_sku_options_can_use_page_default_price(self):
        page = FakeSkuPage(
            {},
            base_text="\u653f\u5e9c\u8865\u8d34\u91d1\u8fd0A5 \u5e73\u53f0\u52a0\u8865\u540e \uffe579.9 \u8d77",
        )

        snapshot = self.collector.collect_from_page(page, expected_model="A5")

        self.assertEqual(snapshot.price, "79.9")
        self.assertEqual(page.clicked_options, [])

    def test_unique_title_confirmed_short_model_with_variant_options_can_use_page_default_price(self):
        page = FakeSkuPage(
            {
                "\u3010\u5347\u7ea7\u6b3e\u3011black": "74.7",
                "\u3010\u6807\u51c6\u6b3e\u3011white": "69.9",
                "\u5b98\u65b9\u6807\u914d": "74.7",
            },
            base_text="\u500d\u601dP1\u84dd\u7259\u8033\u673a \u5e73\u53f0\u52a0\u8865\u540e \uffe574.7 \u8d77",
        )

        snapshot = self.collector.collect_from_page(page, expected_model="P1")

        self.assertEqual(snapshot.price, "74.7")
        self.assertEqual(page.clicked_options, [])

    def test_missing_target_model_on_page_returns_no_price_for_delisted_link(self):
        page = FakeSkuPage(
            {
                "\u3010\u73cd\u73e0\u767d\u3011\u624b\u673a(\u82f9\u679c/\u5b89\u5353)\u25cf\u7535\u8111\u901a\u7528": "439",
                "\u5b98\u65b9\u6807\u914d \u8033\u673a": "439",
            },
            base_text="\u7eff\u8054Q3\u84dd\u7259\u8033\u673a \u578b\u53f7 WS212 \uffe5439",
        )

        snapshot = self.collector.collect_from_page(page, expected_model="T3pro")

        self.assertIsNone(snapshot.price)
        self.assertEqual(page.clicked_options, [])

    def test_strict_sku_mode_without_explicit_match_does_not_use_page_default_price(self):
        page = FakeSkuPage(
            {},
            base_text="\u653f\u5e9c\u8865\u8d34\u91d1\u8fd0A5 \u5e73\u53f0\u52a0\u8865\u540e \uffe579.9 \u8d77",
        )

        snapshot = self.collector.collect_from_page(page, expected_model="A5", allow_fallback_price=False)

        self.assertIsNone(snapshot.price)
        self.assertEqual(page.clicked_options, [])

    def test_short_model_does_not_match_product_title_as_sku_option(self):
        page = FakeSkuPage(
            {
                "\u653f\u5e9c\u8865\u8d34\u91d1\u8fd0A5\u84dd\u7259\u8033\u673a\u6c14\u9aa8\u4f20\u5bfc\u8fd0\u52a8\u4e0d\u5165\u8033\u65e0\u7ebf\u8033\u5939\u5f0f\u63022026\u65b0\u6b3e \u53ef\u5f00\u53d1\u7968": "79.9",
                "\u3010Ultra\u767d\u3011\u5f71\u9662\u5168\u666f\u97f3\u25cf\u8212\u9002\u4e0d\u6f0f\u97f3\u25cfAI\u8d85\u6e05\u901a\u8bdd": "159",
                "\u3010\u9876\u914d\u767d\u3011HiFi\u7ea7\u97f3\u8d28\u2605\u8212\u9002\u4e0d\u6f0f\u97f3\u2605\u957f\u7eed\u822a": "124",
            },
            base_text="\u653f\u5e9c\u8865\u8d34\u91d1\u8fd0A5 \u5e73\u53f0\u52a0\u8865\u540e \uffe579.9 \u8d77",
        )

        snapshot = self.collector.collect_from_page(page, expected_model="A5")

        self.assertIsNone(snapshot.price)
        self.assertEqual(page.clicked_options, [])

    def test_short_base_model_ignores_bundle_options_that_include_model_token(self):
        page = FakeSkuPage(
            {
                "\u3010\u767d\u8272\u3011\u5f71\u9662\u7ea7\u7a7a\u95f4\u97f3\u9891\u2605\u4e91\u611f\u6c14\u56ca": "119",
                "\u3010\u9650\u5b9a\u7ea2\u8272\u3011\u5f71\u9662\u7ea7\u7a7a\u95f4\u97f3\u9891\u2605\u4e91\u611f\u6c14\u56ca": "119",
                "\u3010\u5957\u88c5\u3011S5\u767d\u8272\u8033\u673a+\u8033\u673a\u6536\u7eb3\u888b": "135.1",
                "\u3010\u5957\u88c5\u3011S5\u767d\u8272\u8033\u673a+\u8033\u673a\u6e05\u6d01\u7b14": "135.1",
            },
            base_text="\u7eff\u8054S5\u8033\u673a \u5e97\u94fa\u4f18\u60e0\u540e \uffe5119 \u8d77",
        )

        snapshot = self.collector.collect_from_page(page, expected_model="S5")

        self.assertEqual(snapshot.price, "119")
        self.assertEqual(page.clicked_options, [])

    def test_initial_sku_data_ignores_bundle_dimension_for_base_model(self):
        html = build_tmall_initial_sku_html(
            [
                ("5919063:base;1627207:white", "sku-white"),
                ("5919063:bundle-bag;1627207:white", "sku-bag"),
                ("5919063:bundle-pen;1627207:white", "sku-pen"),
            ],
            {
                "5919063:base": "\u5b98\u65b9\u6807\u914d",
                "5919063:bundle-bag": "\u3010\u5957\u88c5\u3011S5\u767d\u8272\u8033\u673a+\u8033\u673a\u6536\u7eb3\u888b",
                "5919063:bundle-pen": "\u3010\u5957\u88c5\u3011S5\u767d\u8272\u8033\u673a+\u8033\u673a\u6e05\u6d01\u7b14",
                "1627207:white": "\u3010\u767d\u8272\u3011\u5f71\u9662\u7ea7\u7a7a\u95f4\u97f3\u9891\u2605\u4e91\u611f\u6c14\u56ca",
            },
            {
                "sku-white": "119",
                "sku-bag": "135.1",
                "sku-pen": "135.1",
            },
        )

        options = self.collector.extract_initial_sku_price_options(html)

        self.assertEqual([(option.text, option.price) for option in options], [("\u3010\u767d\u8272\u3011\u5f71\u9662\u7ea7\u7a7a\u95f4\u97f3\u9891\u2605\u4e91\u611f\u6c14\u56ca", "119")])


class FakeSkuPage:
    def __init__(self, option_prices, base_text=""):
        self.option_prices = option_prices
        self.base_text = base_text
        self.selected_option = None
        self.clicked_options = []

    def locator(self, selector):
        if selector != "body":
            raise AssertionError(f"unexpected selector: {selector}")
        return FakeBodyLocator(self)

    def get_by_text(self, text, exact=True):
        return FakeTextLocator(self, text)


class FakeInitialDataPage(FakeSkuPage):
    def __init__(self, html, base_text=""):
        super().__init__({}, base_text=base_text)
        self.html = html

    def content(self):
        return self.html


class FakeBodyLocator:
    def __init__(self, page):
        self.page = page

    def inner_text(self, timeout=5000):
        if self.page.selected_option is None:
            return self.page.base_text
        price = self.page.option_prices[self.page.selected_option]
        return f"{self.page.base_text} 平台加补后 ￥{price} 起"

    def evaluate(self, script):
        return list(self.page.option_prices)


class FakeTextLocator:
    def __init__(self, page, text):
        self.page = page
        self.text = text

    @property
    def first(self):
        return self

    def click(self, timeout=5000):
        self.page.selected_option = self.text
        self.page.clicked_options.append(self.text)


def build_tmall_initial_sku_html(skus, vid_names, prices):
    props_by_pid = {}
    for key, name in vid_names.items():
        pid, vid = key.split(":", 1)
        props_by_pid.setdefault(pid, []).append({"vid": vid, "name": name})
    data = {
        "appData": None,
        "loaderData": {
            "home": {
                "data": {
                    "res": {
                        "skuBase": {
                            "skus": [{"propPath": prop_path, "skuId": sku_id} for prop_path, sku_id in skus],
                            "props": [
                                {
                                    "pid": pid,
                                    "name": "套餐类型" if pid == "5919063" else "颜色分类",
                                    "packProp": "true" if pid == "5919063" else "false",
                                    "values": values,
                                }
                                for pid, values in props_by_pid.items()
                            ],
                        },
                        "skuCore": {
                            "sku2info": {
                                sku_id: {"subPrice": {"priceTitle": "平台加补后", "priceText": price}}
                                for sku_id, price in prices.items()
                            }
                        },
                    }
                }
            }
        },
    }
    payload = json.dumps(data, ensure_ascii=False)
    return f"<html><body><script>!(function () {{var a = window.__ICE_APP_CONTEXT__ || {{}};var b = {payload};a.data = b;}})();</script></body></html>"


if __name__ == "__main__":
    unittest.main()
