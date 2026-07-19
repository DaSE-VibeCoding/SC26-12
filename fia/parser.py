from __future__ import annotations

import hashlib
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

import pdfplumber
from pypdf import PdfReader

from .config import (
    METRICS,
    SUMMARY_HEADING,
    SUPPORTED_YEAR_MAX,
    SUPPORTED_YEAR_MIN,
    UNIT_MULTIPLIERS,
)
from .models import Candidate, Evidence, SourceDocument


_PUNCTUATION_RE = re.compile(r"[\s\u3000,，。:：;；()（）\[\]【】/／%％·•_-]+")
_YEAR_RE = re.compile(r"(20\d{2})\s*年?")
_NUMBER_RE = re.compile(r"\(?[-−－—]?\s*\d[\d,，]*(?:\.\d+)?\)?")


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return _PUNCTUATION_RE.sub("", value).replace("“", "").replace("”", "")


_ALIAS_INDEX = sorted(
    (
        (normalize_text(alias), metric.metric_id)
        for metric in METRICS
        for alias in metric.aliases
    ),
    key=lambda item: len(item[0]),
    reverse=True,
)


def match_metric(row_label: str | None) -> str | None:
    normalized = normalize_text(row_label)
    if not normalized:
        return None
    if (
        "扣除与主营业务无关" in normalized
        or "不具备商业实质" in normalized
        or normalized.startswith("营业收入扣除")
    ):
        return None
    for alias, metric_id in _ALIAS_INDEX:
        if alias and alias in normalized:
            return metric_id
    return None


def parse_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    text = value.strip()
    if not text or text in {"-", "—", "–", "－", "不适用", "无"}:
        return None
    match = _NUMBER_RE.search(text)
    if not match:
        return None
    token = match.group(0).replace(",", "").replace("，", "").replace(" ", "")
    negative = token.startswith("(") and token.endswith(")")
    token = token.strip("()").replace("−", "-").replace("－", "-").replace("—", "-")
    try:
        result = Decimal(token)
    except InvalidOperation:
        return None
    return -result if negative and result > 0 else result


def stable_file_id(path: Path) -> str:
    material = f"{path.resolve()}::{path.stat().st_size}::{path.stat().st_mtime_ns}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]


def _detect_company(first_text: str, path: Path) -> str:
    lines = [line.strip() for line in first_text.splitlines() if line.strip()]
    for line in lines[:30]:
        compact = re.sub(r"\s+", "", line)
        match = re.search(r"([\u4e00-\u9fffA-Za-z0-9（）()·]{2,40}(?:股份有限公司|有限责任公司))", compact)
        if match and "会计师事务所" not in match.group(1):
            return match.group(1)
    stem = path.stem
    if "：" in stem:
        return stem.split("：", 1)[0]
    return re.sub(r"20\d{2}年年度报告.*$", "", stem).strip("：:_- ") or "未知公司"


def _is_annual_report(first_text: str, path: Path) -> bool:
    compact_text = normalize_text(first_text)
    compact_stem = normalize_text(path.stem)
    excluded_markers = ("半年度报告", "年度报告摘要")
    name_confirms_annual = "年度报告" in compact_stem and not any(
        marker in compact_stem for marker in excluded_markers
    )
    body_confirms_annual = "年度报告" in compact_text and not any(
        marker in compact_text for marker in excluded_markers
    )
    # 巨潮归档文件名已经过严格年报标题筛选。正文前几页可能提及
    # “半年度报告”，不能因此否定文件名明确标识的完整年度报告。
    return name_confirms_annual or body_confirms_annual


