# Plan 019: Field-unranked auto lane — mint the most-differentiated call-ups by data, retire hand-seeding for them

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat fb360066..HEAD -- prospects/call_up_receipts.py prospects/ahead_of_consensus.py data/manual/call_up_receipts_seed.json`
> `prospects/call_up_receipts.py` landed the at-promotion standard TODAY (commit
> `fb360066`) — re-read it fresh before writing a line. If any in-scope excerpt
> below no longer matches the live code, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MEDIUM (mints NEW public receipt rows by a new rule — the whole point is a claim surface, so the classifier bar and the merge/dedupe are load-bearing)
- **Depends on**: none (isolated to the receipts builder + its tests + the seed file). Do NOT interleave with any other plan that edits `prospects/call_up_receipts.py`.
- **Category**: feature (accountability surface) + trust honesty
- **Planned at**: commit `fb360066`, 2026-07-09
- **Execution window**: anytime. This lane is ADDITIVE to the receipts builder and does NOT touch the AOTC scorecard machinery, so it is not gated by the ~7/13 unlock. (`RECEIPTS_HOLD=True` at `app.py:78` still hides the whole receipts page publicly; that flag is out of scope — flipping it is Alex's call, not this plan's.)

## Why this matters

The receipts board scores ARRIVAL, not outcome, and its trigger (the call-up) creates survivorship bias: bullish over-ranks that never get called up stay invisible, so the ledger can only ever show the calls that *resolved by promotion*. On top of that, the seed lane can only ADD hits — it is hand-curated JSON with no miss path — and today it is doing the single most important job on the board by hand. A call-up that fails `MIN_BOARDS=2` (the public field literally has no read on the player) can never auto-mint, yet that is the MOST differentiated call ValuCast can make: we ranked a guy the field didn't rank at all, and he reached MLB. Right now Hughes (vc#9), Kuroda-Grauer (#41), Cauley (#61), and Watson (#80) are **hand-seeded** with hand-typed `field_label: "field outside top 100"` strings. Hand-seeding the strongest calls reads as curation, not as a receipt — and the label is typed, not derived, so it can drift from the data it claims to summarize (the claims-register gap: a label that says "outside top 100" while a board actually had him at ~#512).

This plan adds a strict, data-derived AUTO path for exactly that bucket: a genuine post-launch call-up, ranked highly by ValuCast at promotion, that the public field had **fewer than 2 boards inside the 600 cap** on. The label is DERIVED from the at-promotion board count ("no public board inside 600" / "1 board, ~#512"), closing the hand-typed-label gap. Legacy seeds keep working; new qualifying rows come through the auto lane; identity dedupe guarantees a player never appears via both. Hughes at vc#9 is the worked example — he would qualify, so the auto lane earns its keep on day one.

## What this plan does NOT fix (say so out loud)

- It does **not** fix the core survivorship bias (over-ranks that never get called up are still invisible) — that is a fundamentally different surface (a "we said buy, the field faded him, he busted" ledger) and is out of scope here. This lane still only fires on ARRIVAL.
- Lead time is still **unweighted** — a 2-day-early field-unranked flag counts the same as a 30-day-early one. This plan does not introduce lead-time weighting; it only widens *which* arrivals can auto-mint. (Noted so nobody thinks the auto lane "solved" it.)

## Current state

All excerpts from `prospects/call_up_receipts.py` at `fb360066` unless noted.

- **The event stream is shared.** `_call_up_events` (:361-385) yields `(identity_key, source_row, cur_row)` for every disappearance/flip. `_detect_call_ups` (:408-485) walks those events, applies `_roster_confirmed` (:388-405), re-sources the scoring row via `_at_promotion_source_row` (:330-358), then calls the injected `from_row(scored_row, cur_date, logged_at)` classifier. **The field-unranked lane hooks the SAME event stream** — it is a third classifier alongside `_receipt_from_row`/`_miss_from_row`, not a new scan.
- **The classifier that rejects field-unranked guys today** is `_call_up_row` (:248-287). Its first hard gate:
  ```python
  public_ranks = _public_source_ranks(_source_ranks(row))
  if len(public_ranks) < MIN_BOARDS:
      return None, None
  ```
  `_public_source_ranks` (in `prospects/ahead_of_consensus.py:97-109`) keeps only external boards with `rank <= CONSENSUS_RANK_CAP` (**600**). So "fewer than 2 public boards ≤ 600 at promotion" is EXACTLY `len(public_ranks) < MIN_BOARDS` — the precise pool that currently returns `(None, None)` and, when a real call-up date exists, lands in the `no_claim` neither-bucket (`_detect_call_ups` :464-468). **This lane promotes a strict subset of that neither-bucket into real rows.**
- **The neither-bucket wiring already carries what we need.** `_detect_call_ups` receives `actual_dates`, `archive_by_date_key`, and `no_claim`; the at-promotion re-source (`scored_row = _at_promotion_source_row(...)`, :454-456) already hands the classifier the archive row that covered the REAL promotion date. The field-unranked classifier reads `scored_row` the same way, so its board-count and its rank are both **at-promotion**, not event-day (this is what makes the derived label honest and dodges the post-graduation rank collapse the at-promotion standard was built to fix).
- **Seed lane** (:185-213, `_seed_receipts`; merge at :660-669 in `build_call_up_receipts`): curated rows carry `divergence=None`, `seed=True`, and a hand-typed `field_label`. Merge rule (:663-669): a seed is merged ONLY if its `identity_key` is not already present among the auto-detected receipts (`by_key`). **Auto wins on identity** — this is the dedupe hook the new lane must slot into.
- **Sorting** (`_sort_receipts`, :216-229): scored rows (int `divergence`) lead, sorted by gap; rows without an int `divergence` (seeds today) trail, newest-call-up first. Field-unranked auto rows have **no int divergence** (there is no consensus to diff against), so they naturally sort into the trailing group with the seeds — correct, they are the same *kind* of claim.
- **Rendering already handles the no-divergence shape** (no template/app change needed):
  - `templates/receipts.html:66-75`: `{% if p.consensus_rank is not none %}` → "Field had him #N"; else → `{{ p.field_label or 'Field had him outside the top 100' }}`; and `{% if p.divergence is not none %}` → `+N` else → `AHEAD` chip.
  - `app.py:7232-7245` (share-card PNG): identical branch — `consensus_rank` present → "vs field #N"; else `field_label or 'field outside top 100'`; int divergence → `+N`/gap color, else the `AHEAD` chip.
  So a field-unranked auto row renders through the EXISTING `field_label` + `AHEAD` path the moment it carries `consensus_rank=None`, `divergence=None`, and a `field_label`. This lane's only new job is to MINT such rows from data and derive their label.
- **Denylist + launch guard + neither-bucket accounting** all run in `build_call_up_receipts` after detection (EXCLUDED at :670-671, LAUNCH_DATE at :682-691, no_claim tally at :698-706). A field-unranked row is a normal receipt row for all of these — it must be denylist-excluded, launch-guarded, and (once it becomes a claim) removed from the neither-bucket count, exactly like a scored hit.
- **`MAX_VALUCAST_RANK = 300`** (`ahead_of_consensus.py:48`) is the scored-hit rank cap. This lane uses a **stricter, separately pre-registered** cap (below) — do NOT reuse or change `MAX_VALUCAST_RANK`.

### Pre-registered thresholds for THIS lane (freeze these; they define the claim)

- `FIELD_UNRANKED_MAX_VALUCAST_RANK = 25` — at-promotion ValuCast rank must be `<= 25` (strict; the mandate's "strongest calls" bar). Hughes at vc#9 clears it; Kuroda-Grauer (#41)/Cauley (#61)/Watson (#80) do **not** auto-qualify and stay as legacy seeds — that asymmetry is intended and must be documented in the code comment.
- Board bar: `len(at-promotion public_ranks) < MIN_BOARDS` (i.e. `< 2`, reusing the existing `MIN_BOARDS`/`CONSENSUS_RANK_CAP=600` definitions — do not fork them).
- Roster confirmation: unchanged `_roster_confirmed` (today's snapshot OR a genuine call-up transaction).
- Launch guard: unchanged `LAUNCH_DATE` on `actual_call_up_date`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Targeted tests | `python -m pytest -q tests/test_call_up_receipts.py` | all pass (existing + your new ones) |
| Page/share render still green | `python -m pytest -q tests/test_call_up_receipts.py -k "hold or normally"` | pass (RECEIPTS_HOLD path unaffected) |
| Full suite (final gate) | `python -m pytest -q` | 1776+ pass, 0 fail; then `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json` (pytest dirties it — NEVER commit it) |
| Live artifact sanity (optional, read-only) | `python scripts/build_valucast_call_up_receipts.py` | runs; inspect that Hughes (`687312_pitcher`) now appears as an AUTO field-unranked row (no longer only via seed) — then `git checkout -- data/models/valucast_call_up_receipts.json data/prediction_archive/valucast_call_up_receipts/` to avoid committing a data churn |

## Scope

**In scope** (the only files you should modify):
- `prospects/call_up_receipts.py` — add the field-unranked classifier + label derivation + wire it into `_detect_call_ups`/`build_call_up_receipts` as a third lane; make the merge/dedupe treat auto field-unranked rows as first-class (they win over seeds on identity).
- `data/manual/call_up_receipts_seed.json` — remove the Hughes row (now auto-minted). Leave Kuroda-Grauer/Cauley/Watson (they don't clear vc#25). Update `_comment` to say the seed is now legacy-only for sub-#25 field-unranked calls.
- `tests/test_call_up_receipts.py` — extend (do not rewrite existing tests).

**Out of scope** (do NOT touch):
- `prospects/ahead_of_consensus.py` and `scripts/build_ahead_of_consensus_scorecard.py` — AOTC scorecard rules are FROZEN (pre-registered 7/2) until the ~7/13 unlock. You READ `MIN_BOARDS`/`CONSENSUS_RANK_CAP`/`_public_source_ranks` from `ahead_of_consensus.py`; you do not change them.
- `templates/receipts.html`, `app.py` — the `field_label`/`AHEAD` render path already handles the no-divergence shape (verified above). No render change is needed; if you think one is, STOP and report — it means a row shape assumption is off.
- `app.py:78 RECEIPTS_HOLD` — do not flip it.
- The scored-hit / miss classifiers (`_call_up_row`, `_receipt_from_row`, `_miss_from_row`) and their semantics — the new lane is a SIBLING, it must not change when an existing scored hit/miss mints.
- `_revalidate_existing` re-scoring of scored rows — see Step 4 for the field-unranked-specific revalidation; do not alter the existing hit/miss re-score path.

## Git workflow

- Work directly on `master` (repo convention — direct-to-main), but **do NOT push**: master auto-deploys valucast.app via Render. Commit locally; the reviewer gates the push.
- NEVER `git add -A` / `commit -am` (repo guardrail — parallel sessions leave untracked files, and there are already untracked `plans/0**.md` + `data/dd/dd_dynasty_feed.json` in the tree). Stage each in-scope file explicitly.
- Never `git stash`.
- Commit message style (imperative, from git log): `Auto-mint field-unranked call-ups; retire the Hughes hand-seed`.

## Steps

### Step 0: Confirm the row shape and the neither-bucket path (read-only)

Re-read `_detect_call_ups` (:408-485) and trace ONE event end to end for a field-unranked player: the event fires → `_roster_confirmed` passes (real txn or roster) → `scored_row` is the at-promotion archive row → `from_row(scored_row, ...)` returns a row → merged. Confirm that TODAY, for a `<2`-board player, `from_row` (`_receipt_from_row`) returns `None`, so he falls into the `no_claim` branch (:464-468). That branch is the exact fork your new lane must intercept: qualifying field-unranked players become a ROW; the rest stay in `no_claim`.

**Verify**: no code change yet — just confirm the trace matches. If `_detect_call_ups` does not match the excerpt, STOP.

### Step 1: Add the pre-registered constant + the label derivation

Near the top of `prospects/call_up_receipts.py` (with the other module constants), add:
```python
# Field-unranked auto lane: mint a receipt for the strongest calls the divergence
# gate CAN'T score -- a post-launch call-up we ranked highly that the public field
# had NO real read on (fewer than MIN_BOARDS public boards inside the 600 cap at
# promotion). Replaces hand-seeding these. STRICT rank cap (25, not MAX_VALUCAST_RANK
# 300): only the most-differentiated calls earn an auto row; Kuroda-Grauer(#41)/
# Cauley(#61)/Watson(#80) stay legacy seeds by design. Pre-registered; frozen.
FIELD_UNRANKED_MAX_VALUCAST_RANK = 25
```
Add a helper that DERIVES the label from the at-promotion public boards (never hand-typed):
```python
def _field_unranked_label(public_ranks: dict) -> str:
    """Human line for a field-unranked auto receipt, derived from the at-promotion
    board coverage. 0 boards inside the 600 cap -> 'no public board inside 600';
    exactly 1 -> '1 board, ~#<rank>'. (This lane only fires below MIN_BOARDS, so the
    count is 0 or 1.)"""
    if not public_ranks:
        return "no public board inside 600"
    rank = round(min(public_ranks.values()))
    return f"1 board, ~#{rank}"
