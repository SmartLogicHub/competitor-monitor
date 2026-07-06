from __future__ import annotations

import argparse
import random
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from activity_service import ActivityService
from bi_service import BICollectResult, collect_bi_new_products
from browser_service import BrowserService
from collector import ProductCollector
from config_service import load_config
from credential_service import load_taobao_credentials
from date_service import build_sheet_name, get_work_week, parse_sheet_range
from excel_service import ExcelService, WorkbookLayoutError, backup_excel, column_name
from logger_service import setup_logger
from new_product_service import get_previous_completed_work_week, is_weekly_new_run_day
from new_product_writer import (
    NewProductWriteStats,
    detect_new_product_layout,
    list_new_product_brands,
    match_new_product_brand,
    write_new_products,
)
from price_trend_service import PriceTrendWriteStats, update_price_trends


@dataclass
class RunStats:
    total: int = 0
    success: int = 0
    skipped: int = 0
    failed: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Competitor monitor Excel auto fill")
    parser.add_argument("--config", default="competitor_monitor/config.yaml", help="Config file path")
    parser.add_argument("--date", default=None, help="Run date in YYYY-MM-DD format; defaults to today")
    parser.add_argument(
        "--mode",
        choices=["daily_price", "weekly_new", "price_trend", "all"],
        default="daily_price",
        help="Run mode: daily_price, weekly_new, price_trend, or all",
    )
    parser.add_argument("--dry-run", action="store_true", help="Backup, detect layout, and list products without browser collection")
    parser.add_argument("--test-one", action="store_true", help="Collect only the first product link")
    parser.add_argument("--limit", type=int, default=None, help="Limit products for batch testing")
    parser.add_argument("--rows", default=None, help="Comma-separated Excel rows or ranges to collect, for example: 24,54,60-62")
    parser.add_argument("--save-every", type=int, default=None, help="Save Excel every N processed products; 0 disables checkpoints")
    parser.add_argument("--force-overwrite", action="store_true", help="Overwrite existing daily price cells for this run")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        row_filter = parse_row_filter(args.rows)
    except ValueError as exc:
        print(f"Invalid --rows: {exc}", file=sys.stderr)
        return 2

    base_dir = Path.cwd()
    config = load_config(args.config)
    apply_cli_overrides(config, args)
    excel_path = _resolve_path(base_dir, config.get("excel_path", "\u7ade\u54c1\u76d1\u63a7.xlsx"))
    log_dir = _resolve_path(base_dir, config.get("log_dir", "competitor_monitor/logs"))
    backup_dir = _resolve_path(base_dir, config.get("backup_dir", "competitor_monitor/backup"))
    logger, log_path = setup_logger(log_dir)
    run_date = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()

    logger.info("Current run time: %s", datetime.now().isoformat(timespec="seconds"))
    logger.info("Input Excel path: %s", excel_path)
    logger.info("Log file path: %s", log_path)

    try:
        backup_path = backup_excel(excel_path, backup_dir)
        logger.info("Backup file path: %s", backup_path)

        excel = ExcelService(excel_path)
        workbook = excel.load_workbook()
        exit_code = 0

        if args.mode in {"daily_price", "all"}:
            daily_stats = run_daily_price_job(
                config=config,
                logger=logger,
                excel=excel,
                workbook=workbook,
                run_date=run_date,
                dry_run=args.dry_run,
                test_one=args.test_one,
                limit=args.limit,
                row_filter=row_filter,
                save_every=args.save_every,
                excel_path=excel_path,
            )
            if daily_stats.failed:
                exit_code = 1
            if args.mode == "all" and not args.dry_run:
                workbook = excel.load_workbook()

        if args.mode in {"weekly_new", "all"}:
            weekly_stats = run_weekly_new_products(
                config=config,
                logger=logger,
                excel=excel,
                workbook=workbook,
                run_date=run_date,
                dry_run=args.dry_run,
                excel_path=excel_path,
            )
            if weekly_stats.failed:
                exit_code = 1

        if args.mode == "price_trend":
            run_price_trend_job(
                config=config,
                logger=logger,
                excel=excel,
                workbook=workbook,
                run_date=run_date,
                dry_run=args.dry_run,
                excel_path=excel_path,
            )

        return exit_code
    except WorkbookLayoutError as exc:
        logger.exception("Workbook layout error: %s", exc)
        return 2
    except Exception as exc:
        logger.exception("Run failed: %s", exc)
        return 1


def apply_cli_overrides(config: dict, args: argparse.Namespace) -> dict:
    if getattr(args, "force_overwrite", False):
        config["force_overwrite"] = True
    return config


