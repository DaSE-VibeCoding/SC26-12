from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable

from .config import METRIC_BY_ID, SUPPORTED_YEAR_MAX, SUPPORTED_YEAR_MIN
from .models import Candidate, SourceDocument, decimal_text
from .parser import choose_candidates, extract_document_candidates, inspect_document


LOGGER = logging.getLogger(__name__)
DISPLAY_ORDER = (
    "revenue",
    "profit_total",
    "net_profit",
    "deducted_net_profit",
    "operating_cash_flow",
    "net_assets",
    "total_assets",
    "share_capital",
    "basic_eps",
    "diluted_eps",
    "deducted_eps",
    "roe",
    "deducted_roe",
)


def _process_path(path: Path) -> tuple[SourceDocument, list[Candidate]]:
    document = inspect_document(path)
    extracted = extract_document_candidates(document) if document.annual_report else []
    return document, extracted


def _quantize(value: Decimal, digits: str = "0.01") -> Decimal:
    return value.quantize(Decimal(digits), rounding=ROUND_HALF_UP)


def _display_value(value: Decimal, kind: str) -> str:
    if kind == "amount":
        converted = _quantize(value / Decimal("100000000"))
        return f"{converted:,.2f} 亿元"
    if kind == "eps":
        return f"{_quantize(value):,.2f} 元/股"
    return f"{_quantize(value):,.2f}%"


def _change(current: Candidate, previous: Candidate | None, kind: str) -> tuple[str | None, str, bool, str]:
    if previous is None:
        return None, "—", False, "缺少上年同口径基数"
    if current.restatement_status == "adjusted" and previous.restatement_status != "adjusted":
        return None, "—", False, "本年采用调整后数，但上年没有同口径调整后基数"
    if kind == "percent":
        value = current.value - previous.value
        sign = "+" if value > 0 else ""
        return decimal_text(value), f"{sign}{_quantize(value):.2f} 个百分点", True, ""
    if previous.value <= 0:
        return None, "—", False, "上年值非正，同比比例不具备可解释性"
    value = (current.value - previous.value) / previous.value * Decimal("100")
    sign = "+" if value > 0 else ""
    return decimal_text(value), f"{sign}{_quantize(value):.2f}%", True, ""


def _alternative_payload(candidate: Candidate) -> dict[str, Any]:
    return {
        "value": decimal_text(candidate.value),
        "raw_value": candidate.raw_value,
        "report_year": candidate.report_year,
        "restatement_status": candidate.restatement_status,
        "source_section": candidate.evidence.section,
        "file_name": candidate.evidence.file_name,
        "page_number": candidate.evidence.page_number,
    }