```
(Use `_public_source_ranks` + `_source_ranks` — already imported/defined — to build `public_ranks` from a scored row. Do not re-implement the 600 cap.)

**Verify**: `python -c "from prospects.call_up_receipts import _field_unranked_label as f; print(f({}), '/', f({'hkb': 512.4}))"` → `no public board inside 600 / 1 board, ~#512`.

### Step 2: Add the field-unranked classifier (the third `from_row`)

Add a classifier with the SAME signature as `_receipt_from_row` — `(row, cur_date, logged_at) -> dict | None` — that fires only for the strict field-unranked case:
```python
def _field_unranked_from_row(row: dict, cur_date: str, logged_at: str) -> dict | None:
    """Mint a field-unranked receipt: a call-up we ranked <= FIELD_UNRANKED_MAX_VALUCAST_RANK
    at promotion that the public field had < MIN_BOARDS boards inside the 600 cap on.
    consensus_rank/divergence are None (there's no field consensus to diff) -- the card
    renders the derived field_label + an AHEAD chip via the existing no-divergence path."""
    key = _identity_key(row)
    valucast_rank = _clean_int(row.get("rank"))
    if not key or valucast_rank is None:
        return None
    public_ranks = _public_source_ranks(_source_ranks(row))
    # Only the bucket the scored classifier CAN'T handle: sub-MIN_BOARDS coverage.
    if len(public_ranks) >= MIN_BOARDS:
        return None
    if valucast_rank > FIELD_UNRANKED_MAX_VALUCAST_RANK:
        return None
    return {
        "identity_key": key,
        "mlbam_id": str(row.get("mlbam_id")),
        "role": str(row.get("role")).lower(),
        "name": row.get("name"),
        "team": row.get("mlb_team") or row.get("team") or "-",
        "pos": _pos(row),
        "level": row.get("level") or "-",
        "valucast_rank": valucast_rank,
        "consensus_rank": None,
        "divergence": None,
        "field_label": _field_unranked_label(public_ranks),
        "call_up_date": cur_date,
        "logged_at": logged_at,
        "field_unranked": True,
    }
```
Carry a `field_unranked: True` marker (NOT `seed`) so downstream can tell an auto field-unranked row from both a scored hit and a curated seed, and so revalidation (Step 4) can target it. Do **not** set `seed` on it — `seed` means curated-and-exempt; this row is auto-derived.

