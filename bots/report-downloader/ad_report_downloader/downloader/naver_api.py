"""Naver 검색광고 API 다운로더 — 다차원 보고서(브라우저 자동화) 완전 대체.

ads.naver.com 다차원 보고서 UI를 Playwright로 조작하던 기존 NaverDownloader를
공식 검색광고 API(https://api.searchad.naver.com) 호출로 대체한다.

인증: base64(HMAC-SHA256("{timestamp}.{method}.{path}", secret_key))
  헤더 X-Timestamp / X-API-KEY / X-Customer / X-Signature (path는 쿼리스트링 제외)

데이터 소스 (대용량 보고서, stat-reports):
  - AD            : 일별 키워드/소재/매체/PC모바일 단위 노출·클릭·비용·순위합
  - AD_CONVERSION : 일별 전환수 (전환방법 1직접/2간접, 전환유형별)
  - EXPKEYWORD    : 검색어 보고서 (검색어/검색어유형 단위) — 일로 ver3 용
  마스터 리포트(Campaign/Adgroup/Keyword/BusinessChannel)로 ID → 이름/URL 해석.

출력: 기존 다차원 보고서 CSV와 동일한 형식(utf-8-sig, 1행 제목, 브랜드별 컬럼
레이아웃)으로 저장해 후처리 파이프라인(키워드 소진내역 가공)을 그대로 통과한다.

주의(2026-02-11 API 공지): 2026-03-30부터 stat-report의 모든 COST는 VAT 포함
정수로 제공된다. 다차원 보고서 화면 값과의 일치 여부는 실데이터 대조로 확정하며,
naver_api.cost_vat_mode 설정("include" 그대로 / "exclude" 1.1로 나눔)으로 제어한다.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import json
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from downloader.base import BaseDownloader, DownloadResult, EmptyDataError

# ──────────────────────────────────────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_BASE_URL = "https://api.searchad.naver.com"

# 마스터 Campaign type 코드 → 다차원 보고서 '캠페인유형' 라벨
# (실데이터 검증: 태하/오현 CSV의 라벨 = 파워링크/플레이스/파워컨텐츠/브랜드검색/신제품검색)
CAMPAIGN_TYPE_LABELS = {
    "1": "파워링크",
    "2": "쇼핑검색",
    "3": "파워컨텐츠",
    "4": "브랜드검색/신제품검색",
    "5": "플레이스",
    "6": "플레이스",
}

PC_MOBILE_LABELS = {"P": "PC", "M": "모바일"}

# Adgroup 마스터 16번(AdGroup Type) 코드 → 캠페인유형 라벨 (캠페인 마스터에 없는
# 삭제 캠페인의 유형 폴백용)
ADGROUP_TYPE_LABELS = {
    "1": "파워링크",
    "2": "쇼핑검색",
    "3": "파워컨텐츠",
    "4": "파워컨텐츠",
    "5": "브랜드검색/신제품검색",
    "6": "플레이스",
    "7": "쇼핑검색",
    "8": "브랜드검색/신제품검색",
    "9": "쇼핑검색",
    "10": "플레이스",
    "11": "브랜드검색/신제품검색",
}

SEARCH_TYPE_LABELS = {"0": "일치", "5": "일치", "1": "확장", "2": "유사일치"}

# 컬럼명 → 차원(dimension) 키
_DIM_COLUMNS = {
    "일별": "date",
    "캠페인유형": "campaign_type",
    "URL": "url",
    "비즈채널": "channel_id",
    "PC/모바일 매체": "device",
    "캠페인": "campaign_name",
    "광고그룹": "adgroup_name",
    "키워드": "keyword",
    "검색어": "search_term",
    "검색 유형": "search_type",
}

# 지표 컬럼 (집계 후 계산)
_METRIC_COLUMNS = {
    "노출수", "클릭수", "클릭률(%)", "평균 CPC", "총비용",
    "총 전환수", "총 전환율(%)", "총 전환당비용(원)", "평균노출순위",
}

# 브랜드별 CSV 레이아웃 프리셋 — 기존 다차원 보고서 산출물과 동일해야 한다.
# ("ohyun"에 '캠페인' 컬럼을 추가하면 안 됨: 후처리의 파워컨텐츠 중복 제거 로직이
#  '캠페인 없는 파워컨텐츠 행 스킵'에 의존한다.)
LAYOUTS: dict[str, dict] = {
    # 태하-데일리 '일일보고서_0920'
    "daily_keyword": {
        "source": "ad",
        "columns": [
            "일별", "캠페인유형", "PC/모바일 매체", "키워드",
            "노출수", "클릭수", "클릭률(%)", "평균 CPC", "총비용",
            "총 전환수", "총 전환율(%)", "총 전환당비용(원)", "평균노출순위",
        ],
    },
    # 태하-데일리 thlaw_04 — 같은 보고서명이지만 비즈채널·캠페인 컬럼이 더 있다
    # (실물 확인: naver_thlaw_04_raw_*.csv). 캠페인명이 있어야 상위 앱의
    # '캠페인명' 규칙(행정/군형사 분류)이 동작하므로 반드시 유지해야 한다.
    "daily_keyword_bizchannel": {
        "source": "ad",
        "columns": [
            "일별", "비즈채널", "캠페인", "캠페인유형", "PC/모바일 매체", "키워드",
            "노출수", "클릭수", "클릭률(%)", "평균 CPC", "총비용",
            "총 전환수", "총 전환율(%)", "총 전환당비용(원)", "평균노출순위",
        ],
    },
    # 오현 '오현 키워드 소진액' / '(스프레드)'
    "ohyun": {
        "source": "ad",
        "columns": [
            "일별", "URL", "캠페인유형", "PC/모바일 매체", "키워드",
            "노출수", "클릭수", "클릭률(%)", "평균 CPC", "총비용", "평균노출순위",
        ],
    },
    # 오현 '오현 키워드 소진액(스프레드)' — 캠페인·광고그룹이 더 있다.
    # 이 컬럼 차이가 상위 앱의 파워컨텐츠 중복 제거를 좌우한다:
    # _skip_raw_row_for_file은 '캠페인이 비어 있는 파워컨텐츠 행'을 버리므로,
    # 캠페인 컬럼이 있는 스프레드 파일에서만 파워컨텐츠 실적이 집계된다.
    # 따라서 두 파일의 레이아웃을 절대 통일하면 안 된다.
    "ohyun_spread": {
        "source": "ad",
        "columns": [
            "일별", "캠페인", "광고그룹", "URL", "캠페인유형", "PC/모바일 매체",
            "키워드", "노출수", "클릭수", "총비용", "평균노출순위",
        ],
    },
    # 태하 주간 / 미소 등 (캠페인·광고그룹 포함 구형 레이아웃)
    "weekly_generic": {
        "source": "ad",
        "columns": [
            "일별", "캠페인유형", "URL", "PC/모바일 매체", "캠페인", "광고그룹",
            "키워드", "노출수", "클릭수", "총비용", "총 전환수",
        ],
    },
    # 일로 ver3 (검색어 차원) — EXPKEYWORD 기반
    "ilo_search": {
        "source": "ilo_search",
        "columns": [
            "일별", "캠페인", "광고그룹", "캠페인유형", "PC/모바일 매체",
            "검색 유형", "검색어",
            "노출수", "클릭수", "클릭률(%)", "평균 CPC", "총비용", "평균노출순위",
        ],
    },
    # 일로 ver2 (키워드 차원) — AD 보고서 기반
    "ilo_keyword": {
        "source": "ilo_keyword",
        "columns": [
            "일별", "캠페인", "광고그룹", "캠페인유형", "PC/모바일 매체",
            "검색 유형", "키워드",
            "노출수", "클릭수", "클릭률(%)", "평균 CPC", "총비용", "평균노출순위",
        ],
    },
}


class NaverApiError(Exception):
    """검색광고 API 호출 실패."""


# ──────────────────────────────────────────────────────────────────────────────
# API 클라이언트 (표준 라이브러리만 사용 — 번들 파이썬에 추가 의존성 없음)
# ──────────────────────────────────────────────────────────────────────────────

class NaverAdApiClient:
    def __init__(self, base_url: str, api_key: str, secret_key: str,
                 customer_id: str, log=None):
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key
        self.secret_key = secret_key
        self.customer_id = str(customer_id)
        self._log = log or (lambda msg: None)

    # ── 서명/헤더 ────────────────────────────────────────────────────────────
    def _headers(self, method: str, path: str) -> dict:
        ts = str(round(time.time() * 1000))
        message = f"{ts}.{method}.{path}"
        digest = hmac.new(
            self.secret_key.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return {
            "X-Timestamp": ts,
            "X-API-KEY": self.api_key,
            "X-Customer": self.customer_id,
            "X-Signature": base64.b64encode(digest).decode("ascii"),
        }

    # ── HTTP ────────────────────────────────────────────────────────────────
    def _request_raw(self, method: str, url: str, path: str,
                     body: bytes | None = None,
                     content_type: str | None = None,
                     retries: int = 3) -> bytes:
        last_err: Exception | None = None
        for attempt in range(1, retries + 1):
            headers = self._headers(method, path)
            if content_type:
                headers["Content-Type"] = content_type
            req = urllib.request.Request(url, data=body, method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return resp.read()
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", "replace")[:400]
                except Exception:
                    pass
                # 4xx는 재시도해도 같은 결과 (429 제외)
                if e.code not in (429, 500, 502, 503, 504):
                    raise NaverApiError(f"HTTP {e.code} {method} {path}: {detail}") from e
                last_err = NaverApiError(f"HTTP {e.code} {method} {path}: {detail}")
            except Exception as e:  # 네트워크 오류 등
                last_err = e
            if attempt < retries:
                time.sleep(2 * attempt)
        raise NaverApiError(f"{method} {path} 재시도 {retries}회 실패: {last_err}")

    def request_json(self, method: str, path: str,
                     params: dict | None = None, body: dict | None = None):
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        raw = self._request_raw(
            method, url, path, body=data,
            content_type="application/json; charset=UTF-8" if data else None,
        )
        if not raw:
            return None
        return json.loads(raw.decode("utf-8"))

    def download_text(self, download_url: str) -> str:
        """stat/master 보고서 downloadUrl 수신 — URL의 path로 서명해야 한다."""
        parsed = urllib.parse.urlsplit(download_url)
        raw = self._request_raw("GET", download_url, parsed.path)
        for enc in ("utf-8-sig", "utf-8", "cp949"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", "replace")


# ──────────────────────────────────────────────────────────────────────────────
# 보고서 잡 공통 (생성 → 폴링 → 다운로드 → 삭제)
# ──────────────────────────────────────────────────────────────────────────────

def _poll_job(client: NaverAdApiClient, get_path: str, timeout_sec: int,
              label: str) -> dict:
    deadline = time.time() + timeout_sec
    interval = 3.0
    while True:
        job = client.request_json("GET", get_path)
        status = (job or {}).get("status", "")
        if status == "BUILT":
            return job
        if status == "NONE":
            return job  # 데이터 없음
        if status == "ERROR":
            raise NaverApiError(f"{label} 생성 실패 (status=ERROR)")
        if time.time() > deadline:
            raise NaverApiError(f"{label} 생성 대기 시간 초과 ({timeout_sec}s, status={status})")
        time.sleep(interval)
        interval = min(interval * 1.5, 15.0)


def _parse_tsv(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in text.splitlines():
        if line.strip():
            rows.append(line.split("\t"))
    return rows


def _fetch_stat_rows(client: NaverAdApiClient, report_tp: str, stat_dt: date,
                     timeout_sec: int, log) -> list[list[str]]:
    """대용량 보고서 1건 (reportTp × 날짜) 생성/수신."""
    dt_str = stat_dt.strftime("%Y%m%d")
    job = None
    try:
        job = client.request_json("POST", "/stat-reports",
                                  body={"reportTp": report_tp, "statDt": dt_str})
    except NaverApiError as e:
        # 동일 잡이 이미 존재하는 경우 등 — 목록에서 재사용 시도
        log(f"stat-report 생성 실패({report_tp} {dt_str}): {e} — 기존 잡 확인")
        existing = client.request_json("GET", "/stat-reports") or []
        for item in existing:
            if item.get("reportTp") == report_tp and \
                    str(item.get("statDt", ""))[:10].replace("-", "")[:8] == dt_str:
                job = item
                break
        if job is None:
            raise
    job_id = job.get("reportJobId")
    if job_id is None:
        raise NaverApiError(f"stat-report 잡 ID 없음: {job}")
    try:
        job = _poll_job(client, f"/stat-reports/{job_id}", timeout_sec,
                        f"stat-report {report_tp} {dt_str}")
        if job.get("status") == "NONE" or not job.get("downloadUrl"):
            log(f"{report_tp} {dt_str}: 데이터 없음")
            return []
        text = client.download_text(job["downloadUrl"])
        rows = _parse_tsv(text)
        log(f"{report_tp} {dt_str}: {len(rows)}행 수신")
        return rows
    finally:
        try:
            client.request_json("DELETE", f"/stat-reports/{job_id}")
        except Exception:
            pass


def _fetch_master_rows(client: NaverAdApiClient, item: str,
                       timeout_sec: int, log) -> list[list[str]]:
    """마스터 리포트 1건 (item 전체 스냅샷) 생성/수신."""
    job = client.request_json("POST", "/master-reports", body={"item": item})
    job_id = job.get("id")
    if not job_id:
        raise NaverApiError(f"master-report 잡 ID 없음: {job}")
    try:
        job = _poll_job(client, f"/master-reports/{job_id}", timeout_sec,
                        f"master-report {item}")
        if job.get("status") == "NONE" or not job.get("downloadUrl"):
            return []
        rows = _parse_tsv(client.download_text(job["downloadUrl"]))
        log(f"마스터 {item}: {len(rows)}행")
        return rows
    finally:
        try:
            client.request_json("DELETE", f"/master-reports/{job_id}")
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────────────────────
# 마스터 데이터 (customer 단위 캐시 — 한 실행 내 계정 중복 조회 방지)
# ──────────────────────────────────────────────────────────────────────────────

class MasterData:
    def __init__(self):
        self.campaign_name: dict[str, str] = {}
        self.campaign_type: dict[str, str] = {}
        self.adgroup_name: dict[str, str] = {}
        self.keyword_text: dict[str, str] = {}
        self.keyword_url_pc: dict[str, str] = {}
        self.keyword_url_mbl: dict[str, str] = {}
        # 채널ID → channelKey (SITE: URL 원형, PLACE: 플레이스 숫자 ID)
        # — 다차원 보고서의 'URL' 차원과 동일한 값 (/ncc/channels에서 수집)
        self.channel_key: dict[str, str] = {}
        # 채널ID → 마스터 Channel Contents (channelKey 부재 시 폴백)
        self.channel_contents: dict[str, str] = {}
        # 광고그룹별 등록 키워드 텍스트 (AI 키워드 재분배 시 제외 목록)
        self.adgroup_keywords: dict[str, set] = {}
        # 광고그룹ID → AdGroup Type 코드 (삭제 캠페인의 유형 폴백)
        self.adgroup_type: dict[str, str] = {}


_MASTER_CACHE: dict[str, MasterData] = {}
_STAT_CACHE: dict[tuple, list[list[str]]] = {}


def _get_master(client: NaverAdApiClient, timeout_sec: int, log) -> MasterData:
    key = f"{client.base_url}|{client.customer_id}"
    if key in _MASTER_CACHE:
        return _MASTER_CACHE[key]

    m = MasterData()
    for row in _fetch_master_rows(client, "Campaign", timeout_sec, log):
        # 1 CustomerID, 2 CampaignID, 3 Name, 4 Type
        if len(row) >= 4:
            m.campaign_name[row[1]] = row[2]
            m.campaign_type[row[1]] = row[3].strip()
    for row in _fetch_master_rows(client, "Adgroup", timeout_sec, log):
        # 1 CustomerID, 2 AdgroupID, 3 CampaignID, 4 Name, ... 16 AdGroup Type
        if len(row) >= 4:
            m.adgroup_name[row[1]] = row[3]
            if len(row) >= 16:
                m.adgroup_type[row[1]] = row[15].strip()
    for row in _fetch_master_rows(client, "Keyword", timeout_sec, log):
        # 1 CustomerID, 2 AdgroupID, 3 KeywordID, 4 Keyword, 5 bid,
        # 6 landingURL(PC), 7 landingURL(Mobile)
        if len(row) >= 4:
            m.keyword_text[row[2]] = row[3]
            m.adgroup_keywords.setdefault(row[1], set()).add(row[3])
            if len(row) >= 7:
                m.keyword_url_pc[row[2]] = row[5]
                m.keyword_url_mbl[row[2]] = row[6]
    for row in _fetch_master_rows(client, "BusinessChannel", timeout_sec, log):
        # 1 CustomerID, 2 Name, 3 ChannelID, 4 Type, 5 Contents
        if len(row) >= 5:
            m.channel_contents[row[2]] = row[4].rstrip("/")
    # channelKey — 다차원 보고서 URL 차원과 동일한 값 (SITE: URL, PLACE: 숫자 ID)
    try:
        channels = client.request_json("GET", "/ncc/channels") or []
        for ch in channels:
            ch_id = str(ch.get("nccBusinessChannelId") or "")
            key = str(ch.get("channelKey") or "")
            if ch_id and key:
                m.channel_key[ch_id] = key
        log(f"채널 channelKey: {len(m.channel_key)}건")
    except Exception as e:
        log(f"⚠ /ncc/channels 조회 실패 — 마스터 contents로 대체: {e}")

    unmapped = sorted({t for t in m.campaign_type.values()
                       if t not in CAMPAIGN_TYPE_LABELS})
    if unmapped:
        log(f"⚠ 매핑되지 않은 캠페인유형 코드: {unmapped} (라벨 확인 필요)")

    _MASTER_CACHE[key] = m
    return m


def _get_stat_rows(client: NaverAdApiClient, report_tp: str, stat_dt: date,
                   timeout_sec: int, log) -> list[list[str]]:
    key = (client.base_url, client.customer_id, report_tp, stat_dt)
    if key not in _STAT_CACHE:
        _STAT_CACHE[key] = _fetch_stat_rows(client, report_tp, stat_dt,
                                            timeout_sec, log)
    return _STAT_CACHE[key]


def clear_caches() -> None:
    _MASTER_CACHE.clear()
    _STAT_CACHE.clear()


# ──────────────────────────────────────────────────────────────────────────────
# 숫자 파싱/출력 헬퍼
# ──────────────────────────────────────────────────────────────────────────────

def _campaign_type_label(master: "MasterData", campaign_id: str,
                         adgroup_id: str, keyword_resolved: bool) -> str:
    """캠페인유형 라벨: 캠페인 마스터 → 광고그룹 타입 → 키워드 존재 시 파워링크."""
    tp = master.campaign_type.get(campaign_id, "")
    if tp:
        return CAMPAIGN_TYPE_LABELS.get(tp, tp)
    ag_tp = master.adgroup_type.get(adgroup_id, "")
    if ag_tp:
        return ADGROUP_TYPE_LABELS.get(ag_tp, ag_tp)
    if keyword_resolved:
        return "파워링크"
    return "-"


def _channel_url(master: "MasterData", channel_id: str,
                 keyword_id: str, device: str) -> str:
    """다차원 'URL' 차원 값: channelKey(정확) → 마스터 contents → 키워드 landing."""
    url = (master.channel_key.get(channel_id, "")
           or master.channel_contents.get(channel_id, ""))
    if not url and keyword_id not in ("", "-"):
        url = (master.keyword_url_pc.get(keyword_id, "") if device == "PC"
               else master.keyword_url_mbl.get(keyword_id, ""))
    return url or "-"


def _num(value: str) -> float:
    try:
        return float(str(value).strip() or 0)
    except ValueError:
        return 0.0


def _fmt(value: float, decimals: int = 0) -> str:
    """다차원 CSV와 같은 표기: 정수는 정수로, 소수는 불필요한 0 제거."""
    if decimals <= 0:
        return str(int(round(value)))
    text = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    return text or "0"


# ──────────────────────────────────────────────────────────────────────────────
# 다운로더
# ──────────────────────────────────────────────────────────────────────────────

class NaverApiDownloader(BaseDownloader):
    """검색광고 API 기반 네이버 보고서 수집기 (브라우저/로그인 불필요)."""

    MEDIA_CODE = "naver"
    IMPLEMENTED = True

    def __init__(self, config: dict, account: dict | None = None):
        super().__init__(config, account)
        api_cfg = config.get("naver_api", {}) or {}
        self.api_key = str(api_cfg.get("api_key", "")).strip()
        self.secret_key = str(api_cfg.get("secret_key", "")).strip()
        self.base_url = str(api_cfg.get("base_url", DEFAULT_BASE_URL)).strip()
        self.cost_vat_mode = str(api_cfg.get("cost_vat_mode", "include")).strip()
        self.conversion_methods = set(
            str(x) for x in api_cfg.get("conversion_methods", [1, 2])
        )
        self.report_timeout_sec = int(api_cfg.get("report_timeout_sec", 600))
        # CUSTOMER_ID: 계정별 명시값 우선, 없으면 account_id 사용
        self.customer_id = str(
            (self.account.get("customer_id") or self.account_id or "")
        ).strip()
        self.layout_name = str(
            self.account.get("api_layout") or self._infer_layout()
        ).strip()

    # ── 레이아웃 결정 ────────────────────────────────────────────────────────
    def _infer_layout(self) -> str:
        name = self.report_name or ""
        brand = (self.brand_name or "")
        if "스프레드" in name:
            return "ohyun_spread"
        if "일일보고서" in name:
            return "daily_keyword"
        if "_ver3" in name or "ver3" in (self.account_name or ""):
            return "ilo_search"
        if "_ver2" in name or "ver2" in (self.account_name or ""):
            return "ilo_keyword"
        if "오현" in name or "오현" in brand:
            return "ohyun"
        return "weekly_generic"

    # ── 실행 진입점 (BaseDownloader.run 대체: 브라우저 불필요) ────────────────
    def run(self, context, start_date: date, end_date: date) -> DownloadResult:
        label = f" [{self.account_name}]" if self.account_name else ""
        self._info(f"API 실행 시작{label} (customer={self.customer_id}, layout={self.layout_name})")

        problem = self._validate()
        if problem:
            self._error(problem)
            return DownloadResult(media_code=self.MEDIA_CODE, error=problem)

        import random
        for attempt in range(1, self.max_attempts + 1):
            if self._stop_requested:
                return self._skip("중지 요청")
            try:
                return self._attempt_api(start_date, end_date)
            except EmptyDataError:
                self._warn("데이터 없음 — 해당 기간 집행 내역 없음")
                return self._skip("데이터 없음")
            except Exception as e:
                text = str(e)
                if "auth-failed" in text or "Auth Failed" in text:
                    # 실전에서 가장 흔한 원인: config의 account_id(ads.naver.com
                    # 광고계정 번호)를 그대로 X-Customer로 보낸 경우. 검색광고
                    # API는 SA CUSTOMER_ID를 요구하므로 계정별 customer_id가
                    # 채워져 있어야 한다.
                    self._error(
                        f"인증 실패 (customer={self.customer_id}). "
                        "config.json의 해당 계정에 customer_id(검색광고 CUSTOMER_ID)가 "
                        "채워져 있는지 확인하세요 — account_id(광고계정 번호)와 다른 값입니다. "
                        "API 키가 이 계정에 대한 권한을 가지고 있는지도 확인이 필요합니다."
                    )
                    return DownloadResult(
                        media_code=self.MEDIA_CODE,
                        error=f"인증 실패 (customer_id 확인 필요): {text[:200]}",
                    )
                self._error(f"시도 {attempt}/{self.max_attempts} 실패: {e}")
                if attempt < self.max_attempts:
                    wait = round(random.uniform(2.0, 4.0), 1)
                    self._info(f"{wait}초 후 재시도")
                    time.sleep(wait)

        return DownloadResult(
            media_code=self.MEDIA_CODE,
            error=f"{self.max_attempts}회 재시도 후 실패",
        )

    def _validate(self) -> str:
        if not self.api_key or not self.secret_key:
            return ("네이버 API 키 미설정 — config.json의 naver_api.api_key / "
                    "naver_api.secret_key를 입력하세요 (광고시스템 > 도구 > API 사용 관리)")
        if not self.customer_id:
            return "CUSTOMER_ID 미설정 — 계정의 account_id 또는 customer_id를 입력하세요"
        layout = LAYOUTS.get(self.layout_name)
        if layout is None:
            return f"알 수 없는 api_layout: '{self.layout_name}' (사용 가능: {sorted(LAYOUTS)})"
        return ""

    # ── 본 작업 ──────────────────────────────────────────────────────────────
    def _attempt_api(self, start: date, end: date) -> DownloadResult:
        layout = LAYOUTS[self.layout_name]
        client = NaverAdApiClient(
            self.base_url, self.api_key, self.secret_key, self.customer_id,
            log=self._info,
        )
        master = _get_master(client, self.report_timeout_sec, self._info)

        source = layout["source"]
        if source == "ad":
            rows = self._build_ad_rows(client, master, layout, start, end)
        elif source in ("ilo_keyword", "ilo_search"):
            rows = self._build_ilo_rows(client, master, layout, start, end, source)
        else:
            rows = self._build_search_rows(client, master, layout, start, end)

        if not rows:
            raise EmptyDataError()

        tmp = self._write_csv(layout, rows, start, end)
        self._check_layout_drift(layout)

        from utils.file_manager import build_destination_path, move_download
        dest = build_destination_path(
            self.save_root, self.MEDIA_CODE, start, end, ".csv",
            account_name=self.account_name,
            brand_name=self.brand_name,
            report_label=self.report_label,
        )
        self._info(f"파일 이동 중 → {dest}")
        final = move_download(tmp, dest, overwrite=self.overwrite)
        self._info(f"✓ 완료: {final} ({len(rows)}행)")
        return DownloadResult(media_code=self.MEDIA_CODE, success=True, dest_path=final)

    # ── AD(+AD_CONVERSION) 기반 집계 ─────────────────────────────────────────
    def _build_ad_rows(self, client, master: MasterData, layout: dict,
                       start: date, end: date) -> list[dict]:
        dim_cols = [c for c in layout["columns"] if c in _DIM_COLUMNS]
        need_conv = any(c.startswith("총 전환") for c in layout["columns"])

        agg: dict[tuple, dict] = {}

        def _accumulate(dims: dict, imp: float, clk: float, cost: float,
                        rank_sum: float, conv: float = 0.0) -> None:
            key = tuple(dims[_DIM_COLUMNS[c]] for c in dim_cols)
            slot = agg.setdefault(key, {
                "dims": dims, "imp": 0.0, "clk": 0.0, "cost": 0.0,
                "rank_sum": 0.0, "conv": 0.0,
            })
            slot["imp"] += imp
            slot["clk"] += clk
            slot["cost"] += cost
            slot["rank_sum"] += rank_sum
            slot["conv"] += conv

        day = start
        while day <= end:
            if self._stop_requested:
                break
            ad_rows = _get_stat_rows(client, "AD", day,
                                     self.report_timeout_sec, self._info)
            # (캠페인, 광고그룹, 매체구분)별 미해석 키워드 풀 — AI 광고 시스템
            # 광고그룹의 자동 키워드는 구 API 마스터에 없어 텍스트 해석 불가.
            unresolved: dict[tuple, dict] = {}
            for row in ad_rows:
                # AD: 0 Date, 1 CustomerID, 2 CampaignID, 3 AdgroupID,
                #     4 KeywordID, 5 AdID, 6 BusinessChannelID, 7 MediaCode,
                #     8 PCMobileType, 9 Imp, 10 Click, 11 Cost, 12 SumAdRank
                if len(row) < 13:
                    continue
                kw_id = row[4].strip()
                if kw_id not in ("", "-") and kw_id not in master.keyword_text:
                    pkey = (row[2], row[3], row[8].strip())
                    pool = unresolved.setdefault(pkey, {
                        "imp": 0.0, "clk": 0.0, "cost": 0.0, "rank_sum": 0.0,
                        "channel_id": row[6].strip() if len(row) > 6 else "",
                    })
                    pool["imp"] += _num(row[9])
                    pool["clk"] += _num(row[10])
                    pool["cost"] += _num(row[11])
                    pool["rank_sum"] += _num(row[12])
                    continue
                dims = self._dims_for_ad_row(row, master, day)
                _accumulate(dims, _num(row[9]), _num(row[10]),
                            _num(row[11]), _num(row[12]))

            if unresolved:
                self._redistribute_unresolved(
                    client, master, day, unresolved, _accumulate)

            if need_conv:
                conv_rows = _get_stat_rows(client, "AD_CONVERSION", day,
                                           self.report_timeout_sec, self._info)
                for row in conv_rows:
                    # AD_CONVERSION: 0 Date, 1 CustomerID, 2 CampaignID,
                    #   3 AdgroupID, 4 KeywordID, 5 AdID, 6 BusinessChannelID,
                    #   7 MediaCode, 8 PCMobileType, 9 Method, 10 Type,
                    #   11 ConvCount, 12 Sales
                    if len(row) < 12:
                        continue
                    if str(row[9]).strip() not in self.conversion_methods:
                        continue
                    # 미해석 키워드의 전환은 '-' 행으로 귀속됨 (텍스트 매핑 불가)
                    dims = self._dims_for_ad_row(row, master, day)
                    _accumulate(dims, 0.0, 0.0, 0.0, 0.0, _num(row[11]))
            day += timedelta(days=1)

        return [agg[k] for k in sorted(agg.keys())]

    def _redistribute_unresolved(self, client, master: MasterData, day: date,
                                 unresolved: dict, _accumulate) -> None:
        """마스터에 없는(AI 광고 자동) 키워드 실적을 검색어 보고서(EXPKEYWORD)로
        재분배한다.

        검증 결과(태하 thlaw_05, 2026-08-10): AI 시스템 광고그룹의 미해석 키워드
        실적은 같은 (캠페인, 광고그룹, PC/모바일) 그룹의 EXPKEYWORD 합계와 정확히
        일치하며, 다차원 보고서의 키워드 텍스트 = 검색어 텍스트였다.
        그룹 합계가 어긋나면 재분배하지 않고 '-' 행으로 안전하게 귀속시킨다.
        """
        exp_rows = _get_stat_rows(client, "EXPKEYWORD", day,
                                  self.report_timeout_sec, self._info)
        # (캠페인, 광고그룹, 매체구분) → [ (검색어, imp, clk, cost) ... ]
        exp_by_group: dict[tuple, list] = {}
        for row in exp_rows:
            # EXPKEYWORD: 0 Date, 1 CustomerID, 2 CampaignID, 3 AdgroupID,
            #   4 SearchKeyword, 5 MediaCode, 6 PCMobileType, 7 Type,
            #   8 Imp, 9 Click, 10 Cost
            if len(row) < 11:
                continue
            gkey = (row[2], row[3], row[6].strip())
            exp_by_group.setdefault(gkey, []).append(
                (row[4], _num(row[8]), _num(row[9]), _num(row[10]),
                 row[7].strip()))

        for (campaign_id, adgroup_id, device_code), pool in unresolved.items():
            candidates = exp_by_group.get(
                (campaign_id, adgroup_id, device_code), [])
            # 후보 검색어: 일치(type 0/5)이면서 이 광고그룹의 등록 키워드가 아닌
            # 것만. 등록 키워드의 일치·확장 실적은 이미 해석된 키워드 행에 집계돼
            # 있다 (검증: 태하 thlaw_01 혼합 그룹, thlaw_05 시스템 그룹).
            # 삭제된 지 오래된 광고그룹(마스터 부재)은 확장 실적 구분이 불가능해
            # 아래 합계 검증에서 자연히 '-' 행 폴백으로 빠진다 — 전일 데이터를
            # 받는 일상 운영에서는 발생하지 않고 과거 백필에서만 나타난다.
            resolved_texts = master.adgroup_keywords.get(adgroup_id, set())
            filtered = [t for t in candidates
                        if t[4] in ("0", "5") and t[0] not in resolved_texts]
            # 같은 검색어가 매체별로 여러 행일 수 있어 검색어 단위로 합산
            per_term: dict[str, list] = {}
            for term, imp, clk, cost, _tp in filtered:
                slot = per_term.setdefault(term, [0.0, 0.0, 0.0])
                slot[0] += imp
                slot[1] += clk
                slot[2] += cost
            terms = [(term, v[0], v[1], v[2]) for term, v in per_term.items()]
            t_imp = sum(t[1] for t in terms)
            t_clk = sum(t[2] for t in terms)
            t_cost = sum(t[3] for t in terms)
            # 클릭·비용은 정확히 일치해야 하고(금액 무결성), 노출수는 EXP에
            # 일부 누락될 수 있어(콘텐츠 매체 등) 잔여분을 '-' 행으로 넘긴다.
            imp_gap = pool["imp"] - t_imp
            ok = (terms
                  and t_clk == pool["clk"]
                  and abs(t_cost - pool["cost"]) <= max(2.0, pool["cost"] * 0.01)
                  and 0 <= imp_gap <= max(5.0, pool["imp"] * 0.15))

            base_dims = {
                "date": day.strftime("%Y.%m.%d."),
                "campaign_type": _campaign_type_label(
                    master, campaign_id, adgroup_id, True),
                "url": _channel_url(master, pool["channel_id"], "-", ""),
                "channel_id": pool["channel_id"] or "-",
                "device": PC_MOBILE_LABELS.get(device_code, device_code),
                "campaign_name": master.campaign_name.get(campaign_id, "-"),
                "adgroup_name": master.adgroup_name.get(adgroup_id, "-"),
                "search_term": "-",
                "search_type": "-",
            }

            if not ok:
                self._warn(
                    f"미해석 키워드 재분배 불가 (그룹 {adgroup_id[-8:]}, "
                    f"{device_code}): AD({pool['imp']:.0f}/{pool['clk']:.0f}/"
                    f"{pool['cost']:.0f}) vs EXP({t_imp:.0f}/{t_clk:.0f}/"
                    f"{t_cost:.0f}) — '-' 행으로 귀속")
                dims = dict(base_dims, keyword="-")
                _accumulate(dims, pool["imp"], pool["clk"], pool["cost"],
                            pool["rank_sum"])
                continue

            # 그룹 평균 노출순위를 노출수 비례로 배분 (검색어별 순위는 미제공)
            rank_avg = pool["rank_sum"] / pool["imp"] if pool["imp"] else 0.0
            for term, imp, clk, cost in terms:
                dims = dict(base_dims, keyword=term)
                _accumulate(dims, imp, clk, cost, rank_avg * imp)
            if imp_gap > 0:
                # EXP에 없는 잔여 노출은 '-' 행으로 (클릭·비용은 이미 배분됨)
                dims = dict(base_dims, keyword="-")
                _accumulate(dims, imp_gap, 0.0, 0.0, rank_avg * imp_gap)
            self._info(
                f"AI 키워드 재분배: 그룹 {adgroup_id[-8:]} {device_code} "
                f"— 검색어 {len(terms)}개 (노출 {pool['imp']:.0f}, 잔여 {imp_gap:.0f})")

    def _dims_for_ad_row(self, row: list[str], master: MasterData,
                         day: date) -> dict:
        campaign_id, adgroup_id = row[2], row[3]
        keyword_id = row[4].strip()
        channel_id = row[6].strip() if len(row) > 6 else ""
        device_code = row[8].strip() if len(row) > 8 else ""

        keyword = master.keyword_text.get(keyword_id, "") if keyword_id not in ("", "-") else ""
        device = PC_MOBILE_LABELS.get(device_code, device_code)

        return {
            "date": day.strftime("%Y.%m.%d."),
            "campaign_type": _campaign_type_label(
                master, campaign_id, adgroup_id, bool(keyword)),
            "url": _channel_url(master, channel_id, keyword_id, device),
            "channel_id": channel_id or "-",
            "device": device,
            "campaign_name": master.campaign_name.get(campaign_id, "-"),
            "adgroup_name": master.adgroup_name.get(adgroup_id, "-"),
            "keyword": keyword or "-",
            "search_term": "-",
            "search_type": "-",
        }

    # ── EXPKEYWORD(검색어 보고서) 기반 집계 — 일로 검증 후 사용 ───────────────
    def _build_search_rows(self, client, master: MasterData, layout: dict,
                           start: date, end: date) -> list[dict]:
        dim_cols = [c for c in layout["columns"] if c in _DIM_COLUMNS]
        agg: dict[tuple, dict] = {}
        day = start
        while day <= end:
            rows = _get_stat_rows(client, "EXPKEYWORD", day,
                                  self.report_timeout_sec, self._info)
            for row in rows:
                # EXPKEYWORD: 0 Date, 1 CustomerID, 2 CampaignID, 3 AdgroupID,
                #   4 SearchKeyword, 5 MediaCode, 6 PCMobileType,
                #   7 SearchKeywordType, 8 Imp, 9 Click, 10 Cost
                if len(row) < 11:
                    continue
                dims = {
                    "date": day.strftime("%Y.%m.%d."),
                    "campaign_type": _campaign_type_label(master, row[2], row[3], True),
                    "url": "-",
                    "channel_id": "-",
                    "device": PC_MOBILE_LABELS.get(row[6].strip(), row[6].strip()),
                    "campaign_name": master.campaign_name.get(row[2], "-"),
                    "adgroup_name": master.adgroup_name.get(row[3], "-"),
                    "keyword": row[4],
                    "search_term": row[4],
                    "search_type": SEARCH_TYPE_LABELS.get(row[7].strip(), row[7].strip()),
                }
                key = tuple(dims[_DIM_COLUMNS[c]] for c in dim_cols)
                slot = agg.setdefault(key, {
                    "dims": dims, "imp": 0.0, "clk": 0.0, "cost": 0.0,
                    "rank_sum": 0.0, "conv": 0.0,
                })
                slot["imp"] += _num(row[8])
                slot["clk"] += _num(row[9])
                slot["cost"] += _num(row[10])
            day += timedelta(days=1)
        return [agg[k] for k in sorted(agg.keys())]

    # ── 일로 ver2(키워드) / ver3(검색어) 전용 집계 ───────────────────────────
    #
    # 실데이터 검증(3계정 × 2026-08-13, 다차원 보고서 원본과 대조)으로 확인된 구조:
    #   AD 보고서의 키워드ID 있는 행  = 등록 키워드 실적(일치 + 일치(유사검색어))
    #   AD 보고서의 키워드ID "-" 행   = 확장 실적(EXPKEYWORD type 1) + 키워드가
    #                                   없는 일치 실적(플레이스 등 비검색 상품)
    #   EXPKEYWORD type 1(확장)은 AD "-" 행과 (캠페인,광고그룹,PC/모바일)
    #   단위로 정확히 일치하며, 잔여분은 전부 플레이스 유형이었다(음수 없음).
    #
    # 상위 앱(index_classifier)의 병합 규칙은
    #   ver2에서 검색유형 == "일치"인 행 + ver3에서 "일치"가 아닌 행
    # 이므로, 위 구조를 그대로 반영하면 합계가 정확히 계정 총액이 된다.
    #
    # 단, 일치(유사검색어) 실적은 API에서 등록 키워드 단위로 분리할 수 없다
    # (EXPKEYWORD는 검색어만 주고 키워드ID가 없음). 그 금액은 이미 AD 키워드
    # 행 안에 포함돼 있으므로, ver3에서 type 2를 내보내면 병합 시 이중 계상이
    # 된다. 따라서 ver3에는 type 2를 넣지 않고, 해당 실적은 등록 키워드 행
    # (검색유형 "일치")에 귀속시킨다 — 총액은 정확하고, 검색어 텍스트 대신
    # 등록 키워드 텍스트로 표기된다는 차이만 남는다(1033536 기준 전체의 1.5%).
    def _build_ilo_rows(self, client, master: MasterData, layout: dict,
                        start: date, end: date, mode: str) -> list[dict]:
        dim_cols = [c for c in layout["columns"] if c in _DIM_COLUMNS]
        agg: dict[tuple, dict] = {}

        def _accumulate(dims: dict, imp: float, clk: float, cost: float,
                        rank_sum: float) -> None:
            key = tuple(dims[_DIM_COLUMNS[c]] for c in dim_cols)
            slot = agg.setdefault(key, {
                "dims": dims, "imp": 0.0, "clk": 0.0, "cost": 0.0,
                "rank_sum": 0.0, "conv": 0.0,
            })
            slot["imp"] += imp
            slot["clk"] += clk
            slot["cost"] += cost
            slot["rank_sum"] += rank_sum

        day = start
        while day <= end:
            if self._stop_requested:
                break
            ad_rows = _get_stat_rows(client, "AD", day,
                                     self.report_timeout_sec, self._info)
            exp_rows = _get_stat_rows(client, "EXPKEYWORD", day,
                                      self.report_timeout_sec, self._info)

            # (캠페인, 광고그룹, PC/모바일) 단위 집계
            dash: dict[tuple, dict] = {}       # AD 키워드ID "-" 행
            group_rank: dict[tuple, list] = {}  # 그룹 평균 노출순위 산출용
            unresolved = 0
            for row in ad_rows:
                if len(row) < 13:
                    continue
                gkey = (row[2], row[3], row[8].strip())
                gr = group_rank.setdefault(gkey, [0.0, 0.0])
                gr[0] += _num(row[9])
                gr[1] += _num(row[12])

                kw_id = row[4].strip()
                if kw_id in ("", "-"):
                    slot = dash.setdefault(gkey, {
                        "imp": 0.0, "clk": 0.0, "cost": 0.0, "rank_sum": 0.0})
                    slot["imp"] += _num(row[9])
                    slot["clk"] += _num(row[10])
                    slot["cost"] += _num(row[11])
                    slot["rank_sum"] += _num(row[12])
                    continue
                if mode != "ilo_keyword":
                    continue
                keyword = master.keyword_text.get(kw_id, "")
                if not keyword:
                    unresolved += 1
                dims = self._ilo_dims(master, day, row[2], row[3],
                                      row[8].strip(), "일치",
                                      keyword or "-")
                _accumulate(dims, _num(row[9]), _num(row[10]),
                            _num(row[11]), _num(row[12]))
            if unresolved:
                self._warn(f"{day}: 마스터에 없는 키워드 {unresolved}행 — '-'로 표기")

            # EXPKEYWORD: (그룹) 확장 합계 + (검색어) 행
            ext_by_group: dict[tuple, dict] = {}
            for row in exp_rows:
                if len(row) < 11:
                    continue
                tp = row[7].strip()
                gkey = (row[2], row[3], row[6].strip())
                if tp == "1":
                    slot = ext_by_group.setdefault(gkey, {
                        "imp": 0.0, "clk": 0.0, "cost": 0.0})
                    slot["imp"] += _num(row[8])
                    slot["clk"] += _num(row[9])
                    slot["cost"] += _num(row[10])
                if mode != "ilo_search":
                    continue
                if tp == "2":
                    # 이중 계상 방지 — 위 docstring 참고 (ver2 키워드 행에 포함됨)
                    continue
                label = "확장" if tp == "1" else "일치"
                gr = group_rank.get(gkey, [0.0, 0.0])
                avg_rank = gr[1] / gr[0] if gr[0] else 0.0
                dims = self._ilo_dims(master, day, row[2], row[3],
                                      row[6].strip(), label, row[4])
                _accumulate(dims, _num(row[8]), _num(row[9]),
                            _num(row[10]), avg_rank * _num(row[8]))

            if mode == "ilo_keyword":
                # AD "-" 행을 확장(EXPKEYWORD type 1)과 잔여 일치로 분리
                for gkey, slot in dash.items():
                    ext = ext_by_group.get(gkey, {"imp": 0.0, "clk": 0.0, "cost": 0.0})
                    avg_rank = slot["rank_sum"] / slot["imp"] if slot["imp"] else 0.0
                    campaign_id, adgroup_id, device_code = gkey
                    if ext["imp"] or ext["clk"] or ext["cost"]:
                        dims = self._ilo_dims(master, day, campaign_id, adgroup_id,
                                              device_code, "확장", "-")
                        _accumulate(dims, ext["imp"], ext["clk"], ext["cost"],
                                    avg_rank * ext["imp"])
                    rem_imp = slot["imp"] - ext["imp"]
                    rem_clk = slot["clk"] - ext["clk"]
                    rem_cost = slot["cost"] - ext["cost"]
                    if rem_imp < -0.001 or rem_clk < -0.001 or rem_cost < -0.001:
                        self._warn(
                            f"{day}: 그룹 {adgroup_id[-8:]} {device_code} 확장 실적이 "
                            f"AD '-' 행보다 큼 (AD {slot['imp']:.0f}/{slot['cost']:.0f} "
                            f"vs EXP {ext['imp']:.0f}/{ext['cost']:.0f}) — 잔여 0 처리")
                        rem_imp = max(rem_imp, 0.0)
                        rem_clk = max(rem_clk, 0.0)
                        rem_cost = max(rem_cost, 0.0)
                    if rem_imp or rem_clk or rem_cost:
                        # 키워드가 없는 일치 실적 (플레이스 등 비검색 상품)
                        dims = self._ilo_dims(master, day, campaign_id, adgroup_id,
                                              device_code, "일치", "-")
                        _accumulate(dims, rem_imp, rem_clk, rem_cost,
                                    avg_rank * rem_imp)
            day += timedelta(days=1)

        return [agg[k] for k in sorted(agg.keys())]

    def _ilo_dims(self, master: MasterData, day: date, campaign_id: str,
                  adgroup_id: str, device_code: str, search_type: str,
                  text: str) -> dict:
        return {
            "date": day.strftime("%Y.%m.%d."),
            "campaign_type": _campaign_type_label(
                master, campaign_id, adgroup_id, text not in ("", "-")),
            "url": "-",
            "channel_id": "-",
            "device": PC_MOBILE_LABELS.get(device_code, device_code),
            "campaign_name": master.campaign_name.get(campaign_id, "-"),
            "adgroup_name": master.adgroup_name.get(adgroup_id, "-"),
            "keyword": text,
            "search_term": text,
            "search_type": search_type,
        }

    # ── CSV 출력 ─────────────────────────────────────────────────────────────
    def _adjust_cost(self, raw_cost: float) -> float:
        if self.cost_vat_mode == "exclude":
            return raw_cost / 1.1
        return raw_cost

    def _write_csv(self, layout: dict, rows: list[dict],
                   start: date, end: date) -> Path:
        columns = layout["columns"]
        s = start.strftime("%Y.%m.%d.")
        e = end.strftime("%Y.%m.%d.")
        title = f"{self.report_name or 'API 보고서'}({s}~{e}),{self.customer_id}"

        tmp = Path(tempfile.mktemp(suffix=".csv"))
        with tmp.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([title])
            writer.writerow(columns)
            for slot in rows:
                writer.writerow(self._render_row(columns, slot))
        return tmp

    def _check_layout_drift(self, layout: dict) -> None:
        """이 계정의 기존(브라우저 시절) raw 파일 헤더와 현재 레이아웃을 비교한다.

        같은 보고서 이름이라도 계정마다 컬럼 구성이 다를 수 있다(실제로
        thlaw_04만 '비즈채널'·'캠페인' 컬럼이 더 있었다). 프리셋이 어긋나면
        상위 앱의 캠페인명 기반 분류가 조용히 '미분류'로 빠지므로, 과거
        산출물이 남아 있으면 헤더를 대조해 경고를 남긴다(동작은 바꾸지 않음).
        """
        try:
            if not self.save_root or not self.account_name:
                return
            from utils.file_manager import _safe_path_part, _safe_filename
            base = (Path(self.save_root)
                    / _safe_path_part(self.brand_name, fallback="브랜드명_미설정")
                    / "Naver")
            if not base.is_dir():
                return
            pattern = f"naver_{_safe_filename(self.account_name)}_raw_*.csv"
            previous = sorted(base.glob(f"*/일별 로우/{pattern}"))
            if not previous:
                return
            with previous[-1].open(encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f)
                next(reader, None)          # 제목 행
                header = next(reader, None)
            if not header:
                return
            if [h.strip() for h in header] != layout["columns"]:
                self._warn(
                    "이전 raw 파일과 컬럼 구성이 다릅니다 — 레이아웃 확인 필요\n"
                    f"  기존({previous[-1].name}): {header}\n"
                    f"  현재({self.layout_name}): {layout['columns']}\n"
                    "  계정의 api_layout 설정을 조정하세요."
                )
        except Exception:
            pass

    def _render_row(self, columns: list[str], slot: dict) -> list[str]:
        dims = slot["dims"]
        imp, clk = slot["imp"], slot["clk"]
        cost = self._adjust_cost(slot["cost"])
        conv = slot["conv"]
        values: list[str] = []
        for col in columns:
            if col in _DIM_COLUMNS:
                values.append(str(dims[_DIM_COLUMNS[col]]))
            elif col == "노출수":
                values.append(_fmt(imp))
            elif col == "클릭수":
                values.append(_fmt(clk))
            elif col == "클릭률(%)":
                values.append(_fmt(clk / imp * 100 if imp else 0, 2))
            elif col == "평균 CPC":
                values.append(_fmt(cost / clk if clk else 0))
            elif col == "총비용":
                values.append(_fmt(cost))
            elif col == "총 전환수":
                values.append(_fmt(conv))
            elif col == "총 전환율(%)":
                values.append(_fmt(conv / clk * 100 if clk else 0, 2))
            elif col == "총 전환당비용(원)":
                values.append(_fmt(cost / conv if conv else 0))
            elif col == "평균노출순위":
                values.append(_fmt(slot["rank_sum"] / imp if imp else 0, 1))
            else:
                values.append("")
        return values

    # ── BaseDownloader 추상 메서드 (API 방식에서는 사용하지 않음) ─────────────
    def check_login(self, page) -> bool:  # pragma: no cover
        return True

    def navigate_to_report(self, page) -> None:  # pragma: no cover
        pass

    def set_period(self, page, start, end) -> None:  # pragma: no cover
        pass

    def trigger_download(self, page, start, end):  # pragma: no cover
        raise RuntimeError("API 다운로더는 브라우저 다운로드를 사용하지 않습니다")
