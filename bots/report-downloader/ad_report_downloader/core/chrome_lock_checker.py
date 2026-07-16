"""
Detects whether the target Chrome profile is currently occupied.

Windows: Chrome uses 'lockfile' (not SingletonLock which is Linux/Mac only).
Fallback: check if chrome.exe has the profile directory open via psutil.
"""
from __future__ import annotations
import subprocess
import sys
import time
from pathlib import Path


def kill_chrome_processes(timeout_sec: float = 5.0) -> int:
    """
    Windows에서 모든 chrome.exe 프로세스를 강제 종료한다.
    종료된 프로세스 수를 반환한다 (0 = 이미 실행 중이지 않음).
    """
    if sys.platform != "win32":
        return 0

    try:
        result = subprocess.run(
            ["taskkill", "/F", "/IM", "chrome.exe", "/T"],
            capture_output=True,
            text=True,
        )
        # 종료 성공 여부: returncode 0 = 종료됨, 128 = 프로세스 없음
        killed = result.returncode == 0
        if killed:
            time.sleep(timeout_sec)   # 프로세스가 완전히 정리될 때까지 대기
        return 1 if killed else 0
    except Exception:
        return 0


def is_profile_locked(user_data_dir: str, profile_directory: str) -> bool:
    """
    Returns True if Chrome appears to have the profile open.

    - Windows: checks 'lockfile' in the profile directory
    - Linux/Mac: checks 'SingletonLock'
    - Fallback: tries to open the lockfile exclusively (Windows file lock)
    """
    if not user_data_dir or not profile_directory:
        return False

    profile_dir = Path(user_data_dir) / profile_directory

    # Windows: 'lockfile' (Chrome 73+)
    # Linux/Mac: 'SingletonLock'
    candidates = ["lockfile", "SingletonLock"]

    for name in candidates:
        lock = profile_dir / name
        if not lock.exists():
            continue

        if sys.platform == "win32":
            # On Windows, try to open the lockfile exclusively.
            # Chrome holds it open; if we can open it, Chrome isn't using it.
            try:
                import msvcrt
                with open(lock, "rb") as f:
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                # Could open → not locked
            except (OSError, IOError):
                # Could NOT open → Chrome has it locked
                return True
        else:
            # Unix: file existence means locked
            return True

    return False


def lock_path(user_data_dir: str, profile_directory: str) -> Path:
    """Return the Windows lockfile path (preferred on Windows)."""
    profile_dir = Path(user_data_dir) / profile_directory
    if sys.platform == "win32":
        return profile_dir / "lockfile"
    return profile_dir / "SingletonLock"
