import argparse
import json
import sys
from pathlib import Path

from fintrace.financial.pipeline import run_financial
from fintrace.shared.exceptions import FinTraceError


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract traceable financial facts")
    parser.add_argument("--company", required=True)
    parser.add_argument("--report-pdf", required=True, type=Path)
    parser.add_argument("--report-year", required=True, type=int)
    parser.add_argument(
        "--report-type", required=True, choices=["q1", "semiannual", "q3", "annual"]
    )
    args = parser.parse_args()
    try:
        quality, output = run_financial(
            args.company, args.report_pdf.resolve(), args.report_year, args.report_type
        )
    except FinTraceError as exc:
        print(json.dumps(exc.to_dict(), ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"quality": quality, "output_dir": str(output)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
