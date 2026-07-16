"""
Centralized logger.
Writes to a daily rotating log file and, when a UI callback is registered,
forwards messages to the PySide6 log panel via that callback.
"""
from __future__ import annotations
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

# ── Log file setup ───────────────────────────────────────────────────────────
_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_log_file = _LOG_DIR / f"app_{datetime.now().strftime('%Y%m%d')}.log"

# ── Log retention (2026-07-16) ───────────────────────────────────────────────
# 디버그 스냅샷(logs/debug의 png/html)이 실행마다 쌓여 수 GB까지 커지던 문제.
# 로거 임포트 시점(=프로그램 시작 시)에 보존 기간이 지난 파일을 자동 삭제한다.
_DEBUG_RETENTION_DAYS = 3   # 디버그 스냅샷 (문제 재현 확인용이므로 짧게)
_APP_LOG_RETENTION_DAYS = 30  # app_YYYYMMDD.log


def _cleanup_old_logs() -> None:
    import time as _time

    now = _time.time()
    debug_dir = _LOG_DIR / "debug"
    try:
        if debug_dir.exists():
            cutoff = now - _DEBUG_RETENTION_DAYS * 86400
            for path in debug_dir.iterdir():
                try:
                    if path.is_file() and path.stat().st_mtime < cutoff:
                        path.unlink()
                except OSError:
                    pass
        cutoff = now - _APP_LOG_RETENTION_DAYS * 86400
        for path in _LOG_DIR.glob("app_*.log"):
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                pass
    except OSError:
        pass


_cleanup_old_logs()

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(_log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)

# ── UI callback ───────────