def run_daily_price_job(
    config,
    logger,
    excel,
    workbook,
    run_date: date,
    dry_run: bool,
    test_one: bool,
    limit: int | None,
    row_filter: set[int] | None,
    save_every: int | None,
    excel_path: Path,
    stop_event=None,
    progress_callback=None,
) -> RunStats:
    worksheet = excel.get_or_create_current_sheet(workbook, run_date)
    layout = excel.detect_layout(worksheet, run_date)
    products = excel.list_mature_products(worksheet, layout.model_column, layout.data_start_row)

    logger.info("Current sheet: %s", worksheet.title)
    logger.info("Price column for run date: %s", column_name(layout.price_column))
    logger.info("Activity column: %s", column_name(layout.activity_column))
    display_products = select_target_products(products, test_one=test_one, limit=limit, row_filter=row_filter)
    logger.info("Total products: %s", len(products))
    logger.info("Products in this run: %s", len(display_products))
    if row_filter:
        logger.info("Requested Excel rows: %s", ",".join(str(row) for row in sorted(row_filter)))

    print_product_list(display_products)
    if dry_run:
        if progress_callback:
            total = len(display_products)
            for processed, product in enumerate(display_products, start=1):
                progress_callback(
                    {
                        "processed": processed,
                        "total": total,
                        "success": 0,
                        "failed": 0,
                        "skipped": processed,
                        "status": "skipped",
                        "row": product.row,
                        "brand": product.brand,
                        "model": product.name,
                        "url": product.url,
                        "price": None,
                        "error": "dry-run",
                        "sheet": worksheet.title,
                    }
                )
        logger.info("Dry-run mode: browser collection and workbook writes are skipped")
        return RunStats(total=len(display_products))

    checkpoint = save_every
    if checkpoint is None:
        checkpoint = int(config.get("save_every_n_products", 5))
    stats = run_collection(
        config,
        logger,
        excel,
        workbook,
        worksheet,
        layout,
        products,
        test_one,
        limit=limit,
        row_filter=row_filter,
        save_every=checkpoint,
        excel_path=excel_path,
        target_date=run_date,
        stop_event=stop_event,
        progress_callback=progress_callback,
    )
    logger.info("Success count: %s", stats.success)
    logger.info("Skipped count: %s", stats.skipped)
    logger.info("Failed count: %s", stats.failed)
    if should_auto_update_price_trends(config, run_date, test_one, limit, row_filter):
        workbook = excel.load_workbook()
        worksheet = excel.get_or_create_current_sheet(workbook, run_date)
        layout = excel.detect_layout(worksheet, run_date)
        trend_stats = update_price_trends(
            worksheet,
            layout,
            force_overwrite=bool(config.get("force_overwrite_price_trend", False)),
        )
        excel.save_workbook(workbook, excel_path)
        log_price_trend_stats(logger, trend_stats)
    elif bool(config.get("price_trend_enabled", True)):
        logger.info("Price trend auto update skipped for this daily run")
    return stats


def run_price_trend_job(config, logger, excel, workbook, run_date: date, dry_run: bool, excel_path: Path) -> PriceTrendWriteStats:
    if not bool(config.get("price_trend_enabled", True)):
        logger.info("Price trend update is disabled; skipping")
        return PriceTrendWriteStats()
    week = price_trend_week_for_run(run_date)
    worksheet = excel.get_or_create_current_sheet(workbook, week.monday)
    layout = excel.detect_layout(worksheet, week.friday)
    logger.info("Price trend sheet: %s", worksheet.title)
    logger.info("Price trend period start date: %s", week.monday)
    logger.info("Price trend period end date: %s", week.friday)
    logger.info("Price trend status column: %s", column_name(layout.price_status_column))
    stats = update_price_trends(
        worksheet,
        layout,
        force_overwrite=bool(config.get("force_overwrite_price_trend", False)),
    )
    log_price_trend_stats(logger, stats)
    if dry_run:
        logger.info("Dry-run mode: price trend workbook writes are skipped")
    else:
        excel.save_workbook(workbook, excel_path)
        logger.info("Saved Excel: %s", excel_path)
    return stats


def should_auto_update_price_trends(
    config,
    run_date: date,
    test_one: bool,
    limit: int | None,
    row_filter: set[int] | None,
) -> bool:
    if not bool(config.get("price_trend_enabled", True)):
        return False
    if not bool(config.get("price_trend_auto_update", True)):
        return False
    if test_one or limit is not None or row_filter:
        return False
    allowed_weekdays = _config_weekdays(config.get("price_trend_allowed_weekdays", [4]))
    return run_date.weekday() in allowed_weekdays


def price_trend_week_for_run(run_date: date):
    if run_date.weekday() == 4:
        return get_work_week(run_date)
    if run_date.weekday() in {0, 5, 6}:
        return get_previous_completed_work_week(run_date)
    return get_work_week(run_date)


