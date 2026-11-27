# Plan 015: Word-form number guard — catch derived numeric claims spelled as words in the scouting-read fact guard

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> ```
> git diff --stat ac20b1f2..HEAD -- scouting/voice.py tests/test_scouting_v2.py
> ```
> This plan was written against `ac20b1f2`. Two independent drift risks:
> (1) The working tree has UNCOMMITTED receipts work in flight (an at-promotion
> rescoring fix touching `prospects/call_up_receipts.py`, `tests/test_call_up_receipts.py`,
> `templates/receipts.html`) — none of those are in this plan's scope, but run
> `git status` first and re-verify your baseline against HEAD at execution time,
> not against the excerpts blindly.
> (2) If `scouting/voice.py` changed since `ac20b1f2`, re-read the excerpted
> regions (`_NUMBER_RE` at :68-71, `BANNED_PHRASES` at :42-66, `style_problems`
> at :100-109, `validate_report_text` at :379-403) before proceeding; on a
> mismatch with the excerpts below, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug (claims-honesty guard gap)
- **Planned at**: commit `ac20b1f2`, 2026-07-09

## Why this matters

The "ValuCast Read" prose on player cards is LLM-written and guarded, at build
time only, by `scouting/voice.py::validate_report_text`. The number-hallucination
guard (`unsupported_numbers` / `_NUMBER_RE`) cross-checks every **digit** token in
the prose against the supplied grounding — so `.312`, `95`, `182.888` all get
verified. But `_NUMBER_RE` matches **digits only** (`r"\.\d+|\d+(?:\.\d+)?"`), so a
derived numeric claim spelled as a **word** is invisible to it.

The `VOICE_PROMPT` explicitly forbids exactly this class of claim — "no arithmetic
(`8 points above league average`)" (voice.py:18, repeated at :29) — and
`BANNED_PHRASES` already bans the digit-form scaffolds `"against a league average"`
etc. (voice.py:58-59). The word-form of the same derived delta slips through.

**The embarrassment scenario the register describes (quote):**

> "VOICE_PROMPT explicitly forbids arithmetic derivation ('no arithmetic ("8 points
> above league average")', voice.py:18/29) and bans 'against a league average'
> phrasings (voice.py:58-59), but 'more than three points above the big-league
> average' is exactly a derived delta written in words. `_NUMBER_RE` (voice.py:71)
> matches only digits, so 'three' is invisible to the guard, and there is no
> league-average BB baseline number in the hitter grounding for the reader to check
> the subtraction against. A sharp reader who knows MLB walk rate isn't a fixed 9%
> flags the '3 points above' as an unverifiable, model-invented comparison the
> site's own rules prohibit."

This is a live defect in the committed artifact. The Eli Willits read
(`816113_hitter`) contains, verbatim (verified in `data/models/valucast_scouting_reports.json`):

> "...walking at an 18% clip that translates to a 12.0% MLB-equivalent rate, **more
> than three points above the big-league average**, while the 12 home runs and .217
> ISO..."

The `12.0%` and `18%` are grounded (digit guard passes), but "three points above
the big-league average" is a subtraction the model invented against a baseline that
is nowhere in the grounding. The register's `suggested_fix` is precisely this
plan's task: catch spelled-out numeric deltas near "above/below ... average" and
the common comparative multiplier templates (double/triple/half/N-times).

## Current state

All in `scouting/voice.py`, verified at `ac20b1f2`:

- `:68-71` — the digit-only number regex (the root of the gap):
  ```python
  # Leading-dot decimals (".28", ".070") are captured AS decimals (0.28, 0.07) — the
  # alternative is ordered first so a rate written without a leading zero is read at its
  # true value instead of tokenizing ".28" -> 28 (which never matched grounding's 0.28).
  _NUMBER_RE = re.compile(r"\.\d+|\d+(?:\.\d+)?")
  ```
