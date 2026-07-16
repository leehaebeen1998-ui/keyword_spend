"""
Config schema: default values, media metadata, and validation helpers.
"""
from __future__ import annotations

import json
from pathlib import Path


DEFAULT_ACCOUNT = {"account_id": "", "account_name": "", "report_name": ""}


DEFAULT_CONFIG: dict = {
    "chrome": {
        "user_data_dir": "",
        "profile_directory": "Default",
    },
    "active_brand": "",
    "brands": [],          # [{"name": "브랜드명", "media": {...}}, ...]
    "brand_name": "",      # 하위 호환: active brand name 복사본 (base.py 참조용)
    "save_root_path": str(Path.home() / "보고서 다운로드"),
    "last_run_period": {"start": "", "end": ""},
    "media": {
        "naver": {
            "enabled": True,
            "timeout_sec": 90,
            "accounts": [{"account_id": "", "account_name": "", "report_name": "다차원보고서"}],
        },
        "google_sa": {
            "enabled": False,
            "timeout_sec": 120,
            "accounts": [{"account_id": "", "account_name": "", "report_name": "캠페인 성과"}],
        },
        "google_da": {
            "enabled": False,
            "timeout_sec": 120,
            "accounts": [{"account_id": "", "account_name": "", "report_name": "캠페인 성과"}],
        },
        "meta": {
            "enabled": False,
            "timeout_sec": 120,
            "accounts": [{"account_id": "", "account_name": "", "report_name": "일별 성과"}],
        },
        "kakao": {
            "enabled": False,
            "timeout_sec": 90,
            "login_id": "eodls1489@naver.com",
            "accounts": [{"account_id": "", "account_name": "", "report_name": "광고성과"}],
        },
        "adn": {
            "enabled": False,
            "timeout_sec": 90,
            "login_id": "giomglobal",
            "accounts": [{"account_id": "", "account_name": "", "report_name": "광고성과"}],
        },
        "mobion_banner": {
            "enabled": False,
            "timeout_sec": 120,
            "accounts": [{"account_id": "", "account_name": "", "report_name": "통합배너"}],
        },
        "mobion_daily": {
            "enabled": False,
            "timeout_sec": 120,
            "accounts": [{"account_id": "", "account_name": "", "report_name": "일자별"}],
        },
        "x": {
            "enabled": False,
            "timeout_sec": 180,
            "accounts": [{"account_id": "18ce55ve4wu", "account_name": "lawterdrug", "report_name": "캠페인 성과"}],
        },
        "google_analytics": {
            "enabled": False,
            "timeout_sec": 120,
            "accounts": [DEFAULT_ACCOUNT.copy()],
        },
        "gfa": {
            "enabled": False,
            "timeout_sec": 300,
            "accounts": [
                {
                    "account_id": "",
                    "account_name": "",
                    "report_name": "성과 보고서",
                    "analysis_unit": "광고 계정",
                    "period_unit": "일",
                    "placement": "전체",
                    "audience": "전체",
                    "column_preset": "",
                }
            ],
        },
    },
    "retry": {"max_attempts": 2},
    "overwrite_existing_file": False,
}


MEDIA_LABELS: dict[str, str] = {
    "naver": "Naver 검색광고",
    "google_sa": "Google SA",
    "google_da": "Google DA",
    "meta": "Meta (Facebook/Instagram)",
    "kakao": "Kakao 광고",
    "adn": "ADN",
    "mobion_banner": "모비온 (통합 배너)",
    "mobion_daily": "모비온 (일자별)",
    "x": "X (Twitter) Ads",
    "google_analytics": "Google Analytics 4",
    "gfa": "Naver GFA (디스플레이 광고)",
}


MEDIA_ORDER: list[str] = [
    "naver",
    "google_sa",
    "google_da",
    "meta",
    "kakao",
    "adn",
    "mobion_banner",
    "mobion_daily",
    "x",
    "google_analytics",
    "gfa",
]


LEGACY_MEDIA_ALIASES: dict[str, str] = {
    "google": "google_sa",
}


def validate_chrome_settings(user_data_dir: str, profile_directory: str) -> tuple[bool, str]:
    if not user_data_dir:
        return False, "Chrome User Data 경로를 입력해주세요."
    udd = Path(user_data_dir)
    if not udd.is_dir():
        return False, "경로가 존재하지 않습니다:\n" + user_data_dir
    if not (udd / "Local State").exists():
        return False, "Chrome User Data 폴더가 아닙니다 (Local State 없음):\n" + user_data_dir
    if profile_directory and not (udd / profile_directory).is_dir():
        return False, "프로필 폴더가 존재하지 않습니다: " + profile_directory
    return True, ""


def validate_save_path(save_root_path: str) -> tuple[bool, str]:
    if not save_root_path:
        return False, "저장 경로를 입력해주세요."
    path = Path(save_root_path)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return False, "저장 경로를 만들 수 없습니다: " + str(exc)
    return True, ""


def read_chrome_profiles(user_data_dir: str) -> dict[str, str]:
    """
    Return Chrome profile display names and folder names.

    Example:
        {"기본 프로필 (Default)": "Default", "프로필 4 (Profile 4)": "Profile 4"}
    """
    profiles: dict[str, str] = {}
    udd = Path(user_data_dir)
    if not udd.is_dir():
        return {"Default": "Default"}

    for child in sorted(udd.iterdir()):
        if not child.is_dir():
            continue
        folder_name = child.name
        if folder_name != "Default" and not (
            folder_name.startswith("Profile ") and folder_name[8:].isdigit()
        ):
            continue

        prefs_file = child / "Preferences"
        if not prefs_file.exists():
            continue

        display_name = folder_name
        try:
            with prefs_file.open(encoding="utf-8", errors="replace") as file:
                prefs = json.load(file)
            display_name = (
                prefs.get("profile", {}).get("name")
                or (prefs.get("account_info") or [{}])[0].get("full_name")
                or folder_name
            )
        except Exception:
            display_name = folder_name

        profiles[f"{display_name} ({folder_name})"] = folder_name

    return profiles or {"Default": "Default"}