**Design note to include as a code comment**: this classifier and `_receipt_from_row` are mutually exclusive on the same row (one requires `>= MIN_BOARDS` boards, the other `< MIN_BOARDS`), so wiring both against the same event can never double-mint the same player as a scored hit AND a field-unranked row.

### Step 3: Wire the lane into detection and the build

`_detect_call_ups` already takes a single `from_row`. The cheapest correct wiring (match the existing pattern, minimal diff): add a `detect_field_unranked(...)` sibling to `detect_receipts`/`detect_misses` (:488-530) that calls `_detect_call_ups(..., _existing_field_unranked(existing_log), _field_unranked_from_row, ...)`, plus an `_existing_field_unranked` reader modeled on `_existing_receipts` (:177-183) that pulls rows from a **new `field_unranked` list** on the artifact (fall back to `[]`).

In `build_call_up_receipts`:
1. Load `field_unranked = _existing_field_unranked(existing_log)` alongside `receipts`/`misses` (:620-621).
2. In the per-pair loop (:635-648), after `detect_receipts`/`detect_misses`, call `field_unranked = detect_field_unranked(prev, cur, cur_date, roster_lookup, field_unranked, logged_at=..., prev_date=..., actual_dates=..., archive_by_date_key=..., no_claim=no_claim)`. **Pass the same `no_claim` dict** — a field-unranked player who fails the rank cap still belongs in the neither bucket, and a player who becomes a field-unranked ROW must be REMOVED from `no_claim` (do it the same way scored claims are: they end up in `claimed_keys` at :698, so include field-unranked identities there — see step 3.5).
3. Merge field-unranked into the receipts board so it renders on the "AHEAD OF THE FIELD" side. Two viable shapes — **pick the one that keeps the render/sort correct and document why**:
   - (Recommended) Fold `field_unranked` rows into the `receipts` list right before the seed merge (:660), so `_sort_receipts` places them in the trailing no-divergence group (with seeds), and the seed dedupe at :663-669 naturally skips any seed whose identity is now an auto field-unranked row (**auto wins over seed on identity — the required dedupe**). Keep them out of `misses`.
   - Guard: when folding in, **auto field-unranked wins over a scored row only if there is no scored row for that identity** — but by Step 2's mutual-exclusivity that collision can't happen for the same at-promotion row; still, assert identity-uniqueness across `receipts + field_unranked` before merge and STOP if a key appears in both (that would mean an upstream shape drift).
