# Plan 018: Lead time on every receipt — how many days of foresight each call-up call had

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat fb360066..HEAD -- prospects/call_up_receipts.py app.py templates/receipts.html tests/test_call_up_receipts.py`
> The receipts builder changed on 7/09 (the at-promotion standard landed in
> `fb360066`). If any in-scope file changed since this plan was written,
> re-read the "Current state" excerpts against the live code before
> proceeding; on a mismatch with an excerpt, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW (purely additive field; no existing row semantics change, no scoring rule touched)
- **Depends on**: none. Fully compatible with the incremental merge and the at-promotion re-validation already in the builder.
- **Category**: feature (accountability / honesty on the receipts board)
- **Execution window**: anytime (does NOT build on the AOTC scorecard machinery — see Scope)
- **Planned at**: commit `fb360066`, 2026-07-09

## Why this matters

The call-up receipts board scores **arrival, not outcome**, and its trigger (a call-up) creates survivorship bias: bullish over-ranks that never resolve are invisible, and the seed lane can only add hits. Within that frame, the one dimension the board *can* honestly quantify — and currently throws away — is **lead time**. Right now a receipt that flagged a player 2 days before his call-up reads identically to one that flagged him 30 days early; the divergence number captures *how far* ahead of the field ValuCast was, but nothing captures *how long* it held that call before the field's own trigger event fired. That's the difference between a lucky same-week guess and a genuine month-ahead read, and the board says nothing about it.

This plan adds `flagged_days_early` to each receipt row: the number of consecutive archive days, walking back from the real call-up date, on which ValuCast already ranked the player at-or-better-than his claimed rank band. It is archive-provable (every day is a committed `valucast_prospect_rank_v1` snapshot), monotone (defined as a single continuous run so it can only be extended by more foresight), and honest about its own limits (omitted, not faked, when the archives can't support it). It renders as "flagged Nd early" on the page row and the share PNG, turning the board's one legitimate signal into something a reader can actually see.

## Current state

All builder logic is in `prospects/call_up_receipts.py`, verified at `fb360066`:

- `:311-327` — `_archive_by_date_key(archive_payloads)` returns `date -> {identity_key: rank_row}` across every walked archive payload. **This is the exact index a lead-time walk-back needs** — it is already built once in the builder and passed everywhere. Each `rank_row` is a raw archive board row.
- Archive board rows carry the ValuCast rank as `row["rank"]` (an int), NOT `valucast_rank`. Verified against `data/prediction_archive/valucast_prospect_rank_v1/2026-07-05.json`: Owen Murphy (`702566`) has `rank=27`, `valucast_rank=None`, plus `context_only.source_ranks`. The receipts scorer (`_call_up_row`, `:257`) already reads `row.get("rank")` for auto rows, so `rank` is the canonical archive field.
- `:609-751` — `build_call_up_receipts(...)`. Relevant flow, in order:
  - `:632` `actual_dates = _actual_call_up_dates(transactions_cache) if transactions_cache else {}` — real (transaction-observed) call-up dates, keyed by `mlbam_id` string.
  - `:633` `archive_index = _archive_by_date_key(archive_payloads)` — the index above, already in scope.
  - `:670-671` receipts/misses are finalized and EXCLUDED-key-filtered.
  - `:676-680` — the shadow-date attach loop, **the exact place to also compute lead time** (it already iterates `receipts + misses` and already has `actual_dates` + `mlbam_id` in hand):
    ```python
    if actual_dates:
        for row in receipts + misses:
            real_date = actual_dates.get(str(row.get("mlbam_id")))
            if real_date:
                row["actual_call_up_date"] = real_date
    ```
  - `:682-691` pre-launch drop; `:698-706` no-claim bucket; `:714-751` the returned payload dict (its `summary` block at `:734-744`).
- Receipt row shape today (auto): `identity_key, mlbam_id, role, name, team, pos, level, valucast_rank, consensus_rank, divergence, call_up_date, logged_at`, plus `actual_call_up_date` when a real date is known. Seed rows (`_seed_receipts`, `:185-213`) additionally carry `field_label`, `seed: True`, and have `consensus_rank/divergence = None`.
- `call_up_date` = the board-OBSERVED date (archive-diff/flip). `actual_call_up_date` = the transaction date. Lead time must anchor on the **real** date when known, falling back to `call_up_date` when it isn't (both are the field's trigger; the real one is more correct).

Page + PNG (both gated behind `RECEIPTS_HOLD = True` at `app.py:78` — the public page is dark, so this ships silently until Alex flips the hold):

- `templates/receipts.html:60-98` — per-row article. The "called up {{ p.call_up_date }}" line lives inside a `buys-tag` span at `:67`/`:69` (AHEAD) and `:92` (BEHIND). This is where "flagged Nd early" attaches.
- `app.py:7168-7257` — `_receipts_share_card_png(...)`. Per-row draw is `draw_section(...)` at `:7213-7246`; the meta line ("team - pos - level") draws at `:7230-7231` via `_graphic_fit_text`. The `ranks` string draws at `:7232-7237`. There is horizontal room but rows are dense (`row_h = 60`); PNG rendering is "if trivial" per the mandate — see Step 4.

Repo conventions: stdlib-only; incremental builder (existing committed rows win the merge — see `_detect_call_ups` `:434` `merged = {...}`); the `_revalidate_existing` pass (`:533-573`) is the precedent for re-touching already-committed rows. `flagged_days_early` is derived fresh every build from the archive index, so it needs NO revalidation hook — it recomputes from scratch each run regardless of what the committed artifact stored (see Step 2 note).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Receipts tests | `python -m pytest -q tests/test_call_up_receipts.py` | all pass (incl. your new ones) |
| Rebuild artifact locally (spot-check) | `python -c "from prospects.call_up_receipts import run_call_up_receipts as r; import json; out=r(); print(json.dumps({k:v for k,v in out.items() if k in ('receipt_count','miss_count','status')}))"` then inspect `data/models/valucast_call_up_receipts.json` for `flagged_days_early` on auto rows | auto rows gain the field; git-restore the artifact after (see below) |
| Full suite (final gate) | `python -m pytest -q` | 1776 passed 0 failed (baseline) + your new tests; then restore the byproduct (next row) |
| Restore pytest byproduct | `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json` | clean `git status` for that file |

**Do NOT commit** `data/models/valucast_call_up_receipts.json` if the spot-check rebuild rewrote it — `git checkout -- data/models/valucast_call_up_receipts.json` after inspecting. The daily build owns that artifact; committing a locally-rebuilt copy (with a fresh `generated_at`/`logged_at`) would fight the pipeline. The field lands in production the next time the daily build runs.

## The definition (write it into a docstring exactly)

`flagged_days_early(row)` = the length of the **single continuous run** of archive dates, immediately preceding the anchor date, on which ValuCast ranked the player inside his claimed band.

- **Anchor date** = `actual_call_up_date` if present, else `call_up_date`. (The field's own trigger. Real date preferred.)
- **Claimed band** = `vc_archive_rank <= ceil(claimed_rank * 1.25)`, where `claimed_rank = row["valucast_rank"]` (the at-promotion VC rank already on the row) and `vc_archive_rank = archive_row["rank"]` for that player on a given archive date. The 1.25 slack absorbs day-to-day board jitter so one noisy day doesn't truncate the run; it is a documented constant, not a scoring rule.
- **Walk**: start at the latest committed archive date strictly `< anchor`. Step backward one archive snapshot at a time (over the dates present in `archive_by_date_key`, sorted descending). Count each date where the player's row exists AND is in-band. **Stop at the first date that is out-of-band OR has no row for the player** (a break in the run ends it — the number is a *continuous* foresight streak, not a lifetime tally).
- **Monotonicity**: the count only ever grows if ValuCast held the call longer/tighter. It cannot be inflated by a distant past in-band day separated by an out-of-band gap.
- **Provability / STOP-per-row**: if there is **no anchor date**, or **no committed archive date strictly before the anchor**, or the player has **no in-band day at all immediately before the anchor** (streak = 0), then **OMIT the field for that row** rather than writing `0` and pretending. A written `flagged_days_early` always means "provably in-band for ≥1 day"; its absence means "archives can't support the claim." (Do NOT store `0`.)

Worked example (verified against live archives, 7/09): Owen Murphy, `valucast_rank=26`, `actual_call_up_date=2026-07-06`, band `ceil(26*1.25)=33`. Walking back from 2026-07-05: in-band every day (ranks 27,24,23,22,21,22,22,20,19,19,19,17,17,17,29) until 2026-06-20 (rank 44 > 33) breaks it → `flagged_days_early = 15`.

## Scope

**In scope** (the only files you modify):
- `prospects/call_up_receipts.py` — add the helper + call it in the shadow-attach loop.
- `templates/receipts.html` — render "flagged Nd early" on AHEAD + BEHIND rows.
- `app.py` — render it on the PNG **only if trivial** (Step 4).
- `tests/test_call_up_receipts.py` — extend (new tests).

**Out of scope** (do NOT touch):
- `prospects/ahead_of_consensus.py`, `scripts/build_ahead_of_consensus_scorecard.py` — the AOTC scorecard rules are FROZEN (pre-registered 7/2) until the ~7/13 gate unlock. This plan does not build on that machinery at all; it reads only the `valucast_prospect_rank_v1` archives and the receipts row.
- Row **semantics** already committed: `call_up_date`, `actual_call_up_date`, `divergence`, `consensus_rank`, `valucast_rank`, sorting (`_sort_receipts`/`_sort_misses`), the merge, and the no-claim bucket. `flagged_days_early` is a NEW field only — no existing field's meaning or the merge order changes, so the incremental artifact does not need a `_revalidate_existing`-style migration (the field is recomputed every build from the archive index; see Step 2).
- `RECEIPTS_HOLD` — leave it `True`. Do not un-hold the page.
- The daily-build wiring and freshness validators (this field rides inside the existing `build_call_up_receipts` output; no new artifact, no schema-gate change needed).

## Git workflow

- Work directly on `master` (repo convention — direct-to-main), but **do NOT push**: master auto-deploys valucast.app via Render. Commit locally; the reviewer gates the push.
- NEVER `git add -A` or `commit -am` (repo guardrail — parallel sessions leave untracked files dirty). Stage each in-scope file explicitly.
- Commit message style (from git log — short imperative subject): `Add flagged_days_early lead time to every receipt row`.

## Steps

### Step 1: Write the lead-time helper

In `prospects/call_up_receipts.py`, add a module-level helper near `_archive_by_date_key` (it depends on that index's shape). Use `math.ceil`; add `import math` at the top if absent (stdlib, allowed).

```python
def _flagged_days_early(
    identity_key: str,
    claimed_rank: int | None,
    anchor_date: str | None,
    archive_by_date_key: dict[str, dict[str, dict]],
) -> int | None:
    """Consecutive archive days of foresight before a call-up (see the plan's
    definition block). Walking back from the latest archive date strictly before
    ``anchor_date``, count each day the player's archive ``rank`` sits inside the
    claimed band (rank <= ceil(claimed_rank * 1.25)); stop at the first out-of-band
    day or the first day with no row. Returns the run length, or ``None`` when the
    archives can't support the claim (no anchor, no earlier archive, or a zero-length
    run). Never returns 0 -- absence means unprovable, presence means >=1 proven day.
    Monotone: a continuous run only, so a distant in-band day across an out-of-band
    gap can't inflate it."""
    if claimed_rank is None or not anchor_date:
        return None
    band = math.ceil(claimed_rank * 1.25)
    earlier = sorted((d for d in archive_by_date_key if d < anchor_date), reverse=True)
    run = 0
    for date in earlier:
        arc_row = archive_by_date_key[date].get(identity_key)
        rank = _clean_int(arc_row.get("rank")) if isinstance(arc_row, dict) else None
        if rank is None or rank > band:
            break
        run += 1
    return run or None
