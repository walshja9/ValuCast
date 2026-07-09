# Prediction-archive retention — decision memo (2026-07-08)

Status: **decision deferred until after the AOTC gate unlock (~2026-07-13)**.
This memo exists so that call is a 30-minute decision instead of a
re-investigation. The free, output-identical win (shallow CI clones,
`fetch-depth: 1` in all three scheduled workflows) shipped with this memo.

## The growth numbers (as of 2026-07-08, commit `72e68864`)

- `data/prediction_archive/` is **920MB across 481 committed JSON files**,
  growing **~18MB/day** with no ceiling.
- `valucast_prospect_rank_v1/` alone adds **~11MB/day**; the universal model
  archive adds ~7MB/day.
- `.git` is **1.6GB**. Every scheduled workflow was cloning the full history
  each run until the `fetch-depth: 1` change in this commit.

## Consumer inventory (verified 2026-07-08)

Six modules read the archive. Several are the source of truth for public
honesty claims — that is what makes casual pruning unsafe.

| Consumer | What it reads | How far back it genuinely needs | Honesty-bound? |
|----------|---------------|----------------------------------|----------------|
| `prospects/movers.py:84` `_archive_payloads` | parses EVERY rank_v1 archive file | back to the scoring epoch — `epoch_reach` (days since `EPOCH_DATE`, movers.py:337) grows with epoch age, NOT a fixed 30-day window | no, but output changes if truncated inside the epoch |
| `prospects/buys.py:175` `_load_history_payloads` | parses every file | the /buys "All" spark window also reaches to the epoch | no, same caveat |
| `prospects/ahead_of_consensus.py:207` | streak scan over the full archive | models `anchored_at_archive_start` (:243), so it TOLERATES a truncated start — but truncating CHANGES `streak_since` claims | **yes** — and rules are FROZEN until ~7/13 |
| `prospects/call_up_receipts.py:343` | receipt timestamps derive from archive presence | as far back as the oldest receipt claim | **yes** |
| `prospects/forward_validation.py:94` | rank + buys archives for validation reports | full range it reports over | no (internal reports) |
| `prospects/recent_signal.py:49` | rank + buys archives, calendar-dated deltas | small windows (days) | no |

Also archived daily in other subdirs: the universal model (~7MB/day), roster
status, and the peak projection (observe-only validation accumulator — a
data-science asset; do not prune without its own decision).

## Constraint

The AOTC scorecard's rules are **pre-registered and frozen until the ~7/13
gate unlock**. `streak_since` and receipt timestamps are public honesty
claims. No archive deletion may land before the unlock, and none after it
without proof the claims survive byte-identical.

## Decision options (post-unlock)

- **Option A — external archive.** Move `data/prediction_archive/` out of the
  serving repo (separate data repo or object storage); consumers read a local
  checkout/cache in CI only. Kills repo growth AND Render deploy weight.
  Blast radius: largest — CI plumbing for every workflow that writes or reads
  the archive, plus a migration of 920MB of history. End state, not first move.
- **Option B — windowed retention + snapshot.** AOTC/receipts snapshot the
  per-call state they need into their own committed artifacts (they partially
  do), then prune archive files older than the longest honest need. Blast
  radius: the two honesty-bound consumers — requires proving
  `streak_since`/receipt claims survive **byte-identical** before any file is
  deleted. Movers/buys epoch reach also caps the prune window.
- **Option C — compaction.** Keep all days but strip archive rows to the
  fields consumers actually read (movers/buys use ~6 of the ~40 fields per
  row). Order-of-magnitude shrink, zero semantic change, still grows forever.
  Blast radius: smallest — a compaction script plus a byte-identical shadow
  build of the consumers.

## Recommendation

**C is the low-risk first move; A is the end state.** B only with a
byte-identical proof gate. Whatever is chosen becomes plan 009 (retention
implementation), which must include a byte-identical shadow build of
movers/buys/AOTC/receipts against the pruned-vs-full archive before any
deletion lands.

## Note on `.git` bloat

The 1.6GB `.git` is only recoverable via history rewrite (BFG/filter-repo) —
a separate, Alex-gated decision that must be coordinated with Render (the
dashboard-connected deploy tracks master). Shallow CI clones already sidestep
the transfer cost; the rewrite is about repo hygiene, not CI speed.

## Maintenance rule

If a new consumer of `data/prediction_archive/` is added before retention
lands, add it to the inventory above in the same PR — a stale inventory is
how the next person deletes something load-bearing.