def log_price_trend_stats(logger, stats: PriceTrendWriteStats) -> None:
    logger.info("Price trend total rows: %s", stats.total)
    logger.info("Price trend written count: %s", stats.written)
    logger.info("Price trend skipped existing count: %s", stats.skipped_existing)
    logger.info("Price trend skipped incomplete count: %s", stats.skipped_incomplete)
    logger.info("Price trend skipped unclassified count: %s", stats.skipped_unclassified)


def run_weekly_new_products(config, logger, excel, workbook, run_date: date, dry_run: bool, excel_path: Path):
    if not bool(config.get("new_product_enabled", True)):
        logger.info("New product monitoring is disabled; skipping weekly_new")
        return NewProductWriteStats()
    allowed_weekdays = _config_weekdays(config.get("new_product_allowed_weekdays", [5, 6]))
    if not is_weekly_new_run_day(run_date, allowed_weekdays):
        logger.info(
            "Weekly new-product BI collection skipped on %s; allowed weekdays are %s (Monday=0, Sunday=6)",
            run_date,
            sorted(allowed_weekdays),
        )
        return NewProductWriteStats()
    week = get_previous_completed_work_week(run_date)
    sheet_date = week.monday
    worksheet = excel.get_or_create_current_sheet(workbook, sheet_date)
    workbook, worksheet = ensure_weekly_price_completeness_before_bi(
        config=config,
        logger=logger,
        excel=excel,
        workbook=workbook,
        run_date=run_date,
        sheet_date=sheet_date,
        dry_run=dry_run,
        excel_path=excel_path,
    )
    layout = detect_new_product_layout(worksheet)
    excel_brands = list_new_product_brands(worksheet, layout)

    logger.info("Current weekly new-product run time: %s", datetime.now().isoformat(timespec="seconds"))
    logger.info("Current sheet: %s", worksheet.title)
    logger.info("Current period start date: %s", week.monday)
    logger.info("Current period end date: %s", week.friday)
    logger.info("Current period sheet name: %s", build_sheet_name(week))
    logger.info("New-product brand count: %s", len(excel_brands))

    mode = config.get("new_product_mode", "bi")
    if mode != "bi":
        raise ValueError(f"Only new_product_mode=bi is supported currently; got {mode}")

    collect_result: BICollectResult
    if dry_run:
        collect_result = BICollectResult(products=[], total_shop_count=0, queried_shop_count=0, total_goods_count=0)
        logger.info("Dry-run mode: BI browser collection and new-product writes are skipped")
    else:
        collect_result = collect_bi_new_products(config, week, logger=logger)

    products_by_brand = {brand: [] for brand in excel_brands}
    unmatched_products = 0
    brand_shop_aliases = config.get("new_product_brand_shop_aliases", {})
    for product in collect_result.products:
        matched_brand = match_new_product_brand(product.brand, excel_brands, brand_shop_aliases)
        if matched_brand is None:
            unmatched_products += 1
            continue
        products_by_brand.setdefault(matched_brand, []).append(product)

    logger.info("BI shop total count: %s", collect_result.total_shop_count)
    logger.info("BI queried shop count: %s", collect_result.queried_shop_count)
    logger.info("BI raw new-product count: %s", collect_result.total_goods_count)
    logger.info("Matched current-period new-product count: %s", len(collect_result.products))
    logger.info("Unmatched new-product count ignored by Excel brand mapping: %s", unmatched_products)
    print_new_product_list(collect_result.products)

    if dry_run:
        return NewProductWriteStats()

    stats = write_new_products(
        worksheet,
        layout,
        products_by_brand,
        no_data_text=config.get("new_product_no_data_text", "\u65e0\u4e0a\u65b0"),
        force_overwrite=bool(config.get("force_overwrite_new_products", False)),
    )
    excel.save_workbook(workbook, excel_path)
    logger.info("New-product written count: %s", stats.written)
    logger.info("New-product duplicate skipped count: %s", stats.skipped_duplicates)
    logger.info("No-new marker written: %s", stats.no_data_written)
    logger.info("New-product failed count: %s", stats.failed)
    for detail in stats.failure_details:
        logger.warning("New-product failed detail: %s", detail)
    logger.info("Saved Excel: %s", excel_path)
    return stats


