from __future__ import annotations

import argparse
import sys
from pathlib import Path

from index_classifier.brand_template_writer import load_upload_rows, write_brand_template


def main() -> None:
    parser = argparse.ArgumentParser(description="브랜드 템플릿 엑셀/xlsb에 업로드용 CSV를 자동 반영합니다.")
    parser.add_argument("--brand", required=True, choices=("법무법인 오현", "법무법인 태하"))
    parser.add_argument("--template", required=True, help="원본 브랜드 템플릿 .xlsx 또는 .xlsb")
    parser.add_argument("--input-csv", required=True, help="업로드용 CSV")
    parser.add_argument("--output", required=True, help="저장할 결과 파일 경로")
    parser.add_argument("--run-date", default=None, help="실행 기준일 YYYY-MM-DD 또는 YYYYMMDD. 기본값: 오늘")
    args = parser.parse_args()

    input_csv = Path(args.input_csv)
    template = Path(args.template)
    if not input_csv.exists():
        print(f"[오류] input-csv 파일을 찾을 수 없습니다: {input_csv}", file=sys.stderr)
        print("       예시 경로가 아니라 실제 CSV 경로를 넣어주세요.", file=sys.stderr)
        sys.exit(1)
    if not template.exists():
        print(f"[오류] template 파일을 찾을 수 없습니다: {template}", file=sys.stderr)
        sys.exit(1)

    rows = load_upload_rows(input_csv)
    if not rows:
        print("[오류] input-csv에 데이터가 없습니다.", file=sys.stderr)
        sys.exit(1)

    result = write_brand_template(
        brand=args.brand,
        template_path=template,
        output_path=Path(args.output),
        rows=rows,
        run_date=args.run_date,
    )

    print("[완료] 브랜드 템플릿 반영")
    print(f"  결과 파일: {result.output_path}")
    print(f"  반영 행 수: {result.written_rows}")
    print(f"  건너뜀: {result.skipped_rows}")
    print(f"  수정 시트: {', '.join(result.touched_sheets) if result.touched_sheets else '(없음)'}")


if __name__ == "__main__":
    main()
