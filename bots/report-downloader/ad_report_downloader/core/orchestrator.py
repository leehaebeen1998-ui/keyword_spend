"""
OrchestratorWorker — QThread that runs all media downloaders sequentially.

Design rules (PRD §5.1):
• Playwright sync API runs ONLY inside this thread.
• UI is updated exclusively via Qt Signals — never by calling UI methods directly.
• A single BrowserContext is shared across all media tabs;
  each downloader opens/closes its own tab.
• 다중 계정: 각 매체의 accounts 리스트를 순차 실행
  진행 단위 = (매체, 계정) 쌍의 총 개수

[패치 내역 - manifest 출력]
• _download_results 수집 (_run_all 루프 안)
• _write_manifest() 메서드 추가 — 다운로드 완료 후 manifest.json 저장
• manifest를 읽는 후처리는 별도 파츠(run_pipeline.py)에서 독립 실행
"""
from __future__ import annotations
from datetime import date
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Signal

from config_schema import MEDIA_ORDER
import utils.logger as log_mod

if TYPE_CHECKING:
    from downloader.base import BaseDownloader, DownloadResult

# media_code → 파이프라인 표준 매체명 매핑
_MEDIA_CODE_TO_NAME: dict[str, str] = {
    "naver":             "Naver",
    "google_sa":         "Google SA",
    "google_da":         "Google DA",
    "meta":              "Meta",
    "kakao":             "Kakao SA",
    "adn":               "ADN",
    "mobion_banner":     "Mobion",
    "mobion_daily":      "Mobion",
    "x":                 "X",
    "google_analytics":  "GA4",
    "gfa":               "GFA DB",
}

# ──────────────────────────────────────────────────────────────────────────────
# Run parameters (plain data object passed to the worker at construction)
# ──────────────────────────────────────────────────────────────────────────────
class RunParams:
    def __init__(
        self,
        start_date: date,
        end_date: date,
        enabled_media: list[str],
        config: dict,
        use_mock: bool = True,
    ):
        self.start_date = start_date
        self.end_date = end_date
        self.enabled_media = enabled_media
        self.config = config
        self.use_mock = use_mock

# ──────────────────────────────────────────────────────────────────────────────
# Account list helper
# ──────────────────────────────────────────────────────────────────────────────
def _get_accounts(media_cfg: dict) -> list[dict]:
    """
    accounts 배열 반환. 구 형식(account_id 단일 필드)도 자동 변환.
    빈 계정(account_id·account_name 모두 공백)도 최소 1개는 반환하여
    account_id 없이 실행되는 매체도 정상 동작.
    """
    accounts = media_cfg.get("accounts")
    if accounts:
        return list(accounts)  # 신 형식

    # 하위 호환: 구 형식 config.json
    return [{
        "account_id":   media_cfg.get("account_id", "").strip(),
        "account_name": "",
        "report_name":  media_cfg.get("report_name", ""),
    }]

# ──────────────────────────────────────────────────────────────────────────────
# Downloader factory
# ──────────────────────────────────────────────────────────────────────────────
def _build_downloader(media_code: str, config: dict, account: dict,
                      use_mock: bool) -> "BaseDownloader":
    """
    Return the appropriate downloader for the given media code and account.
    Falls back to MockDownloader if the real one is not yet implemented.
    """
    from downloader.mock import MockDownloader

    if use_mock:
        return MockDownloader(media_code, config, account)

    _real_cls = None
    try:
        if media_code == "naver":
            from downloader.naver import NaverDownloader as _real_cls          # type: ignore
        elif media_code == "google":
            from downloader.google import GoogleDownloader as _real_cls        # type: ignore
        elif media_code == "google_sa":
            from downloader.google_sa import GoogleSaDownloader as _real_cls  # type: ignore
        elif media_code == "google_da":
            from downloader.google_da import GoogleDaDownloader as _real_cls  # type: ignore
        elif media_code == "meta":
            from downloader.meta import MetaDownloader as _real_cls            # type: ignore
        elif media_code == "kakao":
            from downloader.kakao import KakaoDownloader as _real_cls          # type: ignore
        elif media_code == "adn":
            from downloader.adn import AdnDownloader as _real_cls              # type: ignore
        elif media_code == "mobion_banner":
            from downloader.mobion_banner import MobionBannerDownloader as _real_cls  # type: ignore
        elif media_code == "mobion_daily":
            from downloader.mobion_daily import MobionDailyDownloader as _real_cls   # type: ignore
        elif media_code == "x":
            from downloader.x_ads import XAdsDownloader as _real_cls          # type: ignore
        elif media_code == "google_analytics":
            from downloader.google_analytics import GoogleAnalyticsDownloader as _real_cls  # type: ignore
        elif media_code == "gfa":
            from downloader.gfa import GFADownloader as _real_cls              # type: ignore
    except ImportError:
        pass

    if _real_cls is not None and getattr(_real_cls, "IMPLEMENTED", False):
        return _real_cls(config, account)

    log_mod.log_warning(media_code, "실제 다운로더 미구현 — 테스트 모드로 실행")
    return MockDownloader(media_code, config, account)