def ensure_weekly_price_completeness_before_bi(
    config,
    logger,
    excel,
    workbook,
    run_date: date,
    sheet_date: date,
    dry_run: bool,
    excel_path: Path,
):
    worksheet = excel.get_or_create_current_sheet(workbook, sheet_date)
    completeness = excel.check_weekly_price_completeness(workbook, sheet_date)
    log_template_completeness(logger, "before BI", completeness)
    if completeness.is_complete:
        return workbook, worksheet

    missing_dates = list(completeness.backfillable_dates)
    if not missing_dates:
        logger.warning(
            "Template price completeness has non-backfillable errors before weekly BI: %s",
            format_dates(completeness.missing_dates),
        )
        return workbook, worksheet

    if not bool(config.get("auto_backfill_missing_daily_prices_before_weekly_new", True)):
        logger.warning(
            "Weekly BI price backfill is disabled; missing dates remain: %s",
            format_dates(missing_dates),
        )
        return workbook, worksheet

    if dry_run:
        logger.info(
            "Dry-run mode: missing price dates are reported but not backfilled: %s",
            format_dates(missing_dates),
        )
        return workbook, worksheet

    failed_dates: list[date] = []
    for missing_date in missing_dates:
        logger.info("Backfilling missing daily price date before weekly BI: %s", missing_date.isoformat())
        try:
            backfill_workbook = excel.load_workbook()
            stats = run_daily_price_job(
                config=config,
                logger=logger,
                excel=excel,
                workbook=backfill_workbook,
                run_date=missing_date,
                dry_run=False,
                test_one=False,
                limit=None,
                row_filter=None,
                save_every=config.get("save_every_n_products", 5),
                excel_path=excel_path,
            )
            if stats.failed:
                failed_dates.append(missing_date)
                logger.warning(
                    "Backfill completed with failed items for %s: total=%s success=%s failed=%s",
                    missing_date.isoformat(),
                    stats.total,
                    stats.success,
                    stats.failed,
                )
        except Exception as exc:
            failed_dates.append(missing_date)
            logger.exception("Backfill failed for %s before weekly BI: %s", missing_date.isoformat(), exc)

    workbook = excel.load_workbook()
    worksheet = excel.get_or_create_current_sheet(workbook, sheet_date)
    final_completeness = excel.check_weekly_price_completeness(workbook, sheet_date)
    log_template_completeness(logger, "after BI backfill", final_completeness)
    remaining_missing_dates = list(final_completeness.missing_dates)
    if failed_dates or remaining_missing_dates:
        logger.warning(
            "Weekly BI will continue with incomplete price data; failed_backfill_dates=%s remaining_missing_dates=%s",
            format_dates(failed_dates),
            format_dates(remaining_missing_dates),
        )
    return workbook, worksheet


def log_template_completeness(logger, phase: str, completeness) -> None:
    logger.info(
        "Template completeness %s: sheet=%s period=%s..%s complete=%s missing_dates=%s",
        phase,
        completeness.sheet_name,
        completeness.week_start.isoformat(),
        completeness.week_end.isoformat(),
        completeness.is_complete,
        format_dates(completeness.missing_dates),
    )
    for day in completeness.days:
        if day.is_complete:
            continue
        logger.warning(
            "Template date incomplete: date=%s status=%s filled=%s total=%s missing_rows=%s error=%s",
            day.date.isoformat(),
            day.status,
            day.filled_count,
            day.total_count,
            ",".join(str(row) for row in day.missing_rows) or "-",
            day.error or "-",
        )


def format_dates(values) -> str:
    dates = [value.isoformat() if hasattr(value, "isoformat") else str(value) for value in values]
    return ",".join(dates) if dates else "-"


def _config_weekdays(value) -> list[int]:
    if value is None:
        return [5, 6]
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, (list, tuple, set)):
        parts = list(value)
    else:
        parts = [value]
    weekdays: list[int] = []
    for part in parts:
        day = int(part)
        if day < 0 or day > 6:
            raise ValueError(f"new_product_allowed_weekdays must be between 0 and 6; got {part}")
        weekdays.append(day)
    return weekdays or [5, 6]


