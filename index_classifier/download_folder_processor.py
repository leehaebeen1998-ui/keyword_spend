from __future__ import annotations

import csv
import io
import re
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .raw_upload_builder import UPLOAD_FIELDS, build_ilo_merged_upload_rows, build_upload_rows_from_raw, sort_upload_rows
from .schedule_rules import parse_date


RAW_SUFFIXES = {".csv", ".tsv"}
SKIP_NAME_TOKENS = ("upload_rows", "cleaned", "failed", "index-log", "index_log")


@dataclass(frozen=True)
class RawFilePlan:
    path: Path
    media: str


@dataclass(frozen=True)
class FolderProcessResult:
    output_path: Path
    raw_files: list[RawFilePlan] = field(default_factory=list)
    total_rows: int = 0
    category_counts: dict[str, int] = field(default_factory=dict)
    skipped_files: list[Path] = field(default_factory=list)
    duplicate_rows: int = 0


def discover_raw_files(
    root: str | Path,
    *,
    media_filter: str | None = None,
    folder_date: str | None = None,
) -> tuple[list[RawFilePlan], list[Path]]:
    root_path = Path(root)
    if not root_path.exists():
        raise FileNotFoundError(f"download folder not found: {root_path}")

    plans: list[RawFilePlan] = []
    skipped: list[Path] = []
    for path in sorted(root_path.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in RAW_SUFFIXES:
            continue
        if folder_date and folder_date not in path.as_posix().replace("\\", "/"):
            skipped.append(path)
            continue
        lowered = path.name.lower()
        if any(token in lowered for token in SKIP_NAME_TOKENS):
            skipped.append(path)
            continue
        media = infer_media(path)
        if not media:
            skipped.append(path)
            continue
        if media_filter and media.casefold() != media_filter.casefold():
            continue
        plans.append(RawFilePlan(path=path, media=media))
    return plans, skipped


def infer_media(path: Path) -> str:
    text = " ".join(path.parts).lower().replace("\\", "/")
    name = path.name.lower()
    if "google sa" in text or "google_sa" in text or name.startswith("google_sa"):
        return "Google SA"
    if "/naver/" in text or "naver" in name:
        return "Naver"
    if "일로 데일리" in path.name:
        return "Naver"
    return ""


def process_download_folder(
    *,
    brand: str,
    download_folder: str | Path,
    rules_path: str | Path,
    output_path: str | Path,
    media_filter: str | None = None,
    folder_date: str | None = None,
) -> FolderProcessResult:
    date_token = parse_date(folder_date).strftime("%Y%m%d") if folder_date else None
    plans, skipped = discover_raw_files(download_folder, media_filter=media_filter, folder_date=date_token)
    if not plans:
        date_hint = f" ({date_token} 폴더 기준)" if date_token else ""
        available_dates = _discover_date_tokens(download_folder)
        available_hint = f" 발견된 날짜 폴더: {', '.join(available_dates)}" if available_dates else ""
        raise FileNotFoundError(f"처리할 raw 파일을 찾을 수 없습니다{date_hint}: {Path(download_folder)}{available_hint}")

    all_rows: list[dict[str, Any]] = []
    consumed: set[Path] = set()
    if _uses_ilo_merge(brand):
        for keyword_plan, search_plan in _ilo_pairs(plans):
            consumed.add(keyword_plan.path)
            consumed.add(search_plan.path)
            all_rows.extend(
                build_ilo_merged_upload_rows(
                    brand=brand,
                    media=search_plan.media,
                    keyword_path=keyword_plan.path,
                    search_path=search_plan.path,
                    rules_path=rules_path,
                )
            )

    for plan in plans:
        if plan.path in consumed:
            continue
        all_rows.extend(
            build_upload_rows_from_raw(
                brand=brand,
                media=plan.media,
                input_path=plan.path,
                rules_path=rules_path,
            )
        )

    duplicate_rows = _count_duplicate_upload_rows(all_rows)
    all_rows = sort_upload_rows(all_rows)
    if not all_rows:
        raise ValueError("raw 파일은 찾았지만 변환된 행이 없습니다. 규칙 파일 또는 raw 헤더를 확인해 주세요.")

    output = Path(output_path)
    write_upload_rows(output, all_rows)
    counts: dict[str, int] = {}
    for row in all_rows:
        category = str(row.get("category") or "")
        counts[category] = counts.get(category, 0) + 1
    return FolderProcessResult(
        output_path=output,
        raw_files=plans,
        total_rows=len(all_rows),
        category_counts=counts,
        skipped_files=skipped,
        duplicate_rows=duplicate_rows,
    )


def _uses_ilo_merge(brand: str) -> bool:
    text = str(brand).casefold().replace(" ", "")
    return text in {"lawyergeon:naver", "법무법인일로2", "법무법인일로3"} or "일로" in text


def _ilo_pairs(plans: list[RawFilePlan]) -> list[tuple[RawFilePlan, RawFilePlan]]:
    groups: dict[str, dict[str, RawFilePlan]] = {}
    for plan in plans:
        name = plan.path.name
        if "일로 데일리 소진액_ver" not in name:
            continue
        key = _ilo_account_key(plan.path)
        if not key:
            continue
        version = "ver2" if "ver2" in name else "ver3" if "ver3" in name else ""
        if not version:
            continue
        groups.setdefault(key, {})[version] = plan
    return [
        (group["ver2"], group["ver3"])
        for group in groups.values()
        if "ver2" in group and "ver3" in group
    ]


def _ilo_account_key(path: Path) -> str:
    match = re.search(r",(\d+)(?:\.[^.]+)?$", path.name)
    return match.group(1) if match else ""


def write_upload_rows(output_path: str | Path, rows: list[dict[str, Any]]) -> None:
    output = Path(output_path)
    _ensure_directory(output.parent)
    content = io.StringIO(newline="")
    writer = csv.DictWriter(content, fieldnames=list(UPLOAD_FIELDS), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    _write_text_via_temp_copy(output, content.getvalue(), encoding="utf-8-sig")


def _ensure_directory(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return
    except OSError:
        pass
    env = os.environ.copy()
    env["BRAND_UPLOAD_DIR"] = os.fspath(path)
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
        raise OSError((result.stderr or result.stdout or f"directory create failed: {path}").strip())


def _write_text_via_temp_copy(path: Path, content: str, *, encoding: str) -> None:
    try:
        path.write_text(content, encoding=encoding, newline="")
        return
    except OSError:
        pass

    with tempfile.NamedTemporaryFile("w", encoding=encoding, newline="", delete=False, suffix=path.suffix or ".tmp") as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        env = os.environ.copy()
        env["BRAND_UPLOAD_SRC"] = os.fspath(tmp_path)
        env["BRAND_UPLOAD_DST"] = os.fspath(path)
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "$dir=[System.IO.Path]::GetDirectoryName($env:BRAND_UPLOAD_DST); "
                "[System.IO.Directory]::CreateDirectory($dir) | Out-Null; "
                "Copy-Item -LiteralPath $env:BRAND_UPLOAD_SRC -Destination $env:BRAND_UPLOAD_DST -Force",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=env,
        )
        if result.returncode != 0:
            raise OSError((result.stderr or result.stdout or f"file write failed: {path}").strip())
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


def _count_duplicate_upload_rows(rows: list[dict[str, Any]]) -> int:
    seen: set[tuple[str, ...]] = set()
    duplicate_count = 0
    fields = tuple(UPLOAD_FIELDS)
    for row in rows:
        key = tuple(str(row.get(field, "")).strip() for field in fields)
        if key in seen:
            duplicate_count += 1
        else:
            seen.add(key)
    return duplicate_count


def _discover_date_tokens(root: str | Path) -> list[str]:
    root_path = Path(root)
    if not root_path.exists():
        return []
    tokens: set[str] = set()
    for path in root_path.rglob("*"):
        for part in path.parts:
            if re.fullmatch(r"20\d{6}", part):
                tokens.add(part)
    return sorted(tokens)
