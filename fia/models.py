from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any


@dataclass
class SourceDocument:
    file_id: str
    path: Path
    file_name: str
    company_name: str
    report_year: int
    page_count: int
    annual_report: bool
    warnings: list[str] = field(default_factory=list)


@dataclass
class Evidence:
    file_id: str
    file_name: str
    report_year: int
    page_number: int
    page_count: int
    page_width: float
    page_height: float
    bbox: tuple[float, float, float, float]
    section: str
    table_index: int | None
    row_index: int | None
    column_index: int | None
    row_label: str
    column_label: str
    extraction_method: str

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        x0, top, x1, bottom = self.bbox
        result["bbox_pct"] = {
            "left": x0 / self.page_width,
            "top": top / self.page_height,
            "width": (x1 - x0) / self.page_width,
            "height": (bottom - top) / self.page_height,
        }
        result["pdf_url"] = f"/api/files/{self.file_id}"
        return result


@dataclass
class Candidate:
    metric_id: str
    fiscal_year: int
    value: Decimal
    raw_value: str
    normalized_unit: str
    source_unit: str
    report_year: int
    restatement_status: str
    source_priority: int
    evidence: Evidence

    @property
    def score(self) -> tuple[int, int, int, int, int]:
        restatement_score = {
            "adjusted": 40,
            "current": 20,
            "comparative": 10,
            "adjustment_before": 0,
        }.get(self.restatement_status, 0)
        exact_report_year = int(self.report_year == self.fiscal_year)
        year_distance = -abs(self.report_year - self.fiscal_year)
        # “某年度”的查看证据必须优先指向该年度自己的年报。
        # 仅当本年报告没有可靠候选值时，才允许使用跨年比较列补充。
        return exact_report_year, self.source_priority, restatement_score, year_distance, self.report_year


def decimal_text(value: Decimal) -> str:
    return format(value, "f")
