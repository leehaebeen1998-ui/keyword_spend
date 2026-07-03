import unittest

from pathlib import Path
from tempfile import TemporaryDirectory

from index_classifier import (
    ClassificationEngine,
    ReportRowCleaner,
    append_user_correction,
    build_daily_report,
    filter_indexes_by_scope,
    load_simple_rules_index,
    normalize_row,
    simple_rules_to_index,
)
from index_classifier.adapters import PipelineInput
from index_classifier.simple_rule_table import append_simple_rule, delete_simple_rule, read_simple_rule_rows
from index_classifier.ai import AIRequest, AIResponse
from index_classifier.report_io import read_report_rows


def sample_index():
    return {
        "index_version": "1.0.0",
        "scope": {"brand_id": "brand_001", "account_ids": ["account_001"]},
        "column_aliases": {
            "campaign_type": ["매체"],
            "group_name": ["광고그룹"],
            "keyword_name": ["키워드"],
            "campaign_name": ["캠페인"],
            "url": ["랜딩URL"],
        },
        "forced_url_mapping": [
            {
                "id": "forced-drug",
                "url": "https://example.com/drug",
                "category": "마약",
            }
        ],
        "campaign_type_rules": [
            {
                "id": "type-meta",
                "field": "campaign_type",
                "match_type": "contains",
                "patterns": ["Meta"],
                "category": "Meta",
                "confidence": 0.95,
            }
        ],
        "group_name_rules": [
            {
                "id": "group-criminal",
                "field": "group_name",
                "match_type": "contains",
                "patterns": ["형사"],
                "category": "형사",
                "confidence": 0.9,
            }
        ],
        "keyword_rules": [
            {
                "id": "keyword-divorce",
                "field": "keyword_name",
                "match_type": "contains",
                "patterns": ["이혼"],
                "category": "이혼",
                "confidence": 0.92,
                "campaign_type_filter": ["Naver SA"],
            }
        ],
        "campaign_name_rules": [
            {
                "id": "campaign-tax",
                "field": "campaign_name",
                "match_type": "contains",
                "patterns": ["조세"],
                "category": "조세",
                "confidence": 0.8,
            }
        ],
        "url_rules": [
            {
                "id": "url-criminal",
                "field": "url",
                "match_type": "contains",
                "patterns": ["/criminal"],
                "category": "형사",
                "confidence": 0.65,
            }
        ],
        "user_corrections": [],
        "ai_fallback": {
            "enabled": True,
            "min_confidence": 0.7,
            "analyze_fields": ["ad_text"],
        },
    }


class FakeAIAnalyzer:
    def analyze(self, request: AIRequest) -> AIResponse:
        return AIResponse(
            category="성범죄",
            confidence=0.88,
            evidence={"field": "ad_text", "value": request.normalized_row.get("ad_text")},
        )


