from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

from fia.config import SUMMARY_HEADING
from fia.models import Candidate, Evidence
from fia.parser import (
    _canonicalize_table_rows,
    _is_annual_report,
    choose_candidates,
    match_metric,
    normalize_text,
)


class ParserLayoutTests(unittest.TestCase):
    def test_annual_report_filename_wins_over_body_half_year_reference(self) -> None:
        path = Path("000568_泸州老窖_2022年年度报告.pdf")
        self.assertTrue(_is_annual_report("公司曾披露半年度报告", path))
        self.assertFalse(_is_annual_report("", Path("000568_泸州老窖_2022年半年度报告.pdf")))

    def test_same_year_evidence_beats_later_report_comparative_column(self) -> None:
        def candidate(report_year: int, status: str, source_priority: int) -> Candidate:
            evidence = Evidence(
                file_id=str(report_year),
                file_name=f"{report_year}年年度报告.pdf",
                report_year=report_year,
                page_number=8,
                page_count=100,
                page_width=600,
                page_height=800,
                bbox=(10, 10, 100, 30),
                section="主要会计数据",
                table_index=0,
                row_index=1,
                column_index=1,
                row_label="营业收入",
                column_label="2022年",
                extraction_method="pdfplumber_table",
            )
            return Candidate(
                metric_id="revenue",
                fiscal_year=2022,
                value=Decimal("100"),
                raw_value="100",
                normalized_unit="元",
                source_unit="元",
                report_year=report_year,
                restatement_status=status,
                source_priority=source_priority,
                evidence=evidence,
            )

        exact = candidate(2022, "current", 90)
        later_adjusted = candidate(2024, "adjusted", 100)
        selected, _ = choose_candidates([later_adjusted, exact])

        self.assertIs(selected[("revenue", 2022)], exact)
    def test_common_summary_heading_accepts_both_annual_report_templates(self) -> None:
        self.assertIn(SUMMARY_HEADING, normalize_text("六、主要会计数据和财务指标"))
        self.assertIn(SUMMARY_HEADING, normalize_text("七、近三年主要会计数据和财务指标"))

    def test_revenue_deduction_rows_are_not_misclassified_as_revenue(self) -> None:
        self.assertIsNone(match_metric("营业收入扣除金额（元）"))
        self.assertIsNone(match_metric("营业收入扣除后金额（元）"))
        self.assertEqual(match_metric("营业收入（元）"), "revenue")

    def test_oversegmented_rows_are_compacted_and_multiline_label_is_joined(self) -> None:
        rows = [
            ["", "", "", "", "2024年", "", "", "2023年", "", "", "本年比上年增减", "", "", "2022年", ""],
            ["", "归属于上市公司股东", "", "-33,672,271.06", "", "", "-33,997,049.54", "", "", "0.96%", "", "", "31,639,345.57", "", ""],
            ["", "的净利润（元）", "", "", "", "", "", "", "", "", "", "", "", "", ""],
        ]

        canonical, source_rows = _canonicalize_table_rows(rows)

        self.assertEqual(canonical[0], ["", "2024年", "2023年", "本年比上年增减", "2022年"])
        self.assertEqual(match_metric(canonical[1][0]), "net_profit")
        self.assertEqual(canonical[1][1], "-33,672,271.06")
        self.assertEqual(source_rows[1], [1, 2])


if __name__ == "__main__":
    unittest.main()
