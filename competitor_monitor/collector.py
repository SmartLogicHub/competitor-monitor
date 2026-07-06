from __future__ import annotations

import json
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


@dataclass(frozen=True)
class SkuPriceOption:
    text: str
    price: str


class ProductCollector:
    DEFAULT_BLOCKED_UNMATCHED_SKU_FALLBACK_MODELS = {"a5"}

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
    ):
        self.activity_service = activity_service
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
        visible_text = page.locator("body").inner_text(timeout=5000)
        price = self.extract_price(visible_text)
        if expected_model:
            price = self.collect_matched_sku_prices(
                page,
                expected_model,
                fallback_price=price,
                allow_fallback_price=allow_fallback_price,
                fallback_visible_text=visible_text,
            )
            visible_text = page.locator("body").inner_text(timeout=5000)
        return ProductSnapshot(
            price=price,
            activities=self.activity_service.recognize(visible_text),
            visible_text=visible_text,
        )

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

        option_texts = self.filter_sku_option_texts(expected_model, self.extract_sku_option_texts(page))
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
                return None
            return fallback_price
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
    def requires_explicit_sku_confirmation(expected_model: str) -> bool:
        return bool(required_exact_model_tokens(expected_model))

    @staticmethod
    def page_misses_required_model_tokens(expected_model: str, visible_text: str) -> bool:
        tokens = required_exact_model_tokens(expected_model) or model_tokens(expected_model)
        if not tokens:
            return False
        normalized_page = normalize_sku_text(visible_text)
        return not any(token in normalized_page for token in tokens)

    def should_block_unmatched_sku_fallback(self, expected_model: str, option_texts: list[str]) -> bool:
        normalized_model = normalize_sku_text(expected_model)
        return (
            normalized_model in self.blocked_unmatched_sku_fallback_models
            and self.has_risky_variant_options(option_texts)
        )

    @staticmethod
    def filter_sku_option_texts(expected_model: str, option_texts: list[str]) -> list[str]:
        filtered: list[str] = []
        seen: set[str] = set()
        for option_text in option_texts:
            text = str(option_text or "").strip()
            if not text or text in seen:
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
        options = self.extract_initial_sku_price_options(html)
        if not options:
            return None

        matched_texts = match_sku_options(expected_model, [option.text for option in options])
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

    def extract_initial_sku_price_options(self, html: str) -> list[SkuPriceOption]:
        data = self._extract_initial_app_data(html)
        if not data:
            return []
        sku_resource = self._find_sku_resource(data)
        if not sku_resource:
            return []

        sku_base = sku_resource.get("skuBase") or {}
        sku_core = sku_resource.get("skuCore") or {}
        sku2info = sku_core.get("sku2info") or {}
        value_names, standard_package_values = self._build_sku_value_maps(sku_base)
        options: list[SkuPriceOption] = []
        seen: set[tuple[str, str]] = set()
        for sku in sku_base.get("skus") or []:
            sku_id = str(sku.get("skuId") or "")
            prop_path = str(sku.get("propPath") or "")
            if not sku_id or not prop_path:
                continue
            prop_values = [part for part in prop_path.split(";") if part]
            if standard_package_values and not any(part in standard_package_values for part in prop_values):
                continue
            product_values = [part for part in prop_values if part not in standard_package_values]
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

    @staticmethod
    def _build_sku_value_maps(sku_base: dict) -> tuple[dict[str, str], set[str]]:
        value_names: dict[str, str] = {}
        standard_package_values: set[str] = set()
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
                    if "官方标配" in name:
                        standard_package_values.add(key)
            if is_package_prop and not standard_package_values and package_value_keys:
                standard_package_values.add(package_value_keys[0])
        return value_names, standard_package_values

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
