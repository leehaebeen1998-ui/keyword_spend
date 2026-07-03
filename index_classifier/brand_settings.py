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

from .brand_upload import DEFAULT_BRAND_RULES


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
    rules_path = Path(path)
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
    rules_path = Path(path)
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
    value = Path(path)
    return value if value.is_absolute() else WORKSPACE_ROOT / value


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
