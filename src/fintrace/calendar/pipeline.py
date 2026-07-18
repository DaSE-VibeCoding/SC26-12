from __future__ import annotations

import csv
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


def _query_instruction(company_code: str, company_name: str) -> dict[str, Any]:
    address = require_file("cninfo_address_file").read_text(encoding="utf-8").strip()
    url = address[address.find("http") :] if "http" in address else address
    return {
        "company_code": company_code,
        "source_site": "巨潮资讯网",
        "source_url": url,
        "query_keyword_template": f"{company_code} {company_name} <年份> <报告类型>",
        "instructions": [
            "在巨潮资讯网按股票代码搜索定期报告和预约披露记录。",
            "将结果按项目 CSV 模板填写后重新运行本命令。",
            "不要根据常识补填缺失的公告日期或时间。",
        ],
    }


def run_calendar(
    company_input: str, target_year: int, manual_file: Path | None = None
) -> tuple[dict[str, Any], Path]:
    company_code, _ = normalize_company_code(company_input)
    context = RunContext(feature="calendar", company_code=company_code)
    context.start()
    try:
        company = resolve_company(company_input, target_year)
        events: list[CalendarEvent] = []
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
        manual_review = manual_file is None
        if manual_review:
            write_json(output_dir / "manual_query_instruction.json", instruction)
        quality = {
            "status": "manual_review_required" if manual_review else "passed",
            "event_count": len(events),
            "manual_review_required": manual_review,
            "checks": {
                "company_resolved": True,
                "source_preserved": manual_file is not None,
                "event_types_valid": True,
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
