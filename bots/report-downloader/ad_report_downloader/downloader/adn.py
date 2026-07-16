"""ADN 광고 일별/월별 실적 보고서 다운로더.

대행사(Agency) 포털: https://manage.acrosspf.com

다중 계정 흐름 (로그인 1회 / 계정 N개):
  1. check_login(): 로그인 세션 확인
  2. navigate_to_report():
     a. 계정 목록 페이지(루트)로 이동
     b. account_name과 일치하는 행의 "구버전" 버튼 클릭 → 계정 전환
     c. /report/report_dailys.php 이동
  3. set_period(): 날짜 직접 입력 (YYYYMMDD)
  4. trigger_download(): 다운로드 버튼 클릭
"""
from __future__ import annotations
import getpass
import re
import tempfile
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from playwright.sync_api import Page

from downloader.base import BaseDownloader, EmptyDataError, LoginRequiredError

_SELECTOR_FILE = Path(__file__).parent.parent / "selectors" / "adn.yaml"


def _load_selectors() -> dict:
    with _SELECTOR_FILE.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


class AdnDownloader(BaseDownloader):
    MEDIA_CODE = "adn"
    IMPLEMENTED = True

    def __init__(self, config: dict, account: dict | None = None):
        super().__init__(config, account)
        self._sel = _load_selectors()

    # ------------------------------------------------------------------ #
    # 1. Login check (+ auto-login via Chrome Password Manager)           #
    # ------------------------------------------------------------------ #
    def check_login(self, page: "Page") -> bool:
        """
        로그인 체크 전략:
        - manage.acrosspf.com/login 접속 → 리디렉션 여부로 판별
        - 세션 만료 시 자동 로그인 시도
        - 로그인 후에는 현재 페이지 상태로 검증 (재이동 없음)
        """
        if self._is_adn_logged_in(page):
            return True

        # 세션 만료 → 자동 로그인 시도
        self._info("ADN 세션 만료 — 자동 로그인 시도")
        if not self._do_login(page):
            self._warn("ADN 자동 로그인 실패")
            return False

        # 로그인 후 검증: 현재 페이지에서 바로 확인 (manage.acrosspf.com/login 재이동 금지)
        return self._verify_logged_in_page(page)

    def _is_adn_logged_in(self, page: "Page") -> bool:
        """member.acrosspf.com/agency.php 직접 접속 후 구버전 버튼 유무로 로그인 확인.
        manage.acrosspf.com/login 은 로그인 후에도 세션 유지 리디렉션이 불안정하여 사용 안 함."""
        self._info("ADN 로그인 체크: member.acrosspf.com/agency.php 접속 중...")
        try:
            page.goto("https://member.acrosspf.com/agency.php",
                      wait_until="domcontentloaded", timeout=30_000)
        except Exception as e:
            self._warn(f"ADN 접속 오류: {e}")
            return False
        self.human_delay(1_000, 1_500)

        current_url = page.url
        self._info(f"현재 URL: {current_url}")
        url_lower = current_url.lower()

        # 로그인 페이지로 리디렉션되면 세션 없음
        if "/login" in url_lower:
            return False

        return self._verify_logged_in_page(page)

    def _verify_logged_in_page(self, page: "Page") -> bool:
        """현재 페이지에서 구버전 버튼 존재 여부로 로그인 완료 확인."""
        ready_sel = self._sel["login"].get(
            "agency_ready_selector", "a[onclick*='_jsCmLogin']"
        )
        try:
            page.locator(ready_sel).first.wait_for(state="visible", timeout=10_000)
            self._info(f"ADN 대행사 세션 확인 완료 (URL: {page.url})")
            return True
        except Exception:
            self._screenshot(page, "adn_login_check")
            self._warn(f"ADN 계정 전환 버튼 없음 (URL: {page.url})")
            return False

    def _do_login(self, page: "Page") -> bool:
        """
        Chrome Password Manager autofill 방식 자동 로그인.
        - login_id: config.json → media.adn.login_id (비밀번호는 Chrome이 자동완성)
        - 비밀번호는 코드/설정 파일에 저장하지 않음 (보안 정책)
        """
        login_id = self.config.get("media", {}).get("adn", {}).get("login_id", "")
        if not login_id:
            self._warn("ADN login_id 미설정 — config.json의 media.adn.login_id를 입력하세요")
            return False

        login_sel = self._sel["login"]

        try:
            page.goto("https://manage.acrosspf.com/login",
                      wait_until="domcontentloaded", timeout=30_000)
            self.human_delay(1_000, 1_500)

            # 대행사 탭 클릭
            agency_tab_sel = login_sel.get(
                "agency_tab_selector",
                "[role='tab']:has-text('대행사'), li:has-text('대행사') a, a:has-text('대행사')"
            )
            try:
                tab = page.get_by_role("tab", name="대행사")
                tab.wait_for(state="visible", timeout=5_000)
                tab.click()
                self.human_delay(500, 800)
                self._info("대행사 탭 클릭 완료")
            except Exception:
                try:
                    tab = page.locator(agency_tab_sel).first
                    tab.wait_for(state="visible", timeout=3_000)
                    tab.click()
                    self.human_delay(500, 800)
                    self._info("대행사 탭 클릭 완료 (fallback)")
                except Exception:
                    self._warn("대행사 탭 클릭 실패 — 기본 탭으로 진행")

            # 아이디 입력 (Chrome Password Manager가 비밀번호 자동완성 준비)
            id_sel = login_sel.get("login_id_input", "input#manage_login_id, input[name='login_id']")
            id_input = page.locator(id_sel).first
            id_input.wait_for(state="visible", timeout=8_000)
            id_input.click()
            self.human_delay(200, 400)
            id_input.fill(login_id)
            self._info(f"아이디 입력: {login_id}")
            self.human_delay(300, 600)

            # Tab → 비밀번호 필드로 이동 → Chrome Password Manager 자동완성 트리거
            id_input.press("Tab")
            self.human_delay(1_500, 2_500)  # 자동완성 대기

            # 비밀번호 자동완성 확인
            pw_sel = login_sel.get("login_pw_input", "input[type='password']")
            pw_input = page.locator(pw_sel).first
            pw_val = ""
            try:
                pw_val = pw_input.input_value()
            except Exception:
                pass

            if not pw_val:
                self._info("비밀번호 자동완성 대기 중 (2초 추가)...")
                self.human_delay(2_000, 3_000)
                try:
                    pw_val = pw_input.input_value()
                except Exception:
                    pass

            if not pw_val:
                # 1순위: GUI 실행 시 메모리에 저장한 비밀번호
                pw_val = self.config.get("_adn_password_runtime", "")

            if not pw_val:
                # 2순위: Windows 자격 증명 관리자
                try:
                    import keyring
                    pw_val = keyring.get_password("ad_report_downloader_adn", login_id) or ""
                    if pw_val:
                        self._info("Windows 자격 증명 관리자에서 비밀번호 로드")
                except Exception:
                    pass

            if not pw_val:
                # 3순위: 터미널 입력 (비상용)
                self._info("비밀번호 없음 — 터미널에서 입력하세요")
                try:
                    pw_val = getpass.getpass(prompt=f"\nADN [{login_id}] 비밀번호: ")
                except Exception:
                    pw_val = ""

            if not pw_val:
                self._warn("비밀번호 없음 — 로그인 취소")
                return False

            # 비밀번호 필드 입력: 기존 내용(Chrome 자동완성 포함) 전체 지우고 새로 입력
            try:
                pw_input.click()
                # Ctrl+A → Delete 로 기존 내용 완전 삭제
                pw_input.press("Control+a")
                pw_input.press("Delete")
                self.human_delay(100, 200)
                pw_input.type(pw_val, delay=40)
                self.human_delay(200, 400)
            except Exception as e:
                self._warn(f"비밀번호 입력 실패: {e}")
                self._screenshot(page, "adn_pw_input_failed")
                return False

            self._screenshot(page, "adn_before_submit")
            self._info("비밀번호 입력 완료 — 로그인 버튼 클릭")

            # 로그인 버튼 클릭
            submit_sel = login_sel.get("submit_button", "button[type='submit']")
            submitted = False
            try:
                submit_btn = page.locator(submit_sel).first
                submit_btn.wait_for(state="visible", timeout=3_000)
                submit_btn.click()
                submitted = True
                self._info("로그인 버튼 클릭 완료")
            except Exception:
                pass

            if not submitted:
                pw_input.press("Enter")
                self._info("Enter 키로 로그인 제출")

            # 리디렉션 대기
            try:
                page.wait_for_url(
                    lambda u: "manage.acrosspf.com/login" not in u.lower(),
                    timeout=15_000,
                )
            except Exception:
                pass
            self.human_delay(1_000, 1_500)
            self._screenshot(page, "adn_after_login")
            self._info(f"로그인 후 URL: {page.url}")
            return True

        except Exception as e:
            self._warn(f"자동 로그인 중 오류: {e}")
            self._screenshot(page, "adn_auto_login_error")
            return False

    # ------------------------------------------------------------------ #
    # 2. Navigate to the report page (with account switching)             #
    # ------------------------------------------------------------------ #
    def navigate_to_report(self, page: "Page") -> None:
        """
        portal_type == "agency":
          → 계정 목록에서 account_name 행의 "구버전" 버튼 클릭 → 계정 전환 → 보고서 이동
        portal_type == "advertiser" (기본):
          → 계정 전환 없이 바로 보고서 페이지로 이동
        """
        portal_type = self._sel.get("portal_type", "advertiser")

        if portal_type == "agency" and self.account_name:
            self._switch_account(page)
        else:
            if portal_type == "agency":
                self._warn("account_name 미설정 — 현재 계정으로 보고서 이동")
            else:
                self._info("광고주 모드 — 계정 전환 없이 보고서 페이지로 이동")

        self._goto_report_page(page)

    def _switch_account(self, page: "Page") -> None:
        """계정 목록에서 account_name에 해당하는 행의 구버전 클릭."""
        base = self._sel["base_url"]
        acct_list_path = self._sel["login"].get("account_list_path", "/")

        self._info(f"계정 목록 이동 → '{self.account_name}' 전환 시도")
        if acct_list_path not in page.url:
            page.goto(base + acct_list_path, wait_until="domcontentloaded", timeout=30_000)
        self.human_delay(800, 1500)

        sel = self._sel["account_list"]

        # 계정 행의 구버전 로그인 URL을 현재 탭에서 직접 연다.
        # 원래 버튼은 window.open()을 사용하므로 그냥 클릭하면 팝업이 누적되고,
        # 이후 로직은 여전히 대행사 목록 탭을 사용하게 된다.
        if self._switch_account_in_current_page(page, sel):
            return

        # 방법 2: 모든 구버전 버튼 순서대로 (account_name 없이 첫 번째 계정)
        self._warn(f"계정명 '{self.account_name}' 매칭 실패 — 계정 목록 스크린샷 저장")
        self._screenshot(page, "adn_account_list")
        raise RuntimeError(
            f"ADN 계정 '{self.account_name}' 을 목록에서 찾을 수 없습니다.\n"
            "config.json → media.adn.accounts[].account_name 을 "
            "계정 목록에 표시된 이름과 정확히 일치하게 입력하세요."
        )

    def _switch_account_in_current_page(self, page: "Page", sel: dict) -> bool:
        """
        계정명이 포함된 행에서 구버전 로그인 파라미터를 읽어 현재 탭에서 이동.
        Returns True if successful.
        """
        name = self.account_name
        row_sel = sel.get("table_row", "tbody tr")
        btn_sel = sel.get("switch_button", "a[onclick*='_jsCmLogin']")
        name_cell_sel = sel.get("account_name_cell", "td:nth-child(3)")

        try:
            row = page.locator(row_sel).filter(has_text=name).first
            row.wait_for(state="visible", timeout=15_000)

            actual_name = row.locator(name_cell_sel).first.inner_text(timeout=3_000).strip()
            if actual_name != name:
                self._warn(f"계정명 부분 일치만 발견: 요청='{name}', 화면='{actual_name}'")
                return False

            btn = row.locator(btn_sel).first
            btn.wait_for(state="visible", timeout=5_000)
            onclick = btn.get_attribute("onclick") or ""
            match = re.search(
                r"_jsCmLogin\(\s*'([^']+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'\s*\)",
                onclick,
            )
            if not match:
                self._warn("구버전 전환 버튼의 로그인 파라미터를 읽을 수 없음")
                return False

            log_id, log_pw, log_gbn = match.groups()
            switch_base = sel.get(
                "legacy_switch_url",
                "https://member.acrosspf.com/common/login_agency_manage.php",
            )
            switch_url = (
                f"{switch_base}?log_id={log_id}&log_pw={log_pw}&log_gbn={log_gbn}"
            )

            self._info(f"계정 행 발견: '{name}' — 현재 탭에서 전환")
            page.goto(switch_url, wait_until="domcontentloaded", timeout=30_000)
            self.human_delay(1_000, 2_000)

            if page.is_closed():
                raise RuntimeError("ADN 계정 전환 중 페이지가 닫혔습니다.")
            if self._is_login_page(page):
                raise LoginRequiredError()

            self._info(f"계정 전환 완료: {page.url}")
            return True
        except LoginRequiredError:
            raise
        except Exception as e:
            self._warn(f"계정 전환 오류: {e}")

        return False

    def _is_login_page(self, page: "Page") -> bool:
        """현재 페이지가 ADN 로그인 화면인지 확인."""
        try:
            return page.locator(
                self._sel["login"]["login_element_selector"]
            ).first.is_visible(timeout=2_000)
        except Exception:
            return False

    def _goto_report_page(self, page: "Page") -> None:
        """보고서 > 일별/월별 실적 보고서 페이지로 이동."""
        base = self._sel["base_url"]
        report_path = self._sel["report"]["report_url_path"]

        # 방법 1: 직접 URL 이동 (가장 안정적)
        try:
            page.goto(base + report_path, wait_until="networkidle", timeout=30_000)
            self.human_delay(500, 1000)
            # URL만 보지 말고 실제 보고서 날짜 필드가 렌더링됐는지 확인한다.
            ready_sel = self._sel["report"].get(
                "ready_selector", "input[name='sdate'], #datepicker1"
            )
            if page.locator(ready_sel).first.is_visible(timeout=8_000):
                self._info("보고서 페이지 이동 완료")
                return
        except Exception:
            pass

        if self._is_login_page(page):
            raise LoginRequiredError()

        # 방법 2: 사이드바 클릭
        try:
            sidebar = page.locator(self._sel["report"]["sidebar_report"]).first
            if sidebar.is_visible(timeout=3_000):
                sidebar.click()
                self.human_delay(500, 900)
        except Exception:
            pass

        try:
            submenu = page.locator(self._sel["report"]["submenu_daily"]).first
            submenu.wait_for(state="visible", timeout=8_000)
            submenu.click()
            self.human_delay(800, 1500)
            page.wait_for_load_state("networkidle", timeout=20_000)
            self._info("보고서 페이지 이동 완료 (사이드바)")
            return
        except Exception as e:
            self._screenshot(page, "adn_nav_failed")
            raise RuntimeError(f"ADN 보고서 페이지 이동 실패: {e}") from e

    # ------------------------------------------------------------------ #
    # 3. Set date period                                                   #
    # ------------------------------------------------------------------ #
    def set_period(self, page: "Page", start: date, end: date) -> None:
        """
        날짜 직접 입력 (YYYYMMDD, jQuery UI datepicker).
        JS change 이벤트로 피커에 변경 알림 후 조회 버튼 클릭.
        """
        sel = self._sel["period"]
        start_str = start.strftime("%Y%m%d")
        end_str   = end.strftime("%Y%m%d")

        self._info(f"날짜 설정: {start_str} ~ {end_str}")
        ok_start = self._fill_date_input(page, sel["start_input"], start_str)
        ok_end = self._fill_date_input(page, sel["end_input"], end_str)
        if not (ok_start and ok_end):
            raise RuntimeError("ADN 날짜 입력 실패 — 다운로드를 중단합니다.")
        self.human_delay(300, 600)

        # 직접선택 상태로 만든 뒤 검색 폼을 제출한다.
        try:
            page.evaluate("""() => {
                const s = document.querySelector('input[name="sdate"]');
                const e = document.querySelector('input[name="edate"]');
                const period = document.querySelector('select[name="chk2sp"]');
                if (s) s.dispatchEvent(new Event('change', {bubbles: true}));
                if (e) e.dispatchEvent(new Event('change', {bubbles: true}));
                if (period) period.value = 'direct';
            }""")
            self.human_delay(300, 500)
            form_sel = sel.get("search_form", "form#searchfrm")
            form = page.locator(form_sel).first
            form.wait_for(state="attached", timeout=5_000)
            form.evaluate("form => form.submit()")
            page.wait_for_load_state("domcontentloaded", timeout=20_000)
            self.human_delay(500, 900)
        except Exception as e:
            raise RuntimeError(f"ADN 날짜 조회 실패: {e}") from e

        # 조회 후에도 요청 기간이 유지되는지 확인한다.
        actual_start = page.locator(sel["start_input"].split(",")[0]).first.input_value()
        actual_end = page.locator(sel["end_input"].split(",")[0]).first.input_value()
        if actual_start != start_str or actual_end != end_str:
            raise RuntimeError(
                f"ADN 날짜 검증 실패: 요청 {start_str}~{end_str}, "
                f"화면 {actual_start}~{actual_end}"
            )
        self._info("날짜 조회 및 검증 완료")

    def _fill_date_input(self, page: "Page", selector: str, value: str) -> bool:
        # jQuery UI datepicker 필드는 readonly일 수 있으므로 JS로 직접 값 설정
        for s in selector.split(","):
            s = s.strip()
            try:
                inp = page.locator(s).first
                if not inp.is_visible(timeout=3_000):
                    continue
                # JS로 값 직접 설정 (readonly 우회)
                page.evaluate(
                    f"(sel) => {{ var el = document.querySelector(sel); "
                    f"if (el) {{ el.removeAttribute('readonly'); el.value = '{value}'; }} }}",
                    s,
                )
                self.human_delay(100, 200)
                if inp.input_value() == value:
                    return True
                # fallback: triple_click + fill
                inp.triple_click()
                inp.fill(value)
                self.human_delay(150, 300)
                if inp.input_value() == value:
                    return True
            except Exception:
                continue
        self._warn(f"날짜 입력 실패: {value}")
        return False

    # ------------------------------------------------------------------ #
    # 3-b. 캠페인/그룹/소재 포함 체크박스 확인                             #
    # ------------------------------------------------------------------ #
    def _ensure_resource_checkbox(self, page: "Page") -> None:
        f_sel = self._sel.get("filters", {})
        cb_sel  = f_sel.get("resource_checkbox", "input[name='chk_resource']")
        lbl_sel = f_sel.get("resource_label",    "#div_resource label")

        for s in cb_sel.split(","):
            s = s.strip()
            try:
                cb = page.locator(s).first
                if not cb.is_visible(timeout=2_000):
                    continue
                if cb.is_checked():
                    self._info("캠페인/그룹/소재 포함: 이미 체크됨")
                    return
                try:
                    label = page.locator(lbl_sel).first
                    if label.is_visible(timeout=1_500):
                        label.click()
                    else:
                        cb.click(force=True)
                except Exception:
                    cb.click(force=True)
                self.human_delay(300, 500)
                if cb.is_checked():
                    self._info("캠페인/그룹/소재 포함: 체크 완료")
                else:
                    self._warn("캠페인/그룹/소재 포함: 체크 실패 가능성")
                return
            except Exception:
                continue
        self._warn("캠페인/그룹/소재 포함 체크박스 없음")

    # ------------------------------------------------------------------ #
    # 4. Trigger download                                                  #
    # ------------------------------------------------------------------ #
    def trigger_download(self, page: "Page", start: date, end: date) -> Path:
        """
        확인된 HTML:
          <a href="javascript:;" onclick="jsReportsDW_new()" class="btn btn-dark">다운로드</a>
        """
        self._ensure_resource_checkbox(page)
        self.human_delay(300, 600)

        dl_cfg = self._sel["download"]
        timeout_ms = self.timeout_sec * 1_000

        btn = self._find_download_button(page, dl_cfg)
        if btn is None:
            self._screenshot(page, "adn_download_btn_not_found")
            raise RuntimeError("다운로드 버튼 없음. selectors/adn.yaml 확인")

        self.human_delay(300, 600)

        with page.expect_download(timeout=timeout_ms) as dl_info:
            btn.click()

        download = dl_info.value
        suggested = download.suggested_filename or "adn_report.xlsx"
        suffix = Path(suggested).suffix or ".xlsx"
        tmp = Path(tempfile.mktemp(suffix=suffix))
        download.save_as(str(tmp))

        if not tmp.exists() or tmp.stat().st_size == 0:
            raise RuntimeError(f"다운로드 파일 비어있음: {tmp}")

        self._info(f"파일: {suggested} ({tmp.stat().st_size:,} bytes)")
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