def inspect_document(path: Path) -> SourceDocument:
    with pdfplumber.open(path) as pdf:
        first_pages = []
        for page in pdf.pages[: min(8, len(pdf.pages))]:
            first_pages.append(page.extract_text() or "")
        first_text = "\n".join(first_pages)
        compact = normalize_text(first_text)
        year_match = re.search(r"(20\d{2})年年度报告", compact)
        if not year_match:
            year_match = re.search(r"(20\d{2})年", path.stem)
        report_year = int(year_match.group(1)) if year_match else 0
        annual = _is_annual_report(first_text, path)
        warnings: list[str] = []
        if not annual:
            warnings.append("未确认该文件为年度报告，已跳过指标提取。")
        if report_year and not (SUPPORTED_YEAR_MIN <= report_year <= SUPPORTED_YEAR_MAX):
            warnings.append(
                f"报告年度{report_year}超出默认支持区间{SUPPORTED_YEAR_MIN}-{SUPPORTED_YEAR_MAX}。"
            )
        if not first_text.strip():
            warnings.append("PDF首页未提取到文本，文件可能为扫描件，需要先配置OCR。")
        return SourceDocument(
            file_id=stable_file_id(path),
            path=path,
            file_name=path.name,
            company_name=_detect_company(first_text, path),
            report_year=report_year,
            page_count=len(pdf.pages),
            annual_report=annual,
            warnings=warnings,
        )


def _table_unit(page_text: str, table_top: float, page) -> str:
    search_text = page_text
    try:
        crop_top = max(0.0, table_top - 90.0)
        cropped = page.crop((0, crop_top, page.width, table_top)).extract_text() or ""
        if cropped:
            search_text = cropped + "\n" + page_text
    except Exception:
        pass
    matches = re.findall(r"单位\s*[:：]\s*(百万元|万元|千元|亿元|元)", search_text)
    return matches[0] if matches else "元"


def _header_year_columns(rows: list[list[str | None]], data_start: int, report_year: int):
    header_rows = rows[:data_start]
    max_columns = max((len(row) for row in rows), default=0)
    columns: dict[int, tuple[int, str, str]] = {}
    for column_index in range(1, max_columns):
        parts = []
        for row in header_rows:
            cell = row[column_index] if column_index < len(row) else None
            if cell:
                parts.append(cell.replace("\n", ""))
        label = " / ".join(parts)
        year_match = _YEAR_RE.search(label)
        status = ""
        if "调整后" in label:
            status = "adjusted"
        elif "调整前" in label:
            status = "adjustment_before"
        if year_match:
            year = int(year_match.group(1))
        elif status and (column_index - 1) in columns:
            year = columns[column_index - 1][0]
        else:
            continue
        if not status:
            status = "current" if year == report_year else "comparative"
        columns[column_index] = (year, status, label or f"{year}年")
    return columns


def _canonicalize_table_rows(
    rows: list[list[str | None]],
) -> tuple[list[list[str | None]], list[list[int]]]:
    """Collapse PDF tables whose visual cells were split into many empty columns.

    Newer cninfo PDFs occasionally expose a five-column table as 9-15 columns,
    with the label and value sitting immediately before the visual column's
    header.  They can also split one row label over several physical rows.  We
    compact only tables that exhibit this over-segmentation, leaving ordinary
    tables (including restatement layouts with meaningful blanks) untouched.
    """
    max_columns = max((len(row) for row in rows), default=0)
    cell_count = sum(len(row) for row in rows)
    blank_count = sum(1 for row in rows for cell in row if not (cell or "").strip())
    oversegmented = max_columns >= 8 and cell_count > 0 and blank_count / cell_count >= 0.45
    if not oversegmented:
        return [list(row) for row in rows], [[index] for index in range(len(rows))]

    canonical: list[list[str | None]] = []
    source_rows: list[list[int]] = []
    for original_index, row in enumerate(rows):
        compact = [cell for cell in row if (cell or "").strip()]
        if not compact:
            continue
        first = compact[0] or ""
        if _YEAR_RE.search(first) and not match_metric(first):
            compact.insert(0, "")

        # A single text cell after a numeric row is normally the continuation
        # of a label broken across physical PDF rows (not a new data row).
        if len(compact) == 1 and canonical:
            previous = canonical[-1]
            previous_has_value = any(parse_decimal(cell) is not None for cell in previous[1:])
            continuation = compact[0] or ""
            combined = f"{previous[0] or ''}{continuation}"
            normalized = normalize_text(combined)
            looks_like_metric = bool(match_metric(combined)) or any(
                alias.startswith(normalized) or normalized.startswith(alias)
                for alias, _metric_id in _ALIAS_INDEX
            )
            looks_like_deducted_return = "扣除非经常性损益后归属于" in normalized
            if previous_has_value and (looks_like_metric or looks_like_deducted_return):
                previous[0] = combined
                source_rows[-1].append(original_index)
                continue

        canonical.append(compact)
        source_rows.append([original_index])
    return canonical, source_rows


