"""Naver GFA (Display Advertising) 성과 보고서 다운로더.

URL: https://ads.naver.com/manage/ad-accounts/{account_id}/da/report/performance
로그인: Naver SA와 동일 (chrome_profile 세션 재사용)

다운로드 흐름:
  navigate_to_report → 성과 보고서 페이지 이동
  set_period         → 날짜 + 보고서 옵션(분석단위/기간단위/게재위치/오디언스) 설정 → 확인
  trigger_download   → 열 맞춤 설정 선택 → 다운로드 요청 → 확인 → 파일 준비 대기 → 다운로드
"""
from __future__ import annotations

import tempfile
import time
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from downloader.base import BaseDownloader, LoginRequiredError

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


_SELECTOR_FILE = Path(__file__).parent.parent / "selectors" / "gfa.yaml"


def _load_selectors() -> dict:
    with _SELECTOR_FILE.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


class GFADownloader(BaseDownloader):
    MEDIA_CODE = "gfa"
    IMPLEMENTED = True

    def __init__(self, config: dict, account: dict | None = None):
        super().__init__(config, account)
        self._sel = _load_selectors()
        acct = account or {}
        # 계정별 보고서 옵션 (config.json 에서 설정)
        self._analysis_unit: str = acct.get("analysis_unit", "광고 계정").strip()
        self._period_unit:   str = acct.get("period_unit",   "일").strip()
        self._placement:     str = acct.get("placement",     "전체").strip()
        self._audience:      str = acct.get("audience",      "전체").strip()
        self._column_preset: str = (acct.get("column_preset") or acct.get("report_name", "")).strip()

    # ── 1. Login check ───────────────────────────────────────────────────────
    def check_login(self, page: "Page") -> bool:
        page.goto(self._sel["base_url"], wait_until="domcontentloaded", timeout=30_000)
        self.human_delay(1000, 1500)
        url = page.url.lower()
        for pattern in self._sel["login"]["login_url_patterns"]:
            if pattern.lower() in url:
                return False
        try:
            if page.locator(self._sel["login"]["login_element_selector"]).first.is_visible(timeout=2_000):
                return False
        except Exception:
            pass
        return True

    # ── 2. Navigate ──────────────────────────────────────────────────────────
    def navigate_to_report(self, page: "Page") -> None:
        if not self.account_id:
            raise RuntimeError("GFA account_id가 없습니다.")

        path = self._sel["report"]["performance_path"].replace("{account_id}", self.account_id)
        url = self._sel["base_url"] + path
        self._info(f"GFA 성과 보고서 이동: {url}")

        try:
            page.goto(url, wait_until="networkidle", timeout=40_000)
        except Exception:
            pass  # networkidle 타임아웃 허용
        self.human_delay(1500, 2500)

        # 로그인 리디렉션 확인
        current_url = page.url.lower()
        for pattern in self._sel["login"]["login_url_patterns"]:
            if pattern.lower() in current_url:
                raise LoginRequiredError()

    # ── 3. Set period + report options ───────────────────────────────────────
    def set_period(self, page: "Page", start: date, end: date) -> None:
        self._info(f"날짜 설정: {start} ~ {end}")
        self._open_and_pick_dates(page, start, end)
        self._set_report_options(page)
        self._click_main_confirm(page)

    # ── 4. Trigger download ───────────────────────────────────────────────────
    def trigger_download(self, page: "Page", start: date, end: date) -> Path:
        dl_sel = self._sel["download"]
        timeout_ms = int(dl_sel.get("timeout_sec", self.timeout_sec)) * 1_000

        # ── Step 1: 열 맞춤 설정 선택 (없으면 기본값으로 진행) ────────────────
        if self._column_preset:
            self._select_column_preset(page)

        # ── Step 2: "다운로드 요청" 버튼 클릭 (보고서 페이지에서 직접 요청 생성) ─
        self._info("다운로드 요청 클릭")
        req_btn = self._find_visible(page, dl_sel["request_button"], timeout=10_000)
        if req_btn is None:
            self._screenshot(page, "gfa_request_btn_not_found")
            raise RuntimeError("GFA '다운로드 요청' 버튼을 찾을 수 없습니다.")
        req_btn.click()
        self.human_delay(1000, 1500)

        # ── Step 3: 확인 모달 처리 (2단계 — A 확인 → B 완료 알림 닫기) ────────
        _MODAL_SEL = ".ad-cms-modal-wrap, [data-nclick-area='dialog'], div[role='dialog']"

        def _click_any_confirm(wait_ms: int) -> bool:
            btn = self._find_visible(page, dl_sel["dialog_confirm"], timeout=wait_ms)
            if btn is None:
                btn = self._find_visible(
                    page,
                    "button:has-text('확인'), button:has-text('닫기'), button:has-text('OK')",
                    timeout=wait_ms,
                )
            if btn:
                btn.click()
                return True
            return False

        def _wait_modal_hidden(timeout_ms: int) -> bool:
            try:
                page.wait_for_selector(_MODAL_SEL, state="hidden", timeout=timeout_ms)
                return True
            except Exception:
                return False

        # Modal A (다운로드 요청 확인)
        if _click_any_confirm(6_000):
            self._info("다운로드 요청 확인 클릭 (Modal A)")

        # Modal A 닫힘 대기
        if not _wait_modal_hidden(6_000):
            # Modal B (완료 알림) 가 나타났을 수 있음 → 한 번 더 클릭
            self._warn("모달 추가 감지 — Modal B 닫기 시도")
            if _click_any_confirm(4_000):
                self._info("Modal B 닫기 클릭")
            if not _wait_modal_hidden(6_000):
                # 그래도 남아있으면 Escape 강제 닫기
                self._warn("모달 지속 — Escape 강제 닫기")
                page.keyboard.press("Escape")
                self.human_delay(1000, 1500)
        else:
            self._info("모달 닫힘 확인")
        self.human_delay(800, 1200)

        # ── Step 4: "다운로드 요청 목록" 열기 → 준비된 파일 대기 ───────────
        self._info("다운로드 요청 목록 열기")
        list_btn = self._find_visible(page, dl_sel["open_list_button"], timeout=8_000)
        if list_btn is None:
            self._screenshot(page, "gfa_open_list_not_found")
            raise RuntimeError("GFA '다운로드 요청 목록' 버튼을 찾을 수 없습니다.")
        list_btn.click()
        self.human_delay(1500, 2000)
        self._screenshot(page, "gfa_after_open_list")
        self._info(f"파일 준비 대기 중... (최대 {timeout_ms // 1000}초)")

        # ── Step 5: 보고서 페이지 이탈 → 목록 재클릭 사이클로 상태 갱신 폴링 ──
        # 목록 페이지는 자동 새로고침이 없으므로 이탈→재진입으로 상태를 업데이트함
        _POLL_JS = """() => {
            try {
                const els = document.querySelectorAll('button, a, [role="button"]');
                for (const el of els) {
                    const txt = (el.innerText || el.textContent || '').trim();
                    if (txt === '다운로드') return true;
                }
                return false;
            } catch(e) { return false; }
        }"""

        deadline = time.time() + timeout_ms / 1000
        found = False
        cycle = 0

        while time.time() < deadline:
            # 현재 목록 페이지에서 다운로드 버튼 확인
            try:
                found = page.evaluate(_POLL_JS)
            except Exception:
                found = False
            if found:
                break

            cycle += 1
            elapsed = int(time.time() - (deadline - timeout_ms / 1000))
            self._info(f"준비 대기 중... ({elapsed}초 경과, {cycle}회차) — 이탈 후 목록 재진입")

            # 뒤로가기로 보고서 페이지 이탈
            try:
                page.go_back(wait_until="domcontentloaded", timeout=15_000)
            except Exception:
                try:
                    page.goto(
                        self._sel["base_url"]
                        + self._sel["report"]["performance_path"].replace("{account_id}", self.account_id),
                        wait_until="domcontentloaded",
                        timeout=20_000,
                    )
                except Exception:
                    pass
            self.human_delay(2000, 3000)

            # 목록 패널 다시 열기
            list_btn_r = self._find_visible(page, dl_sel["open_list_button"], timeout=8_000)
            if list_btn_r is not None:
                list_btn_r.click()
                self.human_delay(2000, 3000)
            else:
                self._warn("목록 버튼 재발견 실패 — 잠시 대기")
                time.sleep(10)

        if not found:
            self._screenshot(page, "gfa_download_list_timeout")
            raise RuntimeError(
                f"GFA 다운로드 준비 타임아웃 ({timeout_ms // 1000}초). "
                "다운로드 목록에서 수동으로 파일을 받아주세요."
            )

        # ── Step 6: 다운로드 버튼 클릭 ──────────────────────────────────────
        self._info("다운로드 버튼 클릭")
        dl_btn_sel = dl_sel["list_download_button"]
        with page.expect_download(timeout=60_000) as dl_info:
            dl_btn = self._find_visible(page, dl_btn_sel, timeout=5_000)
            if dl_btn is None:
                # 더 넓은 범위로 재시도
                dl_btn = page.locator(
                    "tbody tr button:has-text('다운로드'), "
                    "tbody tr a:has-text('다운로드'), "
                    "[class*='list-item'] button:has-text('다운로드')"
                ).first
            dl_btn.click()

        download = dl_info.value
        suggested = download.suggested_filename or "gfa_report.xlsx"
        suffix = Path(suggested).suffix or ".xlsx"
        tmp = Path(tempfile.mktemp(suffix=suffix))
        download.save_as(str(tmp))

        if not tmp.exists() or tmp.stat().st_size == 0:
            raise RuntimeError(f"GFA 다운로드 파일이 비어 있습니다: {tmp}")

        self._info(f"파일: {suggested} ({tmp.stat().st_size:,} bytes)")
        return tmp

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _open_and_pick_dates(self, page: "Page", start: date, end: date) -> None:
        """날짜 피커 열기 → 날짜 클릭 → 달력 내 확인."""
        per_sel = self._sel["period"]

        # 날짜 범위 버튼 클릭
        opened = False
        for trigger_sel in per_sel["date_range_button"].split(","):
            trigger_sel = trigger_sel.strip()
            if not trigger_sel:
                continue
            try:
                btn = page.locator(trigger_sel).first
                if btn.is_visible(timeout=1_500):
                    btn.click()
                    opened = True
                    break
            except Exception:
                continue

        if not opened:
            self._warn("GFA 날짜 피커를 열 수 없습니다 — 날짜 설정 건너뜀")
            self._screenshot(page, "gfa_date_picker_not_found")
            return

        self.human_delay(600, 1000)

        # 달력에서 시작일 / 종료일 클릭 (Naver SA와 동일 구조)
        self._click_calendar_day(page, start, "시작일")
        self.human_delay(300, 500)
        self._click_calendar_day(page, end, "종료일")
        self.human_delay(300, 500)

        # 달력 내 확인 버튼 클릭 (여러 셀렉터 순서대로 시도)
        confirm_selectors = [
            "button[data-nclick='ok']",
            "button.ad-cms-btn-color-primary.ad-cms-btn-variant-solid:has-text('확인')",
            "button.ad-cms-btn-color-primary:has-text('확인')",
            "button.ad-cms-btn-variant-solid:has-text('확인')",
            "button.ad-cms-btn:has-text('확인')",
            "button:has-text('확인')",
        ]
        confirmed = False
        for sel in confirm_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=1_000):
                    btn.click()
                    self.human_delay(800, 1200)
                    self._info("날짜 확인 버튼 클릭 완료")
                    confirmed = True
                    break
            except Exception:
                continue
        if not confirmed:
            self._warn("날짜 확인 버튼 미발견 — Escape로 닫기")
            page.keyboard.press("Escape")
            self.human_delay(500, 800)

    def _click_calendar_day(self, page: "Page", target: date, label: str) -> None:
        """Naver CMS 달력 날짜 클릭 (data-year / data-month(0-indexed) / data-day)."""
        month_0 = target.month - 1
        sel = (
            f'[data-year="{target.year}"][data-month="{month_0}"] '
            f'li[data-day="{target.day}"] button'
        )
        try:
            btn = page.locator(sel).first
            btn.wait_for(state="visible", timeout=5_000)
            btn.click()
            self.human_delay(300, 500)
            self._info(f"GFA {label} 선택: {target}")
        except Exception as e:
            self._warn(f"GFA {label} 날짜 클릭 실패 ({target}): {e}")

    def _set_report_options(self, page: "Page") -> None:
        """분석단위 / 기간단위 / 게재위치 / 오디언스 라디오버튼 선택.

        동일한 텍스트(예: '전체')가 여러 그룹에 중복 존재하므로
        div[role='radiogroup'] 인덱스로 스코프를 한정해 클릭한다.
        그룹 순서: 0=분석단위, 1=기간단위, 2=게재위치, 3=오디언스
        """
        settings = [
            (0, self._analysis_unit),  # 분석단위
            (1, self._period_unit),    # 기간단위
            (2, self._placement),      # 게재위치
            (3, self._audience),       # 오디언스
        ]

        groups = page.locator('[role="radiogroup"]')

        for group_idx, option in settings:
            if not option:
                continue
            try:
                group = groups.nth(group_idx)
                # 해당 그룹 내에서 option 텍스트를 포함하는 label 클릭
                lbl = group.locator(f'label:has-text("{option}")').first
                if lbl.is_visible(timeout=2_000):
                    lbl.click()
                    self.human_delay(200, 400)
                    self._info(f"GFA 옵션 선택: {option}")
                else:
                    self._warn(f"GFA 옵션 '{option}' (그룹 {group_idx}) 미표시 — 건너뜀")
            except Exception as e:
                self._warn(f"GFA 옵션 선택 실패 '{option}': {e}")

    def _click_main_confirm(self, page: "Page") -> None:
        """옵션 적용 확인 버튼 클릭 (보고서 데이터 로드)."""
        confirm_sel = self._sel["options"]["main_confirm"]
        try:
            btn = page.locator(confirm_sel).first
            btn.wait_for(state="visible", timeout=5_000)
            btn.click()
            self._info("GFA 확인 클릭 — 보고서 로딩 대기")
            self.human_delay(2000, 3000)
        except Exception as e:
            self._warn(f"GFA 확인 버튼 클릭 실패: {e}")

    def _select_column_preset(self, page: "Page") -> None:
        """열 맞춤 설정 드롭다운에서 지정 preset 선택."""
        preset = self._column_preset
        col_sel = self._sel["column_preset"]
        self._info(f"열 맞춤 설정 선택: '{preset}'")

        # 드롭다운 트리거 클릭
        trigger = self._find_visible(page, col_sel["dropdown_trigger"], timeout=5_000)
        if trigger is None:
            self._warn("열 맞춤 설정 드롭다운 트리거를 찾지 못했습니다.")
            return
        trigger.click()
        self.human_delay(600, 1000)

        # preset 이름 항목 클릭
        item_sel = col_sel["dropdown_item"].replace("{preset}", preset)
        item = self._find_visible(page, item_sel, timeout=3_000)
        if item is not None:
            item.click()
            self.human_delay(400, 700)
            self._info(f"열 맞춤 설정 '{preset}' 선택 완료")
        else:
            self._warn(f"열 맞춤 설정 항목 '{preset}'을 찾지 못했습니다. 기본값으로 진행합니다.")
            page.keyboard.press("Escape")
            self.human_delay(800, 1200)  # 드롭다운 닫힘 대기

    @staticmethod
    def _find_visible(page: "Page", selector: str, timeout: int = 3_000) -> "Locator | None":
        if not selector:
            return None
        for part in selector.split(","):
            item = part.strip()
            if not item:
                continue
            try:
                loc = page.locator(item).first
                if loc.is_visible(timeout=timeout):
                    return loc
            except Exception:
                continue
        return None
