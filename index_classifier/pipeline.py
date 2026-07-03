"""통합 후처리 파이프라인.

report-downloader에서 다운로드된 파일 목록을 받아
Raw 표준화 → 인덱스 분류 → Excel 리포트 생성까지 수행한다.

사용 예:
    from index_classifier.pipeline import run_report_pipeline
    from index_classifier.adapters import PipelineInput

    result = run_report_pipeline(
        inputs=pipeline_inputs,
        rule_table_path="config/simple-index-rules.csv",
        output_dir="output/20260630",
    )
    print(result.excel_path)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .adapters.downloader_result_adapter import PipelineInput
from .classifier import ClassificationEngine
from .excel_builder.aggregations import aggregate_sheets
from .excel_builder.workbook_builder import build_workbook
from .excel_builder.raw_builder import build_raw_excel
from .simple_rules import load_simple_rules_index
from .unmapped_decisions import append_new_unmapped
from .standardizer.media_column_mapping import load_default_mapping
from .standardizer.raw_standardizer import StandardizedFile, standardize_file, annotate_file

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 결과 데이터클래스
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    """run_report_pipeline() 실행 결과."""
    excel_path: Path | None
    raw_excel_path: Path | None
    index_log_path: Path | None
    run_log_path: Path | None
    total_input_files: int = 0
    total_standard_rows: int = 0
    total_cleaned_rows: int = 0
    total_failed_rows: int = 0
    total_unmapped_columns: int = 0
    pipeline_errors: list[dict[str, Any]] = field(default_factory=list)
    category_summary: dict[str, int] = field(default_factory=dict)
    media_summary: dict[str, int] = field(default_factory=dict)
    annotated_files: list[Path] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------

def run_report_pipeline(
    inputs: list[PipelineInput],
    rule_table_path: str | Path,
    output_dir: str | Path,
    *,
    run_date: str | None = None,
    excel_filename: str | None = None,
    mapping_path: str | Path | None = None,
    decisions_path: str | Path | None = None,
    postprocess_enabled: bool = True,
    sheet_mode: str = "all",
    sa_optional_dims: tuple[str, ...] | None = None,
    da_optional_dims: tuple[str, ...] | None = None,
) -> PipelineResult:
    """보고서 후처리 파이프라인 실행.

    Args:
        inputs           : PipelineInput 목록 (adapt_download_results로 변환 후 전달)
        rule_table_path  : simple-index-rules.csv 경로
        output_dir       : 결과 파일 저장 디렉터리
        run_date         : 실행 날짜 (파일명 suffix용, 기본값: 오늘)
        excel_filename   : Excel 파일명 (기본값: 통합_광고리포트_{run_date}.xlsx)
        mapping_path     : media-column-mapping.csv 경로 (없으면 기본 예시 사용)
        decisions_path   : unmapped-column-decisions.csv 경로 (선택)
        postprocess_enabled: False이면 즉시 빈 결과 반환

    Returns:
        PipelineResult
    """
    if not postprocess_enabled:
        logger.info("[pipeline] postprocess_enabled=False — 후처리 건너뜀")
        return PipelineResult(excel_path=None, index_log_path=None, run_log_path=None)

    if not inputs:
        logger.warning("[pipeline] inputs가 비어 있음 — 후처리할 파일 없음")
        return PipelineResult(excel_path=None, index_log_path=None, run_log_path=None)

    run_date = run_date or datetime.now().strftime("%Y%m%d")
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 설정 검증
    rule_path = Path(rule_table_path)
    if not rule_path.exists():
        raise FileNotFoundError(
            f"rule_table_path 파일을 찾을 수 없습니다: {rule_path}\n"
            "config.json의 rule_table_path 설정을 확인해 주세요."
        )

    logger.info("[pipeline] 파이프라인 시작 — 입력 파일 수: %d", len(inputs))

    # 매핑 로드
    mapping = load_default_mapping(mapping_path, decisions_path)

    # 인덱스 로드
    index = load_simple_rules_index(str(rule_path))
    engine = ClassificationEngine(index=index)

    # 로드된 규칙 진단 출력
    ct_rules = index.get("campaign_type_rules", [])
    print(f"[인덱스] 캠페인유형 규칙 {len(ct_rules)}개 로드됨:")
    for r in ct_rules:
        print(f"  패턴={r.get('patterns')} → {r.get('category')} (신뢰도={r.get('confidence')}, 활성={r.get('enabled')})")

    # ---------------------------------------------------------------------------
    # Phase 1: Raw 표준화
    # ---------------------------------------------------------------------------
    all_standard_rows: list[dict[str, Any]] = []
    all_unmapped: list[dict[str, Any]] = []
    pipeline_errors: list[dict[str, Any]] = []

    for pipeline_input in inputs:
        try:
            std_file = standardize_file(
                pipeline_input.file_path,
                media=pipeline_input.media,
                report_type=pipeline_input.report_type,
                account_name=pipeline_input.account_name,
                account_id=pipeline_input.account_id,
                brand_id=pipeline_input.brand_id,
                start_date=pipeline_input.start_date,
                end_date=pipeline_input.end_date,
                mapping=mapping,
                xlsx_sheet_name=pipeline_input.xlsx_sheet_name,
            )
            if std_file.error:
                logger.error("[pipeline] 표준화 실패: %s — %s", pipeline_input.file_path, std_file.error)
                pipeline_errors.append({
                    "phase": "standardize",
                    "file": str(pipeline_input.file_path),
                    "media": pipeline_input.media,
                    "error": std_file.error,
                })
                continue

            all_standard_rows.extend(std_file.standard_rows)

            for unmapped in std_file.unmapped_columns:
                all_unmapped.append({
                    "media": unmapped.media,
                    "source_column": unmapped.source_column,
                    "sample_values": ", ".join(unmapped.sample_values),
                    "decision": unmapped.decision,
                    "suggested_target": unmapped.suggested_target,
                })

            logger.info(
                "[pipeline] 표준화 완료: %s / %s — %d행",
                pipeline_input.media,
                pipeline_input.file_path.name,
                std_file.row_count,
            )
            # 컬럼 진단: campaign_type 값 분포 출력
            if std_file.standard_rows:
                ct_values: dict[str, int] = {}
                for r in std_file.standard_rows:
                    ct = str(r.get("campaign_type") or "(없음)")
                    ct_values[ct] = ct_values.get(ct, 0) + 1
                top = sorted(ct_values.items(), key=lambda x: -x[1])[:5]
                print(f"  [진단] {pipeline_input.media}/{pipeline_input.file_path.name} campaign_type 분포: {top}")
        except Exception as exc:
            logger.exception("[pipeline] 표준화 오류: %s", pipeline_input.file_path)
            pipeline_errors.append({
                "phase": "standardize",
                "file": str(pipeline_input.file_path),
                "media": pipeline_input.media,
                "error": str(exc),
            })

    logger.info("[pipeline] 표준화 완료 — 총 %d행", len(all_standard_rows))

    # ---------------------------------------------------------------------------
    # Phase 2: 인덱스 분류
    # ---------------------------------------------------------------------------
    cleaned_rows: list[dict[str, Any]] = []
    failed_rows: list[dict[str, Any]] = []
    index_log_entries: list[dict[str, Any]] = []
    category_summary: dict[str, int] = {}
    media_summary: dict[str, int] = {}

    for row_num, std_row in enumerate(all_standard_rows, start=1):
        try:
            result = engine.classify_row(std_row)
        except Exception as exc:
            logger.warning("[pipeline] 분류 오류 (행 %d): %s", row_num, exc)
            pipeline_errors.append({
                "phase": "classify",
                "row_number": row_num,
                "error": str(exc),
            })
            result = None  # type: ignore[assignment]

        category = result.category if result else None
        cleaned_row = dict(std_row)
        cleaned_row["category"] = category or ""
        cleaned_row["classification_confidence"] = result.confidence if result else 0.0
        cleaned_row["classification_priority"] = result.matched_priority if result else ""
        cleaned_row["classification_rule_id"] = result.matched_rule_id if result else ""
        cleaned_row["classification_source"] = result.source if result else "error"
        cleaned_row["classification_needs_review"] = result.needs_review if result else True

        cleaned_rows.append(cleaned_row)

        if not category or (result and result.needs_review):
            failed_row = dict(cleaned_row)
            failed_row["source_row_number"] = row_num
            failed_row["reason"] = "unresolved" if not category else "needs_review"
            failed_row["suggested_action"] = "룰 테이블에 규칙 추가 검토"
            failed_rows.append(failed_row)

        # 카테고리 / 매체 집계
        cat_label = category or "미분류"
        category_summary[cat_label] = category_summary.get(cat_label, 0) + 1
        media_label = str(std_row.get("media") or "unknown")
        media_summary[media_label] = media_summary.get(media_label, 0) + 1

        index_log_entries.append({
            "source_row_number": row_num,
            "media": std_row.get("media"),
            "account_name": std_row.get("account_name"),
            "category": category,
            "confidence": result.confidence if result else 0.0,
            "matched_priority": result.matched_priority if result else None,
            "matched_rule_id": result.matched_rule_id if result else None,
            "source": result.source if result else "error",
            "needs_review": result.needs_review if result else True,
        })

    logger.info(
        "[pipeline] 분류 완료 — cleaned: %d, failed: %d",
        len(cleaned_rows), len(failed_rows),
    )

    # ---------------------------------------------------------------------------
    # Phase 2.5: 원본 파일에 카테고리 컬럼 추가하여 저장 (annotate)
    # ---------------------------------------------------------------------------
    annotated_dir = out_dir / "annotated"
    annotated_files: list[Path] = []
    print("[파이프라인] 원본 파일 카테고리 annotate 시작...")

    for pipeline_input in inputs:
        try:
            dst = annotated_dir / pipeline_input.file_path.name
            annotate_file(
                pipeline_input.file_path,
                media=pipeline_input.media,
                account_name=pipeline_input.account_name,
                account_id=pipeline_input.account_id,
                brand_id=pipeline_input.brand_id,
                mapping=mapping,
                engine=engine,
                output_path=dst,
            )
            annotated_files.append(dst)
            print(f"  ✔ {pipeline_input.media} / {pipeline_input.file_path.name}")
        except Exception as exc:
            logger.warning("[pipeline] annotate 실패: %s — %s", pipeline_input.file_path, exc)
            print(f"  ✘ {pipeline_input.file_path.name}: {exc}")

    print(f"[파이프라인] annotate 완료 — {len(annotated_files)}개 파일 저장: {annotated_dir}")

    # ---------------------------------------------------------------------------
    # Phase 3: Excel Report Builder
    # ---------------------------------------------------------------------------
    sheet_data = aggregate_sheets(
        standard_rows=cleaned_rows,
        failed_rows=failed_rows,
        unmapped_rows=all_unmapped,
        index_log_entries=index_log_entries,
        sheet_mode=sheet_mode,
        sa_optional_dims=sa_optional_dims,
        da_optional_dims=da_optional_dims,
    )

    # Excel 파일명 결정
    if not excel_filename:
        date_range = _date_range_str(inputs)
        excel_filename = f"통합_광고리포트_{run_date}_{date_range}.xlsx"

    excel_path = out_dir / excel_filename
    index_log_path = out_dir / f"index_log_{run_date}.json"
    run_log_path = out_dir / f"pipeline_run_{run_date}.log"

    try:
        build_workbook(sheet_data, excel_path)
        logger.info("[pipeline] Excel 생성 완료: %s", excel_path)
    except Exception as exc:
        logger.exception("[pipeline] Excel 생성 실패")
        pipeline_errors.append({"phase": "excel_builder", "error": str(exc)})
        excel_path = None  # type: ignore[assignment]

    # ── Raw Excel (매체별 원본 행, 11개 컬럼) ──
    raw_excel_filename = f"SA_통합_raw_{run_date}_{_date_range_str(inputs)}.xlsx"
    raw_excel_path = out_dir / raw_excel_filename
    try:
        build_raw_excel(cleaned_rows, raw_excel_path)
        logger.info("[pipeline] Raw Excel 생성 완료: %s", raw_excel_path)
    except Exception as exc:
        logger.exception("[pipeline] Raw Excel 생성 실패")
        pipeline_errors.append({"phase": "raw_excel_builder", "error": str(exc)})
        raw_excel_path = None  # type: ignore[assignment]

    # unmapped 컬럼 decisions CSV 자동 누적
    if decisions_path and all_unmapped:
        try:
            added = append_new_unmapped(decisions_path, all_unmapped)
            if added:
                logger.info("[pipeline] unmapped decisions %d개 추가: %s", added, decisions_path)
        except Exception as exc:
            logger.warning("[pipeline] unmapped decisions 누적 실패: %s", exc)

    # Index log JSON 저장
    try:
        _write_json(index_log_path, {
            "run_date": run_date,
            "total_rows": len(all_standard_rows),
            "cleaned_rows": len(cleaned_rows),
            "failed_rows": len(failed_rows),
            "unmapped_columns": len(all_unmapped),
            "category_summary": category_summary,
            "media_summary": media_summary,
            "pipeline_errors": pipeline_errors,
            "entries": index_log_entries,
        })
    except Exception as exc:
        logger.warning("[pipeline] Index log 저장 실패: %s", exc)
        index_log_path = None  # type: ignore[assignment]

    # 실행 로그 저장
    try:
        _write_run_log(run_log_path, inputs, pipeline_errors, cleaned_rows,
                       failed_rows, all_unmapped, excel_path, index_log_path)
    except Exception as exc:
        logger.warning("[pipeline] 실행 로그 저장 실패: %s", exc)
        run_log_path = None  # type: ignore[assignment]

    # ---------------------------------------------------------------------------
    # 최종 로그 출력
    # ---------------------------------------------------------------------------
    _print_summary(inputs, pipeline_errors, all_standard_rows, cleaned_rows,
                   failed_rows, all_unmapped, excel_path, index_log_path, index=index)

    return PipelineResult(
        excel_path=excel_path,
        raw_excel_path=raw_excel_path,
        index_log_path=index_log_path,
        run_log_path=run_log_path,
        total_input_files=len(inputs),
        total_standard_rows=len(all_standard_rows),
        total_cleaned_rows=len(cleaned_rows),
        total_failed_rows=len(failed_rows),
        total_unmapped_columns=len(all_unmapped),
        pipeline_errors=pipeline_errors,
        category_summary=category_summary,
        media_summary=media_summary,
        annotated_files=annotated_files,
    )


# ---------------------------------------------------------------------------
# 내부 유틸
# ---------------------------------------------------------------------------

def _date_range_str(inputs: list[PipelineInput]) -> str:
    starts = [i.start_date for i in inputs if i.start_date]
    ends = [i.end_date for i in inputs if i.end_date]
    if starts and ends:
        return f"{min(starts)}-{max(ends)}"
    return "unknown"


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("w", encoding="utf-8", newline="") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    except OSError:
        import subprocess, os
        content = json.dumps(data, ensure_ascii=False, indent=2, default=str)
        _powershell_write(path, content)


def _powershell_write(path: Path, content: str) -> None:
    import base64, os, subprocess
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    cmd = (
        "$target = $env:_PIPELINE_TARGET_PATH; "
        "$dir = [System.IO.Path]::GetDirectoryName($target); "
        "if ($dir) { [System.IO.Directory]::CreateDirectory($dir) | Out-Null }; "
        "$base64 = [Console]::In.ReadToEnd(); "
        "$bytes = [Convert]::FromBase64String($base64); "
        "[System.IO.File]::WriteAllBytes($target, $bytes)"
    )
    env = os.environ.copy()
    env["_PIPELINE_TARGET_PATH"] = str(path)
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", cmd],
        input=encoded, text=True, capture_output=True, check=True, env=env
    )


def _write_run_log(
    path: Path,
    inputs: list[PipelineInput],
    errors: list[dict[str, Any]],
    cleaned: list[dict[str, Any]],
    failed: list[dict[str, Any]],
    unmapped: list[dict[str, Any]],
    excel_path: Path | None,
    index_log_path: Path | None,
) -> None:
    lines = [
        f"=== pipeline run {datetime.now().isoformat()} ===",
        f"입력 파일 수    : {len(inputs)}",
        f"표준화 행 수    : {len(cleaned)}",
        f"실패 행 수      : {len(failed)}",
        f"미매핑 컬럼 수  : {len(unmapped)}",
        f"파이프라인 오류 : {len(errors)}",
        f"Excel 경로      : {excel_path or '생성 실패'}",
        f"Index log 경로  : {index_log_path or '저장 실패'}",
        "",
        "--- 입력 파일 목록 ---",
    ]
    for i in inputs:
        lines.append(f"  [{i.media}] {i.file_path}")
    if errors:
        lines.append("")
        lines.append("--- 오류 목록 ---")
        for e in errors:
            lines.append(f"  [{e.get('phase')}] {e.get('file', e.get('row_number', ''))} : {e.get('error')}")

    content = "\n".join(lines) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(content, encoding="utf-8")
    except OSError:
        _powershell_write(path, content)


def _print_summary(
    inputs: list[PipelineInput],
    errors: list[dict[str, Any]],
    standard_rows: list[dict[str, Any]],
    cleaned: list[dict[str, Any]],
    failed: list[dict[str, Any]],
    unmapped: list[dict[str, Any]],
    excel_path: Path | None,
    index_log_path: Path | None,
    index: dict[str, Any] | None = None,
) -> None:
    print("=" * 60)
    print("[pipeline] 후처리 완료")
    print(f"  입력 파일 수    : {len(inputs)}")
    print(f"  표준화 행 수    : {len(standard_rows)}")
    print(f"  분류 완료 행    : {len(cleaned)}")
    print(f"  실패 행         : {len(failed)}")
    print(f"  미매핑 컬럼     : {len(unmapped)}")
    print(f"  파이프라인 오류 : {len(errors)}")
    print(f"  Excel 경로      : {excel_path or '생성 실패'}")
    print(f"  Index log 경로  : {index_log_path or '저장 실패'}")

    # ── 미분류 행 진단: campaign_type / group_name 분포 출력 ─────────────
    if failed:
        ct_counts: dict[str, int] = {}
        gn_counts: dict[str, int] = {}
        for row in failed:
            ct = str(row.get("campaign_type") or "").strip()
            ct_counts[ct or "(없음)"] = ct_counts.get(ct or "(없음)", 0) + 1
            gn = str(row.get("group_name") or "").strip()
            gn_counts[gn or "(없음)"] = gn_counts.get(gn or "(없음)", 0) + 1

        # 로드된 캠페인유형 규칙의 패턴 집합
        loaded_ct_patterns: set[str] = set()
        if index:
            for r in index.get("campaign_type_rules", []):
                for p in r.get("patterns", []):
                    loaded_ct_patterns.add(str(p).strip().casefold())

        # 매체별 미분류 분포
        media_counts: dict[str, int] = {}
        for row in failed:
            m = str(row.get("media") or "(미상)").strip()
            media_counts[m] = media_counts.get(m, 0) + 1
        print(f"\n  [미분류 진단] 매체별 미분류 건수:")
        for m, cnt in sorted(media_counts.items(), key=lambda x: -x[1]):
            print(f"    {m}: {cnt}건")

        print(f"\n  [미분류 진단] 캠페인유형별 미분류 건수 (상위 10):")
        for ct, cnt in sorted(ct_counts.items(), key=lambda x: -x[1])[:10]:
            if ct == "(없음)":
                flag = " ← 컬럼 미매핑"
            elif loaded_ct_patterns and any(ct.casefold() in p or p in ct.casefold() for p in loaded_ct_patterns):
                flag = " ← 규칙 있음(매칭 실패?)"
            elif loaded_ct_patterns:
                flag = " ← 규칙 없음"
            else:
                flag = " ← 규칙 미로드"
            print(f"    {ct}: {cnt}건{flag}")

        if all(v == "(없음)" for v in ct_counts):
            print("    ※ campaign_type 컬럼이 비어 있습니다.")
            print("      매체 CSV의 실제 컬럼명을 확인하고 media-column-mapping.csv에 추가하세요.")

    print("=" * 60)
