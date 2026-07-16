#!/usr/bin/env python3
"""Fan stock-shadow-research outputs into each pool's shadow_research_top15/.

stock-shadow-research writes its default shape to rank-history/<date>/<TICKER>/
(report.md + <TICKER>.json). This moves each queued ticker's report into every
pool that queued it, as <pool>/shadow_research_top15/<TICKER>.{md,json}
(report.md -> <TICKER>.md), then removes the emptied loose <TICKER>/ dir.

Deduped by design: a ticker in N pools is copied to all N pool dirs from one
source. Idempotent: a (pool, ticker) that already has both files is skipped, and
tickers whose research was written straight into the pool dir need no source.

Run from the trade-bot repo root:
    python scripts/consolidate_shadow.py --date 2026-07-15 <pool> [<pool> ...]
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

REPO = Path.cwd()


def queue_map(date: str, pools: list[str]) -> dict[str, list[str]]:
    """ticker -> [pools that queued it], from each pool's shadow README."""
    m: dict[str, list[str]] = {}
    for pool in pools:
        readme = REPO / "rank-history" / date / pool / "shadow_research_top15" / "README.md"
        section = readme.read_text().split("## Manual Commands")[1].split("## Expected")[0]
        for line in section.splitlines():
            if line.startswith("stock-shadow-research"):
                m.setdefault(line.split()[1], []).append(pool)
    return m


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("pools", nargs="+")
    args = ap.parse_args()

    base = REPO / "rank-history" / args.date
    pairs = missing = removed = 0
    gaps: list[str] = []
    for ticker, pools in queue_map(args.date, args.pools).items():
        src = base / ticker
        src_md, src_js = src / "report.md", src / f"{ticker}.json"
        for pool in pools:
            dst = base / pool / "shadow_research_top15"
            dst.mkdir(parents=True, exist_ok=True)
            out_md, out_js = dst / f"{ticker}.md", dst / f"{ticker}.json"
            if out_md.is_file() and out_js.is_file():
                pairs += 1
                continue  # already in place (idempotent / written straight to pool)
            if not (src_md.is_file() and src_js.is_file()):
                missing += 1
                gaps.append(f"{ticker}->{pool}")
                continue
            shutil.copyfile(src_md, out_md)
            shutil.copyfile(src_js, out_js)
            json.load(open(out_js))  # validate
            pairs += 1
        # remove the loose per-ticker dir once its content is distributed
        if src.is_dir() and src_md.is_file():
            shutil.rmtree(src)
            removed += 1

    print(f"pairs in place: {pairs} | missing sources: {missing} | loose dirs removed: {removed}")
    if gaps:
        print("MISSING (need shadow research):", ", ".join(sorted(gaps)))


if __name__ == "__main__":
    main()
