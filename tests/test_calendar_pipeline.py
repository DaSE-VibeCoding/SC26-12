import csv
import json
from pathlib import Path

from fintrace.calendar.normalization import normalize_report_type
from fintrace.calendar.pipeline import run_calendar


def test_report_type_aliases() -> None:
    assert normalize_report_type("一季报") == "q1"
    assert normalize_report_type("半年度报告") == "semiannual"
    assert normalize_report_type("三季报") == "q3"
    assert normalize_report_type("年报") == "annual"


def test_manual_calendar_pipeline_produces_independent_outputs() -> None:
    fixture = Path("tests/fixtures/calendar/600519_events.csv").resolve()
    quality, output_dir = run_calendar("600519", 2026, fixture)
    assert quality["status"] == "passed"
    with (output_dir / "calendar_events.csv").open(encoding="utf-8-sig") as handle:
        events = list(csv.DictReader(handle))
    changes = list(csv.DictReader((output_dir / "schedule_changes.csv").open(encoding="utf-8-sig")))
    assert len(events) == 3
    assert len(changes) == 1
    assert events[0]["report_type"] == "annual"


def test_missing_manual_file_creates_review_instruction() -> None:
    quality, output_dir = run_calendar("600519", 2026)
    instruction = json.loads(
        (output_dir / "manual_query_instruction.json").read_text(encoding="utf-8")
    )
    assert quality["manual_review_required"] is True
    assert instruction["source_site"] == "巨潮资讯网"
