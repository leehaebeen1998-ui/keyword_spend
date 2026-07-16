"""
File naming, folder creation, and file-move utilities.

Folder rule:
    {save_root}/{brand_name}/{MediaFolder}/{YYYYMMDD}/일별 로우/

Naming rule:
    {media_code}_{account_name}_raw_{start_date}_{end_date}.{ext}
    If the same name already exists, _002, _003 ... is appended.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path


_MEDIA_FOLDER: dict[str, str] = {
    "naver": "Naver",
    "google": "Google",
    "google_sa": "Google SA",
    "google_da": "Google DA",
    "meta": "Meta",
    "kakao": "Kakao",
    "adn": "ADN",
    "mobion_banner": "Mobion Banner",
    "mobion_daily": "Mobion Daily",
    "x": "X",
    "google_analytics": "GA4",
}


def _safe_path_part(name: str, fallback: str = "미지정") -> str:
    value = (name or "").strip() or fallback
    value = re.sub(r'[\\/:*?"<>|]', "_", value)
    value = re.sub(r"\s+", "_", value)
    return value[:60]


def _safe_filename(name: str) -> str:
    return _safe_path_part(name, fallback="")[:40]


def validate_save_root(save_root_path: str) -> tuple[bool, str]:
    if not save_root_path:
        return False, "저장 경로를 입력해주세요."
    root = Path(save_root_path)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return False, f"저장 경로를 만들 수 없습니다: {exc}"
    if not root.is_dir():
        return False, f"저장 경로가 폴더가 아닙니다: {save_root_path}"
    return True, ""


def build_destination_path(
    save_root: str,
    media_code: str,
    start: date,
    end: date,
    ext: str,
    run_date: date | None = None,
    account_name: str = "",
    brand_name: str = "",
) -> Path:
    """Return the destination path for a downloaded raw report file."""
    if run_date is None:
        run_date = date.today()

    if not ext.startswith("."):
        ext = "." + ext

    media_folder = _MEDIA_FOLDER.get(media_code, media_code.capitalize())
    date_folder = run_date.strftime("%Y%m%d")
    start_str = start.strftime("%Y%m%d")
    end_str = end.strftime("%Y%m%d")

    safe_account = _safe_filename(account_name) if account_name else ""
    account_part = f"_{safe_account}" if safe_account else ""
    filename = f"{media_code}{account_part}_raw_{start_str}_{end_str}{ext}"

    return (
        Path(save_root)
        / _safe_path_part(brand_name, fallback="브랜드명_미설정")
        / media_folder
        / date_folder
        / "일별 로우"
        / filename
    )


def unique_destination_path(dest_path: Path) -> Path:
    """Return a non-existing path by appending _002, _003 ... when needed."""
    if not dest_path.exists():
        return dest_path

    stem = dest_path.stem
    suffix = dest_path.suffix
    parent = dest_path.parent
    for index in range(2, 1000):
        candidate = parent / f"{stem}_{index:03d}{suffix}"
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"동일 이름 파일이 너무 많습니다: {dest_path}")


def move_download(tmp_path: Path, dest_path: Path, overwrite: bool = False) -> Path:
    """
    Move a Playwright temporary download to the destination.

    The project now keeps every downloaded raw file. The overwrite argument is
    accepted for backward compatibility, but existing files are not deleted.
    """
    if not tmp_path.exists():
        raise FileNotFoundError(f"임시 다운로드 파일을 찾을 수 없습니다: {tmp_path}")

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    final_path = unique_destination_path(dest_path)
    tmp_path.replace(final_path)

    if not final_path.exists() or final_path.stat().st_size == 0:
        raise RuntimeError(f"저장된 파일이 비어 있습니다: {final_path}")
    return final_path