class ClassifierTests(unittest.TestCase):
    def test_normalize_row_maps_report_columns(self):
        row = {"매체": "Naver SA", "광고그룹": "형사_구속", "랜딩URL": "https://example.com"}

        normalized = normalize_row(row, sample_index()["column_aliases"])

        self.assertEqual(normalized["campaign_type"], "Naver SA")
        self.assertEqual(normalized["group_name"], "형사_구속")
        self.assertEqual(normalized["url"], "https://example.com")

    def test_forced_url_mapping_wins_over_group_name(self):
        row = {
            "매체": "Naver SA",
            "광고그룹": "형사_구속",
            "랜딩URL": "https://example.com/drug?utm=1",
        }

        result = ClassificationEngine(sample_index()).classify_row(row)

        self.assertEqual(result.category, "마약")
        self.assertEqual(result.matched_priority, 0)
        self.assertEqual(result.confidence, 1.0)

    def test_priority_uses_campaign_type_before_group_name(self):
        row = {
            "매체": "Meta",
            "광고그룹": "형사_구속",
            "랜딩URL": "https://example.com/criminal",
        }

        result = ClassificationEngine(sample_index()).classify_row(row)

        self.assertEqual(result.category, "Meta")
        self.assertEqual(result.matched_priority, 1)

    def test_keyword_rule_can_be_limited_by_campaign_type(self):
        row = {"매체": "Naver SA", "키워드": "이혼전문변호사"}

        result = ClassificationEngine(sample_index()).classify_row(row)

        self.assertEqual(result.category, "이혼")
        self.assertEqual(result.matched_priority, 3)

    def test_low_confidence_rule_does_not_use_ai_when_rule_matched(self):
        row = {
            "랜딩URL": "https://example.com/criminal",
            "광고 문구": "성범죄 사건 상담",
        }

        result = ClassificationEngine(sample_index(), ai_analyzer=FakeAIAnalyzer()).classify_row(row)

        self.assertEqual(result.category, "형사")
        self.assertEqual(result.matched_priority, 5)
        self.assertTrue(result.needs_review)

    def test_ai_is_used_only_when_no_rule_matches(self):
        row = {"광고 문구": "성범죄 사건 상담"}

        result = ClassificationEngine(sample_index(), ai_analyzer=FakeAIAnalyzer()).classify_row(row)

        self.assertEqual(result.category, "성범죄")
        self.assertEqual(result.matched_priority, 6)

    def test_user_correction_is_appended_without_mutating_original_index(self):
        index = sample_index()

        updated = append_user_correction(
            index,
            category="형사",
            evidence={"group_name": "형사_구속"},
            correction_id="correction-test",
            created_at="2026-06-25T00:00:00+09:00",
        )

        self.assertEqual(index["user_corrections"], [])
        self.assertEqual(updated["user_corrections"][0]["category"], "형사")
        self.assertEqual(updated["user_corrections"][0]["id"], "correction-test")

    def test_scope_filter_only_selects_index_without_classifying_by_scope(self):
        first = sample_index()
        second = sample_index()
        second["scope"] = {"brand_id": "brand_002", "account_ids": ["account_002"]}

        matches = filter_indexes_by_scope(
            [first, second],
            brand_id="brand_001",
            account_id="account_001",
        )

        self.assertEqual(matches, [first])

    def test_cleaner_writes_cleaned_failed_and_index_log_files(self):
        with TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            source = temp / "raw.csv"
            cleaned = temp / "cleaned.csv"
            failed = temp / "failed.csv"
            log = temp / "index-log.json"
            source.write_text(
                "매체,광고그룹,랜딩URL,불필요컬럼\n"
                "Naver SA,형사_구속,https://example.com/criminal,drop\n"
                "Naver SA,,https://unknown.example/path,drop\n",
                encoding="utf-8-sig",
            )

            result = ReportRowCleaner(sample_index()).clean_file(
                source,
                cleaned_path=cleaned,
                failed_path=failed,
                log_path=log,
            )

            self.assertEqual(result.total_rows, 2)
            self.assertEqual(result.cleaned_rows, 2)
            self.assertTrue(cleaned.exists())
            self.assertTrue(failed.exists())
            self.assertTrue(log.exists())
            self.assertIn("category", cleaned.read_text(encoding="utf-8-sig"))
            self.assertNotIn("불필요컬럼", cleaned.read_text(encoding="utf-8-sig"))
            self.assertIn("source_row_number", failed.read_text(encoding="utf-8-sig"))
            self.assertIn("applied_index_scope", log.read_text(encoding="utf-8"))

    def test_simple_rules_table_builds_index_without_json_editing(self):
        index = simple_rules_to_index(
            [
                {
                    "순위": "0",
                    "규칙": "강제 지정 URL",
                    "매칭값": "https://example.com/drug",
                    "카테고리": "마약",
                    "신뢰도": "1",
                    "사용": "O",
                },
                {
                    "순위": "2",
                    "규칙": "그룹명",
                    "매칭값": "형사",
                    "카테고리": "형사",
                    "신뢰도": "0.9",
                    "사용": "O",
                },
            ]
        )

        forced = ClassificationEngine(index).classify_row({"랜딩URL": "https://example.com/drug?x=1"})
        group = ClassificationEngine(index).classify_row({"광고그룹": "형사_구속"})

        self.assertEqual(forced.category, "마약")
        self.assertEqual(forced.matched_priority, 0)
        self.assertEqual(group.category, "형사")
        self.assertEqual(group.matched_priority, 2)

    def test_simple_rules_can_be_loaded_from_csv(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "rules.csv"
            path.write_text(
                "순위,규칙,매칭값,카테고리,신뢰도,사용\n"
                "4,캠페인명,브랜드,브랜드,0.85,O\n",
                encoding="utf-8-sig",
            )

            index = load_simple_rules_index(path)
            result = ClassificationEngine(index).classify_row({"캠페인": "브랜드 캠페인"})

            self.assertEqual(result.category, "브랜드")
            self.assertEqual(result.matched_priority, 4)

    def test_rule_table_helpers_append_and_delete_rules(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "rules.csv"

            appended = append_simple_rule(
                path,
                priority=0,
                match_value="https://example.com/drug",
                category="마약",
                memo="강제 URL",
            )
            rows = read_simple_rule_rows(path)

            self.assertEqual(appended["규칙"], "강제 지정 URL")
            self.assertEqual(rows[0]["카테고리"], "마약")

            removed = delete_simple_rule(path, one_based_index=1)

            self.assertEqual(removed["매칭값"], "https://example.com/drug")
            self.assertEqual(read_simple_rule_rows(path), [])

    def test_report_reader_skips_naver_title_row(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "naver.csv"
            path.write_text(
                '"형사_키워드_주간 보고서(2026.06.29.~2026.06.29.),1826631"\n'
                "일별,캠페인유형,URL,캠페인,광고그룹,키워드\n"
                "2026.06.29.,파워링크,https://example.com,C_성범죄,G_강간,카촬\n",
                encoding="utf-8-sig",
            )

            rows = read_report_rows(path)

            self.assertEqual(rows[0]["캠페인"], "C_성범죄")
            self.assertEqual(rows[0]["광고그룹"], "G_강간")

    def test_daily_report_builds_brand_sheet_with_rate_formulas(self):
        try:
            from openpyxl import load_workbook
        except ImportError:
            self.skipTest("openpyxl is not installed")

        with TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            raw = temp / "naver_thlaw_01_raw_20260629_20260629.csv"
            rules = temp / "rules.csv"
            output = temp / "daily.xlsx"

            raw.write_text(
                '"형사_키워드_주간 보고서(2026.06.29.~2026.06.29.),1826631"\n'
                "일별,캠페인유형,URL,PC/모바일 매체,캠페인,광고그룹,키워드,노출수,클릭수,총비용,총 전환수\n"
                "2026.06.29.,파워링크,https://example.com,PC,C_성범죄,G_강간,카촬,100,10,5000,2\n",
                encoding="utf-8-sig",
            )
            rules.write_text(
                "순위,규칙,매칭값,카테고리,신뢰도,사용,메모\n"
                "2,그룹명,강간,성범죄,0.9,O,\n",
                encoding="utf-8-sig",
            )

            result = build_daily_report(
                [
                    PipelineInput(
                        file_path=raw,
                        media="Naver",
                        account_name="태하 네이버",
                        brand_id="법무법인_태하",
                    )
                ],
                rules,
                output,
                append=False,
            )

            workbook = load_workbook(result.workbook_path, data_only=False)
            self.assertIn("법무법인_태하", workbook.sheetnames)
            sheet = workbook["법무법인_태하"]
            self.assertEqual(sheet["E2"].value, "성범죄")
            self.assertEqual(sheet["N2"].value, "=IFERROR(K2/J2,0)")
            self.assertEqual(sheet["O2"].value, "=IFERROR(M2/K2,0)")
            self.assertEqual(sheet["N2"].number_format, "0.00%")


if __name__ == "__main__":
    unittest.main()
