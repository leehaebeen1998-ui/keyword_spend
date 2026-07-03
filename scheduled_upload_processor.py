from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

from index_classifier.brand_template_writer import write_brand_template
from index_classifier.brand_settings import DEFAULT_OUTPUT_ROOT, default_output_path, default_upload_csv_path
from index_classifier.download_folder_processor import process_download_folder
from index_classifier.schedule_rules import custom_download_window, default_download_window


def main() -> None:
    parser = argparse.ArgumentParser(description="Run brand upload processing from a saved schedule config.")
    parser.add_argument("config", help="Path to upload_processor_schedule.json")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    run_date = date.today().strftime("%Y-%m-%d")
    folder_date = run_date
    window = _download_window(config, run_date)

    _log(config_path, f"[시작] {run_date} {config.get('brand', '')}")
    _log(config_path, f"  다운로드 기간: {window.start_yyyymmdd}~{window.end_yyyymmdd}")
    _log(config_path, f"  폴더일: {folder_date.replace('-', '')}")
    _run_optional_command(config_path, "로그인 봇", str(config.get("login_command") or ""))
    _run_optional_command(config_path, "다운로더", str(config.get("downloader_command") or ""))

    upload_csv = default_upload_csv_path(
        brand=str(config["brand"]),
        run_date=run_date,
        output_root=str(config.get("output_root") or DEFAULT_OUTPUT_ROOT),
    )
    output_path = default_output_path(
        brand=str(config["brand"]),
        run_date=run_date,
        template_path=str(config["template_path"]),
        output_root=str(config.get("output_root") or DEFAULT_OUTPUT_ROOT),
    )

    folder_result = process_download_folder(
        brand=str(config["brand"]),
        download_folder=str(config["download_folder"]),
        rules_path=str(config["rules_path"]),
        output_path=upload_csv,
        folder_date=folder_date,
    )
    _log(config_path, f"[완료] 업로드 CSV 생성: {folder_result.output_path}")
    _log(config_path, f"  raw 파일 수: {len(folder_result.raw_files)}")
    _log(config_path, f"  변환 행 수: {folder_result.total_rows}")

    rows = _load_rows(upload_csv)
    if not rows:
        raise ValueError("업로드 CSV에 데이터가 없습니다.")

    template_result = write_brand_template(
        brand=str(config["brand"]),
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
