from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ClassificationResult:
    category: str | None
    confidence: float
    matched_priority: int | None
    matched_rule_id: str | None
    evidence: dict[str, Any] = field(default_factory=dict)
    needs_review: bool = True
    source: str = "unresolved"
    normalized_row: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "confidence": self.confidence,
            "matched_priority": self.matched_priority,
            "matched_rule_id": self.matched_rule_id,
            "evidence": self.evidence,
            "needs_review": self.needs_review,
            "source": self.source,
            "normalized_row": self.normalized_row,
        }