3.5. **Claimed-keys + summary**: add every field-unranked identity to `claimed_keys` (:698) so it leaves the `no_claim` count. Add `"field_unranked_count": len(field_unranked_rows)` to `summary` (next to `seed_count`/`no_claim_call_up_count`). Do NOT change `receipt_count` semantics unless the reviewer wants field-unranked folded into it — default: `receipt_count` counts the final `receipts` list, which now INCLUDES field-unranked rows (they render on that side), so it grows by the field-unranked count naturally. State this explicitly in the summary comment.
4. Persist: add `"field_unranked": field_unranked_rows` to the returned payload dict (:714-751) **only if** you kept them as a separate persisted list per Step 3's `_existing_field_unranked` reader. If you folded them entirely into `receipts` and re-derive them on read via the `field_unranked` marker, you do NOT need a separate top-level key — but then `_existing_field_unranked` must read `field_unranked`-marked rows out of `receipts`. **Choose ONE representation and make `_existing_field_unranked` read from exactly where you write.** (Incremental-merge correctness: existing rows must round-trip, so the reader and writer MUST agree.)

**Incremental-merge invariant (non-negotiable)**: the receipts builder is INCREMENTAL from the committed artifact — existing rows win the merge. A committed field-unranked row must survive the next build unchanged (idempotent), exactly like a committed scored hit. Prove it with the idempotency test in Step 5.

