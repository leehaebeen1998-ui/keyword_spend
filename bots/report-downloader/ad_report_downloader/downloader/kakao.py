"""카카오 키워드광고 관리자센터 맞춤보고서 다운로더.
https://keywordad.kakao.com

계정 전환 흐름 (1회 로그인 / 다중 계정):
  1. check_login(): keywordad.kakao.com 접속 후 세션 확인
  2. navigate_to_report():
     a. account_id 있으면 /{account_id}/report 직접 이동
     b. 사이드바 "보고서" 클릭
     c. 맞춤보고서 목록에서 report_name 클릭
  3. set_period(): 날짜 범위 선택 (달력 UI)
  4. trigger_download(): 다운로드 버튼 클릭

config.json 필수 필드:
  account_id  : 숫자 광고계정 ID (예: "320272")  ← Screenshot 5 테이블 "광고계정 ID"
  report_name : 저장된 보고서 이름 (예: "A_마약_주요키워드_PC_주간 보고서")
"""
from __future__ import annotations
import re
import tempfile
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import yaml

if TYPE_CHECKING:
    from playwright.sync_api import Page

from downloader.base import BaseDownloader, EmptyDataError

_SELECTOR_FILE = Path(__file__).parent.parent / "selectors" / "kakao.yaml"


def _load_selectors() -> dict:
    with _SELECTOR_FILE.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


