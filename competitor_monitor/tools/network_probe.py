from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from browser_service import BrowserService
from config_service import load_config
from excel_service import ExcelService


KEYWORDS = ("mtop", "h5api", "detail", "item", "sku", "rate", "price")
EXCLUDE_KEYWORDS = ("getaddresslist",)


def parse_args():
    parser = argparse.ArgumentParser(description="Observe browser network traffic for one product row.")
    parser.add_argument("--config", default="competitor_monitor/config_real_test.yaml")
    parser.add_argument("--sheet", required=True)
    parser.add_argument("--row", type=int, required=True)
    parser.add_argument("--seconds", type=int, default=12)
    parser.add_argument("--max-body-chars", type=int, default=200000)
    return parser.parse_args()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()
    config = load_config(args.config)
    excel_path = Path(config.get("excel_path", "竞品监控.xlsx"))
    workbook = ExcelService(excel_path).load_workbook()
    worksheet = workbook[args.sheet]
    model_cell = worksheet.cell(row=args.row, column=2)
    url = model_cell.hyperlink.target if model_cell.hyperlink and model_cell.hyperlink.target else str(model_cell.value or "")
    model = str(model_cell.value or "")
    records: list[dict] = []

    def record_response(response):
        response_url = response.url
        if not any(keyword in response_url.lower() for keyword in KEYWORDS):
            return
        if any(keyword in response_url.lower() for keyword in EXCLUDE_KEYWORDS):
            return
        item = {
            "status": response.status,
            "url": response_url,
            "decoded_url": unquote(unquote(response_url)),
            "content_type": response.headers.get("content-type", ""),
            "snippet": "",
        }
        try:
            body = response.text()
            item["snippet"] = body[: args.max_body_chars]
        except Exception as exc:
            item["snippet"] = f"<body unavailable: {exc}>"
        records.append(item)

    with BrowserService(
        headless=bool(config.get("headless", False)),
        timeout_ms=int(config.get("timeout_ms", 60000)),
        user_data_dir=config.get("browser_user_data_dir", "competitor_monitor/browser_profile"),
        context_config=config,
    ) as browser:
        page = browser._context.new_page()
        page.on("response", record_response)
        page.goto(url, wait_until="domcontentloaded", timeout=int(config.get("timeout_ms", 60000)))
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        time.sleep(args.seconds)
        title = page.title()
        body_text = page.locator("body").inner_text(timeout=5000)
        page.close()

    output_dir = Path(config.get("log_dir", "competitor_monitor/logs"))
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"network_probe_row{args.row}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print("model", model)
    print("url", url)
    print("title", title)
    print("body_head", body_text[:500].replace("\n", " | "))
    print("record_count", len(records))
    print("output", output_path)
    for record in records[:20]:
        print(record["status"], record["content_type"], record["url"])
        print(record["snippet"][:240].replace("\n", " "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
