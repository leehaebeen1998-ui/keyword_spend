from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta


@dataclass(frozen=True)
class DownloadWindow:
    start_date: date
    end_date: date
    reason: str

    @property
    def start_yyyymmdd(self) -> str:
        return self.start_date.strftime("%Y%m%d")

    @property
    def end_yyyymmdd(self) -> str:
        return self.end_date.strftime("%Y%m%d")


def parse_date(value: str | date | datetime | None = None) -> date:
    if value is None:
        return date.today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unsupported date format: {value!r}")


def parse_time(value: str | time | None = None) -> time:
    if value is None:
        return time(hour=8, minute=0)
    if isinstance(value, time):
        return value
    text = str(value).strip()
    for fmt in ("%H:%M", "%H%M"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"Unsupported time format: {value!r}")


def default_download_window(run_date: str | date | datetime | None = None) -> DownloadWindow:
    current = parse_date(run_date)
    weekday = current.weekday()
    if weekday == 0:
        end = current - timedelta(days=1)
        start = current - timedelta(days=3)
        return DownloadWindow(start, end, "monday_weekend_catchup")
    if weekday in (1, 2, 3, 4):
        target = current - timedelta(days=1)
        return DownloadWindow(target, target, "weekday_previous_day")
    target = current - timedelta(days=1)
    return DownloadWindow(target, target, "default_previous_day")


def custom_download_window(start_date: str | date | datetime, end_date: str | date | datetime) -> DownloadWindow:
    start = parse_date(start_date)
    end = parse_date(end_date)
    if end < start:
        raise ValueError("end_date cannot be before start_date")
    return DownloadWindow(start, end, "custom_holiday_or_manual")


def next_run_datetime(
    *,
    run_date: str | date | datetime | None = None,
    start_time: str | time | None = None,
) -> datetime:
    current = parse_date(run_date)
    scheduled_time = parse_time(start_time)
    return datetime.combine(current, scheduled_time)
