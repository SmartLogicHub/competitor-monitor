from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from browser_service import build_browser_launch_options, build_context_options, random_delay
from credential_service import load_bi_credentials
from date_service import WorkWeek
from new_product_service import NewProduct, filter_products_for_week, is_relevant_audio_product, normalize_bi_goods


DEFAULT_BI_LOGIN_URL = "https://mbz.ecbis.cn/login"
DEFAULT_BI_NEW_MONITORING_URL = "https://mbz.ecbis.cn/workTable/newMonitoring"
DEFAULT_BI_API_BASE_URL = "https://biplugs.ecbis.cn"
DEFAULT_PLATFORM = "TX"
SHOP_TASK_ENDPOINT = "/prod/newGoodsMonitor/shopTaskList"
NEW_GOODS_ENDPOINT = "/prod/newGoodsMonitor/newGoodsList"


class BIServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class BICollectResult:
    products: list[NewProduct]
    total_shop_count: int
    queried_shop_count: int
    total_goods_count: int


def build_week_payload(week: WorkWeek, platform: str = DEFAULT_PLATFORM, days_type: int = 7) -> dict[str, Any]:
    return {
        "platform": platform,
        "startDate": week.monday.strftime("%Y-%m-%d"),
        "endDate": week.friday.strftime("%Y-%m-%d"),
        "daysType": days_type,
    }


def normalize_shop_goods(shop: dict[str, Any], rows: Iterable[dict[str, Any]], week: WorkWeek) -> list[NewProduct]:
    shop_name = str(shop.get("shopName") or shop.get("name") or "").strip()
    products = [normalize_bi_goods(row, shop_name) for row in rows]
    return [product for product in filter_products_for_week(products, week) if is_relevant_audio_product(product)]


def extract_response_data(response: dict[str, Any], endpoint: str) -> list[dict[str, Any]]:
    if not isinstance(response, dict):
        raise BIServiceError(f"{endpoint} 返回格式不是 JSON 对象")
    if response.get("success") is False:
        raise BIServiceError(f"{endpoint} 返回失败：{response.get('message') or response.get('msg') or response}")
    data = response.get("data")
    if data is None and isinstance(response.get("result"), list):
        data = response["result"]
    if not isinstance(data, list):
        raise BIServiceError(f"{endpoint} 返回 data 不是列表")
    return data


def collect_bi_new_products(config: dict[str, Any], week: WorkWeek, logger=None) -> BICollectResult:
    with BINewProductClient(config, logger=logger) as client:
        return client.collect_week_products(week)


def wait_until_not_login_page(
    page,
    is_login_page,
    timeout_seconds: int = 60,
    sleep_seconds: float = 1,
    sleep_fn=time.sleep,
) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not is_login_page(page):
            return True
        sleep_fn(sleep_seconds)
    return not is_login_page(page)


