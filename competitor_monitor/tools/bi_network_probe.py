from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

from rebrowser_playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from rebrowser_playwright.sync_api import sync_playwright


URL = "https://mbz.ecbis.cn/workTable/newMonitoring"
DEFAULT_PROFILE = "competitor_monitor/browser_profile_bi_probe"
DEFAULT_OUTPUT = "competitor_monitor/logs/bi_network_repro_test.json"


def wait_load(page, timeout: int = 15000) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
    except PlaywrightTimeoutError:
        pass


def is_login_page(page) -> bool:
    try:
        return "/login" in page.url and page.locator("input[type='password']:visible").first.is_visible(timeout=800)
    except Exception:
        return False


def login_if_needed(page, username: str, password: str) -> bool:
    if not is_login_page(page):
        return False
    print("login_required")
    inputs = page.locator("input.login-form__input:visible")
    inputs.nth(0).fill(username, timeout=5000)
    inputs.nth(1).fill(password, timeout=5000)

    boxes = page.locator("form.login-form label.el-checkbox:visible .el-checkbox__inner")
    states = page.evaluate(
        """
        () => Array.from(document.querySelectorAll('form.login-form label.el-checkbox'))
          .filter(l => { const r = l.getBoundingClientRect(); return r.width > 0 && r.height > 0; })
          .slice(0,2).map(l => l.querySelector('input').checked)
        """
    )
    for index, checked in enumerate(states):
        if not checked:
            boxes.nth(index).click(timeout=5000)
            time.sleep(0.2)

    final_states = page.evaluate(
        """
        () => Array.from(document.querySelectorAll('form.login-form label.el-checkbox'))
          .filter(l => { const r = l.getBoundingClientRect(); return r.width > 0 && r.height > 0; })
          .slice(0,2).map(l => l.querySelector('input').checked)
        """
    )
    print("login_checkbox_states", final_states)
    page.locator("form.login-form .login-form__ft .x-button:visible", has_text="\u767b\u5f55").first.click(timeout=5000)
    wait_load(page, 25000)
    for _ in range(60):
        if not is_login_page(page):
            print("login_ok", page.url)
            return True
        time.sleep(1)
    raise RuntimeError("login did not leave login page")


def run_probe() -> dict:
    username = os.environ.get("BI_USER", "")
    password = os.environ.get("BI_PASSWORD", "")
    if not username or not password:
        raise RuntimeError("BI_USER and BI_PASSWORD environment variables are required")

    profile_dir = os.environ.get("BI_PROFILE_DIR", DEFAULT_PROFILE)
    output_path = Path(os.environ.get("BI_PROBE_OUTPUT", DEFAULT_OUTPUT))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(Path(profile_dir).resolve()),
            channel="chrome",
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        page = context.pages[0] if context.pages else context.new_page()
        captured: list[dict] = []

        def on_request(request) -> None:
            parsed = urlparse(request.url)
            if parsed.path.startswith("/prod/newGoodsMonitor/"):
                captured.append(
                    {
                        "url": request.url,
                        "path": parsed.path,
                        "method": request.method,
                        "post_data": request.post_data,
                        "headers_subset": {
                            key: value
                            for key, value in request.headers.items()
                            if key.lower()
                            in {
                                "accept",
                                "content-type",
                                "referer",
                                "user-agent",
                                "x-requested-with",
                                "authorization",
                                "token",
                            }
                        },
                        "resource_type": request.resource_type,
                    }
                )

        page.on("request", on_request)
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        wait_load(page)
        login_if_needed(page, username, password)
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        wait_load(page)
        page.wait_for_timeout(8000)
        print("page_ready", page.url, page.title())

        for shop in ["sanag\u585e\u90a3\u65d7\u8230\u5e97", "JBL\u8033\u673a\u65d7\u8230\u5e97"]:
            locator = page.get_by_text(shop, exact=True)
            if locator.count():
                locator.first.click(timeout=5000)
                print("clicked_shop", shop)
                wait_load(page, 10000)
                page.wait_for_timeout(2000)
            else:
                print("shop_not_found", shop)

        repro = page.evaluate(
            """
            async () => {
              async function postJson(path, payload) {
                const resp = await fetch(path, {
                  method: 'POST',
                  credentials: 'include',
                  headers: {
                    'content-type': 'application/json;charset=UTF-8',
                    'accept': 'application/json, text/plain, */*'
                  },
                  body: JSON.stringify(payload)
                });
                const text = await resp.text();
                let parsed;
                try { parsed = JSON.parse(text); } catch (e) { parsed = {parseError: String(e), textHead: text.slice(0, 500)}; }
                return {status: resp.status, contentType: resp.headers.get('content-type'), parsed};
              }
              const ranges = [
                {name:'default_page_range', startDate:'2026-06-26', endDate:'2026-07-02', daysType:7},
                {name:'excel_week_629_703', startDate:'2026-06-29', endDate:'2026-07-03', daysType:7},
                {name:'excel_week_615_619', startDate:'2026-06-15', endDate:'2026-06-19', daysType:7}
              ];
              const out = [];
              for (const r of ranges) {
                const base = {platform:'TX', endDate:r.endDate, startDate:r.startDate, daysType:r.daysType};
                const shops = await postJson('/prod/newGoodsMonitor/shopTaskList', base);
                const shopRows = (shops.parsed && shops.parsed.data) || [];
                const targets = ['sanag', '\u585e\u90a3', 'JBL', '\u7d22\u5c3c\u5f71\u97f3'];
                const targetShops = shopRows.filter(x => targets.some(t => (x.shopName || '').includes(t))).slice(0, 4);
                const goodsResults = [];
                for (const shop of targetShops) {
                  const goods = await postJson('/prod/newGoodsMonitor/newGoodsList', {...base, shopId: String(shop.shopId)});
                  const rows = (goods.parsed && goods.parsed.data) || [];
                  goodsResults.push({shopName: shop.shopName, shopId: shop.shopId, newCount: shop.newCount, goodsStatus: goods.status, goodsCount: rows.length, sample: rows[0] || null});
                }
                out.push({range:r, shopsStatus:shops.status, shopsContentType:shops.contentType, shopsCount:shopRows.length, firstShop:shopRows[0] || null, targets: goodsResults, parseError: shops.parsed && shops.parsed.parseError, textHead: shops.parsed && shops.parsed.textHead});
              }
              return out;
            }
            """
        )

        result = {"page_url": page.url, "captured_requests": captured, "repro": repro}
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print("saved", output_path.resolve())
        print("captured_count", len(captured))
        print(json.dumps(repro, ensure_ascii=False, indent=2)[:14000])
        context.close()
        return result


if __name__ == "__main__":
    run_probe()
