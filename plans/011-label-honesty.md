# Plan 011: Labels stronger than the data — gate "High" confidence, floor the consensus label, and explain the value scale

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat ac20b1f2..HEAD -- prospects/rank_v1.py web/dynasty_models.py web/public_snapshot_models.py app.py templates/partials/rankings_table_dynasty.html templates/partials/player_detail_dynasty.html templates/methodology.html templates/value_map.html prospects/call_up_receipts.py templates/receipts.html`
> This plan was written at `ac20b1f2` with UNCOMMITTED receipts work already in
> the tree (`prospects/call_up_receipts.py`, `tests/test_call_up_receipts.py`,
> `templates/receipts.html` — an at-promotion rescoring fix in flight). Before
> editing any of those three files re-read them against HEAD: the line numbers
> below (esp. the seed-lane block) may have shifted. If any "Current state"
> excerpt no longer matches the live file, treat it as a STOP condition for
> that step and reconcile before proceeding.

## Status

- **Priority**: P1
- **Effort**: M (six labeling fixes, each S; two touch a Python data path, four are template/copy)
- **Risk**: LOW (no scoring math changes; only what labels claim and when)
- **Depends on**: none (touches app.py tier block + templates; coordinate ordering with plans 005/007 if both edit app.py, but no overlap in the specific regions)
- **Category**: bug (label/data honesty)
- **Planned at**: commit `ac20b1f2`, 2026-07-09

## Why this matters

ValuCast's brand is that a number never claims more than the data behind it. A 7/9 claims-register audit found six places where a **label is stronger than the data it sits over** — each one a screenshot a prospect-Twitter reader can use to call the honesty-branded site dishonest:

- **(a) "High" confidence on a 1-PA player.** The confidence chip reads `High` off a model-profile gate (`role_gate`/`impact_gate`/`sample_reliability>=45`) that never consults the current-season sample floor. A reader who opens a prospect with essentially no current MLB/MiLB line and sees a green **High confidence** chip catches the site asserting high confidence on thin air — while the honest `uncertainty_label` (a "Wide band: …" read) is computed and sits unused on the same row.
- **(b) "Public Consensus" minted from ONE board.** The player card's `Public Consensus ~P#N` figure is a median over `public_source_ranks`, which has no minimum-board floor — so a single outside board produces a "consensus." The site's own noise guard is `MIN_BOARDS=2` ("never a one-board straw man"). A reader who finds a "Public Consensus" resting on one board catches the exact single-deep-board failure the guard exists to stop.
- **(c) ETA sold as a per-player forecast.** The prospect board's **ETA** column renders either the integer ETA year or a static level→window lookup (`AAA → ~1 yr`, `A → ~2-3 yr`) from `LEVEL_ETA_HINTS`. Presented under a bare "ETA" header it reads as a per-player arrival forecast; it is really "everyone at this level gets this window." A reader who notices every AAA prospect shows the identical ETA catches a lookup table dressed as a projection.
- **(d) Hand-typed `field_label` that the archives contradict.** Seed-lane receipts render a free-text `field_label` ("field outside top 100") with an AHEAD badge as a data-backed claim. Gabriel Hughes is seeded "field outside top 100" while STS actually ranks him ~#512 on one board; Kuroda-Grauer/Cauley have zero public boards. On the one board that markets itself as un-cherry-picked receipts, a typed label the data contradicts is the sharpest possible miss.
- **(e) The 0-100 Dynasty Value scale is never explained.** The board/detail/map publish "Dynasty Value 100.0" and a "Dynasty value" Y-axis with no definition anywhere — what 100 anchors to, MLB-vs-prospect derivation, or how the $ column is produced. A critic frames it as "they explain everything except the headline number," an asymmetry that is glaring next to the elaborate prospect scorecards.
- **(f) A dead "elite" tier floor labeled for a scale that doesn't exist.** `DYNASTY_ELITE_FLOOR = 140.0` with a docstring asserting a "140+ band on the 0-150 scale" is dead code: the served snapshot is a 0-100 scale (`value_scale = 0_100_valucast_dynasty_score`, max = 100.0), so **zero** players clear 140 and the "always tier 1 — elite is an absolute badge" branch never fires. Tier 1 is purely gap-defined and can shrink/merge under the min-3 rule. A reader who exports the board catches the tier semantics mislabeled relative to the shipped scale.

