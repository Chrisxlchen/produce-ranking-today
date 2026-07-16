#!/usr/bin/env python3
"""Run the backoffice rotation pipeline for ONE pool into
rank-history/<date>/<pool>/.

Mirrors backoffice/rotate_core_pool.py but: (1) routes output to a per-pool
subdir, (2) picks the candidates file from the pool name, (3) normalizes configs
that wrap tickers under a key instead of a top-level array, (4) supplies an empty
core-pool baseline so it never touches real pools/, and (5) retries Stage 2 when
it blocks on a transient invalid_output.

Run from the trade-bot repo root:
    python scripts/run_pool_rotation.py --pool universal_tickers --date 2026-07-15
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

REPO = Path.cwd()
sys.path.insert(0, str(REPO))

from backoffice.build_core import build_core_json
from backoffice.rotation_summary import write_rotation_run_summary
from backoffice.top3_research_overlay.prepare import prepare_research_queue
from backoffice.topn_pullback_momentum.stage import (
    write_rank_snapshot_json,
    write_rank_top3_json,
)

STAGE2_MAX_ATTEMPTS = 3
# Keys that may hold the ticker array in a wrapped config, most specific first.
ARRAY_KEYS = ("production_universe", "tickers", "universe")


def normalize_candidates(pool: str, scratch: Path) -> Path:
    """Return a path to a JSON array of tickers for `config/<pool>.json`.

    Plain-array configs pass through unchanged. Wrapped configs (a dict with the
    ticker list under a key) get their array extracted to a scratch file.
    """
    cfg = REPO / "config" / f"{pool}.json"
    if not cfg.is_file():
        raise SystemExit(f"config not found: {cfg}")
    raw = json.loads(cfg.read_text())
    if isinstance(raw, list):
        return cfg
    if isinstance(raw, dict):
        for key in ARRAY_KEYS:
            if isinstance(raw.get(key), list):
                out = scratch / f"{pool}_array.json"
                out.write_text(json.dumps(raw[key]))
                return out
        for value in raw.values():  # fall back to the first list value
            if isinstance(value, list):
                out = scratch / f"{pool}_array.json"
                out.write_text(json.dumps(value))
                return out
    raise SystemExit(f"cannot find a ticker array in {cfg}")


def run_stage2(reports_dir: Path, pool: str) -> bool:
    """Run Stage 2, retrying transient blocks. Return True if candidates published."""
    candidates = reports_dir / pool / "stage2_candidates.json"
    for attempt in range(1, STAGE2_MAX_ATTEMPTS + 1):
        print(f"[2/3] Stage-2 screen (attempt {attempt}/{STAGE2_MAX_ATTEMPTS})", flush=True)
        subprocess.run(
            [sys.executable, "-m", "backoffice.research.cli",
             "--reports-dir", str(reports_dir), "--timestamp", pool,
             "--run-mode", "production"],
            cwd=REPO, check=False,
        )
        if candidates.is_file():
            return True
        print("    Stage-2 blocked (no stage2_candidates.json); retrying", flush=True)
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", required=True, help="pool name = config/<pool>.json basename")
    ap.add_argument("--date", required=True, help="report dir date YYYY-MM-DD")
    ap.add_argument("--as-of", help="market-data cutoff; defaults to --date")
    args = ap.parse_args()

    reports_dir = REPO / "rank-history" / args.date
    report_dir = reports_dir / args.pool
    # --date is only the report-dir label; the data cutoff defaults to the real
    # today so a back-labeled date can't fetch an empty (future) window.
    as_of = args.as_of or date.today().isoformat()
    scratch = Path(tempfile.mkdtemp(prefix=f"prt_{args.pool}_"))
    (scratch / "pools").mkdir()
    (scratch / "pools" / "core.json").write_text("[]")  # empty baseline; real pools/ untouched

    candidates = normalize_candidates(args.pool, scratch)
    print(f"\n########## POOL {args.pool} ({candidates.name}) ##########", flush=True)

    # Stage 1 — rotation
    print("[1/3] rotation", flush=True)
    subprocess.run(
        [sys.executable, "-m", "backoffice.quant_ranker.cli",
         "--candidates", str(candidates),
         "--pools-dir", str(scratch / "pools"),
         "--reports-dir", str(reports_dir),
         "--timestamp", args.pool,
         "--as-of", as_of],
        cwd=REPO, check=True,
    )
    if not report_dir.is_dir():
        raise SystemExit(f"rotation produced no report dir: {report_dir}")

    # Stage 2 — AI research gate (with retry)
    published = run_stage2(reports_dir, args.pool)

    # Stage 3 — build_core + Top3 research queue (needs published candidates)
    core_json = None
    if published:
        print("[3/3] build_core + prepare research queue", flush=True)
        core_json = build_core_json(report_dir / "stage2_candidates.json", report_dir)
        prepare_research_queue(report_dir)
    else:
        raise SystemExit(
            f"Stage 2 stayed blocked after {STAGE2_MAX_ATTEMPTS} attempts for "
            f"{args.pool}; no shadow queue produced. Inspect "
            f"{report_dir}/stage2_run.json + stage2_judgements.json."
        )

    # Research-independent raw momentum + snapshot
    write_rank_top3_json(report_dir / "quant_fit.json", as_of=as_of)
    write_rank_snapshot_json(report_dir / "rankings.json", as_of=as_of)

    statuses = {"top3_raw_momentum.json": "not promoted",
                "rankings_snapshot.json": "not promoted"}
    if core_json is not None:
        statuses["core.json"] = "not promoted"
    write_rotation_run_summary(report_dir, promotion_statuses=statuses)
    print(f"done: {report_dir.relative_to(REPO)}", flush=True)


if __name__ == "__main__":
    main()
