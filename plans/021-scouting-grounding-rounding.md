# Plan 021: Scouting grounding rounding — round IP/AB in the MLB stat-line grounding so scout reads stop citing "182.888 innings"

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> ```
> git log -1 --format=%h    # baseline for this plan is 8801cb5c
> git diff --stat 8801cb5c..HEAD -- scouting/mlb_read.py scouting/repository.py tests/test_scouting_v2.py tests/test_scouting_repository.py
> git status --short
> ```
> This plan was written against `8801cb5c`. A parallel session is editing
> `app.py`, `prospects/rank_v1.py`, several templates,
> `prospects/call_up_receipts.py`, and `scripts/validate_valucast_call_up_receipts.py`
> — **none of which this plan touches.** If `scouting/mlb_read.py`,
> `scouting/repository.py`, or `tests/test_scouting_v2.py` changed since
> `8801cb5c`, re-read the excerpted regions below (`_normalized_stat_value`
> mlb_read.py:8-15, `_format_stat` mlb_read.py:49-61, `_round_grounding_rates`
> repository.py:238-255) and confirm they still match before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S (one-to-two rounding constants + a regression test; no regen)
- **Risk**: LOW (rounds two display-only grounding fields to their already-displayed precision; touches no score, rank, value, or artifact schema)
- **Depends on**: none. Sibling to plan 015 (the scouting-read word-form number GUARD): plan 015 explicitly scoped THIS out as "an UPSTREAM grounding fix in scouting/repository.py … a different theme/plan" (015 Scope, "Out of scope" bullet 1). Plan 021 is that upstream fix. The two do not overlap in files beyond `tests/test_scouting_v2.py` (015 adds a `derived_word_number_problems` test class; 021 adds an IP-rounding test) — coordinate only if both land the same day.
- **Category**: bug (false-precision leak into LLM grounding)
- **Planned at**: commit `8801cb5c`, 2026-07-09
- **Execution window**: **anytime.** No frozen-file dependency. (The AOTC scorecard freeze does not touch the scouting pipeline.)

## Why this matters

The "ValuCast Read" prose on player cards is LLM-written from a source-tagged
grounding dict and rendered directly beside the numeric card. Pitcher grounding
carries innings-pitched as a raw model float, so the model echoes it verbatim and
the published read cites innings to three decimal places — a self-evident raw-dump
tell on a site whose entire brand is dated, hand-crafted honesty.

**The embarrassment scenario the register describes (quote, Surface 5 / high):**

> "A prospect-Twitter reader opens Skenes' card: the prose says '182.888 innings'
> while the 2026 Season Outlook grid right below it shows '182.9 IP'
> (templates/partials/player_detail_dynasty.html:9, stat_value renders IP via
> %.1f). No pitcher throws 0.888 of an inning; a thousandth-of-an-inning
> projection is self-evidently a raw model dump the site failed to round. The
> reader screenshots '182.888 innings' as proof ValuCast pipes un-cleaned floats
> into its supposedly-hand-crafted scout voice. 8 published reads carry this
> (Skenes, Misiorowski, C. Sanchez, Kirby, McClanahan, C. Scott, Y. Gomez, plus
> Condon '1.006 OPS')."

The register's `suggested_fix` (quote):

> "Add 'ip' (and any raw count like 'pa'/'ab') to the rounding sweep in
> scouting/repository.py _round_grounding_rates (currently _RATE_ROUND_1DP/
> _RATE_ROUND_WHOLE at lines 241-242 cover only ERA/WHIP/K9/BB9/K%/BB%). Round IP
> to whole or 1dp in the grounding BEFORE the LLM sees it, matching
> mlb_read.py::_format_stat which already displays IP as %.0f/%.1f. The number
> guard cannot catch this because 182.888 literally appears in grounding, so it
> must be fixed upstream at grounding construction."

