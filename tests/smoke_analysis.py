from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from fia.service import AnalysisService  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--pattern", default="*.pdf")
    args = parser.parse_args()
    result = AnalysisService(PROJECT_ROOT / ".fia_runtime" / "test-results").analyze_paths(
        args.input_dir.glob(args.pattern)
    )
    summary = {
        "company_name": result["company_name"],
        "years": result["years"],
        "quality": result["quality"],
        "latest": {
            metric["metric_id"]: metric["values"].get(str(result["latest_year"]))
            for metric in result["metrics"]
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