def run_collection(
    config,
    logger,
    excel,
    workbook,
    worksheet,
    layout,
    products,
    test_one: bool,
    limit: int | None = None,
    row_filter: set[int] | None = None,
    save_every: int = 5,
    excel_path: Path | str | None = None,
    target_date: date | None = None,
    stop_event=None,
    progress_callback=None,
) -> RunStats:
    activity_service = ActivityService(
        config.get("activity_mapping", {}),
        config.get("keep_original_activities", []),
    )
    collector = ProductCollector(
        activity_service,
        blocked_unmatched_sku_fallback_models=config.get("blocked_unmatched_sku_fallback_models"),
    )
    target_products = select_target_products(products, test_one=test_one, limit=limit, row_filter=row_filter)
    stats = RunStats(total=len(target_products))
    force_overwrite = bool(config.get("force_overwrite", False))
    enable_sku_matching = bool(config.get("enable_sku_matching", True))
    allow_ambiguous_sku_collection = bool(config.get("allow_ambiguous_sku_collection", False))
    skip_previous_slash_rows = bool(config.get("skip_when_previous_prices_all_slash", False))
    fallback_to_previous_price = bool(config.get("fallback_to_previous_price_when_uncertain", False))
    ambiguous_product_keys = find_ambiguous_product_url_keys(products)
    min_delay = int(config.get("min_delay_seconds", 5))
    max_delay = int(config.get("max_delay_seconds", 10))
    retry_count = int(config.get("retry_count", 1))
    saved_current_state = False

    def emit_progress(
        processed: int,
        product,
        status: str,
        price=None,
        error: str | None = None,
        warning: str | None = None,
    ) -> None:
        if not progress_callback:
            return
        progress_callback(
            {
                "processed": processed,
                "total": stats.total,
                "success": stats.success,
                "failed": stats.failed,
                "skipped": stats.skipped,
                "status": status,
                "row": product.row,
                "brand": product.brand,
                "model": product.name,
                "url": product.url,
                "price": price,
                "error": error,
                "warning": warning,
                "sheet": worksheet.title,
            }
        )

    with BrowserService(
        headless=bool(config.get("headless", False)),
        timeout_ms=int(config.get("timeout_ms", 30000)),
        user_data_dir=config.get("browser_user_data_dir", "competitor_monitor/browser_profile"),
        context_config=config,
        taobao_credentials=load_taobao_credentials(config),
    ) as browser:
        if bool(config.get("taobao_login_check_enabled", True)):
            browser.ensure_taobao_login()
        for processed_count, product in enumerate(target_products, start=1):
            if stop_event is not None and stop_event.is_set():
                logger.warning("Stop requested; collection halted before row=%s product=%s", product.row, product.name)
                break
            saved_current_state = False
            product_key = product_url_key(product.url)
            is_ambiguous_product = product_key in ambiguous_product_keys
            if is_ambiguous_product and not enable_sku_matching and not allow_ambiguous_sku_collection:
                stats.skipped += 1
                logger.warning(
                    "SKU 姝т箟璺宠繃锛歴heet=%s row=%s 鍟嗗搧=%s 閾炬帴=%s 鍘熷洜=鍚屼竴鍟嗗搧閾炬帴瀵瑰簲澶氫釜 Excel 鍨嬪彿锛屼笖 enable_sku_matching=false",
                    worksheet.title,
                    product.row,
                    product.name,
                    product.url,
                )
                emit_progress(processed_count, product, "skipped", error="ambiguous_sku")
                continue
            expected_model = product.name if enable_sku_matching else None
            price_cell = worksheet.cell(row=product.row, column=layout.price_column)
            skip_price = price_cell.value not in (None, "") and not force_overwrite
            if (
                skip_previous_slash_rows
                and not skip_price
                and previous_price_cells_are_all_slash(worksheet, layout, product.row)
            ):
                stats.skipped += 1
                logger.info(
                    "閸撳秴绨禒閿嬬壐閸忋劋璐?/ 閿涘矁鐑︽潻鍥ㄦ拱閺冦儵鍣伴梿鍡窗sheet=%s row=%s 閸熷棗鎼?%s",
                    worksheet.title,
                    product.row,
                    product.name,
                )
                emit_progress(processed_count, product, "skipped", error="previous_prices_all_slash")
                continue
            try:
                snapshot = collect_with_retry(
                    browser,
                    collector,
                    product.url,
                    retry_count,
                    expected_model=expected_model,
                    allow_fallback_price=not is_ambiguous_product,
                )
                snapshot_visible_text = getattr(snapshot, "visible_text", "")
                page_model_mismatch = bool(
                    expected_model
                    and snapshot_visible_text
                    and ProductCollector.page_misses_required_model_tokens(
                        expected_model,
                        snapshot_visible_text,
                    )
                )
                if page_model_mismatch:
                    activity_value = "/"
                    price_to_write = None if skip_price else "/"
                    logger.warning(
                        "疑似下架或链接失效：sheet=%s row=%s 商品=%s 页面不包含目标型号，写入 /",
                        worksheet.title,
                        product.row,
                        product.name,
                    )
                else:
                    activity_value = activity_service.merge_activities(
                        worksheet.cell(row=product.row, column=layout.activity_column).value,
                        snapshot.activities,
                    )
                    price_to_write = None if skip_price else snapshot.price
                if price_to_write is None and not skip_price:
                    override_price = manual_price_override_for_product(config, product)
                    if override_price is not None:
                        price_to_write = override_price
                        logger.warning(
                            "使用人工确认价：sheet=%s row=%s 商品=%s 人工确认价=%s",
                            worksheet.title,
                            product.row,
                            product.name,
                            override_price,
                        )
                if price_to_write is None and not skip_price and fallback_to_previous_price:
                    price_to_write, fallback_source = latest_historical_fallback_price(
                        excel,
                        workbook,
                        worksheet,
                        layout,
                        product,
                        target_date,
                    )
                    if price_to_write is not None:
                        logger.warning(
                            "使用历史价格兜底：sheet=%s row=%s 商品=%s 来源=%s 历史价格=%s",
                            worksheet.title,
                            product.row,
                            product.name,
                            fallback_source,
                            price_to_write,
                        )
                correction_warning = None
                if price_to_write is not None and not skip_price:
                    visible_discount_price = collector.extract_priority_price(getattr(snapshot, "visible_text", ""))
                    price_to_write, correction_warning = maybe_use_visible_discount_price_on_alert(
                        config,
                        excel,
                        workbook,
                        worksheet,
                        layout,
                        product,
                        target_date,
                        price_to_write,
                        visible_discount_price,
                    )
                    if correction_warning:
                        logger.warning(correction_warning)
                price_alert = None
                if price_to_write is not None and not skip_price:
                    price_alert = detect_price_change_alert(
                        config,
                        excel,
                        workbook,
                        worksheet,
                        layout,
                        product,
                        target_date,
                        price_to_write,
                    )
                    if price_alert:
                        logger.warning(price_alert)
                progress_warning = combine_warnings(correction_warning, price_alert)
                wrote_price = excel.write_product_result(
                    worksheet,
                    layout,
                    product,
                    price_to_write,
                    activity_value,
                    force_overwrite=force_overwrite,
                )
                if price_to_write is None and not skip_price:
                    logger.warning("浠锋牸閲囬泦澶辫触锛歴heet=%s row=%s 鍟嗗搧=%s 閾炬帴=%s", worksheet.title, product.row, product.name, product.url)
                    stats.failed += 1
                    emit_progress(processed_count, product, "failed", error="price_not_collected")
                else:
                    stats.success += 1
                    if skip_price and not wrote_price:
                        stats.skipped += 1
                    emit_progress(processed_count, product, "success", price=price_to_write, warning=progress_warning)
                time.sleep(random.randint(min_delay, max_delay))
            except Exception as exc:
                stats.failed += 1
                logger.exception("閲囬泦澶辫触锛歴heet=%s row=%s 鍟嗗搧=%s 閾炬帴=%s 鍘熷洜=%s", worksheet.title, product.row, product.name, product.url, exc)
                emit_progress(processed_count, product, "failed", error=str(exc))
            if excel_path and should_save_checkpoint(processed_count, save_every):
                excel.save_workbook(workbook, excel_path)
                saved_current_state = True
                if target_date is not None and processed_count < stats.total:
                    workbook, worksheet, layout = reload_workbook_state(excel, workbook, worksheet, target_date)
                logger.info("Processed %s products and saved Excel checkpoint: %s", processed_count, excel_path)
    if excel_path and not saved_current_state:
        excel.save_workbook(workbook, excel_path)
        logger.info("Saved Excel: %s", excel_path)
    return stats