```

Notes: `_clean_int` already exists (`:87`) — reuse it, don't reinvent. `band` uses the row's own `valucast_rank`, which for auto rows is the at-promotion VC rank (correct — that's the rank the receipt claims). The strict `d < anchor_date` prevents counting the anchor day itself (the call-up day is the field's trigger, not foresight).

**Verify**: `python -m pytest -q tests/test_call_up_receipts.py` still green (no callers yet — this only checks the module imports).

### Step 2: Attach it in the shadow-date loop

In `build_call_up_receipts`, extend the existing `:676-680` block so the same loop that attaches `actual_call_up_date` also computes lead time. `archive_index` is already in scope (`:633`). Anchor on the real date when known, else the observed `call_up_date`:

```python
    # Attach the real call-up date next to the archive-diff-inferred one, when a genuine
    # call-up transaction exists for that player. Never changes call_up_date or sorting.
    # (actual_dates was already computed above to drive the at-promotion standard.)
    for row in receipts + misses:
        real_date = actual_dates.get(str(row.get("mlbam_id")))
        if real_date:
            row["actual_call_up_date"] = real_date
        # Lead time: days ValuCast held this call before the field's trigger fired.
        # Anchor on the real date when known, else the board-observed call_up_date.
        # Recomputed every build from the archive index (no migration needed -- the
        # incremental merge preserves the row, and this just re-derives the field).
        days_early = _flagged_days_early(
            row.get("identity_key"),
            _clean_int(row.get("valucast_rank")),
            real_date or _date_part(row.get("call_up_date")),
            archive_index,
        )
        if days_early is not None:
            row["flagged_days_early"] = days_early
        else:
            row.pop("flagged_days_early", None)  # keep stale committed values from surviving
    if not actual_dates and not any("flagged_days_early" in r for r in receipts + misses):
        pass  # (no-op guard kept for readability; loop above already handles empty case)