- `:42-66` — `BANNED_PHRASES` (a flat tuple of lowercased substrings; `banned_phrase_hits`
  at :83-85 does a plain `phrase in lowered` scan). It ALREADY bans the digit-form
  scaffolds: `"against a league average"`, `"against the league average"`,
  `"against a league norm"`, `"against a league mean"`, `"against a league-average"`
  (:58-59). Substring matching is fine for fixed strings but cannot express
  `<word> points above` (variable word) — that needs a regex, so this fix is a NEW
  deterministic check, not a `BANNED_PHRASES` addition.
- `:100-109` — `style_problems(text)` is the model for a text-only regex check that
  returns a `list[str]` of human-readable problem strings (no grounding needed). The
  new check follows this exact shape.
- `:379-403` — `validate_report_text` aggregates every check into a result dict and
  computes `ok` and `hard_ok`. `style_problems` feeds `ok` (drives retry/regen) but
  NOT `hard_ok` (a formulaic read is a regen candidate, not a factual hazard). Read
  the comment at :396-402 carefully — it dictates where your new key belongs.
- `unsupported_numbers` (:258-270) and its result key `"unsupported_numbers"` is a
  **soft flag** — surfaced for spot-check, tolerant of rounding, NOT part of `hard_ok`
  (see :381-382 docstring and the `ok`/`hard_ok` composition at :398-402).

**Grounding context**: there is no league-average baseline number in the hitter
grounding (confirmed: the derived "N points above average" comparison has nothing in
`grounding` to check against — that is exactly why it is a hallucination, not a
citation). So the fix is a **text-pattern** guard (like `style_problems`), not a
grounding cross-check.

**Live flag-rate measurement (run by the plan author at `ac20b1f2` with the EXACT
regexes in Step 1; reproduce in Step 3)**: across 716 published reports, the three
templates flag **15 reads = 2.09%**, ALL real derived-delta violations, zero false
positives. Breakdown: the `<word> points/ticks above/below` template (Template A)
carries most hits — Willits "three points above", Valdez "four full points above", De
Vries "couple ticks above", Waldschmidt "two points above", Miller "two points below",
Clifford "eleven points above", + more. The `double/triple/half ... average|norm|
baseline|rate` multiplier template (Template B) catches Brody Hopkins "double the
major-league norm", Frank Mozzicato "double the MLB walk rate", Mike Sirota "double the
8.5% major-league baseline", plus Yoniel Curet "half above where the average" and
Michael Lombardi "half above the MLB average" (all real derived comparisons). **The two
false positives the naive pattern produced are correctly EXCLUDED** by the tightened
regex: Jacob Gonzalez "scrubs half the power" (not a numeric claim) and Enrique
Bradfield Jr. "organizational depth more than half the time" (an idiom). **Design
consequence, verified**: (1) the multiplier template's leading word must be restricted
to `double|triple|quadruple|half` (never a bare digit/number-word, which spikes the
rate to ~25% by matching every "N% ... rate" phrase — the "N times" form is handled by
the separate Template C that requires the literal "times"), and (2) it must anchor on
average/norm/mean/baseline/rate/clip.

Repo conventions: `scouting/voice.py` is pure data + checks, no I/O, no imports beyond
`re`; checks return `list[str]` of problem descriptions; tests are plain `unittest`
in `tests/test_scouting_v2.py` (no fixtures beyond module-level `GROUNDING`).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Voice guard tests | `python -m pytest -q tests/test_scouting_v2.py` | all pass |
| Flag-rate measurement | `python scripts/_wordform_flagrate_probe.py` (you create this as a THROWAWAY in the scratchpad, NOT committed — see Step 3) | prints the flagged count / % and the per-template breakdown |
| Full suite (final gate) | `python -m pytest -q` | all pass; then `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json` (pytest dirties it — NEVER commit it) |

## Scope

**In scope** (the only files you modify):
- `scouting/voice.py` — add the new word-form comparative check + wire it into `validate_report_text`.
- `tests/test_scouting_v2.py` — add tests using the real caught examples.

**Out of scope** (do NOT touch):
- The IP-rounding gap (Skenes "182.888 innings", register high-severity) — that is an
  UPSTREAM grounding fix in `scouting/repository.py::_round_grounding_rates`, a
  different theme/plan. This guard is a text-pattern check; it does not touch
  grounding construction.
