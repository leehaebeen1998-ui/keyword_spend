from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from index_classifier.brand_template_writer import write_brand_template
from index_classifier.brand_settings import DEFAULT_OUTPUT_ROOT, default_output_path, default_upload_csv_path
from index_classifier.download_folder_processor import process_download_folder
from index_classifier.schedule_rules import custom_download_window, default_download_window

# GUI(upload_processor_gui.py)와 동일한 "다운로더에 브랜드/기간을 맞춰 넣고 실행" 로직을
# 그대로 재사용한다. 이 함수들은 순수 헬퍼(파일 경로 계산, dict 조작)라
# tkinter 창을 띄우지 않고 임포트해도 안전하다.
from upload_processor_gui import (
    _atomic_write_text,
    _bundled_downloader_config_path,
    _default_download_root,
    _downloader_brand_name,
    _normalize_external_command,
)

DOWNLOADER_TIMEOUT_SEC = 1800
POLL_INTERVAL_SEC = 5
LOG_INTERVAL_SEC = 15


def main() -> None:
    parser = argparse.ArgumentParser(description="Run brand upload processing from a saved schedule config.")
    parser.add_argument("config", help="Path to upload_processor_schedule.json")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    run_date = date.today().strftime("%Y-%m-%d")
    folder_date = run_date
    window = _download_window(config, run_date)
    brand = str(config["brand"])
    download_folder = str(config["download_folder"])
    rules_path = str(config["rules_path"])

    _log(config_path, f"[시작] {run_date} {brand}")
    _log(config_path, f"  다운로드 기간: {window.start_yyyymmdd}~{window.end_yyyymmdd}")
    _log(config_path, f"  폴더일: {folder_date.replace('-', '')}")
    _run_optional_command(config_path, "로그인 봇", str(config.get("login_command") or ""))

    upload_csv = default_upload_csv_path(
        brand=brand,
        run_date=run_date,
        output_root=str(config.get("output_root") or DEFAULT_OUTPUT_ROOT),
    )
    output_path = default_output_path(
        brand=brand,
        run_date=run_date,
        template_path=str(config["template_path"]),
        output_root=str(config.get("output_root") or DEFAULT_OUTPUT_ROOT),
    )

    folder_result = _ensure_raw_available(
        config_path=config_path,
        brand=brand,
        download_folder=download_folder,
        rules_path=rules_path,
        upload_csv=upload_csv,
        folder_date=folder_date,
        window=window,
        downloader_command=str(config.get("downloader_command") or ""),
    )
    _log(config_path, f"[완료] 업로드 CSV 생성: {folder_result.output_path}")
    _log(config_path, f"  raw 파일 수: {len(folder_result.raw_files)}")
    _log(config_path, f"  변환 행 수: {folder_result.total_rows}")

    rows = _load_rows(upload_csv)
    if not rows:
        raise ValueError("업로드 CSV에 데이터가 없습니다.")

    template_result = write_brand_template(
        brand=brand,
        template_path=str(config["template_path"]),
        output_path=output_path,
        rows=rows,
        run_date=run_date,
    )
    if template_result.written_rows <= 0:
        raise ValueError("템플릿에 반영된 행이 없습니다.")
    _log(config_path, f"[완료] 템플릿 반영: {template_result.output_path}")
    _log(config_path, f"  반영 행 수: {template_result.written_rows}")
    _log(config_path, f"  수정 시트: {', '.join(template_result.touched_sheets)}")


def _ensure_raw_available(
    *,
    config_path: Path,
    brand: str,
    download_folder: str,
    rules_path: str,
    upload_csv: str,
    folder_date: str,
    window,
    downloader_command: str,
):
    """GUI의 `_process_folder`와 동일한 2단계 재시도 흐름.

    1) 이미 raw 파일이 있으면 바로 처리하고 끝낸다(수동으로 미리 받아둔 경우 등).
    2) raw 파일이 없거나(FileNotFoundError) 예약 기간 중 일부 날짜가 비어 있으면,
       다운로더 봇을 브랜드/기간에 맞춰 실행하고, raw 파일이 나타날 때까지
       (최대 30분) 주기적으로 재확인한다. 사람이 수동으로 다운로더를 눌러줄
       필요가 없도록 하는 것이 목적이다.
    """
    try:
        result = process_download_folder(
            brand=brand,
            download_folder=download_folder,
            rules_path=rules_path,
            output_path=upload_csv,
            folder_date=folder_date,
        )
        missing_dates = _missing_expected_dates(result, window)
    except FileNotFoundError as exc:
        _log(config_path, f"[auto] raw 파일 없음, 다운로더 실행: {exc}")
        return _run_downloader_until_raw_available(
            config_path=config_path,
            brand=brand,
            download_folder=download_folder,
            rules_path=rules_path,
            upload_csv=upload_csv,
            folder_date=folder_date,
            window=window,
            downloader_command=downloader_command,
        )

    if not missing_dates:
        return result

    _log(config_path, f"[auto] raw 날짜 누락({', '.join(missing_dates)}), 다운로더 실행.")
    result = _run_downloader_until_raw_available(
        config_path=config_path,
        brand=brand,
        download_folder=download_folder,
        rules_path=rules_path,
        upload_csv=upload_csv,
        folder_date=folder_date,
        window=window,
        downloader_command=downloader_command,
    )
    missing_dates = _missing_expected_dates(result, window)
    if missing_dates:
        raise FileNotFoundError(f"다운로드 후에도 누락된 날짜 데이터가 있습니다: {', '.join(missing_dates)}")
    return result


