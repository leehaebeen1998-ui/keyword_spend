from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

from .ai import AIAnalyzer, AIRequest, NullAIAnalyzer
from .columns import normalize_row
from .models import ClassificationResult


RULE_STEPS: tuple[tuple[int, str, str], ...] = (
    (1, "campaign_type_rules", "campaign_type"),
    (2, "group_name_rules", "group_name"),
    (3, "keyword_rules", "keyword_name"),
    (4, "campaign_name_rules", "campaign_name"),
    (5, "url_rules", "url"),
)


@dataclass
class ClassificationEngine:
    index: dict[str, Any]
    ai_analyzer: AIAnalyzer | None = None

    def classify_row(self, row: dict[str, Any]) -> ClassificationResult:
        normalized = normalize_row(row, self.index.get("column_aliases", {}))
        min_confidence = self._min_confidence()

        forced = self._match_forced_url(normalized)
        if forced:
            return self._result(
                category=forced["category"],
                confidence=1.0,
                priority=0,
                rule_id=forced.get("id"),
                source="forced_url_mapping",
                evidence={"field": "url", "value": normalized.get("url"), "url": forced.get("url")},
                normalized=normalized,
                min_confidence=min_confidence,
            )

        best_candidate: dict[str, Any] | None = None
        for priority, rule_key, field in RULE_STEPS:
            match = self._match_rules(rule_key, field, normalized)
            if not match:
                continue
            if best_candidate is None or match["confidence"] > best_candidate["confidence"]:
                best_candidate = {**match, "priority": priority, "source": rule_key}
            if match["confidence"] >= min_confidence:
                return self._result(
                    category=match["category"],
                    confidence=match["confidence"],
                    priority=priority,
                    rule_id=match["id"],
                    source=rule_key,
                    evidence=match["evidence"],
                    normalized=normalized,
                    min_confidence=min_confidence,
                )

        if best_candidate:
            return self._result(
                category=best_candidate["category"],
                confidence=best_candidate["confidence"],
                priority=best_candidate["priority"],
                rule_id=best_candidate["id"],
                source=best_candidate["source"],
                evidence=best_candidate["evidence"],
                normalized=normalized,
                min_confidence=min_confidence,
            )

        if self._ai_enabled():
            analyzer = self.ai_analyzer or NullAIAnalyzer()
            ai_response = analyzer.analyze(
                AIRequest(
                    row=row,
                    normalized_row=normalized,
                    index=self.index,
                    best_candidate=best_candidate,
                )
            )
            if ai_response.category:
                return self._result(
                    category=ai_response.category,
                    confidence=ai_response.confidence,
                    priority=6,
                    rule_id=None,
                    source="ai_fallback",
                    evidence=ai_response.evidence,
                    normalized=normalized,
                    min_confidence=min_confidence,
                )

        return ClassificationResult(
            category=None,
            confidence=0.0,
            matched_priority=None,
            matched_rule_id=None,
            evidence={},
            needs_review=True,
            source="unresolved",
            normalized_row=normalized,
        )

    def classify_rows(self, rows: Iterable[dict[str, Any]]) -> list[ClassificationResult]:
        return [self.classify_row(row) for row in rows]

    def _match_forced_url(self, normalized: dict[str, Any]) -> dict[str, Any] | None:
        value = normalized.get("url")
        if not value:
            return None
        row_url = normalize_url(str(value), include_query=False)

        for mapping in self.index.get("forced_url_mapping", []):
            include_query = bool(mapping.get("include_query", False))
            target_url = normalize_url(str(mapping.get("url", "")), include_query=include_query)
            compare_url = normalize_url(str(value), include_query=include_query)
            if compare_url == target_url or row_url == target_url:
                return mapping
        return None

    def _match_rules(
        self,
        rule_key: str,
        field: str,
        normalized: dict[str, Any],
    ) -> dict[str, Any] | None:
        value = normalized.get(field)
        if value is None or str(value).strip() == "":
            return None

        matches: list[dict[str, Any]] = []
        for rule in self.index.get(rule_key, []):
            if not rule.get("enabled", True):
                continue
            if rule.get("field") != field:
                continue
            if not self._campaign_type_allowed(rule, normalized):
                continue
            pattern = self._first_matching_pattern(str(value), rule)
            if pattern is None:
                continue
            matches.append(
                {
                    "id": rule.get("id"),
                    "category": rule.get("category"),
                    "confidence": float(rule.get("confidence", 0.0)),
                    "evidence": {
                        "field": field,
                        "value": value,
                        "pattern": pattern,
                        "match_type": rule.get("match_type"),
                    },
                }
            )

        if not matches:
            return None
        return max(matches, key=lambda item: item["confidence"])

    def _campaign_type_allowed(self, rule: dict[str, Any], normalized: dict[str, Any]) -> bool:
        filters = rule.get("campaign_type_filter") or []
        if not filters:
            return True
        campaign_type = str(normalized.get("campaign_type", ""))
        return any(casefold_contains(campaign_type, item) for item in filters)

    def _first_matching_pattern(self, value: str, rule: dict[str, Any]) -> str | None:
        match_type = rule.get("match_type", "contains")
        for pattern in rule.get("patterns", []):
            pattern_text = str(pattern)
            if match_type == "exact" and value.casefold() == pattern_text.casefold():
                return pattern_text
            if match_type == "contains" and casefold_contains(value, pattern_text):
                return pattern_text
            if match_type == "regex" and re.search(pattern_text, value, flags=re.IGNORECASE):
                return pattern_text
        return None

    def _min_confidence(self) -> float:
        ai_fallback = self.index.get("ai_fallback", {})
        return float(ai_fallback.get("min_confidence", 0.7))

    def _ai_enabled(self) -> bool:
        ai_fallback = self.index.get("ai_fallback", {})
        return bool(ai_fallback.get("enabled", False))

    def _result(
        self,
        *,
        category: str | None,
        confidence: float,
        priority: int,
        rule_id: str | None,
        source: str,
        evidence: dict[str, Any],
        normalized: dict[str, Any],
        min_confidence: float,
    ) -> ClassificationResult:
        return ClassificationResult(
            category=category,
            confidence=confidence,
            matched_priority=priority,
            matched_rule_id=rule_id,
            evidence=evidence,
            needs_review=confidence < min_confidence,
            source=source,
            normalized_row=normalized,
        )


def classify_row(
    row: dict[str, Any],
    index: dict[str, Any],
    ai_analyzer: AIAnalyzer | None = None,
) -> ClassificationResult:
    return ClassificationEngine(index=index, ai_analyzer=ai_analyzer).classify_row(row)


def classify_rows(
    rows: Iterable[dict[str, Any]],
    index: dict[str, Any],
    ai_analyzer: AIAnalyzer | None = None,
) -> list[ClassificationResult]:
    return ClassificationEngine(index=index, ai_analyzer=ai_analyzer).classify_rows(rows)


def normalize_url(url: str, *, include_query: bool) -> str:
    parsed = urlsplit(url.strip())
    path = parsed.path.rstrip("/") or "/"
    query = parsed.query if include_query else ""
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            query,
            "",
        )
    )


def casefold_contains(value: str, pattern: str) -> bool:
    return pattern.casefold() in value.casefold()
