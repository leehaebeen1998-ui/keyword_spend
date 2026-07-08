from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from .brand_upload import DEFAULT_BRAND_RULES, BrandUploadRule


WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "BrandUploadProcessor"
BRAND_PROFILES_PATH = CONFIG_DIR / "brand_profiles.json"
DEFAULT_OUTPUT_ROOT = Path(tempfile.gettempdir()) / "BrandUploadProcessor" / "outputs"


@dataclass
class BrandProfile:
    name: str
    rules_path: str = "examples\\brand-upload-rules.example.csv"
    download_folder: str = ""
    template_path: str = ""
    output_root: str = str(DEFAULT_OUTPUT_ROOT)
    upload_csv: str = ""
    login_command: str = ""
    downloader_command: str = ""
    spreadsheet_url: str = ""
    spreadsheet_sheet_name: str = ""
    spreadsheet_credentials_path: str = ""
    spreadsheet_upload_mode: str = "replace"
    # 브랜드 유형(3종) 분류 및 DEFAULT_BRAND_RULES에 없는 신규 브랜드를 위한 규칙 필드.
    # category_mode: "category_sheets"(엑셀, 카테고리별 시트) 또는 "single_sheet"(일로형: 단일시트/스프레드시트)
    # sheet_mode: category_mode가 "category_sheets"일 때만 의미 있음.
    #   "fixed_today_offset"(오현형: 날짜별 시트 1개) 또는 "rolling_day_sheets"(태하형: 롤링 다중 시트)
    category_mode: str = "category_sheets"
    sheet_mode: str = "fixed_today_offset"
    categories: str = ""
    google_categories: str = ""
    rolling_days: int = 7
    today_offset: int = 1


UI_TYPE_OHYUN = "ohyun"
UI_TYPE_TAEHA = "taeha"
UI_TYPE_ILRO = "ilro"

UI_TYPE_LABELS = {
    UI_TYPE_OHYUN: "오현형 (날짜별 시트)",
    UI_TYPE_TAEHA: "태하형 (롤링 다중 시트)",
    UI_TYPE_ILRO: "일로형 (단일시트·스프레드시트)",
}


def ui_type_for_profile(profile: BrandProfile) -> str:
    if profile.category_mode == "single_sheet":
        return UI_TYPE_ILRO
    if profile.sheet_mode == "rolling_day_sheets":
        return UI_TYPE_TAEHA
    return UI_TYPE_OHYUN


def ui_type_for_brand(name: str, profiles: dict[str, "BrandProfile"] | None = None) -> str:
    rule = DEFAULT_BRAND_RULES.get(name)
    if rule is not None:
        return UI_TYPE_TAEHA if rule.mode == "rolling_day_sheets" else UI_TYPE_OHYUN
    profile = (profiles or {}).get(name)
    if profile is not None:
        return ui_type_for_profile(profile)
    return UI_TYPE_OHYUN


def rule_for_profile(profile: BrandProfile) -> BrandUploadRule | None:
    """profile 설정만으로 BrandUploadRule을 구성한다.

    DEFAULT_BRAND_RULES에 이미 등록된 브랜드(오현/태하)는 항상 그 하드코딩된
    규칙을 우선 사용한다(기존 동작 유지). 그 외 새 브랜드는 profile에 저장된
    유형/카테고리 설정으로 규칙을 만들어, 태하형(rolling_day_sheets)이라도
    코드 수정 없이 UI에서 바로 추가할 수 있게 한다.

    categories가 비어 있으면 None을 반환해 호출부가 기존의 CSV 기반 카테고리
    추론 fallback을 그대로 쓸 수 있게 한다.
    """
    existing = DEFAULT_BRAND_RULES.get(profile.name)
    if existing is not None:
        return existing
    if profile.category_mode == "single_sheet":
        # 일로형은 카테고리별로 나누지 않으므로 카테고리 목록이 없어도 된다.
        # 날짜 계산에만 mode/rolling_days/today_offset이 쓰인다.
        categories = _split_list(profile.categories) or ("__ALL__",)
    else:
        categories = _split_list(profile.categories)
        if not categories:
            return None
    google_categories = _split_list(profile.google_categories)
    mode = profile.sheet_mode or "fixed_today_offset"
    return BrandUploadRule(
        brand=profile.name,
        mode=mode,
        categories=categories,
        google_categories=google_categories,
        rolling_days=max(1, int(profile.rolling_days or 1)),
        today_offset=max(0, int(profile.today_offset or 1)),
        use_today_formula=(mode == "fixed_today_offset"),
    )


