"""X (Twitter) Ads report downloader."""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from downloader.base import BaseDownloader

if TYPE_CHECKING:
    from playwright.sync_api import Page


_SELECTOR_FILE = Path(__file__).parent.parent / "selectors" / "x.yaml"


def _load_selectors() -> dict:
    with _SELECTOR_FILE.open(encoding="utf-8") as file:
        return yaml.safe_load(file)


class XAdsDownloader(BaseDownloader):
    MEDIA_CODE = "x"
    IMPLEMENTED = True

    def __init__(self, config: dict, account: dict | None = None):
        super().__init__(config, account)
        self._sel = _load_selectors()

    def check_login(self, page: "Page") -> bool:
        page.goto(self._sel["base_url"], wait_until="domcontentloaded", timeout=30_000)
        self.human_delay(1000, 1500)
        url = page.url.lower()
        for pattern in self._sel["login"]["login_url_patterns"]:
            if pattern.lower() in url:
                return False
        try:
            selector = self._sel["login"]["login_element_selector"]
            if page.locator(selector).first.is_visible(timeout=2_000):
                return False
        except Exception:
            pass
        return True

    def navigate_to_report(self, page: "Page") -> None:
        if not self.account_id:
            raise RuntimeError("X Ads account_id가 없습니다.")
        target = f"{self._sel['base_url']}/manager/{self.account_id}/campaigns"
        self._info(f"X Ads 캠페인 페이지 이동: {target}")
        page.goto(target, wait_until="domcontentloaded", timeout=30_000)
        self.human_delay(2000, 3000)

        # Campaigns → Ads 탭으로 전환 (다운로드 버튼은 Ads 탭에 있음)
        ads_tab_sel = self._sel.get("tabs", {}).get("ads_tab", "")
        ads_tab = self._find_visible(page, ads_tab_sel, timeout=8_000)
        if ads_tab is not None:
            ads_tab.click()
            self._info("Ads 탭 클릭 완료")
            self.human_delay(1500, 2500)
        else:
            # fallback: URL에 /ads 붙여서 직접 이동 시도
            self._warn("Ads 탭 셀렉터 미매칭 — URL 직접 이동 시도")
            ads_url = f"{self._sel['base_url']}/manager/{self.account_id}/campaigns/ads"
            page.goto(ads_url, wait_until="domcontentloaded", timeout=30_000)
            self.human_delay(2000, 3000)
            # 그래도 campaigns 페이지면 스크린샷으로 확인
            if "/campaigns" in page.url and "/ads" not in page.url:
                self._screenshot(page, "x_ads_tab_not_found")
                self._warn("Ads 탭 이동 실패 — 현재 페이지에서 진행")

    def set_period(self, page: "Page", start: date, end: date) -> None:
        selector = self._sel.get("date_picker", {}).get("trigger", "")
        trigger = self._find_visible(page, selector, timeout=5_000)
        if trigger is None:
            self._warn("X 날짜 필터 버튼을 찾지 못해 기본 기간으로 진행합니다.")
            return

        trigger.click()
        self.human_delay(1200, 1800)  # 달력 렌더링 대기
        self._click_date(page, start, "시작일")
        self.human_delay(800, 1200)   # 시작일 선택 후 달력 재렌더링 대기
        self._click_date(page, end, "종료일")
        self.human_delay(500, 800)
        apply_button = self._find_visible(
            page,
            "button:has-text('적용'), button:has-text('Apply'), button:has-text('확인')",
            timeout=3_000,
        )
        if apply_button is not None:
            apply_button.click()
        else:
            page.keyboard.press("Escape")  # 달력 닫기
        self.human_delay(1000, 1500)

    def trigger_download(self, page: "Page", start: date, end: date) -> Path:
        cfg = self._sel["export"]
        timeout_ms = int(self._sel.get("download", {}).get("timeout_sec", self.timeout_sec)) * 1000

        # 열려있는 오버레이(달력 등) 닫기
        try:
            page.keyboard.press("Escape")
            self.human_delay(400, 600)
        except Exception:
            pass

        icon = self._find_visible(page, cfg["download_icon"], timeout=10_000)
        if icon is None:
            self._screenshot(page, "x_export_icon_not_found")
            raise RuntimeError("X 내보내기 버튼을 찾을 수 없습니다.")
        try:
            icon.click()
        except Exception:
            icon.click(force=True)
        self.human_delay(800, 1200)

        new_export = self._find_visible(page, cfg["new_export_item"], timeout=6_000)
        if new_export is not None:
            new_export.click()
            self.human_delay(800, 1200)

        daily_option = self._find_visible(page, cfg["daily_option"], timeout=5_000)
        if daily_option is not None:
            daily_option.click()
            self.human_delay(400, 700)

        submit = self._find_visible(page, cfg["submit_button"], timeout=5_000)
        if submit is None:
            self._screenshot(page, "x_export_submit_not_found")
            raise RuntimeError("X 내보내기 제출 버튼을 찾을 수 없습니다.")

        with page.expect_download(timeout=timeout_ms) as download_info:
            submit.click()

        download = download_info.value
        suggested = download.suggested_filename or "x_ads_export.csv"
        suffix = Path(suggested).suffix or ".csv"
        tmp = Path(tempfile.mktemp(suffix=suffix))
        download.save_as(str(tmp))
        if not tmp.exists() or tmp.stat().st_size == 0:
            raise RuntimeError(f"X 다운로드 파일이 비어 있습니다: {tmp}")
        return tmp

    def _click_date(self, page: "Page", target: date, label: str) -> None:
        ko_label = f"{target.year}년 {target.month}월 {target.day}일"
        en_label = f"{target.month}/{target.day}/{target.year}"
        en_label2 = target.strftime("%B %#d, %Y")  # "June 1, 2026" (Windows: %#d)
        iso = target.strftime("%Y-%m-%d")           # "2026-06-01"
        selectors = [
            # overflow cell 제외 (data-outside='true' 는 다른 달 넘침 셀)
            f"td[data-day='{iso}']:not([data-outside='true']) button",
            f"[data-day='{iso}']:not([data-outside='true'])",
            f"[aria-label*='{ko_label}']",
            f"[aria-label*='{en_label}']",
            f"[aria-label*='{en_label2}']",
        ]
        # is_visible 무관 — DOM에 있으면 force 클릭
        for selector in selectors:
            try:
                loc = page.locator(selector).first
                if loc.count() > 0:
                    loc.scroll_into_view_if_needed(timeout=2000)
                    loc.click(force=True)
                    self.human_delay(400, 700)
                    self._info(f"X {label} 선택: {target}")
                    return
            except Exception:
                continue
        self._warn(f"X {label} 날짜 셀을 찾지 못했습니다: {target}")

    @staticmethod
    def _find_visible(page: "Page", selector: str, timeout: int = 3_000):
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