**Two verified surprises that change where the fix goes (see "Current state"):**
1. All seven IP-dirty reads are **MLB players**, not prospects — their grounding
   flows through the MLB path `stat_line_stats()` (uppercase `IP`), which is
   **NOT** touched by `_round_grounding_rates` (that function operates on the
   PROSPECT card-line's lowercase keys). So the register's exact suggested hook
   would not fix a single one of the live dirty reads. The correct primary hook is
   `scouting/mlb_read.py::_normalized_stat_value` (the sole normalizer for
   `stat_line_stats`), with the `_round_grounding_rates` addition kept as
   defense-in-depth on the prospect path.
2. The "8th" read (Condon `1.006 OPS`) is a **legitimate 3-decimal rate stat**
   (OPS is conventionally `.xyz`/`1.xyz`), NOT an IP/PA/AB precision leak. The real
   dirty-read count for THIS fix is **7**, not 8. Do not "round" OPS.

## Current state

Verified against the live files at `8801cb5c`.

### The leak is in the MLB grounding path, keyed by UPPERCASE stat names

- **`scouting/repository.py:447-465`** — the MLB branch of `_llm_grounding`
  (`row.is_prospect is False`) builds grounding with
  `"stat_line_stats": {"label": …, "source": …, "stats": stat_line_stats(row.stat_line)}`.
  `stat_line_stats` is imported from `scouting.mlb_read` (repository.py:15). This is
  the "MLB stat_line_stats grounding un-rounded" the register cites at
  repository.py:459-463.
- **`scouting/mlb_read.py:26-41` `stat_line_stats`** — returns
  `{UPPER_KEY: _normalized_stat_value(UPPER_KEY, value)}` for every stat. So the
  grounding keys are `IP`, `AB`, `PA`, `ERA`, … (uppercase), NOT the lowercase
  `k_per_9`/`ip` the prospect path uses.
- **`scouting/mlb_read.py:8-15` `_normalized_stat_value`** — the single normalizer.
  Today it whole-rounds only `WHOLE_COUNTING_STATS`:
  ```python
  WHOLE_COUNTING_STATS = {"HR", "SB", "R", "RBI", "W", "QS", "SV", "HLD", "K", "PA"}
  def _normalized_stat_value(key: str, value):
      if not isinstance(value, (int, float)):
          return value
      number = float(value)
      if key in WHOLE_COUNTING_STATS:
          return float(f"{number:.0f}")
      return value
  ```
  Verified live: `stat_line_stats({"stats": {"IP": 182.888, "AB": 550.4, "PA": 620.9}})`
  → `{"IP": 182.888, "AB": 550.4, "PA": 621.0}` — **PA is already whole-rounded**
  (it is in `WHOLE_COUNTING_STATS`), but **`IP` (182.888) and `AB` (550.4) leak
  through unrounded**. This is the exact hole.
- **`scouting/mlb_read.py:49-61` `_format_stat`** — the DISPLAY formatter (used by
  `build_mlb_scouting_read` prose at `:164`/`:186`) already rounds IP correctly:
  `if key == "IP": return f"{value:.0f}" if value.is_integer() else f"{value:.1f}"`.
  So the display path is honest; only the *grounding* dict the LLM reads carries the
  raw float. Rounding IP to 1dp in `_normalized_stat_value` keeps the grounding and
  the display formatter consistent (both land on `182.9`).

### The prospect path (register's suggested hook) — real but NOT where the live dirty reads are

- **`scouting/repository.py:238-255`**:
  ```python
  _RATE_ROUND_1DP = ("k_per_9", "bb_per_9", "era", "whip")
  _RATE_ROUND_WHOLE = ("k_pct", "bb_pct", "k_bb_pct")
  def _round_grounding_rates(line: dict) -> dict:
      rounded = dict(line)
      for key in _RATE_ROUND_1DP: ...   # round to 1dp
      for key in _RATE_ROUND_WHOLE: ...  # round to whole
      return rounded
  ```
  This is applied by `_card_display_line_grounding` (repository.py:266) to the
  PROSPECT card-line, whose keys are lowercase (`ip`, `pa`, `k_per_9`, …). It has
  no `ip`/`pa`/`ab` entry, so a prospect card-line with a fractional `ip` would also
  leak — but **verified: none of the 7 live dirty reads are prospects** (all are
  MLB players via the uppercase path). Adding `ip`/`pa`/`ab` here is correct
  defense-in-depth (it closes the prospect path prospectively) but is NOT what
  heals the committed reads.
- **`scouting/repository.py:283` `_line_sample_context`** also reads
  `line.get("ip" …)` as a raw `sample` value; that is a separate sample-context
  field, not the grounding stat the prose cites. Leave it unless the probe (Step 3)
  shows it is a leak source too — it is not for the 7 known reads.

### The 7 live dirty reads (verified from the committed artifact)

`data/models/valucast_scouting_reports.json` (716 reports). Reads whose
`published_report` prose carries a >2-decimal number:

| Read | Value in prose | Field |
|------|----------------|-------|
| Paul Skenes | 182.888 | IP |
| Jacob Misiorowski | 189.728 | IP |
| Cristopher Sánchez | 205.266 | IP |
| George Kirby | 183.883 | IP |
| Shane McClanahan | 153.457 | IP |
| Christian Scott | 111.967 | IP |
| Yoendrys Gómez | 70.778 | IP |
| ~~Charlie Condon~~ | ~~1.006~~ | **OPS — legitimate 3dp rate, NOT a leak; excluded** |

All 7 leaks are IP. No live read carries a fractional PA or AB in prose today, but
AB is unrounded in the path (550.4 above), so rounding it is the cheap prophylaxis
the register asks for.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Confirm the leak at HEAD | `python -c "from scouting.mlb_read import stat_line_stats; print(stat_line_stats({'stats': {'IP': 182.888, 'AB': 550.4, 'PA': 620.9}}))"` | prints `{'IP': 182.888, 'AB': 550.4, 'PA': 621.0}` (IP + AB un-rounded) |
| Scouting v2 tests | `python -m pytest -q tests/test_scouting_v2.py` | all pass |
| Scouting repository tests | `python -m pytest -q tests/test_scouting_repository.py` | all pass |
| Dirty-read inventory (throwaway, scratchpad) | `python <scratchpad>/_ip_precision_probe.py` (you create it — see Step 3) | prints the current dirty-read count / names |
| Full suite (final) | `python -m pytest -q` | ~1771+ passed, 0 failed; then restore the byproduct (below) |
| Restore pytest byproduct | `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json` | file back to HEAD (pytest dirties it — NEVER commit it) |

## Scope

**In scope** (the only files you modify):
- `scouting/mlb_read.py` — the PRIMARY fix: round `IP` (1dp, matching `_format_stat`) and `AB` (whole) in `_normalized_stat_value` so the MLB grounding stops carrying sub-integer IP/AB.
- `scouting/repository.py` — defense-in-depth: add `ip` (1dp) and `pa`/`ab` (whole) to the prospect-path rounding sweep (`_round_grounding_rates` / its `_RATE_ROUND_*` tuples) so a fractional prospect card-line `ip`/`pa`/`ab` can never leak either.
- `tests/test_scouting_v2.py` — add a regression test asserting `stat_line_stats` rounds IP to 1dp and AB to whole (mirror `test_stat_line_stats_derives_slg_from_ops_and_obp` at :148).

**Out of scope** (do NOT touch):
- **Regenerating the scouting artifact.** This is the load-bearing budget constraint: a full LLM re-generation of the 7 reads is an API-spend decision that is **Alex's call**, not this plan's. The fix cleans NEW and REFRESHED reads at grounding construction; the 7 committed reads heal on the next scheduled scouting regeneration (`scripts/build_scouting_repository.py`, which the daily build already runs under a generation budget). Do NOT run any scouting build or mass regen. State this in the report.
- `scouting/voice.py` / the number guard (`unsupported_numbers`, `_NUMBER_RE`) — this is plan 015's surface. The guard cannot catch this leak (182.888 literally appears in grounding, so it "matches") — that is exactly why the fix is upstream. Do not touch the guard.
- The Condon `1.006 OPS` value or any `RATE_STATS` — OPS/AVG/OBP/SLG/ISO are legitimately 3-decimal; rounding them would corrupt correct data. `_normalized_stat_value` must leave `RATE_STATS` untouched.
- `_line_sample_context` (repository.py:283) — a separate sample field, not a grounding leak for the known reads. Leave it unless Step 3's probe implicates it.
- `templates/partials/player_detail_dynasty.html` — being edited by the parallel session AND already renders IP correctly via `%.1f`; the display was never the bug.
- `prospects/ahead_of_consensus.py`, `scripts/build_ahead_of_consensus_scorecard.py` — frozen AOTC (unrelated to scouting), noted so you never wander in.

## Git workflow

- Work directly on `master` (repo convention — direct-to-main), but **do NOT push**: master auto-deploys valucast.app via Render. Commit locally; the reviewer gates the push.
- NEVER `git add -A` or `commit -am` (repo guardrail — a parallel session leaves the tree dirty, and there is an untracked `data/dd/dd_dynasty_feed.json`). Stage each file explicitly: `git add scouting/mlb_read.py scouting/repository.py tests/test_scouting_v2.py`.
- Do NOT stage the scouting artifact (`data/models/valucast_scouting_reports.json`) — you are not regenerating it; it must stay unchanged.
- Do NOT stage the pytest byproduct file or the scratchpad probe.
- Commit message style (short imperative subject), e.g. `Round IP/AB in scouting grounding so reads stop citing 182.888 innings`.

## Steps

### Step 0: Confirm the leak is live before you touch anything

```
python -c "from scouting.mlb_read import stat_line_stats; s=stat_line_stats({'stats': {'IP': 182.888, 'ERA': 3.32, 'AB': 550.4, 'PA': 620.9}}); print('IP', s['IP'], '| AB', s['AB'], '| PA', s['PA'])"
```
**Verify**: prints `IP 182.888 | AB 550.4 | PA 621.0` — IP and AB carry sub-integer
precision, PA is already whole (proving `WHOLE_COUNTING_STATS` works and IP/AB are
the gap). If IP already prints `182.9`, the fix landed since `8801cb5c` — STOP and
reconcile.

### Step 1: Round IP and AB in the MLB normalizer (primary fix)

In `scouting/mlb_read.py`, extend `_normalized_stat_value` so IP rounds to 1dp
(matching `_format_stat`'s `%.0f`/`%.1f`) and AB rounds to whole. Keep
`WHOLE_COUNTING_STATS` handling and the `RATE_STATS` passthrough exactly as-is.
Illustrative:
```python
def _normalized_stat_value(key: str, value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return value
    number = float(value)
    if key == "IP":
        # Match _format_stat: whole if integral, else 1dp. No pitcher throws
        # 0.888 of an inning — the raw model float must not reach the LLM grounding
        # (7/9 claims audit: Skenes "182.888 innings").
        return float(f"{number:.0f}") if number.is_integer() else round(number, 1)
    if key == "AB" or key in WHOLE_COUNTING_STATS:
        return float(f"{number:.0f}")
    return value
```
Note: adding the `bool` guard is a small safety tweak (a stray `True`/`False`
should never be treated as a number); keep it minimal. Do NOT add `IP`/`AB` to the
`WHOLE_COUNTING_STATS` set itself — IP needs 1dp, not whole, so it gets its own
branch. AB may be folded into the whole branch as shown.

**Verify**:
- `python -c "from scouting.mlb_read import stat_line_stats; s=stat_line_stats({'stats': {'IP': 182.888, 'AB': 550.4, 'PA': 620.9, 'OPS': 1.006, 'ERA': 3.32}}); print(s)"` → `IP` is `182.9`, `AB` is `550.0`, `PA` is `621.0`, **`OPS` is still `1.006`** (rate untouched), `ERA` still `3.32`.
- `python -c "from scouting.mlb_read import stat_line_stats; print(stat_line_stats({'stats': {'IP': 200.0}})['IP'])"` → `200.0` (integral IP stays clean, no spurious `.0` mismatch).

### Step 2: Defense-in-depth on the prospect card-line path

In `scouting/repository.py`, add the raw count/IP fields to the prospect-path
sweep so a fractional prospect card-line can't leak either. The prospect keys are
lowercase:
```python
_RATE_ROUND_1DP = ("k_per_9", "bb_per_9", "era", "whip", "ip")   # + ip (1dp)
_RATE_ROUND_WHOLE = ("k_pct", "bb_pct", "k_bb_pct", "pa", "ab")  # + pa, ab (whole)
```
This changes nothing for the 7 known MLB reads (they don't use this path) but
closes the prospect path prospectively. Confirm `_round_grounding_rates` still
guards `isinstance(value, (int, float)) and not isinstance(value, bool)` before
rounding (it does at repository.py:249/253) — so a missing field is a no-op.

**Verify**:
- `python -c "from scouting.repository import _round_grounding_rates; print(_round_grounding_rates({'ip': 182.888, 'pa': 240.7, 'ab': 210.4, 'ops': 0.9}))"` → `ip` 182.9, `pa` 241, `ab` 210, **`ops` untouched** (0.9).
- `python -m pytest -q tests/test_scouting_repository.py` → all pass (no existing test should break; if one asserts a fractional prospect ip/pa in grounding, it was pinning the bug — inspect, and if it's a genuine expected-value change, update that one assertion and note it).

### Step 3: Inventory the currently-committed dirty reads (document, do NOT regen)

Create a THROWAWAY probe in the scratchpad (do NOT commit) that counts committed
reads whose prose carries a >2-decimal number and classifies IP-family vs rate:
```python
# scratchpad only — inventories committed sub-integer IP/PA/AB leaks in scouting prose
import json, re
d = json.load(open("data/models/valucast_scouting_reports.json"))
reps = d["reports"]
dirty = []
for r in reps:
    txt = r.get("published_report") or ""
    for m in re.findall(r"\d+\.\d{3,}", txt):
        # crude classifier: an "innings" neighbor or an integer part > 30 is IP-ish;
        # a value < 2.0 with a 3dp tail is almost certainly a rate (OPS/AVG) — exclude.
        val = float(m)
        is_rate = val < 2.0
        dirty.append((r.get("name"), m, "rate(excl)" if is_rate else "IP/count"))
ip_leaks = [x for x in dirty if x[2] == "IP/count"]
print(f"reports={len(reps)} total>2dp={len(dirty)} IP/count leaks={len(ip_leaks)}")
for n, m, kind in dirty:
    print("  ", n, "::", m, kind)
```
Run it. **Expected at `8801cb5c`: 8 total >2dp, 7 classified IP/count (Skenes,
Misiorowski, C. Sánchez, Kirby, McClanahan, C. Scott, Y. Gómez), 1 excluded rate
(Condon 1.006 OPS).** Record the exact count in your report — it is the number of
committed reads that will heal on the next scheduled regen.

**Verify**: probe prints 7 IP/count leaks and 1 excluded rate; matches the table in
"Current state". If the count differs materially, note it (the artifact rebuilds
daily; the set can drift) — but the fix is unchanged, only the healing count moves.

### Step 4: Regression test

Extend `tests/test_scouting_v2.py` (it already imports `stat_line_stats`,
mlb_read.py:9). Add a test modeled on `test_stat_line_stats_derives_slg_from_ops_and_obp`
(:148-151):
```python
def test_stat_line_stats_rounds_ip_and_ab_but_not_rate(self):
    stats = stat_line_stats({"stats": {"IP": 182.888, "AB": 550.4, "PA": 620.9, "OPS": 1.006, "ERA": 3.32}})
    self.assertEqual(stats["IP"], 182.9)      # 1dp, no thousandth-of-an-inning
    self.assertEqual(stats["AB"], 550.0)      # whole
    self.assertEqual(stats["PA"], 621.0)      # whole (already covered, pinned here)
    self.assertEqual(stats["OPS"], 1.006)     # rate untouched — NOT a leak
    self.assertEqual(stats["ERA"], 3.32)      # rate untouched

def test_stat_line_stats_keeps_integral_ip_clean(self):
    self.assertEqual(stat_line_stats({"stats": {"IP": 200.0}})["IP"], 200.0)
```
(Optionally add a `_round_grounding_rates` prospect-path assertion if you want the
defense-in-depth pinned too; not required.)

**Verify**: `python -m pytest -q tests/test_scouting_v2.py` → all pass, including
the new methods.

### Step 5: Full suite + restore the pytest byproduct

```
python -m pytest -q
git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json
git status --short
```
**Verify**: full suite green (baseline ~1771+ passed, 0 failed, plus your new
tests); `git status` shows ONLY `scouting/mlb_read.py`, `scouting/repository.py`,
`tests/test_scouting_v2.py` modified — the parallel session's dirty files untouched,
the scouting artifact unchanged (you did not regen), the archive byproduct restored,
and the scratchpad probe not under the repo.

## Test plan

- `tests/test_scouting_v2.py`: +2 methods on `stat_line_stats` — (1) IP→1dp,
  AB→whole, PA→whole, rate stats (OPS/ERA) untouched; (2) integral IP stays clean.
  Real values from the live artifact (182.888) so the test documents the exact
  caught case. This is the grounding-construction proof the number guard can't
  provide.
- `tests/test_scouting_repository.py`: rely on the existing suite staying green for
  the defense-in-depth change; add a `_round_grounding_rates` ip/pa/ab assertion
  only if it fits the file's precedent (optional).
- The committed-artifact dirty-read count is exercised by the Step-3 throwaway probe
  (not a committed test — the artifact rebuilds daily and the exact set drifts;
  pinning a count would make the test brittle).
- Final: `python -m pytest -q` all green, then restore the archive byproduct.

## Done criteria

- [ ] `python -c "from scouting.mlb_read import stat_line_stats; print(stat_line_stats({'stats': {'IP': 182.888, 'AB': 550.4}}))"` → `IP` `182.9`, `AB` `550.0`.
- [ ] `python -c "from scouting.mlb_read import stat_line_stats; print(stat_line_stats({'stats': {'OPS': 1.006}}))"` → `OPS` still `1.006` (rate untouched).
- [ ] `grep -n "\"ip\"\|'ip'\|\"ab\"\|'ab'\|\"pa\"\|'pa'" scouting/repository.py` → `ip`/`pa`/`ab` present in `_RATE_ROUND_1DP`/`_RATE_ROUND_WHOLE`.
- [ ] `grep -n "IP" scouting/mlb_read.py` → `_normalized_stat_value` has an `IP` branch (1dp).
- [ ] `python -m pytest -q` exits 0; the archive byproduct restored afterward.
- [ ] `git status --short` shows only `scouting/mlb_read.py`, `scouting/repository.py`, `tests/test_scouting_v2.py` (no artifact, no receipts/parallel-session files, no scratchpad probe).
- [ ] `git diff --stat data/models/valucast_scouting_reports.json` → **empty** (no regen; the 7 committed reads heal on the next scheduled build).
- [ ] `plans/README.md` status row updated.

## STOP conditions

- The Step-0 check already prints `IP 182.9` — the fix landed since `8801cb5c`
  (someone shipped it); reconcile instead of duplicating.
- Rounding IP/AB in `_normalized_stat_value` breaks an existing test that asserted
  a fractional IP/AB in `stat_line_stats` output or in MLB grounding — that test was
  pinning the bug; inspect it, and if the new rounded value is genuinely correct,
  update that one assertion and report it. If instead the failure is on a RATE stat
  (OPS/AVG/…), your branch is over-rounding — fix the branch, not the test.
- You find yourself needing to regenerate the scouting artifact to make a test pass
  — the tests must pass against the FUNCTION, not the committed prose. A test that
  requires regen is mis-scoped; the 7 committed reads heal on the next scheduled
  build, not in this plan.
- You find yourself editing `scouting/voice.py`, the number guard, or the Condon
  OPS value — all out of scope (015's surface / a legitimate rate). Stop.
- The parallel session landed in `scouting/mlb_read.py` or `scouting/repository.py`
  and the excerpts no longer match — re-read and reconcile (those files are not in
  the session's stated edit set, so this is unlikely, but check).

## Maintenance notes

- **The primary hook is the MLB normalizer, not the register's suggested
  `_round_grounding_rates`.** The register assumed the leak was on the prospect
  card-line path (lowercase `ip`), but all 7 live dirty reads are MLB players whose
  grounding flows through `stat_line_stats` (uppercase `IP`). Rounding at
  `_normalized_stat_value` fixes the actual leak and keeps grounding consistent with
  `_format_stat`'s display rounding. The `_round_grounding_rates` addition is
  defense-in-depth for the prospect path (prospectively correct, currently unused
  by any dirty read).
- **`IP` gets its own 1dp branch, not `WHOLE_COUNTING_STATS`** — a starter's IP is
  meaningfully `182.9`, not `183`; whole-rounding IP would degrade a real display
  value. Match `_format_stat`'s `%.0f if integral else %.1f`.
- **Never round `RATE_STATS`** (AVG/OBP/SLG/OPS/ISO). Condon's `1.006 OPS` is
  correct 3-decimal baseball formatting — it is NOT the same class as `182.888 IP`
  and must be left alone. If a future audit re-flags "1.006" as false precision,
  push back: that is the standard rate display.
- **The committed 7 reads heal on regen, not here.** The fix cleans grounding at
  construction; the published prose is baked. Whoever next runs
  `scripts/build_scouting_repository.py` (daily build, under its generation budget)
  regenerates the reads with rounded grounding and the `182.888` strings disappear.
  A dedicated regen of just those 7 is a budget decision for Alex — do not trigger
  it from this plan.
- This is a SILENT-DATA-QUALITY fix with no user-visible toggle; the only proof it
  works going forward is the regression test + the next clean build. If the probe
  count ever rises after a build, the fix regressed (or a new grounding path was
  added that bypasses `_normalized_stat_value`) — re-run the Step-3 probe.
