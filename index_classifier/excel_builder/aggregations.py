"""표준화된 행을 Excel 시트별로 집계한다.

pandas 없이 순수 Python으로 구현.

sheet_mode:
  "all"      — SA/DA 통합 시트 + 매체별 개별 시트
  "combined" — SA/DA 통합 시트만 생성
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..standardizer.media_column_mapping import METRIC_COLUMNS

# ---------------------------------------------------------------------------
# 채널 분류
# ---------------------------------------------------------------------------

SA_MEDIA: frozenset[str] = frozenset(
    {"Naver", "Google SA", "Kakao SA", "Naver Powerlink",
     "Naver Shopping Search", "Naver Region", "Google Region"}
)

DA_MEDIA: frozenset[str] = frozenset(
    {"Google DA", "Google Conversion Action", "Meta", "ADN",
     "Mobion", "Mobion Closing Panel", "GFA DB", "GFA Store", "X"}
)

# ---------------------------------------------------------------------------
# 집계 차원 정의 (내부 필드명)
# ---------------------------------------------------------------------------

# 항상 포함되는 고정 차원 (수정 불가)
_FIXED_DIMS: tuple[str, ...] = ("date", "account_name", "media", "category")

# 기본 선택 차원 (사용자가 변경 가능)
_SA_OPTIONAL_DEFAULT: tuple[str, ...] = ("campaign_name", "group_name", "keyword_name")
_DA_OPTIONAL_DEFAULT: tuple[str, ...] = ("campaign_name", "group_name", "creative_name")

# 선택 가능한 전체 차원 목록 (UI 노출용, 순서대로)
SA_OPTIONAL_ALL: tuple[tuple[str, str], ...] = (
    ("campaign_type",  "광고유형"),
    ("campaign_name",  "캠페인"),
    ("group_name",     "그룹"),
    ("region",         "지역"),
    ("device",         "기기"),
    ("keyword_name",   "키워드"),
)
DA_OPTIONAL_ALL: tuple[tuple[str, str], ...] = (
    ("campaign_type",  "광고유형"),
    ("campaign_name",  "캠페인"),
    ("group_name",     "그룹"),
    ("creative_name",  "소재"),
    ("region",         "지역"),
    ("device",         "기기"),
    ("keyword_name",   "키워드"),
)

# 하위 호환용 상수
SA_KW_DIMS = _FIXED_DIMS + _SA_OPTIONAL_DEFAULT
DA_KW_DIMS = _FIXED_DIMS + _DA_OPTIONAL_DEFAULT

# ---------------------------------------------------------------------------
# 한글 컬럼명 매핑
# ---------------------------------------------------------------------------

_DIM_KR: dict[str, str] = {
    "date":           "일자",
    "account_name":   "계정명",
    "media":          "매체",
    "category":       "카테고리",
    "campaign_type":  "광고유형",
    "campaign_name":  "캠페인",
    "group_name":     "그룹",
    "creative_name":  "소재",
    "keyword_name":   "키워드",
    "url":            "URL",
    "device":         "기기",
    "region":         "지역",
    "channel_type":   "채널유형",
}

_METRIC_KR: dict[str, str] = {
    "impressions":                      "노출수",
    "clicks":                           "클릭수",
    "cost":                             "비용",
    "conversion_count":                 "전환수",
    "purchase_conversion_count":        "구매전환수",
    "purchase_conversion_revenue":      "구매전환액",
    "general_inquiry_conversion_count": "문의전환수",
    "phone_conversion_count":           "전화전환수",
    "kakao_conversion_count":           "카카오전환수",
    "channel_talk_conversion_count":    "채팅전환수",
    "db_conversion_count":              "DB전환수",
    "session_revenue":                  "세션수익",
    "direct_revenue":                   "직접수익",
    "total_revenue":                    "총수익",
    "video_views":                      "동영상조회수",
    "ctr":                              "CTR",
    "cpc":                              "CPC",
    "cpa":                              "CPA",
    "roas":                             "ROAS",
    "conversion_rate":                  "전환율",
    "cost_per_conversion":              "전환당비용",
}

# 숫자/비율 컬럼명 (한글) — workbook_builder에서 참조
NUMBER_COLS_KR = {"노출수", "클릭수", "비용", "전환수", "구매전환수", "구매전환액",
                  "문의전환수", "전화전환수", "카카오전환수", "채팅전환수", "DB전환수",
                  "세션수익", "직접수익", "총수익", "동영상조회수",
                  "행수", "미분류_행수", "미매핑_컬럼수"}
RATE_COLS_KR = {"CTR", "CPC", "CPA", "ROAS", "전환율", "전환당비용"}

# Failed Rows 출력 컬럼
FAILED_ROWS_COLUMNS: tuple[str, ...] = (
    "source_row_number", "date", "account_name", "media", "channel_type",
    "campaign_type", "campaign_name", "group_name", "keyword_name",
    "creative_name", "url", "category", "reason", "suggested_action", "source_file",
)

# Unmapped Columns 출력 컬럼
UNMAPPED_COLUMNS_COLUMNS: tuple[str, ...] = (
    "media", "source_column", "sample_values", "decision", "suggested_target",
)


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def aggregate_sheets(
    standard_rows: list[dict[str, Any]],
    failed_rows: list[dict[str, Any]],
    unmapped_rows: list[dict[str, Any]],
    index_log_entries: list[dict[str, Any]],
    *,
    sheet_mode: str = "all",
    sa_optional_dims: tuple[str, ...] | None = None,
    da_optional_dims: tuple[str, ...] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """표준 행을 시트별로 분리/집계한다.

    Args:
        sheet_mode: "all" = 통합+개별, "combined" = 통합만
        sa_optional_dims: SA 선택 차원 (None이면 기본값 사용)
        da_optional_dims: DA 선택 차원 (None이면 기본값 사용)
    Returns:
        {sheet_name: [row_dict, ...]}
    """
    eff_sa_dims = _FIXED_DIMS + (sa_optional_dims if sa_optional_dims is not None else _SA_OPTIONAL_DEFAULT)
    eff_da_dims = _FIXED_DIMS + (da_optional_dims if da_optional_dims is not None else _DA_OPTIONAL_DEFAULT)

    sa_rows = [r for r in standard_rows if r.get("channel_type") == "SA"]
    da_rows = [r for r in standard_rows if r.get("channel_type") in ("DA", "GA4")]

    sheets: dict[str, list[dict[str, Any]]] = {}

    # ── SA 통합 (항상 생성) ──
    sheets["SA 통합"] = _mark_type(_aggregate_kr(sa_rows, eff_sa_dims), "SA")

    # ── SA 매체별 개별 시트 ──
    if sheet_mode == "all":
        for media in _media_list(sa_rows):
            m_rows = [r for r in sa_rows if str(r.get("media", "")) == media]
            sheets[_safe_sheet_name(media)] = _mark_type(_aggregate_kr(m_rows, eff_sa_dims), "SA")

    # ── DA 통합 ──
    if da_rows:
        sheets["DA 통합"] = _mark_type(_aggregate_kr(da_rows, eff_da_dims), "DA")

        if sheet_mode == "all":
            for media in _media_list(da_rows):
                m_rows = [r for r in da_rows if str(r.get("media", "")) == media]
                sheet_name = _safe_sheet_name(media)
                if sheet_name not in sheets:  # SA와 이름 충돌 방지
                    sheets[sheet_name] = _mark_type(_aggregate_kr(m_rows, eff_da_dims), "DA")

    sheets["90_Failed_Rows"] = _build_failed_rows_sheet(failed_rows)
    sheets["91_Unmapped_Columns"] = unmapped_rows
    sheets["99_Index_Log"] = index_log_entries

    # 요약은 마지막에
    sheets["00_요약"] = _build_summary(sheets, standard_rows, failed_rows, unmapped_rows)

    return sheets


# ---------------------------------------------------------------------------
# 내부 유틸
# ---------------------------------------------------------------------------

def _mark_type(rows: list[dict[str, Any]], sheet_type: str) -> list[dict[str, Any]]:
    """각 행에 __sheet_type__ 마커를 추가한다 (workbook_builder SA/DA 판별용)."""
    for r in rows:
        r["__sheet_type__"] = sheet_type
    return rows


def _media_list(rows: list[dict[str, Any]]) -> list[str]:
    """rows에서 매체명 목록을 정렬하여 반환."""
    return sorted({str(r.get("media", "")) for r in rows if r.get("media")})


def _safe_sheet_name(name: str) -> str:
    """Excel 시트명: 31자 이내, 금지 문자 제거."""
    for ch in r'\/:*?[]':
        name = name.replace(ch, "")
    return name[:31]


def _aggregate_kr(
    rows: list[dict[str, Any]],
    dim_cols: tuple[str, ...],
) -> list[dict[str, Any]]:
    """dim_cols 기준으로 지표 합산 → 한글 컬럼명 딕셔너리 반환."""
    grouped: dict[tuple, dict[str, Any]] = defaultdict(lambda: defaultdict(float))

    for row in rows:
        key = tuple(str(row.get(c) or "") for c in dim_cols)
        group = grouped[key]

        if not group.get("__dims_set__"):
            for col in dim_cols:
                group[col] = row.get(col, "")
            group["__dims_set__"] = True

        for metric in METRIC_COLUMNS:
            val = row.get(metric)
            if val not in (None, "", 0):
                group[metric] += _to_float(val)

    result: list[dict[str, Any]] = []
    for group in grouped.values():
        # 한글 dim 컬럼
        row_out: dict[str, Any] = {}
        for col in dim_cols:
            kr = _DIM_KR.get(col, col)
            row_out[kr] = group.get(col, "")
        # 한글 지표 컬럼 (0인 것도 포함)
        for metric in METRIC_COLUMNS:
            kr = _METRIC_KR.get(metric, metric)
            row_out[kr] = group.get(metric, 0) or 0
        _add_derived_metrics_kr(row_out)
        result.append(row_out)

    # 정렬: 일자 → 계정명 → 매체
    result.sort(key=lambda r: (
        str(r.get("일자") or ""),
        str(r.get("계정명") or ""),
        str(r.get("매체") or ""),
    ))
    return result


def _add_derived_metrics_kr(row: dict[str, Any]) -> None:
    """CTR, CPC, CPA, ROAS 재계산 (한글 키)."""
    impressions = _to_float(row.get("노출수"))
    clicks      = _to_float(row.get("클릭수"))
    cost        = _to_float(row.get("비용"))
    conversions = _to_float(row.get("전환수"))
    revenue     = (
        _to_float(row.get("구매전환액"))
        or _to_float(row.get("총수익"))
        or _to_float(row.get("세션수익"))
        or _to_float(row.get("직접수익"))
    )

    row["CTR"]    = _safe_div(clicks, impressions)
    row["CPC"]    = _safe_div(cost, clicks)
    row["CPA"]    = _safe_div(cost, conversions)
    row["ROAS"]   = (round(_safe_div(revenue, cost) * 100, 2)  # type: ignore[operator]
                     if cost and isinstance(_safe_div(revenue, cost), float) else "")
    row["전환율"] = _safe_div(conversions, clicks)


def _build_failed_rows_sheet(
    failed_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in failed_rows:
        out: dict[str, Any] = {col: row.get(col, "") for col in FAILED_ROWS_COLUMNS}
        if not out.get("reason"):
            out["reason"] = "인덱스 분류 실패 (unresolved)"
        if not out.get("suggested_action"):
            out["suggested_action"] = "룰 테이블에 키워드/캠페인명 규칙 추가 검토"
        result.append(out)
    return result


def _build_summary(
    sheets: dict[str, list[dict[str, Any]]],
    standard_rows: list[dict[str, Any]],
    failed_rows: list[dict[str, Any]],
    unmapped_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []

    # 카테고리별
    by_cat: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in standard_rows:
        cat = str(row.get("category") or "미분류")
        by_cat[cat]["노출수"] += _to_float(row.get("impressions"))
        by_cat[cat]["클릭수"] += _to_float(row.get("clicks"))
        by_cat[cat]["비용"]   += _to_float(row.get("cost"))
        by_cat[cat]["전환수"] += _to_float(row.get("conversion_count"))
        by_cat[cat]["행수"]   += 1

    for cat, m in sorted(by_cat.items()):
        row_out: dict[str, Any] = {"구분": "카테고리", "항목": cat, **{k: m[k] for k in m}}
        _add_summary_derived(row_out)
        summary.append(row_out)

    # 매체별
    by_media: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in standard_rows:
        med = str(row.get("media") or "unknown")
        by_media[med]["노출수"] += _to_float(row.get("impressions"))
        by_media[med]["클릭수"] += _to_float(row.get("clicks"))
        by_media[med]["비용"]   += _to_float(row.get("cost"))
        by_media[med]["전환수"] += _to_float(row.get("conversion_count"))
        by_media[med]["행수"]   += 1

    for med, m in sorted(by_media.items()):
        row_out = {"구분": "매체", "항목": med, **{k: m[k] for k in m}}
        _add_summary_derived(row_out)
        summary.append(row_out)

    # 전체
    summary.append({
        "구분": "전체", "항목": "전체",
        "노출수": sum(_to_float(r.get("impressions")) for r in standard_rows),
        "클릭수": sum(_to_float(r.get("clicks")) for r in standard_rows),
        "비용":   sum(_to_float(r.get("cost")) for r in standard_rows),
        "전환수": sum(_to_float(r.get("conversion_count")) for r in standard_rows),
        "행수": len(standard_rows),
        "미분류_행수": len(failed_rows),
        "미매핑_컬럼수": len(unmapped_rows),
    })
    return summary


def _add_summary_derived(row: dict[str, Any]) -> None:
    clicks      = _to_float(row.get("클릭수"))
    impressions = _to_float(row.get("노출수"))
    cost        = _to_float(row.get("비용"))
    conversions = _to_float(row.get("전환수"))
    row["CTR"] = _safe_div(clicks, impressions)
    row["CPC"] = _safe_div(cost, clicks)
    row["CPA"] = _safe_div(cost, conversions)


def _to_float(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


def _safe_div(numerator: Any, denominator: Any) -> float | str:
    n = _to_float(numerator)
    d = _to_float(denominator)
    if d == 0:
        return ""
    return round(n / d, 6)
