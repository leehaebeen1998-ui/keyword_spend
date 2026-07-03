"""매체별 컬럼 매핑 로더.

media-column-mapping.csv를 읽어 두 가지 매핑을 제공한다:
  1. column_map   : 원본 컬럼명 → 표준 컬럼명 (매체별)
  2. event_map    : GA4 이벤트 이름 값 → 표준 지표 컬럼 (GA4 전용)
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

# 기본 매핑 파일 위치 (examples 폴더의 예시 CSV)
_DEFAULT_MAPPING_PATH = (
    Path(__file__).parent.parent.parent / "examples" / "media-column-mapping.example.csv"
)

# 매체명 별칭 → 표준 매체명 (소문자/underscore 변형 → 정규 매체명)
_MEDIA_NAME_ALIASES: dict[str, str] = {
    "naver": "Naver",
    "naver_sa": "Naver",
    "naver_powerlink": "Naver Powerlink",
    "naver_shopping_search": "Naver Shopping Search",
    "naver_region": "Naver Region",
    "google_sa": "Google SA",
    "google_da": "Google DA",
    "google_conversion_action": "Google Conversion Action",
    "google_region": "Google Region",
    "kakao": "Kakao SA",
    "kakao_sa": "Kakao SA",
    "meta": "Meta",
    "mobion": "Mobion",
    "mobion_closing_panel": "Mobion Closing Panel",
    "ga4": "GA4",
    "adn": "ADN",
    "gfa_db": "GFA DB",
    "gfa_store": "GFA Store",
    "x": "X",
}


def canonical_media(media: str) -> str:
    """매체명을 표준 매체명으로 정규화.

    "google_sa" → "Google SA", "kakao" → "Kakao SA" 등
    이미 표준 매체명인 경우 그대로 반환.
    """
    # 1) 정확히 일치하는 alias가 있으면 반환
    normalized_key = media.lower().replace(" ", "_").replace("-", "_")
    if normalized_key in _MEDIA_NAME_ALIASES:
        return _MEDIA_NAME_ALIASES[normalized_key]
    # 2) 원래 값 그대로
    return media


# 매체별 SA/DA 채널 구분
_CHANNEL_TYPE_MAP: dict[str, str] = {
    "Naver": "SA",
    "Naver Powerlink": "SA",
    "Naver Shopping Search": "SA",
    "Naver Region": "SA",
    "Google SA": "SA",
    "Google Region": "SA",
    "Kakao SA": "SA",
    "Google DA": "DA",
    "Google Conversion Action": "DA",
    "Meta": "DA",
    "ADN": "DA",
    "Mobion": "DA",
    "Mobion Closing Panel": "DA",
    "GFA DB": "DA",
    "GFA Store": "DA",
    "X": "DA",
    "GA4": "GA4",
}

# GA4 원본 컬럼명 집합 (이 값만 column_map에 넣고 나머지는 event_map으로 분류)
_GA4_RAW_COLUMNS: frozenset[str] = frozenset(
    {
        "날짜",
        "수동 소스/매체",
        "수동 광고 콘텐츠",
        "수동 검색어",
        "이벤트 이름",
        "활성 사용자",
        "date",
        "media",
        "creative_name",
        "keyword_name",
        "conversion_event_name",
        "conversion_event_value",
    }
)

# 공통 지표 컬럼 집합 (집계 시 합산 대상)
METRIC_COLUMNS: frozenset[str] = frozenset(
    {
        "impressions",
        "clicks",
        "cost",
        "conversion_count",
        "purchase_conversion_count",
        "purchase_conversion_revenue",
        "general_inquiry_conversion_count",
        "phone_conversion_count",
        "kakao_conversion_count",
        "channel_talk_conversion_count",
        "youtube_subscribe_conversion_count",
        "db_conversion_count",
        "session_revenue",
        "direct_revenue",
        "total_revenue",
        "video_views",
    }
)

# 재계산 지표 컬럼 집합 (합산 후 재계산)
DERIVED_METRIC_COLUMNS: frozenset[str] = frozenset(
    {
        "ctr",
        "cpc",
        "cpa",
        "roas",
        "conversion_rate",
        "cost_per_conversion",
    }
)

# 표준 차원 컬럼 목록 (순서 유지용)
DIMENSION_COLUMNS: tuple[str, ...] = (
    "date",
    "account_name",
    "account_id",
    "brand_id",
    "media",
    "channel_type",
    "report_type",
    "campaign_type",
    "campaign_name",
    "group_name",
    "keyword_name",
    "creative_name",
    "ad_text",
    "url",
    "device",
    "ad_type",
    "region",
    "city",
    "source_file",
)

# 전체 표준 출력 컬럼 (차원 + 지표 + 분류 결과)
ALL_OUTPUT_COLUMNS: tuple[str, ...] = (
    *DIMENSION_COLUMNS,
    *sorted(METRIC_COLUMNS),
    "category",
    "classification_confidence",
    "classification_priority",
    "classification_rule_id",
    "classification_source",
    "classification_needs_review",
)


class MediaColumnMapping:
    """매체별 컬럼 매핑 테이블.

    Attributes:
        column_map  : {media: {source_col: target_col}}
        event_map   : {media: {event_value: target_metric_col}}
        decisions   : {(media, source_col): "map"|"ignore"|"review"}
    """

    def __init__(
        self,
        column_map: dict[str, dict[str, str]],
        event_map: dict[str, dict[str, str]],
        decisions: dict[tuple[str, str], str] | None = None,
    ) -> None:
        self.column_map = column_map
        self.event_map = event_map
        self.decisions = decisions or {}

    def get_target(self, media: str, source_column: str) -> str | None:
        """source_column → target_column 반환. 없으면 None."""
        return self.column_map.get(canonical_media(media), {}).get(source_column)

    def get_event_target(self, media: str, event_value: str) -> str | None:
        """GA4 이벤트 이름 값 → 지표 컬럼 반환. 없으면 None."""
        return self.event_map.get(canonical_media(media), {}).get(event_value)

    def channel_type(self, media: str) -> str | None:
        """매체명 → "SA" | "DA" | "GA4" | None."""
        return _CHANNEL_TYPE_MAP.get(canonical_media(media))

    def list_expected_columns(self, media: str) -> list[str]:
        """매체의 예상 원본 컬럼 목록."""
        return list(self.column_map.get(canonical_media(media), {}).keys())

    def find_unmapped(self, media: str, raw_columns: list[str]) -> list[str]:
        """raw_columns 중 매핑 없는 컬럼 목록 반환."""
        mapped = set(self.column_map.get(canonical_media(media), {}).keys())
        return [col for col in raw_columns if col not in mapped]

    def decision_for(self, media: str, source_column: str) -> str | None:
        """unmapped-column-decisions의 처리 결정값 반환."""
        return self.decisions.get((canonical_media(media), source_column))


def load_mapping_from_csv(
    mapping_path: str | Path,
    decisions_path: str | Path | None = None,
) -> MediaColumnMapping:
    """media-column-mapping.csv + (선택) unmapped-column-decisions.csv를 로드."""
    column_map: dict[str, dict[str, str]] = {}
    event_map: dict[str, dict[str, str]] = {}

    path = Path(mapping_path)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            media = (row.get("media") or "").strip()
            source = (row.get("source_column") or "").strip()
            target = (row.get("target_column") or "").strip()
            if not media or not source or not target:
                continue

            # GA4 이벤트 값 매핑 판별
            if media == "GA4" and source not in _GA4_RAW_COLUMNS:
                event_map.setdefault(media, {})[source] = target
            else:
                column_map.setdefault(media, {})[source] = target

    # unmapped column decisions (선택)
    decisions: dict[tuple[str, str], str] = {}
    if decisions_path:
        dp = Path(decisions_path)
        with dp.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                media = (row.get("media") or "").strip()
                source = (row.get("source_column") or "").strip()
                decision = (row.get("decision") or "review").strip()
                if media and source:
                    decisions[(canonical_media(media), source)] = decision

    return MediaColumnMapping(
        column_map=column_map,
        event_map=event_map,
        decisions=decisions,
    )


def load_default_mapping(
    mapping_path: str | Path | None = None,
    decisions_path: str | Path | None = None,
) -> MediaColumnMapping:
    """기본 경로에서 매핑 로드. 파일이 없으면 빈 매핑 반환."""
    path = Path(mapping_path) if mapping_path else _DEFAULT_MAPPING_PATH
    if not path.exists():
        return MediaColumnMapping(column_map={}, event_map={}, decisions={})
    return load_mapping_from_csv(path, decisions_path=decisions_path)
