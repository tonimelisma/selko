#!/usr/bin/env python3
"""One-time production repair for review queue integrity — R5.

Dry-run is default. Mutation requires:
  --environment production
  --manifest /absolute/path/to/untracked-manifest.json
  --apply
  --confirm-user <user-uuid>

Manifest contains event UUIDs/actions only, no subjects/bodies.
See docs/specs/review-queue-integrity.md §9.
"""

import argparse
import json
import sys
from pathlib import Path
import uuid

def parse_args():
    p = argparse.ArgumentParser(description="Repair review queue integrity (R5)")
    p.add_argument("--environment", required=True, choices=["production","staging","development"])
    p.add_argument("--manifest", required=True, type=Path, help="Absolute path to untracked manifest JSON")
    p.add_argument("--apply", action="store_true", help="Actually mutate (default dry-run)")
    p.add_argument("--confirm-user", required=True, help="User UUID to confirm")
    return p.parse_args()

ACTIONS = {"merge_duplicate_group","cancel_event","mark_source_resolved"}

def main():
    args = parse_args()
    try:
        uuid.UUID(args.confirm_user)
    except ValueError:
        print(f"Invalid --confirm-user UUID: {args.confirm_user}", file=sys.stderr)
        sys.exit(2)
    if not args.manifest.is_absolute():
        print("Manifest must be absolute path", file=sys.stderr)
        sys.exit(2)
    if not args.manifest.exists():
        print(f"Manifest not found: {args.manifest}", file=sys.stderr)
        sys.exit(2)
    data = json.loads(args.manifest.read_text())
    if not isinstance(data, dict) or "actions" not in data:
        print("Manifest must be {actions: [...]}", file=sys.stderr)
        sys.exit(2)
    for act in data["actions"]:
        if act.get("action") not in ACTIONS:
            print(f"Invalid action: {act}", file=sys.stderr)
            sys.exit(2)
        # Validate UUIDs
        for k in ["survivor","event_id","duplicate","duplicate_ids"]:
            if k in act:
                vals = act[k] if isinstance(act[k], list) else [act[k]]
                for v in vals:
                    try: uuid.UUID(v)
                    except: print(f"Invalid UUID {k}={v}", file=sys.stderr); sys.exit(2)
    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"[{mode}] environment={args.environment} manifest={args.manifest} actions={len(data['actions'])}")
    for i, act in enumerate(data["actions"], 1):
        print(f"  {i}. {act['action']} {act}")
    if not args.apply:
        print("Dry run complete — no mutations. Re-run with --apply to mutate.")
        sys.exit(0)
    if args.environment != "production":
        print("Apply only allowed with --environment production", file=sys.stderr)
        sys.exit(2)
    # Real mutation would be one transaction locking targets in UUID order.
    # For R5 DB contracts, this script is a placeholder that validates preconditions.
    print("Apply would run one transaction per spec §9 (locking targets, moving sources/hints, audit).")
    print("No DB connection in this dry-run placeholder — integrate with supabase client for production.")
    sys.exit(0)

if __name__ == "__main__":
    main()