### Step 4: Revalidate committed field-unranked rows under the at-promotion standard

`_revalidate_existing` (:533-573) re-scores committed AUTO scored rows and drops ones that no longer classify. Field-unranked rows have `divergence is None`, so the current guard `if not key or row.get("seed") or row.get("divergence") is None: kept.append(row); continue` **exempts them** — they'd survive forever even if a later archive shows the field actually DID rank the player (≥2 boards) at promotion, which would retroactively mean he never was a field-unranked call.

Add a **field-unranked-specific** revalidation (do not entangle it with the hit/miss path):
- For each committed row with `field_unranked is True` and a known `actual_call_up_date` earlier than its `call_up_date` and a covering archive: re-fetch the at-promotion archive row, recompute `len(_public_source_ranks(...))` and `valucast_rank`, and KEEP it only if it still satisfies `< MIN_BOARDS` boards AND `rank <= FIELD_UNRANKED_MAX_VALUCAST_RANK`. If it no longer qualifies, drop it and record it in `no_claim` (same as the scored path). If no real date / no covering archive, KEEP (can't re-score → don't guess), matching the scored path's conservatism.
- Also **re-derive `field_label`** from the at-promotion board coverage when you re-source (so a committed row's label can't go stale against its own at-promotion data — this is the claims-register honesty fix, enforced not just at mint).

