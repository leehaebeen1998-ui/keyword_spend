from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .ai import AIAnalyzer
from .classifier import ClassificationEngine
from .store import load_index
from .report_io import read_report_rows, write_csv_rows, write_text


CLASSIFICATION_FIELDS: tuple[str, ...] = (
    "classification_confidence",
    "classification_priority",
    "classification_rule_id",
    "classification_source",
    "classification_needs_review",
)

DEFAULT_OUTPUT_FIELDS: tuple[str, ...] = (
    "date",
    "media",
    "campaign_type",
    "campaign_name",
    "group_name",
    "creative_name",
    "device",
    "ad_type",
    "keyword_name",
    "url",
    "category",
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
    "conversion_rate",
    "cost_per_conversion",
    "account_id",
    "brand_id",
    "ad_text",
    "source_file",
    *CLASSIFICATION_FIELDS,
)


@dataclass(frozen=True)
class CleaningConfig:
    output_fields: tuple[str, ...] = DEFAULT_OUTPUT_FIELDS
    failed_rows_include_review: bool = True
    output_encoding: str = "utf-8-sig"
    xlsx_sheet_name: str | None = None
    log_indent: int = 2

    @staticmethod
    def default_output_path(input_path: str | Path) -> Path:
        path = Path(input_path)
        return path.with_name(f"{path.stem}.cleaned.csv")

    @staticmethod
    def default_failed_path(input_path: str | Path) -> Path:
        path = Path(input_path)
        return path.with_name(f"{path.stem}.failed.csv")

    @staticmethod
    def default_log_path(input_path: str | Path) -> Path:
        path = Path(input_path)
        return path.with_name(f"{path.stem}.index-log.json")


@dataclass(frozen=True)
class ReportCleanResult:
    original_report_path: Path
    cleaned_report_path: Path
    failed_rows_path: Path
    index_log_path: Path
    total_rows: int
    cleaned_rows: int
    failed_rows: int
    applied_index_scope: dict[str, Any]


@dataclass
class ReportRowCleaner:
    index: dict[str, Any]
    config: CleaningConfig = CleaningConfig()
    ai_analyzer: AIAnalyzer | None = None

    def clean_file(
        self,
        input_path: str | Path,
        *,
        cleaned_path: str | Path | None = None,
        failed_path: str | Path | None = None,
        log_path: str | Path | None = None,
    ) -> ReportCleanResult:
        source_path = Path(input_path)
        cleaned_output = Path(cleaned_path) if cleaned_path else self.config.default_output_path(source_path)
        failed_output = Path(failed_path) if failed_path else self.config.default_failed_path(source_path)
        log_output = Path(log_path) if log_path else self.config.default_log_path(source_path)

        raw_rows = read_report_rows(source_path, sheet_name=self.config.xlsx_sheet_name)
        engine = ClassificationEngine(index=self.index, ai_analyzer=self.ai_analyzer)

        cleaned_rows: list[dict[str, Any]] = []
        failed_rows: list[dict[str, Any]] = []
        log_entries: list[dict[str, Any]] = []

        for row_number, raw_row in enumerate(raw_rows, start=2):
            result = engine.classify_row(raw_row)
            cleaned_row = self._build_cleaned_row(result.normalized_row, result.to_dict())
            cleaned_rows.append(cleaned_row)

            failed = result.category is None
            if self.config.failed_rows_include_review:
                failed = failed or result.needs_review
            if failed:
                failed_rows.append({"source_row_number": row_number, **cleaned_row})

            log_entries.append(
                {
                    "source_row_number": row_number,
                    "category": result.category,
                    "confidence": result.confidence,
                    "matched_priority": result.matched_priority,
                    "matched_rule_id": result.matched_rule_id,
                    "source": result.source,
                    "needs_review": result.needs_review,
                    "evidence": result.evidence,
                }
            )

        fieldnames = list(self.config.output_fields)
        write_csv_rows(
            cleaned_output,
            cleaned_rows,
            fieldnames=fieldnames,
            encoding=self.config.output_encoding,
        )
        write_csv_rows(
            failed_output,
            failed_rows,
            fieldnames=["source_row_number", *fieldnames],
            encoding=self.config.output_encoding,
        )
        self._write_index_log(
            log_output,
            source_path=source_path,
            cleaned_path=cleaned_output,
            failed_path=failed_output,
            total_rows=len(raw_rows),
            failed_rows=len(failed_rows),
            entries=log_entries,
        )

        return ReportCleanResult(
            original_report_path=source_path,
            cleaned_report_path=cleaned_output,
            failed_rows_path=failed_output,
            index_log_path=log_output,
            total_rows=len(raw_rows),
            cleaned_rows=len(cleaned_rows),
            failed_rows=len(failed_rows),
            applied_index_scope=self.index.get("scope", {}),
        )

    def _build_cleaned_row(
        self,
        normalized_row: dict[str, Any],
        classification: dict[str, Any],
    ) -> dict[str, Any]:
        row = {field: normalized_row.get(field, "") for field in self.config.output_fields}
        row.update(
            {
                "category": classification["category"] or "",
                "classification_confidence": classification["confidence"],
                "classification_priority": classification["matched_priority"] if classification["matched_priority"] is not None else "",
                "classification_rule_id": classification["matched_rule_id"] or "",
                "classification_source": classification["source"],
                "classification_needs_review": classification["needs_review"],
            }
        )
        return row

    def _write_index_log(
        self,
        path: str | Path,
        *,
        source_path: Path,
        cleaned_path: Path,
        failed_path: Path,
        total_rows: int,
        failed_rows: int,
        entries: list[dict[str, Any]],
    ) -> None:
        log_path = Path(path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "source_report_path": str(source_path),
            "cleaned_report_path": str(cleaned_path),
            "failed_rows_path": str(failed_path),
            "total_rows": total_rows,
            "failed_rows": failed_rows,
            "applied_index_scope": self.index.get("scope", {}),
            "applied_index_version": self.index.get("index_version"),
            "entries": entries,
        }
        write_text(
            log_path,
            f"{json.dumps(payload, ensure_ascii=False, indent=self.config.log_indent)}\n",
            encoding="utf-8",
        )


def clean_report_file(
    input_path: str | Path,
    index_path: str | Path,
    *,
    cleaned_path: str | Path | None = None,
    failed_path: str | Path | None = None,
    log_path: str | Path | None = None,
    config: CleaningConfig | None = None,
    ai_analyzer: AIAnalyzer | None = None,
) -> ReportCleanResult:
    index = load_index(index_path)
    return ReportRowCleaner(
        index=index,
        config=config or CleaningConfig(),
        ai_analyzer=ai_analyzer,
    ).clean_file(
        input_path,
        cleaned_path=cleaned_path,
        failed_path=failed_path,
        log_path=log_path,
    )
