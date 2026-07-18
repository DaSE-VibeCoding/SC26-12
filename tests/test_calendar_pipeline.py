import csv
import json
from pathlib import Path

import httpx

from fintrace.calendar.cninfo import is_full_annual_report, query_annual_reports
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


def test_annual_report_title_filter_is_strict() -> None:
    assert is_full_annual_report("贵州茅台2025年年度报告") is True
    assert is_full_annual_report("贵州茅台2025年年度报告摘要") is False
    assert is_full_annual_report("贵州茅台2025年年度报告（英文版）") is False
    assert is_full_annual_report("贵州茅台2025年半年度报告") is False
    assert is_full_annual_report("贵州茅台关于2025年年度报告的更正公告") is False
    assert is_full_annual_report("贵州茅台2025年年度报告（修订版）") is True


def test_cninfo_query_selects_only_full_chinese_annual_report() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("szse_stock.json"):
            return httpx.Response(
                200,
                json={"stockList": [{"code": "600519", "orgId": "gssh0600519"}]},
            )
        return httpx.Response(
            200,
            json={
                "hasMore": False,
                "announcements": [
                    {
                        "secCode": "600519",
                        "secName": "贵州茅台",
                        "announcementId": "full",
                        "announcementTitle": "贵州茅台2025年年度报告",
                        "announcementTime": 1776355200000,
                        "adjunctUrl": "finalpage/2026-04-17/full.PDF",
                    },
                    {
                        "secCode": "600519",
                        "announcementTitle": "贵州茅台2025年年度报告摘要",
                        "announcementTime": 1776355200000,
                    },
                    {
                        "secCode": "600519",
                        "announcementTitle": "贵州茅台2025年年度报告（英文版）",
                        "announcementTime": 1776355200000,
                    },
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        reports, audit = query_annual_reports("600519", 2026, client=client)
    assert len(reports) == 1
    assert reports[0]["announcement_title"] == "贵州茅台2025年年度报告"
    assert reports[0]["event_date"] == "2026-04-17"
    assert reports[0]["report_period"] == "2025-12-31"
    assert audit["candidate_count"] == 3
    assert audit["selected_count"] == 1


def test_automatic_cninfo_calendar_pipeline(monkeypatch) -> None:
    def fake_query(company_code: str, publication_year: int, *, source_url: str):
        assert source_url == "https://www.cninfo.com.cn/new/index.jsp"
        return (
            [
                {
                    "announcement_title": "贵州茅台2025年年度报告",
                    "report_period": "2025-12-31",
                    "event_date": "2026-04-17",
                    "source_url": "https://static.cninfo.com.cn/report.pdf",
                }
            ],
            {
                "candidate_count": 3,
                "selected_count": 1,
                "raw_pages": [],
            },
        )

    monkeypatch.setattr("fintrace.calendar.pipeline.query_annual_reports", fake_query)
    quality, output_dir = run_calendar("600519", 2026)
    timeline = json.loads((output_dir / "calendar_timeline.json").read_text(encoding="utf-8"))
    assert quality["manual_review_required"] is False
    assert quality["checks"]["annual_reports_only"] is True
    assert timeline["events"][0]["event_type"] == "actual"
    assert timeline["events"][0]["event_date"] == "2026-04-17"


def test_empty_cninfo_result_creates_review_instruction(monkeypatch) -> None:
    monkeypatch.setattr(
        "fintrace.calendar.pipeline.query_annual_reports",
        lambda company_code, publication_year, *, source_url: (
            [],
            {"candidate_count": 0, "selected_count": 0, "raw_pages": []},
        ),
    )
    quality, output_dir = run_calendar("600519", 2026)
    instruction = json.loads(
        (output_dir / "manual_query_instruction.json").read_text(encoding="utf-8")
    )
    assert quality["manual_review_required"] is True
    assert instruction["source_site"] == "巨潮资讯网"