# ──────────────────────────────────────────────────────────────────────────────
# Worker thread
# ──────────────────────────────────────────────────────────────────────────────
class OrchestratorWorker(QThread):
    """
    Runs in a background thread.
    The UI connects to the signals below; the worker never touches UI widgets.
    """

    # Signals ─────────────────────────────────────────────────────────────────
    log_message          = Signal(str, str, str)   # timestamp, media_code, message
    media_status_changed = Signal(str, str)         # media_code, status
    progress_updated     = Signal(int, int)         # completed_count, total_count
    run_finished         = Signal(dict)             # {media_code: "success"|"failed"|"skipped"|"error"}
    login_required       = Signal(str)              # media_code

    def __init__(self, params: RunParams, parent=None):
        super().__init__(parent)
        self._params = params
        self._stop_requested = False
        self._current: "BaseDownloader | None" = None
        self._download_results: list[dict] = []   # manifest 출력용 결과 수집

    def request_stop(self) -> None:
        """Ask the worker to stop gracefully after the current media finishes."""
        self._stop_requested = True
        if self._current:
            self._current.request_stop()

    # ── QThread entry point ──────────────────────────────────────────────────
    def run(self) -> None:
        params = self._params
        enabled = [m for m in MEDIA_ORDER if m in params.enabled_media]
        summary: dict[str, str] = {}
        self._download_results = []

        log_mod.set_ui_callback(self._emit_log)

        try:
            if not self._preflight(params, summary):
                self.run_finished.emit(summary)
                return

            if params.use_mock:
                self._run_all(None, enabled, summary, params)
            else:
                from playwright.sync_api import sync_playwright
                from core.chrome_profile import resolve_chrome_profile

                profile = resolve_chrome_profile(params.config)
                profile.user_data_dir.mkdir(parents=True, exist_ok=True)

                chrome_exe = self._find_chrome_exe()
                self._emit_log(self._ts(), "SYSTEM", f"Chrome 경로: {chrome_exe}")
                self._emit_log(self._ts(), "SYSTEM", f"프로필: {profile.label}")
                self._emit_log(self._ts(), "SYSTEM",
                    "⚠ Chrome이 실행 중이면 먼저 닫아주세요 (프로필 충돌 방지)")

                self._emit_log(self._ts(), "SYSTEM", "Chrome 실행 중...")

                with sync_playwright() as pw:
                    context = pw.chromium.launch_persistent_context(
                        user_data_dir=str(profile.user_data_dir),
                        executable_path=chrome_exe,
                        headless=False,
                        ignore_default_args=[
                            "--disable-extensions",
                            "--use-mock-keychain",
                        ],
                        args=[
                            *profile.launch_args(),
                            "--no-first-run",
                            "--no-default-browser-check",
                            "--disable-session-crashed-bubble",
                            "--disable-background-mode",
                            "--password-store=gnome-libsecret",
                            "--disable-blink-features=AutomationControlled",
                        ],
                        viewport={"width": 1280, "height": 900},
                        slow_mo=100,
                    )
                    self._emit_log(self._ts(), "SYSTEM", "Chrome 실행 완료")
                    try:
                        self._run_all(context, enabled, summary, params)
                    finally:
                        try:
                            context.close()
                        except Exception:
                            pass

            # 다운로드 완료 후 manifest.json 저장
            self._write_manifest(self._download_results, params)

        except Exception as e:
            err_str = str(e)
            if "has been closed" in err_str or "Target page" in err_str:
                self._emit_log(
                    self._ts(), "SYSTEM",
                    "✗ Chrome을 열 수 없습니다.\n"
                    "→ Chrome이 실행 중이면 모두 닫고 다시 시도하세요.\n"
                    f"[상세] {type(e).__name__}: {e}"
                )
            elif "Executable doesn't exist" in err_str or "executablePath" in err_str:
                self._emit_log(
                    self._ts(), "SYSTEM",
                    "✗ Chrome 실행 파일을 찾을 수 없습니다.\n"
                    "→ Google Chrome이 설치되어 있는지 확인하세요.\n"
                    f"[상세] {e}"
                )
            else:
                self._emit_log(
                    self._ts(), "SYSTEM",
                    f"✗ {type(e).__name__}: {e}"
                )
            summary["SYSTEM"] = "error"

        finally:
            log_mod.set_ui_callback(None)

        self.run_finished.emit(summary)

    # ── Pre-flight ───────────────────────────────────────────────────────────
    def _preflight(self, params: RunParams, summary: dict) -> bool:
        if params.config.get("save_root_path") and not params.use_mock:
            from utils.file_manager import validate_save_root
            ok, err = validate_save_root(params.config["save_root_path"])
            if not ok:
                self._emit_log(self._ts(), "SYSTEM", f"✗ 저장 경로 오류: {err}")
                summary["SYSTEM"] = "save_path_error"
                return False

        return True

    # ── Sequential download loop ─────────────────────────────────────────────
    def _run_all(self, context, enabled: list[str], summary: dict,
                 params: RunParams) -> None:
        """
        (매체, 계정) 쌍을 순서대로 실행.
        진행률(progress_updated) 단위 = 쌍의 총 개수.
        매체 상태 아이콘(media_status_changed):
          - 첫 계정 시작 시 → "running"
          - 마지막 계정 완료 시 → 전체 계정 결과에 따라 success/failed/skipped
        """
        # ── 실행 단위 목록 빌드 ──────────────────────────────────────────────
        units: list[tuple[str, dict]] = []   # [(media_code, account_dict), ...]
        for media_code in enabled:
            media_cfg = params.config.get("media", {}).get(media_code, {})
            for acct in _get_accounts(media_cfg):
                units.append((media_code, acct))

        total = len(units)
        self._emit_log(self._ts(), "SYSTEM",
            f"총 {len(enabled)}개 매체 / {total}개 계정 실행 시작")

        # 매체별 계정 결과 추적
        media_results: dict[str, list[str]] = {}
        login_blocked_media: set[str] = set()
        # 매체별 총 계정 수 (마지막 계정 판별용)
        media_total: dict[str, int] = {}
        for m in enabled:
            media_cfg = params.config.get("media", {}).get(m, {})
            media_total[m] = len(_get_accounts(media_cfg))

        for idx, (media_code, account) in enumerate(units):
            # ── 중지 요청 처리 ───────────────────────────────────────────────
            if self._stop_requested:
                acct_label = account.get("account_name") or account.get("account_id") or "기본"
                summary.setdefault(media_code, "skipped")
                self.media_status_changed.emit(media_code, "skipped")
                self._emit_log(self._ts(), media_code,
                    f"건너뜀 [{acct_label}] (중지 요청)")
                self.progress_updated.emit(idx + 1, total)
                continue

            acct_label = account.get("account_name") or account.get("account_id") or "기본"

            # 동일 매체 로그인 실패 시 나머지 계정 스킵
            if media_code in login_blocked_media:
                status = "skipped"
                media_results.setdefault(media_code, []).append(status)
                self._emit_log(
                    self._ts(), media_code,
                    f"건너뜀 [{acct_label}] (동일 매체 로그인 필요)",
                )
                self.progress_updated.emit(idx + 1, total)
                if len(media_results[media_code]) == media_total[media_code]:
                    summary[media_code] = "skipped"
                    self.media_status_changed.emit(media_code, "skipped")
                continue

            # 이 매체의 첫 계정이면 "running" 발신
            if media_code not in media_results:
                self.media_status_changed.emit(media_code, "running")

            self._emit_log(self._ts(), media_code,
                f"─── 시작 [{acct_label}] ───")

            downloader = _build_downloader(
                media_code, params.config, account, params.use_mock
            )
            self._current = downloader
            result = downloader.run(context, params.start_date, params.end_date)
            self._current = None

            # 성공한 결과만 manifest 목록에 수집
            if result.success and result.dest_path:
                self._download_results.append({
                    "media":        _MEDIA_CODE_TO_NAME.get(media_code, media_code),
                    "account_name": account.get("account_name", ""),
                    "account_id":   account.get("account_id", ""),
                    "file_path":    str(result.dest_path),
                    "start_date":   params.start_date.strftime("%Y%m%d"),
                    "end_date":     params.end_date.strftime("%Y%m%d"),
                })

            # ── 결과 분류 ────────────────────────────────────────────────────
            if result.login_required:
                self.login_required.emit(media_code)
                login_blocked_media.add(media_code)
                status = "skipped"
            elif result.skipped:
                status = "skipped"
            elif result.success:
                status = "success"
            else:
                status = "failed"

            media_results.setdefault(media_code, []).append(status)
            self._emit_log(self._ts(), media_code,
                f"완료 [{acct_label}]: {status}")
            self.progress_updated.emit(idx + 1, total)

            # ── 마지막 계정이면 매체 최종 상태 확정 ─────────────────────────
            if len(media_results[media_code]) == media_total[media_code]:
                all_st = media_results[media_code]
                if any(s == "failed" for s in all_st):
                    final_status = "failed"
                elif all(s == "success" for s in all_st):
                    final_status = "success"
                else:
                    final_status = "skipped"

                summary[media_code] = final_status
                self.media_status_changed.emit(media_code, final_status)
                self._emit_log(self._ts(), media_code,
                    f"─── {media_code} 전체 완료: {final_status} ───")

    # ── manifest.json 출력 ───────────────────────────────────────────────────
    def _write_manifest(self, download_results: list[dict], params: RunParams) -> None:
        """
        다운로드 완료 후 manifest.json을 저장한다.

        manifest는 파츠 간 표준 인터페이스 역할을 한다.
        후처리 파츠(run_pipeline.py 등)는 이 파일을 읽어 독립 실행한다.

        저장 위치 우선순위:
          1. config["manifest_output_dir"]  (명시 설정)
          2. config["save_root_path"]       (다운로드 루트)
          3. 저장 안 함 (경고만 출력)
        """
        if not download_results:
            return

        import json
        from datetime import datetime
        from pathlib import Path

        config = params.config
        out_dir = config.get("manifest_output_dir", "").strip()
        if not out_dir:
            out_dir = config.get("save_root_path", "").strip()
        if not out_dir:
            self._emit_log(self._ts(), "SYSTEM",
                "[manifest] manifest_output_dir 미설정 — 저장 건너뜀")
            return

        out_path = Path(out_dir)
        try:
            out_path.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            self._emit_log(self._ts(), "SYSTEM",
                f"[manifest] 폴더 생성 실패: {exc}")
            return

        manifest = {
            "brand":      config.get("brand_name", ""),
            "period": {
                "start": params.start_date.strftime("%Y%m%d"),
                "end":   params.end_date.strftime("%Y%m%d"),
            },
            "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "files":      download_results,
        }

        manifest_file = out_path / "manifest.json"
        try:
            manifest_file.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._emit_log(self._ts(), "SYSTEM",
                f"[manifest] ✅ 저장 완료 — {manifest_file}")
            self._emit_log(self._ts(), "SYSTEM",
                f"  파일 {len(download_results)}건 / 브랜드: {manifest['brand']}")
        except Exception as exc:
            self._emit_log(self._ts(), "SYSTEM",
                f"[manifest] ❌ 저장 실패: {exc}")

    # ── Helpers ──────────────────────────────────────────────────────────────
    def _emit_log(self, ts: str, media: str, message: str) -> None:
        self.log_message.emit(ts, media, message)

    @staticmethod
    def _ts() -> str:
        from datetime import datetime
        return datetime.now().strftime("%H:%M:%S")

    @staticmethod
    def _find_chrome_exe() -> str:
        import os
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
        ]
        for p in candidates:
            if os.path.exists(p):
                return p
        raise RuntimeError(
            "Chrome 실행 파일을 찾을 수 없습니다.\n"
            "Google Chrome이 설치되어 있는지 확인하세요."
        )
