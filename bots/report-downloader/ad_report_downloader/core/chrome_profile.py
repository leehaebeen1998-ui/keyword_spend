"""Resolve the Chrome profile used by Playwright."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEDICATED_MODE = "dedicated"
EXISTING_MODE = "existing"
VALID_MODES = {DEDICATED_MODE, EXISTING_MODE}


@dataclass(frozen=True)
class ChromeProfile:
    user_data_dir: Path
    profile_directory: str | None
    mode: str

    @property
    def label(self) -> str:
        if self.mode == DEDICATED_MODE:
            return f"전용 자동화 프로필 ({self.user_data_dir})"
        return f"기존 Chrome 프로필 ({self.profile_directory})"

    def launch_args(self) -> list[str]:
        if self.profile_directory:
            return [f"--profile-directory={self.profile_directory}"]
        return []


def resolve_chrome_profile(config: dict, app_dir: Path | None = None) -> ChromeProfile:
    """Return a validated profile selection without modifying profile data."""
    chrome = config.get("chrome", {})
    mode = chrome.get("profile_mode", DEDICATED_MODE)
    if mode not in VALID_MODES:
        raise ValueError(f"지원하지 않는 Chrome 프로필 방식입니다: {mode}")

    if mode == DEDICATED_MODE:
        root = app_dir or Path(__file__).resolve().parents[1]
        return ChromeProfile(root / "chrome_profile", None, mode)

    user_data_dir = str(chrome.get("user_data_dir", "")).strip()
    profile_directory = str(chrome.get("profile_directory", "")).strip()
    if not user_data_dir or not profile_directory:
        raise ValueError("기존 Chrome 프로필 경로와 프로필 폴더를 모두 설정해주세요.")

    root = Path(user_data_dir)
    if not root.is_dir() or not (root / "Local State").is_file():
        raise ValueError(f"올바른 Chrome User Data 경로가 아닙니다: {root}")
    if not (root / profile_directory).is_dir():
        raise ValueError(f"Chrome 프로필 폴더가 없습니다: {profile_directory}")

    return ChromeProfile(root, profile_directory, mode)
