from __future__ import annotations

import unittest

from index_classifier.brand_settings import (
    BrandProfile,
    UI_TYPE_ILRO,
    UI_TYPE_OHYUN,
    UI_TYPE_TAEHA,
    rule_for_profile,
    ui_type_for_brand,
    ui_type_for_profile,
)
from index_classifier.brand_template_writer import write_brand_template
from index_classifier.brand_upload import DEFAULT_BRAND_RULES, build_sheet_targets


class UiTypeClassificationTests(unittest.TestCase):
    def test_ui_type_for_profile_single_sheet_is_ilro(self):
        profile = BrandProfile(name="신규브랜드A", category_mode="single_sheet")
        self.assertEqual(ui_type_for_profile(profile), UI_TYPE_ILRO)

    def test_ui_type_for_profile_rolling_is_taeha(self):
        profile = BrandProfile(name="신규브랜드B", category_mode="category_sheets", sheet_mode="rolling_day_sheets")
        self.assertEqual(ui_type_for_profile(profile), UI_TYPE_TAEHA)

    def test_ui_type_for_profile_fixed_offset_is_ohyun(self):
        profile = BrandProfile(name="신규브랜드C", category_mode="category_sheets", sheet_mode="fixed_today_offset")
        self.assertEqual(ui_type_for_profile(profile), UI_TYPE_OHYUN)

    def test_ui_type_for_brand_uses_default_rules_first_for_ohyun(self):
        # 오현은 DEFAULT_BRAND_RULES에 등록되어 있으므로, 저장된 프로필의
        # category_mode/sheet_mode 필드가 비어 있거나(과거 프로필) 잘못돼 있어도
        # 항상 오현형으로 분류되어야 한다.
        stale_profile = BrandProfile(name="법무법인 오현")  # 기본값(category_sheets/fixed_today_offset)
        profiles = {"법무법인 오현": stale_profile}
        self.assertEqual(ui_type_for_brand("법무법인 오현", profiles), UI_TYPE_OHYUN)

    def test_ui_type_for_brand_uses_default_rules_first_for_taeha(self):
        # 태하는 DEFAULT_BRAND_RULES 상 rolling_day_sheets이므로, 프로필의
        # 필드가 기본값(fixed_today_offset)으로 저장돼 있어도 태하형으로 분류되어야
        # 한다. 이게 어긋나면 GUI가 태하를 오현 탭에 잘못 띄우게 된다.
        stale_profile = BrandProfile(name="법무법인 태하")  # 기본값(category_sheets/fixed_today_offset)
        profiles = {"법무법인 태하": stale_profile}
        self.assertEqual(ui_type_for_brand("법무법인 태하", profiles), UI_TYPE_TAEHA)

    def test_ui_type_for_brand_falls_back_to_profile_for_new_brand(self):
        profile = BrandProfile(name="신규브랜드D", category_mode="single_sheet")
        profiles = {"신규브랜드D": profile}
        self.assertEqual(ui_type_for_brand("신규브랜드D", profiles), UI_TYPE_ILRO)

    def test_ui_type_for_brand_unknown_defaults_to_ohyun(self):
        self.assertEqual(ui_type_for_brand("존재하지않는브랜드", {}), UI_TYPE_OHYUN)


