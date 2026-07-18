from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fintrace.calendar.pipeline import run_calendar
from fintrace.shared.exceptions import FinTraceError


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a local disclosure calendar")
    parser.add_argument("--company", required=True)
    parser.add_argument("--target-year", required=True, type=int)
    parser.add_argument("--manual-file", type=Path)
    args = parser.parse_args()
    try:
        quality, output_dir = run_calendar(args.company, args.target_year, args.manual_file)
    except FinTraceError as exc:
        print(json.dumps(exc.to_dict(), ensure_ascii=False), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {"quality": quality, "output_dir": str(output_dir)}, ensure_ascii=False, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