None of these are fabricated numbers — they are honest builders with labels that round off the caveat. This plan makes each label say exactly what the data supports.

## Current state

Verified at `ac20b1f2`. Read each cited line yourself before editing — the register's refs may have drifted and the receipts files are mid-edit.

### (a) Confidence "high" ignores current sample
- `prospects/rank_v1.py:1529-1551` — `_confidence(source, model_profile, reliability, current_context)`. The pedigree/fallback branch (`:1543-1546`) DOES consult `current_context["skill_band"]` and returns `low` on `band == "thin"` or no context. But the **model-scored** "high" branch is:
  ```python
  role_gate = (model_profile or {}).get("role_gate")
  impact_gate = (model_profile or {}).get("impact_gate")
  if role_gate == "active" and impact_gate == "active" and (reliability or 0.0) >= 45:
      return "high"
  return "medium"
  ```
  `reliability` is `components.get("sample_reliability")` — a model-side reliability, not a current-season PA/IP floor. `current_context` (with `skill_band`) is passed in but never consulted in this branch. So a model-strong profile with a **thin** current sample returns `high`.
- `_factual_current_context` (`:610-689`) assigns `skill_band = "thin"` for the thinnest current lines (hitter `:672`, pitcher `:636`). This is the exact signal the fallback branch already trusts.
- The confidence rides the board row at `:2038` (`"confidence": confidence`) and the display-only `uncertainty` component at `:1997`.
- Board render: `templates/partials/rankings_table_dynasty.html:161-165` shows the confidence chip **only when `v11`** (the dd_dynasty v1.1 column); `:59` is the header. Prospect mode does not render a confidence column — the chip appears in the detail card headline (`player_detail_dynasty.html:52-53`, "… confidence") and the `uncertainty_label` is already rendered in the detail card at `:287-288`.

### (b) "Public Consensus" median with no board floor
- `web/dynasty_models.py:104-112` and `web/public_snapshot_models.py:143-150` — `public_source_consensus` returns the rounded median of `public_source_ranks.values()` whenever the list is non-empty. **No `>= MIN_BOARDS` guard** — a single board yields a "consensus."
- `web/dynasty_models.py:93-101` / `public_snapshot_models.py:133-140` — `public_source_ranks` filters `source_ranks` to external boards under `_CONSENSUS_RANK_CAP` (600).
- `templates/partials/player_detail_dynasty.html:467-476` — renders `Public Consensus ~P#{{ row.public_source_consensus }}` and a count note `{{ row.public_source_ranks | length }} board(s)` (so the count IS shown), but the **label "Public Consensus" + the median math still fire on n=1**. The "Ahead of the Curve" chip at `:472` already gates on `length >= 3`; the spread strip at `:486` gates on `length >= 2`. Only the bare consensus figure is ungated.
- The canonical floor is `prospects/ahead_of_consensus.py:42` `MIN_BOARDS = 2`, whose comment calls it "the line between ~40 credible early calls and a garbage list driven by single deep boards."

### (c) ETA column is a level-window lookup
- `prospects/availability.py:59-67` — `LEVEL_ETA_HINTS` maps level → window string; `:147-153` `eta_window(row)` returns the explicit integer ETA if present, else the level hint. `:158-170` `_ETA_WINDOW_LABELS` / `eta_window_label` render the compact labels (`~1 yr`, `~2-3 yr`, …).
- `web/dynasty_models.py:118-125` and `web/public_snapshot_models.py:110-118` — `eta_display` returns `str(self.eta)` (the year) when `eta` is set, else `eta_window_label(...)` (the level-derived window).
- `templates/partials/rankings_table_dynasty.html:52` — header `<th class="col-eta …">…ETA</th>` (no tooltip). `:154` — cell `{{ row.eta_display or '—' }}`.