def _combined_row_bbox(table, row_indexes: list[int]) -> tuple[float, float, float, float]:
    bboxes = [table.rows[index].bbox for index in row_indexes]
    return (
        min(item[0] for item in bboxes),
        min(item[1] for item in bboxes),
        max(item[2] for item in bboxes),
        max(item[3] for item in bboxes),
    )


def _find_summary_pages(pdf) -> list[int]:
    matches: list[int] = []
    for page_index, page in enumerate(pdf.pages[: min(35, len(pdf.pages))]):
        text = page.extract_text() or ""
        if SUMMARY_HEADING in normalize_text(text):
            matches.append(page_index)
    return matches


def extract_summary_candidates(document: SourceDocument) -> list[Candidate]:
    if not document.annual_report or not document.report_year:
        return []
    candidates: list[Candidate] = []
    with pdfplumber.open(document.path) as pdf:
        summary_starts = _find_summary_pages(pdf)
        if not summary_starts:
            document.warnings.append(
                "未定位到“主要会计数据和财务指标”章节，未对未知表格进行猜测。"
            )
            return candidates
        page_indexes = sorted(
            {
                page_index
                for start in summary_starts
                for page_index in range(start, min(start + 3, len(pdf.pages)))
            }
        )
        carried_header_rows: list[list[str | None]] | None = None
        for page_index in page_indexes:
            page = pdf.pages[page_index]
            page_text = page.extract_text() or ""
            try:
                tables = page.find_tables()
            except Exception as exc:
                document.warnings.append(f"第{page_index + 1}页表格识别失败：{exc}")
                continue
            for table_index, table in enumerate(tables):
                rows, source_rows = _canonicalize_table_rows(table.extract() or [])
                data_rows = [index for index, row in enumerate(rows) if row and match_metric(row[0])]
                if not data_rows:
                    header_text = normalize_text(" ".join(cell or "" for row in rows for cell in row))
                    if (
                        "主要会计数据" in header_text or "主要财务指标" in header_text
                    ) and any(_YEAR_RE.search(cell or "") for row in rows for cell in row):
                        carried_header_rows = rows
                    continue
                data_start = min(data_rows)
                if data_start == 0 and carried_header_rows:
                    year_columns = _header_year_columns(
                        carried_header_rows + rows,
                        len(carried_header_rows),
                        document.report_year,
                    )
                    carried_header_rows = None
                else:
                    year_columns = _header_year_columns(rows, data_start, document.report_year)
                if not year_columns:
                    continue
                source_unit = _table_unit(page_text, table.bbox[1], page)
                for row_index in data_rows:
                    row = rows[row_index]
                    metric_id = match_metric(row[0])
                    if not metric_id:
                        continue
                    metric_kind = next(metric.kind for metric in METRICS if metric.metric_id == metric_id)
                    for column_index, (year, status, column_label) in year_columns.items():
                        if column_index >= len(row):
                            continue
                        parsed = parse_decimal(row[column_index])
                        if parsed is None:
                            continue
                        multiplier = UNIT_MULTIPLIERS.get(source_unit, 1) if metric_kind == "amount" else 1
                        normalized = parsed * multiplier
                        original_rows = source_rows[row_index]
                        bbox = _combined_row_bbox(table, original_rows)
                        evidence = Evidence(
                            file_id=document.file_id,
                            file_name=document.file_name,
                            report_year=document.report_year,
                            page_number=page_index + 1,
                            page_count=document.page_count,
                            page_width=float(page.width),
                            page_height=float(page.height),
                            bbox=tuple(float(value) for value in bbox),
                            section="七、近三年主要会计数据和财务指标",
                            table_index=table_index,
                            row_index=original_rows[0],
                            column_index=column_index,
                            row_label=(row[0] or "").replace("\n", ""),
                            column_label=column_label,
                            extraction_method="pdf_table",
                        )
                        candidates.append(
                            Candidate(
                                metric_id=metric_id,
                                fiscal_year=year,
                                value=normalized,
                                raw_value=row[column_index] or "",
                                normalized_unit=(
                                    "元" if metric_kind == "amount" else "元/股" if metric_kind == "eps" else "%"
                                ),
                                source_unit=source_unit if metric_kind == "amount" else "元/股" if metric_kind == "eps" else "%",
                                report_year=document.report_year,
                                restatement_status=status,
                                source_priority=100,
                                evidence=evidence,
                            )
                        )
    return candidates


