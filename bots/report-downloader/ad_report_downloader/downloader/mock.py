"""
Mock downloader — Phase 0 only.

Simulates the full download flow with artificial delays so the
orchestrator ↔ UI signal path can be tested without a real browser.
"""
from __future__ import annotations
import random
import tempfile
import time
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext, Page

import utils.logger as log_mod
from downloader.base import BaseDownloader, DownloadResult
from utils.file_manager import build_destination_path, move_download


class MockDownloader(BaseDownloader):
    """Simulates a real media download for Phase-0 UI testing."""

    IMPLEMENTED = True  # Mock is always "implemented"

    def __init__(self, media_code: str, config: dict, account: dict | None = None,
                 fail_probability: float = 0.1):
        self.MEDIA_CODE = media_code
        super().__init__(config, account)
        self._fail_prob = fail_probability

    def run(
        self,
        context: "BrowserContext",  # may be None in mock mode
        start_date: date,
        end_date: date,
    ) -> DownloadResult:
        """Override: skips browser entirely."""
        label = f" [{self.account_name}]" if self.account_name else ""
        self._info(f"실행 시작 [테스트 모드]{label}")
        time.sleep(random.uniform(0.5, 1.2))

        if self._stop_requested:
            return self._skip("중지 요청")

        self._info("로그인 세션 확인 중")
        time.sleep(random.uniform(0.3, 0.7))

        self._info("보고서 메뉴 진입 중")
        time.sleep(random.uniform(0.4, 0.9))

        self._info(f"기간 설정: {start_date} ~ {end_date}")
        time.sleep(random.uniform(0.2, 0.5))

        # Simulate occasional failure
        if random.random() < self._fail_prob:
            self._error("다운로드 실패 [테스트 시뮬레이션]")
            return DownloadResult(
                media_code=self.MEDIA_CODE,
                error="테스트 시뮬레이션 실패",
            )

        self._info("다운로드 중")
        time.sleep(random.uniform(1.0, 2.0))

        # Create a minimal fake xlsx file
        tmp = Path(tempfile.mktemp(suffix=".xlsx"))
        tmp.write_bytes(b"PK\x03\x04" + b"\x00" * 128)

        if self.save_root:
            dest = build_destination_path(
                self.save_root, self.MEDIA_CODE, start_date, end_date, ".xlsx",
                account_name=self.account_name,
                brand_name=self.brand_name,
            )
            final = move_download(tmp, dest, overwrite=self.overwrite)
            self._info(f"✓ 완료: {final}")
        else:
            tmp.unlink(missing_ok=True)
            final = build_destination_path(
                ".", self.MEDIA_CODE, start_date, end_date, ".xlsx",
                account_name=self.account_name,
                brand_name=self.brand_name,
            )
            self._info("✓ 완료 (저장 경로 미설정 — 파일 미저장)")

        return DownloadResult(media_code=self.MEDIA_CODE, success=True, dest_path=final)

    # Required abstract methods (unused in mock)
    def check_login(self, page: "Page") -> bool:
        return True

    def navigate_to_report(self, page: "Page") -> None:
        pass

    def set_period(self, page: "Page", start: date, end: date) -> None:
        pass

    def trigger_download(self, page: "Page", start: date, end: date) -> Path:
        tmp = Path(tempfile.mktemp(suffix=".xlsx"))
        tmp.write_bytes(b"PK\x03\x04" + b"\x00" * 128)
        return tmp
