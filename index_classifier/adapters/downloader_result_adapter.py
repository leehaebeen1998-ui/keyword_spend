"""report-downloader의 DownloadResult를 PipelineInput으로 변환한다.

report-downloader 레포와 직접 의존하지 않는다.
DownloadResult 객체를 dict 또는 직접 전달 방식 모두 지원한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PipelineInput:
    """후처리 파이프라인 단일 파일 입력 정보.

    report-downloader의 DownloadResult로부터 채워지거나
    build_report_from_raw.py CLI에서 직접 구성된다.
    """
    file_path: Path
    media: str
    account_name: str = ""
    account_id: str = ""
    brand_id: str = ""
    report_type: str = ""
    start_date: str = ""
    end_date: str = ""
    # downloader가 이미 xlsx_sheet_name을 알고 있는 경우
    xlsx_sheet_name: str | None = None
    # 다운로드 메타데이터 (로그용)
    extra: dict[str, Any] = field(default_factory=dict)


def adapt_download_result(result: Any) -> PipelineInput | None:
    """단일 DownloadResult → PipelineInput 변환.

    DownloadResult는 아래 속성을 가져야 한다:
        success      : bool
        file_path    : Path | str | None
        media        : str  (없으면 "unknown")
        account_name : str  (없으면 "")
        account_id   : str  (없으면 "")

    None 반환 = 변환 불가 (실패 결과 또는 file_path 없음).
    """
    # dict 형태 지원
    if isinstance(result, dict):
        if not result.get("success", True):
            return None
        raw_path = result.get("file_path") or result.get("raw_file_path")
        if not raw_path:
            return None
        return PipelineInput(
            file_path=Path(raw_path),
            media=str(result.get("media") or "unknown"),
            account_name=str(result.get("account_name") or ""),
            account_id=str(result.get("account_id") or ""),
            brand_id=str(result.get("brand_id") or ""),
            report_type=str(result.get("report_type") or ""),
            start_date=str(result.get("start_date") or ""),
            end_date=str(result.get("end_date") or ""),
            xlsx_sheet_name=result.get("xlsx_sheet_name"),
            extra={k: v for k, v in result.items()
                   if k not in ("file_path", "raw_file_path", "media",
                                "account_name", "account_id", "brand_id",
                                "report_type", "start_date", "end_date",
                                "success", "xlsx_sheet_name")},
        )

    # 객체(dataclass/namedtuple) 형태 지원
    success = getattr(result, "success", True)
    if not success:
        return None

    raw_path = (
        getattr(result, "file_path", None)
        or getattr(result, "raw_file_path", None)
    )
    if not raw_path:
        return None

    return PipelineInput(
        file_path=Path(raw_path),
        media=str(getattr(result, "media", "unknown")),
        account_name=str(getattr(result, "account_name", "")),
        account_id=str(getattr(result, "account_id", "")),
        brand_id=str(getattr(result, "brand_id", "")),
        report_type=str(getattr(result, "report_type", "")),
        start_date=str(getattr(result, "start_date", "")),
        end_date=str(getattr(result, "end_date", "")),
        xlsx_sheet_name=getattr(result, "xlsx_sheet_name", None),
    )


def adapt_download_results(results: list[Any]) -> tuple[list[PipelineInput], list[Any]]:
    """DownloadResult 목록 → (변환 성공 목록, 변환 실패/스킵 목록).

    실패 목록은 다운로드 실패이거나 file_path 없는 항목이다.
    """
    inputs: list[PipelineInput] = []
    skipped: list[Any] = []

    for r in results:
        adapted = adapt_download_result(r)
        if adapted is not None:
            inputs.append(adapted)
        else:
            skipped.append(r)

    return inputs, skipped