class KakaoDownloader(BaseDownloader):
    MEDIA_CODE = "kakao"
    IMPLEMENTED = True

    def __init__(self, config: dict, account: dict | None = None):
        super().__init__(config, account)
        self._sel = _load_selectors()

    # ------------------------------------------------------------------ #
    # 1. Login check                                                       #
    # ------------------------------------------------------------------ #
    _KEYRING_SERVICE = "ad_report_downloader_kakao"

    def check_login(self, page: "Page") -> bool:
        """keywordad.kakao.com 접속 후 로그인 여부 확인.
        세션 만료 시 keyring에 저장된 비밀번호로 자동 로그인합니다.
        """
        base = self._sel["base_url"]
        page.goto(base, wait_until="domcontentloaded", timeout=30_000)
        self.human_delay(800, 1500)

        if self._is_logged_in(page):
            return True

        self._info("카카오 세션 만료 — 자동 로그인 시도")
        self._do_login(page)

        if self._is_logged_in(page):
            self._info("카카오 자동 로그인 완료")
            return True

        self._warn("카카오 자동 로그인 실패")
        return False

    def _is_logged_in(self, page: "Page") -> bool:
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

    def _do_login(self, page: "Page") -> None:
        """keyring에 저장된 자격증명으로 카카오 자동 로그인."""
        login_id = self.config.get("media", {}).get("kakao", {}).get("login_id", "")
        if not login_id:
            self._warn("config.json kakao.login_id 미설정 — 자동 로그인 불가")
            return

        # 비밀번호 조회 (keyring → runtime config)
        pw = ""
        try:
            import keyring
            pw = keyring.get_password(self._KEYRING_SERVICE, login_id) or ""
        except Exception:
            pass
        if not pw:
            pw = self.config.get("_kakao_password_runtime", "")
        if not pw:
            self._warn("카카오 비밀번호 미저장 — 로그인.bat 실행 후 비밀번호를 저장해주세요")
            return

        sel = self._sel["login"]

        # 로그인 페이지로 이동 (이미 있을 수 있지만 명시적으로)
        if "accounts.kakao.com" not in page.url.lower():
            page.goto("https://accounts.kakao.com/login", wait_until="domcontentloaded", timeout=20_000)
            self.human_delay(600, 1000)

        # ID 입력
        try:
            id_input = page.locator(sel["id_input"]).first
            id_input.wait_for(state="visible", timeout=8_000)
            id_input.click()
            id_input.press("Control+a")
            id_input.press("Delete")
            id_input.type(login_id, delay=40)
            self.human_delay(300, 500)
        except Exception as e:
            self._warn(f"카카오 ID 입력 실패: {e}")
            self._screenshot(page, "kakao_login_id_fail")
            return

        # PW 입력
        try:
            pw_input = page.locator(sel["pw_input"]).first
            pw_input.wait_for(state="visible", timeout=5_000)
            pw_input.click()
            pw_input.press("Control+a")
            pw_input.press("Delete")
            pw_input.type(pw, delay=40)
            self.human_delay(300, 500)
        except Exception as e:
            self._warn(f"카카오 비밀번호 입력 실패: {e}")
            self._screenshot(page, "kakao_login_pw_fail")
            return

        # 로그인 버튼 클릭
        try:
            submit = page.locator(sel["submit_button"]).first
            submit.wait_for(state="visible", timeout=5_000)
            submit.click()
        except Exception as e:
            self._warn(f"카카오 로그인 버튼 클릭 실패: {e}")
            self._screenshot(page, "kakao_login_submit_fail")
            return

        # 로그인 완료 대기 (keywordad.kakao.com으로 리디렉션)
        try:
            page.wait_for_url(
                lambda url: (
                    "keywordad.kakao.com" in url.lower()
                    and "accounts.kakao.com" not in url.lower()
                ),
                timeout=30_000,
            )
        except Exception:
            self._screenshot(page, "kakao_login_redirect_fail")

    # ------------------------------------------------------------------ #
    # 2. Navigate to the saved report                                      #
    # ------------------------------------------------------------------ #
    def navigate_to_report(self, page: "Page") -> None:
        self._info(f"Looking for report: '{self.report_name}'")

        # 1. 계정 전환 (account_id 직접 URL 이동)
        if self.account_id:
            self._switch_account(page)
        else:
            self._warn("account_id 미설정 — 현재 계정 상태로 보고서 이동")

        # 2. 사이드바 "보고서" 클릭 (이미 /report에 있으면 skip)
        if "/report" not in page.url.lower():
            self._click_sidebar_report(page)

        # 3. 저장된 보고서 클릭
        self._click_report_by_name(page)

    def _is_current_account(self, page: "Page") -> bool:
        """URL 경로의 첫 번째 세그먼트가 account_id인지 확인."""
        try:
            path = urlparse(page.url).path  # e.g. "/320272/report"
            seg = path.strip("/").split("/")[0]
            return seg == str(self.account_id)
        except Exception:
            return False

    def _switch_account(self, page: "Page") -> None:
        """/{account_id}/report 직접 이동으로 계정 전환."""
        if self._is_current_account(page) and "/report" in page.url.lower():
            self._info(f"이미 계정 {self.account_id} 보고서 페이지")
            return

        acc_cfg = self._sel["account_switch"]
        url_tpl = acc_cfg["report_url_with_account"]
        url = self._sel["base_url"] + url_tpl.format(account_id=self.account_id)

        self._info(f"계정 전환: {url}")
        try:
            page.goto(url, wait_until="networkidle", timeout=35_000)
            self.human_delay(800, 1500)
        except Exception as e:
            self._screenshot(page, "kakao_account_switch_failed")
            raise RuntimeError(f"카카오 계정 전환 실패: {e}") from e

        if not self._is_current_account(page):
            self._warn(f"계정 전환 후 URL이 예상과 다름 — 계속 진행 ({page.url})")

    def _click_sidebar_report(self, page: "Page") -> None:
        """사이드바에서 '보고서' 메뉴 클릭."""
        sidebar_sel = self._sel["report"]["sidebar_report"]
        try:
            sidebar = page.locator(sidebar_sel).first
            if sidebar.is_visible(timeout=4_000):
                sidebar.click()
                self.human_delay(800, 1500)
                page.wait_for_load_state("networkidle", timeout=20_000)
                self._info("사이드바 '보고서' 클릭 완료")
                return
        except Exception:
            pass

        # Fallback: account_id 없으면 기본 /report URL
        base = self._sel["base_url"]
        path = self._sel["report"]["report_url_path"]
        try:
            page.goto(base + path, wait_until="networkidle", timeout=30_000)
            self.human_delay(500, 1000)
        except Exception:
            pass

    def _click_report_by_name(self, page: "Page") -> None:
        """맞춤보고서 목록에서 report_name 클릭."""
        name = self.report_name
        link_sel = self._sel["report"]["report_list_link"]

        # Primary: exact text match
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

        # Fallback: scan table links
        try:
            for link in page.locator(link_sel).all():
                try:
                    if name in link.inner_text(timeout=800):
                        link.click()
                        self.human_delay(1000, 2000)
                        page.wait_for_load_state("networkidle", timeout=25_000)
                        self._info(f"Report '{name}' opened (fallback)")
                        return
                except Exception:
                    continue
        except Exception:
            pass

        self._screenshot(page, "kakao_report_list")
        raise RuntimeError(
            f"Report '{name}' not found in 카카오 키워드광고 맞춤보고서 목록. "
            "Check config.json report_name."
        )

    # ------------------------------------------------------------------ #
    # 3. Set date period                                                   #
    # ------------------------------------------------------------------ #
    def set_period(self, page: "Page", start: date, end: date) -> None:
        """
        Kakao 달력 UI 흐름:
          1. 달력 버튼 클릭 → 프리셋 드롭다운 열림
          2. "맞춤 설정" 선택 → 날짜 입력창 표시
          3. 시작/종료 날짜 입력 (YYYY.MM.DD)
          4. 적용 버튼 클릭 (button.btn_gm.gm_bl)
        """
        sel = self._sel["period"]

        # 1. 달력 버튼 클릭
        cal_btn = page.locator(sel["date_range_button"]).first
        cal_btn.wait_for(state="visible", timeout=10_000)
        cal_btn.click()
        self.human_delay(500, 900)

        # 2. "맞춤 설정" 드롭다운 항목 클릭
        custom_sel = sel.get("custom_range_option", "")
        if custom_sel:
            try:
                custom_item = page.locator(custom_sel).first
                custom_item.wait_for(state="visible", timeout=5_000)
                custom_item.click()
                self._info("'맞춤 설정' 선택 — 날짜 입력창 오픈")
                self.human_delay(400, 700)
            except Exception as e:
                self._warn(f"'맞춤 설정' 항목 클릭 실패: {e}")
                self._screenshot(page, "kakao_custom_range_not_found")

        if not self._wait_for_calendar_popup(page):
            self._warn("Calendar popup not visible — proceeding anyway")
            self._screenshot(page, "kakao_calendar_not_found")

        # 3. 날짜 입력
        start_ok = self._try_fill_input(page, sel["start_input"], start)
        end_ok   = self._try_fill_input(page, sel["end_input"], end)

        if not start_ok:
            self._info(f"Calendar click: start {start}")
            self._click_calendar_day(page, start, sel)
        if not end_ok:
            self._info(f"Calendar click: end {end}")
            self._click_calendar_day(page, end, sel)

        self.human_delay(300, 500)

        # 4. 적용 버튼 클릭
        try:
            apply_btn = page.locator(sel["apply_button"]).first
            apply_btn.wait_for(state="visible", timeout=5_000)
            apply_btn.click()
            self.human_delay(1000, 2000)
            self._info("Date range applied")
        except Exception as e:
            self._warn(f"Apply button not found: {e}")
            self._screenshot(page, "kakao_apply_btn_not_found")

        page.wait_for_load_state("networkidle", timeout=25_000)

    def _wait_for_calendar_popup(self, page: "Page") -> bool:
        for sel in [
            ".calendar_wrap, [class*='calendar_layer'], [class*='layer_calendar']",
            "table.calendar_body, table[class*='calendar']",
            "input[id*='start'], input[id*='end']",
        ]:
            try:
                page.locator(sel).first.wait_for(state="visible", timeout=2_500)
                return True
            except Exception:
                continue
        return False

    def _try_fill_input(self, page: "Page", selector: str, dt: date) -> bool:
        """날짜 입력 필드에 YYYY.MM.DD 형식으로 입력. 성공 시 True."""
        value = dt.strftime("%Y.%m.%d")
        for s in selector.split(","):
            s = s.strip()
            try:
                inp = page.locator(s).first
                if not inp.is_visible(timeout=2_000):
                    continue
                inp.triple_click()
                inp.fill(value)
                inp.press("Tab")
                self.human_delay(200, 400)
                return True
            except Exception:
                continue
        return False

    def _click_calendar_day(self, page: "Page", target: date, sel: dict) -> None:
        """JS로 캘린더 정확한 패널의 날짜 클릭 (2패널 달력 지원).

        카카오 달력은 좌(전월)+우(당월) 2패널 구조.
        같은 날짜 숫자가 양 패널에 존재하므로 JS로 헤더 텍스트를 읽어
        맞는 패널(테이블)만 클릭한다.
        """
        prev_sel = sel.get("prev_month_btn", "button.btn_prev")
        next_sel = sel.get("next_month_btn", "button.btn_next")
        t_year, t_month, t_day = target.year, target.month, target.day

        # JS로 셀 좌표 반환 → Playwright 마우스 클릭 (range 선택 이벤트 정상 발생)
        bbox = page.evaluate(f"""
        (() => {{
            const tYear = {t_year}, tMonth = {t_month}, tDay = {t_day};

            const tables = Array.from(document.querySelectorAll(
                '.datecalendar_wrap table, .date_calendar table, .calendar_layer table'
            )).filter(t => t.querySelector('td'));

            function getTableYM(tbl) {{
                let el = tbl.parentElement;
                for (let i = 0; i < 5; i++) {{
                    if (!el) break;
                    const nodes = el.querySelectorAll(
                        '[class*="tit"], strong, caption, [class*="head"] *'
                    );
                    for (const n of nodes) {{
                        const txt = Array.from(n.childNodes)
                            .filter(c => c.nodeType === 3)
                            .map(c => c.textContent).join('').trim()
                            || n.textContent.trim();
                        const m = txt.match(/(\\d{{4}})[^\\d]+(\\d{{1,2}})/);
                        if (m) return [parseInt(m[1]), parseInt(m[2])];
                    }}
                    el = el.parentElement;
                }}
                return null;
            }}

            function findCell(tbl) {{
                for (const td of tbl.querySelectorAll('td')) {{
                    if (td.textContent.trim() === String(tDay)
                        && !td.classList.contains('disabled')
                        && !td.classList.contains('in_active')
                        && !td.getAttribute('disabled')) {{
                        const r = td.getBoundingClientRect();
                        return {{x: r.x + r.width / 2, y: r.y + r.height / 2, label: 'panel'}};
                    }}
                }}
                return null;
            }}

            // 1차: 월이 일치하는 패널
            for (const tbl of tables) {{
                const ym = getTableYM(tbl);
                if (ym && ym[0] === tYear && ym[1] === tMonth) {{
                    const cell = findCell(tbl);
                    if (cell) return cell;
                }}
            }}

            // 2차: 마지막(오른쪽) 패널 fallback
            for (let i = tables.length - 1; i >= 0; i--) {{
                const cell = findCell(tables[i]);
                if (cell) {{ cell.label = 'fallback-' + i; return cell; }}
            }}

            return null;
        }})()
        """)

        if bbox:
            page.mouse.click(bbox["x"], bbox["y"])
            self.human_delay(200, 400)
            self._info(f"날짜 클릭 ({bbox.get('label','?')} {t_year}-{t_month:02d}-{t_day:02d}): {target}")
        else:
            self._warn(f"날짜 셀 클릭 실패: {target}")
            self._screenshot(page, f"kakao_day_click_fail_{target}")

    # ------------------------------------------------------------------ #
    # 4. Trigger download                                                  #
    # ------------------------------------------------------------------ #
    def trigger_download(self, page: "Page", start: date, end: date) -> Path:
        """
        확인된 HTML (Screenshot 8 DevTools):
          <button type="button" class="btn_gm gm_line">
            <span class="inner_g icon_g">
              <span class="ico_comm ico_download">다운로드</span>
            </span>
          </button>
        """
        dl_cfg = self._sel["download"]
        timeout_ms = int(dl_cfg.get("timeout_sec", 90)) * 1_000

        btn = self._find_download_button(page, dl_cfg)
        if btn is None:
            self._screenshot(page, "kakao_download_btn_not_found")
            raise RuntimeError(
                "Download button not found. Check selectors/kakao.yaml download.button."
            )

        if btn.is_disabled():
            raise EmptyDataError("Download button disabled — no data for period")

        self.human_delay(300, 600)

        # force=True: <div class="single_wrap"> 등 interceptor 즉시 우회
        # ※ 일반 click(timeout=5s) 방식은 타임아웃 동안 부분 다운로드(3 bytes)가
        #    먼저 캡처되어 깨진 파일이 저장되는 버그가 있음
        try:
            with page.expect_download(timeout=timeout_ms) as dl_info:
                btn.click(force=True)
        except Exception:
            self._warn("force 클릭 실패 — dispatch_event 시도")
            with page.expect_download(timeout=timeout_ms) as dl_info:
                btn.dispatch_event("click")

        download = dl_info.value
        suggested = download.suggested_filename or "kakao_report.xlsx"
        suffix = Path(suggested).suffix or ".xlsx"
        tmp = Path(tempfile.mktemp(suffix=suffix))
        download.save_as(str(tmp))

        if not tmp.exists() or tmp.stat().st_size == 0:
            raise RuntimeError(f"Downloaded file is empty: {tmp}")

        self._info(f"File: {suggested} ({tmp.stat().st_size:,} bytes)")
        return tmp

    def _find_download_button(self, page: "Page", dl_cfg: dict):
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
