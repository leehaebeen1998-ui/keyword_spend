"""
Abstract base class for all media downloaders.

Subclasses must:
    - Set MEDIA_CODE = "naver" (etc.)
    - Set IMPLEMENTED = True when fully implemented
    - Override: check_login, navigate_to_report, set_period, trigger_download

The base class handles:
    - Retry loop (config-driven max_attempts)
    - Logging (via utils.logger)
    - Exception isolation (no single media failure stops the run)
    - Screenshot capture on failure for diagnosis
    - File move via utils.file_manager
"""
from __future__ import annotations
import random
import time
from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext, Page

import utils.logger as log_mod
from utils.file_manager import build_destination_path, move_download


# ──────────────────────────────────────────────────────────────────────────────
# Result
# ──────────────────────────────────────────────────────────────────────────────
class DownloadResult:
    def __init__(
        self,
        media_code: str,
        success: bool = False,
        dest_path: Path | None = None,
        error: str = "",
        skipped: bool = False,
        skip_reason: str = "",
        login_required: bool = False,
    ):
        self.media_code = media_code
        self.success = success
        self.dest_path = dest_path
        self.error = error
        self.skipped = skipped
        self.skip_reason = skip_reason
        self.login_required = login_required

    @property
    def status_label(self) -> str:
        if self.skipped:
            return f"skipped ({self.skip_reason})"
        return "success" if self.success else f"failed ({self.error})"

    def __repr__(self) -> str:
        return f"DownloadResult({self.media_code}, {self.status_label})"


# ──────────────────────────────────────────────────────────────────────────────
# Custom exceptions
# ──────────────────────────────────────────────────────────────────────────────
class LoginRequiredError(Exception):
    """Raised when the media page redirects to a login screen."""


class EmptyDataError(Exception):
    """Raised when the report period has no data (download button disabled, etc.)."""


