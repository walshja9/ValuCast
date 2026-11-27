# Plan 014: Methodology page honesty polish — interpret the win-rate, band the MAE headlines, surface the losing Steamer forward test

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat ac20b1f2..HEAD -- templates/methodology.html app.py data/validation/methodology_scorecard.json data/models/valucast_mlb_projection_source_comparison.json tests/test_methodology_validation.py`
> If any in-scope file changed since this plan was written, re-read the cited
> line ranges in the live file and compare against the "Current state" excerpts
> below BEFORE editing; on a mismatch, treat it as a STOP condition. Also note:
> the working tree may have UNCOMMITTED receipts work in flight
> (`prospects/call_up_receipts.py`, `tests/test_call_up_receipts.py`,
> `templates/receipts.html`) — that is a DIFFERENT surface; it does not touch
> your files, but confirm `git status` shows your in-scope files clean before
> you start, and re-verify every excerpt against HEAD at execution time.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW (display/copy + one advisory artifact load; NO scoring, NO model, NO builder changes)
- **Depends on**: none. Touches `templates/methodology.html` + the `methodology()` route in `app.py` + its test file — no overlap with plans 004–008.
- **Category**: honesty / copy (epistemic under-contextualization)
- **Planned at**: commit `ac20b1f2`, 2026-07-09

## Why this matters

The /methodology page is the surface where ValuCast's "we say so rather than borrow
credibility" brand lives. The 7/9 claims-register audit flagged three HIGH-severity
epistemic gaps — all under-contextualization, not fabrication. Each has a concrete
public-failure scenario the fix must prevent:

- **(a) The 0.519 win-rate reads as a passing grade to a lay reader and as a buried
  near-tie to an expert.** Embarrassment scenario (register, verbatim): *"A sharp
  reader recognizes 0.519 as a coin flip. The MAE headline says ValuCast beats Marcel;
  the win-rate says its season-to-season ORDERING beats Marcel's ordering only 51.9% of
  the time — statistically indistinguishable from a tie. They screenshot both numbers
  side by side: 'Their own scorecard says the model out-ranks the baseline 51.9% of the
  time. That is a coin flip. The 0.979 headline is carried entirely by shrinking error
  on 4 correlated rate stats, not by actually ordering players better.' The page prints
  the damning number but never reconciles it with the positive headline, so it looks
  like burying rather than disclosing."* The fix: add one interpretation clause per
  win-rate (hitting 0.519 AND pitching 0.694) — ordering is essentially even; the edge
  is error magnitude on rate stats, not re-ordering players.

- **(b) The headline MAE ratios are point estimates with no sample-noise context.**
  Embarrassment scenario (register, verbatim): *"A reader notes there is no confidence
  interval or year-by-year stability shown, so a 0.807 that could be one or two lucky
  ERA seasons reads identically to a robust structural edge. 'They report 19% better ERA
  prediction to three sig figs across 2020-2025 with no per-season breakdown — 2020 was
  60 games and they pro-rate it. How much of this is the COVID season?' The point
  estimate is presented as if it had no sampling uncertainty."* The fix: put the sample
  size `n=` on the two aggregate ledger rows (it currently rides only the win-rate
  bullets in a different drawer) and add a plain-language noise caveat that the pitching
  edge concentrates in the highest-variance stats (ERA/BB_9) and includes the 60-game
  2020 season.

- **(c) The page says the Steamer benchmark is "pending" while a live forward test is
  quietly LOSING.** Embarrassment scenario (register, verbatim): *"There IS a live
  forward test vs Steamer running right now ... model_score 1.2118,
  marcel_beats_steamer=false, i.e. ValuCast's rate-stat MAE is ~21% WORSE than Steamer
  on forward actuals, gate status 'insufficient_sample'. A reader who finds
  /aotc-scorecard.json or the comparison artifact catches the gap: the methodology page
  implies the Steamer comparison simply hasn't been run ('benchmark pending'), when in
  fact the one forward comparison being run currently LOSES to Steamer by 21%. They post:
  'They say beating Steamer is untested. Their own committed artifact has them 1.21x
  Steamer's error and hides it behind insufficient-sample.'"* The fix: state the live
  forward result and its caveat directly on the page. The page must NOT imply forward
  superiority anywhere — it currently doesn't claim superiority, but "benchmark pending"
  misleads by omission when a losing comparison is committed and public.

All three fixes are display/copy only. No scoring, no model, no builder, no artifact
regeneration.

## Current state

Verified against the live files at `ac20b1f2`, 2026-07-09.

### `templates/methodology.html`

- **:10** — `<p class="methodology-version">As of June 2026{% if scorecard %} · {{ scorecard.version }}{% endif %}</p>` (register's low-severity date gap is OUT of scope for this plan — see Scope).
- **:24** — `<tr><td>Steamer board</td><td>External comparison board; matching historical benchmark pending</td></tr>` (the "At a glance" provenance table).
- **:186-192** — the two win-rate `<li>` bullets in the "Validation details" `<details>`. Each ALREADY carries `n =`:
  ```html
  <li><strong>Hitting</strong> vs classic Marcel, n = {{ scorecard.hitting.sample_size }} qualified hitter-seasons,
      correlation-win rate {{ scorecard.hitting.correlation_win_rate }}.
      {{ scorecard.hitting.eligibility }}.</li>
  <li><strong>Pitching</strong> vs persistence (last-year carry-forward),
      n = {{ scorecard.pitching.sample_size }} qualified pitcher-seasons,
      skill correlation-win rate {{ scorecard.pitching.correlation_win_rate }}.
      {{ scorecard.pitching.eligibility }}.</li>
  ```
  These render `0.519` and `0.694` FLAT (no interpretation) — gap (a) lands here.
- **:222-235** — the held-out ledger table. The two aggregate rows (the visually dominant
  headline numbers) carry NO `n=` and NO noise band:
  ```html
  <tr>
      <td>Pitching vs persistence (skill)</td>
      <td><strong>{{ scorecard.pitching.aggregate_mae_ratio }}</strong> MAE ratio
          ({% if scorecard.pitching.aggregate_mae_ratio < 1.0 %}~{{ pct(scorecard.pitching.aggregate_mae_ratio) }}% lower error{% else %}~{{ -pct(scorecard.pitching.aggregate_mae_ratio) }}% HIGHER error — no current edge{% endif %}) —
          IP and K roughly <strong>neutral</strong>; the signal is concentrated in ERA / WHIP / K-9 / BB-9.</td>
  </tr>
  <tr>
      <td>Hitting vs classic Marcel</td>
      <td><strong>{{ scorecard.hitting.aggregate_mae_ratio }}</strong> aggregate MAE ratio
          ({% if ... %}...{% endif %}) — signal
          concentrated in <strong>AVG/OBP/SLG/OPS</strong>.</td>
  </tr>
  ```
  gap (b) lands here. Note the ledger already AUTO-INVERTS its language ("HIGHER error — no
  current edge") when a ratio crosses 1.0 — do NOT disturb that conditional; only append.
- **:317-324** — the "What we have and haven't proven" honesty section:
  ```html
  <p>Our validation is against internal baselines (persistence and classic Marcel),
  which it beats on held-out data. ValuCast has <strong>not yet proven</strong> it
  beats Steamer or ZiPS: we lack matching archived preseason projections for a fair,
  apples-to-apples historical backtest. So Steamer is an <strong>external comparison
  board, with a matching historical benchmark pending</strong> — not a benchmark we've
  beaten.</p>
  ```
  gap (c) lands here. This paragraph is honest for the HISTORICAL backtest but silent on
  the live forward comparison.

### `app.py` — the `methodology()` route (`:4567-4616`)

```python
@app.route("/methodology")
def methodology():
    import json as _json
    ...
    try:
        scorecard = _json.loads(
            (Path(__file__).parent / "data" / "validation" / "methodology_scorecard.json")
            .read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        scorecard = None
    try:
        sensitivity = _json.loads(
            (Path(__file__).parent / "data" / "validation" / "sensitivity_scorecard.json")
            .read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        sensitivity = None
    ...
    return render_template(
        "methodology.html", methodology_page=True, scorecard=scorecard,
        sensitivity=sensitivity,
        hit_weights=..., hit_n_reg=..., pit_n_reg=..., worked=worked,
        pct=lambda r: round((1 - r) * 100, 1),
    )
```

The route loads `scorecard` and `sensitivity` inside `try/except` that degrade to `None`
on a missing/corrupt artifact (a deliberate 7/2 hardening so a bad refresh never 500s the
page). It does NOT load the forward-gate comparison artifact — gap (c) needs it.

### `data/validation/methodology_scorecard.json` (verified values)

- `hitting.aggregate_mae_ratio` = `0.979`, `hitting.correlation_win_rate` = `0.519`,
  `hitting.sample_size` = `1770`, `hitting.seasons` = `[2020..2025]`.
- `pitching.aggregate_mae_ratio` = `0.807`, `pitching.correlation_win_rate` = `0.694`,
  `pitching.sample_size` = `2234`, `pitching.seasons` = `[2020..2025]`,
  `pitching.per_stat_mae_ratio.ERA` = `0.632`, `.BB_9` = `0.715`.

### `data/models/valucast_mlb_projection_source_comparison.json` (verified values — the forward gate)

- `gate.model_score` = `1.2118`, `gate.baseline_score` = `1.0`,
  `gate.status` = `"insufficient_sample"`,
  `gate.reason` = `"forward horizon 21d < required 30d"`,
  `gate.metric` = `"rate_stat_mae_ratio_vs_forward_actuals"`,
  `gate.validated_through` = `"2026-07-09"`.
- `marcel_beats_steamer` = `false` (top-level).
- `comparison_basis.horizon_days` = `21`, `.min_horizon_days` = `30`, `.min_sample` = `50`,
  `.horizon_sufficient` = `false`.
- `live_source_flip.automatic` = `false` (this comparison never flips the live source —
  it is advisory-only and default-off).
- The `1.2118` ratio = ValuCast rate-stat MAE ÷ Steamer's = ~21% HIGHER error. `pct(1.2118)`
  would render a NEGATIVE "lower error" number — do NOT reuse the `pct()` lambda for this;
  see Step 3 for how to phrase it honestly ("~21% higher error", i.e. `round((r-1)*100)`).

### `tests/test_methodology_validation.py` — the guard test (do not break)

`test_honesty_reframe` (`:52-58`) asserts the page still contains `"not yet proven"`,
`"benchmark pending"`, `"available as an opt-in"`, `"will not become the default"`, and
does NOT contain `"external benchmark"`. Your edits must keep all five true — you are
ADDING a clause about the live forward result NEXT TO "benchmark pending", not replacing
those phrases. `test_no_internal_corr_leak` (`:61-62`) asserts `"0.87"` never appears —
none of your added copy uses that string. `test_renders_artifact_aggregate_numbers`
(`:20-25`) pins the aggregate ratios and sample sizes to the artifact — your changes keep
those template expressions intact.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Methodology tests | `python -m pytest -q tests/test_methodology_validation.py` | all pass (baseline: all green pre-change) |
| Render smoke | `python -c "import sys; sys.path.insert(0,'src'); from app import app; c=app.test_client(); r=c.get('/methodology'); print(r.status_code)"` | prints `200` |
| Full suite (final gate) | `python -m pytest -q` | all pass (~1771+ passed, 0 failed); then restore the byproduct file (next row) |
| Restore pytest byproduct | `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json` | pytest dirties this file every run — NEVER commit it |

Note the app entrypoint is under `src/` (`sys.path.insert(0, "src")` in the test file).
If the smoke command errors on import, check how `tests/test_methodology_validation.py`
imports `app` (`:6-7`) and mirror that path.

## Scope

**In scope** (the only files you may modify):
- `templates/methodology.html` — copy edits at the three gap sites + one new render block for the forward gate.
- `app.py` — the `methodology()` route (`:4567-4616`) ONLY: load the comparison artifact into a `forward_gate` context var, same try/except-degrade pattern as `scorecard`.
- `tests/test_methodology_validation.py` — extend with assertions for the three new copy elements.

**Out of scope** (do NOT touch):
- `scripts/build_ahead_of_consensus_scorecard.py`, `prospects/ahead_of_consensus.py` — the AOTC scorecard scoring rules are FROZEN (pre-registered 7/2) until the ~7/13 gate unlock. You are not near them, but confirm you never edit them.
- `scripts/build_validation_scorecard.py` and any builder — NO artifact regeneration; you render committed values only.
- `data/validation/methodology_scorecard.json` and `data/models/valucast_mlb_projection_source_comparison.json` — READ ONLY. Do not edit or regenerate. If a number looks wrong, that's a STOP condition, not a fix.
- The `as_of "2026-06"` vs `generated_at "2026-07-09"` date mismatch (register low-severity gap on this same surface) — a different theme; leave `methodology.html:10` alone.
- The two MEDIUM register gaps on this surface (headline "beats Marcel" rate-stat scoping in the intro paragraph; opt-in BOARD caption honesty in `_source_caption.html`) — see Excluded, below.
- The receipts work in flight (`prospects/call_up_receipts.py` et al.) — different surface.

## Git workflow

- Work directly on `master` locally, but **do NOT push**. `master` auto-deploys valucast.app via Render; the reviewer gates the push.
- NEVER `git add -A` or `commit -am` (repo guardrail — parallel sessions leave untracked files). Stage each file explicitly: `git add templates/methodology.html app.py tests/test_methodology_validation.py`.
- Commit message style (short imperative subject), e.g.: `Interpret win-rate, band MAE headlines, surface live Steamer forward loss on /methodology`.

## Steps

### Step 1: Interpret both correlation-win rates (gap a)

In `templates/methodology.html`, in the two win-rate `<li>` bullets (`:186-192`), append
one interpretation clause AFTER each `correlation-win rate ...` value, BEFORE the
`eligibility` text. Keep the `{{ scorecard.hitting.correlation_win_rate }}` /
`{{ scorecard.pitching.correlation_win_rate }}` expressions verbatim (they are drift-locked
to the artifact — do not hardcode 0.519/0.694). Add plain-English interpretation, e.g.:

- Hitting: after the win-rate, add `— essentially even on ranking; the edge is in error magnitude on rate stats, not in re-ordering players.`
- Pitching: after the win-rate, add `— a modest ranking edge; most of the improvement is smaller error on the rate stats below, not re-ordering pitchers.`

Phrase it as static prose (no new conditional); the register only needs the flat number
reconciled with the headline. The exact wording is yours as long as it (1) tells a lay
reader 0.519 is a near-tie on ORDERING and (2) points the real edge at rate-stat error
magnitude.

**Verify**: `python -m pytest -q tests/test_methodology_validation.py` → all pass. Then
`python -c "import sys; sys.path.insert(0,'src'); from app import app; print('even on ranking' in app.test_client().get('/methodology').data.decode())"` → `True` (adjust the search string to whatever phrase you used; you will pin it in Step 4).

### Step 2: Put n= and a noise caveat on the two aggregate MAE headline rows (gap b)

In the held-out ledger table (`:222-235`), on EACH of the two aggregate rows, do two things
WITHOUT disturbing the existing `< 1.0 ? lower : HIGHER-no-edge` conditional:

1. Add the sample size inline next to the ratio, reusing the artifact expressions already
   proven present: `n = {{ scorecard.pitching.sample_size }} pitcher-seasons` (2234) and
   `n = {{ scorecard.hitting.sample_size }} hitter-seasons` (1770). Do NOT hardcode the
   numbers — use the `{{ scorecard.* }}` expressions so they stay drift-locked.
2. Append a plain-language noise caveat. For the PITCHING row specifically, name the
   variance concentration and the 2020 short season, e.g.:
   `The pitching gain concentrates in ERA and BB-9 — the noisiest, most luck-driven stats — and the hold-out includes the 60-game 2020 season, so read the point estimate as directional, not precise.`
   For the HITTING row, a lighter caveat suffices, e.g.:
   `Aggregate over {{ scorecard.hitting.sample_size }} seasons; the win comes from four correlated rate stats, so it is a narrow edge, not an across-the-board one.`

Keep both caveats as static prose appended inside the existing `<td>`. Do not add a real
confidence interval or bootstrap (that would need a builder change — out of scope); a
plain-language noise disclosure is the mandated fix.

**Verify**: `python -m pytest -q tests/test_methodology_validation.py` → all pass
(`test_renders_artifact_aggregate_numbers` must still find both ratios AND both sample
sizes — the sample sizes now also appear on the ledger rows, which is fine). Render smoke
prints `200`.

### Step 3: Surface the live Steamer forward loss (gap c)

Two parts — a route change and a template change.

**3a. Load the forward-gate artifact in the route.** In `app.py`, inside `methodology()`
(after the `sensitivity` load block, `:4590`), add a THIRD try/except that mirrors the
existing pattern exactly:
```python
    try:
        forward_gate = _json.loads(
            (Path(__file__).parent / "data" / "models" / "valucast_mlb_projection_source_comparison.json")
            .read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        forward_gate = None
```
and pass `forward_gate=forward_gate` in the `render_template(...)` call. Degrade-to-`None`
on a missing/corrupt artifact is REQUIRED (the page must never 500 — same 7/2 posture as
`scorecard`). Do not import anything new; `_json` and `Path` are already in scope.

**3b. Render it honestly in the "What we have and haven't proven" section.** In
`templates/methodology.html` (`:317-324`), immediately AFTER the existing "benchmark
pending" paragraph, add a guarded paragraph that states the live forward result. Compute
the "higher error" percent from the ratio WITHOUT the `pct()` lambda (that lambda returns
`(1-r)*100`, which goes negative above 1.0 — wrong sign for a losing ratio). Use Jinja
arithmetic on the artifact value instead:
```html
{% if forward_gate and forward_gate.gate %}
<p><strong>A live forward check is running — and currently losing.</strong> We also run a
day-by-day forward comparison of ValuCast H+P against the Steamer board on this season's
actuals. As of {{ forward_gate.gate.validated_through }}, ValuCast's rate-stat error is
about {{ ((forward_gate.gate.model_score - 1) * 100) | round | int }}% <em>higher</em> than
Steamer's ({{ forward_gate.gate.model_score }}× its error) over a
{{ forward_gate.comparison_basis.horizon_days }}-day window — but the sample is still below
our {{ forward_gate.comparison_basis.min_horizon_days }}-day gate, so it is
<strong>not yet decisive</strong> and does not flip the live board. We publish it here
rather than wait for it to look better.</p>
{% endif %}
```
Adjust field paths only if the drift check showed the artifact shape changed. The `{% if %}`
guard is mandatory so a missing artifact renders NOTHING (never a stack trace, never a
half-sentence). This paragraph must NOT claim or imply forward superiority anywhere — it
states a loss with its caveat. The existing "benchmark pending" phrasing at `:24` and
`:317-324` STAYS (the historical backtest genuinely is pending; the guard test depends on
those words) — you are adding the forward result alongside it, not replacing it.

**Verify**: `python -m pytest -q tests/test_methodology_validation.py` → all pass
(`test_honesty_reframe` still finds "not yet proven" and "benchmark pending", still does not
find "external benchmark"). Render smoke:
`python -c "import sys; sys.path.insert(0,'src'); from app import app; h=app.test_client().get('/methodology').data.decode(); print('higher' in h and 'not yet decisive' in h)"` → `True`.
Confirm the rendered percent reads as a POSITIVE ~21 (not negative): grep the rendered HTML
for `21%` — `python -c "import sys; sys.path.insert(0,'src'); from app import app; print('21%' in app.test_client().get('/methodology').data.decode())"` → `True`.

### Step 4: Pin the three new copy elements in the test

Extend `tests/test_methodology_validation.py` with ONE new test method (add it to
`TestMethodologyValidation`) that asserts all three fixes are present, so a future refactor
can't silently drop them:
```python
def test_honesty_polish_present(self):
    flat = " ".join(self.html.split())
    # gap (a): win-rate interpreted, not flat
    self.assertIn("even on ranking", flat)          # or your exact hitting clause
    # gap (b): sample size on the aggregate ledger rows + noise caveat
    self.assertIn(str(self.art["hitting"]["sample_size"]), self.html)
    self.assertIn(str(self.art["pitching"]["sample_size"]), self.html)
    self.assertIn("2020", flat)                      # the 60-game season caveat
    # gap (c): live forward loss surfaced, positive "higher" framing, still not decisive
    low = flat.lower()
    self.assertIn("higher", low)
    self.assertIn("not yet decisive", low)
    self.assertNotIn("-21%", self.html)              # sign must be positive
```
Match the literal strings to the exact wording you shipped in Steps 1–3. Do NOT weaken any
existing assertion.

**Verify**: `python -m pytest -q tests/test_methodology_validation.py` → all pass including
the new method.

### Step 5: Full-suite gate and cleanup

Run the full suite, confirm zero failures, and restore the pytest byproduct file.

**Verify**:
- `python -m pytest -q` → all pass (~1771+ passed, 0 failed).
- `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json`
- `git status` → only `templates/methodology.html`, `app.py`, `tests/test_methodology_validation.py` modified; the byproduct file restored; no other file dirtied.

## Test plan

- `tests/test_methodology_validation.py`: +1 new method (`test_honesty_polish_present`)
  pinning the win-rate interpretation clause, the ledger-row sample sizes + 2020 caveat, and
  the forward-loss paragraph with positive-sign framing.
- All existing methodology tests must stay green — especially `test_honesty_reframe`
  (the five phrase assertions) and `test_renders_artifact_aggregate_numbers` (ratio/sample
  drift-lock).
- Render smoke (`/methodology` → 200) after each step, since the whole change is template + one route var.
- Final: `python -m pytest -q` all green, then restore the archive byproduct file.

## Done criteria (grep-checkable)

- [ ] `python -m pytest -q` exits 0; the pytest byproduct file is restored afterward.
- [ ] `grep -n "even on ranking\|not in .* re-ordering\|coin flip\|essentially even" templates/methodology.html` → at least the hitting win-rate interpretation clause present (match your wording).
- [ ] `grep -n "sample_size" templates/methodology.html` → both `scorecard.hitting.sample_size` and `scorecard.pitching.sample_size` now appear on the ledger rows (Step 2), in addition to the win-rate bullets.
- [ ] `grep -n "2020" templates/methodology.html` → the pitching noise caveat names the 60-game season.
- [ ] `grep -n "forward_gate" app.py` → the route loads the comparison artifact and passes it to `render_template`.
- [ ] `grep -n "forward_gate" templates/methodology.html` → the guarded forward-loss paragraph exists.
- [ ] `grep -n "not yet decisive\|currently losing\|higher" templates/methodology.html` → the honest forward-loss framing present.
- [ ] `python -c "import sys; sys.path.insert(0,'src'); from app import app; h=app.test_client().get('/methodology').data.decode(); print('benchmark pending' in h and 'not yet proven' in h and 'external benchmark' not in h)"` → `True` (guard test invariants preserved).
- [ ] `python -c "import sys; sys.path.insert(0,'src'); from app import app; print('21%' in app.test_client().get('/methodology').data.decode())"` → `True` (positive-sign forward-loss percent).
- [ ] `git status`: only the three in-scope files modified.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- Any in-scope file changed since `ac20b1f2` in a way that makes the "Current state"
  excerpts no longer match — re-read, reconcile, and if a fix already landed, report
  instead of duplicating it.
- `data/models/valucast_mlb_projection_source_comparison.json` no longer has
  `gate.model_score` / `gate.validated_through` / `comparison_basis.horizon_days`, OR its
  `gate.status` has flipped to something other than `insufficient_sample` with
  `marcel_beats_steamer` now `true` (the forward test has changed verdict) — STOP and report;
  the "currently losing" copy would become wrong and the wording needs the reviewer's call.
- `pct()` or the ledger's `< 1.0` auto-invert conditional would need changing to make a
  fix work — it should not; if it does, you have drifted from the plan, STOP.
- `test_honesty_reframe` or `test_renders_artifact_aggregate_numbers` goes red — your copy
  edit broke a drift-lock; fix the copy, do not weaken the test.
- Any temptation to edit a builder, an artifact JSON, or an AOTC scoring file — STOP; this
  plan is display/copy only.

## Maintenance notes

- The forward-gate paragraph is drift-locked to the live artifact by construction (it
  renders `gate.model_score` / `validated_through` directly). When the 30-day horizon
  matures and `gate.status` flips to a decided verdict, the copy "still below our N-day gate,
  so it is not yet decisive" auto-stales — a follow-up should revisit the wording then
  (and if `marcel_beats_steamer` ever flips `true`, the "currently losing" framing must
  change). That is a future edit, not this plan's.
- The register also flagged two MEDIUM gaps on this same surface (headline "beats Marcel"
  rate-stat scoping in the intro paragraph at `:216-234`; opt-in BOARD caption honesty in
  `templates/partials/_source_caption.html`) and a LOW date-mismatch gap. They are
  intentionally out of this P2/S plan — see Excluded in the handoff.
- Reviewer scrutiny: confirm the added forward percent renders as POSITIVE ~21 (the `pct()`
  lambda would have made it negative — the plan deliberately uses `(model_score - 1) * 100`
  instead). Confirm no scoring/model/builder file appears in the diff.