### (d) Seed `field_label` is a free-text string, not derived
- `prospects/call_up_receipts.py:185-213` (`_seed_receipts`) — copies `row.get("field_label") or "field outside top 100"` verbatim from the seed file. The seed rows carry `consensus_rank: null` / `divergence: null` precisely because the boards don't produce a `>=2`-board consensus; the actual per-board `source_ranks` are NOT consulted to build the label.
- `data/manual/call_up_receipts_seed.json` — 4 rows, all `field_label: "field outside top 100"`; Gabriel Hughes (`687312_pitcher`) is one of them. The `_comment` explicitly invites hand-editing the label.
- `templates/receipts.html:69` — renders `{{ p.field_label or 'Field had him outside the top 100' }}`.
- `app.py:7236` (receipts share-card PNG) — `f"VC #… - {row.get('field_label') or 'field outside top 100'}"`.
- Available data to derive from: the ranked-board archive rows carry `source_ranks` per identity (used everywhere else via `_public_source_ranks`). The seed row itself does NOT carry `source_ranks`; the builder would need to look the player up in the same board archive it already loads, OR the derivation happens where the seed is merged against the auto-detected board. **Read `prospects/call_up_receipts.py` end-to-end at execution time** to find where board `source_ranks` for a seed identity are reachable (the auto-scan already reads them). If they are NOT reachable at seed-merge time without a new data load, the correct fix is a **validator** (see Step 4b) rather than a live derivation.

### (e) 0-100 Dynasty Value scale unexplained
- `templates/methodology.html` — grep confirms **no** dynasty-value / 0-100 / value-scale / dollar section anywhere. Sections present: "What ValuCast is" (`:29`), "The two boards" (`:40`), "Prospect Rank v1" (`:53`), "How the model works" (`:124`), scorecard (`:208`), AOTC rules (`:244`), sensitivity (`:276`), "What we have and haven't proven" (`:318`).
- The value appears at `templates/partials/rankings_table_dynasty.html:51` (header "Dynasty Value") / `:153` (cell), `player_detail_dynasty.html:41`, and the `/map` Y-axis `templates/value_map.html:159` (`'Dynasty value'`) + tooltip `:118` (`value.toFixed(1)`).
- Served scale: `data/public/public_dynasty_snapshot.json` per-player `value_scale = "0_100_valucast_dynasty_score"`; verified max = 100.0, min = 0.0, n = 3730.

### (f) Dead elite floor at 140 on a 0-100 scale
- `app.py:836-857` — `DYNASTY_ELITE_FLOOR = 140.0`; docstring: "Values >= DYNASTY_ELITE_FLOOR (the 140+ band on the 0-150 scale) are always tier 1 — elite is an absolute badge". `_compute_dynasty_tiers` filters `elite = [r for r in rows if value_of(r) >= 140.0]`; on the 0-100 snapshot `elite` is always empty → falls through to `_gap_tiers`.
- Verified: on the served snapshot **0** players reach 140; **4** reach >=95, 4 reach >=93 (max is 100.0).
- Caller: `app.py:902-913` `_dynasty_tiers_for` → `_compute_dynasty_tiers(pool, value_of=value_of)`; `pool` rows carry `dynasty_value` (0-100) and `value_scale`.
- Existing tests: `tests/test_dynasty_tiers.py` uses 140+/145/150 literals for the elite band (`test_small_elite_band_never_merges_down`, `test_two_elites_stay_tier_one`) and a `78.0`-max prospect band for the no-elite case. **These tests encode the old 0-150 assumption and WILL need updating** when the floor moves — that is expected and in scope; do not delete the elite-band coverage, re-point it to the new floor.

