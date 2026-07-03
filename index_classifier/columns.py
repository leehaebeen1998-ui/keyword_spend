from __future__ import annotations

from typing import Any


DEFAULT_COLUMN_ALIASES: dict[str, list[str]] = {
    "account_id": ["계정 ID", "계정", "account_id", "account"],
    "brand_id": ["브랜드 ID", "브랜드", "brand_id", "brand"],
    "campaign_type": ["캠페인 유형", "매체", "광고상품", "channel"],
    "campaign_name": ["캠페인", "캠페인명", "campaign", "campaign_name"],
    "group_name": ["그룹", "광고그룹", "광고 그룹명", "ad_group", "adset", "ad_set"],
    "keyword_name": ["키워드", "키워드명", "keyword", "keyword_name"],
    "url": ["URL", "랜딩URL", "최종 URL", "landing_url", "final_url"],
    "creative_name": ["소재명", "creative_name", "creative"],
    "ad_text": ["광고 문구", "ad_text", "copy"],
}


def normalize_header(value: str) -> str:
    return "".join(str(value).strip().lower().replace("-", "_").split())


def build_alias_lookup(column_aliases: dict[str, list[str]] | None = None) -> dict[str, str]:
    aliases = dict(DEFAULT_COLUMN_ALIASES)
    for field, values in (column_aliases or {}).items():
        aliases.setdefault(field, [])
        aliases[field] = [*aliases[field], *values]

    lookup: dict[str, str] = {}
    for field, names in aliases.items():
        lookup[normalize_header(field)] = field
        for name in names:
            lookup[normalize_header(name)] = field
    return lookup


def normalize_row(
    row: dict[str, Any],
    column_aliases: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    lookup = build_alias_lookup(column_aliases)
    normalized: dict[str, Any] = {}

    for raw_key, value in row.items():
        field = lookup.get(normalize_header(raw_key))
        if field and field not in normalized:
            normalized[field] = value

    return normalized