```

Drop the old `if actual_dates:` guard that wrapped the block — the loop must run even when `actual_dates` is empty (lead time anchors on `call_up_date` in that case), and `real_date` is `None`-safe. The `.pop(...)` handles the incremental case where a previously-written `flagged_days_early` is no longer provable (e.g. archives pruned): a stale value must not survive.

Keep the third clause (`if not actual_dates ... pass`) OUT if it reads as dead weight — it is only a comment anchor; prefer deleting it and leaving the loop clean. The load-bearing change is: (a) unconditional loop, (b) compute + attach/pop `flagged_days_early`.

**Verify**: spot-check rebuild (Commands table) — confirm `flagged_days_early` appears on auto rows with real archive support (Murphy → 15) and is ABSENT on rows where it can't be proven. Then `git checkout -- data/models/valucast_call_up_receipts.json`.

### Step 3: Render "flagged Nd early" on the page

In `templates/receipts.html`, append the lead time to the "called up" `buys-tag` line on both sides. AHEAD side (`:67` and `:69`), append inside each span after the call-up date:

```jinja
... &middot; called up {{ p.call_up_date }}{% if p.flagged_days_early %} &middot; flagged {{ p.flagged_days_early }}d early{% endif %}
```

Apply the identical `{% if p.flagged_days_early %}...{% endif %}` suffix to the BEHIND row's tag at `:92`. Because the field is omitted (not `0`) when unprovable, the truthiness test hides it cleanly for seeds and short-lead rows — no extra guard needed.

**Verify**: `python -m pytest -q tests/test_call_up_receipts.py -k "renders_normally or hold"` → the two page-render tests still pass. If those tests assert on rendered HTML content, extend one to assert the "flagged" string appears when a row carries the field (see Test plan).

### Step 4: Render it on the share PNG — ONLY if trivial

The mandate says PNG rendering is conditional on being trivial. It IS trivial here: append the lead time to the existing meta line so no new row geometry is needed. In `app.py` `draw_section` (`:7230`), change the meta string to fold in lead time when present:

```python
            meta_parts = [row.get("team"), row.get("pos"), row.get("level")]
            if row.get("flagged_days_early"):
                meta_parts.append(f"flagged {row['flagged_days_early']}d early")
            meta = " - ".join(str(part) for part in meta_parts if part)
            draw.text((x + 150, top + 35), _graphic_fit_text(draw, meta, f_meta, 350), fill=muted, font=f_meta)