class RuleForProfileTests(unittest.TestCase):
    def test_existing_brand_always_uses_default_rules(self):
        # 오현 프로필에 엉뚱한 카테고리가 저장되어 있어도, DEFAULT_BRAND_RULES가
        # 항상 우선한다 (기존 동작 보존).
        profile = BrandProfile(name="법무법인 오현", categories="엉뚱한카테고리")
        rule = rule_for_profile(profile)
        self.assertIs(rule, DEFAULT_BRAND_RULES["법무법인 오현"])

    def test_new_brand_rolling_day_sheets_without_code_change(self):
        # 태하형과 동일한 rolling_day_sheets 모드를, DEFAULT_BRAND_RULES에 전혀
        # 없는 신규 브랜드에 대해 UI/profile 설정만으로 만들 수 있어야 한다.
        profile = BrandProfile(
            name="신규 태하형 브랜드",
            category_mode="category_sheets",
            sheet_mode="rolling_day_sheets",
            categories="형사, 이혼",
            google_categories="형사",
            rolling_days=5,
            today_offset=2,
        )
        rule = rule_for_profile(profile)
        self.assertIsNotNone(rule)
        self.assertEqual(rule.mode, "rolling_day_sheets")
        self.assertEqual(rule.categories, ("형사", "이혼"))
        self.assertEqual(rule.google_categories, ("형사",))
        self.assertEqual(rule.rolling_days, 5)
        self.assertFalse(rule.use_today_formula)

        targets = build_sheet_targets(rule, "2026-07-08")
        sheet_names = {target.sheet_name for target in targets}
        # rolling_days=5 -> offsets 1..5 (+ weekend catchup if run_date is Monday;
        # 2026-07-08 is a Wednesday, so no catchup, just 1..5).
        self.assertIn("형사(1일)", sheet_names)
        self.assertIn("형사(5일)", sheet_names)
        self.assertIn("형사(1일)_구글", sheet_names)

    def test_new_brand_fixed_today_offset_without_code_change(self):
        profile = BrandProfile(
            name="신규 오현형 브랜드",
            category_mode="category_sheets",
            sheet_mode="fixed_today_offset",
            categories="형사, 이혼, 성범죄",
            today_offset=1,
        )
        rule = rule_for_profile(profile)
        self.assertIsNotNone(rule)
        self.assertEqual(rule.mode, "fixed_today_offset")
        self.assertEqual(rule.categories, ("형사", "이혼", "성범죄"))
        self.assertTrue(rule.use_today_formula)

        targets = build_sheet_targets(rule, "2026-07-08")
        sheet_names = {target.sheet_name for target in targets}
        # run_date=2026-07-08, today_offset=1 -> report_date=2026-07-07 -> day=7
        self.assertIn("형사7일", sheet_names)

    def test_new_brand_single_sheet_without_categories_returns_all_marker(self):
        profile = BrandProfile(
            name="신규 일로형 브랜드",
            category_mode="single_sheet",
            categories="",
        )
        rule = rule_for_profile(profile)
        self.assertIsNotNone(rule)
        self.assertEqual(rule.categories, ("__ALL__",))

    def test_new_brand_category_sheets_without_categories_returns_none(self):
        # category_mode가 category_sheets인데 categories가 비어 있으면, 호출부가
        # 기존 CSV 기반 카테고리 추론 fallback(_brand_rule_for_upload)을 쓸 수
        # 있도록 None을 반환해야 한다.
        profile = BrandProfile(
            name="카테고리 없는 신규 브랜드",
            category_mode="category_sheets",
            categories="",
        )
        self.assertIsNone(rule_for_profile(profile))


class WriteBrandTemplateRuleOverrideTests(unittest.TestCase):
    def test_write_brand_template_uses_override_rule_instead_of_inference(self):
        # write_brand_template에 rule을 명시적으로 넘기면, brand 이름 기반의
        # _brand_rule_for_upload() 추론(카테고리를 CSV에서 그러모으는 fallback)을
        # 완전히 건너뛰고 override rule을 그대로 써야 한다.
        try:
            from openpyxl import Workbook
        except ImportError:
            self.skipTest("openpyxl not available")

        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp_dir:
            template_path = Path(tmp_dir) / "template.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "형사(1일)"
            sheet.append(["키워드", "노출수", "클릭수", "클릭률", "클릭비용", "총비용", "노출순위"])
            sheet.append(["", "", "", "", "", "", ""])
            workbook.save(template_path)

            rows = [
                {
                    "date": "20260707",
                    "media": "naver",
                    "category": "형사",
                    "campaign_type": "",
                    "keyword": "테스트키워드",
                    "impressions": "100",
                    "clicks": "10",
                    "cost": "5000",
                    "rank": "1",
                }
            ]

            override_rule_profile = BrandProfile(
                name="override 테스트 브랜드",
                category_mode="category_sheets",
                sheet_mode="rolling_day_sheets",
                categories="형사",
                rolling_days=1,
                today_offset=1,
            )
            rule = rule_for_profile(override_rule_profile)
            self.assertIsNotNone(rule)

            output_path = Path(tmp_dir) / "output.xlsx"
            result = write_brand_template(
                brand="override 테스트 브랜드",  # DEFAULT_BRAND_RULES에 없는 브랜드
                template_path=template_path,
                output_path=output_path,
                rows=rows,
                run_date="2026-07-08",
                rule=rule,
            )
            # rolling_day_sheets 모드이므로 시트명이 "형사(1일)" 형식이어야 하고,
            # 이 시트가 템플릿에 있으므로 행이 반영되어야 한다.
            self.assertEqual(result.written_rows, 1)
            self.assertIn("형사(1일)", result.touched_sheets)


if __name__ == "__main__":
    unittest.main()
