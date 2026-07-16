"""
mobion downloader — stub (Phase 0).
Implement check_login / navigate_to_report / set_period / trigger_download
then set IMPLEMENTED = True.
"""
from __future__ import annotations
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page

from downloader.base import BaseDownloader

MEDIA_CODE_MAP = {
    "naver": "naver",
    "google": "google",
    "meta": "meta",
    "kakao": "kakao",
    "adn": "adn",
    "mobion": "mobion",
    "x_ads": "x",
}

_THIS_MODULE = "mobion"


class _StubDownloader(BaseDownloader):
    MEDIA_CODE = MEDIA_CODE_MAP.get(_THIS_MODULE, _THIS_MODULE)
    IMPLEMENTED = False   # ← flip to True when all methods are filled in

    def check_login(self, page: "Page") -> bool:
        raise NotImplementedError(f"{self.MEDIA_CODE}: check_login 미구현")

    def navigate_to_report(self, page: "Page") -> None:
        raise NotImplementedError(f"{self.MEDIA_CODE}: navigate_to_report 미구현")

    def set_period(self, page: "Page", start: date, end: date) -> None:
        raise NotImplementedError(f"{self.MEDIA_CODE}: set_period 미구현")

    def trigger_download(self, page: "Page", start: date, end: date) -> Path:
        raise NotImplementedError(f"{self.MEDIA_CODE}: trigger_download 미구현")


# Public alias used by the orchestrator factory
MobionDownloader = _StubDownloader
