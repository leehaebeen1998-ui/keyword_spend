from __future__ import annotations

import csv
import errno
import base64
import os
import io
import subprocess
import uuid
from pathlib import Path
from typing import Any


SIMPLE_RULE_HEADERS: tuple[str, ...] = (
    "순위",
    "규칙",
    "매칭값",
    "카테고리",
    "신뢰도",
    "사용",
    "메모",
)

RULE_LABELS: dict[int, str] = {
    0: "강제 지정 URL",
    1: "캠페인 유형",
    2: "그룹명",
    3: "키워드명",
    4: "캠페인명",
    5: "일반 URL",
}

DEFAULT_CONFIDENCE_BY_PRIORITY: dict[int, str] = {
    0: "1",
    1: "0.8",
    2: "0.9",
    3: "0.9",
    4: "0.85",
    5: "0.65",
}


def read_simple_rule_rows(path: str | Path) -> list[dict[str, Any]]:
    rule_path = Path(path)
    if not rule_path.exists():
        return []

    with open(os.fspath(rule_path), "r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return [dict(row) for row in reader]


def write_simple_rule_rows(path: str | Path, rows: list[dict[str, Any]]) -> None:
    rule_path = Path(path)
    rule_path.parent.mkdir(parents=True, exist_ok=True)
    content = _serialize_simple_rule_rows(rows)

    # 방법 1: 직접 쓰기 (OneDrive 동기화 중 os.replace가 잠길 때 우회)
    try:
        _write_text(rule_path, content)
        return
    except OSError:
        pass

    # 방법 2: temp 파일 → 원본 삭제 → rename
    temp_path = rule_path.with_name(f".{rule_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        _write_text(temp_path, content)
        if rule_path.exists():
            rule_path.unlink()
        temp_path.rename(rule_path)
        return
    except OSError:
        pass
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass

    # 방법 3: PowerShell 폴백
    _write_text_with_powershell(rule_path, content)


def _serialize_simple_rule_rows(rows: list[dict[str, Any]]) -> str:
    file = io.StringIO(newline="")
    writer = csv.DictWriter(file, fieldnames=list(SIMPLE_RULE_HEADERS), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return file.getvalue()


def _write_text(path: Path, content: str) -> None:
    try:
        with open(os.fspath(path), "w", encoding="utf-8-sig", newline="") as file:
            file.write(content)
    except OSError as exc:
        if exc.errno != errno.EBADF:
            raise
        _write_text_low_level(path, content)


def _write_text_low_level(path: Path, content: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY

    descriptor = os.open(os.fspath(path), flags, 0o666)
    try:
        data = content.encode("utf-8-sig")
        while data:
            written = os.write(descriptor, data)
            data = data[written:]
    finally:
        os.close(descriptor)


def _write_text_with_powershell(path: Path, content: str) -> None:
    command = (
        "$target = $env:RULE_EDITOR_TARGET_PATH; "
        "$base64 = [Console]::In.ReadToEnd(); "
        "$bytes = [Convert]::FromBase64String($base64); "
        "[System.IO.File]::WriteAllBytes($target, $bytes)"
    )
    encoded = base64.b64encode(content.encode("utf-8-sig")).decode("ascii")
    env = os.environ.copy()
    env["RULE_EDITOR_TARGET_PATH"] = os.fspath(path)
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        input=encoded,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "PowerShell file write failed").strip()
        raise OSError(message)


def append_simple_rule(
    path: str | Path,
    *,
    priority: int,
    match_value: str,
    category: str,
    confidence: str | None = None,
    enabled: str = "O",
    memo: str = "",
) -> dict[str, Any]:
    if priority not in RULE_LABELS:
        raise ValueError(f"Unsupported priority: {priority}")

    row = {
        "순위": str(priority),
        "규칙": RULE_LABELS[priority],
        "매칭값": match_value.strip(),
        "카테고리": category.strip(),
        "신뢰도": (confidence or DEFAULT_CONFIDENCE_BY_PRIORITY[priority]).strip(),
        "사용": enabled.strip() or "O",
        "메모": memo.strip(),
    }

    rows = read_simple_rule_rows(path)
    rows.append(row)
    write_simple_rule_rows(path, rows)
    return row

def delete_simple_rule(
    path: str | Path,
    *,
    one_based_index: int,
) -> dict[str, Any]:
    """규칙 CSV에서 one_based_index 번째 규칙을 삭제하고 삭제된 행을 반환.

    Args:
        path: 규칙 CSV 경로
        one_based_index: 1-기반 행 번호 (헤더 제외)

    Raises:
        IndexError: 유효하지 않은 인덱스
    """
    rows = read_simple_rule_rows(path)
    idx = one_based_index - 1
    if idx < 0 or idx >= len(rows):
        raise IndexError(
            f"인덱스 {one_based_index}가 범위를 벗어났습니다. "
            f"현재 규칙 수: {len(rows)}"
        )
    removed = rows.pop(idx)
    write_simple_rule_rows(path, rows)
    return removed
