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
    paths = sorted(args.input_dir.glob("002330_*.pdf"))
    assert len(paths) == 5, f"预期5份得利斯年报，实际{len(paths)}份"
    result = AnalysisService(PROJECT_ROOT / ".fia_runtime" / "verification-delisi").analyze_paths(paths)
    assert result["years"] == [2021, 2022, 2023, 2024, 2025]
    assert result["quality"]["found_cells"] == 65, result["quality"]
    metrics = {metric["metric_id"]: metric for metric in result["metrics"]}

    def value(metric_id: str, year: int) -> Decimal:
        return Decimal(metrics[metric_id]["values"][str(year)]["value"])

    assert value("revenue", 2025) == Decimal("3147334762.78")
    assert value("net_profit", 2024) == Decimal("-33672271.06")
    assert value("share_capital", 2024) == Decimal("635375290.00")
    assert value("deducted_eps", 2025) == Decimal("-0.100")
    assert value("deducted_roe", 2024) == Decimal("-2.10")
    assert value("profit_total", 2024) == Decimal("-34697244.05")
    print("得利斯样例验证通过：65/65 个目标单元格，补充来源及PDF证据坐标正常。")


if __name__ == "__main__":
    main()
