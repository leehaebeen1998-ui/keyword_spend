"""Google Display Ads downloader alias.

The download procedure is identical to Google Ads; only the media code and
configuration bucket are separated for reporting and storage.
"""
from __future__ import annotations

from downloader.google import GoogleDownloader


class GoogleDaDownloader(GoogleDownloader):
    MEDIA_CODE = "google_da"
    IMPLEMENTED = True