def _locate_fallback_pages(path: Path, needed: set[str]) -> dict[str, int]:
    """Locate allowed supplemental statement pages with one pypdf pass."""
    located: dict[str, int] = {}
    reader = PdfReader(str(path))
    for page_index in range(20, len(reader.pages)):
        text = reader.pages[page_index].extract_text() or ""
        compact = normalize_text(text)
        if "profit_total" in needed and "profit_total" not in located:
            if all(token in compact for token in ("利润总额", "营业利润", "所得税费用")):
                located["profit_total"] = page_index
        if "share_capital" in needed and "share_capital" not in located:
            if all(token in compact for token in ("股本", "资本公积", "所有者权益")):
                located["share_capital"] = page_index
        if "deducted_return" in needed and "deducted_return" not in located:
            # The table header can remain on the preceding page while the data
            # rows continue on the next page, so the row wording itself is the
            # reliable locator for this supplemental source.
            if "扣除非经常性损益后归属于" in compact and "净利润" in compact:
                located["deducted_return"] = page_index
        if needed.issubset(located):
            break
    return located


def extract_profit_total_fallback(
    document: SourceDocument, target_page_index: int | None = None
) -> list[Candidate]:
    """Extract profit total from the consolidated income statement when absent in the summary."""
    if not document.annual_report or not document.report_year:
        return []
    candidates: list[Candidate] = []
    # pypdf is much faster for locating a text page than running table detection
    # across every page. pdfplumber is used only after the candidate page is known.
    if target_page_index is None:
        target_page_index = _locate_fallback_pages(
            document.path, {"profit_total"}
        ).get("profit_total")
    if target_page_index is None:
        document.warnings.append("摘要表未披露利润总额，且未在合并利润表中可靠定位该指标。")
        return candidates

    with pdfplumber.open(document.path) as pdf:
        for page_index in (target_page_index,):
            page = pdf.pages[page_index]
            try:
                tables = page.find_tables()
            except Exception:
                continue
            for table_index, table in enumerate(tables):
                rows, source_rows = _canonicalize_table_rows(table.extract() or [])
                for row_index, row in enumerate(rows):
                    if not row or "利润总额" not in normalize_text(row[0]):
                        continue
                    numeric_cells: list[tuple[int, Decimal, str]] = []
                    for column_index, cell in enumerate(row[1:], start=1):
                        parsed = parse_decimal(cell)
                        if parsed is not None:
                            numeric_cells.append((column_index, parsed, cell or ""))
                    if len(numeric_cells) < 2:
                        continue
                    for offset, (column_index, value, raw_value) in enumerate(numeric_cells[-2:]):
                        fiscal_year = document.report_year - offset
                        original_rows = source_rows[row_index]
                        bbox = _combined_row_bbox(table, original_rows)
                        evidence = Evidence(
                            file_id=document.file_id,
                            file_name=document.file_name,
                            report_year=document.report_year,
                            page_number=page_index + 1,
                            page_count=document.page_count,
                            page_width=float(page.width),
                            page_height=float(page.height),
                            bbox=tuple(float(item) for item in bbox),
                            section="合并利润表（补充来源）",
                            table_index=table_index,
                            row_index=original_rows[0],
                            column_index=column_index,
                            row_label=(row[0] or "").replace("\n", ""),
                            column_label=f"{fiscal_year}年",
                            extraction_method="income_statement_fallback",
                        )
                        candidates.append(
                            Candidate(
                                metric_id="profit_total",
                                fiscal_year=fiscal_year,
                                value=value,
                                raw_value=raw_value,
                                normalized_unit="元",
                                source_unit="元",
                                report_year=document.report_year,
                                restatement_status="current" if offset == 0 else "comparative",
                                source_priority=60,
                                evidence=evidence,
                            )
                        )
                    return candidates
    if not candidates:
        document.warnings.append("摘要表未披露利润总额，且未在合并利润表中可靠定位该指标。")
    return candidates


