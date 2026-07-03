import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from index_classifier.download_folder_processor import discover_raw_files, process_download_folder


class DownloadFolderProcessorTests(unittest.TestCase):
    def test_discovers_naver_and_google_raw_files(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Naver" / "20260701" / "일별 로우").mkdir(parents=True)
            (root / "Google SA" / "20260701" / "일별 로우").mkdir(parents=True)
            naver = root / "Naver" / "20260701" / "일별 로우" / "naver_brand_01_raw_20260630_20260630.csv"
            google = root / "Google SA" / "20260701" / "일별 로우" / "google_sa_brand_01_raw_20260630_20260630.csv"
            naver.write_text("x", encoding="utf-8")
            google.write_text("x", encoding="utf-8")

            plans, skipped = discover_raw_files(root)

            self.assertEqual(skipped, [])
            self.assertEqual([plan.media for plan in plans], ["Google SA", "Naver"])

    def test_process_download_folder_combines_rows(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rules = root / "rules.csv"
            output = root / "upload_rows.csv"
            naver_dir = root / "Naver" / "20260701" / "일별 로우"
            google_dir = root / "Google SA" / "20260701" / "일별 로우"
            naver_dir.mkdir(parents=True)
            google_dir.mkdir(parents=True)
            rules.write_text(
                "브랜드,순위,규칙,매칭값,카테고리,신뢰도,사용,메모\n"
                "테스트 브랜드,0,계정번호,01,형,1,O,\n"
                "테스트 브랜드,2,캠페인명,성범죄,성범죄,1,O,\n",
                encoding="utf-8-sig",
            )
            (naver_dir / "naver_test_01_raw_20260630_20260630.csv").write_text(
                '"일일보고서(2026.06.30.~2026.06.30.),1"\n'
                "캠페인유형,PC/모바일 매체,키워드,노출수,클릭수,클릭률(%),평균 CPC,총비용,총 전환수,총 전환율(%),총 전환당비용(원),평균노출순위\n"
                "파워링크,모바일,형사변호사,100,1,1,5000,5000,0,0,0,2.1\n",
                encoding="utf-8-sig",
            )
            (google_dir / "google_sa_test_01_raw_20260630_20260630.csv").write_text(
                "일간 키워드 보고\n"
                "2026년 6월 30일 - 2026년 6월 30일\n"
                "일\t캠페인\t캠페인 유형\t기기\t검색 키워드\t노출수\t클릭수\t클릭률(CTR)\t통화 코드\t평균 비용\t비용\t전환\t모든 전환당 비용\t전환율\n"
                "2026-06-30\t[SA] 성범죄_확장\t검색\t휴대전화\t성범죄변호사\t10\t1\t10.00%\tKRW\t1000\t1000\t0\t0\t0.00%\n",
                encoding="utf-16",
            )

            result = process_download_folder(
                brand="테스트 브랜드",
                download_folder=root,
                rules_path=rules,
                output_path=output,
            )

            self.assertEqual(result.total_rows, 2)
            self.assertEqual(result.category_counts["형"], 1)
            self.assertEqual(result.category_counts["성범죄"], 1)
            with output.open("r", encoding="utf-8-sig", newline="") as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(len(rows), 2)

    def test_process_download_folder_reports_duplicate_rows_without_dropping(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rules = root / "rules.csv"
            output = root / "upload_rows.csv"
            raw_dir = root / "Naver" / "20260701" / "일별 로우"
            raw_dir.mkdir(parents=True)
            rules.write_text(
                "브랜드,순위,규칙,매칭값,카테고리,신뢰도,사용,메모\n"
                "테스트 브랜드,0,계정번호,01,형,1,O,\n",
                encoding="utf-8-sig",
            )
            body = (
                '"일일보고서(2026.06.30.~2026.06.30.),1"\n'
                "캠페인유형,PC/모바일 매체,키워드,노출수,클릭수,클릭률(%),평균 CPC,총비용,총 전환수,총 전환율(%),총 전환당비용(원),평균노출순위\n"
                "파워링크,모바일,형사변호사,100,1,1,5000,5000,0,0,0,2.1\n"
            )
            (raw_dir / "naver_test_01_raw_20260630_20260630.csv").write_text(body, encoding="utf-8-sig")
            (raw_dir / "naver_test_01_copy_raw_20260630_20260630.csv").write_text(body, encoding="utf-8-sig")

            result = process_download_folder(
                brand="테스트 브랜드",
                download_folder=root,
                rules_path=rules,
                output_path=output,
            )

            self.assertEqual(result.total_rows, 2)
            self.assertEqual(result.duplicate_rows, 1)
            with output.open("r", encoding="utf-8-sig", newline="") as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(len(rows), 2)

    def test_process_download_folder_filters_by_folder_date(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rules = root / "rules.csv"
            output = root / "upload_rows.csv"
            for folder_date in ("20260701", "20260702"):
                raw_dir = root / "Naver" / folder_date / "일별 로우"
                raw_dir.mkdir(parents=True)
                (raw_dir / f"naver_test_01_raw_{folder_date}_{folder_date}.csv").write_text(
                    '"일일보고서(2026.06.30.~2026.06.30.),1"\n'
                    "캠페인유형,PC/모바일 매체,키워드,노출수,클릭수,클릭률(%),평균 CPC,총비용,총 전환수,총 전환율(%),총 전환당비용(원),평균노출순위\n"
                    f"파워링크,모바일,{folder_date},100,1,1,5000,5000,0,0,0,2.1\n",
                    encoding="utf-8-sig",
                )
            rules.write_text(
                "브랜드,순위,규칙,매칭값,카테고리,신뢰도,사용,메모\n"
                "테스트 브랜드,0,계정번호,01,형,1,O,\n",
                encoding="utf-8-sig",
            )

            result = process_download_folder(
                brand="테스트 브랜드",
                download_folder=root,
                rules_path=rules,
                output_path=output,
                folder_date="2026-07-01",
            )

            self.assertEqual(len(result.raw_files), 1)
            self.assertIn("20260701", str(result.raw_files[0].path))


if __name__ == "__main__":
    unittest.main()
