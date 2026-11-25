"""One-time import of the old hosted database into Selko's data directory.

    python -m selko_import database --source-url-file FILE --target DATA_DIR/selko.db
    python -m selko_import attachments --source-url-file FILE \\
        --storage-url https://<ref>.supabase.co --storage-key-file FILE --data-dir DATA_DIR

Secrets are read from files, never from the command line: the source URL
carries the database password, the storage key reads every user's files.

database:    0 imported and verified; 3 the source schema differs from the
             pinned map, or it holds data of the removed Google Photos
             ingestion; 5 verification failed (nothing written); 2 usage.
attachments: 0 every object copied and verified (re-runnable: files already in
             place are skipped); 6 some objects missing at the source or not
             matching their size/hash; 7 the Storage API refused the request.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _secret(path: Path) -> str:
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise SystemExit(f"{path} is empty")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="selko_import", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    database = sub.add_parser("database", help="copy and verify every table")
    database.add_argument("--source-url-file", required=True, type=Path)
    database.add_argument("--target", required=True, type=Path)
    files = sub.add_parser("attachments", help="copy and verify attachment files")
    files.add_argument("--source-url-file", required=True, type=Path)
    files.add_argument("--storage-url", required=True)
    files.add_argument("--storage-key-file", required=True, type=Path)
    files.add_argument("--data-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    if args.command == "database":
        from selko_import.core import ImportError_, import_sync

        if args.target.exists():
            print(f"refusing to replace an existing database: {args.target}", file=sys.stderr)
            return 2
        try:
            report = import_sync(_secret(args.source_url_file), args.target)
        except ImportError_ as exc:
            print(f"import failed: {exc}", file=sys.stderr)
            return exc.exit_code
        total = sum(t.rows for t in report.tables)
        print(f"imported {report.accounts} accounts and {total} rows in {len(report.tables)} tables; every checksum matches")
        return 0

    from selko_import.attachments import CopyError, copy_attachments

    try:
        report = copy_attachments(
            _secret(args.source_url_file), args.storage_url, _secret(args.storage_key_file),
            args.data_dir / "attachments",
        )
    except CopyError as exc:
        print(f"attachment copy failed: {exc}", file=sys.stderr)
        return exc.exit_code
    if not report.ok:
        print("attachment copy incomplete: re-run to retry; missing objects are absent at the source", file=sys.stderr)
        return 6
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
