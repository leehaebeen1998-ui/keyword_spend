"""Mobion old UI common downloader logic."""
from __future__ import annotations

import re
import tempfile
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from downloader.base import BaseDownloader, EmptyDataError

if TYPE_CHECKING:
    from playwright.sync_api import Page


class MobionBase(BaseDownloader):
    _SELECTOR_FILE: Path

    def __init__(self, config: dict, account: dict | None = None):
        super().__init__(config, account)
        self._sel = self._load_selectors()

    def _load_selectors(self) -> dict:
        with self._SELECTOR_FILE.open(encoding="utf-8") as file:
            return yaml.safe_load(file)

    def check_login(self, page: "Page") -> bool:
        base = self._sel.get("login_base_url") or self._sel["base_url"]
        path = self._sel.get("report", {}).get("old_ui_path", "")
        page.goto(base + path, wait_until="domcontentloaded", timeout=30_000)
        self.human_delay(800, 1500)

        url = page.url.lower()
        for pattern in self._sel["login"]["login_url_patterns"]:
            if pattern.lower() in url:
                return False

        try:
            login_selector = self._sel["login"]["login_element_selector"]
            if page.locator(login_selector).first.is_visible(timeout=2_000):
                return False
        except Exception:
            pass
        return True

    def _ensure_old_ui(self, page: "Page") -> None:
        base = self._sel["base_url"]
        old_path = self._sel["report"].get("old_ui_path", "")
        if old_path and old_path not in page.url:
            page.goto(base + old_path, wait_until="domcontentloaded", timeout=30_000)
            self.human_delay(800, 1200)
        # AJAX 계정 목록 로드 대기 (showIndexList는 2초 후 실행)
        try:
            page.wait_for_load_state("networkidle", timeout=12_000)
        except Exception:
            pass
        self.human_delay(500, 800)

    def _find_shotcut(self, page: "Page"):
        """계정에 맞는 a.shotcut 링크를 찾아 반환. 없으면 None.
        AJAX 로드 후 호출되어야 함 (_ensure_old_ui에서 networkidle 대기).
        """
        search_keys = [k for k in (self.account_id, self.account_name) if k]

        # 1) account_id로 href 또는 onclick 매칭
        if self.account_id:
            for attr_sel in (
                f"a.shotcut[href*=\"changeUser('{self.account_id}')\"]",
                f"a.shotcut[onclick*=\"changeUser('{self.account_id}')\"]",
                f"a[href*=\"changeUser('{self.account_id}')\"]",
                f"a[onclick*=\"changeUser('{self.account_id}')\"]",
            ):
                loc = page.locator(attr_sel).first
                try:
                    if loc.is_visible(timeout=2_000):
                        return loc
                except Exception:
                    pass

        # 2) 모든 a.shotcut / changeUser 관련 링크 순회
        for link_sel in ("a.shotcut", "a[href*='changeUser'], a[onclick*='changeUser']"):
            try:
                all_links = page.locator(link_sel).all()
                for sc in all_links:
                    try:
                        row_text = sc.evaluate(
                            "el => (el.closest('tr') || el.parentElement || el).innerText"
                        )
                        for key in search_keys:
                            if key in row_text:
                                return sc
                    except Exception:
                        continue
            except Exception:
                continue

        return None

    def _switch_account(self, page: "Page") -> None:
        self._info(f"모비온 계정 전환: {self.account_id or self.account_name}")

        # giomglobal(마스터)로 항상 로그인된 상태.
        # 이전에 선택한 광고주($toastDiffSessionId)가 있으면 보고서가 바로 렌더링 →
        # 모달이 자동으로 뜨지 않음. span.modalOpen 클릭으로 모달을 직접 열어야 함.

        # Step 1: span.modalOpen 클릭으로 광고주 전환 모달 열기
        try:
            btn = page.locator("span.modalOpen[data-url*='user_change']").first
            btn.wait_for(state="visible", timeout=5_000)
            btn.click()
            self._info("  광고주 전환 버튼 클릭")
        except Exception:
            # 버튼 없음 → 모달이 자동으로 이미 떠 있는 경우 (마스터 계정 첫 방문)
            self._info("  modalOpen 버튼 없음 — 자동 모달 확인")

        # Step 2: page.frames 폴링으로 iframe Frame 객체 취득
        search_keys = [k for k in (self.account_id, self.account_name) if k]
        modal_frame = None
        for _ in range(50):  # 최대 10초 폴링
            modal_frame = next((f for f in page.frames if "user_change" in f.url), None)
            if modal_frame:
                break
            self.human_delay(200, 200)

        if modal_frame is None:
            self._screenshot(page, f"{self.MEDIA_CODE}_no_modal_frame_{self.account_id}")
            raise RuntimeError("광고주 전환 iframe을 찾을 수 없습니다.")

        # iframe 내부 DOM 완전 로드 대기
        try:
            modal_frame.wait_for_load_state("domcontentloaded", timeout=10_000)
        except Exception:
            pass
        self.human_delay(500, 800)

        # Step 3: data-advertiser-id 행 클릭 (td.blue → a → tr 순서로 시도)
        clicked = False
        if self.account_id:
            for sel in (
                f"tr[data-advertiser-id='{self.account_id}'] td.blue",
                f"tr[data-advertiser-id='{self.account_id}'] a",
                f"tr[data-advertiser-id='{self.account_id}']",
            ):
                try:
                    loc = modal_frame.locator(sel).first
                    loc.wait_for(state="visible", timeout=5_000)
                    loc.click()
                    self._info(f"  계정 행 클릭: {self.account_id} ({sel.split(']')[1]})")
                    clicked = True
                    break
                except Exception as e:
                    self._info(f"  클릭 실패 ({sel.split(']')[1]}): {e}")

        # fallback: 아이디 td 텍스트 매칭
        if not clicked:
            for key in search_keys:
                try:
                    for td in modal_frame.locator("td").all():
                        try:
                            if td.inner_text(timeout=300).strip() == key:
                                # 같은 행의 td.blue 클릭 시도
                                row_blue = modal_frame.locator(
                                    f"tr:has(td:text-is('{key}')) td.blue"
                                ).first
                                row_blue.click(timeout=3_000)
                                self._info(f"  계정 행 클릭 (텍스트 매칭): {key}")
                                clicked = True
                                break
                        except Exception:
                            continue
                    if clicked:
                        break
                except Exception:
                    continue

        if not clicked:
            self._screenshot(page, f"{self.MEDIA_CODE}_account_row_not_found_{self.account_id}")
            raise RuntimeError(
                f"모비온 광고주 로그인 모달에서 계정을 찾을 수 없습니다: "
                f"{self.account_id} / {self.account_name}"
            )

        # Step 4: 비밀번호 재입력 다이얼로그 처리 (행 클릭 후 나타남)
        self.human_delay(500, 800)
        try:
            pw_input = modal_frame.locator("input[type='password']").first
            pw_input.wait_for(state="visible", timeout=4_000)
            password = self._runtime_password()
            if not password:
                raise RuntimeError(
                    f"keyring에 비밀번호 없음: {self.account_id} — "
                    f"모비온_비밀번호설정.py 실행 필요"
                )
            pw_input.fill(password)
            self.human_delay(300, 500)
            # Enter 키로 제출 (버튼 클릭보다 안정적)
            pw_input.press("Enter")
            self.human_delay(200, 400)
            # fallback: 확인 버튼 직접 클릭
            try:
                confirm_btn = modal_frame.locator("button:has-text('확인'), input[value='확인']").first
                if confirm_btn.is_visible(timeout=1_000):
                    confirm_btn.click()
            except Exception:
                pass
            self._info("  비밀번호 입력 완료")
        except RuntimeError:
            raise
        except Exception:
            # 비밀번호 다이얼로그 없음 — 바로 전환
            pass

        # 계정 전환 후 페이지 로드 대기
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass
        self.human_delay(800, 1200)
        self._info(f"  계정 전환 완료: {self.account_id}")

    def _runtime_password(self) -> str:
        try:
            import keyring
            _SVC = "ad_report_downloader_mobon"
            for key in (self.account_id, self.account_name):
                if key:
                    pw = keyring.get_password(_SVC, key)
                    if pw:
                        return pw
        except Exception:
            pass
        # 폴백: config 런타임 딕셔너리
        passwords = self.config.get("_mobon_passwords_runtime", {})
        return passwords.get(self.account_id, "") or passwords.get(self.account_name, "")

    def set_period(self, page: "Page", start: date, end: date) -> None:
        start_str = start.strftime("%Y%m%d")
        end_str   = end.strftime("%Y%m%d")

        # daterangepicker 초기화 대기
        try:
            page.wait_for_function("typeof $ !== 'undefined' && $('#dateInput').data('daterangepicker') !== undefined", timeout=8_000)
        except Exception:
            pass

        # daterangepicker JS API로 직접 날짜 설정 (UI 클릭보다 안정적)
        result = page.evaluate(f"""
            (() => {{
                var picker = $('#dateInput').data('daterangepicker');
                if (!picker) return false;
                picker.setStartDate('{start_str}');
                picker.setEndDate('{end_str}');
                picker.clickApply();
                return true;
            }})()
        """)

        if result:
            self.human_delay(800, 1200)
            try:
                page.wait_for_load_state("networkidle", timeout=20_000)
            except Exception:
                pass
            return

        # fallback: UI 클릭 방식
        sel = self._sel["period"]
        button = self._find_first_visible(page, sel["date_range_button"], timeout=8_000)
        if button is None:
            self._screenshot(page, f"{self.MEDIA_CODE}_no_date_button")
            raise RuntimeError("모비온 날짜 범위 버튼을 찾을 수 없습니다.")

        button.click()
        self.human_delay(500, 900)

        picker = page.locator(sel["picker"])
        try:
            picker.wait_for(state="visible", timeout=4_000)
        except Exception:
            try:
                page.evaluate("$('#dateInput').trigger('click')")
                self.human_delay(500, 800)
                picker.wait_for(state="visible", timeout=4_000)
            except Exception as exc:
                self._screenshot(page, f"{self.MEDIA_CODE}_datepicker_not_open")
                raise RuntimeError("모비온 날짜 선택기가 열리지 않았습니다.") from exc

        self._navigate_to_month(page, start, sel)
        self._click_day(page, start, sel)
        self.human_delay(400, 700)
        self._navigate_to_month(page, end, sel)
        self._click_day(page, end, sel)
        self.human_delay(400, 700)

        apply_selector = sel.get("apply_button", "")
        apply_button = self._find_first_visible(page, apply_selector, timeout=2_000)
        if apply_button is not None:
            apply_button.click()

        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
        except Exception:
            pass

    def trigger_download(self, page: "Page", start: date, end: date) -> Path:
        dl_cfg = self._sel["download"]
        timeout_ms = self.timeout_sec * 1000
        button = self._find_download_button(page, dl_cfg)
        if button is None:
            self._screenshot(page, f"{self.MEDIA_CODE}_download_not_found")
            raise RuntimeError("모비온 엑셀 다운로드 버튼을 찾을 수 없습니다.")

        if button.is_disabled():
            raise EmptyDataError("엑셀 버튼이 비활성화되어 있습니다.")

        with page.expect_download(timeout=timeout_ms) as download_info:
            button.click()

        download = download_info.value
        suggested = download.suggested_filename or "mobion_report.xlsx"
        suffix = Path(suggested).suffix or ".xlsx"
        tmp = Path(tempfile.mktemp(suffix=suffix))
        download.save_as(str(tmp))
        if not tmp.exists() or tmp.stat().st_size == 0:
            raise RuntimeError(f"모비온 다운로드 파일이 비어 있습니다: {tmp}")
        return tmp

    def _goto_report(self, page: "Page") -> None:
        base = self._sel["base_url"]
        target = base + self._sel["report"]["report_url_path"]
        page.goto(target, wait_until="domcontentloaded", timeout=30_000)
        self.human_delay(800, 1200)

    def _select_template(self, page: "Page") -> None:
        """보고서 템플릿 드롭다운에서 report_name에 해당하는 항목을 선택한다."""
        report_name = getattr(self, "report_name", "") or ""
        skip_names = ("", "일자별", "기본 템플릿", "일별/월별 실적 보고서")
        if report_name in skip_names:
            return

        dropdown_sel = "div.customSelect[name='customSelectDiv']"
        try:
            dropdown = page.locator(dropdown_sel).first
            dropdown.wait_for(state="visible", timeout=5_000)
        except Exception:
            self._warn(f"보고서 템플릿 드롭다운 없음 — '{report_name}' 선택 생략")
            return

        # 현재 선택된 항목 확인
        try:
            current = dropdown.locator("span").first.inner_text(timeout=2_000).strip()
            if current == report_name:
                self._info(f"보고서 템플릿 이미 선택됨: {report_name}")
                return
        except Exception:
            pass

        # 드롭다운 열기
        try:
            dropdown.click()
            self.human_delay(300, 500)
        except Exception as e:
            self._warn(f"보고서 템플릿 드롭다운 열기 실패: {e}")
            return

        # 항목 클릭 (정확 일치 우선, 부분 일치 fallback)
        # li.admin_first 등 숨겨진/빈 항목은 건너뜀
        item_sel = "div.customSelect[name='customSelectDiv'] ul[name='customSelectUl'] li"
        try:
            items = page.locator(item_sel).all()

            def _visible_items():
                result = []
                for item in items:
                    try:
                        if not item.is_visible(timeout=300):
                            continue
                        text = item.inner_text(timeout=500).strip()
                        if text:
                            result.append((item, text))
                    except Exception:
                        continue
                return result

            visible = _visible_items()
            matched = None

            # 정확 일치
            for item, text in visible:
                if text == report_name:
                    matched = item
                    break

            # 부분 일치 (빈 문자열 제외)
            if matched is None:
                for item, text in visible:
                    if report_name in text or text in report_name:
                        matched = item
                        break

            if matched:
                matched.click()
                self.human_delay(500, 800)
                try:
                    page.wait_for_load_state("networkidle", timeout=10_000)
                except Exception:
                    pass
                self._info(f"보고서 템플릿 선택 완료: {report_name}")
            else:
                self._warn(f"보고서 템플릿 '{report_name}' 항목을 찾을 수 없음 — 기본 템플릿으로 진행")
                # 드롭다운 닫기
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
        except Exception as e:
            self._warn(f"보고서 템플릿 선택 중 오류: {e}")

    def _get_displayed_months(self, page: "Page", sel: dict) -> list[tuple[int, int]]:
        months = []
        for header_selector in (sel["month_header_left"], sel["month_header_right"]):
            try:
                text = page.locator(header_selector).first.inner_text(timeout=2_000)
                match = re.search(r"(\d{4})[^\d]+(\d{1,2})|(\d{1,2})[^\d]+(\d{4})", text)
                if match:
                    if match.group(1):
                        months.append((int(match.group(1)), int(match.group(2))))
                    else:
                        months.append((int(match.group(4)), int(match.group(3))))
            except Exception:
                continue
        return months

    def _navigate_to_month(self, page: "Page", target: date, sel: dict) -> None:
        prev_button = page.locator(sel["prev_month_btn"]).first
        next_button = page.locator(sel["next_month_btn"]).first
        target_month = (target.year, target.month)

        for _ in range(24):
            months = self._get_displayed_months(page, sel)
            if target_month in months:
                return
            if not months:
                break
            if target_month < months[0]:
                prev_button.click()
            else:
                next_button.click()
            self.human_delay(300, 500)

    def _click_day(self, page: "Page", target: date, sel: dict) -> None:
        day = str(target.day)
        months = self._get_displayed_months(page, sel)
        cell_selector = sel["day_cell_left"]
        if months and (target.year, target.month) != months[0]:
            cell_selector = sel["day_cell_right"]

        for selector in (
            cell_selector,
            "div.daterangepicker td.available:not(.off)",
            "div.daterangepicker td:not(.off):not(.disabled)",
        ):
            try:
                for cell in page.locator(selector).all():
                    if cell.inner_text(timeout=500).strip() == day:
                        cell.click()
                        self.human_delay(200, 400)
                        return
            except Exception:
                continue

        self._screenshot(page, f"{self.MEDIA_CODE}_click_day_failed_{target}")
        raise RuntimeError(f"모비온 날짜를 클릭할 수 없습니다: {target}")

    def _find_download_button(self, page: "Page", dl_cfg: dict):
        for key in ("button", "button_fallback"):
            loc = self._find_first_visible(page, dl_cfg.get(key, ""), timeout=5_000)
            if loc is not None:
                return loc
        return None

    @staticmethod
    def _find_first_visible(page: "Page", selector: str, timeout: int = 3_000):
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
