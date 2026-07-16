"""Google Ads 보고서 에디터 다운로더.

계정 전환 흐름 (MCC → 광고주 계정, 1회 로그인 / 최대 3계정):
  1. check_login(): ads.google.com 접속 후 세션 확인
  2. navigate_to_report():
     a. account_name 으로 MCC 드롭다운 계정 전환
     b. 사이드바 '통계 및 보고서' → '보고서 에디터'
     c. report_name 으로 저장된 보고서 클릭
     d. 필터 상태 확인 (캠페인/광고그룹 → '전체')
  3. set_period(): 날짜 범위 설정 (맞춤 기간)
  4. trigger_download(): 다운로드 아이콘 → Excel(.xlsx) 선택
"""
from __future__ import annotations
import re
import tempfile
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from playwright.sync_api import Page

from downloader.base import BaseDownloader, EmptyDataError

_SELECTOR_FILE = Path(__file__).parent.parent / "selectors" / "google.yaml"


def _load_selectors() -> dict:
    with _SELECTOR_FILE.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


class GoogleDownloader(BaseDownloader):
    MEDIA_CODE = "google"
    IMPLEMENTED = True

    def __init__(self, config: dict, account: dict | None = None):
        super().__init__(config, account)
        self._sel = _load_selectors()

    # ------------------------------------------------------------------ #
    # 1. Login check                                                       #
    # ------------------------------------------------------------------ #
    def check_login(self, page: "Page") -> bool:
        base = self._sel["base_url"]
        suffix = self._sel["report"]["report_editor_url_suffix"]
        page.goto(base + suffix, wait_until="domcontentloaded", timeout=30_000)
        self.human_delay(800, 1500)

        # Google Ads 고객 ID 선택 화면은 Google 계정 로그인이 완료된 뒤
        # 표시된다. URL만 보면 accounts.google.com 또는
        # ads.google.com/nav/selectaccount 이므로 로그인 화면과 구분해야 한다.
        if self._is_account_selection_page(page):
            self._info("Google Ads 계정 선택 화면 감지 — 로그인 세션 유효")
            return True

        url = page.url.lower()
        for pattern in self._sel["login"]["login_url_patterns"]:
            if pattern.lower() in url:
                return False

        try:
            fallback = self._sel["login"]["login_element_selector"]
            if page.locator(fallback).first.is_visible(timeout=2_000):
                return False
        except Exception:
            pass

        return True

    @staticmethod
    def _normalize_account_id(value: str) -> str:
        """Google Ads 고객 ID를 숫자만 남겨 비교 가능하게 정규화."""
        return re.sub(r"\D", "", value or "")

    def _is_account_selection_page(self, page: "Page") -> bool:
        """Google 로그인 화면이 아닌 Google Ads 고객 ID 선택 화면인지 확인."""
        # URL 기반 감지 (가장 빠르고 신뢰도 높음)
        url = page.url.lower()
        sel = self._sel.get("account_selection", {})
        url_pattern = sel.get("url_pattern", "selectaccount")
        if url_pattern.lower() in url:
            return True

        # DOM 기반 감지 (URL만으로 판단 불가능한 경우 fallback)
        heading_sel = sel.get(
            "heading",
            "[aria-label='Google Ads 계정 선택'], .selection-header-old, .selection-header-new",
        )
        item_sel = sel.get(
            "item",
            "material-list-item[class*='user-customer-list-item']",
        )
        try:
            heading = page.locator(heading_sel).first
            if heading.is_visible(timeout=3_000):
                return True
        except Exception:
            pass
        try:
            if page.locator(item_sel).count() > 0:
                return True
        except Exception:
            pass
        return False

    def _select_account_from_selection_page(self, page: "Page") -> None:
        """초기 Google Ads 계정 선택 화면에서 account_id 행을 클릭."""
        target_id = self._normalize_account_id(self.account_id)
        if not target_id:
            raise RuntimeError(
                "Google Ads 계정 선택 화면에서 사용할 account_id가 없습니다. "
                "config.json → media.google.accounts[].account_id 를 확인하세요."
            )

        sel = self._sel.get("account_selection", {})
        item_sel = sel.get(
            "item",
            "material-list-item.user-customer-list-item[role='menuitem']",
        )
        id_sel = sel.get("account_id", ".material-list-item-secondary")

        self._info(f"계정 선택 화면에서 고객 ID 검색: {self.account_id}")
        items = page.locator(item_sel)
        items.first.wait_for(state="visible", timeout=10_000)

        for item in items.all():
            try:
                displayed_id = item.locator(id_sel).first.inner_text(timeout=1_500).strip()
                if self._normalize_account_id(displayed_id) != target_id:
                    continue

                account_text = item.inner_text(timeout=1_500).strip().replace("\n", " / ")
                item.click()
                self._info(f"Google Ads 계정 선택: {account_text}")
                self.human_delay(1_000, 2_000)

                # 고객 ID 선택 후 Google Ads 본 화면으로 전환될 때까지 대기.
                try:
                    page.wait_for_function(
                        "() => !document.querySelector(\"h2[aria-label='Google Ads 계정 선택']\")",
                        timeout=30_000,
                    )
                except Exception:
                    pass
                self.human_delay(500, 900)

                if self._is_account_selection_page(page):
                    raise RuntimeError(
                        f"Google Ads 고객 ID {self.account_id} 클릭 후에도 "
                        "계정 선택 화면에 머물러 있습니다."
                    )
                self._info(f"Google Ads 계정 진입 완료 → {page.url}")
                return
            except RuntimeError:
                raise
            except Exception:
                continue

        self._screenshot(page, "google_initial_account_list")
        raise RuntimeError(
            f"Google Ads 계정 선택 화면에서 고객 ID '{self.account_id}'를 "
            "찾을 수 없습니다."
        )

    # ------------------------------------------------------------------ #
    # 2-a. Account switching (MCC → client account)                       #
    # ------------------------------------------------------------------ #
    def _is_current_account(self, page: "Page") -> bool:
        """상단 헤더에 이미 account_name 이 표시 중인지 확인."""
        if not self.account_name:
            return False
        try:
            header = page.locator("header, #header, [role='banner']").first
            txt = header.inner_text(timeout=2_000)
            if self.account_name.lower() in txt.lower():
                return True
        except Exception:
            pass
        try:
            if self.account_name.lower() in page.title().lower():
                return True
        except Exception:
            pass
        return False

    def _switch_account(self, page: "Page") -> None:
        """
        상단 계정 트리거 클릭 → account_name 항목 선택 → '계정 전환' 확인.

        확인된 HTML (Screenshot 2-3):
          trigger: material-gaia-picker .trigger[aria-haspopup='true']
          계정 항목: customer-item span.name
          확인 버튼: button '계정 전환'
        """
        # 최초 진입 시 표시되는 고객 ID 선택 화면은 상단 MCC 드롭다운과
        # DOM 구조가 다르므로 account_id로 먼저 처리한다.
        if self._is_account_selection_page(page):
            self._select_account_from_selection_page(page)
            return

        if self._is_current_account(page):
            self._info(f"이미 '{self.account_name}' 계정 — 전환 생략")
            return

        self._info(f"계정 전환 시작: {self.account_name}")
        sel = self._sel["account_switch"]

        # ① 계정 트리거 클릭
        trigger = page.locator(sel["trigger"]).first
        trigger.wait_for(state="visible", timeout=8_000)
        trigger.click()
        self.human_delay(800, 1500)

        # ② account_name 일치 항목 클릭
        name = self.account_name
        matched = False

        # 방법 1: customer-item span.name 텍스트 순회
        try:
            for item in page.locator(sel["account_name_span"]).all():
                try:
                    if name.lower() in item.inner_text(timeout=1_000).lower():
                        item.click()
                        self.human_delay(500, 900)
                        matched = True
                        self._info(f"계정 선택: '{name}'")
                        break
                except Exception:
                    continue
        except Exception:
            pass

        # 방법 2: page.get_by_text fallback
        if not matched:
            try:
                page.get_by_text(name, exact=True).first.click()
                self.human_delay(500, 900)
                matched = True
                self._info(f"계정 선택 (fallback): '{name}'")
            except Exception:
                pass

        if not matched:
            self._screenshot(page, "google_account_list")
            raise RuntimeError(
                f"Google Ads 계정 '{name}' 을 목록에서 찾을 수 없습니다.\n"
                "config.json → media.google.accounts[].account_name 을\n"
                "계정 목록 표시 이름과 정확히 일치하게 입력하세요."
            )

        # ③ '계정 전환' 버튼 클릭 (있으면)
        try:
            sw_btn = page.locator(sel["switch_button"]).first
            if sw_btn.is_visible(timeout=3_000):
                sw_btn.click()
                self.human_delay(1_000, 2_000)
                self._info("'계정 전환' 버튼 클릭")
        except Exception:
            pass  # 항목 클릭만으로 전환되는 경우도 있음

        page.wait_for_load_state("networkidle", timeout=30_000)
        self._info(f"계정 전환 완료 → {page.url}")

    # ------------------------------------------------------------------ #
    # 2-b. Navigate to the saved report                                    #
    # ------------------------------------------------------------------ #
    def navigate_to_report(self, page: "Page") -> None:
        self._info(f"Looking for report: '{self.report_name}'")

        # 최초 고객 ID 선택 화면은 account_name 유무와 관계없이 account_id로 처리.
        if self._is_account_selection_page(page):
            self._select_account_from_selection_page(page)
        # Google Ads 본 화면에서는 기존 MCC 드롭다운 전환 로직 사용.
        elif self.account_name:
            self._switch_account(page)

        # '통계 및 보고서' 섹션 펼치기
        try:
            stats = page.locator(self._sel["report"]["sidebar_stats_section"]).first
            if stats.is_visible(timeout=2_000):
                stats.click()
                self.human_delay(400, 700)
        except Exception:
            pass

        # '보고서 에디터' 클릭
        try:
            nav = page.locator(self._sel["report"]["sidebar_report_editor"]).first
            if nav.is_visible(timeout=3_000):
                nav.click()
                self.human_delay(800, 1500)
                page.wait_for_load_state("networkidle", timeout=20_000)
        except Exception:
            # Fallback: 직접 URL 이동
            base = self._sel["base_url"]
            suffix = self._sel["report"]["report_editor_url_suffix"]
            try:
                page.goto(base + suffix, wait_until="networkidle", timeout=30_000)
                self.human_delay(500, 1000)
            except Exception:
                pass

        # "저장된 보고서" 섹션이 접혀 있으면 펼치기
        self._expand_saved_reports(page)

        # 저장된 보고서 클릭
        self._click_report_by_name(page)

        # 필터 확인 (캠페인/광고그룹 상태 → '전체')
        self._ensure_filters_all(page)

    def _ensure_filters_all(self, page: "Page") -> None:
        """
        필터가 '전체'가 아니면 '재설정' 버튼으로 초기화.
        재설정 버튼 없으면 개별 칩 클릭으로 fallback.
        chip이 보이지 않거나 텍스트를 읽을 수 없으면 안전하게 needs_reset=True 처리.
        """
        f_sel = self._sel.get("filters", {})
        good_text = f_sel.get("good_status_text", "전체")
        bad_text   = f_sel.get("bad_status_text", "사용중")

        # 필터 상태 확인
        chips = [
            ("캠페인 상태",  f_sel.get("campaign_status_chip", "")),
            ("광고그룹 상태", f_sel.get("adgroup_status_chip", "")),
        ]
        needs_reset = False
        for label, chip_sel in chips:
            if not chip_sel:
                continue
            try:
                chip = page.locator(chip_sel).first
                if not chip.is_visible(timeout=2_000):
                    continue
                chip_text = chip.inner_text(timeout=2_000).strip()
                # "전체"가 포함되어 있어도 "사용중" 같은 bad_text가 함께 있으면 reset
                has_good = good_text in chip_text
                has_bad  = bad_text and bad_text in chip_text
                if has_good and not has_bad:
                    self._info(f"{label} filter: OK ({good_text})")
                else:
                    self._warn(f"{label} filter 재설정 필요: '{chip_text}'")
                    needs_reset = True
            except Exception:
                pass

        if not needs_reset:
            return

        # 방법 1: 재설정 클릭 (텍스트로 찾기 — 엘리먼트 종류 무관)
        try:
            reset_btn = page.get_by_text("재설정", exact=True).first
            reset_btn.wait_for(state="visible", timeout=3_000)
            reset_btn.click()
            self.human_delay(800, 1_200)
            page.wait_for_load_state("networkidle", timeout=15_000)
            self._info("필터 재설정 완료 (재설정 버튼)")
            return
        except Exception:
            pass

        # 방법 2: 개별 칩 클릭으로 전체 선택
        for label, chip_sel in chips:
            if not chip_sel:
                continue
            try:
                chip = page.locator(chip_sel).first
                if not chip.is_visible(timeout=2_000):
                    continue
                chip_text = chip.inner_text(timeout=2_000)
                if good_text in chip_text:
                    continue

                chip.click()
                self.human_delay(500, 800)
                all_opt = page.locator(
                    f_sel.get("all_option", "material-select-item:has-text('전체')")
                ).first
                all_opt.wait_for(state="visible", timeout=5_000)
                all_opt.click()
                self.human_delay(400, 600)
                page.wait_for_load_state("networkidle", timeout=15_000)
                self._info(f"{label} filter → 전체")
            except Exception as e:
                self._warn(f"{label} filter reset 실패: {e}")

    def _expand_saved_reports(self, page: "Page") -> None:
        """'저장된 보고서' 섹션이 접혀 있으면 클릭해서 펼침.

        주의: "자주 사용하는 보고서" 카드 내부에도 "저장된 보고서" 배지 텍스트가
        있으므로 get_by_text().first 로 잡으면 카드를 클릭해버린다.
        → JavaScript 로 aria-expanded 를 가진 조상을 탐색해 섹션 헤더만 클릭한다.
        """
        self._screenshot(page, "google_before_expand_saved_reports")
        try:
            result = page.evaluate("""() => {
                // "저장된 보고서" 텍스트 노드를 모두 수집
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                const candidates = [];
                let node;
                while ((node = walker.nextNode())) {
                    if (node.textContent.trim() === '저장된 보고서') {
                        candidates.push(node);
                    }
                }

                // 각 후보에서 aria-expanded 조상 탐색 → 있으면 섹션 헤더
                for (const node of candidates) {
                    let el = node.parentElement;
                    let depth = 0;
                    while (el && depth < 12) {
                        if (el.hasAttribute('aria-expanded')) {
                            const expanded = el.getAttribute('aria-expanded');
                            if (expanded === 'false') {
                                el.click();
                                return 'clicked_header:' + el.tagName + ':was_false';
                            }
                            return 'already_open:' + el.tagName;
                        }
                        el = el.parentElement;
                        depth++;
                    }
                }

                // fallback: 마지막 후보 부모 클릭 (섹션 헤더가 카드들보다 뒤에 위치)
                if (candidates.length > 0) {
                    const last = candidates[candidates.length - 1];
                    last.parentElement.click();
                    return 'fallback_last_clicked';
                }
                return 'not_found';
            }""")
            self._info(f"'저장된 보고서' 섹션: {result}")
            self.human_delay(1200, 1800)
            # 섹션 내 모든 항목 렌더링을 위해 스크롤
            try:
                page.evaluate("""() => {
                    const lists = document.querySelectorAll('[class*="saved-report"], [class*="report-list"], nav[class*="report"]');
                    for (const el of lists) { el.scrollTop = el.scrollHeight; }
                    window.scrollTo(0, document.body.scrollHeight);
                }""")
                self.human_delay(500, 800)
            except Exception:
                pass
            self._screenshot(page, "google_after_expand_saved_reports")
        except Exception as e:
            self._warn(f"'저장된 보고서' 섹션 펼치기 실패 (무시): {e}")

    def _click_report_by_name(self, page: "Page") -> None:
        name = self.report_name

        # 현재 화면에 보이는 보고서명 전체 로그 (진단용)
        try:
            visible_names = []
            for el in page.locator("span.report-name-text, [class*='report-name'] span").all():
                try:
                    t = el.inner_text(timeout=500).strip()
                    if t:
                        visible_names.append(t)
                except Exception:
                    pass
            self._info(f"화면 보고서 목록 ({len(visible_names)}개): {visible_names}")
        except Exception:
            pass

        # 방법 1: 정확 텍스트 매칭 (자주 사용하는 카드 + 저장된 보고서 목록 모두 포함)
        try:
            target = page.get_by_text(name, exact=True).first
            target.wait_for(state="visible", timeout=10_000)
            target.click()
            self.human_delay(1000, 2000)
            page.wait_for_load_state("networkidle", timeout=25_000)
            self._info(f"Report '{name}' opened")
            return
        except Exception:
            pass

        # 방법 2: span.report-name-text 순회 (정확 일치만)
        link_sel = self._sel["report"]["report_list_link"]
        try:
            for link in page.locator(link_sel).all():
                if link.inner_text(timeout=1_000).strip() == name:
                    link.click()
                    self.human_delay(1000, 2000)
                    page.wait_for_load_state("networkidle", timeout=25_000)
                    self._info(f"Report '{name}' opened (fallback)")
                    return
        except Exception:
            pass

        # 방법 3: 정확 텍스트 매칭 (report-name 클래스)
        try:
            for el in page.locator("[class*='report-name'], [class*='reportName']").all():
                txt = el.inner_text(timeout=500).strip()
                if txt == name:
                    el.click()
                    self.human_delay(1000, 2000)
                    page.wait_for_load_state("networkidle", timeout=25_000)
                    self._info(f"Report '{name}' opened (exact class match: '{txt}')")
                    return
        except Exception:
            pass

        # 방법 4: 화면에 보이는 모든 텍스트 중 보고서명 포함 요소 클릭
        try:
            for el in page.locator("li, a, span, div").all():
                try:
                    txt = el.inner_text(timeout=200).strip()
                    if txt == name:
                        el.click()
                        self.human_delay(1000, 2000)
                        page.wait_for_load_state("networkidle", timeout=25_000)
                        self._info(f"Report '{name}' opened (dom scan)")
                        return
                except Exception:
                    continue
        except Exception:
            pass

        self._screenshot(page, "google_report_list")
        raise RuntimeError(
            f"Report '{name}' not found in Google Ads report editor. "
            "Check config.json report_name."
        )

    # ------------------------------------------------------------------ #
    # 3. Set date period                                                   #
    # ------------------------------------------------------------------ #
    def set_period(self, page: "Page", start: date, end: date) -> None:
        """
        Google Ads 날짜 범위 선택:
          1. 날짜 버튼 클릭 (aria-label: '기간 선택')
          2. '맞춤' 옵션 선택
          3. 시작/종료 날짜 입력
          4. 적용
        """
        sel = self._sel["period"]

        if self._dates_already_set(page, start, end):
            self._info(f"Date unchanged ({start} ~ {end})")
            return

        date_btn = page.locator(sel["date_range_button"]).first
        date_btn.wait_for(state="visible", timeout=10_000)
        # acx-overlay-container 및 모든 자식 요소(material-tree-shift, top-section 등)
        # 가 포인터 이벤트를 차단하므로 JS로 완전 비활성화 후 dispatch_event로 클릭
        page.evaluate("""() => {
            document.querySelectorAll('acx-overlay-container, acx-overlay-container *').forEach(
                el => el.style.setProperty('pointer-events', 'none', 'important')
            );
        }""")
        try:
            date_btn.dispatch_event("click")
        except Exception:
            date_btn.click(force=True)
        # 버튼 클릭 후 pointer-events 복구 — date picker 드롭다운과 상호작용하기 위해
        page.evaluate("""() => {
            document.querySelectorAll('acx-overlay-container, acx-overlay-container *').forEach(
                el => el.style.removeProperty('pointer-events')
            );
        }""")
        self.human_delay(500, 900)

        self._select_custom_range(page, sel)
        self.human_delay(500, 800)

        # 날짜 피커 상태 디버그 캡처
        self._screenshot(page, f"{self.MEDIA_CODE}_date_picker_after_custom")

        start_str = start.strftime("%Y-%m-%d")
        end_str   = end.strftime("%Y-%m-%d")

        self._info(f"Setting start: {start_str}")
        self._fill_date_input(page, sel["start_input"], start_str, start)

        self._info(f"Setting end: {end_str}")
        self._fill_date_input(page, sel["end_input"], end_str, end)

        # Fallback: input.input-area 인덱스 기반 입력 (aria-label 없는 Google Ads 날짜 필드)
        self._fill_date_inputs_by_index(page, start, end)

        self.human_delay(300, 500)

        try:
            apply = page.locator(sel["apply_button"]).first
            if apply.is_visible(timeout=3_000):
                apply.click()
                self.human_delay(800, 1500)
                self._info("Date range applied")
        except Exception:
            pass

        page.wait_for_load_state("networkidle", timeout=25_000)

    def _dates_already_set(self, page: "Page", start: date, end: date) -> bool:
        try:
            btn = page.locator(self._sel["period"]["date_range_button"]).first
            text = btn.get_attribute("aria-label", timeout=2_000) or ""
            s_day   = str(start.day)
            e_day   = str(end.day)
            s_month = str(start.month)
            return s_day in text and e_day in text and s_month in text
        except Exception:
            return False

    def _select_custom_range(self, page: "Page", sel: dict) -> None:
        try:
            custom = page.locator(sel["custom_range_option"]).first
            if custom.is_visible(timeout=3_000):
                custom.click()
                self.human_delay(400, 700)
                self._info("Custom range selected")
        except Exception:
            self._info("Custom range option not found — popup may already show inputs")

    def _fill_date_input(self, page: "Page", selector: str, iso_str: str, dt: date) -> None:
        """ISO 형식으로 날짜 입력, 실패 시 한국어 형식 시도."""
        for s in selector.split(","):
            s = s.strip()
            try:
                inp = page.locator(s).first
                if not inp.is_visible(timeout=2_000):
                    self._info(f"  날짜 input 비가시: {s!r}")
                    continue
                inp.triple_click()
                inp.fill(iso_str)
                self.human_delay(200, 400)
                self._info(f"  날짜 입력 성공 ({s!r}): {iso_str}")
                return
            except Exception as e:
                self._info(f"  날짜 input 실패 ({s!r}): {e}")
                continue

        # 화면에 보이는 모든 input 태그 목록 로그
        try:
            visible_inputs = page.evaluate("""() => {
                return Array.from(document.querySelectorAll('input')).map(el => ({
                    type: el.type,
                    aria: el.getAttribute('aria-label'),
                    placeholder: el.placeholder,
                    cls: el.className.substring(0, 60),
                    visible: el.offsetParent !== null
                })).filter(x => x.visible);
            }""")
            self._info(f"  화면 input 목록: {visible_inputs}")
        except Exception:
            pass

        # Fallback: 한국어 형식
        kr_str = f"{dt.year}년 {dt.month}월 {dt.day}일"
        for s in selector.split(","):
            s = s.strip()
            try:
                inp = page.locator(s).first
                if not inp.is_visible(timeout=1_000):
                    continue
                inp.triple_click()
                inp.type(kr_str, delay=50)
                self.human_delay(200, 400)
                self._info(f"  날짜 입력 성공-KR ({s!r}): {kr_str}")
                return
            except Exception:
                continue

        self._warn(f"Could not fill date input for {iso_str}")

    def _fill_date_inputs_by_index(self, page: "Page", start: date, end: date) -> None:
        """input.input-area 인덱스 기반 날짜 입력 (Angular 이벤트 트리거 포함).

        fill()은 Angular의 reactive form 이벤트를 트리거하지 못하므로
        triple_click() + keyboard.type() 조합으로 character-by-character 입력.
        """
        # aria-required="true" 인 input.input-area만 → 시작일/종료일 정확히 2개
        try:
            all_inputs = page.locator("input.input-area[aria-required='true']").all()
            visible = [inp for inp in all_inputs if inp.is_visible(timeout=500)]
        except Exception:
            return

        if len(visible) < 2:
            self._info(f"  aria-required input {len(visible)}개 (2개 미만) — 날짜 피커 미열림")
            return

        self._info(f"  날짜 피커 input {len(visible)}개 발견 — 인덱스 기반 입력 시작")

        # 한국어 날짜 형식: YYYY. M. D. (피커 표시 형식과 동일)
        s_str = f"{start.year}. {start.month}. {start.day}."
        e_str = f"{end.year}. {end.month}. {end.day}."

        pairs = [(visible[0], s_str, "시작일"), (visible[1], e_str, "종료일")]
        for inp, date_str, label in pairs:
            try:
                inp.click()
                self.human_delay(150, 250)
                # 전체 선택 후 문자별 타이핑 (Angular input 이벤트 발생)
                inp.press("Control+a")
                self.human_delay(80, 120)
                page.keyboard.type(date_str, delay=40)
                self.human_delay(300, 450)
                inp.press("Tab")  # blur → Angular change detection
                self.human_delay(200, 350)
                actual = inp.input_value(timeout=800)
                self._info(f"  {label} 입력: '{date_str}' → 실제값: '{actual}'")
            except Exception as e:
                self._warn(f"  {label} 입력 실패: {e}")

    # ------------------------------------------------------------------ #
    # 4. Trigger download                                                  #
    # ------------------------------------------------------------------ #
    def trigger_download(self, page: "Page", start: date, end: date) -> Path:
        """
        다운로드 아이콘 클릭 → 포맷 팝업 → Excel(.xlsx) 선택.

        확인된 HTML (Screenshot 8):
          <material-button aria-label="다운로드" aria-haspopup="true" ...>
            <download-menu ...>...</download-menu>
          </material-button>
        """
        dl_cfg = self._sel["download"]
        timeout_ms = self.timeout_sec * 1_000

        btn = self._find_download_button(page, dl_cfg)
        if btn is None:
            self._screenshot(page, "google_dl_not_found")
            raise RuntimeError(
                "Google Ads 다운로드 버튼 없음. "
                "selectors/google.yaml → download.button 확인"
            )

        self.human_delay(300, 600)

        # 버튼 클릭 → 포맷 팝업 오픈
        btn.click()
        self.human_delay(1_200, 1_800)  # 팝업 렌더링 대기

        # Excel(.xlsx) 포맷 선택 후 다운로드 대기
        fmt_excel = dl_cfg.get("format_excel", "")
        fmt_csv   = dl_cfg.get("format_csv", "")

        with page.expect_download(timeout=timeout_ms) as dl_info:
            clicked = False
            for fmt_sel in (fmt_excel, fmt_csv):
                if not fmt_sel or clicked:
                    continue
                for s in fmt_sel.split(","):
                    s = s.strip()
                    try:
                        opt = page.locator(s).first
                        if opt.is_visible(timeout=3_000):
                            opt.click()
                            clicked = True
                            self._info(f"다운로드 포맷 선택: {s}")
                            break
                    except Exception:
                        continue

            if not clicked:
                # 포맷 팝업 없음 — 버튼 재클릭으로 직접 다운로드
                self._info("포맷 팝업 없음 — 버튼 재클릭으로 다운로드 시도")
                btn.click()

        download = dl_info.value
        suggested = download.suggested_filename or "google_report.xlsx"
        suffix = Path(suggested).suffix or ".xlsx"
        tmp = Path(tempfile.mktemp(suffix=suffix))
        download.save_as(str(tmp))

        if not tmp.exists() or tmp.stat().st_size == 0:
            raise RuntimeError(f"Google Ads 다운로드 파일 비어있음: {tmp}")

        self._info(f"파일: {suggested} ({tmp.stat().st_size:,} bytes)")
        return tmp

    def _find_download_button(self, page: "Page", dl_cfg: dict):
        for key in ("button", "button_fallback"):
            s = dl_cfg.get(key, "")
            if not s:
                continue
            try:
                loc = page.locator(s).first
                loc.wait_for(state="visible", timeout=8_000)
                return loc
            except Exception:
                continue
        return None
