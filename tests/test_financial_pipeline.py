import csv
import json
from pathlib import Path

import pytest

from fintrace.financial.pipeline import FinancialExtractionError, run_financial

REPORT = Path("input_example/贵州茅台：贵州茅台2026年第一季度报告.pdf").resolve()


@pytest.fixture(scope="module")
def financial_result() -> tuple[dict, Path]:
    return run_financial("600519", REPORT, 2026, "q1")


def test_financial_pipeline_extracts_traceable_facts(financial_result: tuple[dict, Path]) -> None:
    quality, output = financial_result
    with (output / "financial_facts.csv").open(encoding="utf-8-sig") as handle:
        facts = list(csv.DictReader(handle))
    evidence = [
        json.loads(line)
        for line in (output / "evidence_index.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert quality["fact_count"] == 16
    assert len(facts) == len(evidence) == 16
    assert {fact["indicator"] for fact in facts} >= {
        "revenue",
        "net_profit_parent",
        "operating_cash_flow",
        "total_assets",
    }
    assert all(item["page_number"] in {1, 2} for item in evidence)
    assert all(item["coordinate_system"] == "pdf_points_origin_bottom_left" for item in evidence)


def test_derived_metrics_reference_two_evidence_items(financial_result: tuple[dict, Path]) -> None:
    _, output = financial_result
    traces = [
        json.loads(line)
        for line in (output / "indicator_traces.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(traces) == 8
    assert all(len(trace["inputs"]) == 2 for trace in traces)
    roe = next(trace for trace in traces if trace["indicator"].startswith("roe_weighted"))
    assert roe["comparison_type"] == "percentage_point_change"
    assert roe["result"] == "-0.35"


def test_viewer_contains_canvas_coordinate_highlighting(
    financial_result: tuple[dict, Path],
) -> None:
    _, output = financial_result
    viewer = (output / "evidence_viewer.html").read_text(encoding="utf-8")
    assert "pdfjsLib.getDocument" in viewer
    assert "evidence.bbox.x0" in viewer
    assert "pdf_highlights.json" in viewer


def test_report_identity_mismatch_is_rejected() -> None:
    with pytest.raises(FinancialExtractionError, match="does not match"):
        run_financial("600519", REPORT, 2026, "annual")
