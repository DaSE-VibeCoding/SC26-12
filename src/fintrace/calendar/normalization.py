from __future__ import annotations

import hashlib
from functools import lru_cache
from typing import Any

import yaml

from fintrace.calendar.models import CalendarEvent
from fintrace.shared.exceptions import FinTraceError
from fintrace.shared.paths import get_project_root


class CalendarNormalizationError(FinTraceError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, code="calendar_normalization_error", **kwargs)


@lru_cache(maxsize=1)
def load_calendar_rules() -> dict[str, Any]:
    path = get_project_root() / "configs" / "calendar_rules.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CalendarNormalizationError("Calendar rules must be a mapping.")
    return payload


def normalize_report_type(value: str) -> str:
    candidate = str(value).strip().lower()
    aliases = load_calendar_rules()["report_type_aliases"]
    for canonical, values in aliases.items():
        if candidate in {str(item).strip().lower() for item in values}:
            return canonical
    raise CalendarNormalizationError(
        f"Unsupported report type: {value}", step="normalize_calendar_events"
    )


def normalize_event_type(value: str) -> str:
    candidate = str(value).strip().lower()
    allowed = set(load_calendar_rules()["event_types"])
    if candidate not in allowed:
        raise CalendarNormalizationError(
            f"Unsupported calendar event type: {value}", step="normalize_calendar_events"
        )
    return candidate


def make_event_id(row: dict[str, Any], company_code: str) -> str:
    identity = "|".join(
        str(row.get(key, ""))
        for key in ("report_period", "report_type", "event_type", "event_date", "source_url")
    )
    digest = hashlib.sha256(f"{company_code}|{identity}".encode()).hexdigest()[:16]
    return f"cal_{company_code}_{digest}"


def normalize_event(row: dict[str, Any], company_code: str, company_name: str) -> CalendarEvent:
    report_type = normalize_report_type(str(row.get("report_type", "")))
    event_type = normalize_event_type(str(row.get("event_type", "")))
    previous_date = row.get("previous_date")
    if event_type == "schedule_change" and not previous_date:
        raise CalendarNormalizationError(
            "A schedule_change event requires previous_date.",
            step="normalize_calendar_events",
        )
    payload = {
        **row,
        "event_id": make_event_id(row, company_code),
        "company_code": company_code,
        "company_name": company_name,
        "report_type": report_type,
        "event_type": event_type,
        "source_site": row.get("source_site") or "manual_import",
        "manual_review_required": _boolean(row.get("manual_review_required", False)),
    }
    try:
        return CalendarEvent.model_validate(payload)
    except ValueError as exc:
        raise CalendarNormalizationError(
            "Calendar row failed validation.",
            step="normalize_calendar_events",
            details={"reason": str(exc), "row": row},
        ) from exc


def _boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}
