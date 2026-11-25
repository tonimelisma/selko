"""Operator commands run inside the image: ``python -m selko.admin <command>``.

    migrate                          apply pending migrations and exit
    delete-account <account-uuid>    delete an account and everything it owns
                                     (the privacy policy's deletion on request)
    seed-demo <email>                demo data for an empty account; refused
                                     unless SELKO_ALLOW_DEMO_SEED=1

The database is ``$SELKO_DATA_DIR/selko.db``. Output names counts and ids,
never row contents.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import uuid

from selko.db import accounts as account_rows
from selko.db.demo import seed_demo
from selko.db.runtime import attachments_dir, open_database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="selko.admin", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    delete = sub.add_parser("delete-account")
    delete.add_argument("account_id")
    seed = sub.add_parser("seed-demo")
    seed.add_argument("email")
    args = parser.parse_args(argv)

    db = open_database(os.environ.get("SELKO_DATA_DIR", "data"))
    if args.command == "migrate":
        print("migrated")
        return 0
    if args.command == "delete-account":
        try:
            account_id = str(uuid.UUID(args.account_id))
        except ValueError:
            print("an account id is a UUID", file=sys.stderr)
            return 2
        if not account_rows.delete_account(db, account_id):
            print("no such account", file=sys.stderr)
            return 1
        folder = attachments_dir() / account_id
        if folder.is_dir():
            shutil.rmtree(folder)
        print(f"deleted account {account_id}")
        return 0
    if args.command == "seed-demo":
        if os.environ.get("SELKO_ALLOW_DEMO_SEED") != "1":
            print("refused: set SELKO_ALLOW_DEMO_SEED=1 to write demo data", file=sys.stderr)
            return 2
        print(json.dumps(seed_demo(db, args.email, attachments_dir())))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