- The request-time re-validation / staleness gaps (published_report served without
  re-check; percentile coarsening) — separate plans.
- `unsupported_numbers` / `_NUMBER_RE` / the `/1000` rate collapse — do NOT modify the
  digit guard. Adding word-number parsing INTO `_NUMBER_RE` would risk the digit-token
  invariants (leading-dot ordering, the count-vs-rate collapse). The new check is a
  SEPARATE function, exactly like `style_problems`.
- `BANNED_PHRASES` — do not add regex-shaped entries there; it is a fixed-substring
  list by contract. The new check is its own function.
- `prospects/ahead_of_consensus.py`, `scripts/build_ahead_of_consensus_scorecard.py`
  — the AOTC scorecard rules are FROZEN (pre-registered 7/2) until the ~7/13 gate
  unlock. Not in scope here anyway; noted so you never wander into them.
- Regenerating the scouting artifact. This plan changes the guard, not the prose. Do
  NOT run any scouting build or mass-regeneration (see STOP conditions).

## Git workflow

- Work directly on `master` (repo convention — direct-to-main), but **do NOT push**:
  master auto-deploys valucast.app via Render. Commit locally; the reviewer gates the push.
- NEVER `git add -A` or `commit -am` (repo guardrail — parallel sessions leave
  untracked files, and there is uncommitted receipts work in the tree right now).
  Stage each file explicitly: `git add scouting/voice.py tests/test_scouting_v2.py`.
- Commit message style (short imperative subject), e.g.:
  `Flag word-form derived numeric deltas in scouting-read guard`

## Steps

### Step 0: Confirm the gap is live before you touch anything

Confirm the digit guard misses the Willits word-form claim (proves the gap exists at HEAD):
```
python -c "from scouting.voice import unsupported_numbers; print(unsupported_numbers('translates to a 12.0% MLB-equivalent rate, more than three points above the big-league average', {'card_display_line': {'bb_pct': 18.0}, 'mlb_equivalent_translation': {'bb_pct': 12.0}}))"
```
**Verify**: prints `[]` (no unsupported digit tokens) even though "three points above
the big-league average" is a derived delta. If it already prints a non-empty list
containing a word-form flag, the guard was changed since `ac20b1f2` — STOP and reconcile.

### Step 1: Add the word-form comparative check to `scouting/voice.py`

Add a module-level regex pair and a function next to `style_problems` (mirror its
shape: text-only, returns `list[str]`). Two templates, precision-tuned per the
measured false positives:

