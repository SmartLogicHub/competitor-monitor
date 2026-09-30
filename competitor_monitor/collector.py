from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from activity_service import ActivityService
from sku_service import match_sku_options, model_tokens, normalize_sku_text, required_exact_model_tokens, summarize_sku_label


@dataclass(frozen=True)
class ProductSnapshot:
    price: str | None
    activities: list[str]
    visible_text: str
    visible_promotion_price: str | None = None
    sku_candidate_price: str | None = None
    promotion_content_ready: bool = False
    promotion_body_reads: int = 1
    model_variant_missing: bool = False
    explicitly_unavailable: bool = False
    target_model_replaced: bool = False


@dataclass(frozen=True)
class SkuPriceOption:
    text: str
    price: str


class ProductCollector:
    DEFAULT_BLOCKED_UNMATCHED_SKU_FALLBACK_MODELS = {"a5"}
    CONTROLLED_MODEL_ALIASES = {
        "动钛圈": ("opendotsone",),
    }

    PRICE_RULES = [
        "平台加补后",
        "店铺优惠后",
        "店铺优惠价",
        "补贴后",
        "到手价",
        "券后价",
        "活动价",
    ]

    def __init__(
        self,
        activity_service: ActivityService,
        blocked_unmatched_sku_fallback_models: list[str] | None = None,
        promotion_content_wait_seconds: float = 10,
        promotion_content_poll_milliseconds: int = 500,
        promotion_price_stable_reads: int = 2,
        sku_price_settle_reads: int = 8,
    ):
        self.activity_service = activity_service
        self.promotion_content_wait_seconds = max(0.0, float(promotion_content_wait_seconds))
        self.promotion_content_poll_milliseconds = max(1, int(promotion_content_poll_milliseconds))
        self.promotion_price_stable_reads = max(2, int(promotion_price_stable_reads))
        self.sku_price_settle_reads = max(2, int(sku_price_settle_reads))
        models = (
            blocked_unmatched_sku_fallback_models
            if blocked_unmatched_sku_fallback_models is not None
            else self.DEFAULT_BLOCKED_UNMATCHED_SKU_FALLBACK_MODELS
        )
        self.blocked_unmatched_sku_fallback_models = {
            normalize_sku_text(model)
            for model in models
            if normalize_sku_text(model)
        }

    def collect_from_page(
        self,
        page,
        expected_model: str | None = None,
        allow_fallback_price: bool = True,
    ) -> ProductSnapshot:
        visible_text, promotion_content_ready, promotion_body_reads = self.wait_for_promotion_content(
            page,
            expected_model=expected_model,
        )
        visible_promotion_price = self.extract_priority_price(visible_text)
        price = self.extract_price(visible_text)
        sku_candidate_price = None
        model_variant_missing = False
        explicitly_unavailable = self.page_is_explicitly_unavailable(visible_text)
        target_model_replaced = bool(
            expected_model and self.page_confirms_different_product(expected_model, visible_text)
        )
        if explicitly_unavailable or target_model_replaced:
            price = None
        elif expected_model:
            model_variant_missing = self.specific_model_variant_is_missing(page, expected_model)
            if not model_variant_missing:
                sku_candidate_price = self.collect_matched_sku_prices(
                    page,
                    expected_model,
                    fallback_price=price,
                    allow_fallback_price=allow_fallback_price,
                    fallback_visible_text=visible_text,
                )
            if (
                visible_promotion_price
                and sku_candidate_price
                and not self.priority_price_is_starting_price(visible_text)
            ):
                price = visible_promotion_price
            else:
                price = sku_candidate_price
        return ProductSnapshot(
            price=price,
            activities=self.activity_service.recognize(visible_text),
            visible_text=visible_text,
            visible_promotion_price=visible_promotion_price,
            sku_candidate_price=sku_candidate_price,
            promotion_content_ready=promotion_content_ready,
            promotion_body_reads=promotion_body_reads,
            model_variant_missing=model_variant_missing,
            explicitly_unavailable=explicitly_unavailable,
            target_model_replaced=target_model_replaced,
        )

    @staticmethod
    def page_is_explicitly_unavailable(visible_text: str) -> bool:
        normalized = re.sub(r"\s+", "", str(visible_text or ""))
        markers = (
            "商品已下架",
            "此商品已下架",
            "商品已经下架",
            "此商品已经下架",
            "宝贝已下架",
            "此宝贝已下架",
            "宝贝已经下架",
            "此宝贝已经下架",
            "商品不存在",
            "宝贝不存在",
            "商品已失效",
            "宝贝已失效",
            "商品已过期",
            "宝贝已过期",
        )
        return any(marker in normalized for marker in markers)

    def wait_for_promotion_content(self, page, expected_model: str | None = None) -> tuple[str, bool, int]:
        max_waits = int(
            math.ceil(
                (self.promotion_content_wait_seconds * 1000) / self.promotion_content_poll_milliseconds
            )
        )
        visible_text = page.locator("body").inner_text(timeout=5000)
        previous_price_candidate = self.ready_price_candidate(page, visible_text, expected_model)
        stable_price_reads = 1 if previous_price_candidate else 0
        for attempt in range(max_waits):
            self.wait_for_promotion_poll(page)
            visible_text = page.locator("body").inner_text(timeout=5000)
            price_candidate = self.ready_price_candidate(page, visible_text, expected_model)
            if price_candidate and price_candidate == previous_price_candidate:
                stable_price_reads += 1
            elif price_candidate:
                previous_price_candidate = price_candidate
                stable_price_reads = 1
            else:
                previous_price_candidate = None
                stable_price_reads = 0
            required_stable_reads = self.required_stable_reads_for_candidate(price_candidate)
            if stable_price_reads >= required_stable_reads:
                return visible_text, True, attempt + 2
        return visible_text, False, max_waits + 1

    def ready_price_candidate(
        self,
        page,
        visible_text: str,
        expected_model: str | None,
    ) -> tuple[str, str] | None:
        promotion_price = self.extract_priority_price(visible_text)
        if promotion_price:
            return ("visible_promotion", promotion_price)
        if expected_model:
            initial_sku_price = self.collect_prices_from_initial_sku_data(page, expected_model)
            if initial_sku_price:
                return ("initial_sku", initial_sku_price)
        return None

    def required_stable_reads_for_candidate(self, candidate: tuple[str, str] | None) -> int:
        if candidate and candidate[0] == "initial_sku":
            return self.sku_price_settle_reads
        return self.promotion_price_stable_reads

    def wait_for_promotion_poll(self, page) -> None:
        try:
            page.wait_for_timeout(self.promotion_content_poll_milliseconds)
        except AttributeError:
            return

    def collect_matched_sku_prices(
        self,
        page,
        expected_model: str,
        fallback_price: str | None = None,
        allow_fallback_price: bool = True,
        fallback_visible_text: str | None = None,
    ) -> str | None:
        initial_data_price = self.collect_prices_from_initial_sku_data(page, expected_model)
        if initial_data_price:
            return initial_data_price

        raw_option_texts = self.extract_sku_option_texts(page)
        option_texts = self.filter_sku_option_texts(expected_model, raw_option_texts)
        if not option_texts:
            if self.page_misses_required_model_tokens(expected_model, fallback_visible_text or ""):
                return None
            return fallback_price if allow_fallback_price else None
        matched_options = match_sku_options(expected_model, option_texts)
        if not matched_options:
            if not allow_fallback_price:
                return None
            if self.page_misses_required_model_tokens(expected_model, fallback_visible_text or ""):
                return None
            if self.should_block_unmatched_sku_fallback(expected_model, option_texts):
                if self.can_use_title_confirmed_non_starting_page_price(
                    expected_model,
                    fallback_price,
                    fallback_visible_text or "",
                ):
                    return fallback_price
                return None
            return fallback_price
        self.select_standard_package_option(page, raw_option_texts)
        prices: list[tuple[str, str]] = []
        for option_text in matched_options:
            if not self.click_sku_option(page, option_text):
                continue
            visible_text = page.locator("body").inner_text(timeout=5000)
            price = self.extract_price(visible_text)
            if price:
                prices.append((summarize_sku_label(expected_model, option_text), price))
        if not prices:
            return None
        return self._lowest_price_text([price for _, price in prices])

    @staticmethod
    def select_standard_package_option(page, option_texts: list[str]) -> bool:
        for option_text in option_texts:
            text = str(option_text or "").strip()
            if not ProductCollector.is_standard_package_option(text):
                continue
            return ProductCollector.click_sku_option(page, text)
        return False

    @staticmethod
    def is_standard_package_option(option_text: str) -> bool:
        normalized = normalize_sku_text(option_text)
        markers = (
            "\u5b98\u65b9\u6807\u914d",
            "\u6807\u914d",
            "\u6807\u51c6\u5957\u9910",
            "\u6807\u51c6\u6b3e",
            "\u57fa\u7840\u5957\u9910",
            "\u57fa\u7840\u6b3e",
        )
        return any(normalize_sku_text(marker) in normalized for marker in markers)

    @staticmethod
    def requires_explicit_sku_confirmation(expected_model: str) -> bool:
        return bool(required_exact_model_tokens(expected_model))

    @staticmethod
    def page_misses_required_model_tokens(expected_model: str, visible_text: str) -> bool:
        exact_tokens = required_exact_model_tokens(expected_model)
        tokens = exact_tokens or model_tokens(expected_model)
        if not tokens:
            return False
        normalized_page = normalize_sku_text(visible_text)
        normalized_model = normalize_sku_text(expected_model)
        aliases = ProductCollector.CONTROLLED_MODEL_ALIASES.get(normalized_model, ())
        if any(alias in normalized_page for alias in aliases):
            return False
        if any(token in normalized_page for token in tokens):
            return False
        if exact_tokens:
            return True
        return not ProductCollector._page_contains_distinctive_chinese_model_part(expected_model, normalized_page)

    @staticmethod
    def page_confirms_different_product(expected_model: str, visible_text: str) -> bool:
        text = str(visible_text or "")
        if not text or not ProductCollector.page_misses_required_model_tokens(expected_model, text):
            return False
        if "参数信息" not in text or not any(marker in text for marker in ("图文详情", "用户评价")):
            return False
        if re.search(r"请登录|登录后|安全验证|滑动验证|访问被拒绝|网络异常", text):
            return False
        model_match = re.search(
            r"(?:^|\n)\s*型号\s*(?:[:：]\s*)?(?:\n|\s+)\s*([^\n￥¥]{1,60})",
            text,
            flags=re.IGNORECASE,
        )
        if not model_match or not normalize_sku_text(model_match.group(1)):
            return False
        return bool(re.search(r"[￥¥]\s*(?:\n\s*)?\d+(?:\.\d+)?", text))

    @staticmethod
    def _page_contains_distinctive_chinese_model_part(expected_model: str, normalized_page: str) -> bool:
        normalized_model = normalize_sku_text(expected_model)
        if not re.search(r"[\u4e00-\u9fff]", normalized_model):
            return False
        generic_descriptors = (
            "\u5934\u6234\u5f0f",
            "\u5165\u8033\u5f0f",
            "\u534a\u5165\u8033",
            "\u5f00\u653e\u5f0f",
            "\u9aa8\u4f20\u5bfc",
            "\u4e3b\u52a8\u964d\u566a",
            "\u964d\u566a",
            "\u84dd\u7259",
            "\u65e0\u7ebf",
            "\u6709\u7ebf",
            "\u8033\u673a",
        )
        distinctive = normalized_model
        for descriptor in generic_descriptors:
            distinctive = distinctive.replace(normalize_sku_text(descriptor), "")
        candidates = [
            part
            for part in re.findall(r"[0-9a-z\u4e00-\u9fff]+", distinctive)
            if len(part) >= 2
        ]
        return any(candidate in normalized_page for candidate in candidates)

    def should_block_unmatched_sku_fallback(self, expected_model: str, option_texts: list[str]) -> bool:
        normalized_model = normalize_sku_text(expected_model)
        return (
            normalized_model in self.blocked_unmatched_sku_fallback_models
            and self.has_risky_variant_options(option_texts)
        )

    def can_use_title_confirmed_non_starting_page_price(
        self,
        expected_model: str,
        fallback_price: str | None,
        visible_text: str,
    ) -> bool:
        if not fallback_price or self.page_misses_required_model_tokens(expected_model, visible_text):
            return False
        priority_price = self.extract_priority_price(visible_text)
        if priority_price != fallback_price:
            return False
        return not self.priority_price_is_starting_price(visible_text)

    @classmethod
    def priority_price_is_starting_price(cls, visible_text: str) -> bool:
        text = re.sub(r"\s+", " ", visible_text or "")
        for keyword in cls.PRICE_RULES:
            position = text.find(keyword)
            if position < 0:
                continue
            after_keyword = text[position + len(keyword) : position + len(keyword) + 64]
            price_match = re.search(r"(?:[\u00a5\uffe5]\s*)?\d+(?:\.\d+)?", after_keyword)
            if not price_match:
                continue
            price_tail = after_keyword[price_match.end() : price_match.end() + 4]
            return bool(re.match(r"\s*\u8d77", price_tail))
        return False

    @staticmethod
    def filter_sku_option_texts(expected_model: str, option_texts: list[str]) -> list[str]:
        filtered: list[str] = []
        seen: set[str] = set()
        for option_text in option_texts:
            text = str(option_text or "").strip()
            if not text or text in seen:
                continue
            if ProductCollector.is_non_product_sku_option(text):
                continue
            if ProductCollector.is_product_title_like_candidate(expected_model, text):
                continue
            if ProductCollector.is_bundle_sku_option_for_base_model(expected_model, text):
                continue
            seen.add(text)
            filtered.append(text)
        return filtered

    @staticmethod
    def is_bundle_sku_option_for_base_model(expected_model: str, option_text: str) -> bool:
        model_text = str(expected_model or "")
        if re.search(r"套装|套餐|礼盒|礼包|组合|保护套|收纳袋|清洁笔|贴纸", model_text, flags=re.IGNORECASE):
            return False
        option = str(option_text or "")
        return bool(re.search(r"套装|套餐|组合|收藏加购|加购|保护套|收纳袋|清洁笔|贴纸|耳机\s*[+＋]|[+＋]\s*耳机", option))

    @staticmethod
    def is_product_title_like_candidate(expected_model: str, option_text: str) -> bool:
        tokens = required_exact_model_tokens(expected_model)
        if not tokens:
            return False
        normalized = re.sub(r"\s+", "", str(option_text or "").casefold())
        if not any(token in normalized for token in tokens):
            return False
        title_markers = (
            "\u84dd\u7259\u8033\u673a",
            "\u65e0\u7ebf\u8033\u673a",
            "\u53ef\u5f00\u53d1\u7968",
            "\u653f\u5e9c\u8865\u8d34",
            "2026\u65b0\u6b3e",
            "2025\u65b0\u6b3e",
        )
        return len(normalized) >= 24 and any(marker in normalized for marker in title_markers)

    @staticmethod
    def has_risky_variant_options(option_texts: list[str]) -> bool:
        risky_keywords = (
            "ultra",
            "pro",
            "max",
            "\u9876\u914d",
            "\u81f3\u5c0a",
            "\u5347\u7ea7",
            "\u7248\u672c",
            "\u7248",
        )
        for option_text in option_texts:
            normalized = str(option_text or "").casefold()
            if any(keyword in normalized for keyword in risky_keywords):
                return True
        return False

    def collect_prices_from_initial_sku_data(self, page, expected_model: str) -> str | None:
        try:
            html = page.content()
        except Exception:
            return None
        options = self.extract_initial_sku_price_options(html, expected_model=expected_model)
        options = [option for option in options if not self.is_non_product_sku_option(option.text)]
        if not options:
            return None

        matched_texts = match_sku_options(expected_model, [option.text for option in options])
        if not matched_texts:
            matched_texts = self.match_variant_sku_options(expected_model, options)
        if not matched_texts:
            return None
        matched_set = set(matched_texts)
        prices = [
            (summarize_sku_label(expected_model, option.text), option.price)
            for option in options
            if option.text in matched_set
        ]
        if not prices:
            return None
        return self._lowest_price_text([price for _, price in prices])

    @staticmethod
    def match_variant_sku_options(expected_model: str, options: list[SkuPriceOption]) -> list[str]:
        normalized_model = normalize_sku_text(expected_model)
        upgrade_markers = ("pro", "ultra")
        requested_upgrade = next((marker for marker in upgrade_markers if marker in normalized_model), None)
        if requested_upgrade:
            return [option.text for option in options if requested_upgrade in normalize_sku_text(option.text)]
        return [
            option.text
            for option in options
            if not any(marker in normalize_sku_text(option.text) for marker in upgrade_markers)
        ]

    @staticmethod
    def is_non_product_sku_option(option_text: str) -> bool:
        normalized = normalize_sku_text(option_text)
        markers = (
            "收藏加购",
            "加购",
            "限量礼赠",
            "礼赠",
            "下单赠送",
            "赠送",
            "赠品",
            "免费试用",
            "试用",
            "权益",
            "联系客服",
            "客服备注",
            "顺丰",
            "次日达",
        )
        return any(normalize_sku_text(marker) in normalized for marker in markers)

    @staticmethod
    def specific_model_variant_is_missing(page, expected_model: str) -> bool:
        required_tokens = ProductCollector.specific_model_variant_tokens(expected_model)
        if not required_tokens:
            return False
        option_texts = ProductCollector.extract_sku_option_texts(page)
        try:
            initial_data = ProductCollector._extract_initial_app_data(page.content())
        except Exception:
            initial_data = None
        sku_resource = ProductCollector._find_sku_resource(initial_data) if initial_data else None
        for prop in (sku_resource or {}).get("skuBase", {}).get("props", []) or []:
            for value in prop.get("values") or []:
                option_texts.append(str(value.get("name") or ""))
        if not any(str(option_text or "").strip() for option_text in option_texts):
            return False
        normalized_options = normalize_sku_text(" ".join(option_texts))
        return not all(token in normalized_options for token in required_tokens)

    def extract_initial_sku_price_options(
        self,
        html: str,
        expected_model: str | None = None,
    ) -> list[SkuPriceOption]:
        data = self._extract_initial_app_data(html)
        if not data:
            return []
        sku_resource = self._find_sku_resource(data)
        if not sku_resource:
            return []

        sku_base = sku_resource.get("skuBase") or {}
        sku_core = sku_resource.get("skuCore") or {}
        sku2info = sku_core.get("sku2info") or {}
        value_names, selected_package_values, required_package_missing = self._build_sku_value_maps(
            sku_base,
            expected_model=expected_model,
        )
        if required_package_missing:
            return []
        options: list[SkuPriceOption] = []
        seen: set[tuple[str, str]] = set()
        for sku in sku_base.get("skus") or []:
            sku_id = str(sku.get("skuId") or "")
            prop_path = str(sku.get("propPath") or "")
            if not sku_id or not prop_path:
                continue
            prop_values = [part for part in prop_path.split(";") if part]
            if selected_package_values and not any(part in selected_package_values for part in prop_values):
                continue
            product_values = [part for part in prop_values if part not in selected_package_values]
            product_labels = [value_names.get(part, part) for part in product_values]
            all_labels = [value_names.get(part, part) for part in prop_values]
            text = " / ".join(product_labels or all_labels)
            price = self._extract_sku_price_text(sku2info.get(sku_id) or {})
            if not text or not price:
                continue
            key = (text, price)
            if key in seen:
                continue
            seen.add(key)
            options.append(SkuPriceOption(text=text, price=price))
        return options

    @staticmethod
    def _extract_initial_app_data(html: str) -> dict | None:
        text = html or ""
        marker = "var b = "
        position = text.find(marker)
        if position < 0:
            return None
        start = text.find("{", position)
        if start < 0:
            return None
        end = ProductCollector._find_balanced_json_end(text, start)
        if end is None:
            return None
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _find_balanced_json_end(text: str, start: int) -> int | None:
        level = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                level += 1
            elif char == "}":
                level -= 1
                if level == 0:
                    return index + 1
        return None

    @staticmethod
    def _find_sku_resource(data) -> dict | None:
        if isinstance(data, dict):
            if isinstance(data.get("skuBase"), dict) and isinstance(data.get("skuCore"), dict):
                return data
            for value in data.values():
                found = ProductCollector._find_sku_resource(value)
                if found:
                    return found
        elif isinstance(data, list):
            for value in data:
                found = ProductCollector._find_sku_resource(value)
                if found:
                    return found
        return None

    @classmethod
    def _build_sku_value_maps(
        cls,
        sku_base: dict,
        expected_model: str | None = None,
    ) -> tuple[dict[str, str], set[str], bool]:
        value_names: dict[str, str] = {}
        standard_package_values: set[str] = set()
        package_values: list[tuple[str, str]] = []
        for prop in sku_base.get("props") or []:
            pid = str(prop.get("pid") or "")
            is_package_prop = str(prop.get("packProp") or "").lower() == "true" or "套餐" in str(prop.get("name") or "")
            values = prop.get("values") or []
            package_value_keys: list[str] = []
            for value in values:
                vid = str(value.get("vid") or "")
                name = str(value.get("name") or "")
                if not pid or not vid:
                    continue
                key = f"{pid}:{vid}"
                value_names[key] = name
                if is_package_prop:
                    package_value_keys.append(key)
                    package_values.append((key, name))
                    if "官方标配" in name:
                        standard_package_values.add(key)
            if is_package_prop and not standard_package_values and package_value_keys:
                standard_package_values.add(package_value_keys[0])
        gift_package_values = cls._matching_gift_package_values(expected_model, package_values)
        required_package_missing = cls.requires_specific_package(expected_model) and not gift_package_values
        return value_names, gift_package_values or standard_package_values, required_package_missing

    @staticmethod
    def _matching_gift_package_values(
        expected_model: str | None,
        package_values: list[tuple[str, str]],
    ) -> set[str]:
        normalized_model = normalize_sku_text(expected_model or "")
        gift_markers = ("礼盒", "礼包", "套装", "套餐")
        if not ProductCollector.requires_specific_package(expected_model):
            return set()
        gift_candidates = [
            (key, normalize_sku_text(name))
            for key, name in package_values
            if any(normalize_sku_text(marker) in normalize_sku_text(name) for marker in gift_markers)
        ]
        if not gift_candidates:
            return set()
        model_numbers = re.findall(r"\d{2,}", normalized_model)
        if model_numbers:
            numbered = [
                key
                for key, name in gift_candidates
                if all(number in name for number in model_numbers)
            ]
            if numbered:
                return set(numbered)
        if len(gift_candidates) == 1:
            return {gift_candidates[0][0]}
        return set()

    @staticmethod
    def requires_specific_package(expected_model: str | None) -> bool:
        normalized_model = normalize_sku_text(expected_model or "")
        return any(
            normalize_sku_text(marker) in normalized_model
            for marker in ("礼盒", "礼包", "套装", "套餐")
        )

    @staticmethod
    def specific_model_variant_tokens(expected_model: str) -> list[str]:
        if not ProductCollector.requires_specific_package(expected_model):
            return []
        normalized_model = normalize_sku_text(expected_model)
        tokens = list(re.findall(r"\d{2,}", normalized_model))
        tokens.extend(
            normalize_sku_text(marker)
            for marker in ("礼盒", "礼包", "套装", "套餐")
            if normalize_sku_text(marker) in normalized_model
        )
        return list(dict.fromkeys(tokens))

    @staticmethod
    def _extract_sku_price_text(sku_info: dict) -> str | None:
        price_blocks = [sku_info.get("subPrice") or {}, sku_info.get("price") or {}]
        for block in price_blocks:
            price_text = str(block.get("priceText") or "")
            numbers = re.findall(r"\d+(?:\.\d+)?", price_text)
            if len(numbers) >= 2:
                return f"{numbers[0]}/{numbers[1]}"
            if len(numbers) == 1:
                return numbers[0]
        return None

    @staticmethod
    def _lowest_price_text(price_values: list[str]) -> str | None:
        candidates: list[tuple[Decimal, str]] = []
        for value in price_values:
            for number in re.findall(r"\d+(?:\.\d+)?", str(value or "")):
                try:
                    candidates.append((Decimal(number), number))
                except InvalidOperation:
                    continue
        if not candidates:
            return None
        return min(candidates, key=lambda item: item[0])[1]

    @staticmethod
    def extract_sku_option_texts(page) -> list[str]:
        script = """
        () => {
            const root = document.querySelector(
                '[class*="GeneralSkuPanel"], [class*="skuWrapper"], [class*="Sku"], [class*="sku"]'
            ) || document.body;
            const nodes = Array.from(root.querySelectorAll(
                'button,[role="button"],li,a,div,span'
            ));
            const seen = new Set();
            const result = [];
            for (const node of nodes) {
                const rect = node.getBoundingClientRect();
                const text = (node.innerText || node.textContent || '').trim().replace(/\\s+/g, ' ');
                if (!text || text.length < 2 || text.length > 80 || text.includes('￥')) continue;
                if (rect.width <= 0 || rect.height <= 0) continue;
                const className = String(node.className || '');
                const role = node.getAttribute('role') || '';
                const interactive = node.tagName === 'BUTTON'
                    || node.tagName === 'A'
                    || node.tagName === 'LI'
                    || role === 'button'
                    || /sku|spec|prop|select|valueitem/i.test(className);
                if (!interactive) continue;
                if (!seen.has(text)) {
                    seen.add(text);
                    result.push(text);
                }
            }
            return result;
        }
        """
        try:
            values = page.locator("body").evaluate(script)
        except Exception:
            return []
        return [str(value).strip() for value in values if str(value).strip()]

    @staticmethod
    def click_sku_option(page, option_text: str) -> bool:
        candidates = [option_text]
        short_label = re.split(r"[|｜/]", option_text, maxsplit=1)[0].strip()
        if short_label and short_label != option_text:
            candidates.append(short_label)
        for text in candidates:
            try:
                page.get_by_text(text, exact=True).first.click(timeout=5000)
                if hasattr(page, "wait_for_timeout"):
                    page.wait_for_timeout(500)
                return True
            except Exception:
                continue
        return False

    def extract_price(self, visible_text: str) -> str | None:
        price = self.extract_priority_price(visible_text)
        if price:
            return price
        return self._extract_main_price(re.sub(r"\s+", " ", visible_text or ""))

    def extract_priority_price(self, visible_text: str) -> str | None:
        text = re.sub(r"\s+", " ", visible_text or "")
        for keyword in self.PRICE_RULES:
            price = self._extract_price_after_keyword(text, keyword)
            if price:
                return price
        return None

    @staticmethod
    def _extract_price_after_keyword(text: str, keyword: str) -> str | None:
        pattern = rf"{re.escape(keyword)}[^0-9￥¥]{{0,20}}[￥¥]?\s*(\d+(?:\.\d+)?)(?:\s*[-~至/]\s*[￥¥]?\s*(\d+(?:\.\d+)?))?\s*起?"
        match = re.search(pattern, text)
        if not match:
            return None
        first, second = match.group(1), match.group(2)
        return f"{first}/{second}" if second else first

    @staticmethod
    def _extract_main_price(text: str) -> str | None:
        prices = re.findall(r"[￥¥]\s*(\d+(?:\.\d+)?)", text)
        return prices[0] if prices else None
