# Plan 006: Contain the prediction-archive growth cost — shallow CI clones now, retention decision documented for post-7/13

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 72e68864..HEAD -- .github/workflows/daily-public-data.yml .github/workflows/prospect-shadow.yml .github/workflows/roster-pulse.yml`
> On any drift, re-read the changed workflow before proceeding.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW (workflow-only + one new doc; no product code)
- **Depends on**: none
- **Category**: tech-debt / CI
- **Planned at**: commit `72e68864`, 2026-07-08

## Why this matters

`data/prediction_archive` is 920MB across 481 committed JSON files, growing ~18MB/day with no ceiling (`valucast_prospect_rank_v1/` alone adds ~11MB/day). `.git` is 1.6GB. All three scheduled workflows clone the FULL history (`fetch-depth: 0`) on every run — that cost grows forever. The obvious fix, deleting old archive files, is NOT safe to do casually: six modules read that archive, several as the source of truth for public honesty claims (the AOTC ledger's "flagged on date X", receipts timestamps), and the AOTC scorecard's rules are frozen until the ~7/13 gate unlock. So this plan ships the free, output-identical win now (shallow clones) and commits a decision memo that makes the retention call post-7/13 a 30-minute decision instead of a re-investigation.

## Current state

- Shallow-clone targets, all currently `fetch-depth: 0`:
  - `.github/workflows/daily-public-data.yml:88`
  - `.github/workflows/prospect-shadow.yml:25`
  - `.github/workflows/roster-pulse.yml:35`
- Each workflow already has a "Sync to latest origin/master" step (`git fetch origin && git checkout -B master origin/master`) and pushes with a plain fail-loud `git push origin master`. None of the build steps read git HISTORY — every consumer reads files from the working tree — so clone depth affects only transfer cost, not outputs.
- Archive consumer inventory (verified 7/8 — this is the load-bearing content of the memo in Step 2):
  - `prospects/movers.py:84` `_archive_payloads` — parses EVERY rank_v1 archive file; the epoch floor (`epoch_reach` = days since `EPOCH_DATE`, movers.py:337) means its walk-back grows with epoch age → needs history back to the scoring epoch, NOT just 30 days.
  - `prospects/buys.py:175` `_load_history_payloads` — parses every file; the /buys "All" spark window also reaches to the epoch.
  - `prospects/ahead_of_consensus.py:207` — streak scan over the full archive; explicitly models `anchored_at_archive_start` (:243), i.e. it TOLERATES a truncated archive start, but truncating CHANGES `streak_since` claims → frozen until post-7/13.
  - `prospects/call_up_receipts.py:343` — receipt timestamps derive from archive presence; honesty-bound.
  - `prospects/forward_validation.py:94` — reads rank + buys archives for validation reports.
  - `prospects/recent_signal.py:49` — reads rank + buys archives; calendar-dated deltas (small windows).
- Also archived daily (other subdirs of `data/prediction_archive/`): universal model (~7MB/day), roster status, peak projection (observe-only validation accumulator — a data-science asset, do not prune without a decision).
- Repo convention for decision memos: `docs/specs/YYYY-MM-DD-<topic>.md` (see `docs/specs/2026-06-27-w21-mle-backtest-gate.md`, `docs/specs/2026-06-27-forward-retention-seed.md`).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| YAML sanity | `python -c "import yaml; [yaml.safe_load(open(f)) for f in ['.github/workflows/daily-public-data.yml','.github/workflows/prospect-shadow.yml','.github/workflows/roster-pulse.yml']]"` | no output |
| Post-merge live check (reviewer/Alex runs) | `gh run watch` after the next scheduled run of each workflow | run green; push step fast-forward |

## Scope

**In scope**:
- The three workflow files (the `fetch-depth` lines only).
- New file: `docs/specs/2026-07-08-prediction-archive-retention.md`.

**Out of scope** (do NOT touch):
- ANY file under `data/prediction_archive/` — no deletions, no pruning scripts.
- All six consumer modules listed above.
- `git gc` / history rewriting / BFG — the 1.6GB `.git` is only fixable by history rewrite; that is a separate, Alex-gated decision (note it in the memo).

## Git workflow

- Work on `master` locally; do NOT push (workflow edits go live on push and the next cron runs them — reviewer gates it). Stage the 4 files explicitly.
- Commit style: `Shallow-clone the scheduled workflows; document archive retention decision`.

## Steps

### Step 1: `fetch-depth: 0` → `fetch-depth: 1` in all three workflows

Edit exactly the three cited lines. Do not touch the sync or push steps: pushing new commits from a shallow clone is supported (the sync step's `git fetch origin && git checkout -B master origin/master` works shallow; the subsequent commit is a child of the fetched tip, so the push is a normal fast-forward).

**Verify**: YAML sanity command → no output. `grep -n "fetch-depth" .github/workflows/*.yml` → three hits, all `fetch-depth: 1`.

### Step 2: Write the retention decision memo

Create `docs/specs/2026-07-08-prediction-archive-retention.md` containing: (1) the growth numbers above; (2) the consumer inventory above, verbatim — per consumer: what it reads, how far back it genuinely needs, and whether it is honesty-bound; (3) the constraint that AOTC scorecard rules are frozen until ~7/13; (4) the decision options for after the unlock, each with its blast radius:
   - **Option A — external archive**: move `data/prediction_archive/` out of the serving repo (separate data repo or object storage), consumers read a local checkout/cache in CI only. Kills repo growth AND Render deploy weight; largest plumbing.
   - **Option B — windowed retention + snapshot**: AOTC/receipts snapshot the per-call state they need into their own committed artifacts (they partially do), then prune archive files older than the longest honest need; requires proving `streak_since`/receipt claims survive byte-identical.
   - **Option C — compaction**: keep all days but strip archive rows to the fields consumers read (movers/buys need ~6 fields of the ~40 per row); order-of-magnitude shrink, zero semantic change, still grows forever.
   (5) a recommendation line: C is the low-risk first move, A is the end state; B only with a byte-identical proof gate. (6) the note that `.git` history bloat is only recoverable via history rewrite — separate decision, coordinate with Render.

**Verify**: file exists; `grep -c "Option" docs/specs/2026-07-08-prediction-archive-retention.md` ≥ 3.

## Test plan

No product code changes → no new tests. The verification is the YAML check plus the reviewer watching the next scheduled run of each workflow complete green (checkout faster, push fast-forward).

## Done criteria

- [ ] Three workflows at `fetch-depth: 1`; YAML sanity passes.
- [ ] Memo committed at `docs/specs/2026-07-08-prediction-archive-retention.md` with inventory + options + recommendation.
- [ ] `git status` shows only the 4 in-scope files.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- Any workflow step is found to read git history (e.g. `git log`/`git diff` against older commits) — recheck before changing that workflow's depth.
- A workflow's push step still contains a rebase/merge fallback (contradicts the "plain fail-loud push" excerpt).

## Maintenance notes

- After ~7/13, turn the memo into plan 009 (retention implementation) — that plan must include a byte-identical shadow build of movers/buys/AOTC/receipts against the pruned vs. full archive before any deletion lands.
- If a new consumer of `data/prediction_archive/` is added before retention lands, add it to the memo's inventory in the same PR — the inventory going stale is how the next person deletes something load-bearing.