def extract_share_capital_fallback(
    document: SourceDocument, target_page_index: int | None = None
) -> list[Candidate]:
    """Extract share capital from the consolidated balance sheet."""
    if not document.annual_report or not document.report_year:
        return []
    if target_page_index is None:
        target_page_index = _locate_fallback_pages(
            document.path, {"share_capital"}
        ).get("share_capital")
    if target_page_index is None:
        document.warnings.append("摘要表未披露股本，且未在合并资产负债表中可靠定位该指标。")
        return []

    with pdfplumber.open(document.path) as pdf:
        page = pdf.pages[target_page_index]
        try:
            tables = page.find_tables()
        except Exception:
            tables = []
        for table_index, table in enumerate(tables):
            rows, source_rows = _canonicalize_table_rows(table.extract() or [])
            for row_index, row in enumerate(rows):
                if not row or match_metric(row[0]) != "share_capital":
                    continue
                numeric_cells = [
                    (column_index, parsed, cell or "")
                    for column_index, cell in enumerate(row[1:], start=1)
                    if (parsed := parse_decimal(cell)) is not None
                ]
                if len(numeric_cells) < 2:
                    continue
                original_rows = source_rows[row_index]
                bbox = _combined_row_bbox(table, original_rows)
                candidates: list[Candidate] = []
                for offset, (column_index, value, raw_value) in enumerate(numeric_cells[:2]):
                    fiscal_year = document.report_year - offset
                    evidence = Evidence(
                        file_id=document.file_id,
                        file_name=document.file_name,
                        report_year=document.report_year,
                        page_number=target_page_index + 1,
                        page_count=document.page_count,
                        page_width=float(page.width),
                        page_height=float(page.height),
                        bbox=tuple(float(item) for item in bbox),
                        section="合并资产负债表（补充来源）",
                        table_index=table_index,
                        row_index=original_rows[0],
                        column_index=column_index,
                        row_label=(row[0] or "").replace("\n", ""),
                        column_label=f"{fiscal_year}年末",
                        extraction_method="balance_sheet_fallback",
                    )
                    candidates.append(
                        Candidate(
                            metric_id="share_capital",
                            fiscal_year=fiscal_year,
                            value=value,
                            raw_value=raw_value,
                            normalized_unit="元",
                            source_unit="元",
                            report_year=document.report_year,
                            restatement_status="current" if offset == 0 else "comparative",
                            source_priority=70,
                            evidence=evidence,
                        )
                    )
                return candidates
    document.warnings.append("摘要表未披露股本，且未在合并资产负债表中可靠定位该指标。")
    return []


