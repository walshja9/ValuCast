# Plan 003: Stop embedding unused DD rank/value in the public snapshot, and tighten the external-board label

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat c8d8a22..HEAD -- scripts/build_public_dynasty_snapshot.py templates/partials/player_detail_dynasty.html web/public_snapshot_models.py tests/test_public_dynasty_snapshot.py`
> On a mismatch with the "Current state" excerpts, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (cleaner after 001's validators exist, but independent)
- **Category**: tech-debt / provenance
- **Planned at**: commit `c8d8a22`, 2026-06-17

## Why this matters

The public dynasty snapshot — the artifact ValuCast points to as "ValuCast-owned"
and which is committed to the repo — physically embeds DD rank and value on every
prospect row (`dd_dynasty_rank`, `dd_dynasty_value`, `dd_prospect_rank`,
`has_dd_context: true`) even though **no template renders these keys** (verified:
a repo-wide template grep finds zero references). They are dead payload that
weakens the provenance story for anyone who inspects the public file. Removing
them makes the public artifact honestly DD-free without touching any visible
surface.

The visible external-board comparison panel (CFR/HKB/Pipeline) is kept — it is
intentional, labeled comparison-only context that helps the independence story
("ValuCast disagrees with consensus here, on purpose"). This plan only tightens
its label to the agreed wording and confirms it never appears on share graphics.

## Current state

- `scripts/build_public_dynasty_snapshot.py:412-430` — the per-row public `context`:
  ```python
  "context": {
      "kind": "optional_display_context",
      "usage": "display_only_not_used_for_valucast_score",
      "valucast_rank_v1": row.get("rank"),
      "dd_dynasty_rank": context.get("dd_dynasty_rank"),     # unused by any template
      "dd_dynasty_value": context.get("dd_dynasty_value"),   # unused
      "dd_prospect_rank": context.get("dd_prospect_rank"),   # unused
      "source_ranks": context.get("source_ranks"),           # KEEP — feeds the external-board panel
      "value_history_points": context.get("value_history_points"),
      "stat_line_source": context.get("stat_line_source"),
      ... (stat_line_* context fields) ...
      "graduation_context": context.get("graduation_context"),
      "has_dd_context": context.get("has_dd_context", False),  # unused by any template
  },
  ```
  `source_ranks` IS consumed: `web/public_snapshot_models.py:103-122` derives
  `public_source_ranks` from it, rendered by the external-board panel. Keep it.

- `templates/partials/player_detail_dynasty.html:395-404` — the panel and its label:
  ```html
  {% if row.source_ranks %}
  <details class="detail-section source-evidence market-context-details">
      <summary><span>External board context</span> ...</summary>
      <p class="market-context-note">
          Comparison-only context. These boards never feed ValuCast rank or value.
      </p>
  ```
  It is a `<details>` (collapsed by default) — good.

- The share PNG card (`app.py` `_prospect_player_card_png` / `_graphic_*`) renders
  ValuCast value + P#rank only (no external/source ranks) — confirm this remains
  true in Step 2.

## Commands you will need

| Purpose | Command (run from repo root) | Expected |
|---------|------------------------------|----------|
| Grep consumers of a key | `grep -rn "dd_dynasty_rank\|dd_dynasty_value\|dd_prospect_rank\|has_dd_context\|value_history_points" --include=*.py --include=*.html --include=*.js .` | only build + rank_v1 + (possibly) value_history_points producers; NO render consumers |
| Snapshot tests | `python -m pytest -q tests/test_public_dynasty_snapshot.py` | all pass |
| Snapshot validator | `python scripts/validate_public_dynasty_snapshot.py` | exit 0 |
| Detail-render test | `python -m pytest -q tests/test_app.py` | all pass |
| Lint | `ruff check <changed files>` | exit 0 |

## Scope

**In scope**:
- `scripts/build_public_dynasty_snapshot.py` (Step 1 — drop the unused DD keys from the public `context`)
- `templates/partials/player_detail_dynasty.html` (Step 2 — label only)
- `tests/test_public_dynasty_snapshot.py` (assert the dropped keys are absent)

**Out of scope**:
- `prospects/rank_v1.py` — its internal `_context` may keep computing these for its
  own provenance/comparison; this plan only cleans the PUBLIC snapshot artifact.
- `source_ranks` and `public_source_ranks` — kept (the panel needs them).
- Any score/value field. Removing display context must not change a single value.

## Steps

### Step 1: Confirm no consumer, then drop the unused DD keys from the public context

Run the consumer grep (table above) for each of `dd_dynasty_rank`,
`dd_dynasty_value`, `dd_prospect_rank`, `has_dd_context`. For any key with **zero**
render/validator/model consumers (only the builder and rank_v1 producer appear),
remove it from the `context` dict at `build_public_dynasty_snapshot.py:412-430`.

`value_history_points`: grep it too. If nothing consumes it, drop it as well; if
something does, keep it. (Templates don't reference it; confirm no JS does.)

Do NOT remove `source_ranks`, `valucast_rank_v1`, `stat_line_*`, `graduation_context`,
`kind`, or `usage`.

Check the snapshot validator: `web/public_snapshot_store.py` `REQUIRED_CONTEXT_FIELDS`
is `("stat_line_source",)` and `PROSPECT_VALUCAST_STAT_CONTEXT_FIELDS` does not
include any `dd_*` key, so dropping them does not violate required-field validation —
confirm by running the validator in the Verify step.

**Verify**: `python scripts/validate_public_dynasty_snapshot.py` → exit 0 (regen
the snapshot first if the validator reads the on-disk file:
`python scripts/build_public_dynasty_snapshot.py` then validate). Add/extend a test
in `tests/test_public_dynasty_snapshot.py` asserting a built prospect row's
`context` does NOT contain `dd_dynasty_rank`/`dd_dynasty_value`/`dd_prospect_rank`/
`has_dd_context`, and DOES still contain `source_ranks`. `python -m pytest -q
tests/test_public_dynasty_snapshot.py` → all pass.

### Step 2: Tighten the external-board label; confirm it's not on share graphics

In `templates/partials/player_detail_dynasty.html`, set the panel label to the
agreed wording — summary "External board context", note
"External board context — not used in ValuCast score." (replace the current
"Comparison-only context. These boards never feed ValuCast rank or value." line,
or keep both sentences if clearer; the required phrase "not used in ValuCast score"
must appear). Leave it collapsed (`<details>`), keep the CFR/HKB/Pipeline rows
under the existing display-only fields.

Confirm the share PNG does not render source/external ranks:
`grep -n "source_ranks\|public_source\|external" app.py | grep -i png` and inspect
`_prospect_player_card_png`/`_graphic_*`. If they already exclude it (expected),
no change. If any external rank leaks onto a share graphic, STOP and report.

**Verify**: `python -m pytest -q tests/test_app.py` → all pass.

### Step 3: Full gate

**Verify**: `python -m pytest -q` → all pass. `ruff check` on changed files → exit 0.

## Test plan

- `tests/test_public_dynasty_snapshot.py`: built prospect row `context` excludes the
  four DD keys (and `value_history_points` if dropped) and still includes
  `source_ranks`. Model on the existing context-field assertions in that file.
- `tests/test_app.py`: the detail render still shows the external-board panel when
  `source_ranks` is present (unchanged behavior) with the new label.

## Done criteria

ALL must hold:
- [ ] The consumer grep confirms zero render/validator/model consumers for each dropped key.
- [ ] Built prospect-row `context` no longer contains `dd_dynasty_rank`/`dd_dynasty_value`/`dd_prospect_rank`/`has_dd_context`.
- [ ] `source_ranks` and the external-board panel still work.
- [ ] Panel note contains "not used in ValuCast score".
- [ ] `python scripts/validate_public_dynasty_snapshot.py` exits 0.
- [ ] `python -m pytest -q` exits 0.
- [ ] `ruff check` clean on changed files; only in-scope files modified.
- [ ] `plans/README.md` status row updated.

## STOP conditions

Stop and report if:
- The consumer grep finds a key IS read by a template/JS/validator/model — keep
  that key and report which consumer uses it.
- Removing a key changes any rendered value or fails the snapshot validator.
- An external/source rank is found rendered on a share graphic (Step 2).
- "Current state" excerpts don't match live code (drift).

## Maintenance notes

- `rank_v1.json` (internal) may still carry these comparison fields; that is
  acceptable — only the PUBLIC snapshot is the independence-claim artifact. A later
  pass can decide whether rank_v1's internal copy is still earning its keep.
- If a future feature wants to show a "ValuCast vs DD rank" delta, re-add the
  specific key it needs (labeled comparison-only) rather than re-embedding all of
  them.
