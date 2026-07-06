import unittest

from sku_service import match_sku_options, normalize_sku_text, summarize_sku_label


class SkuServiceTest(unittest.TestCase):
    def test_normalizes_pro_roman_numerals_to_digit(self):
        self.assertEqual(normalize_sku_text("S6S proII"), "s6spro2")
        self.assertEqual(normalize_sku_text("S6S ProⅡ"), "s6spro2")

    def test_matches_pro2_options_for_excel_proii_model(self):
        options = [
            "Pro2无尽黑 | 千元级二代钛动圈★声波聚焦防漏音",
            "Pro2玫瑰金 | 千元级二代钛动圈★声波聚焦防漏音",
            "Ultra星芒紫 | 四代金穹钛动圈★轻柔舒适不夹耳",
        ]

        matches = match_sku_options("S6S proII", options)

        self.assertEqual(
            matches,
            [
                "Pro2无尽黑 | 千元级二代钛动圈★声波聚焦防漏音",
                "Pro2玫瑰金 | 千元级二代钛动圈★声波聚焦防漏音",
            ],
        )

    def test_matches_ultra_options_without_matching_pro2_options(self):
        options = [
            "Pro2无尽黑 | 千元级二代钛动圈★声波聚焦防漏音",
            "Ultra星芒紫 | 四代金穹钛动圈★轻柔舒适不夹耳",
            "Ultra无尽黑 | 四代金穹钛动圈★轻柔舒适不夹耳",
        ]

        matches = match_sku_options("S6S ultra", options)

        self.assertEqual(
            matches,
            [
                "Ultra星芒紫 | 四代金穹钛动圈★轻柔舒适不夹耳",
                "Ultra无尽黑 | 四代金穹钛动圈★轻柔舒适不夹耳",
            ],
        )

    def test_matches_chinese_model_with_numeric_suffix(self):
        options = [
            "\u592a\u7a7a\u6f2b\u6e382\u3010\u767d\u6a59\u3011\u5347\u7ea7\u6b3e",
            "\u592a\u7a7a\u6f2b\u6e382\u3010\u9ed1\u7eff\u3011\u5347\u7ea7\u6b3e",
            "\u592a\u7a7a\u6f2b\u6e383\u3010\u767d\u6a59\u3011\u5347\u7ea7\u6b3e",
        ]

        matches = match_sku_options("\u592a\u7a7a\u6f2b\u6e382", options)

        self.assertEqual(matches, options[:2])

    def test_matches_short_alphanumeric_model_when_token_is_explicit(self):
        options = [
            "A3 \u9876\u914d\u7248",
            "A5 \u5b98\u65b9\u6807\u914d",
        ]

        self.assertEqual(match_sku_options("A5", options), ["A5 \u5b98\u65b9\u6807\u914d"])

    def test_matches_base_short_model_without_pop_or_limited_variants(self):
        options = [
            "[R1] brown",
            "[R1] black",
            "[R1 Pop] white",
            "[R1\u9650\u5b9a\u7248] black",
        ]

        self.assertEqual(match_sku_options("R1\u590d\u53e4\u5934\u6234\u5f0f", options), options[:2])

    def test_base_model_does_not_match_explicit_upgrade_or_package_options(self):
        options = [
            "S5 \u5b98\u65b9\u6807\u914d",
            "S5 \u5347\u7ea7\u6b3e",
            "S5 Pro \u7248",
            "S5\u5957\u88c5+\u8033\u673a\u6e05\u6d01\u7b14",
        ]

        self.assertEqual(match_sku_options("S5", options), ["S5 \u5b98\u65b9\u6807\u914d"])

    def test_returns_empty_when_no_confident_model_token_matches(self):
        options = ["黑色", "白色", "官方标配"]

        self.assertEqual(match_sku_options("S7S Ultra", options), [])

    def test_summarizes_sku_label_by_removing_matched_model_token(self):
        self.assertEqual(summarize_sku_label("S6S ultra", "Ultra星芒紫 | 四代金穹钛动圈"), "星芒紫")
        self.assertEqual(summarize_sku_label("S6S proII", "Pro2无尽黑 | 千元级二代钛动圈"), "无尽黑")


if __name__ == "__main__":
    unittest.main()