# ──────────────────────────────────────────────────────────────────────────────
# Base downloader
# ──────────────────────────────────────────────────────────────────────────────
class BaseDownloader(ABC):
    """Abstract base for all media downloaders."""

    MEDIA_CODE: str = ""
    IMPLEMENTED: bool = False  # Set to True in a fully implemented subclass

    def __init__(self, config: dict, account: dict | None = None):
        """
        Parameters
        ----------
        config  : 전체 config dict
        account : 이번 실행에 해당하는 계정 정보
                  {"account_id": "...", "account_name": "...", "report_name": "..."}
                  None 이면 media 레벨 기본값 사용 (하위 호환)
        """
        self.config = config
        self.account: dict = account or {}
        _media_cfg = config.get("media", {}).get(self.MEDIA_CODE, {})
        _acct = self.account

        # 계정별 값 우선, 없으면 media 레벨 fallback
        self.timeout_sec:  int  = _media_cfg.get("timeout_sec", 90)
        self.report_name:  str  = (_acct.get("report_name") or _media_cfg.get("report_name", "")).strip()
        self.account_id:   str  = (_acct.get("account_id") or "").strip()
        self.account_name: str  = (_acct.get("account_name") or self.account_id or "").strip()

        self.max_attempts: int  = config.get("retry", {}).get("max_attempts", 2)
        self.overwrite:    bool = False
        self.save_root:    str  = config.get("save_root_path", "")
        self.brand_name:   str  = (_acct.get("brand_name") or config.get("brand_name") or "").strip()
        self._stop_requested = False

    # ── Public API (called by Orchestrator) ──────────────────────────────────

    def run(
        self,
        context: "BrowserContext",
        start_date: date,
        end_date: date,
    ) -> DownloadResult:
        """
        Entry point called by the orchestrator.
        Opens a new tab, executes the download flow, closes the tab.
        Handles retry loop and all exceptions.
        """
        label = f" [{self.account_name}]" if self.account_name else ""
        self._info(f"실행 시작{label}")

        for attempt in range(1, self.max_attempts + 1):
            if self._stop_requested:
                return self._skip("중지 요청")

            page: Page | None = None
            try:
                page = context.new_page()
                result = self._attempt(page, start_date, end_date, attempt)
                return result

            except LoginRequiredError:
                self._error("로그인 필요 — 해당 매체를 건너뜁니다")
                if page:
                    self._screenshot(page, "login_required")
                return self._skip("로그인 필요", login_required=True)

            except EmptyDataError:
                self._warn("데이터 없음 — 해당 기간 집행 내역 없음")
                return self._skip("데이터 없음")

            except Exception as e:
                self._error(f"시도 {attempt}/{self.max_attempts} 실패: {e}")
                if page:
                    self._screenshot(page, f"error_attempt{attempt}")
                if attempt < self.max_attempts:
                    wait = round(random.uniform(2.0, 4.0), 1)
                    self._info(f"{wait}초 후 재시도")
                    time.sleep(wait)

            finally:
                if page:
                    try:
                        page.close()
                    except Exception:
                        pass

        self._error(f"{self.max_attempts}회 재시도 후 최종 실패")
        return DownloadResult(
            media_code=self.MEDIA_CODE,
            error=f"{self.max_attempts}회 재시도 후 실패",
        )

    def request_stop(self) -> None:
        """Signal the downloader to stop after the current safe point."""
        self._stop_requested = True

    # ── Abstract methods (subclasses implement) ──────────────────────────────

    @abstractmethod
    def check_login(self, page: "Page") -> bool:
        """
        Navigate to the media's management URL and verify the session.
        Return True if logged in. Raise LoginRequiredError (or return False) if not.
        """

    @abstractmethod
    def navigate_to_report(self, page: "Page") -> None:
        """Navigate from the landing page to the target report screen."""

    @abstractmethod
    def set_period(self, page: "Page", start: date, end: date) -> None:
        """Set start/end dates in the report UI."""

    @abstractmethod
    def trigger_download(self, page: "Page", start: date, end: date) -> Path:
        """
        Click download and wait for the file using page.expect_download().
        Return the path to Playwright's temporary file.
        """

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _attempt(self, page: "Page", start: date, end: date, attempt: int) -> DownloadResult:
        if attempt > 1:
            self._info(f"재시도 {attempt}/{self.max_attempts}")

        self._info("로그인 세션 확인 중")
        if not self.check_login(page):
            raise LoginRequiredError()

        self._info("보고서 메뉴 진입 중")
        self.navigate_to_report(page)

        self._info(f"기간 설정: {start} ~ {end}")
        self.set_period(page, start, end)

        self._info("다운로드 실행")
        tmp_path = self.trigger_download(page, start, end)

        dest = build_destination_path(
            self.save_root, self.MEDIA_CODE, start, end, tmp_path.suffix,
            account_name=self.account_name,
            brand_name=self.brand_name,
        )
        self._info(f"파일 이동 중 → {dest}")
        final = move_download(tmp_path, dest, overwrite=self.overwrite)
        self._info(f"✓ 완료: {final}")

        return DownloadResult(media_code=self.MEDIA_CODE, success=True, dest_path=final)

    def _skip(self, reason: str, login_required: bool = False) -> DownloadResult:
        return DownloadResult(
            media_code=self.MEDIA_CODE,
            skipped=True,
            skip_reason=reason,
            login_required=login_required,
        )

    def _screenshot(self, page: "Page", label: str) -> None:
        """Save a debug screenshot + page HTML for diagnosis (PRD §4.4)."""
        try:
            from datetime import datetime
            debug_dir = Path("logs") / "debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            png = debug_dir / f"{self.MEDIA_CODE}_{label}_{ts}.png"
            html = debug_dir / f"{self.MEDIA_CODE}_{label}_{ts}.html"
            page.screenshot(path=str(png), full_page=True)
            html.write_text(page.content(), encoding="utf-8")
            self._info(f"디버그 저장: {png.name}")
        except Exception:
            pass

    # ── Logging shorthands ───────────────────────────────────────────────────

    def _info(self, msg: str) -> None:
        log_mod.log_info(self.MEDIA_CODE, msg)

    def _warn(self, msg: str) -> None:
        log_mod.log_warning(self.MEDIA_CODE, msg)

    def _error(self, msg: str) -> None:
        log_mod.log_error(self.MEDIA_CODE, msg)

    # ── Utility ──────────────────────────────────────────────────────────────

    @staticmethod
    def human_delay(min_ms: int = 300, max_ms: int = 900) -> None:
        """Random delay to reduce bot-detection risk (PRD §4.5)."""
        time.sleep(random.randint(min_ms, max_ms) / 1000)
