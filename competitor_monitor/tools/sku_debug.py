from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from activity_service import ActivityService
from browser_service import BrowserService
from collector import ProductCollector
from config_service import load_config
from excel_service import ExcelService
from sku_service import match_sku_options, summarize_sku_label


def parse_args():
    parser = argparse.ArgumentParser(description="Debug visible SKU extraction for one product page.")
    parser.add_argument("--config", default="competitor_monitor/config_real_test.yaml")
    parser.add_argument("--url")
    parser.add_argument("--model")
    parser.add_argument("--sheet")
    parser.add_argument("--row", type=int)
    return parser.parse_args()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()
    config = load_config(args.config)
    url = args.url
    model = args.model
    if args.sheet and args.row:
        excel_path = Path(config.get("excel_path", "竞品监控.xlsx"))
        workbook = ExcelService(excel_path).load_workbook()
        worksheet = workbook[args.sheet]
        model_cell = worksheet.cell(row=args.row, column=2)
        model = model or str(model_cell.value or "")
        if model_cell.hyperlink and model_cell.hyperlink.target:
            url = url or model_cell.hyperlink.target
    if not url or not model:
        raise ValueError("Provide --url and --model, or provide --sheet and --row.")
    activity = ActivityService(config.get("activity_mapping", {}), config.get("keep_original_activities", []))
    collector = ProductCollector(activity)
    with BrowserService(
        headless=bool(config.get("headless", False)),
        timeout_ms=int(config.get("timeout_ms", 60000)),
        user_data_dir=config.get("browser_user_data_dir", "competitor_monitor/browser_profile"),
        context_config=config,
    ) as browser:
        page = browser.open_page(url)
        options = collector.extract_sku_option_texts(page)
        matches = match_sku_options(model, options)
        print("option_count", len(options))
        for option in options:
            marker = "*" if option in matches else "-"
            print(marker, option)
        print("matched_count", len(matches))
        for option in matches:
            clicked = collector.click_sku_option(page, option)
            text = page.locator("body").inner_text(timeout=5000)
            price = collector.extract_price(text)
            print("clicked", clicked, "label", summarize_sku_label(model, option), "price", price, "option", option)
        page.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
