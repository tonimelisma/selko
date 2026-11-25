"""python -m selko_import --source-url-file FILE --target PATH

The source URL is read from a file (never a command line: it carries a
password). Exit codes: 0 imported and verified; 3 the source schema differs
from the pinned map; 5 verification failed (nothing replaced); 2 usage.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from selko_import.core import ImportError_, import_sync


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="selko_import", description=__doc__)
    parser.add_argument("--source-url-file", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.target.exists():
        print(f"refusing to replace an existing database: {args.target}", file=sys.stderr)
        return 2
    url = args.source_url_file.read_text(encoding="utf-8").strip()
    try:
        report = import_sync(url, args.target)
    except ImportError_ as exc:
        print(f"import failed: {exc}", file=sys.stderr)
        return exc.exit_code
    total = sum(t.rows for t in report.tables)
    print(f"imported {report.accounts} accounts and {total} rows in {len(report.tables)} tables; every checksum matches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