Keep this as a small dedicated function (e.g. `_revalidate_field_unranked`) called right after the existing `_revalidate_existing` calls (:657-658). Do not widen `_revalidate_existing`'s `want_kind` contract.

### Step 5: Tests

Add to `tests/test_call_up_receipts.py` (reuse the `_rank_row`, `_cu`, `_cache` helpers at the bottom):

1. **Hughes worked example (the headline test).** A vc#9 pitcher, ZERO public boards, genuine post-launch call-up → auto-mints a field-unranked receipt with `consensus_rank is None`, `divergence is None`, `field_label == "no public board inside 600"`, `field_unranked is True`, and NOT `seed`. Assert it lands on `payload["receipts"]` and is counted in `summary["field_unranked_count"]`, and that `no_claim_call_up_count` does NOT count him.
2. **1-board label derivation.** A vc#12 player with exactly one board at ~#512 → row minted, `field_label == "1 board, ~#512"`.
3. **Rank-cap rejection.** A vc#41 player, zero boards, genuine call-up → NO field-unranked row (fails the strict 25 cap) → he stays in the neither bucket (`no_claim_call_up_count == 1`). (This is the Kuroda-Grauer case — proves the strict cap keeps the weaker calls as seeds, not auto rows.)
4. **Two-board player is NOT field-unranked.** vc#20 with 2+ boards and a real gap → mints as a SCORED hit (`divergence` is an int), NOT a field-unranked row (`field_unranked` absent). Proves mutual exclusivity — no double-mint.
5. **Seed dedupe / auto-wins-on-identity.** Provide a seed row for Hughes' identity AND let him auto-mint → exactly one Hughes row, it is the AUTO one (`field_unranked is True`, `seed` absent), `seed_count` does not count him.
6. **Idempotency (incremental merge).** Build once, feed the resulting artifact back as `existing_log`, build again with the same inputs → the field-unranked rows are byte-identical (same as `test_detect_receipts_recomputes_consensus_and_merges_idempotently` in spirit). Proves committed rows round-trip.
7. **Revalidation drop.** Commit a field-unranked row for a player, then supply an at-promotion archive where the field actually had ≥2 boards on him at his real call-up date → the committed row is DROPPED and he moves to `no_claim`. (Mirror the Keys/Cabrera revalidation tests' structure.)
8. **Denylist + launch guard still bind.** A denylisted identity and a pre-launch `actual_call_up_date`, each otherwise field-unranked-qualifying → neither mints (reuse the existing denylist/launch test shapes).

**Verify each step** with `python -m pytest -q tests/test_call_up_receipts.py` after writing that step's test; then the full suite at the end.

## Test plan

- `tests/test_call_up_receipts.py`: +8 tests (list above). No existing test should change behavior — the scored-hit/miss/seed/no_claim tests must all still pass unmodified (if one breaks, you changed a shared path you shouldn't have — STOP and reconcile).
- Final: `python -m pytest -q` all green (baseline 1776 passed 0 failed → expect 1784+), then `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json`.

## Done criteria

- [ ] `python -m pytest -q` exits 0; byproduct archive file restored after.
- [ ] `grep -n "FIELD_UNRANKED_MAX_VALUCAST_RANK" prospects/call_up_receipts.py` → constant defined `= 25`, and referenced in the classifier AND the revalidation.
- [ ] `grep -n "_field_unranked_from_row\|_field_unranked_label\|detect_field_unranked" prospects/call_up_receipts.py` → all three present and wired.
- [ ] `grep -n "field_unranked_count" prospects/call_up_receipts.py` → present in the summary dict.
- [ ] `grep -n "Gabriel Hughes\|687312" data/manual/call_up_receipts_seed.json` → NO hits (the Hughes seed is removed).
- [ ] `grep -n "Cauley\|Watson\|Kuroda-Grauer" data/manual/call_up_receipts_seed.json` → still present (legacy seeds retained).
- [ ] The 8 new tests exist and pass; all pre-existing `tests/test_call_up_receipts.py` tests pass unmodified.
- [ ] `git status` shows ONLY `prospects/call_up_receipts.py`, `data/manual/call_up_receipts_seed.json`, `tests/test_call_up_receipts.py` modified (plus the restored byproduct file untouched). No `data/models/valucast_call_up_receipts.json` or archive churn committed.
- [ ] `plans/README.md` status row updated (or the dispatching reviewer maintains it).

## STOP conditions

- `_detect_call_ups`, `_call_up_row`, or the `no_claim` branch no longer matches the excerpts (something landed after `fb360066` — re-read `prospects/call_up_receipts.py` and reconcile; if the at-promotion standard was refactored, STOP and report rather than layering on a moved target).
- You find you MUST edit `templates/receipts.html` or `app.py` to render a field-unranked row — that means a row-shape assumption here is wrong (the render path already handles `consensus_rank=None`/`divergence=None`/`field_label`). STOP and report; do not widen scope into the app.
- The reader/writer of persisted field-unranked rows disagree on location (a committed row doesn't round-trip in the idempotency test) — fix the representation before proceeding; an incremental merge that loses committed rows is a data-integrity bug, not a test nit.
- Any pre-existing `tests/test_call_up_receipts.py` test changes behavior — you touched a shared classifier/merge path. Back out and re-scope to the sibling lane.
- The live build (optional Step: `build_valucast_call_up_receipts.py`) mints a field-unranked row for anyone whose `actual_call_up_date` is pre-`LAUNCH_DATE` or who is on `EXCLUDED_IDENTITY_KEYS` — the guards regressed. STOP.

## Maintenance notes

- **Why vc#25 strict and separate from `MAX_VALUCAST_RANK` (300):** the scored-hit cap is 300 because a scored hit has field corroboration (≥2 boards) backing the gap. A field-unranked row has NO field corroboration — it is purely ValuCast's own conviction — so it must clear a much higher conviction bar to be a public receipt. 25 is pre-registered; changing it changes what the board CLAIMS, so treat it like the AOTC targets: don't nudge it without a memo.
- **Derived label, never typed:** the whole point of the lane over hand-seeding is that `field_label` is computed from the at-promotion board coverage at BOTH mint (Step 2) and revalidation (Step 4). If a future change lets a hand-typed label back in on an auto row, the claims-register drift this plan closed reopens.
- **Seeds are now legacy-only for sub-#25 field-unranked calls.** Kuroda-Grauer/Cauley/Watson remain seeds because they don't clear vc#25; if a future call clears #25 it auto-mints and its seed (if any) is deduped out. When those three eventually age off relevance, the seed lane can be revisited — but leaving the mechanism for legacy rows is deliberate (the mandate: "leave the seed mechanism for legacy rows").
- **Reviewer scrutiny:** (1) confirm no player can appear on BOTH `receipts` (field-unranked) and `misses`; (2) confirm the idempotency test genuinely round-trips a committed field-unranked row through `existing_log`; (3) confirm `no_claim_call_up_count` DROPS by exactly the number of newly-minted field-unranked rows (they leave the neither bucket) and doesn't double-count.
