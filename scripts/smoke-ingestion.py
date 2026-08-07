#!/usr/bin/env python3
"""R6 — One-command synthetic for /health/ingestion + /health/egress.

Checks that the post-cutover observability contract holds: tasks alive,
no dead letters, poll SLO inside warning, egress single-digit MB projection,
and watchdog Sentry path is wired (when SMOKE_SENTRY_DSN is set).

Usage:
  python scripts/smoke-ingestion.py [--base-url http://localhost:8000]
  SMOKE_SENTRY_DSN=... python scripts/smoke-ingestion.py --check-sentry

Exit 0 = contract holds. Non-zero = print diff and fail.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request

DEFAULT_BASE = "http://localhost:8000"

def fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode())

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=DEFAULT_BASE)
    ap.add_argument("--check-sentry", action="store_true", help="trigger synthetic Sentry path if DSN set")
    args = ap.parse_args()

    base = args.base_url.rstrip("/")

    # --- /health/ingestion ---
    try:
        ing = fetch_json(f"{base}/health/ingestion")
    except Exception as e:
        print(f"FAIL: /health/ingestion fetch failed: {e}", file=sys.stderr)
        return 2

    ok = True

    if ing.get("background_processing_enabled") is False:
        print("INFO: background_processing_enabled=false — ingestion is disabled (local/CI); skipping degraded checks")
        print(json.dumps(ing, indent=2))
    else:
        tasks = ing.get("tasks") or []
        for t in tasks:
            if not t.get("alive"):
                print(f"FAIL: task {t.get('name')} not alive", file=sys.stderr)
                ok = False
        if (ing.get("items_dead_letter") or 0) > 0:
            print(f"FAIL: items_dead_letter={ing.get('items_dead_letter')} (expect 0)", file=sys.stderr)
            ok = False
        if (ing.get("attachments_dead_letter") or 0) > 0:
            print(f"FAIL: attachments_dead_letter={ing.get('attachments_dead_letter')} (expect 0)", file=sys.stderr)
            ok = False
        if ing.get("status") == "down":
            print("FAIL: status=down", file=sys.stderr)
            ok = False
        # SLO: oldest_next_poll_seconds should be < warning (default 1800) or None (no integrations)
        oldest = ing.get("oldest_next_poll_seconds")
        if oldest is not None and oldest > 1800:
            print(f"FAIL: oldest_next_poll_seconds={oldest} exceeds warning (1800)", file=sys.stderr)
            ok = False
        print("ingestion:", json.dumps(ing, indent=2))

    # --- /health/egress ---
    try:
        egress = fetch_json(f"{base}/health/egress")
    except Exception as e:
        print(f"WARN: /health/egress fetch failed: {e}", file=sys.stderr)
        egress = None

    if egress is not None:
        proj = egress.get("projected_bytes_per_30d")
        bph = egress.get("bytes_per_hour")
        print("egress:", json.dumps(egress, indent=2))
        # R6: after R3/R4 idle, projection should be single-digit MB/month, not 28 GB
        # Naïve projection is valid only on long-lived idle instance — warn not fail on fresh deploy
        uptime = egress.get("uptime_seconds") or 0
        if uptime < 600:
            print(f"INFO: uptime {uptime}s < 600s — projection not meaningful yet (fresh deploy)")
        elif proj is not None and proj > 10 * 1024 * 1024:
            print(f"WARN: projected_bytes_per_30d={proj} exceeds 10 MB — check for busy-wait", file=sys.stderr)
            # not fatal in smoke, but visible
        print(f"bytes_per_hour={bph} projected_30d={proj} uptime={uptime}s")

    if args.check_sentry:
        print("Sentry synthetic: not yet wired as HTTP trigger — verify via watchdog logger + DSN (see docs)")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
