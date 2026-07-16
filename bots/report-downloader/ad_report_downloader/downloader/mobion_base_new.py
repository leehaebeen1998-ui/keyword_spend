"""모비온 공통 베이스 클래스 — 신규 UI (adcenter.mobon.net)

서브클래스:
  MobionBannerDownloader  → 통합 배너 보고서 (저장된 보고서 클릭)
  MobionDailyDownloader   → 일자별 보고서 (?reporttype=01 또는 저장된 보고서)

계정 전환 보안 정책:
  - 코드·설정 파일에 비밀번호 절대 미저장 (ID/PW 저장 금지)
  - Chrome Password Manager 자동완성(autofill)만 사용
  - Chrome에 adcenter.mobon.net 비밀번호가 저장되어 있어야 함

신규 UI 계정 전환 흐름 (iframe 없음):
  1. 헤더 프로필 버튼 클릭 → div#userProfileModal 열기
  2. input#memSearchKeyword 에 account_id 입력 → 검색
  3. li[data-user-id='{account_id}'] button.modalOpenBtn 클릭
  4. div#userPasswordModal 에서 Chrome 자동완성 비밀번호
  5. button#detailButton (확인) 클릭
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


class MobionBase(BaseDownloader):
    """
    모비온 신규 UI 공통 기능:
      - 로그인 확인 (adcenter.mobon.net)
      - 계정 전환 (헤더 프로필 → 검색 → 선택 → 비밀번호)
      - daterangepicker 날짜 선택 (auto-apply 모드)
      - 다운로드 버튼 클릭
    """

    _SELECTOR_FILE: Path

    def __init__(self, config: dict, account: dict | None = None):
        super().__init__(config, account)
        self._sel = self._load_selectors()

    def _load_selectors(self) -> dict:
        with self._SELECTOR_FILE.open(encoding="utf-8") as f:
            return yaml.safe_load(f)

    # ================================================================== #
    # 1. Login check                                                       #
    # ================================================================== #
    def check_login(self, page: "Page") -> bool:
        """adcenter.mobon.net 로그인 여부 확인."""
        base = self._sel["base_url"]
        check_url = self._sel["login"].get("check_url", "/campaigns")

        page.goto(base + check_url, wait_until="domcontentloaded", timeout=30_000)
        self.human_delay(800, 1500)

        url = page.url.lower()
        for pattern in self._sel["login"]["login_url_patterns"]:
            if pattern.lower() in url:
                self._warn(f"로그인 페이지 감지: {page.url}")
                return False

        try:
            if page.locator(self._sel["login"]["login_element_selector"]).first.is_visible(timeout=2_000):
                self._warn("로그인 폼 감지 — 미로그인 상태")
                return False
        except Exception:
            pass

        self._info(f"로그인 확인 완료: {page.url}")
        return True

    # ================================================================== #
    # 2. Account switching                                                 #
    # ================================================================== #
    def _is_current_account(self, page: "Page") -> bool:
        """현재 페이지에 account_id 가 이미 표시 중인지 확인."""
        if not self.account_id:
            return False
        # 헤더에 account_id 텍스트 포함 여부
        for css in ("header", "header .rightBox", "header .userInfo", "#userInfo"):
            try:
                txt = page.locator(css).first.inner_text(timeout=1_500)
                if self.account_id.lower() in txt.lower():
                    return True
            except Exception:
                continue
        # meta[name="adverId"] 로도 확인 (신규 UI 에서 확인된 패턴)
        try:
            adver_id = page.locator("meta[name='adverId']").get_attribute("content", timeout=1_000)
            if adver_id and adver_id.lower() == self.account_id.lower():
                return True
        except Exception:
            pass
        return False

    def _open_profile_modal(self, page: "Page", sel: dict) -> bool:
        """
        헤더 프로필 버튼을 클릭해 userProfileModal 을 엽니다.
        모달이 이미 열려 있으면 건너뜁니다.
        """
        modal_css = sel["modal"]
        # 이미 열려 있으면 스킵
        try:
            modal = page.locator(modal_css).first
            if modal.is_visible(timeout=1_000):
                return True
        except Exception:
            pass

        # 트리거 버튼 목록 순서대로 시도
        triggers = [
            sel.get("profile_trigger", ""),
            "header .rightBox button",
            "header button[class*='profile']",
            "header .up_profile",
            "header [data-moname='userProfileModal']",
            # 계정명 텍스트가 있는 헤더 요소
            f"header span:has-text('{self.account_id}')",
        ]

        for trigger_css in triggers:
            if not trigger_css:
                continue
            try:
                for loc in page.locator(trigger_css).all():
                    try:
                        if loc.is_visible(timeout=500):
                            loc.click()
                            self.human_delay(500, 1000)
                            # 모달이 열렸는지 확인
                            if page.locator(modal_css).first.is_visible(timeout=2_000):
                                return True
                    except Exception:
                        continue
            except Exception:
                continue

        # JavaScript 로 모달 강제 오픈 시도
        try:
            page.evaluate("document.querySelector('#userProfileModal')?.classList.add('on')")
            self.human_delay(300, 500)
            if page.locator(modal_css).first.is_visible(timeout=2_000):
                self._warn("프로필 모달 JS 강제 오픈")
                return True
        except Exception:
            pass

        return False

    def _switch_account(self, page: "Page") -> None:
        """
        신규 UI 계정 전환:
          헤더 프로필 → 검색 → 계정 선택 → Chrome 자동완성 비밀번호 → 확인.

        보안 정책: 코드/설정에 비밀번호 미저장.
        Chrome Password Manager에 adcenter.mobon.net 비밀번호가 저장되어 있어야 함.
        """
        if self._is_current_account(page):
            self._info(f"이미 '{self.account_id}' 계정 — 전환 생략")
            return

        self._info(f"계정 전환 시작: {self.account_id or self.account_name}")
        sel = self._sel["account_switch"]

        # ① 프로필 모달 열기
        if not self._open_profile_modal(page, sel):
            self._screenshot(page, f"mobion_modal_open_failed_{self.account_id}")
            raise RuntimeError(
                f"userProfileModal 을 열 수 없습니다. "
                "헤더 프로필 버튼 셀렉터를 확인하세요: "
                f"{sel.get('profile_trigger', '?')}"
            )

        # ② account_id 검색
        search_key = self.account_id or self.account_name
        search_inp = page.locator(sel["search_input"]).first
        search_inp.wait_for(state="visible", timeout=5_000)
        search_inp.click()
        search_inp.fill(search_key)
        self.human_delay(200, 400)

        # 검색 버튼 클릭 (또는 Enter)
        try:
            page.locator(sel["search_button"]).click()
        except Exception:
            search_inp.press("Enter")
        self.human_delay(700, 1200)

        # ③ 계정 선택
        if self.account_id:
            item_css = sel["account_item_by_id"].replace("{account_id}", self.account_id)
        else:
            item_css = f"ul#searchHtml li button:has-text('{self.account_name}')"

        account_btn = page.locator(item_css).first
        account_btn.wait_for(state="visible", timeout=8_000)
        account_btn.click()
        self.human_delay(500, 900)

        # ④ 비밀번호 모달 대기
        pw_modal_css = sel["password_modal"]
        pw_modal = page.locator(pw_modal_css).first
        pw_modal.wait_for(state="visible", timeout=8_000)

        # ⑤ 비밀번호 Chrome 자동완성
        self._autofill_password_new_ui(page, sel)

        # ⑥ 확인 클릭
        confirm = page.locator(sel["confirm_button"]).first
        confirm.wait_for(state="visible", timeout=3_000)
        confirm.click()
        self.human_delay(1_500, 2_500)
        page.wait_for_load_state("networkidle", timeout=20_000)

        self._info(f"계정 전환 완료 → {page.url}")

        # ⑦ 전환 확인
        if self.account_id and not self._is_current_account(page):
            self._screenshot(page, f"mobion_switch_failed_{self.account_id}")
            raise RuntimeError(
                f"계정 전환 후 확인 실패: '{self.account_id}'\n"
                "Chrome 비밀번호 관리자(chrome://settings/passwords)에\n"
                "adcenter.mobon.net 비밀번호가 저장되어 있는지 확인하세요."
            )

    def _autofill_password_new_ui(self, page: "Page", sel: dict) -> None:
        """
        신규 UI 비밀번호 모달에서 Chrome Password Manager 자동완성.
        모달은 메인 DOM에 있음 (iframe 아님).
        """
        pw_inp = page.locator(sel["password_input"]).first
        pw_inp.wait_for(state="visible", timeout=5_000)

        # 1단계: 클릭 → Chrome 자동완성 트리거
        pw_inp.click()
        self.human_delay(1_000, 1_500)

        try:
            if pw_inp.input_value(timeout=1_000):
                self._info("Chrome 자동완성 성공 (자동 입력)")
                return
        except Exception:
            pass

        # 2단계: 드롭다운 키보드 선택
        page.keyboard.press("ArrowDown")
        self.human_delay(300, 600)
        page.keyboard.press("Enter")
        self.human_delay(600, 1_000)

        try:
            if pw_inp.input_value(timeout=1_000):
                self._info("Chrome 자동완성 성공 (키보드 선택)")
                return
        except Exception:
            pass

        # 3단계: 실패
        self._screenshot(page, "mobion_autofill_failed")
        raise RuntimeError(
            "Mobion 비밀번호 자동완성 실패.\n"
            "Chrome 비밀번호 관리자(chrome://settings/passwords)에\n"
            "adcenter.mobon.net 계정의 비밀번호를 저장해 주세요.\n"
            "(구 manage.mobon.net 아닌 adcenter.mobon.net 으로 저장할 것)"
        )

    # ================================================================== #
    # 3. Navigate to report editor                                         #
    # ================================================================== #
    def _goto_report_editor(self, page: "Page") -> None:
        """보고서 에디터 페이지로 이동."""
        base = self._sel["base_url"]
        editor_url = self._sel["report"]["editor_url"]
        target = base + editor_url

        if page.url.rstrip("/") == target.rstrip("/"):
            return

        # 사이드바 메뉴 클릭 시도
        for key in ("sidebar_report", "sidebar_editor"):
            css = self._sel["report"].get(key, "")
            if not css:
                continue
            try:
                loc = page.locator(css).first
                if loc.is_visible(timeout=2_000):
                    loc.click()
                    self.human_delay(400, 700)
                    if "report/edit" in page.url:
                        return
            except Exception:
                continue

        # 직접 URL 이동
        page.goto(target, wait_until="networkidle", timeout=30_000)
        self.human_delay(500, 1000)
        self._info(f"보고서 에디터 이동: {page.url}")

    def _click_saved_report(self, page: "Page", report_name: str) -> None:
        """저장된 보고서 목록에서 report_name 으로 클릭."""
        link_tmpl = self._sel["report"]["saved_report_link"]
        link_css = link_tmpl.replace("{report_name}", report_name)

        try:
            link = page.locator(link_css).first
            link.wait_for(state="visible", timeout=8_000)
            link.click()
            self.human_delay(800, 1500)
            page.wait_for_load_state("networkidle", timeout=20_000)
            self._info(f"저장된 보고서 '{report_name}' 클릭 완료: {page.url}")
        except Exception as e:
            self._screenshot(page, f"mobion_report_not_found_{self.account_id}")
            raise RuntimeError(
                f"저장된 보고서 '{report_name}' 를 찾을 수 없습니다.\n"
                f"보고서 에디터(adcenter.mobon.net/campaigns/report/edit)에서\n"
                f"해당 계정({self.account_id})으로 보고서를 먼저 저장해 주세요."
            ) from e

    # navigate_to_report — 서브클래스 구현
    def navigate_to_report(self, page: "Page") -> None:
        raise NotImplementedError

    # ================================================================== #
    # 4. Set date period — daterangepicker (auto-apply)                   #
    # ================================================================== #
    def set_period(self, page: "Page", start: date, end: date) -> None:
        sel = self._sel["period"]

        # daterangepicker 열기
        if not self._open_daterangepicker(page, sel):
            self._screenshot(page, f"{self.MEDIA_CODE}_no_date_btn")
            raise RuntimeError(
                "daterangepicker 를 열 수 없습니다.\n"
                f"현재 URL: {page.url}\n"
                "날짜 버튼 스크린샷을 공유해 주세요."
            )
        self._info("daterangepicker opened")

        self._info(f"Selecting start date: {start}")
        self._navigate_to_month(page, start, sel)
        self._click_day(page, start, sel)
        self.human_delay(400, 700)

        self._info(f"Selecting end date: {end}")
        self._navigate_to_month(page, end, sel)
        self._click_day(page, end, sel)
        self.human_delay(400, 700)

        page.wait_for_load_state("networkidle", timeout=25_000)
        self._info(f"Date range set: {start} ~ {end}")

    def _find_date_button(self, page: "Page", sel: dict):
        """날짜 범위 버튼 찾기 (여러 셀렉터 시도)."""
        btn_css = sel