```python
# 7/9 claims audit: the digit-only _NUMBER_RE lets a DERIVED numeric delta spelled as
# a WORD pass the fact guard -- e.g. Eli Willits "more than three points above the
# big-league average" (a subtraction the model invented; no league baseline is in the
# grounding to check it against). VOICE_PROMPT forbids exactly this ("no arithmetic")
# and BANNED_PHRASES catches the digit-form scaffold, but not the word-form.
_NUMBER_WORD = (
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"couple|several)"
)
# Template A: "<word|digits> [full] points/percentage points/percent/ticks above|below ..."
# All 10 live hits on this template are real violations -- no exclusion needed.
_WORD_DELTA_RE = re.compile(
    r"\b(?:" + _NUMBER_WORD + r"|\d+)\s+(?:full\s+)?"
    r"(?:points?|percentage\s+points?|percent|ticks?)\s+"
    r"(?:above|below|better|worse|higher|lower|more|fewer)\b",
    re.IGNORECASE,
)
# Template B: multiplier comparative ("double/triple/half the league norm"). The
# leading alternation is ONLY the multiplier WORDS -- NOT bare digits/number-words.
# (Allowing a bare number token there over-fires massively: "20.0% ... rate" and every
# "N% ... walk rate" phrase matches -> ~25% flag rate. Verified.) MUST also anchor on
# an average/norm/mean/baseline/rate/clip word or it fires on non-numeric prose
# ("scrubs half the power", "depth more than half the time").
_MULTIPLIER_DELTA_RE = re.compile(
    r"\b(?:double|triple|quadruple|half)\s+"
    r"(?:the\s+)?"
    r"(?:[\w.%-]+\s+){0,3}?"
    r"(?:average|norm|mean|baseline|rate|clip)\b",
    re.IGNORECASE,
)
# Template C: the "N times the league" comparative (separate from the multiplier words).
_TIMES_DELTA_RE = re.compile(
    r"\b(?:" + _NUMBER_WORD + r"|\d+)\s+times\s+(?:the|as|higher|more|league)\b",
    re.IGNORECASE,
)


def derived_word_number_problems(text: str) -> list[str]:
    """Derived numeric deltas spelled as WORDS, which the digit-only number guard
    (unsupported_numbers) cannot see. VOICE_PROMPT bans arithmetic derivation; this
    catches the word-form the digit scan misses. Soft signal (drives regen), same
    class as unsupported_numbers -- surfaced, not a hard fact-hazard."""
    out: list[str] = []
    t = text or ""
    for match in _WORD_DELTA_RE.finditer(t):
        out.append(f"word-form derived delta '{match.group(0).strip()}'")
    for match in _MULTIPLIER_DELTA_RE.finditer(t):
        out.append(f"word-form multiplier comparison '{match.group(0).strip()}'")
    for match in _TIMES_DELTA_RE.finditer(t):
        out.append(f"word-form 'N times' comparison '{match.group(0).strip()}'")
    return out
```

IMPORTANT precision constraints (VERIFIED by the plan author against the live artifact
at `ac20b1f2` — these exact regexes produce the 15/716 = 2.09% rate with the false
positives excluded and Sirota "double the 8.5% ... baseline" correctly caught; do not
relax them):
- Template B's leading alternation is ONLY `double|triple|quadruple|half`. Do NOT add
  `_NUMBER_WORD` or `\d+` to it — a bare number token there matches "20.0% strikeout
  rate", "12.0% ... walk rate", etc. and blows the flag rate to ~25% (measured). The
  "N times" form is handled separately by Template C, which requires the literal word
  "times" and so cannot match a bare "N% ... rate" phrase.