class BINewProductClient:
    def __init__(self, config: dict[str, Any] | None = None, logger=None):
        self.config = config or {}
        self.logger = logger
        self.timeout_ms = int(self.config.get("timeout_ms", 30000))
        self.headless = bool(self.config.get("headless", False))
        self.login_url = self.config.get("bi_login_url", DEFAULT_BI_LOGIN_URL)
        self.new_monitoring_url = self.config.get("bi_new_monitoring_url", DEFAULT_BI_NEW_MONITORING_URL)
        self.api_base_url = str(self.config.get("bi_api_base_url", DEFAULT_BI_API_BASE_URL)).rstrip("/")
        self.platform = self.config.get("bi_platform", DEFAULT_PLATFORM)
        self.profile_dir = Path(
            self.config.get("bi_browser_user_data_dir")
            or self.config.get("browser_user_data_dir", "competitor_monitor/browser_profile_bi")
        )
        self._playwright = None
        self._context = None
        self._page = None

    def __enter__(self):
        try:
            from rebrowser_playwright.sync_api import sync_playwright
        except ModuleNotFoundError as exc:
            raise BIServiceError("Missing rebrowser-playwright. Install with: pip install rebrowser-playwright") from exc
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        launch_options = {
            "headless": self.headless,
            "timeout": self.timeout_ms,
            **build_browser_launch_options(self.config),
            **build_context_options(self.config),
        }
        self._context = self._playwright.chromium.launch_persistent_context(str(self.profile_dir), **launch_options)
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._context:
            self._context.close()
        if self._playwright:
            self._playwright.stop()

    def collect_week_products(self, week: WorkWeek) -> BICollectResult:
        page = self._ensure_page()
        self.ensure_logged_in(page)
        payload = build_week_payload(week, platform=self.platform)
        shop_response = self.post_json(page, SHOP_TASK_ENDPOINT, payload)
        shops = extract_response_data(shop_response, SHOP_TASK_ENDPOINT)
        target_keywords = [str(item).strip() for item in self.config.get("bi_target_shop_keywords", []) if str(item).strip()]
        queried_shops = [shop for shop in shops if self._should_query_shop(shop, target_keywords)]

        all_products: list[NewProduct] = []
        total_goods_count = 0
        for shop in queried_shops:
            shop_id = str(shop.get("shopId") or shop.get("id") or "").strip()
            if not shop_id:
                continue
            goods_payload = {**payload, "shopId": shop_id}
            goods_response = self.post_json(page, NEW_GOODS_ENDPOINT, goods_payload)
            goods_rows = extract_response_data(goods_response, NEW_GOODS_ENDPOINT)
            total_goods_count += len(goods_rows)
            all_products.extend(normalize_shop_goods(shop, goods_rows, week))
            self._log_info(f"BI 上新店铺 {shop.get('shopName')} 原始 {len(goods_rows)} 条，周期内 {len(all_products)} 条累计")
            self._wait_between_requests()

        return BICollectResult(
            products=all_products,
            total_shop_count=len(shops),
            queried_shop_count=len(queried_shops),
            total_goods_count=total_goods_count,
        )

    def ensure_logged_in(self, page) -> None:
        page.goto(self.new_monitoring_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        self._wait_for_page(page)
        if not self._is_login_page(page):
            return
        credentials = load_bi_credentials(self.config)
        if credentials is None:
            raise BIServiceError(
                "BI 登录状态已失效，请设置 BI_USER/BI_PASSWORD 环境变量，"
                "或在本地凭据文件中保存账号密码后重试"
            )
        self._fill_login_form(page, credentials.username, credentials.password)
        self._wait_for_page(page, timeout_ms=max(self.timeout_ms, 60000))
        if not wait_until_not_login_page(page, self._is_login_page, timeout_seconds=60):
            raise BIServiceError("BI 自动登录后仍停留在登录页，请检查账号密码或是否需要人工验证")
        page.goto(self.new_monitoring_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        self._wait_for_page(page)

    def post_json(self, page, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.api_base_url}{endpoint}"
        result = page.evaluate(
            """
            async ({url, payload}) => {
              const resp = await fetch(url, {
                method: 'POST',
                credentials: 'include',
                headers: {
                  'accept': 'application/json, text/plain, */*',
                  'content-type': 'application/json;charset=UTF-8',
                  'x-requested-with': 'XMLHttpRequest'
                },
                body: JSON.stringify(payload)
              });
              const text = await resp.text();
              let parsed;
              try {
                parsed = JSON.parse(text);
              } catch (error) {
                parsed = {parseError: String(error), textHead: text.slice(0, 500)};
              }
              return {status: resp.status, ok: resp.ok, parsed};
            }
            """,
            {"url": url, "payload": payload},
        )
        if not result.get("ok"):
            raise BIServiceError(f"{endpoint} 请求失败，HTTP {result.get('status')}：{result.get('parsed')}")
        parsed = result.get("parsed")
        if isinstance(parsed, dict) and parsed.get("parseError"):
            raise BIServiceError(f"{endpoint} 返回不是有效 JSON：{parsed.get('textHead')}")
        return parsed

    def _ensure_page(self):
        if self._page is None:
            raise BIServiceError("BI 浏览器上下文尚未启动")
        return self._page

    def _fill_login_form(self, page, username: str, password: str) -> None:
        self._log_info("BI 登录状态失效，正在重新登录")
        inputs = page.locator("input.login-form__input:visible")
        if inputs.count() < 2:
            inputs = page.locator("input:visible")
        inputs.nth(0).fill(username, timeout=self.timeout_ms)
        inputs.nth(1).fill(password, timeout=self.timeout_ms)
        states = self._login_checkbox_states(page)
        boxes = page.locator("form.login-form label.el-checkbox:visible .el-checkbox__inner")
        for index, checked in enumerate(states[:2]):
            if not checked:
                boxes.nth(index).click(timeout=self.timeout_ms)
                time.sleep(0.2)
        final_states = self._login_checkbox_states(page)
        if len(final_states) < 2 or not all(final_states[:2]):
            raise BIServiceError(f"BI 登录页勾选框未全部选中，当前状态：{final_states}")
        button = page.locator("form.login-form .login-form__ft .x-button:visible", has_text="登录").first
        button.click(timeout=self.timeout_ms)

    @staticmethod
    def _login_checkbox_states(page) -> list[bool]:
        return page.evaluate(
            """
            () => Array.from(document.querySelectorAll('form.login-form label.el-checkbox'))
              .filter(label => {
                const rect = label.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
              })
              .slice(0, 2)
              .map(label => {
                const input = label.querySelector('input');
                return input ? input.checked : false;
              })
            """
        )

    @staticmethod
    def _is_login_page(page) -> bool:
        try:
            return "/login" in page.url and page.locator("input[type='password']:visible").first.is_visible(timeout=800)
        except Exception:
            return False

    def _wait_for_page(self, page, timeout_ms: int | None = None) -> None:
        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms or self.timeout_ms)
        except Exception:
            pass

    def _wait_between_requests(self) -> None:
        min_delay = float(self.config.get("bi_min_delay_seconds", 1))
        max_delay = float(self.config.get("bi_max_delay_seconds", 3))
        random_delay(min_delay, max_delay)

    @staticmethod
    def _should_query_shop(shop: dict[str, Any], target_keywords: list[str]) -> bool:
        if target_keywords:
            shop_name = str(shop.get("shopName") or "")
            return any(keyword in shop_name for keyword in target_keywords)
        try:
            return int(shop.get("newCount") or 0) > 0
        except (TypeError, ValueError):
            return True

    def _log_info(self, message: str) -> None:
        if self.logger:
            self.logger.info("%s %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message)
