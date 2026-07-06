from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class WorkWeek:
    monday: date
    friday: date


def get_work_week(target_date: date) -> WorkWeek:
    """Return the Monday-Friday monitoring period containing target_date."""
    monday = target_date - timedelta(days=target_date.weekday())
    friday = monday + timedelta(days=4)
    return WorkWeek(monday=monday, friday=friday)


def is_workday(target_date: date) -> bool:
    return target_date.weekday() < 5


def build_sheet_name(week: WorkWeek) -> str:
    return f"{week.monday.month}.{week.monday.day}-{week.friday.month}.{week.friday.day}"


def date_header_labels(week: WorkWeek) -> list[str]:
    return [f"{(week.monday + timedelta(days=i)).month}月{(week.monday + timedelta(days=i)).day}" for i in range(5)]


def date_header_label(target_date: date) -> str:
    return f"{target_date.month}月{target_date.day}"


def parse_sheet_range(sheet_name: str, target_year: int) -> WorkWeek | None:
    parsed = _parse_sheet_parts(sheet_name)
    if parsed is None:
        return None
    start_month, start_day, end_month, end_day = parsed
    end_year = target_year + 1 if start_month > end_month else target_year
    return WorkWeek(
        monday=date(target_year, start_month, start_day),
        friday=date(end_year, end_month, end_day),
    )


def _parse_sheet_parts(sheet_name: str) -> tuple[int, int, int, int] | None:
    match = re.fullmatch(r"\s*(\d{1,2})[月.]?(\d{1,2})\s*-\s*(\d{1,2})[月.]?(\d{1,2})\s*", sheet_name)
    if not match:
        return None
    return tuple(map(int, match.groups()))


def sheet_name_contains_date(sheet_name: str, target_date: date) -> bool:
    parsed = _parse_sheet_parts(sheet_name)
    if parsed is None:
        return False
    start_month, start_day, end_month, end_day = parsed
    for start_year in (target_date.year - 1, target_date.year, target_date.year + 1):
        end_year = start_year + 1 if start_month > end_month else start_year
        week = WorkWeek(
            monday=date(start_year, start_month, start_day),
            friday=date(end_year, end_month, end_day),
        )
        if week.monday <= target_date <= week.friday:
            return True
    return False


def looks_like_period_sheet(sheet_name: str) -> bool:
    return parse_sheet_range(sheet_name, date.today().year) is not None