- Template B's mandatory `(?:average|norm|mean|baseline|rate|clip)` anchor plus the
  restricted leading words is what excludes "half the power" (Jacob Gonzalez) and "half
  the time" (Bradfield). The `{0,3}?` lazy gap (with `%`/`.`/`-` allowed in the gap
  token class) lets a modifier ride between ("the major-league **norm**", "the 8.5%
  major-league **baseline**") while staying short enough not to span a whole clause.
- If, after your regex, the measured flag rate in Step 3 exceeds ~10%, that means the
  patterns are over-firing (or the artifact genuinely leans on this construction) —
  see STOP conditions; do not ship a guard that would force mass regeneration without
  a reviewer decision.

### Step 2: Wire the check into `validate_report_text`

In `validate_report_text` (:379-403), compute the new list and add it to the result
dict. Place it with the **soft** signals — it is the same class as
`unsupported_numbers` (a surfaced flag that drives retry/regen), NOT a hard
fact-hazard like handedness/role_vocab. So:
- Add `derived = derived_word_number_problems(text)` alongside `numbers = unsupported_numbers(...)`.
- Add key `"derived_word_number_problems": derived` to the returned dict.
- Add `and not derived` to the `"ok"` composition (:398-401) so it drives regen.
- Do **NOT** add it to `"hard_ok"` (:402) — mirror how `unsupported_numbers`/`style`
  are excluded from `hard_ok`. Read the comment at :396-397 and match that intent.

**Verify**: `python -m pytest -q tests/test_scouting_v2.py` → all existing tests still
pass (you have not changed any existing behavior; you added a new key + one `ok` term).
If an existing test that asserts `["ok"] is True` now fails, it means that test's
sample text contains a word-form delta — inspect it; if the sample is a legitimately
clean read that your regex wrongly flags, your regex is too broad (fix the regex, not
the test). If the sample genuinely contains a derived delta, update that one assertion
and note it.

### Step 3: Measure the flag-rate change; enforce the STOP threshold

Create a THROWAWAY probe in the scratchpad (do NOT commit it) that runs the new
`derived_word_number_problems` over every published report and prints the rate:
```python
# scratchpad only — measures Theme-6 guard flag rate on the committed artifact
import json
from scouting.voice import derived_word_number_problems
d = json.load(open("data/models/valucast_scouting_reports.json"))
pub = [r for r in d["reports"] if (r.get("published_report") or "").strip()]
flagged = [(r["name"], derived_word_number_problems(r["published_report"]))
           for r in pub if derived_word_number_problems(r["published_report"])]
print(f"published={len(pub)} flagged={len(flagged)} = {100*len(flagged)/len(pub):.2f}%")
for name, probs in flagged:
    print("  ", name, "::", probs)
```
Run it. **Expected at `ac20b1f2`: 15 flagged of 716 = 2.09%**, and the flagged
names should include Willits, Valdez, De Vries, Waldschmidt, Miller, Clifford (Template
A) and Hopkins, Mozzicato, Sirota, Curet, Lombardi (Template B), and should NOT include
Jacob Gonzalez or Enrique Bradfield Jr. (the excluded false positives). If your rate is
~25% instead of ~2%, your Template B leading alternation includes bare digits/number-
words — remove them (only `double|triple|quadruple|half` belong there; "N times" is
Template C).

**STOP threshold**: if the measured rate **exceeds ~10%**, STOP and report to the
reviewer. A >10% rate means either the regex over-fires (false positives to tighten)
or the artifact genuinely leans on this construction so heavily that shipping the
guard implies a mass scouting regeneration — which is a reviewer decision (regen is a
budgeted, artifact-dirtying operation explicitly OUT of this plan's scope), not
something to trigger silently.

**Verify**: rate printed is well under 10% (expected ~2%); false-positive names absent.

### Step 4: Tests using the real caught examples

Extend `tests/test_scouting_v2.py`. Import `derived_word_number_problems` in the
existing `from scouting.voice import (...)` block. Add a test class/method modeled on
`test_style_problems_flag_robotic_tells` (:37-46) and
`test_style_problems_gate_ok_but_not_hard_ok` (:48-53):

1. **Catches the real Willits delta**:
   `assertTrue(derived_word_number_problems("translates to a 12.0% MLB-equivalent rate, more than three points above the big-league average"))`
2. **Catches the multiplier form**:
   `assertTrue(derived_word_number_problems("the MLB-equivalent BB/9 of 6.5 is double the major-league norm"))`
3. **Does NOT flag the measured false positives** (regression pins for the precision anchor):
   - `assertEqual(derived_word_number_problems("translation normally scrubs half the power"), [])`
   - `assertEqual(derived_word_number_problems("lands him as organizational depth more than half the time"), [])`
4. **Does NOT flag clean prose** (a grounded rate cited plainly is fine):
   - `assertEqual(derived_word_number_problems("A .416 OBP at 18 with a 12.0% MLB-equivalent walk rate."), [])`
   (This confirms the multiplier anchor `rate` does not fire on a bare cited rate —
   there is no multiplier word before it. If this assertion fails, Template B's leading
   alternation is matching a bare number token; tighten it so the multiplier/number
   token and the anchor are both required.)
5. **Gate wiring**: a read with a word-form delta gates `ok` False but leaves
   `hard_ok` True (mirror :48-53):
   ```python
   guard = validate_report_text(
       "A clean opener. It runs three points above the big-league average over 240 PA.",
       GROUNDING,
   )
   self.assertTrue(guard["derived_word_number_problems"])
   self.assertFalse(guard["ok"])
   self.assertTrue(guard["hard_ok"])
   ```

**Verify**: `python -m pytest -q tests/test_scouting_v2.py` → all pass, including your
new tests.

### Step 5: Full suite + restore the pytest byproduct

```
python -m pytest -q
git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json
git status
```
**Verify**: full suite green (baseline ~1771+ passed, 0 failed, plus your new tests);
`git status` shows ONLY `scouting/voice.py` and `tests/test_scouting_v2.py` modified
(the receipts work in flight stays untouched; the archive byproduct is restored; the
scratchpad probe is not under the repo).

## Test plan

- `tests/test_scouting_v2.py`: +1 method for the new function (catches both templates,
  excludes both measured false positives, ignores clean prose) and +1 for the gate
  wiring (`ok` False / `hard_ok` True). Real verbatim text from the live artifact
  (Willits, Hopkins, Jacob Gonzalez, Bradfield) so the tests document the exact caught
  and excluded cases.
- Flag-rate is exercised by the Step-3 throwaway probe against the committed artifact
  (not a committed test — the artifact isn't a test fixture and would make the test
  brittle to daily rebuilds).
- Final: `python -m pytest -q` all green, then restore the archive byproduct.

## Done criteria

- [ ] `grep -n "derived_word_number_problems" scouting/voice.py` → function defined AND
      called in `validate_report_text`.
- [ ] `grep -n "derived_word_number_problems" tests/test_scouting_v2.py` → imported and
      asserted (both catch and exclude cases).
- [ ] `grep -n "_NUMBER_RE" scouting/voice.py` → unchanged from the excerpt (the digit
      guard was NOT modified).
- [ ] The Step-3 probe reports a flag rate under 10% (expected ~2%) with the false
      positives (Jacob Gonzalez, Bradfield) absent from the flagged list.
- [ ] `python -m pytest -q` exits 0; the archive byproduct file is restored afterward.
- [ ] `git status` shows only `scouting/voice.py` + `tests/test_scouting_v2.py` staged/
      modified (no receipts files, no scratchpad probe, no artifact).
- [ ] `plans/README.md` status row updated.

## STOP conditions

- **Flag rate > ~10%** in Step 3 — mass regeneration would be implied; that is a
  reviewer decision, not a silent ship. Report the rate and the flagged sample.
- The Step-0 check already flags the word-form claim (the guard was changed since
  `ac20b1f2` — someone landed a word-form fix; reconcile instead of duplicating).
- Any existing `tests/test_scouting_v2.py` test that asserted `["ok"] is True` now
  fails on a read you cannot confirm contains a genuine derived delta — do not silently
  rewrite its meaning; report it (it may mean the regex is too broad).
- The `validate_report_text` `ok`/`hard_ok` composition (:398-402) no longer matches
  the excerpt (a parallel edit landed) — re-read and reconcile.
- You find yourself editing `_NUMBER_RE`, `BANNED_PHRASES`, grounding construction in
  `scouting/repository.py`, or running any scouting build/regeneration — all out of
  scope; stop.

## Maintenance notes

- This guard is intentionally a **text-pattern** check (like `style_problems`), not a
  grounding cross-check, because the derived comparison has NO baseline in the grounding
  to check against — its very unverifiability is the violation. If a future grounding
  ever supplies an explicit league-average baseline number, the honest upgrade is to
  require the word-form claim to carry that grounded figure, not to expand these regexes.
- Precision over recall by design: Template B's mandatory average/norm/mean/baseline/
  rate/clip anchor is load-bearing — it is what keeps "half the power"/"half the time"
  from firing. If a reviewer later wants broader recall, add anchor words consciously
  and re-run the Step-3 probe to re-check the false-positive rate.
- This is a SOFT signal (drives regen via `ok`, not a `hard_ok` block) on purpose — a
  word-form delta is a regen candidate, matching how `unsupported_numbers` is treated.
  Do not promote it to `hard_ok` without a reviewer decision; a false positive that
  hard-blocks would discard an otherwise-good read.
- The flag-rate probe is a throwaway, not a committed test, because the artifact
  rebuilds daily and its exact contents (and thus the exact count) drift; pinning a
  count in a test would make it brittle. Re-run the probe manually if the guard is ever
  broadened.
