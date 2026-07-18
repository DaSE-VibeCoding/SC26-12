from __future__ import annotations

import csv
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fintrace.calendar.cninfo import query_annual_reports
from fintrace.calendar.models import CalendarEvent
from fintrace.calendar.normalization import CalendarNormalizationError, normalize_event
from fintrace.shared.company_resolver import normalize_company_code, resolve_company
from fintrace.shared.exceptions import FinTraceError, InputFileNotFoundError
from fintrace.shared.file_store import append_jsonl, write_json
from fintrace.shared.paths import configured_path, project_relative, require_file
from fintrace.shared.run_context import RunContext

CSV_FIELDS = list(CalendarEvent.model_fields)


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise InputFileNotFoundError(
            f"Calendar import file does not exist: {path}", step="read_manual_calendar"
        )
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
            raise CalendarNormalizationError("Calendar JSON must contain a list of objects.")
        return payload
    raise CalendarNormalizationError("Calendar import must be a .csv or .json file.")


def _write_csv(path: Path, events: list[CalendarEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for event in events:
            writer.writerow(event.model_dump(mode="json"))


def _cninfo_home_url() -> str:
    address = require_file("cninfo_address_file").read_text(encoding="utf-8").strip()
    return address[address.find("http") :] if "http" in address else address


def _query_instruction(company_code: str, company_name: str) -> dict[str, Any]:
    return {
        "company_code": company_code,
        "source_site": "巨潮资讯网",
        "source_url": _cninfo_home_url(),
        "query_keyword_template": f"{company_code} {company_name} <年份> <报告类型>",
        "instructions": [
            "在巨潮资讯网按股票代码搜索年度报告。",
            "排除年度报告摘要、半年度报告和英文版，只记录正式年度报告发布时间。",
            "网络查询失败后可按项目 CSV 模板填写，并使用 --manual-file 重新运行。",
        ],
    }


def _events_from_cninfo(
    announcements: list[dict[str, Any]], company_code: str, company_name: str, queried_at: datetime
) -> list[CalendarEvent]:
    return [
        normalize_event(
            {
                "report_period": item["report_period"],
                "report_type": "annual",
                "event_type": "actual",
                "event_date": item["event_date"],
                "announcement_title": item["announcement_title"],
                "source_site": "巨潮资讯网",
                "source_url": item["source_url"],
                "query_keyword": company_code,
                "queried_at": queried_at.isoformat(),
                "manual_review_required": False,
            },
            company_code,
            company_name,
        )
        for item in announcements
    ]


def run_calendar(
    company_input: str, target_year: int, manual_file: Path | None = None
) -> tuple[dict[str, Any], Path]:
    company_code, _ = normalize_company_code(company_input)
    context = RunContext(feature="calendar", company_code=company_code)
    context.start()
    try:
        company = resolve_company(company_input, target_year)
        events: list[CalendarEvent] = []
        source_preserved = False
        if manual_file:
            step = "import_manual_calendar"
            context.start_step(step, {"manual_file": project_relative(manual_file)})
            raw = manual_file.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            raw_dir = configured_path("raw_calendar_dir") / company_code / context.run_id
            raw_dir.mkdir(parents=True, exist_ok=True)
            stored_source = raw_dir / manual_file.name
            shutil.copy2(manual_file, stored_source)
            rows = _read_rows(manual_file)
            events = [normalize_event(row, company_code, company.company_name) for row in rows]
            events.sort(
                key=lambda event: (event.event_date, event.event_time or datetime.min.time())
            )
            context.finish_step(
                step,
                {
                    "source_file": project_relative(stored_source),
                    "source_sha256": digest,
                    "event_count": len(events),
                },
            )
            source_preserved = True
        else:
            step = "query_cninfo_annual_reports"
            context.start_step(
                step, {"company_code": company_code, "publication_year": target_year}
            )
            queried_at = datetime.now(UTC)
            announcements, audit = query_annual_reports(
                company_code, target_year, source_url=_cninfo_home_url()
            )
            raw_dir = configured_path("raw_calendar_dir") / company_code / context.run_id
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_response = raw_dir / "cninfo_annual_reports.json"
            write_json(raw_response, audit)
            events = _events_from_cninfo(
                announcements, company_code, company.company_name, queried_at
            )
            context.finish_step(
                step,
                {
                    "source_file": project_relative(raw_response),
                    "candidate_count": audit["candidate_count"],
                    "event_count": len(events),
                },
            )
            source_preserved = True

        events.sort(key=lambda event: (event.event_date, event.event_time or datetime.min.time()))

        output_dir = context.output_dir
        _write_csv(output_dir / "calendar_events.csv", events)
        _write_csv(
            output_dir / "schedule_changes.csv",
            [event for event in events if event.event_type == "schedule_change"],
        )
        timeline = {
            "company": company.model_dump(mode="json"),
            "generated_at": datetime.now(UTC).isoformat(),
            "events": [event.model_dump(mode="json") for event in events],
        }
        write_json(output_dir / "calendar_timeline.json", timeline)
        instruction = _query_instruction(company_code, company.company_name)
        manual_review = not events
        if manual_review:
            write_json(output_dir / "manual_query_instruction.json", instruction)
        quality = {
            "status": "manual_review_required" if manual_review else "passed",
            "event_count": len(events),
            "manual_review_required": manual_review,
            "checks": {
                "company_resolved": True,
                "source_preserved": source_preserved,
                "event_types_valid": True,
                "annual_reports_only": manual_file is not None or all(
                    event.report_type == "annual" and event.event_type == "actual"
                    for event in events
                ),
            },
        }
        write_json(output_dir / "quality_report.json", quality)
        if manual_review or company.company_info_fallback:
            context.warning_count += int(manual_review) + int(company.company_info_fallback)
        context.finish(with_warnings=context.warning_count > 0)
        append_jsonl(
            configured_path("indexes_dir") / "calendar_runs.jsonl",
            [
                {
                    "run_id": context.run_id,
                    "company_code": company_code,
                    "event_count": len(events),
                    "output": project_relative(output_dir),
                }
            ],
        )
        return quality, output_dir
    except FinTraceError as exc:
        context.fail(exc.to_dict())
        raise