def reload_workbook_state(excel, workbook, worksheet, target_date: date):
    """Reload after a checkpoint so openpyxl image streams are fresh for the next save."""
    sheet_title = worksheet.title
    if hasattr(workbook, "close"):
        workbook.close()
    reloaded_workbook = excel.load_workbook()
    reloaded_worksheet = reloaded_workbook[sheet_title]
    reloaded_layout = excel.detect_layout(reloaded_worksheet, target_date)
    return reloaded_workbook, reloaded_worksheet, reloaded_layout


def parse_row_filter(raw_rows: str | None) -> set[int] | None:
    if raw_rows is None or not raw_rows.strip():
        return None

    rows: set[int] = set()
    for raw_part in raw_rows.split(","):
        part = raw_part.strip()
        if not part:
            raise ValueError("empty row value")
        if "-" in part:
            start_text, end_text = [piece.strip() for piece in part.split("-", 1)]
            start = parse_positive_row_number(start_text)
            end = parse_positive_row_number(end_text)
            if start > end:
                raise ValueError(f"row range start is greater than end: {part}")
            rows.update(range(start, end + 1))
        else:
            rows.add(parse_positive_row_number(part))
    return rows


def parse_positive_row_number(value: str) -> int:
    try:
        row = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid row number: {value}") from exc
    if row <= 0:
        raise ValueError(f"row number must be positive: {value}")
    return row


def select_target_products(products, test_one: bool = False, limit: int | None = None, row_filter: set[int] | None = None):
    if row_filter is not None:
        products = [product for product in products if product.row in row_filter]
    if test_one:
        return products[:1]
    if limit is None:
        return products
    if limit <= 0:
        return []
    return products[:limit]


