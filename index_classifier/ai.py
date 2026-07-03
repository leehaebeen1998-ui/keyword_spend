from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class AIRequest:
    row: dict[str, Any]
    normalized_row: dict[str, Any]
    index: dict[str, Any]
    best_candidate: dict[str, Any] | None = None


@dataclass(frozen=True)
class AIResponse:
    category: str | None
    confidence: float = 0.0
    evidence: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None


class AIAnalyzer(Protocol):
    def analyze(self, request: AIRequest) -> AIResponse:
        """Return an AI classification result for unresolved or low-confidence rows."""


class NullAIAnalyzer:
    def analyze(self, request: AIRequest) -> AIResponse:
        return AIResponse(
            category=None,
            confidence=0.0,
            evidence={},
            reason="AI analyzer is not configured.",
        )
