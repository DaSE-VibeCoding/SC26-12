from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


class UiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (PROJECT_ROOT / "static" / "index.html").read_text(encoding="utf-8")
        cls.javascript = (PROJECT_ROOT / "static" / "app.js").read_text(encoding="utf-8")
        cls.styles = (PROJECT_ROOT / "static" / "styles.css").read_text(encoding="utf-8")

    def test_human_input_is_stock_code_only(self) -> None:
        self.assertIn('id="stockCode"', self.html)
        self.assertIn('id="analyzeStockButton"', self.html)
        self.assertNotIn('type="file"', self.html)
        self.assertIn('api("/api/analyze-stock"', self.javascript)
        self.assertIn('api("/api/disclosure"', self.javascript)

    def test_two_assistants_run_in_parallel_and_have_switch_tabs(self) -> None:
        self.assertIn('id="disclosureTab"', self.html)
        self.assertIn('id="financialTab"', self.html)
        self.assertIn('id="disclosurePanel"', self.html)
        self.assertIn('id="financialPanel"', self.html)
        self.assertIn("Promise.allSettled", self.javascript)
        self.assertIn("runDisclosureAnalysis(stockCode)", self.javascript)
        self.assertIn("runFinancialAnalysis(stockCode)", self.javascript)

    def test_chart_has_two_colored_unit_axes_and_shared_year_axis(self) -> None:
        self.assertIn("canvas.dataset.leftAxisUnit = absoluteUnit", self.javascript)
        self.assertIn("canvas.dataset.rightAxisUnit = changeUnit", self.javascript)
        self.assertIn('canvas.dataset.xAxis = "年份"', self.javascript)
        self.assertIn("context.strokeStyle = colors.blue", self.javascript)
        self.assertIn("context.strokeStyle = colors.red", self.javascript)
        self.assertIn("`柱状图（${absoluteUnit}）`", self.javascript)
        self.assertIn("`折线图（${changeUnit}）`", self.javascript)

    def test_evidence_render_is_explicit_and_serialized(self) -> None:
        self.assertNotIn("renderMetric(state.activeMetricId, true)", self.javascript)
        self.assertIn("await cancelActivePdfRender()", self.javascript)
        self.assertIn("pdfRenderToken", self.javascript)
        self.assertIn('elements.pdfStage.dataset.pageNumber = String(safePage)', self.javascript)
        self.assertIn(".pdf-placeholder[hidden], .pdf-canvas-wrap[hidden]", self.styles)

    def test_pdfjs_main_module_and_worker_are_version_locked(self) -> None:
        self.assertIn('from "/static/vendor/pdf.mjs?v=5.6.205"', self.javascript)
        self.assertIn('from "/static/vendor/pdf.worker.mjs?v=5.6.205"', self.javascript)
        self.assertIn('const PDF_WORKER_URL = "/static/vendor/pdf.worker.mjs?v=5.6.205"', self.javascript)
        self.assertIn("globalThis.pdfjsWorker = { WorkerMessageHandler }", self.javascript)
        self.assertIn('/static/app.js?v=4.0', self.html)

    def test_evidence_ui_discloses_cross_year_sources(self) -> None:
        self.assertIn('entry.evidence?.report_year !== entry.year', self.javascript)
        self.assertIn('evidence.report_year !== year', self.javascript)
        self.assertIn('"跨年补充"', self.javascript)
        self.assertIn('"各年原报告优先"', self.javascript)

    def test_frontend_errors_are_reported_to_log_endpoint(self) -> None:
        self.assertIn('fetch("/api/client-log"', self.javascript)
        self.assertIn('window.addEventListener("error"', self.javascript)
        self.assertIn('window.addEventListener("unhandledrejection"', self.javascript)
        self.assertIn('reportClientError("PDF 证据加载或渲染失败"', self.javascript)


if __name__ == "__main__":
    unittest.main(verbosity=2)
