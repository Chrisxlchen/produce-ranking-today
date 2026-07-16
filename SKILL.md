---
name: produce-ranking-today
description: Produce today's per-pool rank-history + shadow research for named trade-bot pools. User-invoked; pass pool names.
disable-model-invocation: true
---

# Produce Ranking Today

Runs the backoffice rotation pipeline for each named pool into
`rank-history/<date>/<pool>/`, then runs `stock-shadow-research` on each pool's
Top15 and writes the reports straight into that pool's dir.

Run from the trade-bot repo root with the project venv active
(`source .venv/bin/activate`).

## Arguments

Pool names are `config/<pool>.json` basenames, e.g.:

```
produce-ranking-today universal_tickers selective_500_tickers production_universe_v1 ndx_universe_2026
```

No pool names given → ask which pools; do not guess. Date is today unless the
user gives an as-of date (then pass it as `--date` and `--as-of`).

## Steps

1. **Rotate each pool.** For every pool run
   `python <skill>/scripts/run_pool_rotation.py --pool <name> --date <date>`
   (independent pools may run concurrently). The driver normalizes the config,
   supplies an empty core baseline, runs Stage 1→3, and retries a transiently
   blocked Stage 2. **Done when** every pool has
   `rank-history/<date>/<pool>/shadow_research_top15/README.md`.

2. **Build the shadow queue.** From each pool's `shadow_research_top15/README.md`
   `## Manual Commands`, read the Top15 tickers and build a `ticker -> [pools]`
   map. **Done when** you have the deduped unique ticker set and each ticker's
   pool list.

3. **Run shadow research.** Fan the unique tickers across parallel subagents
   (~5 each). Each subagent runs `stock-shadow-research` per its `SKILL.md`, and
   for each ticker writes `report.md` + `<TICKER>.json` into **every pool dir
   that queued it**: `rank-history/<date>/<pool>/shadow_research_top15/<TICKER>.{md,json}`
   (uppercase ticker). A `.md` Write-hook may block — write `.md` via Bash.
   **Done when** every queued (pool, ticker) pair has both files.

4. **Verify + summarize.** Confirm both files exist and each JSON parses for
   every queued (pool, ticker) pair. Then write `rank-history/<date>/SUMMARY.md`:
   a per-pool Top15 verdict table (`new_entry_bias` per ticker) plus a conviction
   list of tickers queued by 2+ pools. **Done when** the verified pair count
   equals the expected count and `SUMMARY.md` is written.

## Reference

- **Research only — hard boundary.** Never write `pools/*.json`, `config/*`,
  ranking/sizing code, or the DB. Promotion (`top3_research_overlay finalize
  --promote`) is a separate explicit step the user must ask for.
- **Prerequisite skills.** `stock-shadow-research` orchestrates `prism-skill` +
  the serenity set (`serenity-alpha`, `gf-dma-health-index`, `tam-adj-peg`,
  `bayesian-intrinsic-growth-valuation`, `buy-side-equity-research-memo`); all
  must be installed in `~/.claude/skills/`.
- **Config shapes** the driver handles: plain array, or a dict wrapping the array
  under `production_universe` / `tickers` / `universe` (e.g.
  `production_universe_v1.json`).
- **Stage 2 blocks** happen when the judge returns `invalid_output` for a name
  inside the Selection Frontier. The driver retries up to 3×; a persistent block
  aborts that pool with a pointer to `stage2_run.json`.
- **Deduping matters:** the same leader appears across pools (semis, security).
  Run each unique ticker's research once, then write copies into each pool dir —
  don't re-research per pool.
