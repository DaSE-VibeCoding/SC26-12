from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import fitz
import pdfplumber
import yaml

from fintrace.shared.company_resolver import normalize_company_code, resolve_company
from fintrace.shared.exceptions import FinTraceError, InputFileNotFoundError
from fintrace.shared.file_store import append_jsonl, write_json
from fintrace.shared.paths import configured_path, get_project_root, project_relative
from fintrace.shared.run_context import RunContext


class FinancialExtractionError(FinTraceError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, code="financial_extraction_error", **kwargs)


def _decimal(text: str) -> Decimal:
    try:
        return Decimal(text.replace(",", "").strip())
    except InvalidOperation as exc:
        raise FinancialExtractionError(f"Invalid financial value: {text}") from exc


def _indicator_rules() -> dict[str, Any]:
    path = get_project_root() / "configs" / "indicators.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))["indicators"]


def _compact(text: str | None) -> str:
    return re.sub(r"\s+", "", text or "")


def _find_indicator(label: str, rules: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    compact = _compact(label)
    for key, rule in rules.items():
        if any(_compact(alias) == compact for alias in rule["aliases"]):
            return key, rule
    return None


def _bbox_for_value(page: fitz.Page, raw_text: str) -> tuple[dict[str, float] | None, bool]:
    matches = page.search_for(raw_text)
    if not matches:
        return None, True
    rect = matches[0]
    height = page.rect.height
    return (
        {"x0": rect.x0, "y0": height - rect.y1, "x1": rect.x1, "y1": height - rect.y0},
        len(matches) != 1,
    )


def _write_csv(path: Path, facts: list[dict[str, Any]]) -> None:
    fields = [
        "fact_id",
        "company_code",
        "report_id",
        "indicator",
        "indicator_label",
        "period_label",
        "raw_value",
        "raw_unit",
        "normalized_value",
        "normalized_unit",
        "evidence_id",
        "confidence",
        "manual_review_required",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(facts)


def _viewer_html(pdf_path: str) -> str:
    template = Path(__file__).with_name("viewer_template.html").read_text(encoding="utf-8")
    return template.replace("__REPORT_PDF__", json.dumps(pdf_path, ensure_ascii=False))


def _validate_report_identity(
    first_page_text: str, company_code: str, report_year: int, report_type: str
) -> None:
    compact = _compact(first_page_text)
    expected_type = {
        "q1": "第一季度报告",
        "semiannual": "半年度报告",
        "q3": "第三季度报告",
        "annual": "年度报告",
    }[report_type]
    missing = []
    if company_code not in compact:
        missing.append("company_code")
    if str(report_year) not in compact:
        missing.append("report_year")
    if expected_type not in compact:
        missing.append("report_type")
    if missing:
        raise FinancialExtractionError(
            "Report identity does not match the supplied metadata.",
            step="validate_report_identity",
            details={"missing_or_mismatched": missing},
        )


def run_financial(
    company_input: str,
    report_pdf: Path,
    report_year: int,
    report_type: str,
) -> tuple[dict[str, Any], Path]:
    company_code, _ = normalize_company_code(company_input)
    context = RunContext(feature="financial", company_code=company_code)
    context.start()
    try:
        if not report_pdf.is_file():
            raise InputFileNotFoundError(f"Report PDF does not exist: {report_pdf}")
        company = resolve_company(company_input, report_year)
        raw = report_pdf.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        report_id = f"rpt_{company_code}_{digest[:16]}"
        step = "register_and_extract_pdf"
        context.start_step(step, {"report_pdf": project_relative(report_pdf), "sha256": digest})
        raw_dir = configured_path("raw_reports_dir") / company_code
        raw_dir.mkdir(parents=True, exist_ok=True)
        stored_pdf = raw_dir / f"{digest[:16]}_{report_pdf.name}"
        if not stored_pdf.exists():
            shutil.copy2(report_pdf, stored_pdf)

        document = fitz.open(report_pdf)
        if document.is_encrypted or document.page_count == 0:
            raise FinancialExtractionError("PDF is encrypted or empty.")
        _validate_report_identity(
            document[0].get_text("text"), company_code, report_year, report_type
        )
        pages = []
        for index, page in enumerate(document):
            pages.append(
                {
                    "page_number": index + 1,
                    "width": page.rect.width,
                    "height": page.rect.height,
                    "rotation": page.rotation,
                    "word_count": len(page.get_text("words")),
                }
            )
        write_json(context.processed_dir / step / "pages.json", pages)

        rules = _indicator_rules()
        facts: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []
        seen_facts: set[tuple[str, str]] = set()
        with pdfplumber.open(report_pdf) as pdf:
            for page_index in (0, 1):
                for table in pdf.pages[page_index].extract_tables():
                    table_text = _compact(" ".join(cell or "" for row in table for cell in row))
                    if not any(header in table_text for header in ("本报告期", "本报告期末")):
                        continue
                    for row in table:
                        if len(row) < 3:
                            continue
                        match = _find_indicator(row[0] or "", rules)
                        if not match:
                            continue
                        indicator, rule = match
                        for column, period_label in ((1, "current"), (2, "prior")):
                            fact_key = (indicator, period_label)
                            if fact_key in seen_facts:
                                continue
                            raw_value = row[column] if column < len(row) else None
                            if not raw_value or not re.search(r"\d", raw_value):
                                continue
                            value = _decimal(raw_value)
                            evidence_id = f"ev_{report_id}_{indicator}_{period_label}"
                            fact_id = f"fact_{report_id}_{indicator}_{period_label}"
                            bbox, review = _bbox_for_value(document[page_index], raw_value)
                            confidence = 0.95 if bbox and not review else 0.7
                            fact = {
                                "fact_id": fact_id,
                                "company_code": company_code,
                                "report_id": report_id,
                                "indicator": indicator,
                                "indicator_label": rule["label"],
                                "period_label": period_label,
                                "raw_value": raw_value,
                                "raw_unit": rule["unit"],
                                "normalized_value": str(value),
                                "normalized_unit": rule["unit"],
                                "evidence_id": evidence_id,
                                "confidence": confidence,
                                "manual_review_required": review,
                            }
                            facts.append(fact)
                            seen_facts.add(fact_key)
                            evidence.append(
                                {
                                    **fact,
                                    "report_file": project_relative(stored_pdf),
                                    "report_hash": digest,
                                    "page_number": page_index + 1,
                                    "page_width": document[page_index].rect.width,
                                    "page_height": document[page_index].rect.height,
                                    "coordinate_system": "pdf_points_origin_bottom_left",
                                    "bbox": bbox,
                                    "row_label": row[0],
                                    "column_label": period_label,
                                }
                            )
        document.close()
        if not facts:
            raise FinancialExtractionError("No configured financial indicators were extracted.")
        context.finish_step(step, {"report_id": report_id, "fact_count": len(facts)})

        traces = []
        by_indicator = {(fact["indicator"], fact["period_label"]): fact for fact in facts}
        for indicator, rule in rules.items():
            current = by_indicator.get((indicator, "current"))
            prior = by_indicator.get((indicator, "prior"))
            if not current or not prior or Decimal(prior["normalized_value"]) == 0:
                continue
            current_value = Decimal(current["normalized_value"])
            prior_value = Decimal(prior["normalized_value"])
            comparison = rule.get("comparison", "yoy")
            if comparison == "percentage_point_change":
                result = current_value - prior_value
                suffix = "较上期变动"
                formula = "current - prior"
                unit = "个百分点"
            else:
                result = (current_value - prior_value) / prior_value * Decimal(100)
                suffix = "较上年末变化" if comparison == "period_change" else "同比"
                formula = "(current - prior) / prior * 100"
                unit = "%"
            traces.append(
                {
                    "trace_id": f"trace_{report_id}_{indicator}_{comparison}",
                    "indicator": f"{indicator}_{comparison}",
                    "indicator_label": f"{rule['label']}{suffix}",
                    "comparison_type": comparison,
                    "formula_version": f"{comparison}_v1",
                    "formula": formula,
                    "result": str(result.quantize(Decimal("0.01"))),
                    "unit": unit,
                    "inputs": [current["evidence_id"], prior["evidence_id"]],
                }
            )

        output = context.output_dir
        _write_csv(output / "financial_facts.csv", facts)
        append_jsonl(output / "evidence_index.jsonl", evidence)
        append_jsonl(output / "indicator_traces.jsonl", traces)
        write_json(output / "pdf_highlights.json", evidence)
        write_json(
            output / "viewer_manifest.json",
            {
                "report_id": report_id,
                "report_file": project_relative(stored_pdf),
                "pages": pages,
                "default_evidence_id": evidence[0]["evidence_id"],
                "evidence_count": len(evidence),
            },
        )
        viewer_pdf_path = Path(os.path.relpath(stored_pdf, output)).as_posix()
        (output / "evidence_viewer.html").write_text(
            _viewer_html(viewer_pdf_path), encoding="utf-8"
        )
        (output / "analysis_summary.md").write_text(
            "# 财务分析摘要\n\n"
            + "\n".join(f"- {trace['indicator_label']}: {trace['result']}%" for trace in traces)
            + "\n",
            encoding="utf-8",
        )
        reviews = sum(bool(item["manual_review_required"]) for item in evidence)
        quality = {
            "status": "passed_with_warnings" if reviews else "passed",
            "fact_count": len(facts),
            "trace_count": len(traces),
            "evidence_count": len(evidence),
            "manual_review_count": reviews,
            "text_pdf": all(page["word_count"] > 0 for page in pages),
        }
        write_json(output / "quality_report.json", quality)
        context.warning_count += reviews + int(company.company_info_fallback)
        context.finish(with_warnings=context.warning_count > 0)
        append_jsonl(
            configured_path("indexes_dir") / "financial_runs.jsonl",
            [
                {
                    "run_id": context.run_id,
                    "company_code": company_code,
                    "report_id": report_id,
                    "output": project_relative(output),
                    "created_at": datetime.now(UTC),
                }
            ],
        )
        return quality, output
    except FinTraceError as exc:
        context.fail(exc.to_dict())
        raise
