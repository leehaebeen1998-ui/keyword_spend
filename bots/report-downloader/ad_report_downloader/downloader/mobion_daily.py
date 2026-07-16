"""Mobion daily report downloader."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from downloader.mobion_base import MobionBase

if TYPE_CHECKING:
    from playwright.sync_api import Page

_APPLY_BTN_SELECTOR = (
    "div.daterangepicker button.applyBtn, "
    "div.daterangepicker .applyBtn"
)


_SELECTOR_FILE = Path(__file__).parent.parent / "selectors" / "mobion_daily.yaml"


class MobionDailyDownloader(MobionBase):
    MEDIA_CODE = "mobion_daily"
    IMPLEMENTED = True
    _SELECTOR_FILE = _SELECTOR_FILE

    def navigate_to_report(self, page: "Page") -> None:
        self._info("모비온 일자별 보고서 이동")
        # 리포트 페이지 이동 → 마스터 계정일 때 광고주 로그인 모달 자동 등장
        self._goto_report(page)
        if self.account_id:
            self._switch_account(page)
        else:
            self._warn("account_id 미설정 — 현재 로그인 계정으로 진행")
        self._select_template(page)
        # '디스플레이 전체' 필터 해제를 날짜 설정 전에 수행
        # trigger_download에서 수행하면 set_period 이후 필터 클릭 → AJAX 재조회로 날짜가 오늘로 리셋되는 버그 발생
        self._deselect_display_all(page)

    def set_period(self, page: "Page", start: date, end: date) -> None:
        """일별 보고서 전용 날짜 설정.

        MobionBase.set_period의 JS API(picker.clickApply())는 일별 보고서에서
        AJAX 재조회를 발동시키지 못하는 경우가 있음.
        → 피커를 직접 열고 Apply 버튼을 Playwright로 클릭해 실제 이벤트를 발생시킴.
        """
        start_str = start.strftime("%Y%m%d")
        end_str = end.strftime("%Y%m%d")

        # daterangepicker 초기화 대기
        try:
            page.wait_for_function(
                "typeof $ !== 'undefined' && $('#dateInput').data('daterangepicker') !== undefined",
                timeout=8_000,
            )
        except Exception:
            pass

        # 1) 날짜 버튼 클릭으로 피커 열기 (JS 호출이 아닌 실제 클릭)
        date_btn = self._find_first_visible(
            page, self._sel["period"]["date_range_button"], timeout=8_000
        )
        if date_btn is None:
            self._screenshot(page, "mobion_daily_no_date_btn")
            # fallback: 부모 클래스 로직
            super().set_period(page, start, end)
            return

        date_btn.click()
        self.human_delay(500, 800)

        # 2) JS API로 날짜 값 설정 (UI 조작 없이 빠르게)
        page.evaluate(f"""
            (() => {{
                var picker = $('#dateInput').data('daterangepicker');
                if (picker) {{
                    picker.setStartDate('{start_str}');
                    picker.setEndDate('{end_str}');
                }}
            }})()
        """)
        self.human_delay(300, 500)

        # 3) Apply 버튼을 Playwright로 직접 클릭 → 실제 이벤트 발생 → AJAX 재조회
        apply_btn = self._find_first_visible(page, _APPLY_BTN_SELECTOR, timeout=3_000)
        if apply_btn is not None:
            apply_btn.click()
            self._info(f"일별 날짜 Apply 클릭: {start_str} ~ {end_str}")
            try:
                page.wait_for_load_state("networkidle", timeout=20_000)
            except Exception:
                pass
            self.human_delay(500, 800)
            return

        # Apply 버튼을 못 찾으면 부모 fallback (달력 클릭 방식)
        self._warn("Apply 버튼 없음 — 부모 set_period 사용")
        super().set_period(page, start, end)

    def trigger_download(self, page: "Page", start: date, end: date) -> Path:
        return super().trigger_download(page, start, end)

    def _deselect_display_all(self, page: "Page") -> None:
        selectors = [
            "button.advertiser_product[data-advertiser-product='00']",
            "button.advertiser_product:has-text('디스플레이 전체')",
            "li.on button.advertiser_product",
        ]
        for selector in selectors:
            try:
                loc = page.locator(selector).first
                if loc.is_visible(timeout=2_000):
                    loc.click()
                    # 필터 클릭 후 페이지 데이터가 완전히 리로드될 때까지 대기
                    # (networkidle 없이 human_delay만 하면 set_period가 리로드 중인 페이지에서 실행되어
                    #  daterangepicker가 초기화되지 않거나 AJAX 응답이 기존 날짜로 덮어써짐)
                    try:
                        page.wait_for_load_state("networkidle", timeout=12_000)
                    except Exception:
                        pass
                    self.human_delay(500, 800)
                    self._info("'디스플레이 전체' 비활성화 완료")
                    return
            except Exception:
                continue
        self._warn("'디스플레이 전체' 버튼 없음 — 필터 생략")
