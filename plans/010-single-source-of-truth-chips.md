# Plan 010: One claim, one computing function — kill the four contradictory-chip surfaces

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run FIRST)**: this plan was written against HEAD `ac20b1f2`.
> Run:
> `git diff --stat ac20b1f2..HEAD -- prospects/rank_v1.py web/prospect_context.py web/public_snapshot_models.py templates/partials/rankings_table_dynasty.html templates/partials/player_detail_dynasty.html templates/partials/_value_spark.html app.py`
> If any of those changed since `ac20b1f2`, re-read the cited lines on the LIVE
> file before editing and reconcile against the "Current state" excerpts below;
> on a mismatch with an excerpt, treat it as a STOP condition.
>
> **Working-tree note (verify at execution time)**: at planning time the tree
> had UNCOMMITTED receipts work in `prospects/call_up_receipts.py`,
> `tests/test_call_up_receipts.py`, and `templates/receipts.html` (an
> at-promotion rescoring fix in flight). None of those three files are in this
> plan's scope. Run `git status --short` first; if any of THIS plan's in-scope
> files already show as modified, STOP and report — someone else is mid-edit.
> Do NOT `git stash`.

## Status

- **Priority**: P1
- **Effort**: M (four independent display/guard fixes; each is S)
- **Risk**: LOW (three are display-only; one adds a guard clause to an existing pure function)
- **Depends on**: 011 first (011 Step 1 owns the shared `_confidence` gate; this plan's Step 1 only verifies it and adds the contradiction regression test)
- **Category**: bug (epistemic honesty — contradictory public claims)
- **Planned at**: commit `ac20b1f2`, 2026-07-09

## Why this matters

ValuCast's brand is verifiable honesty: every public claim must survive a
prospect-Twitter regular screenshotting it. A 7/9 claims-register audit found
four places where **two independent code paths render two claims about the same
thing on the same card, and the claims contradict** — the single most
screenshot-able class of failure on the site. The principle this plan encodes:
*every public claim has ONE computing function; surfaces render its output,
they never recompute it or pair it with a second, unreconciled source.*

The four register embarrassment scenarios, verbatim, so you know exactly what
public failure each fix prevents:

- **(a) "High" confidence chip next to a "Thin sample" chip.** Register:
  *"16 rows show both chips at once (P#28 Briceno 19 PA, P#153 Noble Meyer 4 IP,
  P#397 Gutierrez 1 PA, P#533 Montilla 1 PA, P#716 Kudrna 2 IP...). why_rank_chips
  reads factual_current_context.skill_band == 'thin' and labels 'Thin sample',
  while _confidence for the main-model source never consults skill_band=='thin' at
  all (that guard only exists in the pedigree branch). A reader who notices 'High'
  next to 'Thin sample' on the same line correctly concludes one of the two is
  untrustworthy — undermining the whole 'verifiable honesty' brand on a single
  screenshot."*

- **(b) Form Curve panel vs Recent form chip point opposite directions.**
  Register: *"Charlie Condon's card shows 'Form Curve -12.1 over 31d' (red, down)
  beside 'Recent form: Heating Up'... One card claims heating up, bullish, early,
  AND a big red -12.1 form line. 8+ prospects show this divergence. 'Form Curve'
  reads as on-field form to a baseball reader but is actually the delta of
  ValuCast's own dynasty VALUE (a model recompute), so two 'form' signals point
  opposite directions and neither resolves it."*

- **(c) On-page AOTC "spots ahead" vs the share PNG AOTC banner use DIFFERENT
  rank sources.** Register: *"On Condon the HTML card resolves to ValuCast Rank
  P#53 and consensus ~P#48 (roughly even/behind the field), while clicking 'Share
  graphic' produces a PNG stamped 'VC #3 vs field ~#66 — +63 — 17d early'. Two
  different ValuCast ranks (53 vs 3) and contradictory divergence stories
  reachable from one player's card, because feed prospect_rank and
  valucast_prospect_rank_v1 rank are different numbers. A reader screenshotting
  both catches ValuCast contradicting itself."*

- **(d) Board mobile stat strip shows an unlabeled level-slice next to a Level
  badge naming a different level.** Register: *"P#1 Eli Willits renders with Level
  'A+' ... but the mobile stat strip shows OPS 0.918 / Sample 232 PA — and
  factual_current_context.level is 'A' (the lower level), not A+. So the prominent
  number beside the 'A+' chip is silently his A-ball slice, unlabeled. This is the
  exact AA/A+ split-mislabel class a sharp reader already caught this week."*

## Current state

Verified at `ac20b1f2`. Read each cited line on the live file yourself before
editing — the drift check above tells you when to distrust these excerpts.

### (a) Confidence "High" vs "Thin sample" — the guard exists in one branch only

`prospects/rank_v1.py:1529-1551`, function `_confidence`:
```python
def _confidence(
    source: str,
    model_profile: dict | None,
    reliability: float | None,
    current_context: dict | None = None,
) -> str:
    if source in {PEDIGREE_SCORE_SOURCE, "universal_fallback", "identity_only_fallback"}:
        # ...pedigree branch...
        band = str((current_context or {}).get("skill_band") or "").lower()
        if not current_context or band == "thin":
            return "low"
        return "medium"
    role_gate = (model_profile or {}).get("role_gate")
    impact_gate = (model_profile or {}).get("impact_gate")
    if role_gate == "active" and impact_gate == "active" and (reliability or 0.0) >= 45:
        return "high"        # <-- main-model path: skill_band NEVER consulted
    return "medium"
```
- The pedigree branch (`:1543-1546`) already downgrades a `band == "thin"` line
  to `"low"`. The main-model branch (`:1547-1551`) checks only role/impact gates
  and `reliability >= 45` (a pedigree-blended prior, NOT current sample), so a
  1-PA line can read `"high"`.
- The callsite (`prospects/rank_v1.py:1989-1994`) already passes
  `current_context = components.get("factual_current_context")` — the
  `skill_band` value is in hand at that branch; it is simply ignored.
- The "Thin sample" chip that contradicts it: `web/prospect_context.py:129-142`
  (`why_rank_chips`) calls `skill_band_label(context)`, and
  `_SKILL_LABELS[(role, "thin")] == "Thin sample"` (`:11,16`). The board renders
  the chip at `templates/partials/rankings_table_dynasty.html:107-112` and the
  confidence chip independently at `:161-165` (`{{ confidence.get('level') | title }}`,
  where `confidence = row.confidence`, set at `:72`).
- `factual_current_context.skill_band` is assigned `"thin"` in
  `prospects/rank_v1.py:_factual_current_context` (`:636`, `:672`) — the SAME
  field both paths read, so a shared guard is a true single-source fix.

### (b) Form Curve vs Recent form — two different "form" measurements, both labeled "form"

- **Form Curve** panel: `templates/partials/_value_spark.html:1-35`. Title is
  literally `<h4>Form Curve</h4>` with sub `rolling daily dynasty value` (`:7-9`),
  delta styled by `spark.direction` (`:11`), which is `"up"/"down"/"flat"` from
  `web/value_spark.py:54` (`"up" if delta > 0 else "down"...`). The spark is built
  in `app.py:8071` as `build_spark(dd_row.value_history)` — the delta of
  ValuCast's own dynasty VALUE over the calendar span. Included on the card at
  `templates/partials/player_detail_dynasty.html:145-147`.
- **Recent form** chip: `templates/partials/player_detail_dynasty.html:246-248`,
  renders `recent_form.momentum_label` (`Heating Up`/`Cooling Off`/`Steady`, from
  `prospects/recent_form.py:_label`, `:68-71`) with the hardcoded text
  `last {{ recent_form.window_days or 30 }}d vs season`. `recent_form` is a
  DIFFERENT artifact (`valucast_recent_form_signal.json`, loaded
  `app.py:5032-5034`) comparing a recent MiLB stat window against the player's
  own season line.
- These are two legitimately different quantities (model value delta vs on-field
  stat momentum). The fix is NOT to make them agree — it is to **disambiguate the
  labels** so a reader cannot read them as the same "form" signal pointing two
  ways. "Form Curve" is the offender: to a baseball reader "form" means on-field
  form, but the panel is a model-value curve.

### (c) On-card AOTC vs share-PNG AOTC — genuinely two rank sources

- **Card (HTML) side**: `templates/partials/player_detail_dynasty.html:451-475`.
  The "ValuCast Rank" and "spots ahead/behind the field" note read
  `row.prospect_rank` (`:455,:460`) and `row.public_source_consensus` (`:459-461,
  :470`). Here `row` is the **DD feed row** (`dd_row` from `dd_store`,
  `app.py:8067`), whose `prospect_rank` is the feed's board rank and whose
  `public_source_consensus` is the median of the feed's `public_source_ranks`
  (`web/public_snapshot_models.py:142-150` for the snapshot analogue).
- **Share-PNG side**: the AOTC banner text is built by
  `app.py:_ahead_of_consensus_receipt_text` (`:4894-4922`) →
  `AHEAD OF THE CURVE — VC #{valucast_rank} vs field ~#{consensus_rank} · +{divergence}`,
  where the receipt comes from `app.py:_ahead_of_consensus_for_key` (`:4861-4891`),
  which reads `data/models/valucast_ahead_of_consensus.json` and returns that
  artifact's `valucast_rank` / `consensus_rank` (rank_v1-derived, a DIFFERENT
  number from the feed's `prospect_rank`). `_card_consensus_value` (`:4925-4945`)
  prefers the same receipt's `consensus_rank`.
- **Key enabling fact**: the artifact receipt is ALREADY in the detail-card
  template context. `_artifact_context_for_row` (`app.py:5019-5061`) computes
  `ahead_of_consensus = _ahead_of_consensus_for_key(key)` (`:5024`) and returns it
  under key `"ahead_of_consensus"` (`:5060`); that dict is merged into the
  template context via `context.update(artifact_context)` (`app.py:8085`). The
  template just doesn't use it for the source-evidence rank — it recomputes from
  the feed instead. So the single-source fix is: **make the HTML source-evidence
  block render the same `ahead_of_consensus` receipt the PNG uses**, when that
  receipt exists.

### (d) Board mobile stat strip level vs Level badge — strip has no level tag

- The strip: `templates/partials/rankings_table_dynasty.html:137-146` iterates
  `row.factual_context_stat_items[:4]` — `Sample / OPS / ISO / BB-K`, with NO
  level label. `factual_context_stat_items` →
  `web/public_snapshot_models.py:451-453` → `stat_items(self.factual_current_context)`
  → `web/prospect_context.py:86-112` (emits only Sample + rate items, never a
  level).
- The Level badge / ETA on the same row derive from `card_level_label`
  (`web/public_snapshot_models.py:220-235`), which can return the COMBINED level
  (e.g. `"A+ & A"` via `_card_combined_level_label`, `:237-252`) — a different
  level from the strip's `factual_current_context.level` slice (the "A" slice).
- The register's own strengths note the fix pattern already lives in this file:
  `card_level_label` and `_card_combined_level_label` deliberately build the
  joined label from the `levels` list and never split on `"+"` (`:248-252`,
  comment: *"The 'A+' level contains a literal '+', so never split ... on '+'"*).
  The strip just needs to name the level of the line it is showing.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Confidence guard tests | `python -m pytest -q tests/test_prospect_rank_v1.py` | all pass |
| Board render tests | `python -m pytest -q tests/test_public_dynasty_snapshot.py` | all pass |
| Form / card intelligence tests | `python -m pytest -q tests/test_recent_form.py tests/test_card_intelligence.py` | all pass |
| Share-card AOTC tests | `python -m pytest -q tests/test_ahead_of_curve_card_stamp.py` | all pass |
| Full suite (final gate) | `python -m pytest -q` | ~1771+ pass, 0 fail; then restore the byproduct file (below) |

**Byproduct restore (MANDATORY after any full-suite run):**
`git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json`
— pytest dirties this file as a side effect. NEVER commit it.

## Scope

**In scope** (the only files you may modify):
- `prospects/rank_v1.py` — the `_confidence` main-model guard, gap (a).
- `templates/partials/_value_spark.html` — Form Curve label disambiguation, gap (b).
- `templates/partials/player_detail_dynasty.html` — Recent form clarifier (b) + source-evidence single-source rank (c).
- `web/prospect_context.py` **and/or** `web/public_snapshot_models.py` — level tag on the stat strip, gap (d) (see Step 4 for which).
- `templates/partials/rankings_table_dynasty.html` — render the strip's level tag, gap (d).
- Tests: `tests/test_prospect_rank_v1.py`, `tests/test_public_dynasty_snapshot.py`, `tests/test_card_intelligence.py` (extend existing files; add a new test module only if the surface has no existing home).

**Out of scope** (do NOT touch):
- `prospects/ahead_of_consensus.py` and `scripts/build_ahead_of_consensus_scorecard.py` — the AOTC scorecard rules are FROZEN (pre-registered 7/2) until the ~7/13 gate unlock. Gap (c) is a DISPLAY reconciliation only; you are not touching how ranks/divergence are computed, only which already-computed source the HTML renders.
- `prospects/call_up_receipts.py`, `tests/test_call_up_receipts.py`, `templates/receipts.html` — uncommitted receipts work in flight (see working-tree note).
- `web/value_spark.py` and `prospects/recent_form.py` — the two "form" MODELS are correct; gap (b) is a labeling fix in templates only. Do NOT change either computation.
- The `_confidence` PEDIGREE branch — it already has the thin guard; only the main-model branch is missing it.
- The confidence chip's other consumers (uncertainty band, drivers) — gap (a) is one guard clause, nothing downstream.

## Git workflow

- Work directly on `master` locally, **do NOT push** — master auto-deploys
  valucast.app via Render; the reviewer gates the push.
- NEVER `git add -A` or `commit -am` (repo guardrail — parallel sessions leave
  untracked files). Stage each in-scope file explicitly.
- Commit style (short imperative subject), e.g.:
  `Single-source the confidence/form/AOTC/level chips so no card contradicts itself`.

## Steps

### Step 1: gap (a) — verify the thin-sample guard, do NOT implement it here

**DEDUP (reviewer, 7/9): plan 011 Step 1 owns the `_confidence` change** — its
current-sample gate on the model-scored "high" branch subsumes this plan's thin
guard (a thin band can never satisfy it). Execute plan **011 before 010**. In
this step you only: (1) confirm `_confidence`'s model-scored branch already
gates "high" on the current sample (grep for the 011 change; if it is absent,
STOP and report — do not implement two overlapping gates), and (2) add the
regression assertion for THIS plan's specific contradiction to the test file:
no public-snapshot row may carry confidence "high" together with the
"Thin sample" why-rank chip. The original overlapping implementation sketch is
kept below ONLY as context for what 011's gate must make impossible:
```python
band = str((current_context or {}).get("skill_band") or "").lower()
role_gate = (model_profile or {}).get("role_gate")
impact_gate = (model_profile or {}).get("impact_gate")
if band == "thin":
    return "medium"   # never "High" when the board also shows "Thin sample"
if role_gate == "active" and impact_gate == "active" and (reliability or 0.0) >= 45:
    return "high"
return "medium"
```
Keep it to `"medium"` (not `"low"`) on the main-model path — the score is
model-gated (not pedigree-led), so `"low"` would over-correct and drift from the
pedigree branch's meaning. The goal is only: no row is simultaneously `"high"`
and `"thin"`. Do not touch the pedigree branch.

**Verify**: `python -m pytest -q tests/test_prospect_rank_v1.py` → all pass, plus
1 new test: `_confidence("prospect_model_v0_6", {"role_gate":"active","impact_gate":"active"}, 90.0, {"skill_band":"thin"})` returns `"medium"` (NOT `"high"`); and the same call with `skill_band="impact"` still returns `"high"`.

### Step 2: gap (b) — disambiguate the two "form" labels on the detail card

Two edits, both label-only (no computation changes):

1. `templates/partials/_value_spark.html`: the panel currently titles itself
   `Form Curve` (`:8`) with sub `rolling daily dynasty value` (`:9`). Rename the
   heading so a baseball reader cannot read it as on-field form. Use
   `ValuCast Value Trend` (or `Model Value Trend`) for the `<h4>`, and keep/adjust
   the sub to make clear it is ValuCast's own model value, e.g.
   `rolling daily ValuCast value — not on-field form`. Do NOT change `spark.*`
   fields or the delta styling logic.
2. `templates/partials/player_detail_dynasty.html:247`: the Recent form chip
   already says `last {{ recent_form.window_days or 30 }}d vs season`. Leave the
   `momentum_label` and the window text as-is (the window is already artifact-driven).
   The rename in edit 1 is what resolves the contradiction; only add a short
   clarifier here IF, after edit 1, the two panels could still be conflated — keep
   any addition to a few words and do not restyle.

Do not soften the red down-color on the value-trend delta — the number is honest;
the label was the lie. Renaming the panel is the fix.

**Verify**: `python -m pytest -q tests/test_card_intelligence.py tests/test_recent_form.py`
→ all pass. Then `grep -n "Form Curve" templates/partials/_value_spark.html`
→ no hits (the ambiguous label is gone). If any test asserts the literal string
`"Form Curve"`, update that assertion to the new label (it is a display string,
not a contract) and note it.

### Step 3: gap (c) — render ONE ValuCast rank for the AOTC claim (card == PNG)

The share PNG's AOTC banner reads the `ahead_of_consensus` artifact receipt; the
HTML source-evidence block recomputes from the feed. Make the HTML block render
the SAME receipt when it exists, so both surfaces of one player agree.

In `templates/partials/player_detail_dynasty.html`, in the source-evidence block
(`:451-476`): the receipt is available in the template context as
`ahead_of_consensus` (a dict with `valucast_rank`, `consensus_rank`,
`divergence`, `board_count`, `days_ahead`; see `app.py:4883-4891` for its exact
shape, and `:5024,:5060,:8085` for how it reaches the template). When
`ahead_of_consensus` is a non-empty dict with an integer `valucast_rank`:
- render `ValuCast Rank` as `P#{{ ahead_of_consensus.valucast_rank }}`,
- render the consensus as `~P#{{ ahead_of_consensus.consensus_rank }}`,
- compute the "spots ahead/behind the field" note from
  `ahead_of_consensus.divergence` (positive = ahead), matching the PNG's
  `+{divergence}` sign convention (see `_ahead_of_consensus_receipt_text`,
  `app.py:4901,4911`),
- and keep the existing `active_mlb_callup` suppression guard (`:459`) — the PNG
  path is gated the same way at the featured-board level.

When `ahead_of_consensus` is absent/empty, fall back to the CURRENT feed-based
rendering unchanged (a player with no AOTC receipt still shows his feed
`prospect_rank`; there is no second source to contradict in that case, so no
inconsistency). Board-count wording (`:471`) should read the receipt's
`board_count` when the receipt is in use, else the existing
`public_source_ranks | length`.

CRITICAL single-source constraint: after this step, for any player who has an
`ahead_of_consensus` receipt, the "ValuCast Rank", the consensus, AND the "spots
ahead" number on the HTML card must be numerically identical to what the share
PNG stamps. If you find a player where the receipt exists but the PNG uses a
different field than `_ahead_of_consensus_for_key` returns, STOP and report —
that means there is a THIRD source and this plan's model of the bug is wrong.

**Verify**: `python -m pytest -q tests/test_ahead_of_curve_card_stamp.py tests/test_card_intelligence.py`
→ all pass, plus 1 new test asserting that for a row WITH an `ahead_of_consensus`
receipt the rendered source-evidence rank equals `receipt["valucast_rank"]`
(render the partial with a stub context, or assert at the context-assembly level
if the existing card-intelligence tests operate there — mirror how the nearest
existing test drives the template).

### Step 4: gap (d) — tag the mobile stat strip with the level of the line it shows

The strip prints `factual_current_context`'s slice with no level, beside a Level
badge that may name the combined level. Give the strip its own level tag sourced
from the SAME field the strip's numbers come from
(`factual_current_context.level`), so the strip and its numbers can never name
different levels.

Pick the smaller-diff option (prefer A):

- **Option A (template-only, preferred)**: in
  `templates/partials/rankings_table_dynasty.html:137-146`, prepend a level chip
  to the strip sourced from the strip's own line. Expose the strip's level via a
  small read-only property on the row (e.g.
  `web/public_snapshot_models.py`: `factual_context_level` →
  `self.factual_current_context.get("level")`) and render it as the first
  `mobile-stat` item (label `Level`, value that level) when present. This keeps
  the strip self-consistent: the level shown IS the level of the OPS/ISO beside it.
- **Option B**: prepend the level inside `stat_items`
  (`web/prospect_context.py:86-112`) as the first item when
  `context.get("level")` is present. Only choose this if the template cannot
  cleanly reach the level; it changes a shared helper, so re-run every caller's
  tests (`grep -rn "stat_items\|factual_context_stat_items" web templates app.py`).

Do NOT try to make the strip show the COMBINED level to match the badge — that
would reintroduce the mislabel (the strip's numbers are the single-level slice).
The honest fix is to label the strip with ITS level; the badge keeps its combined
label. Two labels naming two real, correctly-attributed levels is not a
contradiction — an unlabeled slice masquerading under the badge's level is.

**Verify**: `python -m pytest -q tests/test_public_dynasty_snapshot.py` → all
pass, plus 1 new test: build a `PublicSnapshotRow` whose
`factual_current_context.level == "A"` while `card_level_label` yields a combined
`"A+ & A"`, and assert the strip now surfaces the `"A"` level (via the new
property or the first `stat_items` entry). Willits is the register's live example
(strip level "A", badge "A+").

## Test plan

- `tests/test_prospect_rank_v1.py`: +1 (main-model thin → medium, not high).
- `tests/test_public_dynasty_snapshot.py`: +1 (strip carries its own level) and,
  if a board-level co-occurrence test exists, extend it to assert no row is both
  `confidence == "high"` and carrying a `"Thin sample"` why-rank chip.
- `tests/test_card_intelligence.py` and/or `tests/test_ahead_of_curve_card_stamp.py`:
  +1 (HTML source-evidence rank == receipt `valucast_rank` when a receipt exists).
- `tests/test_recent_form.py` / `tests/test_card_intelligence.py`: run to confirm
  the label rename broke nothing; update any assertion pinning the literal
  `"Form Curve"` string.
- Final: `python -m pytest -q` all green, then
  `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json`.

## Done criteria

- [ ] `python -m pytest -q` exits 0 (byproduct file restored after).
- [ ] `grep -n "band == \"thin\"" prospects/rank_v1.py` → at least 2 hits (pedigree branch + new main-model guard).
- [ ] `grep -n "Form Curve" templates/partials/_value_spark.html` → no hits (ambiguous label removed).
- [ ] `grep -n "ahead_of_consensus" templates/partials/player_detail_dynasty.html` → the source-evidence block now reads the receipt.
- [ ] `grep -n "Level" templates/partials/rankings_table_dynasty.html` → the mobile stat strip emits a level chip (or `factual_context_level` property exists and is rendered).
- [ ] New tests from the test plan exist and pass.
- [ ] `git status --short` shows only this plan's in-scope files modified; the receipts working-tree files are untouched by you; the pytest byproduct is restored.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- Any "Current state" excerpt does not match the live file (drift landed first —
  re-read, reconcile, and if the contradiction was already fixed differently,
  report instead of re-fixing).
- For gap (c): the share PNG's AOTC banner is found to read a rank field OTHER
  than what `_ahead_of_consensus_for_key` returns (a third source exists — the
  bug model is wrong; report before touching the template).
- The `_confidence` callsite (`prospects/rank_v1.py:1989`) no longer passes
  `factual_current_context` — the main-model guard would have no `skill_band` to
  read.
- Editing gap (b) or (d) forces a change to a computation file
  (`web/value_spark.py`, `prospects/recent_form.py`, or the score math) — that is
  out of scope; these are label/tag fixes only. Report if you cannot fix the label
  without touching a model.

## Maintenance notes

- The unifying invariant to preserve going forward: **a confidence word and a
  sample-quality chip on the same row both derive from `factual_current_context`;
  an AOTC rank on any surface derives from `_ahead_of_consensus_for_key`; a level
  label sits with the numbers it describes.** New surfaces should read these same
  functions/artifacts, never recompute a parallel number.
- Gap (b) note for a future reader: "Form Curve" and "Recent form" are genuinely
  different signals (model-value delta vs on-field-stat momentum). If they are
  ever merged into one panel, keep BOTH meanings visible — do not collapse them
  into a single "form" number, which would hide the model-vs-field distinction the
  rename preserves.
- Gap (c) note: this plan reconciles DISPLAY only. If a future change wants the
  card and PNG to agree by making the FEED rank canonical instead of the artifact
  rank, that is a computation decision that must respect the AOTC freeze (do not
  change it before the ~7/13 gate unlock).
- Reviewer scrutiny: confirm Step 3 leaves the no-receipt fallback path visually
  identical to today (only receipt-bearing players change), and that Step 1's
  `"medium"` (not `"low"`) choice is intentional and documented in the code
  comment.