def _run_downloader_until_raw_available(
    *,
    config_path: Path,
    brand: str,
    download_folder: str,
    rules_path: str,
    upload_csv: str,
    folder_date: str,
    window,
    downloader_command: str,
):
    _prepare_bundled_downloader_config(config_path, brand=brand, window=window)

    command = _normalize_external_command(downloader_command)
    if not command:
        raise FileNotFoundError("raw 파일이 없고 downloader_command도 비어 있어 자동 다운로드를 할 수 없습니다.")

    _log(config_path, f"[시작] 다운로더: {command}")
    process = subprocess.Popen(
        command,
        shell=True,
        cwd=Path(__file__).parent,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _log(config_path, f"[started] 다운로더 pid={process.pid}")

    deadline = time.monotonic() + DOWNLOADER_TIMEOUT_SEC
    last_log = 0.0
    while time.monotonic() < deadline:
        try:
            result = process_download_folder(
                brand=brand,
                download_folder=download_folder,
                rules_path=rules_path,
                output_path=upload_csv,
                folder_date=folder_date,
            )
        except FileNotFoundError:
            if process.poll() is not None and process.returncode not in (0, None):
                raise RuntimeError(f"다운로더가 raw 파일 생성 전에 code {process.returncode}로 종료되었습니다.")
            now = time.monotonic()
            if now - last_log >= LOG_INTERVAL_SEC:
                _log(config_path, "[auto] 다운로더 raw 파일 대기 중...")
                last_log = now
            time.sleep(POLL_INTERVAL_SEC)
            continue

        missing_dates = _missing_expected_dates(result, window)
        if missing_dates:
            if process.poll() is not None and process.returncode not in (0, None):
                raise RuntimeError(
                    f"다운로더가 code {process.returncode}로 종료됐지만 누락된 날짜가 남아 있습니다: {', '.join(missing_dates)}"
                )
            now = time.monotonic()
            if now - last_log >= LOG_INTERVAL_SEC:
                _log(config_path, f"[auto] 누락된 raw 날짜 대기 중: {', '.join(missing_dates)}")
                last_log = now
            time.sleep(POLL_INTERVAL_SEC)
            continue

        _log(config_path, "[auto] 다운로더 실행 후 raw 파일 확인됨.")
        return result

    raise TimeoutError("다운로더 실행 후 30분 내에 raw 파일을 찾지 못했습니다.")


def _prepare_bundled_downloader_config(config_path: Path, *, brand: str, window) -> None:
    """다운로더 봇의 config.json을 이번 예약 실행의 브랜드/기간에 맞춘다.

    GUI의 `_prepare_bundled_downloader`와 동일하게, active_brand/brand_name/media를
    이 스케줄이 대상으로 하는 브랜드로 강제 전환한다. 이걸 안 하면 다운로더가
    직전에 GUI에서 마지막으로 선택했던(또는 다른 예약이 마지막으로 설정한) 엉뚱한
    브랜드의 계정을 받아올 수 있다.
    """
    downloader_config_path = _bundled_downloader_config_path()
    if not downloader_config_path.exists():
        _log(config_path, f"[warning] 다운로더 config를 찾을 수 없습니다: {downloader_config_path}")
        return
    try:
        data = json.loads(downloader_config_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        _log(config_path, f"[warning] 다운로더 config 읽기 실패: {exc}")
        return

    download_root = _default_download_root()
    if download_root:
        Path(download_root).mkdir(parents=True, exist_ok=True)
        data["save_root_path"] = download_root

    data["last_run_period"] = {
        "start": window.start_date.strftime("%Y-%m-%d"),
        "end": window.end_date.strftime("%Y-%m-%d"),
    }

    downloader_brand = _downloader_brand_name(brand, data)
    if downloader_brand:
        data["active_brand"] = downloader_brand
        data["brand_name"] = downloader_brand
        for entry in data.get("brands", []):
            if str(entry.get("name") or "").strip() == downloader_brand:
                media = entry.get("media")
                if isinstance(media, dict):
                    data["media"] = media
                break

    _atomic_write_text(downloader_config_path, json.dumps(data, ensure_ascii=False, indent=2))
    _log(config_path, f"[ready] 다운로더 브랜드={downloader_brand or brand}, 저장 폴더={download_root}")


def _missing_expected_dates(result, window) -> list[str]:
    expected: list[str] = []
    current = window.start_date
    while current <= window.end_date:
        expected.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    available = set(getattr(result, "date_counts", {}) or {})
    return [date_key for date_key in expected if date_key not in available]


def _download_window(config: dict[str, Any], run_date: str):
    if str(config.get("schedule_mode", "")) == "공휴일 수동":
        custom_start = str(config.get("custom_start", "")).strip()
        custom_end = str(config.get("custom_end", "")).strip()
        if custom_start and custom_end:
            return custom_download_window(custom_start, custom_end)
    return default_download_window(run_date)


def _load_rows(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
        return [dict(row) for row in csv.DictReader(file)]


def _run_optional_command(config_path: Path, label: str, command: str) -> None:
    command = command.strip()
    if not command:
        return
    _log(config_path, f"[시작] {label}: {command}")
    result = subprocess.run(
        command,
        shell=True,
        cwd=Path(__file__).parent,
        capture_output=True,
        text=True,
        encoding="mbcs",
        errors="replace",
        check=False,
    )
    if result.stdout.strip():
        _log(config_path, result.stdout.strip())
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or f"{label} 실행 실패").strip())
    _log(config_path, f"[완료] {label}")


def _log(config_path: Path, message: str) -> None:
    log_path = config_path.with_suffix(".log")
    with log_path.open("a", encoding="utf-8") as file:
        file.write(message + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        config_arg = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("upload_processor_schedule.json")
        try:
            _log(config_arg, f"[오류] {exc}")
        finally:
            raise
