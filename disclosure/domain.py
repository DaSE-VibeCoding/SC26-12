"""财报披露时间看板的业务规则。

所有日期在文件、存储和 API 边界统一使用 ``YYYY-MM-DD``。本模块不包含
任何演示数据或随机日期生成逻辑。
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any


YEARS = (2022, 2023, 2024, 2025, 2026)
REPORT_TYPES = ("Q1", "H1", "Q3", "FY")

REPORT_META = {
    "Q1": {"label": "第一季度报告", "short_label": "一季报", "period_suffix": "03-31"},
    "H1": {"label": "半年度报告", "short_label": "半年报", "period_suffix": "06-30"},
    "Q3": {"label": "第三季度报告", "short_label": "三季报", "period_suffix": "09-30"},
    "FY": {"label": "年度报告", "short_label": "年报", "period_suffix": "12-31"},
}

PERIOD_SUFFIX_TO_TYPE = {meta["period_suffix"]: kind for kind, meta in REPORT_META.items()}

RESERVATION_FIELDS = (
    ("first_reservation_date", "首次预约"),
    ("first_change_date", "第一次变更"),
    ("second_change_date", "第二次变更"),
    ("third_change_date", "第三次变更"),
)


class ValidationError(ValueError):
    """可直接展示给用户的输入错误。"""


def normalize_stock_code(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    if not re.fullmatch(r"\d{6}", text):
        raise ValidationError("股票代码必须是 6 位数字")
    return text


def normalize_year(value: Any) -> int:
    try:
        year = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("报告年度必须是 2022—2026 之间的整数") from exc
    if year not in YEARS:
        raise ValidationError("报告年度必须在 2022—2026 之间")
    return year


def normalize_report_type(value: Any) -> str:
    kind = "" if value is None else str(value).strip().upper()
    if kind not in REPORT_TYPES:
        raise ValidationError("报告类型必须是 Q1、H1、Q3 或 FY")
    return kind


def normalize_iso_date(value: Any, field_name: str) -> str | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value).strip()).isoformat()
    except ValueError as exc:
        raise ValidationError(f"{field_name} 必须是 YYYY-MM-DD 日期") from exc


def report_period(report_year: Any, report_type: Any) -> str:
    year = normalize_year(report_year)
    kind = normalize_report_type(report_type)
    return f"{year}-{REPORT_META[kind]['period_suffix']}"


def period_to_year_type(period: str) -> tuple[int, str]:
    match = re.fullmatch(r"(\d{4})-(\d{2}-\d{2})", str(period).strip())
    if not match or match.group(2) not in PERIOD_SUFFIX_TO_TYPE:
        raise ValidationError(f"无法识别报告期：{period}")
    year = int(match.group(1))
    if year not in YEARS:
        raise ValidationError(f"报告期不在 2022—2026 范围内：{period}")
    return year, PERIOD_SUFFIX_TO_TYPE[match.group(2)]


def report_window(report_year: Any, report_type: Any) -> tuple[date, date]:
    year = normalize_year(report_year)
    kind = normalize_report_type(report_type)
    if kind == "Q1":
        return date(year, 1, 1), date(year, 4, 30)
    if kind == "H1":
        return date(year, 5, 1), date(year, 8, 31)
    if kind == "Q3":
        return date(year, 9, 1), date(year, 10, 31)
    return date(year, 11, 1), date(year + 1, 4, 30)


def select_reservation(record: dict[str, Any]) -> tuple[str | None, str | None]:
    """按三次变更 > 二次变更 > 一次变更 > 首次预约选择日期。"""

    for field, label in reversed(RESERVATION_FIELDS):
        value = record.get(field)
        if value:
            return str(value), label
    return None, None


def select_display_date(record: dict[str, Any]) -> tuple[str | None, str]:
    actual = record.get("actual_disclosure_date")
    if actual:
        return str(actual), "ACTUAL"
    reservation, _ = select_reservation(record)
    if reservation:
        return reservation, "RESERVATION"
    return None, "MISSING"


def enrich_record(record: dict[str, Any]) -> dict[str, Any]:
    result = dict(record)
    reservation_date, reservation_label = select_reservation(result)
    display_date, display_type = select_display_date(result)
    history = [
        {"field": field, "label": label, "date": result[field]}
        for field, label in RESERVATION_FIELDS
        if result.get(field)
    ]
    result.update(
        {
            "selected_reservation_date": reservation_date,
            "selected_reservation_label": reservation_label,
            "display_date": display_date,
            "display_date_type": display_type,
            "reservation_history": history,
            "reservation_change_count": max(0, len(history) - 1),
        }
    )
    return result


def missing_record(stock_code: str, company_name: str, year: int, kind: str) -> dict[str, Any]:
    return enrich_record(
        {
            "stock_code": normalize_stock_code(stock_code),
            "company_name": company_name,
            "short_name": company_name,
            "report_year": normalize_year(year),
            "report_type": normalize_report_type(kind),
            "first_reservation_date": None,
            "first_change_date": None,
            "second_change_date": None,
            "third_change_date": None,
            "actual_disclosure_date": None,
            "source_type": "MISSING",
            "source_url": None,
            "source_file": None,
            "fetched_at": None,
        }
    )


def business_key(record: dict[str, Any]) -> str:
    return f"{record['stock_code']}|{int(record['report_year'])}|{record['report_type']}"


def market_for_stock(stock_code: str) -> str | None:
    """返回巨潮预约披露页面使用的市场参数；北交所暂不在该页面范围内。"""

    code = normalize_stock_code(stock_code)
    if code.startswith(("300", "301", "302")):
        return "szcn"
    if code.startswith(("688", "689")):
        return "shkcp"
    if code.startswith(("600", "601", "603", "605", "900")):
        return "shmb"
    if code.startswith(("000", "001", "002", "003", "200")):
        return "szmb"
    return None
