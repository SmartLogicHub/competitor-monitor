from __future__ import annotations

import argparse
import sys
from pathlib import Path

from web_api import WebApiService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a competitor monitor task through the Web backend service")
    parser.add_argument("--config", default=None, help="Config file path; defaults to competitor_monitor/config.yaml")
    parser.add_argument(
        "--mode",
        choices=["daily_price", "weekly_new", "price_trend", "all"],
        default="daily_price",
        help="Task mode to run",
    )
    parser.add_argument("--date", dest="run_date", default=None, help="Run date in YYYY-MM-DD format; defaults to today")
    parser.add_argument("--dry-run", action="store_true", help="Run safety checks without real collection/write")
    parser.add_argument("--test-one", action="store_true", help="Collect only one product")
    parser.add_argument("--rows", default=None, help="Excel rows or ranges, for example 24,54,60-62")
    parser.add_argument("--limit", default=None, help="Limit item count")
    parser.add_argument("--save-every", default=None, help="Save Excel every N processed products")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_dir = runtime_base_dir()
    config_path = Path(args.config) if args.config else base_dir / "competitor_monitor" / "config.yaml"
    if not config_path.is_absolute():
        config_path = base_dir / config_path

    payload = {
        "mode": args.mode,
        "dry_run": bool(args.dry_run),
        "test_one": bool(args.test_one),
    }
    if args.run_date:
        payload["run_date"] = args.run_date
    if args.rows:
        payload["rows"] = args.rows
    if args.limit:
        payload["limit"] = args.limit
    if args.save_every:
        payload["save_every"] = args.save_every

    service = WebApiService(base_dir=base_dir, config_path=config_path)
    print(f"Starting task: mode={payload['mode']} config={display_path(config_path, base_dir)}")
    service.run_task(payload)
    service.wait_for_current_task()
    status = service.get_tasks_status()
    print(
        "Task finished: "
        f"status={status.get('system_status')} "
        f"success={status.get('success_count')} "
        f"failed={status.get('failed_count')} "
        f"skipped={status.get('skipped_count')} "
        f"step={status.get('current_step')}"
    )
    if status.get("last_notify_error"):
        print(f"WeCom notify error: {status.get('last_notify_error')}")
    return 0 if status.get("system_status") == "success" else 1


def runtime_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def display_path(path: Path, base_dir: Path) -> str:
    try:
        return path.resolve().relative_to(base_dir.resolve()).as_posix()
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