def extract_deducted_return_fallback(
    document: SourceDocument, target_page_index: int | None = None
) -> list[Candidate]:
    """Extract deducted ROE/basic EPS from the report's return table."""
    if not document.annual_report or not document.report_year:
        return []
    if target_page_index is None:
        target_page_index = _locate_fallback_pages(
            document.path, {"deducted_return"}
        ).get("deducted_return")
    if target_page_index is None:
        document.warnings.append(
            "摘要表未披露扣非每股收益/净资产收益率，且未定位到补充表格。"
        )
        return []

    with pdfplumber.open(document.path) as pdf:
        page = pdf.pages[target_page_index]
        try:
            tables = page.find_tables()
        except Exception:
            tables = []
        for table_index, table in enumerate(tables):
            rows, source_rows = _canonicalize_table_rows(table.extract() or [])
            for row_index, row in enumerate(rows):
                normalized_label = normalize_text(row[0] if row else "")
                if not (
                    "扣除非经常性损益后归属于" in normalized_label
                    and "净利润" in normalized_label
                ):
                    continue
                numeric_cells = [
                    (column_index, parsed, cell or "")
                    for column_index, cell in enumerate(row[1:], start=1)
                    if (parsed := parse_decimal(cell)) is not None
                ]
                if len(numeric_cells) < 2:
                    continue
                original_rows = source_rows[row_index]
                bbox = _combined_row_bbox(table, original_rows)
                candidates: list[Candidate] = []
                specs = (
                    ("deducted_roe", "%", numeric_cells[0]),
                    ("deducted_eps", "元/股", numeric_cells[1]),
                )
                for metric_id, unit, (column_index, value, raw_value) in specs:
                    evidence = Evidence(
                        file_id=document.file_id,
                        file_name=document.file_name,
                        report_year=document.report_year,
                        page_number=target_page_index + 1,
                        page_count=document.page_count,
                        page_width=float(page.width),
                        page_height=float(page.height),
                        bbox=tuple(float(item) for item in bbox),
                        section="净资产收益率及每股收益（补充来源）",
                        table_index=table_index,
                        row_index=original_rows[0],
                        column_index=column_index,
                        row_label=(row[0] or "").replace("\n", ""),
                        column_label=f"{document.report_year}年",
                        extraction_method="return_table_fallback",
                    )
                    candidates.append(
                        Candidate(
                            metric_id=metric_id,
                            fiscal_year=document.report_year,
                            value=value,
                            raw_value=raw_value,
                            normalized_unit=unit,
                            source_unit=unit,
                            report_year=document.report_year,
                            restatement_status="current",
                            source_priority=70,
                            evidence=evidence,
                        )
                    )
                return candidates
    document.warnings.append(
        "摘要表未披露扣非每股收益/净资产收益率，且未定位到补充表格。"
    )
    return []


def extract_document_candidates(document: SourceDocument) -> list[Candidate]:
    summary = extract_summary_candidates(document)
    has_current_profit_total = any(
        item.metric_id == "profit_total" and item.fiscal_year == document.report_year for item in summary
    )
    has_current_share_capital = any(
        item.metric_id == "share_capital" and item.fiscal_year == document.report_year for item in summary
    )
    has_current_deducted_eps = any(
        item.metric_id == "deducted_eps" and item.fiscal_year == document.report_year for item in summary
    )
    has_current_deducted_roe = any(
        item.metric_id == "deducted_roe" and item.fiscal_year == document.report_year for item in summary
    )
    needed: set[str] = set()
    if not has_current_profit_total:
        needed.add("profit_total")
    if not has_current_share_capital:
        needed.add("share_capital")
    if not (has_current_deducted_eps and has_current_deducted_roe):
        needed.add("deducted_return")
    pages = _locate_fallback_pages(document.path, needed) if needed else {}
    if "profit_total" in needed:
        summary.extend(extract_profit_total_fallback(document, pages.get("profit_total")))
    if "share_capital" in needed:
        summary.extend(extract_share_capital_fallback(document, pages.get("share_capital")))
    if "deducted_return" in needed:
        summary.extend(extract_deducted_return_fallback(document, pages.get("deducted_return")))
    return summary


def choose_candidates(candidates: Iterable[Candidate]) -> tuple[dict[tuple[str, int], Candidate], dict[tuple[str, int], list[Candidate]]]:
    grouped: dict[tuple[str, int], list[Candidate]] = {}
    for candidate in candidates:
        grouped.setdefault((candidate.metric_id, candidate.fiscal_year), []).append(candidate)
    selected: dict[tuple[str, int], Candidate] = {}
    for key, options in grouped.items():
        selected[key] = max(options, key=lambda item: item.score)
    return selected, grouped
