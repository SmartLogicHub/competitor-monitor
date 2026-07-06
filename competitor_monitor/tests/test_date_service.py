import unittest
from datetime import date

from date_service import (
    build_sheet_name,
    date_header_labels,
    get_work_week,
    is_workday,
    sheet_name_contains_date,
)


class DateServiceTest(unittest.TestCase):
    def test_builds_current_work_week_from_any_weekday(self):
        week = get_work_week(date(2026, 7, 3))

        self.assertEqual(week.monday, date(2026, 6, 29))
        self.assertEqual(week.friday, date(2026, 7, 3))
        self.assertEqual(build_sheet_name(week), "6.29-7.3")
        self.assertEqual(
            date_header_labels(week),
            ["6月29", "6月30", "7月1", "7月2", "7月3"],
        )

    def test_detects_date_inside_sheet_name_range(self):
        self.assertTrue(sheet_name_contains_date("6.29-7.3", date(2026, 7, 1)))
        self.assertFalse(sheet_name_contains_date("6.29-7.3", date(2026, 7, 6)))

    def test_detects_cross_year_sheet_name_range(self):
        self.assertTrue(sheet_name_contains_date("12月29-1月2", date(2026, 1, 1)))
        self.assertTrue(sheet_name_contains_date("12.29-1.2", date(2025, 12, 30)))
        self.assertFalse(sheet_name_contains_date("12月29-1月2", date(2026, 1, 5)))

    def test_identifies_monday_to_friday_as_workdays(self):
        self.assertTrue(is_workday(date(2026, 7, 3)))
        self.assertFalse(is_workday(date(2026, 7, 4)))
        self.assertFalse(is_workday(date(2026, 7, 5)))


if __name__ == "__main__":
    unittest.main()