class AnalysisService:
    def __init__(self, result_dir: Path):
        self.result_dir = result_dir
        self.result_dir.mkdir(parents=True, exist_ok=True)

    def analyze_paths(self, paths: Iterable[Path]) -> dict[str, Any]:
        resolved_paths = sorted({Path(item).resolve() for item in paths}, key=lambda item: item.name)
        started = time.perf_counter()
        LOGGER.info("PDF 分析开始：files=%d paths=%s", len(resolved_paths), [str(path) for path in resolved_paths])
        documents: list[SourceDocument] = []
        candidates: list[Candidate] = []

        worker_count = min(4, max(1, len(resolved_paths)))
        if worker_count == 1:
            processed = [_process_path(resolved_paths[0])] if resolved_paths else []
        else:
            with ProcessPoolExecutor(max_workers=worker_count) as executor:
                processed = list(executor.map(_process_path, resolved_paths))
        for document, extracted in processed:
            documents.append(document)
            candidates.extend(extracted)
            LOGGER.info(
                "PDF 解析完成：file=%s company=%s report_year=%s pages=%s annual=%s candidates=%d warnings=%d",
                document.file_name,
                document.company_name,
                document.report_year,
                document.page_count,
                document.annual_report,
                len(extracted),
                len(document.warnings),
            )

        selected, grouped = choose_candidates(candidates)
        report_years = sorted(
            {
                document.report_year
                for document in documents
                if SUPPORTED_YEAR_MIN <= document.report_year <= SUPPORTED_YEAR_MAX
            }
        )
        company_counts = Counter(document.company_name for document in documents if document.company_name)
        company_name = company_counts.most_common(1)[0][0] if company_counts else "未知公司"

        warnings: list[str] = []
        company_keys = {
            re.sub(
                r"(?:股份有限公司|有限责任公司|有限公司)$",
                "",
                re.sub(r"[（(]控股[）)]", "", company.replace(" ", "")),
            )
            for company in company_counts
        }
        if len(company_keys) > 1:
            raise ValueError("检测到多家公司年报，请一次只选择同一家公司的文件。")
        for document in documents:
            warnings.extend(f"{document.file_name}：{item}" for item in document.warnings)

        metrics_payload: list[dict[str, Any]] = []
        evidence_index: list[dict[str, Any]] = []
        found_cells = 0
        for metric_id in DISPLAY_ORDER:
            definition = METRIC_BY_ID[metric_id]
            values: dict[str, Any] = {}
            for year in report_years:
                candidate = selected.get((metric_id, year))
                if candidate is None:
                    values[str(year)] = {
                        "year": year,
                        "status": "missing",
                        "display_value": "未披露",
                        "change_display": "—",
                        "comparable": False,
                        "reason": "在指定摘要表及允许的补充来源中未可靠定位",
                    }
                    continue
                found_cells += 1
                previous = selected.get((metric_id, year - 1))
                change_value, change_display, comparable, reason = _change(
                    candidate, previous, definition.kind
                )
                options = sorted(grouped[(metric_id, year)], key=lambda item: item.score, reverse=True)
                unique_values = {item.value for item in options}
                has_restatement = any(item.restatement_status == "adjusted" for item in options)
                if len(unique_values) > 1 and not has_restatement:
                    warnings.append(f"{definition.short_label}{year}年存在跨报告差异，已选择优先级最高证据。")
                evidence = candidate.evidence.to_dict()
                evidence_is_same_year = candidate.evidence.report_year == year
                evidence_index.append(
                    {
                        "metric_id": metric_id,
                        "fiscal_year": year,
                        "value": decimal_text(candidate.value),
                        "evidence": evidence,
                    }
                )
                values[str(year)] = {
                    "year": year,
                    "status": "ok",
                    "value": decimal_text(candidate.value),
                    "raw_value": candidate.raw_value,
                    "display_value": _display_value(candidate.value, definition.kind),
                    "normalized_unit": candidate.normalized_unit,
                    "source_unit": candidate.source_unit,
                    "change_value": change_value,
                    "change_display": change_display,
                    "change_kind": "percentage_point" if definition.kind == "percent" else "relative_percent",
                    "comparable": comparable,
                    "reason": reason,
                    "restatement_status": candidate.restatement_status,
                    "is_fallback": candidate.source_priority < 100,
                    "confidence": 0.90 if candidate.source_priority < 100 else 0.99 if candidate.restatement_status == "adjusted" else 0.97,
                    "evidence_report_year": candidate.evidence.report_year,
                    "evidence_is_same_year": evidence_is_same_year,
                    "evidence": evidence,
                    "alternatives": [_alternative_payload(item) for item in options[1:]],
                }
            metrics_payload.append(
                {
                    "metric_id": metric_id,
                    "label": definition.label,
                    "short_label": definition.short_label,
                    "kind": definition.kind,
                    "display_unit": "亿元" if definition.kind == "amount" else "元/股" if definition.kind == "eps" else "%",
                    "values": values,
                }
            )

        expected_cells = len(DISPLAY_ORDER) * len(report_years)
        result = {
            "schema_version": "1.0",
            "company_name": company_name,
            "years": report_years,
            "latest_year": max(report_years) if report_years else None,
            "accounting_scope": "合并口径",
            "value_policy": "same_year_report_preferred",
            "metrics": metrics_payload,
            "documents": [
                {
                    **asdict(document),
                    "path": str(document.path),
                    "pdf_url": f"/api/files/{document.file_id}",
                }
                for document in documents
            ],
            "quality": {
                "expected_cells": expected_cells,
                "found_cells": found_cells,
                "completeness": round(found_cells / expected_cells, 4) if expected_cells else 0,
                "warnings": list(dict.fromkeys(warnings)),
            },
        }
        self._write_artifacts(result, evidence_index, documents)
        LOGGER.info(
            "PDF 分析完成：company=%s years=%s candidates=%d cells=%d/%d warnings=%d elapsed=%.3fs",
            company_name,
            report_years,
            len(candidates),
            found_cells,
            expected_cells,
            len(result["quality"]["warnings"]),
            time.perf_counter() - started,
        )
        return result

    def _write_artifacts(
        self,
        result: dict[str, Any],
        evidence_index: list[dict[str, Any]],
        documents: list[SourceDocument],
    ) -> None:
        viewer_manifest = {
            "schema_version": "1.0",
            "files": [
                {
                    "file_id": document.file_id,
                    "file_name": document.file_name,
                    "report_year": document.report_year,
                    "page_count": document.page_count,
                    "pdf_url": f"/api/files/{document.file_id}",
                }
                for document in documents
            ],
        }
        payloads = {
            "normalized_financials.json": result,
            "pdf_highlights.json": evidence_index,
            "viewer_manifest.json": viewer_manifest,
        }
        for file_name, payload in payloads.items():
            target = self.result_dir / file_name
            target.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            LOGGER.info("结果文件已写入：file=%s", target)
