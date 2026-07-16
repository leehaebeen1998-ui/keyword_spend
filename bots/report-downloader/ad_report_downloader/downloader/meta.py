"""Meta Ads Manager (Facebook/Instagram) report downloader.

계정 전환 흐름 (1회 로그인 / 다중 계정):
  1. check_login(): /adsreporting/ 접속 후 세션 확인
  2. navigate_to_report():
     a. account_id + business_id 가 있으면 URL 직접 이동
        → https://adsmanager.facebook.com/adsreporting/?act={account_id}&business_id={business_id}
     b. 보고서 목록에서 report_name 클릭
  3. set_period(): 날짜 범위 선택
  4. trigger_download(): 내보내기 버튼 클릭

config.json 필수 필드:
  account_id  : 숫자 광고 계정 ID (예: "1191819368044014")
  business_id : Meta 비즈니스 계정 ID (예: "187111177012330") — 공통값
  report_name : 저장된 보고서 이름 (예: "메타 주간보고서")
"""
from __future__ import annotations
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse, parse_qs

import yaml

if TYPE_CHECKING:
    from playwright.sync_api import Page

from downloader.base import BaseDownloader, EmptyDataError

_SELECTOR_FILE = Path(__file__).parent.parent / "selectors" / "meta.yaml"


def _load_selectors() -> dict:
    with _SELECTOR_FILE.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