```

`_graphic_fit_text` already truncates to the 350px budget, so an overlong meta line degrades gracefully rather than overflowing. Do NOT add a new column, resize rows, or move any box — if fitting it into the meta line looks wrong, STOP at Step 3 and report that PNG rendering was deferred (page-only ships the feature; the PNG is behind `RECEIPTS_HOLD` anyway).

**Verify**: `python -m pytest -q tests/test_call_up_receipts.py` → all pass (the PNG route is `RECEIPTS_HOLD`-gated so it 404s in the held state; the render function itself is exercised only if a test calls it directly — if one does, confirm it still produces bytes).

### Step 5: Tests

Add to `tests/test_call_up_receipts.py` (model fixtures on `_rank_row` at `:594` and the end-to-end builder tests like `test_lagged_flip_rescored...` at `:460`):

1. **`test_flagged_days_early_counts_continuous_in_band_run`** — call `_flagged_days_early` directly with a hand-built `archive_by_date_key` of ~5 dates: player in-band on the 3 dates immediately before the anchor, out-of-band on the 4th → assert `== 3`. Add a 5th, earlier, in-band date separated by that out-of-band gap → assert it STAYS `3` (monotone/continuous, gap not bridged).
2. **`test_flagged_days_early_omitted_when_unprovable`** — (a) no anchor date → `None`; (b) anchor with no earlier archive date → `None`; (c) player out-of-band on the first day before the anchor (zero-length run) → `None`. Assert the helper returns `None` for each (never `0`).
3. **`test_build_attaches_flagged_days_early_to_auto_rows`** — end-to-end via `build_call_up_receipts` (mirror `test_actual_call_up_date_shadow_attaches_real_date_without_changing_anything_else` at `:267`): supply archives where a player is in-band for N days before his call-up; assert the receipt row has `flagged_days_early == N` and that a row with no supporting archive history does NOT have the key. Assert `call_up_date`, `divergence`, and sort order are unchanged (additive-only guarantee).
4. **(page)** extend the "renders normally" test (or add one) to confirm the template emits `flagged` when a receipt row carries `flagged_days_early` and omits it otherwise.

**Verify**: `python -m pytest -q tests/test_call_up_receipts.py` → all pass. Then `python -m pytest -q` → 1776 + new tests pass; `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json`.

## Test plan

- `tests/test_call_up_receipts.py`: +4 (helper continuous-run, helper omit-cases, end-to-end attach + additive-invariance, page-render presence/absence).
- No validator/schema-gate test changes: the field is optional and lives inside the existing artifact; nothing floors it or requires it.
- Final gate: full `python -m pytest -q` green, byproduct restored, artifact + prediction-archive files git-clean.

## Done criteria

- [ ] `python -m pytest -q` exits 0 (1776 baseline + new tests), byproduct file restored.
- [ ] `grep -n "_flagged_days_early" prospects/call_up_receipts.py` → helper defined once + called once in the shadow-attach loop.
- [ ] `grep -n "flagged_days_early" prospects/call_up_receipts.py templates/receipts.html` → present in builder + both template sides.
- [ ] `grep -n "return run or None\|return None" prospects/call_up_receipts.py` shows the helper never returns `0` (omit-not-zero contract).
- [ ] Spot-check rebuild shows `flagged_days_early` on real auto rows (Murphy=15) and absent where unprovable; then `git checkout -- data/models/valucast_call_up_receipts.json`.
- [ ] `git status`: only `prospects/call_up_receipts.py`, `templates/receipts.html`, `app.py` (if Step 4 taken), `tests/test_call_up_receipts.py` modified. No data artifacts staged.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- The `:676-680` shadow-attach loop no longer matches the excerpt (a later plan refactored it) — re-read and reconcile before wiring in; if `actual_call_up_date` is now attached somewhere else, attach lead time there instead.
- Archive board rows no longer carry the ValuCast rank under `row["rank"]` (the whole walk-back reads that field) — if the archive schema changed, STOP and report; do not guess an alternate field.
- Step 4's meta-line fold makes the PNG row overflow or look wrong even with `_graphic_fit_text` — ship page-only (Steps 1-3, 5) and report the PNG deferral. This is an accepted partial per the mandate ("if trivial").
- A row's `valucast_rank` is missing on an auto row (the band can't be computed) — the helper already returns `None` (omit); this is correct, not a STOP, but note it if it happens on a row you expected to score.

## Maintenance notes

- The 1.25 band slack is the one tunable knob. It exists to keep a single jittery board day from truncating an otherwise-continuous run; if it ever reads as too loose (a run survives a day the model clearly cooled on the player), tighten it toward 1.0 in the helper and re-run the receipts tests. It is NOT a scoring rule and touches nothing frozen.
- Because `flagged_days_early` is re-derived from the archive index every build (never trusted from the committed row), it self-heals: prune old archives and the number shrinks honestly; add backfilled archives and it grows. That is why it needs no `_revalidate_existing` hook, unlike the divergence-bearing fields.
- If Alex later un-holds the receipts page (`RECEIPTS_HOLD = False`), the "flagged Nd early" line and PNG meta go live automatically — no further change. Sanity-check the PNG meta line width on a real 8-row board at that point.
- Seed rows carry `valucast_rank` but their call-up history may predate the archive window; they'll usually get `None` (omitted) and that's correct — a curated seed makes no dated foresight claim.
