from __future__ import annotations

import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from urllib import parse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from fia.cninfo import (  # noqa: E402
    ANNUAL_REPORT_CATEGORY,
    CNINFO_QUERY_URL,
    CNINFO_STOCK_LIST_URL,
    CninfoAnnualReportClient,
    QUERY_END_DATE,
    QUERY_START_DATE,
    is_full_annual_report,
    normalize_stock_code,
)


class FakeResponse:
    def __init__(self, payload: bytes):
        self.stream = io.BytesIO(payload)
        self.headers = {"Content-Length": str(len(payload))}

    def read(self, size: int = -1) -> bytes:
        return self.stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.stream.close()


class FakeCninfoTransport:
    def __init__(self) -> None:
        self.pdf_download_count = 0
        self.query_parameters: dict[str, list[str]] = {}

    def __call__(self, req, timeout=30):
        if req.full_url == CNINFO_STOCK_LIST_URL:
            return FakeResponse(
                json.dumps(
                    {"stockList": [{"code": "600519", "zwjc": "贵州茅台", "orgId": "gssh0600519"}]},
                    ensure_ascii=False,
                ).encode("utf-8")
            )
        if req.full_url == CNINFO_QUERY_URL:
            self.query_parameters = parse.parse_qs(
                req.data.decode("utf-8"),
                keep_blank_values=True,
            )
            announcements = []
            for year in range(2021, 2026):
                common = {
                    "secCode": "600519",
                    "secName": "贵州茅台",
                    "announcementTime": (year + 1) * 1_000_000_000,
                }
                announcements.extend(
                    [
                        {
                            **common,
                            "announcementId": f"full-{year}",
                            "announcementTitle": f"贵州茅台{year}年<em>年度报告</em>",
                            "adjunctUrl": f"finalpage/{year + 1}/full-{year}.PDF",
                        },
                        {
                            **common,
                            "announcementId": f"corrected-{year}",
                            "announcementTitle": f"贵州茅台{year}年<em>年度报告</em>（更正后）",
                            "announcementTime": (year + 1) * 1_000_000_000 - 1,
                            "adjunctUrl": f"finalpage/{year + 1}/corrected-{year}.PDF",
                        },
                        {
                            **common,
                            "announcementId": f"summary-{year}",
                            "announcementTitle": f"贵州茅台{year}年<em>年度报告</em>摘要",
                            "adjunctUrl": f"finalpage/{year + 1}/summary-{year}.PDF",
                        },
                        {
                            **common,
                            "announcementId": f"english-{year}",
                            "announcementTitle": f"贵州茅台{year}年<em>年度报告</em>（英文版）",
                            "adjunctUrl": f"finalpage/{year + 1}/english-{year}.PDF",
                        },
                    ]
                )
            announcements.append(
                {
                    "secCode": "600519",
                    "secName": "贵州茅台",
                    "announcementTime": 2_000_000_000,
                    "announcementId": "full-2020",
                    "announcementTitle": "贵州茅台2020年<em>年度报告</em>",
                    "adjunctUrl": "finalpage/2021/full-2020.PDF",
                }
            )
            return FakeResponse(
                json.dumps({"hasMore": False, "announcements": announcements}, ensure_ascii=False).encode(
                    "utf-8"
                )
            )
        if req.full_url.startswith("https://static.cninfo.com.cn/"):
            self.pdf_download_count += 1
            return FakeResponse(b"%PDF-1.7\n% fake annual report\n")
        raise AssertionError(f"unexpected URL: {req.full_url}")


class CninfoAnnualReportTests(unittest.TestCase):
    def test_title_filter_keeps_only_full_chinese_annual_report(self) -> None:
        self.assertTrue(is_full_annual_report("贵州茅台2025年<em>年度报告</em>"))
        self.assertTrue(is_full_annual_report("贵州茅台2025年年度报告（更正后）"))
        self.assertFalse(is_full_annual_report("贵州茅台2025年年度报告（修订版）"))
        self.assertFalse(is_full_annual_report("贵州茅台2025年年度报告（更新后）"))
        self.assertFalse(is_full_annual_report("贵州茅台2025年年度报告（更正后）说明"))
        self.assertFalse(is_full_annual_report("贵州茅台2025年半年度报告"))
        self.assertFalse(is_full_annual_report("贵州茅台2025年年度报告摘要"))
        self.assertFalse(is_full_annual_report("贵州茅台2025年年度报告（英文版）"))

    def test_stock_code_validation(self) -> None:
        self.assertEqual(normalize_stock_code("600519"), "600519")
        with self.assertRaisesRegex(ValueError, "6 位数字"):
            normalize_stock_code("60051A")

    def test_query_download_archive_and_reuse_exactly_five_reports(self) -> None:
        transport = FakeCninfoTransport()
        client = CninfoAnnualReportClient(opener=transport)
        with tempfile.TemporaryDirectory() as temp:
            paths, manifest = client.fetch_and_archive("600519", Path(temp))
            archived_years = [
                re.search(r"_(20\d{2})年年度报告\.pdf$", item.name).group(1)
                for item in paths
            ]
            self.assertEqual(archived_years, [str(year) for year in range(2021, 2026)])
            self.assertTrue(all(path.read_bytes().startswith(b"%PDF-") for path in paths))
            self.assertEqual(manifest["years"], [2021, 2022, 2023, 2024, 2025])
            self.assertEqual(len(manifest["reports"]), 5)
            self.assertEqual(manifest["query_audit"]["candidate_count"], 21)
            self.assertEqual(manifest["query_audit"]["selected_count"], 5)
            self.assertTrue(all(item["title"].endswith("年度报告（更正后）") for item in manifest["reports"]))
            self.assertTrue(all(item["is_correction"] for item in manifest["reports"]))
            self.assertEqual(transport.query_parameters["searchkey"], [""])
            self.assertEqual(transport.query_parameters["category"], [ANNUAL_REPORT_CATEGORY])
            self.assertEqual(
                transport.query_parameters["seDate"],
                [f"{QUERY_START_DATE.isoformat()}~{QUERY_END_DATE.isoformat()}"],
            )
            self.assertEqual(transport.pdf_download_count, 5)

            reused_paths, reused_manifest = client.fetch_and_archive("600519", Path(temp))
            self.assertEqual(reused_paths, paths)
            self.assertTrue(all(item["reused"] for item in reused_manifest["reports"]))
            self.assertEqual(transport.pdf_download_count, 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
