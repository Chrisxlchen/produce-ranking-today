#!/usr/bin/env python3
"""Finalize per-pool research overlays at Top5 and promote them to flat pools/
with a pool-source prefix.

For each pool it: (1) transforms the raw stock-shadow JSON in
shadow_research_top15/ into the overlay research shape finalize expects,
(2) runs finalize at top_n=5 into the report dir (no built-in --promote),
(3) copies the five researched pools to pools/ as
`<prefix>_top5_<suffix>.json`, rewriting the internal pool_name to match so
load_all_pools (which keys by pool_name) doesn't collide across pools.

Prefix = the pool name's first token (ndx_universe_2026 -> "ndx", etc.).

Run from the trade-bot repo root:
    python scripts/promote_top5.py --date 2026-07-15 ndx_universe_2026 selective_500_tickers ...
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path.cwd()
sys.path.insert(0, str(REPO))

# _overlay_research_from_stock_shadow is the same transform finalize's own
# auto-import uses; reused directly because our per-pool dirs aren't date-named
# so that auto-import path is skipped.
from backoffice.top3_research_overlay.finalize import (
    finalize_research_overlay,
    _overlay_research_from_stock_shadow,
)
from backoffice.top3_research_overlay.schema import RESEARCH_SCHEMA_VERSION

TOP_N = 5
STEM = "top3_"  # produced filename/pool_name stem, rewritten to <prefix>_top5_
RESEARCH_POOLS = (
    "top3_research_ranked_momentum",
    "top3_momentum_research_veto",
    "top3_persistent_momentum_research_veto",
    "top3_ai_theme_momentum",
    "top3_ai_ranked",
)


def prefix_for(pool: str) -> str:
    return pool.split("_")[0]


def overlayize(report_dir: Path, as_of: str) -> None:
    shadow_dir = report_dir / "shadow_research_top15"
    for js in sorted(shadow_dir.glob("*.json")):
        payload = json.loads(js.read_text())
        if payload.get("schema_version") == RESEARCH_SCHEMA_VERSION:
            continue  # already overlay shape; idempotent
        row = _overlay_research_from_stock_shadow(payload, as_of=as_of)
        js.write_text(json.dumps(row, indent=2) + "\n")


def promote_pool(date: str, pool: str, pools_dir: Path) -> list[tuple[Path, int]]:
    report_dir = REPO / "rank-history" / date / pool
    if not report_dir.is_dir():
        raise SystemExit(f"report dir not found: {report_dir}")
    overlayize(report_dir, date)
    finalize_research_overlay(report_dir, top_n=TOP_N)  # writes 5 pools into report_dir

    pref = prefix_for(pool)
    pools_dir.mkdir(parents=True, exist_ok=True)
    # Archive the promoted files under rank-history so a dated copy survives for
    # future backtests even after pools/ moves on.
    archive_dir = REPO / "rank-history" / date / "promoted_pools"
    archive_dir.mkdir(parents=True, exist_ok=True)
    written: list[tuple[Path, int]] = []
    for name in RESEARCH_POOLS:
        payload = json.loads((report_dir / f"{name}.json").read_text())
        new_name = f"{pref}_top5_{name[len(STEM):]}"
        payload["pool_name"] = new_name
        blob = json.dumps(payload, indent=2) + "\n"
        (archive_dir / f"{new_name}.json").write_text(blob)
        dst = pools_dir / f"{new_name}.json"
        dst.write_text(blob)
        written.append((dst, len(payload.get("main", []))))
    return written


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--pools-dir", default="pools")
    ap.add_argument("pools", nargs="+", help="pool dir names under rank-history/<date>/")
    args = ap.parse_args()

    pools_dir = REPO / args.pools_dir
    for pool in args.pools:
        print(f"\n=== promote {pool} (top{TOP_N}) ===", flush=True)
        for dst, n in promote_pool(args.date, pool, pools_dir):
            try:
                shown = dst.relative_to(REPO)
            except ValueError:
                shown = dst
            print(f"  {shown}  ({n} names)", flush=True)


if __name__ == "__main__":
    main()