def _split_list(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in re.split(r"[,\n]", str(value or "")) if item.strip())


def resolve_app_path(path: str | Path) -> Path:
    value = Path(path)
    if value.is_absolute():
        return value
    candidates = [
        WORKSPACE_ROOT / value,
        WORKSPACE_ROOT.parent / value,
        Path.cwd() / value,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def load_profiles(path: str | Path = BRAND_PROFILES_PATH) -> dict[str, BrandProfile]:
    profile_path = Path(path)
    if not profile_path.exists():
        return {}
    data = json.loads(profile_path.read_text(encoding="utf-8-sig"))
    result: dict[str, BrandProfile] = {}
    for item in data.get("brands", []):
        profile = BrandProfile(**item)
        result[profile.name] = profile
    return result


def save_profiles(profiles: dict[str, BrandProfile], path: str | Path = BRAND_PROFILES_PATH) -> Path:
    profile_path = workspace_path(path)
    ensure_directory(profile_path.parent)
    data = {"brands": [asdict(profile) for profile in sorted(profiles.values(), key=lambda item: item.name)]}
    profile_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return profile_path


def brand_names_from_rules(path: str | Path) -> list[str]:
    rules_path = resolve_app_path(path)
    if not rules_path.exists() or rules_path.suffix.lower() != ".csv":
        return []
    with rules_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        names = {str(row.get("브랜드") or "").strip() for row in reader}
    return sorted(name for name in names if name)


def brand_names(*, rules_path: str | Path = "", profiles: dict[str, BrandProfile] | None = None) -> list[str]:
    names = set(DEFAULT_BRAND_RULES)
    if profiles:
        names.update(profiles)
    if rules_path:
        names.update(brand_names_from_rules(rules_path))
    return sorted(names)


def category_names_from_rules(path: str | Path, *, brand: str) -> tuple[str, ...]:
    rules_path = resolve_app_path(path)
    if not rules_path.exists() or rules_path.suffix.lower() != ".csv":
        return ()
    result: list[str] = []
    seen: set[str] = set()
    with rules_path.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            row_brand = str(row.get("브랜드") or "").strip()
            category = str(row.get("카테고리") or "").strip()
            if row_brand == brand and category and category not in seen:
                seen.add(category)
                result.append(category)
    return tuple(result)


def safe_name(value: str) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value).strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or "brand"


def yyyymmdd(value: str | date | datetime | None) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y%m%d")
        except ValueError:
            continue
    return date.today().strftime("%Y%m%d")


def default_upload_csv_path(*, brand: str, run_date: str | date | datetime | None, output_root: str | Path = DEFAULT_OUTPUT_ROOT) -> Path:
    folder = _output_root(output_root) / safe_name(brand) / yyyymmdd(run_date)
    return folder / f"{safe_name(brand)}_{yyyymmdd(run_date)}_upload_rows.csv"


def default_output_path(
    *,
    brand: str,
    run_date: str | date | datetime | None,
    template_path: str | Path = "",
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
) -> Path:
    suffix = Path(template_path).suffix.lower() if template_path else ".xlsx"
    if suffix not in {".xlsx", ".xlsb"}:
        suffix = ".xlsx"
    folder = _output_root(output_root) / safe_name(brand) / yyyymmdd(run_date)
    return folder / f"{safe_name(brand)}_{yyyymmdd(run_date)}{suffix}"


def _output_root(output_root: str | Path) -> Path:
    root = Path(output_root or DEFAULT_OUTPUT_ROOT)
    if root.is_absolute():
        return root
    if str(root).strip().lower() in {"outputs", ".\\outputs", "./outputs"}:
        return DEFAULT_OUTPUT_ROOT
    return DEFAULT_OUTPUT_ROOT / root


def workspace_path(path: str | Path) -> Path:
    return resolve_app_path(path)


def ensure_directory(path: str | Path) -> None:
    target = workspace_path(path)
    try:
        target.mkdir(parents=True, exist_ok=True)
        return
    except OSError:
        pass
    env = os.environ.copy()
    env["BRAND_UPLOAD_DIR"] = os.fspath(target)
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", "[System.IO.Directory]::CreateDirectory($env:BRAND_UPLOAD_DIR) | Out-Null"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=env,
    )
    if result.returncode != 0:
        raise OSError((result.stderr or result.stdout or f"directory create failed: {target}").strip())


def merge_profile(profile: BrandProfile, values: Iterable[tuple[str, str]]) -> BrandProfile:
    data = asdict(profile)
    for key, value in values:
        data[key] = value
    return BrandProfile(**data)
