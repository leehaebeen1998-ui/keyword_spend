from __future__ import annotations

import argparse
import sys
from pathlib import Path

from index_classifier.raw_upload_builder import build_upload_csv_from_raw


def main() -> None:
    parser = argparse.ArgumentParser(description="브랜드 raw 보고서를 템플릿 업로드용 CSV로 변환합니다.")
    parser.add_argument("--brand", required=True, help="브랜드명")
    parser.add_argument("--media", required=True, help="Naver 또는 Google SA")
    parser.add_argument("--input", required=True, help="raw CSV 경로")
    parser.add_argument("--output", required=True, help="생성할 upload_rows.csv 경로")
    parser.add_argument("--default-category", default="", help="태하처럼 파일 전체가 한 카테고리일 때 강제 카테고리")
    parser.add_argument("--rules", required=True, help="브랜드별 고정 분류 규칙 CSV/JSON 경로")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[오류] input 파일을 찾을 수 없습니다: {input_path}", file=sys.stderr)
        sys.exit(1)

    result = build_upload_csv_from_raw(
        brand=args.brand,
        media=args.media,
        input_path=input_path,
        output_path=Path(args.output),
        default_category=args.default_category,
        rules_path=args.rules,
    )

    print("[완료] 업로드 CSV 생성")
    print(f"  결과 파일: {result.output_path}")
    print(f"  변환 행 수: {result.written_rows}")
    print("  카테고리:")
    for category, count in sorted(result.category_counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"    {category}: {count}")


if __name__ == "__main__":
    main()
