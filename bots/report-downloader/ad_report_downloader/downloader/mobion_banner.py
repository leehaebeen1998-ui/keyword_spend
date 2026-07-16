"""Mobion integrated banner report downloader."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from downloader.mobion_base import MobionBase

if TYPE_CHECKING:
    from playwright.sync_api import Page


_SELECTOR_FILE = Path(__file__).parent.parent / "selectors" / "mobion_banner.yaml"


class MobionBannerDownloader(MobionBase):
    MEDIA_CODE = "mobion_banner"
    IMPLEMENTED = True
    _SELECTOR_FILE = _SELECTOR_FILE

    def navigate_to_report(self, page: "Page") -> None:
        self._info("모비온 통합 배너 보고서 이동")
        # 리포트 페이지 이동 → 마스터 계정일 때 광고주 로그인 모달 자동 등장
        self._goto_report(page)
        if self.account_id:
            self._switch_account(page)
        else:
            self._warn("account_id 미설정 — 현재 로그인 계정으로 진행")
        self._select_template(page)