Repo conventions: templates are Jinja2; no new deps; tests are plain pytest/unittest; ASCII-safe (no em-dashes in files that PS5.1 touches — but these are Python/HTML, standard tooling, so normal punctuation in HTML copy is fine — match the existing file's style).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Confidence/rank tests | `python -m pytest -q tests/test_prospect_rank_v1.py` | all pass |
| Dynasty model/tier tests | `python -m pytest -q tests/test_dynasty_tiers.py tests/test_dynasty_models.py tests/test_public_dynasty_snapshot.py` | all pass |
| Receipts tests | `python -m pytest -q tests/test_call_up_receipts.py` | all pass (re-verify against the in-flight edit first) |
| Consensus label tests | `python -m pytest -q tests/test_card_intelligence.py tests/test_ahead_of_consensus.py` | all pass |
| Template smoke | `python -c "import jinja2, pathlib; jinja2.Environment(loader=jinja2.FileSystemLoader('templates')).get_template('partials/player_detail_dynasty.html')"` (repeat for `methodology.html`, `partials/rankings_table_dynasty.html`, `receipts.html`) | no exception |
| Elite-floor liveness | `python -c "import json; d=json.load(open('data/public/public_dynasty_snapshot.json',encoding='utf-8')); v=[p['value'] for p in d['players'] if isinstance(p.get('value'),(int,float))]; import app; print(sum(1 for x in v if x>=app.DYNASTY_ELITE_FLOOR))"` | > 0 (at least one player clears the recalibrated floor) |
| Full suite (final gate) | `python -m pytest -q` | ~1771+ pass, 0 fail; then `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json` (pytest dirties it — NEVER commit it) |

## Scope

**In scope** (the only files you may modify):
- `prospects/rank_v1.py` — Step 1 (confidence sample gate).
- `web/dynasty_models.py`, `web/public_snapshot_models.py` — Step 2 (consensus board floor).
- `templates/partials/player_detail_dynasty.html` — Step 2 (label/count), Step 5 (value explainer link).
- `templates/partials/rankings_table_dynasty.html` — Step 3 (ETA header tooltip), optionally Step 1 (surface uncertainty in prospect confidence display).
- `templates/methodology.html` — Step 5 (dynasty-value section).
- `templates/value_map.html` — Step 5 (value axis explainer link).
- `app.py` — Step 6 (elite floor + docstring).
- `prospects/call_up_receipts.py`, `templates/receipts.html` — Step 4 (field_label). **Mid-edit; re-verify first.**
- `scripts/validate_valucast_call_up_receipts.py` — Step 4b, only if adding the validator.
- Tests: `tests/test_prospect_rank_v1.py`, `tests/test_dynasty_tiers.py`, `tests/test_dynasty_models.py`, `tests/test_card_intelligence.py`, `tests/test_call_up_receipts.py` (extend existing files).

**Out of scope** (do NOT touch):
- `prospects/ahead_of_consensus.py`, `scripts/build_ahead_of_consensus_scorecard.py` — the AOTC scorecard rules are FROZEN (pre-registered 7/2) until the ~7/13 gate unlock. You may READ `MIN_BOARDS` from there (or re-declare the same value) but must not change scoring.
- The `_confidence` medium/low branches beyond the one added sample gate — do not re-tune the pedigree logic.
- The dollar-value math (`_dynasty_dollars`, redraft $). Step 5 only DOCUMENTS the scale; it does not change any number.
- The `/gaps` board copy (already shows per-row board_count; a separate plan owns its freshness).
- Any scoring/value computation. This plan changes only labels, one confidence bucket, and one tier constant.

## Git workflow

- Work directly on `master` (repo convention — direct-to-main), but **do NOT push**: master auto-deploys valucast.app via Render. Commit locally; the reviewer gates the push.
- NEVER `git add -A` or `commit -am` (repo guardrail — parallel sessions leave untracked files, and the receipts work + the untracked `dd_dynasty_feed.json` / audit JSON must not be swept in). Stage each file explicitly by path.
- Do NOT stage `data/prediction_archive/…/2026-06-15.json` or `data/models/valucast_call_up_receipts.json` (pytest/build byproducts).
- Commit message style (from git log): short imperative subject, e.g. `Gate High confidence on current sample; floor consensus label; explain the 0-100 value scale`.

## Steps

### Step 1: Gate "High" confidence behind a current-sample floor

In `prospects/rank_v1.py::_confidence` (the model-scored branch at `:1547-1551`), require a non-thin current sample before returning `high`. Add before the `return "high"`:
```python
band = str((current_context or {}).get("skill_band") or "").lower()
current_is_thin = (not current_context) or band == "thin"
if role_gate == "active" and impact_gate == "active" and (reliability or 0.0) >= 45 and not current_is_thin:
    return "high"
return "medium"
```
Rationale: `high` should mean the model AND a real current sample agree. A thin/absent current line caps the chip at `medium` (never demote a genuinely-sampled model-strong profile). This reuses the exact `skill_band` signal the pedigree branch already trusts, so the two branches become consistent.

**Do NOT** touch the `uncertainty` component or the point estimate — the band is display-only and already correct.

**Verify**: `python -m pytest -q tests/test_prospect_rank_v1.py` → all pass. Add 1 test: a model profile with `role_gate/impact_gate == "active"`, `sample_reliability >= 45`, and `factual_current_context={"skill_band":"thin"}` → `_confidence(...) == "medium"` (was `"high"`); the same inputs with a non-thin band → `"high"`. If an existing test asserts `"high"` for a thin-sample fixture, that test was encoding the bug — update it and note the change in your report.

### Step 2: Floor the "Public Consensus" label at MIN_BOARDS (2)

The bare consensus figure must not be minted from a single board. Fix at the model layer so every surface inherits it:

1. In BOTH `web/dynasty_models.py::public_source_consensus` (`:104-112`) and `web/public_snapshot_models.py::public_source_consensus` (`:143-150`), return `None` when fewer than 2 boards back it:
   ```python
   ranks = sorted(self.public_source_ranks.values())
   if len(ranks) < 2:          # a single board is not a consensus (MIN_BOARDS)
       return None
   ```
   (Keep the median math unchanged below.) Use a named constant `_MIN_CONSENSUS_BOARDS = 2` at module top in each file, with a comment referencing `ahead_of_consensus.MIN_BOARDS` as the canonical source — do not import the AOTC module (frozen; avoid a coupling that could drag the freeze). The two files already duplicate `public_source_ranks` verbatim, so a local constant matches the existing duplication pattern.

2. In `templates/partials/player_detail_dynasty.html`, the `:467` block now only renders when `public_source_consensus is not none` (i.e. `>=2` boards), so a 1-board case shows no "consensus." Add an explicit 1-board affordance so the single board isn't silently dropped: when `row.public_source_ranks | length == 1`, render a distinct line — e.g. `<span class="stat-label">Public boards</span>` + `1 board (not a consensus)` — instead of the "Public Consensus" label. Keep the `~P#N` median ONLY for the `>=2` path. The count note at `:471` stays.

**Verify**: `python -m pytest -q tests/test_card_intelligence.py tests/test_dynasty_models.py` → all pass. Add 1 test on the model class: a row with one external board in `source_ranks` → `public_source_consensus is None`; two boards → returns the rounded median. Template smoke per the commands table.

### Step 3: Relabel the ETA column as a level-based window

The ETA column mixes a real integer ETA year with a static level→window lookup. Make the header honest without changing the data. In `templates/partials/rankings_table_dynasty.html:52`, add a `title` tooltip to the ETA `<th>` (matching how `:55` and `:61` already use `title=` on headers):
```html
<th class="col-eta sortable" aria-sort="none" title="Estimated arrival. A year is a per-player ETA when we have one; otherwise a level-based window (everyone at that level shares it), not a per-player forecast."><button …>ETA</button></th>
```
Keep the cell (`:154`) as-is. This is a copy-only change — no Python, no data.

**Verify**: template smoke (`get_template('partials/rankings_table_dynasty.html')` → no exception). `grep -n "level-based window" templates/partials/rankings_table_dynasty.html` → 1 hit.

### Step 4: Derive the seed `field_label` from the archives (or gate it)

**Re-read `prospects/call_up_receipts.py` against HEAD first — this file is mid-edit.**

Preferred (4a — derive): if, at the point `_seed_receipts` rows are merged, the per-identity board `source_ranks` are reachable (the auto-scan already reads the ranked-board archive to compute consensus), replace the free-text label with a derived one:
- 0 public boards under the cap → `"no public board inside 600"`.
- exactly 1 board at rank `r` → `"1 board, ~#{r}"`.
- `>=2` boards → this row would not be seed-only; let the auto path own it.

Apply the derived label in the builder so it flows to both `templates/receipts.html:69` and `app.py:7236` (share-card) unchanged. A seed row may still carry an explicit `field_label` override, but only USE it when it does not contradict the archives (see 4b).

Fallback (4b — validate) — REQUIRED regardless of whether 4a is feasible: add a build-time check in `scripts/validate_valucast_call_up_receipts.py` (which already inspects `field_label` at `:55-57`): if a seed row's typed `field_label` claims "outside top 100" / "outside the top N" but a public board in the archive actually ranks that identity at `<= N`, the validator FAILS naming the player and the contradicting board. This is the honesty backstop: a hand-typed label can never survive the build if the archive disproves it. If 4a is genuinely infeasible (board `source_ranks` not reachable at seed-merge without a new heavy load — report this finding), 4b alone is the accepted fix and the label stays typed but is now archive-checked.

Do NOT invent a miss lane for seeds and do NOT change which rows are seeds — only the label's truthfulness.

**Verify**: `python -m pytest -q tests/test_call_up_receipts.py` → all pass. If 4a: add a test that a seed identity with a 1-board archive rank of ~512 derives `"1 board, ~#512"` (the Gabriel Hughes case), NOT "field outside top 100". If 4b: add a test that a seed `field_label` contradicted by a board `<=100` makes the validator return a problem. Run `python scripts/validate_valucast_call_up_receipts.py` against the committed artifact → exit 0 (today's seeds must pass after any label change; if a real contradiction surfaces, fix the seed file's label, that is the point).

### Step 5: Explain the 0-100 Dynasty Value scale

Add ONE methodology section and link to it from the two value surfaces. No number changes.

1. In `templates/methodology.html`, add a new `<section>` (place it after "The two boards" at `:40-51`, since the value scale spans both boards) with an `id="dynasty-value-scale"` `<h3>`:
   - Define the scale: Dynasty Value is a 0-100 score; 100 anchors to the top of the board (the single most valuable dynasty asset), not a real-world unit.
   - State the MLB-vs-prospect derivation honestly: MLB and prospect values come from separate 0-100 normalizations aligned at the top of the board (do NOT claim a unit-reconciled cross-universe calibration — a separate finding covers that; here just disclose it).
   - One line on the $ column: replacement-adjusted auction dollars where total payout = teams x budget, driven by the roster/teams/budget knobs.
   - Keep it to a short paragraph or a 3-4 row list; match the surrounding section voice.
2. In `templates/partials/player_detail_dynasty.html` near the Dynasty Value headline (`:41` region) and in `templates/value_map.html` near the axis label (`:159`) or the heading sub-line (`:23`), add a small "what is this?" affordance linking to `/methodology#dynasty-value-scale` (a plain `<a href="/methodology#dynasty-value-scale">`). Minimal footprint — a superscript/link, not a redesign.

**Verify**: template smoke for all three templates. `grep -rn "dynasty-value-scale" templates/` → the methodology anchor + at least the two links. Manual read: the section actually answers "what does a 72 mean vs a 95?".

### Step 6: Recalibrate the elite tier floor to the served 0-100 scale

In `app.py:836`, the `DYNASTY_ELITE_FLOOR = 140.0` is dead on the 0-100 snapshot. Two acceptable approaches — prefer (A):

- **(A) Drive it from the served scale.** Set a floor appropriate to 0-100 (e.g. `95.0`, matching the 4 players currently >=95 — verify the count at execution time, it may drift). Update the docstring (`:842-844`) to say "the 95+ band on the 0-100 dynasty value scale" — delete the "0-150" / "140+" language. Keep the `_gap_tiers` fallback and the min-3 protection exactly as-is.
- **(B) Read the scale from the artifact.** If the pool rows expose `value_scale`, branch the floor on the scale string (0-100 → 95, legacy 0-150 → 140). This is more robust but heavier; only do it if `value_of`'s rows reliably carry `value_scale` at this call site (they do NOT today — `_compute_dynasty_tiers` takes bare rows with `dynasty_value`). Given that, **(A) is the recommended fix**; do not over-engineer.

Whichever you pick, the invariant is: **at least one player on the current served snapshot must clear the floor**, so the "elite is an absolute badge" branch is live again and can't silently rot.

Update `tests/test_dynasty_tiers.py`: re-point the elite-band fixtures from 140/145/150 to values above the new floor (e.g. 96/98/100) and the no-elite band to values below it, preserving the three behaviors (small band never merges, 2-player band holds tier 1, no-elite falls to gap tiering). Add the liveness assertion: run `_compute_dynasty_tiers` over a synthetic pool including a >=floor value and assert that row is tier 1.

**Verify**: `python -m pytest -q tests/test_dynasty_tiers.py` → all pass. Run the "Elite-floor liveness" command from the table → prints a count `> 0`. `grep -n "0-150\|140+" app.py` → no hits in the tier docstring.

## Test plan

- `tests/test_prospect_rank_v1.py`: +1 (thin current sample caps confidence at medium; non-thin stays high).
- `tests/test_dynasty_models.py` (and/or `tests/test_card_intelligence.py`): +1 (single-board consensus is None; 2-board returns median).
- `tests/test_call_up_receipts.py`: +1 (derived 1-board label OR validator catches a contradicted seed label).
- `tests/test_dynasty_tiers.py`: rewrite the three elite/no-elite fixtures to the recalibrated floor + add a liveness assertion.
- Template changes (Steps 2 tail, 3, 5) are covered by the template-smoke command; no logic tests needed for pure copy.
- Final: `python -m pytest -q` all green (~1771+ pass, 0 fail), then `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json`.

## Done criteria

- [ ] `python -m pytest -q` exits 0 (byproduct file restored after; receipts model JSON NOT staged).
- [ ] `grep -n "current_is_thin\|skill_band" prospects/rank_v1.py` → the high-branch now consults the current sample band.
- [ ] `grep -n "_MIN_CONSENSUS_BOARDS\|len(ranks) < 2" web/dynasty_models.py web/public_snapshot_models.py` → both files floor the consensus at 2 boards.
- [ ] `grep -n "not a consensus\|1 board" templates/partials/player_detail_dynasty.html` → the 1-board affordance exists.
- [ ] `grep -n "level-based window" templates/partials/rankings_table_dynasty.html` → ETA header tooltip present.
- [ ] `grep -n "dynasty-value-scale" templates/methodology.html templates/partials/player_detail_dynasty.html templates/value_map.html` → anchor + both links.
- [ ] `grep -n "0-150\|140+" app.py` → no hits in the tier block; `grep -n "DYNASTY_ELITE_FLOOR = " app.py` → the recalibrated value.
- [ ] Elite-floor liveness command prints `> 0`.
- [ ] Step 4: either a derived `field_label` in `prospects/call_up_receipts.py` OR a contradiction check in `scripts/validate_valucast_call_up_receipts.py`; `python scripts/validate_valucast_call_up_receipts.py` exits 0.
- [ ] `git status`: only in-scope files modified; the receipts model artifact and the 06-15 archive are NOT staged; `dd_dynasty_feed.json` and the audit JSON remain untracked.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- The receipts files (`prospects/call_up_receipts.py`, `templates/receipts.html`, `tests/test_call_up_receipts.py`) diverge from the excerpts here because the in-flight rescoring edit landed differently — reconcile Step 4 against the live code before touching it; if the seed-lane block was refactored, report and re-plan Step 4.
- `_confidence`'s high branch no longer matches the `:1547-1551` excerpt (someone re-tuned confidence first) — re-read and reconcile, do not blind-edit.
- `public_source_consensus` is no longer duplicated across the two model files (someone consolidated it) — apply the floor to the single canonical implementation instead of both.
- Recalibrating `DYNASTY_ELITE_FLOOR` would put ZERO players on the current snapshot above the floor even at a 0-100-appropriate value (snapshot scale changed) — STOP and report the actual max/value_scale; the floor must be data-driven, never a guess that stays dead.
- Deriving `field_label` (4a) requires loading a new heavy artifact at seed-merge time — fall back to 4b (validator only) and report that 4a was infeasible.

## Maintenance notes

- The `_MIN_CONSENSUS_BOARDS = 2` constant duplicated in the two model files must stay equal to `ahead_of_consensus.MIN_BOARDS`. If the AOTC freeze ever lifts and that value changes, update both model copies (a comment in each points here). Duplication is deliberate — importing the frozen AOTC module into the request path would couple the live board to a frozen file.
- Step 6's floor is a scale-specific constant. If the snapshot ever moves off 0-100 (e.g. back to 0-150), the floor and its liveness test must move with it — the liveness assertion is the tripwire that makes a stale floor fail the build instead of silently going dead again.
- Step 1 makes `high` require BOTH model and current-sample agreement. If a future model change wants pedigree-only "high" for a specific class, add it as an explicit branch with its own justification — do not loosen the `current_is_thin` gate quietly.
- Reviewer scrutiny: confirm no scoring/value number changed anywhere (diff should be labels, one confidence bucket, one tier constant, and tests). The point estimate and the display-only uncertainty band are untouched.
