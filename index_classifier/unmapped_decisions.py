"""unmapped-column-decisions.csv 자동 누적 및 로드.

파이프라인 실행 시 신규 unmapped 컬럼을 decisions CSV에 자동 append한다.
사용자가 결정값(map/ignore/review)을 직접 편집한 뒤 다음 실행에 반영된다.
"""
from __future__ import annotations

import csv
import io
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_FIELDNAMES = ("media", "source_column", "decision", "target_column", "memo")


def load_decisions(decisions_path: str | Path) -> dict[tuple[str, str], dict[str, str]]:
    """decisions CSV를 로드. {(media, source_column): row_dict} 반환."""
    path = Path(decisions_path)
    if not path.exists():
        return {}
    result: dict[tuple[str, str], dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            media = (row.get("media") or "").strip()
            col = (row.get("source_column") or "").strip()
            if media and col:
                result[(media, col)] = dict(row)
    return result


def append_new_unmapped(
    decisions_path: str | Path,
    unmapped_rows: list[dict[str, Any]],
) -> int:
    """파이프라인에서 발견된 신규 unmapped 컬럼을 decisions CSV에 추가.

    이미 존재하는 (media, source_column) 조합은 건너뛴다.
    Returns:
        추가된 신규 항목 수
    """
    path = Path(decisions_path)
    existing = load_decisions(path)
    added = 0

    new_rows: list[dict[str, str]] = []
    seen_in_batch: set[tuple[str, str]] = set()

    for row in unmapped_rows:
        media = str(row.get("media") or "").strip()
        col = str(row.get("source_column") or "").strip()
        if not media or not col:
            continue
        key = (media, col)
        if key in existing or key in seen_in_batch:
            continue
        seen_in_batch.add(key)
        new_rows.append({
            "media": media,
            "source_column": col,
            "decision": "review",
            "target_column": str(row.get("suggested_target") or ""),
            "memo": f"자동 감지 — 샘플: {row.get('sample_values', '')}",
        })
        added += 1

    if not new_rows:
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)

    # 파일이 없으면 헤더 포함, 있으면 append
    write_header = not path.exists() or path.stat().st_size == 0
    try:
        with path.open("a", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_FIELDNAMES, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            writer.writerows(new_rows)
    except OSError:
        _append_with_powershell(path, new_rows, write_header)

    if added:
        logger.info("[unmapped_decisions] %d개 신규 항목 추가: %s", added, path)

    return added


def _append_with_powershell(
    path: Path,
    rows: list[dict[str, str]],
    write_header: bool,
) -> None:
    """OneDrive 잠금 우회 — PowerShell을 통해 CSV append."""
    import base64, os, subprocess

    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=_FIELDNAMES, extrasaction="ignore")
    if write_header:
        writer.writeheader()
    writer.writerows(rows)
    content = buf.getvalue()

    encoded = base64.b64encode(content.encode("utf-8-sig")).decode("ascii")
    cmd = (
        "$target = $env:_UNMAPPED_TARGET_PATH; "
        "$dir = [System.IO.Path]::GetDirectoryName($target); "
        "if ($dir) { [System.IO.Directory]::CreateDirectory($dir) | Out-Null }; "
        "$base64 = [Console]::In.ReadToEnd(); "
        "$bytes = [Convert]::FromBase64String($base64); "
        "[System.IO.File]::AppendAllText($target, "
        "[System.Text.Encoding]::UTF8.GetString($bytes))"
    )
    env = os.environ.copy()
    env["_UNMAPPED_TARGET_PATH"] = str(path)
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", cmd],
        input=encoded, text=True, capture_output=True, check=True, env=env,
    )
