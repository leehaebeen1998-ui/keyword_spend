from __future__ import annotations

import argparse
import sys
from pathlib import Path

from index_classifier.download_folder_processor import process_download_folder


def main() -> None:
    parser = argparse.ArgumentParser(description="다운로더 결과 폴더에서 raw 파일을 찾아 upload_rows.csv를 생성합니다.")
    parser.add_argument("--brand", required=True, help="브랜드명")
    parser.add_argument("--download-folder", required=True, help="다운로더가 raw를 저장한 상위 폴더")
    parser.add_argument("--rules", required=True, help="브랜드 업로드 규칙 CSV")
    parser.add_argument("--output", required=True, help="생성할 통합 upload_rows.csv")
    parser.add_argument("--media", default=None, help="특정 매체만 처리: Naver 또는 Google SA")
    parser.add_argument("--folder-date", default=None, help="다운로더 날짜 폴더 YYYY-MM-DD 또는 YYYYMMDD")
    args = parser.parse_args()

    folder = Path(args.download_folder)
    rules = Path(args.rules)
    if not folder.exists():
        print(f"[오류] download-folder를 찾을 수 없습니다: {folder}", file=sys.stderr)
        sys.exit(1)
    if not rules.exists():
        print(f"[오류] rules 파일을 찾을 수 없습니다: {rules}", file=sys.stderr)
        sys.exit(1)

    result = process_download_folder(
        brand=args.brand,
        download_folder=folder,
        rules_path=rules,
        output_path=Path(args.output),
        media_filter=args.media,
        folder_date=args.folder_date,
    )

    print("[완료] 다운로드 폴더 처리")
    print(f"  결과 파일: {result.output_path}")
    print(f"  raw 파일 수: {len(result.raw_files)}")
    for plan in result.raw_files:
        print(f"    [{plan.media}] {plan.path}")
    print(f"  변환 행 수: {result.total_rows}")
    print("  카테고리:")
    for category, count in sorted(result.category_counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"    {category}: {count}")
    if result.skipped_files:
        print(f"  건너뛴 파일: {len(result.skipped_files)}")


if __name__ == "__main__":
    main()
