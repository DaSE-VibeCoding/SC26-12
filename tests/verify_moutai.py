from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from fia.service import AnalysisService  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    args = parser.parse_args()
    paths = sorted(args.input_dir.glob("*贵州茅台*.pdf"))
    assert len(paths) == 5, f"预期5份贵州茅台年报，实际{len(paths)}份"
    result = AnalysisService(PROJECT_ROOT / ".fia_runtime" / "verification").analyze_paths(paths)
    assert result["years"] == [2021, 2022, 2023, 2024, 2025]
    assert result["quality"]["found_cells"] == 65
    metrics = {metric["metric_id"]: metric for metric in result["metrics"]}

    def value(metric_id: str, year: int) -> Decimal:
        return Decimal(metrics[metric_id]["values"][str(year)]["value"])

    assert value("revenue", 2025) == Decimal("168838102514.79")
    assert value("net_profit", 2025) == Decimal("82320067101.68")
    assert value("net_profit", 2021) == Decimal("52435506622.16")
    assert metrics["net_profit"]["values"]["2021"]["restatement_status"] == "adjusted"
    assert value("profit_total", 2021) == Decimal("74528031894.76")
    assert metrics["profit_total"]["values"]["2021"]["is_fallback"] is True
    assert metrics["profit_total"]["values"]["2021"]["evidence"]["page_number"] == 55
    assert metrics["roe"]["values"]["2025"]["change_display"] == "-3.49 个百分点"
    print("贵州茅台样例验证通过：65/65 个目标单元格，重述与PDF证据坐标正常。")


if __name__ == "__main__":
    main()