class MetaDownloader(BaseDownloader):
    MEDIA_CODE = "meta"
    IMPLEMENTED = True

    def __init__(self, config: dict, account: dict | None = None):
        super().__init__(config, account)
        self._sel = _load_selectors()

    # ------------------------------------------------------------------ #
    # 1. Login check                                                       #
    # ------------------------------------------------------------------ #
    def check_login(self, page: "Page") -> bool:
        """
        /adsreporting/ 접속 후 로그인 여부 확인.
        로그인 페이지로 리다이렉트되거나 로그인 폼이 보이면 False.
        Chrome 프로필 세션만 사용 (쿠키 파일 주입 없음).
        """
        base = self._sel["base_url"]
        path = self._sel["report"]["reporting_url_path"]  # /adsreporting/
        page.goto(base + path, wait_until="domcontentloaded", timeout=30_000)
        self.human_delay(1000, 2000)

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

    # ------------------------------------------------------------------ #
    # 2. Navigate to the saved report                                      #
    # ------------------------------------------------------------------ #
    def navigate_to_report(self, page: "Page") -> None:
        self._info(f"Looking for report: '{self.report_name}'")

        # 1. 계정 전환 (account_id 있을 경우 URL 직접 이동)
        if self.account_id:
            self._switch_account(page)
        else:
            # account_id 없으면 보고서 목록으로 직접 이동
            self._goto_report_list(page)

        # 2. 저장된 보고서 클릭
        self._click_report_by_name(page)

    def _is_current_account(self, page: "Page") -> bool:
        """URL의 act 파라미터로 현재 계정 확인 (가장 신뢰도 높음)."""
        try:
            parsed = urlparse(page.url)
            params = parse_qs(parsed.query)
            act = params.get("act", [""])[0]
            if act and self.account_id and act == str(self.account_id):
                return True
        except Exception:
            pass
        return False

    def _switch_account(self, page: "Page") -> None:
        """
        URL 직접 이동으로 계정 전환.
        act={account_id}&business_id={business_id} 파라미터 사용.
        """
        if self._is_current_account(page):
            self._info(f"이미 계정 {self.account_id} 선택됨")
            return

        acc_cfg = self._sel["account_switch"]
        url_tpl = acc_cfg["reporting_url_with_account"]

        # account_id는 self.account_id, business_id는 account dict 또는 media config에서
        business_id = ""
        if self.account:
            business_id = str(self.account.get("business_id", ""))
        if not business_id:
            # config["media"]["meta"]["business_id"] (공통값)
            _media_cfg = self.config.get("media", {}).get("meta", {})
            business_id = str(_media_cfg.get("business_id", ""))

        if not business_id:
            self._warn(
                "business_id 미설정 — account 또는 config에 business_id를 추가하세요. "
                "account_id만으로 보고서 목록 이동 시도."
            )
            url = self._sel["base_url"] + f"/adsreporting/?act={self.account_id}"
        else:
            url = self._sel["base_url"] + url_tpl.format(
                account_id=self.account_id,
                business_id=business_id,
            )

        self._info(f"계정 전환: act={self.account_id}, business_id={business_id}")
        try:
            page.goto(url, wait_until="networkidle", timeout=35_000)
            self.human_delay(800, 1500)
        except Exception as e:
            self._screenshot(page, "meta_account_switch_failed")
            raise RuntimeError(f"Meta 계정 전환 실패: {e}") from e

        if not self._is_current_account(page):
            self._warn(
                f"계정 전환 후 URL act 파라미터가 {self.account_id}와 다름 — 계속 진행"
            )

    def _goto_report_list(self, page: "Page") -> None:
        """account_id 없이 보고서 목록으로 이동."""
        base = self._sel["base_url"]
        path = self._sel["report"]["reporting_url_path"]
        if "/adsreporting" not in page.url.lower():
            try:
                page.goto(base + path, wait_until="networkidle", timeout=30_000)
                self.human_delay(800, 1500)
            except Exception:
                pass

    def _click_report_by_name(self, page: "Page") -> None:
        name = self.report_name

        # Primary: get_by_text exact match
        try:
            target = page.get_by_text(name, exact=True).first
            target.wait_for(state="visible", timeout=10_000)
            target.click()
            self.human_delay(1200, 2500)
            page.wait_for_load_state("networkidle", timeout=25_000)
            self._info(f"Report '{name}' opened")
            return
        except Exception:
            pass

        # Fallback: scan list items
        link_sel = self._sel["report"]["report_list_item"]
        try:
            for item in page.locator(link_sel).all():
                try:
                    if name in item.inner_text(timeout=800):
                        item.click()
                        self.human_delay(1200, 2500)
                        page.wait_for_load_state("networkidle", timeout=25_000)
                        self._info(f"Report '{name}' opened (fallback)")
                        return
                except Exception:
                    continue
        except Exception:
            pass

        self._screenshot(page, "meta_report_list")
        raise RuntimeError(
            f"Report '{name}' not found in Meta Ads reporting. "
            "Check config.json report_name."
        )

    # ------------------------------------------------------------------ #
    # 3. Set date period                                                   #
    # ------------------------------------------------------------------ #
    def set_period(self, page: "Page", start: date, end: date) -> None:
        """
        Meta date picker flow:
          1. 날짜 범위 버튼 클릭 → 캘린더+프리셋 다이얼로그 오픈 (바로 열림, '맞춤 설정' 불필요)
          2a. 프리셋 클릭 (오늘/어제 등 일치 시 — 가장 안정적)
          2b. 캘린더 셀 클릭 (같은 날 3-click 방식: 더미→시작→종료)
          3. '업데이트' 버튼 클릭
        """
        sel = self._sel["period"]

        # 1. 날짜 범위 버튼 클릭 → 다이얼로그 오픈
        date_btn = page.locator(sel["date_range_button"]).first
        date_btn.wait_for(state="visible", timeout=10_000)
        date_btn.click()
        self.human_delay(1000, 1500)

        # 2a. 프리셋 클릭 (오늘/어제 — 일일 보고서 가장 빈번한 케이스)
        if self._try_date_preset(page, start, end):
            pass  # 프리셋으로 날짜 설정 완료, 업데이트 버튼만 남음
        else:
            # 2b. 캘린더 셀 클릭
            self._screenshot(page, "meta_before_calendar_click")
            if start == end:
                # 같은 날 선택: 더미 날짜 먼저 클릭 후 시작→종료
                dummy = start - timedelta(days=1)
                self._navigate_calendar_to_month(page, dummy)
                self._click_calendar_day(page, dummy, "더미(초기화)")
                self.human_delay(400, 600)
            self._navigate_calendar_to_month(page, start)
            self._click_calendar_day(page, start, "시작일")
            self.human_delay(500, 800)
            self._navigate_calendar_to_month(page, end)
            self._click_calendar_day(page, end, "종료일")
            self.human_delay(500, 800)

        # 3. 업데이트/적용 버튼 클릭
        apply_sel = (
            "[data-surface='/am/date_picker'] [role='button']:has-text('업데이트'), "
            "[role='button']:has-text('업데이트'), "
            "[data-surface='/am/date_picker'] [role='button']:has-text('적용'), "
            "[role='button']:has-text('적용')"
        )
        try:
            apply_btn = page.locator(apply_sel).last
            apply_btn.wait_for(state="visible", timeout=5_000)
            apply_btn.click()
            self.human_delay(1000, 2000)
            self._info(f"날짜 범위 적용: {start} ~ {end}")
        except Exception as e:
            self._warn(f"업데이트 버튼 클릭 실패: {e}")

        page.wait_for_load_state("networkidle", timeout=25_000)

    def _try_date_preset(self, page: "Page", start: date, end: date) -> bool:
        """
        날짜 범위가 프리셋(오늘/어제)과 일치하면 해당 버튼 클릭.
        성공 시 True.
        스크린샷에서 확인된 프리셋 목록:
          최대, 오늘, 어제, 최근7일, 최근14일, 최근28일, 이번주, 지난주, 이번달...
        """
        today = date.today()
        yesterday = today - timedelta(days=1)

        preset_text = None
        if start == end == today:
            preset_text = "오늘"
        elif start == end == yesterday:
            preset_text = "어제"

        if not preset_text:
            return False

        # 프리셋 셀렉터 후보
        candidates = [
            f"[role='radio']:has-text('{preset_text}')",
            f"[role='listitem']:has-text('{preset_text}')",
            f"li:has-text('{preset_text}')",
            f"[role='button']:has-text('{preset_text}')",
        ]
        for sel_str in candidates:
            try:
                btn = page.locator(sel_str).first
                if btn.is_visible(timeout=2_000):
                    btn.click()
                    self.human_delay(400, 700)
                    self._info(f"날짜 프리셋 선택: '{preset_text}'")
                    return True
            except Exception:
                continue

        self._warn(f"프리셋 '{preset_text}' 버튼을 찾지 못함 — 캘린더 클릭으로 전환")
        return False

    def _navigate_calendar_to_month(self, page: "Page", target: date) -> None:
        """
        달력이 저장된 기간으로 열려 있을 때 target 월까지 '다음 달' 버튼 클릭.
        Meta 달력의 > 버튼은 aria-label 없이 SVG만 있는 경우가 많으므로
        위치 기반 JS로 가장 오른쪽 소형 버튼을 클릭.
        """
        target_ko = f"{target.year}년 {target.month}월"
        target_en = target.strftime('%B %Y')  # "June 2026"

        def is_visible() -> bool:
            # 1차: 해당 달 1일 캘린더 셀이 DOM에 존재하는지 확인 (가장 정확)
            en_first = f"1 {target.strftime('%B %Y')}"   # "1 June 2026"
            ko_first = f"{target.year}년 {target.month}월 1일"  # "2026년 6월 1일"
            for label in [en_first, ko_first]:
                try:
                    if page.locator(f"[role='button'][aria-label*='{label}']").count() > 0:
                        return True
                except Exception:
                    pass
            # 2차: JS로 leaf 요소 중 월 헤더 텍스트 정확 매칭
            try:
                return bool(page.evaluate(f"""() => {{
                    const t1 = '{target_ko}';
                    const t2 = '{target_en}';
                    return [...document.querySelectorAll('*')].some(el =>
                        el.children.length === 0 &&
                        (el.textContent.trim() === t1 || el.textContent.trim() === t2)
                    );
                }}"""))
            except Exception:
                pass
            return False

        if is_visible():
            return

        # JS: 달력의 '다음 달(>)' 버튼 클릭
        # DevTools 확인: 버튼 내부에 숨겨진 div로 "다음 달" 텍스트가 있음 (aria-label 없음)
        click_next_js = """() => {
            // 1) innerText에 "다음 달" 포함 버튼 (확인된 DOM 구조)
            const byText = [...document.querySelectorAll('[role="button"], button')].filter(e =>
                e.textContent.includes('다음 달') || e.textContent.includes('Next month')
            );
            if (byText.length > 0) { byText[byText.length - 1].click(); return 'text-match'; }

            // 2) aria-label 기반 (혹시 있을 경우)
            const byLabel = [...document.querySelectorAll('[role="button"], button')].filter(e => {
                const la = (e.getAttribute('aria-label') || '').toLowerCase();
                return la.includes('다음') || la.includes('next');
            });
            if (byLabel.length > 0) { byLabel[byLabel.length - 1].click(); return 'label'; }

            // 3) 월 헤더("2026년 X월") 오른쪽 소형 버튼
            const allEls = [...document.querySelectorAll('*')];
            const monthHeaders = allEls.filter(el =>
                el.children.length === 0 && /\\d{4}년 \\d{1,2}월/.test(el.textContent.trim())
            );
            if (monthHeaders.length > 0) {
                monthHeaders.sort((a, b) =>
                    b.getBoundingClientRect().left - a.getBoundingClientRect().left
                );
                const rr = monthHeaders[0].getBoundingClientRect();
                const nextBtns = [...document.querySelectorAll('[role="button"], button')].filter(b => {
                    const br = b.getBoundingClientRect();
                    return br.left >= rr.right - 5
                        && br.top >= rr.top - 10 && br.bottom <= rr.bottom + 10
                        && br.width <= 60;
                });
                if (nextBtns.length > 0) { nextBtns[0].click(); return 'header-right'; }
            }
            return 'none';
        }"""

        for step in range(18):
            if is_visible():
                self._info(f"캘린더 {step}회 이동 → {target_ko}")
                return
            try:
                result = page.evaluate(click_next_js)
                self.human_delay(300, 500)
                if result == 'none':
                    self._warn(f"캘린더 다음달 버튼 없음 (step={step})")
                    break
            except Exception as e:
                self._warn(f"캘린더 이동 JS 실패: {e}")
                break

        if not is_visible():
            self._warn(f"{target_ko} 이동 실패 — 현재 뷰에서 클릭 시도")

    def _click_calendar_day(self, page: "Page", target: date, label: str) -> None:
        """
        캘린더에서 특정 날짜 셀을 클릭합니다.
        aria-label 형식은 UI 언어에 따라 다름:
          - 영어: "Monday, 15 June 2026"  → 부분 매칭: "15 June 2026"
          - 한국어: "2026년 6월 15일"      → 부분 매칭: "2026년 6월 15일"
        """
        # 영어 형식: "15 June 2026"
        en_label = f"{target.day} {target.strftime('%B %Y')}"
        # 한국어 형식: "2026년 6월 15일"
        ko_label = f"{target.year}년 {target.month}월 {target.day}일"

        candidates = [
            # 영어 — data-surface 한정
            (f"[data-surface='/am/date_picker/calendar_section'] [role='button'][aria-label*='{en_label}']", en_label),
            # 영어 — 전체
            (f"[role='button'][aria-label*='{en_label}']", en_label),
            # 한국어 — data-surface 한정
            (f"[data-surface='/am/date_picker/calendar_section'] [role='button'][aria-label*='{ko_label}']", ko_label),
            # 한국어 — 전체
            (f"[role='button'][aria-label*='{ko_label}']", ko_label),
        ]

        for sel_str, matched_label in candidates:
            try:
                cell = page.locator(sel_str).first
                cell.wait_for(state="visible", timeout=5_000)
                cell.click()
                self._info(f"{label} 클릭: {matched_label}")
                return
            except Exception:
                continue

        # 어떤 형식도 매칭 안 됨 → 실패로 처리 (잘못된 기간으로 다운로드 방지)
        self._screenshot(page, f"meta_calendar_{label}")
        raise RuntimeError(
            f"{label} 캘린더 셀 없음 — 영어({en_label}) / 한국어({ko_label}) 모두 실패. "
            "logs/debug/ 스크린샷 확인 후 selectors/meta.yaml 또는 _click_calendar_day 수정 필요."
        )

    # ------------------------------------------------------------------ #
    # 4. Trigger download (export)                                         #
    # ------------------------------------------------------------------ #
    def trigger_download(self, page: "Page", start: date, end: date) -> Path:
        """
        확인된 HTML (Screenshot 4 DevTools):
          <div aria-busy="false" ... role="button" tabindex="0"
               data-surface="am/lib:export_button" id="js_10g">
          <span id="export_button" ...>

        Meta 내보내기 흐름:
          1. export 버튼 클릭 → 파일 형식 다이얼로그가 열릴 수 있음
          2. 다이얼로그가 열리면 확인 버튼 클릭
          3. page.expect_download() 로 파일 수신
        """
        dl_cfg = self._sel["download"]
        timeout_ms = int(dl_cfg.get("timeout_sec", 120)) * 1_000

        btn = self._find_export_button(page, dl_cfg)
        if btn is None:
            self._screenshot(page, "meta_export_btn_not_found")
            raise RuntimeError(
                "Export button not found. Check selectors/meta.yaml download.button."
            )

        if btn.get_attribute("aria-disabled") == "true":
            raise EmptyDataError("Export button disabled — no data for period")

        self.human_delay(300, 600)

        # 메인 내보내기 버튼 클릭 → 모달 다이얼로그 대기
        btn.click()
        self.human_delay(1200, 2000)

        # 모달의 "내보내기" 확인 버튼 대기
        # 확인된 data-surface: /am/lib:ads_report_builder_export_dialog_modal_.../lib:export-confirm-button
        confirm_sel = dl_cfg.get("export_dialog_confirm", "[data-surface*='export-confirm-button']")
        try:
            confirm_btn = page.locator(confirm_sel).first
            confirm_btn.wait_for(state="visible", timeout=8_000)
            self._info("Export 모달 확인됨 — 내보내기 버튼 클릭")
        except Exception:
            self._screenshot(page, "meta_export_modal_not_found")
            raise RuntimeError(
                "Meta 내보내기 모달을 찾을 수 없습니다. "
                "selectors/meta.yaml의 export_dialog_confirm 셀렉터를 확인하세요."
            )

        with page.expect_download(timeout=timeout_ms) as dl_info:
            confirm_btn.click()

        download = dl_info.value
        suggested = download.suggested_filename or "meta_report.csv"
        suffix = Path(suggested).suffix or ".csv"
        tmp = Path(tempfile.mktemp(suffix=suffix))
        download.save_as(str(tmp))

        if not tmp.exists() or tmp.stat().st_size == 0:
            raise RuntimeError(f"Downloaded file is empty: {tmp}")

        self._info(f"File: {suggested} ({tmp.stat().st_size:,} bytes)")
        return tmp

    def _find_export_button(self, page: "Page", dl_cfg: dict):
        """내보내기 버튼 탐색 (primary → fallback)."""
        for key in ("button", "button_fallback"):
            sel = dl_cfg.get(key, "")
            if not sel:
                continue
            try:
                loc = page.locator(sel).first
                loc.wait_for(state="visible", timeout=8_000)
                return loc
            except Exception:
                continue
        return None
