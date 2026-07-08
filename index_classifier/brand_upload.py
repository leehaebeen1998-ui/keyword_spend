from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable


DATE_FMT = "%Y%m%d"


@dataclass(frozen=True)
class SheetTarget:
    brand: str
    category: str
    report_date: date
    sheet_name: str
    date_formula: str | None = None
    media: str = "naver"
    campaign_kind: str | None = None

    @property
    def offset_days(self) -> int:
        return int(self.sheet_name.split("(")[-1].split("일")[0]) if "(" in self.sheet_name else 1


@dataclass(frozen=True)
class BrandUploadRule:
    brand: str
    mode: str
    categories: tuple[str, ...]
    sheet_prefixes: dict[str, str] = field(default_factory=dict)
    google_categories: tuple[str, ...] = ()
    rolling_days: int = 1
    today_offset: int = 1
    use_today_formula: bool = True


DEFAULT_BRAND_RULES: dict[str, BrandUploadRule] = {
    "법무법인 오현": BrandUploadRule(
        brand="법무법인 오현",
        mode="fixed_today_offset",
        categories=(
            "ohcrime(형사)",
            "ohdcrime(마약)",
            "ohehon(이혼)",
            "ohscrime(성범죄)",
            "법무법인오현(허브)",
            "경제범죄",
            "부동산전문",
            "명예훼손",
            "교통사고",
            "회생",
            "노무노사",
            "학교폭력",
            "군형사",
            "파컨(경제범죄)",
            "파컨(법무법인오현(허브))",
            "파컨(교통사고)",
            "파컨(노무노사)",
            "파컨(마약)",
            "파컨(명예훼손)",
            "파컨(부동산전문)",
            "파컨(성범죄)",
            "파컨(이혼)",
            "파컨(학교폭력)",
            "파컨(형사)",
        ),
        rolling_days=1,
        today_offset=1,
    ),
    "법무법인 태하": BrandUploadRule(
        brand="법무법인 태하",
        mode="rolling_day_sheets",
        categories=("형", "이", "마", "성", "행정", "조세", "군형사", "개인회생"),
        google_categories=("형", "성범죄", "교통", "이", "마", "재산범죄", "군형사"),
        rolling_days=7,
        today_offset=1,
        use_today_formula=False,
    ),
}


def parse_run_date(value: str | date | datetime | None = None) -> date:
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


def report_date_for_offset(run_date: str | date | datetime, offset_days: int) -> date:
    return parse_run_date(run_date) - timedelta(days=offset_days)


def offset_for_report_date(run_date: str | date | datetime, report_date: str | date | datetime) -> int:
    offset = (parse_run_date(run_date) - parse_run_date(report_date)).days
    if offset < 0:
        raise ValueError("report_date cannot be after run_date")
    return offset


def weekend_catchup_offsets(run_date: str | date | datetime) -> tuple[int, ...]:
    """Return offsets to process when a weekday run needs weekend sheets too.

    Monday runs should cover Sunday, Saturday, and Friday because no normal
    weekday operator run usually happened over the weekend.
    """
    current = parse_run_date(run_date)
    if current.weekday() == 0:
        return (1, 2, 3)
    return (1,)


def rolling_offsets(run_date: str | date | datetime, rolling_days: int, *, include_weekend_catchup: bool = True) -> tuple[int, ...]:
    base = set(range(1, rolling_days + 1))
    if include_weekend_catchup:
        base.update(weekend_catchup_offsets(run_date))
    return tuple(sorted(base))


def build_sheet_targets(
    rule: BrandUploadRule,
    run_date: str | date | datetime,
    *,
    include_weekend_catchup: bool = True,
) -> list[SheetTarget]:
    current = parse_run_date(run_date)
    targets: list[SheetTarget] = []

    if rule.mode == "fixed_today_offset":
        # 평일에는 태하와 동일하게 시트명이 고정 라벨("1일")이고, 주말 캐치업
        # (월요일 실행 시 금/토/일 3일치)만 실제 달력 날짜로 시트명이 갈린다.
        # 하나의 "1일" 시트로는 캐치업 대상 여러 날짜를 구분할 수 없기 때문이다.
        catchup_offsets = weekend_catchup_offsets(current) if include_weekend_catchup else (rule.today_offset,)
        needs_catchup = len(catchup_offsets) > 1

        if needs_catchup:
            for offset in catchup_offsets:
                report_date = report_date_for_offset(current, offset)
                for category in rule.categories:
                    sheet_prefix = rule.sheet_prefixes.get(category, category)
                    campaign_kind = None
                    if rule.brand == "법무법인 오현":
                        campaign_kind = "power_contents" if category.startswith("파컨(") else "power_link"
                    targets.append(
                        SheetTarget(
                            brand=rule.brand,
                            category=category,
                            report_date=report_date,
                            sheet_name=f"{sheet_prefix}{report_date.day}일",
                            date_formula=None,
                            campaign_kind=campaign_kind,
                        )
                    )
            return targets

        report_date = report_date_for_offset(current, rule.today_offset)
        formula = f"=TODAY()-{rule.today_offset}" if rule.use_today_formula else None
        for category in rule.categories:
            sheet_prefix = rule.sheet_prefixes.get(category, category)
            campaign_kind = None
            if rule.brand == "법무법인 오현":
                campaign_kind = "power_contents" if category.startswith("파컨(") else "power_link"
            targets.append(
                SheetTarget(
                    brand=rule.brand,
                    category=category,
                    report_date=report_date,
                    sheet_name=f"{sheet_prefix}1일",
                    date_formula=formula,
                    campaign_kind=campaign_kind,
                )
            )
        return targets

    if rule.mode == "rolling_day_sheets":
        for offset in rolling_offsets(current, rule.rolling_days, include_weekend_catchup=include_weekend_catchup):
            report_date = report_date_for_offset(current, offset)
            for category in rule.categories:
                targets.append(
                    SheetTarget(
                        brand=rule.brand,
                        category=category,
                        report_date=report_date,
                        sheet_name=f"{category}({offset}일)",
                    )
                )
            for category in rule.google_categories:
                targets.append(
                    SheetTarget(
                        brand=rule.brand,
                        category=category,
                        report_date=report_date,
                        sheet_name=f"{category}({offset}일)_구글",
                        media="google",
                    )
                )
        return targets

    raise ValueError(f"Unsupported brand upload mode: {rule.mode}")


def target_dates_for_upload(run_date: str | date | datetime, offsets: Iterable[int]) -> tuple[str, ...]:
    current = parse_run_date(run_date)
    return tuple(report_date_for_offset(current, offset).strftime(DATE_FMT) for offset in offsets)