def should_save_checkpoint(processed_count: int, save_every: int | None) -> bool:
    if not save_every or save_every <= 0:
        return False
    return processed_count > 0 and processed_count % save_every == 0


def previous_price_cells_are_all_slash(worksheet, layout, row: int) -> bool:
    previous_columns = [
        column
        for column in getattr(layout, "date_price_columns", [])
        if column < layout.price_column
    ]
    if not previous_columns:
        return False
    values = [worksheet.cell(row=row, column=column).value for column in previous_columns]
    return all(is_slash_marker(value) for value in values)


def latest_previous_price(worksheet, layout, row: int):
    previous_columns = [
        column
        for column in getattr(layout, "date_price_columns", [])
        if column < layout.price_column
    ]
    return latest_price_from_columns(worksheet, row, previous_columns)


def latest_historical_fallback_price(excel, workbook, worksheet, layout, product, target_date: date | None):
    current_price = latest_previous_price(worksheet, layout, product.row)
    if current_price is not None:
        return current_price, f"{worksheet.title} 前序日期"
    previous_price = latest_previous_sheet_price(excel, workbook, worksheet, product, target_date)
    if previous_price is not None:
        price, sheet_title = previous_price
        return price, sheet_title
    return None, None


def manual_price_override_for_product(config, product) -> str | None:
    overrides = config.get("manual_price_overrides", [])
    if not isinstance(overrides, list):
        return None
    product_model = normalize_product_name(getattr(product, "name", ""))
    product_brand = normalize_product_name(getattr(product, "brand", "") or "")
    for override in overrides:
        if not isinstance(override, dict):
            continue
        price = override.get("price")
        model = override.get("model")
        if price in (None, "") or not model:
            continue
        if normalize_product_name(model) != product_model:
            continue
        brand = normalize_product_name(override.get("brand", "") or "")
        if brand and brand != product_brand:
            continue
        return str(price).strip()
    return None


def maybe_use_visible_discount_price_on_alert(
    config,
    excel,
    workbook,
    worksheet,
    layout,
    product,
    target_date: date | None,
    current_price,
    visible_discount_price,
):
    if not bool(config.get("prefer_visible_discount_price_on_price_alert", True)):
        return current_price, None
    current_number = first_price_number(current_price)
    visible_number = first_price_number(visible_discount_price)
    if current_number is None or visible_number is None or current_number == visible_number:
        return current_price, None

    historical_price, historical_source = latest_historical_fallback_price(
        excel,
        workbook,
        worksheet,
        layout,
        product,
        target_date,
    )
    historical_number = first_price_number(historical_price)
    if historical_number is None or historical_number == 0:
        return current_price, None

    current_diff = abs(current_number - historical_number)
    visible_diff = abs(visible_number - historical_number)
    threshold_percent = config_decimal(config.get("price_alert_threshold_percent", 20), Decimal("20"))
    min_abs_diff = config_decimal(config.get("price_alert_min_abs_diff", 20), Decimal("20"))
    current_percent = (current_diff / historical_number) * Decimal("100")
    if current_percent < threshold_percent or current_diff < min_abs_diff:
        return current_price, None
    if visible_diff >= current_diff:
        return current_price, None

    warning = (
        f"价格候选纠偏：sheet={worksheet.title} row={product.row} "
        f"品牌={getattr(product, 'brand', '') or '-'} 商品={product.name} "
        f"采集候选价={current_price} 页面优惠价={visible_discount_price} "
        f"历史价={historical_price} 来源={historical_source or '-'} "
        "已写入页面优惠价，请人工复核"
    )
    return visible_discount_price, warning


def combine_warnings(*warnings) -> str | None:
    parts = [str(warning) for warning in warnings if warning]
    return "；".join(parts) if parts else None


def detect_price_change_alert(
    config,
    excel,
    workbook,
    worksheet,
    layout,
    product,
    target_date: date | None,
    current_price,
) -> str | None:
    if not bool(config.get("price_alert_enabled", True)):
        return None
    current_number = first_price_number(current_price)
    if current_number is None:
        return None
    historical_price, historical_source = latest_historical_fallback_price(
        excel,
        workbook,
        worksheet,
        layout,
        product,
        target_date,
    )
    historical_number = first_price_number(historical_price)
    if historical_number is None or historical_number == 0:
        return None

    diff = abs(current_number - historical_number)
    percent = (diff / historical_number) * Decimal("100")
    threshold_percent = config_decimal(config.get("price_alert_threshold_percent", 20), Decimal("20"))
    min_abs_diff = config_decimal(config.get("price_alert_min_abs_diff", 20), Decimal("20"))
    if percent < threshold_percent or diff < min_abs_diff:
        return None
    direction = "上涨" if current_number > historical_number else "下降"
    return (
        f"价格异常波动：sheet={worksheet.title} row={product.row} "
        f"品牌={product.brand or '-'} 商品={product.name} "
        f"历史价={historical_price} 来源={historical_source or '-'} "
        f"本次写入={current_price} {direction}{percent.quantize(Decimal('0.1'))}% "
        "请人工复核"
    )


def first_price_number(value) -> Decimal | None:
    matches = re.findall(r"\d+(?:\.\d+)?", str(value or ""))
    numbers: list[Decimal] = []
    for match in matches:
        try:
            numbers.append(Decimal(match))
        except InvalidOperation:
            continue
    return min(numbers) if numbers else None


def config_decimal(value, default: Decimal) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def latest_previous_sheet_price(excel, workbook, current_worksheet, product, target_date: date | None):
    if target_date is None:
        return None
    current_week = parse_sheet_range(current_worksheet.title, target_date.year)
    cutoff_date = current_week.monday if current_week else target_date
    candidates = []
    for worksheet in workbook.worksheets:
        if worksheet is current_worksheet:
            continue
        week = parse_sheet_range(worksheet.title, target_date.year)
        if week is None or week.friday >= cutoff_date:
            continue
        candidates.append((week.friday, worksheet, week))
    for _, worksheet, week in sorted(candidates, key=lambda item: item[0], reverse=True):
        try:
            layout = excel.detect_layout(worksheet, week.friday)
            products = excel.list_mature_products(worksheet, layout.model_column, layout.data_start_row)
        except Exception:
            continue
        for candidate in products:
            if not same_product_identity(product, candidate):
                continue
            price = latest_price_from_columns(worksheet, candidate.row, layout.date_price_columns)
            if price is not None:
                return price, worksheet.title
    return None


def latest_price_from_columns(worksheet, row: int, columns):
    for column in sorted(columns, reverse=True):
        value = worksheet.cell(row=row, column=column).value
        if is_usable_price_value(value):
            return value
    return None


def same_product_identity(left, right) -> bool:
    if normalize_product_name(getattr(left, "name", "")) != normalize_product_name(getattr(right, "name", "")):
        return False
    left_brand = normalize_product_name(getattr(left, "brand", "") or "")
    right_brand = normalize_product_name(getattr(right, "brand", "") or "")
    if left_brand and right_brand and left_brand != right_brand:
        return False
    if left_brand and not right_brand:
        return False
    return True


def is_usable_price_value(value) -> bool:
    if value in (None, ""):
        return False
    text = str(value).strip()
    if not text or is_slash_marker(text):
        return False
    return bool(re.search(r"\d", text))


def is_slash_marker(value) -> bool:
    return str(value).strip() in {"/", "\uff0f"}


def find_ambiguous_product_url_keys(products) -> set[str]:
    names_by_key: dict[str, set[str]] = defaultdict(set)
    for product in products:
        key = product_url_key(product.url)
        if not key:
            continue
        names_by_key[key].add(normalize_product_name(product.name))
    return {key for key, names in names_by_key.items() if len(names) > 1}


def product_url_key(url: str) -> str:
    parsed = urlparse(str(url or ""))
    query = parse_qs(parsed.query)
    for field_name in ("id", "item_id", "itemId"):
        values = query.get(field_name)
        if values and values[0]:
            return f"item:{values[0]}"
    return parsed._replace(query="", fragment="").geturl().strip().lower().rstrip("/")


def normalize_product_name(name: str) -> str:
    return re.sub(r"\s+", "", str(name or "")).casefold()


def collect_with_retry(
    browser,
    collector,
    url: str,
    retry_count: int,
    expected_model: str | None = None,
    allow_fallback_price: bool = True,
):
    last_error = None
    for _ in range(retry_count + 1):
        page = None
        try:
            page = browser.open_page(url)
            return collector.collect_from_page(
                page,
                expected_model=expected_model,
                allow_fallback_price=allow_fallback_price,
            )
        except Exception as exc:
            last_error = exc
        finally:
            if page:
                page.close()
    raise last_error


def print_product_list(products) -> None:
    print("Products to collect:")
    for product in products:
        print(f"- row={product.row} brand={product.brand or ''} name={product.name} url={product.url}")


def print_new_product_list(products) -> None:
    print("New products to write:")
    for product in products:
        print(
            f"- brand={product.brand} date={product.on_sale_date} model={product.model} "
            f"shape={product.shape} price={product.price} url={product.link or ''}"
        )


def _resolve_path(base_dir: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base_dir / path


if __name__ == "__main__":
    sys.exit(main())
