from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from fia.web import LoggingThreadingHTTPServer, create_handler


class FakeRegistry:
    def register(self, path: Path) -> str:
        return path.name

    def get(self, file_id: str):
        return None

    def entries(self):
        return []


class FakeFinancialClient:
    def __init__(self, barrier: threading.Barrier):
        self.barrier = barrier

    def fetch_and_archive(self, stock_code, archive_dir):
        self.barrier.wait(timeout=2)
        return [], {"stock_code": stock_code, "reports": [], "archive_dir": str(archive_dir)}


class FakeFinancialService:
    def analyze_paths(self, paths):
        return {"company_name": "测试公司", "metrics": [], "years": [], "quality": {}}


class FakeDisclosureService:
    def __init__(self, barrier: threading.Barrier):
        self.barrier = barrier

    def configuration_status(self):
        return {"status": "ok", "mode": "TEST"}

    def dashboard(self, stock_code, report_year, report_type):
        self.barrier.wait(timeout=2)
        return {
            "target_company": {"stock_code": stock_code, "company_name": "测试公司"},
            "filters": {"report_year": report_year, "report_type": report_type},
        }


class FakeState:
    def __init__(self, root: Path, barrier: threading.Barrier):
        self.project_root = root
        self.static_dir = PROJECT_ROOT / "static"
        self.input_dir = root
        self.archive_dir = root / "annual_reports"
        self.result_dir = root / "results"
        self.log_dir = root / "logs"
        self.registry = FakeRegistry()
        self.cninfo = FakeFinancialClient(barrier)
        self.service = FakeFinancialService()
        self.disclosure = FakeDisclosureService(barrier)
        self.analysis_lock = threading.Lock()


def post_json(url: str, payload: dict) -> dict:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


class CombinedApplicationTests(unittest.TestCase):
    def test_two_analysis_routes_can_execute_concurrently(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            barrier = threading.Barrier(2)
            state = FakeState(Path(temp_dir), barrier)
            server = LoggingThreadingHTTPServer(("127.0.0.1", 0), create_handler(state))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    disclosure = executor.submit(
                        post_json,
                        f"{base_url}/api/disclosure",
                        {"stock_code": "600519", "report_year": 2026, "report_type": "Q1"},
                    )
                    financial = executor.submit(
                        post_json,
                        f"{base_url}/api/analyze-stock",
                        {"stock_code": "600519"},
                    )
                    self.assertEqual(disclosure.result()["target_company"]["stock_code"], "600519")
                    self.assertEqual(financial.result()["annual_report_archive"]["stock_code"], "600519")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_health_exposes_both_services(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = FakeState(Path(temp_dir), threading.Barrier(2))
            server = LoggingThreadingHTTPServer(("127.0.0.1", 0), create_handler(state))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urlopen(f"http://127.0.0.1:{server.server_port}/api/health", timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(payload["application"], "FinancialReportAssistant")
                self.assertIn("financial_indicators", payload["services"])
                self.assertIn("disclosure_time", payload["services"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
