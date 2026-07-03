import unittest

from index_classifier.schedule_rules import custom_download_window, default_download_window, next_run_datetime


class ScheduleRulesTests(unittest.TestCase):
    def test_tuesday_to_friday_downloads_previous_day(self):
        window = default_download_window("2026-07-01")

        self.assertEqual(window.start_yyyymmdd, "20260630")
        self.assertEqual(window.end_yyyymmdd, "20260630")
        self.assertEqual(window.reason, "weekday_previous_day")

    def test_monday_downloads_friday_to_sunday(self):
        window = default_download_window("2026-07-06")

        self.assertEqual(window.start_yyyymmdd, "20260703")
        self.assertEqual(window.end_yyyymmdd, "20260705")
        self.assertEqual(window.reason, "monday_weekend_catchup")

    def test_custom_holiday_window(self):
        window = custom_download_window("2026-08-14", "2026-08-17")

        self.assertEqual(window.start_yyyymmdd, "20260814")
        self.assertEqual(window.end_yyyymmdd, "20260817")
        self.assertEqual(window.reason, "custom_holiday_or_manual")

    def test_start_time_defaults_to_8am(self):
        scheduled = next_run_datetime(run_date="2026-07-01")

        self.assertEqual(scheduled.strftime("%Y-%m-%d %H:%M"), "2026-07-01 08:00")


if __name__ == "__main__":
    unittest.main()
