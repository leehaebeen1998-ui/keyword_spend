"""Google Analytics 4 exploration report downloader."""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from downloader.base import BaseDownloader

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


_SELECTOR_FILE = Path(__file__).parent.parent / "selectors" / "google_analytics.yaml"


def _load_selectors() -> dict:
    with _SELECTOR_FILE.open(encoding="utf-8") as file:
        return yaml.safe_load(file)


class GoogleAnalyticsDownloader(BaseDownloader):
    MEDIA_CODE = "google_analytics"
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
            raise RuntimeError("GA4 account_id가 없습니다.")
        if not self.report_name:
            raise RuntimeError("GA4 report_name이 없습니다.")

        url = f"{self._sel['base_url']}#/analysis/{self.account_id}"
        self._info(f"탐색 목록 이동: {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        self.human_delay(5000, 6000)
        self._click_report_card(page)

    def set_period(self, page: "Page", start: date, end: date) -> None:
        self._info(f"날짜 범위 설정: {start} ~ {end}")
        dr = self._sel["date_range"]

        trigger = self._find_visible(page, dr["section_trigger"], timeout=8_000)
        if trigger is None:
            self._warn("날짜 범위 버튼을 찾지 못해 기본 날짜로 진행합니다.")
            return
        trigger.click()
        self.human_delay(1000, 1500)

        custom = self._find_visible(page, dr.get("custom_option", ""), timeout=4_000)
        if custom is not None:
            custom.click(force=True)
            self.human_delay(1000, 1500)

        self._click_calendar_date(page, start, "시작일")
        self._click_calendar_date(page, end, "종료일")

        apply_button = self._find_visible(page, dr.get("apply_button", ""), timeout=5_000)
        if apply_button is not None:
            apply_button.click()
        else:
            page.keyboard.press("Enter")
        self.human_delay(800, 1200)

    def trigger_download(self, page: "Page", start: date, end: date) -> Path:
        export_cfg = self._sel["export"]
        timeout_ms = int(export_cfg.get("timeout_sec", self.timeout_sec)) * 1000

        button = self._find_visible(page, export_cfg["export_button"], timeout=10_000)
        if button is None:
            self._screenshot(page, "ga4_export_button_not_found")
            raise RuntimeError("GA4 내보내기 버튼을 찾을 수 없습니다.")

        button.click()
        self.human_delay(800, 1200)

        with page.expect_download(timeout=timeout_ms) as download_info:
            csv_option = self._find_visible(page, export_cfg["csv_option"], timeout=6_000)
            if csv_option is not None:
                csv_option.click()
            else:
                button.click()

        download = download_info.value
        suggested = download.suggested_filename or "ga4_explore.csv"
        suffix = Path(suggested).suffix or ".csv"
        tmp = Path(tempfile.mktemp(suffix=suffix))
        download.save_as(str(tmp))

        if not tmp.exists() or tmp.stat().st_size == 0:
            raise RuntimeError(f"GA4 다운로드 파일이 비어 있습니다: {tmp}")

        self._info(f"파일: {suggested} ({tmp.stat().st_size:,} bytes)")
        return tmp

    def _click_report_card(self, page: "Page") -> None:
        self._info(f"탐색 보고서 찾는 중: '{self.report_name}'")
        self._screenshot(page, "ga4_before_find_report")

        # body 텍스트로 에디터 진입 여부 확인 (is_visible보다 신뢰성 높음)
        try:
            body_text = page.locator("body").inner_text(timeout=5_000)
            if "탐색 분석 이름" in body_text:
                if self.report_name in body_text:
                    self._info(f"보고서 이미 열려있음 — 클릭 생략: {self.report_name}")
                    return
                else:
                    self._info("다른 탐색 보고서 열려있음 → 목록으로 재이동")
                    url = f"{self._sel['base_url']}#/analysis/{self.account_id}"
                    page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                    self.human_delay(5000, 6000)
        except Exception:
            pass

        url_before = page.url

        # JavaScript TreeWalker: 텍스트 노드 탐색 → 행(TR/MAT-ROW/role=row) 클릭
        try:
            result = page.evaluate("""(reportName) => {
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                const exact = [];
                let node;
                while ((node = walker.nextNode())) {
                    if (node.textContent.trim() === reportName) {
                        exact.push(node);
                    }
                }
                for (const node of exact) {
                    let el = node.parentElement;
                    for (let i = 0; i < 12; i++) {
                        if (!el) break;
                        const tag = el.tagName.toUpperCase();
                        const role = (el.getAttribute('role') || '').toLowerCase();
                        // 클릭 가능한 행/버튼/앵커 요소 탐색
                        if (tag === 'TR' || tag === 'MAT-ROW' || tag === 'A' || tag === 'BUTTON'
                            || role === 'row' || role === 'button' || role === 'link') {
                            el.click();
                            return 'clicked_row:' + tag + ':role=' + role + ':' + el.className.substring(0, 40);
                        }
                        el = el.parentElement;
                    }
                }
                // fallback: 텍스트 노드 부모 중 가시적인 첫 요소 클릭
                for (const node of exact) {
                    let el = node.parentElement;
                    for (let i = 0; i < 8; i++) {
                        if (!el) break;
                        if (el.offsetWidth > 0 && el.offsetHeight > 0) {
                            el.click();
                            return 'fallback:' + el.tagName + ':' + el.className.substring(0, 40);
                        }
                        el = el.parentElement;
                    }
                }
                return 'not_found:exact=' + exact.length;
            }""", self.report_name)
            self._info(f"JS 보고서 클릭: {result}")

            if result and "not_found" not in result:
                # SPA 라우팅 완료까지 폴링 (URL 변경 OR 에디터 텍스트 등장)
                try:
                    page.wait_for_function(
                        """([urlBefore, name]) => {
                            if (window.location.href !== urlBefore) return true;
                            const body = document.body.innerText || '';
                            return body.includes('탐색 분석 이름') && body.includes(name);
                        }""",
                        arg=[url_before, self.report_name],
                        timeout=10_000,
                    )
                    self._info("보고서 에디터 열림")
                    self.human_delay(3000, 4000)  # 버튼/툴바 렌더링 대기
                    return
                except Exception as e:
                    self._warn(f"에디터 열림 대기 실패: {e}")
        except Exception as e:
            self._warn(f"JS 클릭 실패: {e}")

        self._screenshot(page, "ga4_report_not_found")
        raise RuntimeError(f"GA4 탐색 보고서 '{self.report_name}'를 찾을 수 없습니다.")

    def _click_calendar_date(self, page: "Page", target: date, label: str) -> None:
        ko_label = f"{target.year}년 {target.month}월 {target.day}일"
        en_label = f"{target.month}/{target.day}/{target.year}"
        day = str(target.day)
        selectors = [
            f"[aria-label*='{ko_label}']",
            f"[aria-label*='{en_label}']",
            f"[id^='reach-datepicker'] button:has-text('{day}')",
            f"button[role='gridcell']:has-text('{day}')",
            f"td[role='gridcell']:has-text('{day}') button",
        ]

        for selector in selectors:
            loc = self._find_visible(page, selector, timeout=2_000)
            if loc is None:
                continue
            loc.click(force=True)
            self.human_delay(400, 700)
            self._info(f"{label} 선택: {target}")
            return

        self._screenshot(page, f"ga4_calendar_{label}")
        raise RuntimeError(f"GA4 {label} 날짜를 선택할 수 없습니다: {target}")

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
