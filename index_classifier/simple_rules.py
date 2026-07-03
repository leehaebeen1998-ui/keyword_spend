from __future__ import annotations

from pathlib import Path
from typing import Any

from .report_io import read_report_rows


DEFAULT_SIMPLE_COLUMN_ALIASES: dict[str, list[str]] = {
    "priority": ["순위", "뎁스", "depth", "priority"],
    "rule_type": ["규칙", "규칙종류", "기준", "rule", "rule_type"],
    "match_value": ["매칭값", "조건", "값", "내용", "match", "match_value"],
    "category": ["카테고리", "분류", "category"],
    "confidence": ["신뢰도", "confidence"],
    "enabled": ["사용", "활성", "enabled"],
    "memo": ["메모", "비고", "memo"],
}


RULE_TYPE_MAP: dict[str, tuple[int, str, str]] = {
    "강제지정url": (0, "forced_url_mapping", "url"),
    "강제url": (0, "forced_url_mapping", "url"),
    "forcedurl": (0, "forced_url_mapping", "url"),
    "캠페인유형": (1, "campaign_type_rules", "campaign_type"),
    "매체": (1, "campaign_type_rules", "campaign_type"),
    "그룹명": (2, "group_name_rules", "group_name"),
    "광고그룹명": (2, "group_name_rules", "group_name"),
    "키워드명": (3, "keyword_rules", "keyword_name"),
    "키워드": (3, "keyword_rules", "keyword_name"),
    "캠페인명": (4, "campaign_name_rules", "campaign_name"),
    "일반url": (5, "url_rules", "url"),
    "url": (5, "url_rules", "url"),
}

PRIORITY_MAP: dict[int, tuple[str, str]] = {
    1: ("campaign_type_rules", "campaign_type"),
    2: ("group_name_rules", "group_name"),
    3: ("keyword_rules", "keyword_name"),
    4: ("campaign_name_rules", "campaign_name"),
    5: ("url_rules", "url"),
}


def load_simple_rules_index(
    path: str | Path,
    *,
    brand_id: str = "default",
    account_ids: list[str] | None = None,
    ai_fallback: bool = True,
    min_confidence: float = 0.7,
    base_index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = read_report_rows(path)
    return simple_rules_to_index(
        rows,
        brand_id=brand_id,
        account_ids=account_ids,
        ai_fallback=ai_fallback,
        min_confidence=min_confidence,
        base_index=base_index,
    )


def simple_rules_to_index(
    rows: list[dict[str, Any]],
    *,
    brand_id: str = "default",
    account_ids: list[str] | None = None,
    ai_fallback: bool = True,
    min_confidence: float = 0.7,
    base_index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    index = base_index.copy() if base_index else _empty_index(
        brand_id=brand_id,
        account_ids=account_ids or [],
        ai_fallback=ai_fallback,
        min_confidence=min_confidence,
    )

    counters: dict[str, int] = {}
    for row in rows:
        normalized = _normalize_simple_row(row)
        if not _is_enabled(normalized.get("enabled", "O")):
            continue

        category = _clean(normalized.get("category"))
        match_value = _clean(normalized.get("match_value"))
        if not category or not match_value:
            continue

        priority, rule_key, field = _resolve_rule_target(normalized)
        counters[rule_key] = counters.get(rule_key, 0) + 1
        rule_id = f"simple-{rule_key.replace('_rules', '').replace('_mapping', '')}-{counters[rule_key]:03d}"

        if priority == 0:
            index["forced_url_mapping"].append(
                {
                    "id": rule_id,
                    "url": match_value,
                    "category": category,
                    "include_query": False,
                    "memo": _clean(normalized.get("memo")),
                }
            )
            continue

        index[rule_key].append(
            {
                "id": rule_id,
                "field": field,
                "match_type": "contains",
                "patterns": [match_value],
                "category": category,
                "confidence": _confidence(normalized.get("confidence"), default=_default_confidence(priority)),
                "enabled": True,
                "memo": _clean(normalized.get("memo")),
            }
        )

    return index


def _empty_index(
    *,
    brand_id: str,
    account_ids: list[str],
    ai_fallback: bool,
    min_confidence: float,
) -> dict[str, Any]:
    return {
        "index_version": "1.0.0",
        "scope": {
            "brand_id": brand_id,
            "account_ids": account_ids,
        },
        "column_aliases": {},
        "forced_url_mapping": [],
        "campaign_type_rules": [],
        "group_name_rules": [],
        "keyword_rules": [],
        "campaign_name_rules": [],
        "url_rules": [],
        "user_corrections": [],
        "ai_fallback": {
            "enabled": ai_fallback,
            "min_confidence": min_confidence,
            "analyze_fields": [
                "landing_page_text",
                "creative_name",
                "ad_text",
                "page_title",
                "meta_description",
            ],
        },
    }


def _normalize_simple_row(row: dict[str, Any]) -> dict[str, Any]:
    lookup: dict[str, str] = {}
    for field, aliases in DEFAULT_SIMPLE_COLUMN_ALIASES.items():
        lookup[_key(field)] = field
        for alias in aliases:
            lookup[_key(alias)] = field

    normalized: dict[str, Any] = {}
    for key, value in row.items():
        field = lookup.get(_key(key))
        if field:
            normalized[field] = value
    return normalized


def _resolve_rule_target(row: dict[str, Any]) -> tuple[int, str, str]:
    rule_type = _key(row.get("rule_type"))
    if rule_type in RULE_TYPE_MAP:
        return RULE_TYPE_MAP[rule_type]

    priority = int(float(_clean(row.get("priority")) or "5"))
    if priority == 0:
        return (0, "forced_url_mapping", "url")
    if priority not in PRIORITY_MAP:
        raise ValueError(f"Unsupported simple rule priority: {priority}")

    rule_key, field = PRIORITY_MAP[priority]
    return (priority, rule_key, field)


def _confidence(value: Any, *, default: float) -> float:
    text = _clean(value)
    if not text:
        return default
    return float(text)


def _default_confidence(priority: int) -> float:
    return {
        1: 0.8,
        2: 0.9,
        3: 0.9,
        4: 0.8,
        5: 0.65,
    }.get(priority, 0.7)


def _is_enabled(value: Any) -> bool:
    text = _key(value)
    return text not in {"x", "n", "no", "false", "0", "사용안함", "비활성"}


def _key(value: Any) -> str:
    return "".join(str(value or "").strip().lower().replace("-", "").replace("_", "").split())


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
