# Plan 020: /gaps board-source freshness + consensus dispersion — stamp the field's real vintage, gate the page on its OWN staleness, and show how far the boards disagree

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
> git diff --stat 8801cb5c..HEAD -- prospects/consensus_gap.py templates/gaps.html app.py tests/test_consensus_gap.py scripts/build_consensus_gap_board.py
> git status --short
> ```
> This plan was written against `8801cb5c`. Two live drift risks:
> (1) A parallel session is editing `app.py`, `prospects/rank_v1.py`,
> `templates/partials/player_detail_dynasty.html`, `templates/methodology.html`,
> `templates/partials/rankings_table_dynasty.html`, `templates/value_map.html`,
> `web/dynasty_models.py`, `web/public_snapshot_models.py`,
> `prospects/call_up_receipts.py`, `scripts/validate_valucast_call_up_receipts.py`
> — **your only app.py edit is a new context key inside the `gaps()` route
> (HEAD ~line 7109-7128), a region that session does not touch.** Re-read that
> route against HEAD before editing; if it changed shape, reconcile. If you
> cannot cleanly add the context keys without colliding, STOP and report.
> (2) Plan 017 (Gaps → ledger claim lifecycle, post-7/13) ALSO edits
> `prospects/consensus_gap.py`, `templates/gaps.html`, `app.py`'s `gaps()`
> context, and extends `tests/test_consensus_gap.py` — the exact files this plan
> touches. The two are disjoint by theme (017 = a NEW lifecycle/enrollment
> engine + resolved/expired strip; 020 = display freshness + dispersion), but if
> 017 has already landed, re-read all four files against HEAD and confirm the
> excerpts below still match before proceeding. Land 020 first when possible.

## Status

- **Priority**: P1
- **Effort**: M (one builder enrichment, one route context add, template fineprint + a dedicated notice, one small test file extension)
- **Risk**: LOW-MEDIUM (adds display fields + a page-local staleness flag; touches NO scoring, qualification, ordering, or the frozen AOTC code; the ToS "aggregate-only" invariant is preserved and pinned by an existing test)
- **Depends on**: none. Coordinates with plan 017 (both edit `prospects/consensus_gap.py` / `templates/gaps.html` / the `gaps()` context / `tests/test_consensus_gap.py`) — land 020 first; 017's executor re-runs its drift check after.
- **Category**: honesty (staleness / provenance / uncertainty-disclosure)
- **Planned at**: commit `8801cb5c`, 2026-07-09
- **Execution window**: **anytime.** No frozen-file dependency forces post-7/13 — the fix lives entirely in the NON-frozen `consensus_gap.py`, the `gaps()` route context, `gaps.html`, and a new/extended notice partial. The frozen files (`ahead_of_consensus.py`, `build_ahead_of_consensus_scorecard.py`) are read-only imports here and stay untouched.

## Why this matters

The /gaps page is the single surface whose entire brand line is "we say so
rather than borrow credibility" (gaps.html:24) — a two-sided board of testable
claims against "the public consensus." The 7/9 claims-register audit found three
ways the page overstates the currency and agreement of that consensus. All three
are screenshot-in-one-tweet failures on the exact axis the page markets.

**(a) HIGH — the field's rank is stamped with today's date but is 9-15 days old.**
The page header stamps `editorial_date(gaps_generated_at)` = today (gaps.html:23)
and the fineprint calls each row a testable claim vs "the public consensus (median
of 3+ outside boards)" (gaps.html:24), implying the field's ranks are current.
*Embarrassment scenario from the register (verbatim):*

> "The consensus is computed from board source data that is 9-15 days old: HKB
> consensus generated 2026-06-30, MLB Pipeline as_of 2026-06-30, ProspectsLive
> top600.csv last modified 2026-06-26, STS consensus CSV 2026-06-24 (verified via
> file mtimes and snapshot generated_at fields). The daily workflow … refreshes
> MLB actuals/Statcast/MiLB/model but has NO step that re-fetches HKB/Pipeline/PL/
> STS/FG boards … So consensus_gap.json inherits today's generated_at … while the
> underlying field ranks are frozen ~2 weeks back. A prospect-Twitter regular …
> checks /gaps, sees 'field ~#26 across 4 boards' dated today for Mike Sirota, and
> can prove the number ValuCast attributes to 'the field' is a two-week-old rank —
> on the exact page whose brand is 'we say so rather than borrow credibility.'"

**(b) HIGH — /gaps is structurally exempt from the site's own 7-day stale bar.**
The page relies on the shared `{% include 'partials/_stale_notice.html' %}`
(gaps.html:14), but that banner's `snapshot_stale` flag is set by the context
processor `_snapshot_staleness` (app.py:276-281) purely from
`dynasty_data_source == 'valucast_public_snapshot_stale'` — the DD/dynasty MLB
snapshot, a completely different artifact. `consensus_gap.json` is loaded
independently in the `gaps()` route with zero freshness check on its own
`generated_at` or on the board-source vintage. *Register (verbatim):*

> "So the gap board can never show a stale notice for its own data going old: if
> the daily build fails for days, or the boards freeze for a month, the page keeps
> rendering with no warning while the shared banner only reflects an unrelated
> snapshot. The site's own honesty standard is 7 days (MAX_SNAPSHOT_STALE_DAYS=7);
> this surface is structurally exempt from it. A reader who catches the boards
> being 15 days stale (Gap 1) discovers there is no mechanism that would ever have
> told them."

**(c) MEDIUM — consensus dispersion is hidden; a split field reads like a tight one.**
Each row shows "field ~#<consensus_rank> across <board_count> boards", presenting
the rounded median as the field's single price. *Register (verbatim):*

> "The board dispersion is hidden. Charlie Condon, the #1 'WE'RE HIGHER' row (VC #3
> vs 'field ~#66 across 5 boards'), actually has boards at hkb=30, pl=44,
> pipeline=66, fg_ord=67, STS=157 (verified from valucast_prospect_rank_v1.json) —
> a 127-spot spread where the field flatly disagrees with itself. The page shows a
> tidy '~#66' that no single board holds and implies field agreement that isn't
> there. … a 40-PA-equivalent thin/split field is shown identically to a tight one
> (De Vries, boards [2,2,2,6,23], is genuinely tight — but the page renders both
> the same). No IQR, range, or agreement indicator is published."

All three are provenance/uncertainty disclosures. None require changing which
boards count, the median math, the qualification thresholds, ordering, or the
AOTC scoring — those all stay byte-identical.

## Current state

Verified against the live files at `8801cb5c` (`app.py` re-verify against HEAD
per the drift check — a parallel session is editing it, though not the `gaps()`
route region).

### The gaps builder is NOT frozen — the frozen code is only imported

- **`prospects/consensus_gap.py`** (the /gaps display-artifact builder) is
  **in scope** and safe to edit. It imports primitives from the FROZEN
  `prospects/ahead_of_consensus.py` (`_board_rows`, `_divergence_row`,
  `_conviction`, `active_roster_lookup`, `FEATURED_MIN_BOARDS`, `MAX_VALUCAST_RANK`,
  `MIN_DIVERGENCE`, `RANK_PATH`, `MLB_ROSTER_STATUS_PATH`, `_load_optional`) but
  the enrichment this plan adds lives entirely in the NON-frozen builder. **Do NOT
  edit `prospects/ahead_of_consensus.py` or `scripts/build_ahead_of_consensus_scorecard.py`
  — pre-registered AOTC scoring, frozen until ~7/13.**
- **The dispersion data is ALREADY computed by the frozen `_divergence_row`** and
  is available to the non-frozen builder without any frozen-file change:
  `prospects/ahead_of_consensus.py:136-139` builds a `boards` dict of per-source
  ranks (`{source: rank}`), returned on every divergence row (`:155`). Verified
  live: Charlie Condon's row carries
  `boards = {'fg_ord': 67, 'hkb': 30, 'pipeline': 66, 'pl': 44, 'sts': 157}`,
  `consensus_rank = 66`, `board_count = 5` — so `min = 30`, `max = 157` are a pure
  read off the row the builder already has in hand.
- **`consensus_gap.py:87-99` `_display_row`** is where the ToS trim happens today:
  it copies only aggregate keys (`identity_key, mlbam_id, name, team, role,
  valucast_rank, consensus_rank, board_count, divergence`) and **deliberately drops
  the per-source `boards` dict** (the comment at `:88-91` and the test at
  `tests/test_consensus_gap.py:41` — `assert "boards" not in payload["higher"][0]`
  — pin this: per-source ranks must NEVER leave the builder). This is the seam to
  add aggregate `board_min` / `board_max` **integers** (NOT the `boards` dict).
- **`consensus_gap.py:130-170` `build_consensus_gap_board`** assembles the artifact
  dict — `generated_at`, `method`, `scoring`, `summary`, `higher`, `lower`. There is
  **no board-vintage field today.** `run()` (`:173-182`) reads `RANK_PATH` and
  `MLB_ROSTER_STATUS_PATH` and writes the artifact; it does not read the raw board
  snapshots.

### Where board-source dates actually live (investigated — this is the load-bearing surprise)

The rank artifact `data/models/valucast_prospect_rank_v1.json` does **NOT** carry
per-board source dates: its `input_artifacts` block lists only model/schema
versions, no board vintages (verified). The per-board ranks are stamped onto each
row's `context_only.source_ranks` by `prospects/rank_v1.py:411-449` from five
committed snapshot files. Their vintages are **inconsistent** — only two carry an
internal date:

| Board | Snapshot file (loaded by rank_v1.py:404-408) | Internal date field | Value at `8801cb5c` |
|-------|----------------------------------------------|---------------------|---------------------|
| HKB | `data/hkb/hkb_consensus_snapshot.json` | `generated_at` | 2026-06-30 |
| Pipeline | `data/pipeline/pipeline_consensus_snapshot.json` | `generated_at` / `as_of` | 2026-06-30 |
| ProspectsLive | `data/prospectslive/prospectslive_consensus_snapshot.json` | **none** (source CSV `prospectslive_top600.csv`) | CSV committed 2026-06-26 |
| STS | `data/sts/sts_consensus_snapshot.json` | **none** (source CSV `sts_consensus_hitters.csv`) | CSV committed 2026-06-24 |
| FanGraphs | `data/fangraphs/fg_fv_snapshot.json` | **none** (source `fg_board_*.csv`) | no reliable committed vintage |

**Surprise / trap, verified:** the three consensus-`snapshot.json` files
(PL/STS/FG) get **re-committed with today's date** by the daily build even though
their real source CSVs are ~2 weeks old — so `git log -1 --format=%cs` on the
`*_consensus_snapshot.json` is a MISLEADING vintage (it reads "today"). The
honest per-board vintage is: the **internal `generated_at`** for HKB and Pipeline,
and the **raw source CSV's committed date** (`git log -1 --format=%cs -- <csv>`,
or its filesystem mtime as a fallback) for PL and STS. FG has no dependable
committed vintage on the export CSVs today. So a builder that just stamps
"today" or reads the snapshot-JSON commit date would reproduce the exact lie the
register flags. See Step 1 for the honest minimal approach.

### The staleness plumbing you will mirror (do not reuse the DD flag)

- **`app.py:276-281` `_snapshot_staleness`** context processor — sets
  `snapshot_stale` from `dynasty_data_source == "valucast_public_snapshot_stale"`.
  This is the DD/dynasty snapshot flag; it must NOT be reused for /gaps (register
  gap b is precisely that /gaps rides this unrelated flag).
- **`app.py:648-651`** `MAX_SNAPSHOT_STALE_DAYS = 7` and `_within_stale_window(generated_at, max_days=…)`
  — the site's honesty bar (7 days) and the date-diff helper. `_within_stale_window`
  returns `True` when `generated_at` is within the window (i.e. fresh). Reuse this
  helper for the board-min-date check; do NOT invent a second date parser.
- **`app.py:7109-7128` the `gaps()` route** — loads `CONSENSUS_GAP_PATH`
  (`app.py:568-570`) via `_load_artifact` and renders `gaps.html` with
  `gaps_generated_at`, `gaps_method`, `gaps_summary`, `gaps_higher`, `gaps_lower`,
  `as_of`, etc. **No board-vintage or gap-staleness key today.**
- **`templates/partials/_stale_notice.html`** — the shared DD banner (single
  `{% if snapshot_stale %}` div). The new gaps notice must be a **distinct**
  element (a new partial or an inline block in gaps.html), NOT a change to this
  shared file, so the two staleness concepts stay separate (register gap b).

### The gaps template render points

- **`templates/gaps.html:23`** — header sub: `{{ gap_count }} gaps{% if gaps_generated_at %} &middot; {{ editorial_date(gaps_generated_at) }}{% endif %}`.
- **`gaps.html:24`** — the "median of {{ gaps_method.min_boards }}+ outside boards … we say so rather than borrow credibility" fineprint.
- **`gaps.html:14`** — `{% include "partials/_stale_notice.html" %}` (the DD banner; the new gaps notice goes near here or in the heading).
- **`gaps.html:48` and `:63`** — the per-row tag: `{{ p.team }} &middot; field ~#{{ p.consensus_rank }} across {{ p.board_count }} boards` (both the higher and lower sides). This is where the spread affordance is added.
- **`gaps.html` is NOT in the parallel session's edit set** and is NOT touched by plan 013 (013's scope is buys/movers/comps/methodology templates — confirmed). It IS in plan 017's scope (post-7/13); coordinate per the drift check.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Consensus-gap builder tests | `python -m pytest -q tests/test_consensus_gap.py` | all pass |
| Rebuild the gaps artifact after the builder change | `python scripts/build_consensus_gap_board.py` | prints the evaluated/ahead/fade summary; artifact regenerates |
| Confirm dispersion for a known split row | `python -c "from prospects.ahead_of_consensus import _divergence_row, _board_rows; import json; d=json.load(open('data/models/valucast_prospect_rank_v1.json')); [print(r['name'], sorted(_divergence_row(r)['boards'].values())) for r in _board_rows(d) if _divergence_row(r) and _divergence_row(r).get('name')=='Charlie Condon']"` | prints `Charlie Condon [30, 44, 66, 67, 157]` |
| Full suite (final) | `python -m pytest -q` | ~1771+ passed, 0 failed; then restore the byproduct (below) |
| Restore pytest byproduct | `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json` | file back to HEAD (pytest dirties it — NEVER commit it) |

## Scope

**In scope** (the only files you modify or create):
- `prospects/consensus_gap.py` — (i) add aggregate `board_min`/`board_max` integers to `_display_row`; (ii) read the board-source vintages and record a `board_source_dates` map + a `board_min_date` into the artifact in `build_consensus_gap_board` / `run`.
- `app.py` — inside the `gaps()` route ONLY: pass the artifact's `board_min_date` (and the per-board dates if rendered) into the template, plus a computed `gap_boards_stale` flag (via `_within_stale_window`). No other app.py region.
- `templates/gaps.html` — (i) "boards last refreshed <date>" fineprint; (ii) a dedicated gaps-staleness notice when `gap_boards_stale`; (iii) the per-row spread affordance ("field #30-#157, median ~#66") on both sides.
- OPTIONAL NEW `templates/partials/_gaps_stale_notice.html` — the dedicated notice, if you prefer a partial over an inline block. (A partial is cleaner; either is acceptable. Do NOT edit the shared `_stale_notice.html`.)
- `tests/test_consensus_gap.py` — extend: assert `board_min`/`board_max` present and correct, assert the ToS invariant still holds (no `boards` dict leaks), assert `board_min_date` is recorded, and (route-level) assert the fineprint/notice renders.

**Out of scope** (do NOT touch):
- `prospects/ahead_of_consensus.py`, `scripts/build_ahead_of_consensus_scorecard.py` — **FROZEN** (pre-registered AOTC scoring, ~7/13 unlock). Import only. Do NOT add a date field, a dispersion field, or anything else to `_divergence_row` — read the `boards` dict it already returns, in the non-frozen builder.
- `prospects/rank_v1.py` — being edited by the parallel session; also NOT where this fix belongs (the rank artifact has no board-date map and adding one there is a bigger, coupled change). Read via `git show HEAD:prospects/rank_v1.py` only if you need to confirm the snapshot paths.
- The board-source snapshot BUILDERS (`scripts/build_hkb_consensus_snapshot.py`, `build_pipeline_consensus_snapshot.py`, `build_prospectslive_consensus_snapshot.py`, the STS/FG loaders) — do NOT add date stamping to the dateless snapshots in this plan; read their existing vintages. (Adding an internal `source_date` to PL/STS/FG snapshots is a reasonable follow-up but is a separate, cross-file change — note it in Maintenance, don't do it here.)
- The median math, board selection (`_public_source_ranks`), qualification (`_qualifies_ahead`/`_qualifies_fade`), ordering (`_conviction`), depth rule, or the 15-row cap — all unchanged.
- `_snapshot_staleness` / the shared `_stale_notice.html` / the DD `snapshot_stale` flag — the gaps notice is a SEPARATE flag and element.
- Per-source rank publication — `board_min`/`board_max` are the ONLY dispersion numbers that may appear; the `boards` dict must stay out of the artifact and off the page (ToS rule, pinned by `tests/test_consensus_gap.py:41`).

### Register gaps deliberately EXCLUDED from this plan (same surface, different theme)

The Surface-3 register has three MORE gaps that are NOT in this plan:
- **STS double-counting** (medium, provenance): "across N boards" counts STS (itself a formulated consensus) as one independent board. Relabeling/excluding STS from the COUNT is a board-independence change touching how `board_count` is computed — a different theme; leave `board_count` semantics alone here.
- **Fade truncation "showing 15 of 46"** (medium, falsifiability): render `shown_per_side` vs `fade_qualified`. This is display copy but belongs with plan 017's ledger-lifecycle work (which enrolls the full qualified set); do NOT add it here to avoid colliding with 017's rework of the same fineprint.
- **Fresh-exclusion / stale-consensus asymmetry** (medium, staleness): the "as of <board date>" per-row qualifier. This is SUBSUMED by fix (a) — once "boards last refreshed <date>" is on the page, the field-rank vintage is disclosed page-wide. Do NOT also add a per-row "as of" string (redundant clutter); the page-level fineprint is the honest minimal answer. Note this reconciliation in Maintenance.

## Git workflow

- Work directly on `master` (repo convention — direct-to-main), but **do NOT push**: master auto-deploys valucast.app via Render. Commit locally; the reviewer gates the push.
- NEVER `git add -A` or `commit -am` (repo guardrail — a parallel session and the in-flight receipts work leave the tree dirty). Stage each in-scope file explicitly. **Never `git stash`.**
- Do not stage or commit the parallel session's files, the pytest byproduct, or the untracked `data/dd/dd_dynasty_feed.json`.
- The regenerated `data/models/valucast_consensus_gap.json` **is** a committed artifact (its sibling builders commit their outputs); stage it explicitly alongside the code. Confirm its diff is ONLY the new `board_min`/`board_max`/`board_min_date`/`board_source_dates` fields plus the unchanged rows.
- Commit message style (short imperative subject), e.g. `Stamp /gaps board vintage, gate it on its own staleness, show consensus spread`.

## Steps

### Step 0: Confirm the three gaps are live before touching anything

```
# (a) the artifact stamps generated_at but has no board vintage:
python -c "import json; d=json.load(open('data/models/valucast_consensus_gap.json')); print('generated_at', d.get('generated_at')); print('has board vintage key:', any('board' in k and 'date' in k for k in d)); print('sample higher row keys:', list((d.get('higher') or [{}])[0].keys()))"
# expect: generated_at ~today; 'has board vintage key: False'; row keys have NO board_min/board_max
# (b) the gaps route has no gap-staleness key:
git show HEAD:app.py | sed -n '7109,7128p'
# expect: render_template("gaps.html", ...) with NO gap_boards_stale / board_min_date
# (c) the row tag shows only the median, no spread:
grep -n "field ~#" templates/gaps.html
# expect: two hits (:48, :63), neither shows a range
```
**Verify**: all three confirm the gaps are present at HEAD. If any is already
fixed (a board-vintage key exists, or a `gap_boards_stale` context key is passed),
the parallel session or plan 017 landed here first — STOP and reconcile.

### Step 1: Record the board vintages in the gaps artifact

All edits in `prospects/consensus_gap.py` (non-frozen). The honest vintage per
board is: the internal `generated_at`/`as_of` for HKB and Pipeline; the source
CSV's committed date for PL and STS; FG has no dependable committed vintage today
(record it as `null`/omit and do not let it poison the min). See "Current state"
for why the snapshot-JSON commit date is a lie.

**1a — Add a small vintage reader.** Add a module-level helper (fail-soft, no new
imports beyond `json`/`datetime`/`subprocess`-free — prefer reading committed file
content and `os.path.getmtime` as a fallback over shelling out). Concretely:

```python
# 7/9 claims audit (Surface 3, gap a/b): the /gaps page stamps today's date on a
# field consensus whose source boards are 9-15 days old, and nothing gates the page
# on that vintage. Record the real per-board dates so the page can disclose them.
# Only HKB and Pipeline snapshots carry an internal date; PL/STS derive from their
# source CSV; FG has no dependable committed vintage. See plan 020 "Current state".
_BOARD_SOURCES = {
    "hkb": ROOT / "data" / "hkb" / "hkb_consensus_snapshot.json",
    "pipeline": ROOT / "data" / "pipeline" / "pipeline_consensus_snapshot.json",
    "pl": ROOT / "data" / "prospectslive" / "prospectslive_top600.csv",
    "sts": ROOT / "data" / "sts" / "sts_consensus_hitters.csv",
    # fg intentionally omitted: no dependable committed vintage on the export CSV today.
}

def _board_source_date(source: str, path: Path) -> str | None:
    """Best available YYYY-MM-DD vintage for one board. Internal generated_at/as_of
    for JSON snapshots that carry one; file mtime otherwise. Fail-soft -> None."""
    try:
        if path.suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            stamp = payload.get("generated_at") or payload.get("as_of")
            if stamp:
                return str(stamp)[:10]
        # dateless snapshots / CSVs: fall back to filesystem mtime (the committed
        # CSV's date). NOT the *_consensus_snapshot.json commit date, which the
        # daily build re-stamps to today even when the CSV is 2 weeks old.
        from datetime import datetime, timezone
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).date().isoformat()
    except Exception:  # noqa: BLE001
        return None

def _board_vintages() -> dict:
    dates = {src: _board_source_date(src, p) for src, p in _BOARD_SOURCES.items()}
    present = sorted(d for d in dates.values() if d)
    return {
        "board_source_dates": {k: v for k, v in dates.items() if v},
        "board_min_date": present[0] if present else None,
    }
```

> **Note on mtime vs git-date**: `git log -1 --format=%cs -- <csv>` is the most
> honest source-CSV vintage, but shelling to git from a builder that also runs in
> CI is brittle (shallow clones, detached HEAD). Filesystem mtime is the pragmatic
> fallback and matches how the register itself measured the vintages ("verified via
> file mtimes"). If mtime proves unreliable in CI (checkout resets it to now),
> STOP and report — do NOT silently ship a "today" vintage that recreates the lie.
> A follow-up (Maintenance) is to have the PL/STS/FG snapshot BUILDERS stamp an
> internal `source_date`, which removes the mtime dependency entirely.

**1b — Thread the vintages into the artifact.** In `build_consensus_gap_board`,
accept the vintages (compute them in `run()` and pass in, mirroring how
`roster_status` is injected, so tests stay pure/deterministic):

```python
def build_consensus_gap_board(rank_payload, generated_at=None, roster_status=None, board_vintages=None):
    ...
    payload = { ... existing keys ... }
    vintages = board_vintages or {}
    payload["board_source_dates"] = vintages.get("board_source_dates") or {}
    payload["board_min_date"] = vintages.get("board_min_date")
    return payload
```
and in `run()`: `board_vintages=_board_vintages()` passed through. Keep the
`method`/`scoring`/`summary` blocks byte-identical otherwise.

**Verify**:
- `python scripts/build_consensus_gap_board.py` runs clean.
- `python -c "import json; d=json.load(open('data/models/valucast_consensus_gap.json')); print(d['board_min_date']); print(d['board_source_dates'])"` → prints a date near `2026-06-24`/`2026-06-30` (NOT today) and a per-board map with at least hkb+pipeline dated.
- If `board_min_date` prints today's date, the mtime fallback is reading a re-stamped file — STOP (see the note in 1a).

### Step 2: Add aggregate dispersion (board_min / board_max) to the display rows

Still in `prospects/consensus_gap.py`. In `_display_row`, derive the min/max of
the per-source ranks from the `boards` dict the frozen `_divergence_row` already
put on the row, and emit them as **integers** (never the dict):

```python
def _display_row(row: dict) -> dict:
    # Aggregate consensus only — the per-source `boards` dict never enters this
    # artifact (ToS). But its min/max ARE publishable as a dispersion signal: they
    # reveal a split field (Condon #30-#157) vs a tight one (De Vries #2-#23)
    # without redistributing any single board's exact per-player rank.
    board_ranks = [r for r in (row.get("boards") or {}).values() if isinstance(r, (int, float))]
    out = {key: row.get(key) for key in (
        "identity_key", "mlbam_id", "name", "team", "role",
        "valucast_rank", "consensus_rank", "board_count", "divergence",
    )}
    if board_ranks:
        out["board_min"] = int(min(board_ranks))
        out["board_max"] = int(max(board_ranks))
    return out
```

**Correctness constraint**: the output dict must still NOT contain the key
`boards`. Confirm `tests/test_consensus_gap.py:41` (`assert "boards" not in payload["higher"][0]`)
stays green — publishing `board_min`/`board_max` is a two-number summary, not the
per-source list, so the ToS invariant holds. If you find yourself tempted to add
the `boards` dict "for the template," STOP — the min/max integers are all the page
gets.

**Verify**:
- `python scripts/build_consensus_gap_board.py && python -c "import json; d=json.load(open('data/models/valucast_consensus_gap.json')); r=[x for x in d['higher'] if x['name']=='Charlie Condon']; print(r[0] if r else 'Condon not in higher (check ordering)')"` → the Condon row shows `board_min: 30, board_max: 157, consensus_rank: 66` and NO `boards` key.
- `grep -c '"boards"' data/models/valucast_consensus_gap.json` → **0** (per-source ranks never entered the artifact).

### Step 3: Pass the vintage + a gaps-specific staleness flag into the route

In `app.py`, inside the `gaps()` route ONLY (HEAD ~7109-7128). Add:
```python
board_min_date = payload.get("board_min_date")
gap_boards_stale = bool(board_min_date) and not _within_stale_window(board_min_date)
```
and add to the `render_template("gaps.html", …)` kwargs:
```python
gaps_board_min_date=board_min_date,
gaps_board_source_dates=payload.get("board_source_dates") or {},
gap_boards_stale=gap_boards_stale,
```
Do NOT touch `_snapshot_staleness` or the DD `snapshot_stale` flag — this is a
distinct, page-local flag computed from the board vintage. Reuse the existing
`_within_stale_window` helper (app.py:651) so the 7-day bar is single-sourced.

**Verify**:
- `git show HEAD:app.py | sed -n '648,651p'` confirms `_within_stale_window` still takes `(generated_at, max_days=MAX_SNAPSHOT_STALE_DAYS)` and returns True when fresh — so `not _within_stale_window(board_min_date)` is True when the board min date is older than 7 days (the intended "stale" sense). If the helper's return polarity changed, adjust and note it.
- `python -c "import app; c=app.app.test_client(); html=c.get('/gaps').data.decode(); print('boards last refreshed' in html or 'refreshed' in html)"` (after Step 4 template edit) → True.

### Step 4: Render the vintage fineprint, the dedicated notice, and the spread

All in `templates/gaps.html` (and optionally the new `_gaps_stale_notice.html`).

**4a — "boards last refreshed <date>" fineprint.** In the heading block (near
`gaps.html:23-25`), add a fineprint line driven by `gaps_board_min_date`, e.g.:
```
{% if gaps_board_min_date %}<p class="buys-fineprint">The field ranks come from outside boards last refreshed {{ editorial_date(gaps_board_min_date) }} — the divergence is measured against that vintage, not today's boards.</p>{% endif %}
```
Keep the existing `editorial_date(gaps_generated_at)` header stamp (it honestly
dates when ValuCast *computed* the board), but this line now discloses the FIELD's
vintage separately, resolving the conflation the register flags.

**4b — Dedicated gaps staleness notice (distinct from the DD banner).** When
`gap_boards_stale`, render a notice near `gaps.html:14` (or as
`{% include "partials/_gaps_stale_notice.html" %}`). It must be visibly distinct
from the DD `_stale_notice.html` and name the board vintage:
```
{% if gap_boards_stale %}
<div class="notice">The outside prospect boards behind these gaps were last refreshed {{ editorial_date(gaps_board_min_date) }}, past our 7-day freshness bar — the field's ranks may have moved since. We refresh boards on their own cadence, not daily.</div>
{% endif %}
```
Do NOT gate this on `snapshot_stale`; it is its own flag. Do NOT edit
`_stale_notice.html`.

**4c — Spread affordance on each row.** At `gaps.html:48` and `:63`, extend the
tag so a split field reads differently from a tight one, driven by
`p.board_min`/`p.board_max` (guard on their presence):
```
<span class="buys-tag">{{ p.team }} &middot; field {% if p.board_min is not none and p.board_max is not none and p.board_min != p.board_max %}#{{ p.board_min }}&ndash;#{{ p.board_max }}, median{% endif %} ~#{{ p.consensus_rank }} across {{ p.board_count }} boards</span>
```
When min == max (unanimous) or the fields are absent, it falls back to the current
"field ~#N across M boards" phrasing exactly. Verify the ToS line: only the
aggregate min/max/median appear — never a per-source attribution (no "hkb #30").

**Verify**:
- `python -m pytest -q tests/test_consensus_gap.py` → all pass (including your extensions).
- `python -c "import app; c=app.app.test_client(); html=c.get('/gaps').data.decode(); print('last refreshed' in html); print('median' in html)"` → both True.
- `grep -n "hkb\|pipeline\|fg_ord\|\bpl\b\|sts" templates/gaps.html` → **no per-source board names rendered as ranks** (the spread is anonymous min/max only). Board *source-date* keys in `gaps_board_source_dates` may be referenced if you chose to render a per-board date list, but per-source RANKS must never appear.

### Step 5: Full suite + restore the pytest byproduct

```
python -m pytest -q
git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json
git status --short
```
**Verify**: full suite green (baseline ~1771+ passed, 0 failed, plus your new
assertions); `git status` shows ONLY `prospects/consensus_gap.py`, `app.py`,
`templates/gaps.html`, `tests/test_consensus_gap.py`, the regenerated
`data/models/valucast_consensus_gap.json`, and (if created)
`templates/partials/_gaps_stale_notice.html` as YOUR changes — the parallel
session's dirty files stay untouched, the archive byproduct is restored, and the
untracked `data/dd/dd_dynasty_feed.json` is not staged.

## Test plan

- `tests/test_consensus_gap.py` extend (mirror the existing `_rank_row`/`build_consensus_gap_board` fixtures):
  1. **Dispersion published as min/max, not the dict**: build a row whose boards
     span widely (e.g. `boards={"hkb": 30, "pl": 44, "sts": 157}`) and assert the
     display row has `board_min == 30`, `board_max == 157`, `consensus_rank`
     unchanged, AND `"boards" not in row` (re-pin the ToS invariant alongside the
     new fields).
  2. **Unanimous field**: `boards={"hkb": 20, "pl": 20, "sts": 20}` → `board_min == board_max == 20` (template will collapse to the plain phrasing).
  3. **Vintage recorded**: call `build_consensus_gap_board(..., board_vintages={"board_source_dates": {"hkb": "2026-06-30"}, "board_min_date": "2026-06-24"})` and assert `payload["board_min_date"] == "2026-06-24"` and the map round-trips. (Test the injection path — do NOT make the test read real snapshot files, which drift daily.)
  4. **Route staleness flag** (extend `test_gaps_page_drift_locks_to_the_committed_artifact` or add a sibling): assert the `/gaps` HTML contains "last refreshed" when the committed artifact carries a `board_min_date`, and that the existing drift-lock assertions (`~#<consensus_rank>`, "not ledger-scored yet", "sample-size statement", "build_consensus_gap_board.py") STILL pass unchanged.
- Do NOT add a test that pins the exact real `board_min_date` value (it drifts with each board refresh) — pin the injection path and the presence of the fineprint instead.
- Final: `python -m pytest -q` all green, then restore the archive byproduct.

## Done criteria

- [ ] `python -m pytest -q` exits 0 (~1771+ passed, 0 failed); the byproduct file restored after.
- [ ] `python -c "import json; d=json.load(open('data/models/valucast_consensus_gap.json')); print(d['board_min_date'], bool(d['board_source_dates']))"` → a date NOT equal to today, and a non-empty source-date map (hkb+pipeline at minimum).
- [ ] `grep -c '"boards"' data/models/valucast_consensus_gap.json` → **0** (ToS invariant intact; per-source ranks never published).
- [ ] `grep -n "board_min\|board_max" data/models/valucast_consensus_gap.json` → present on rows whose field disagrees.
- [ ] `/gaps` HTML contains "last refreshed" (vintage fineprint) and, for a split row, a "#min–#max, median ~#N" tag.
- [ ] `grep -n "gap_boards_stale\|_within_stale_window(board_min_date)\|board_min_date" app.py` → the gaps route computes and passes the page-local flag; `_snapshot_staleness` is unchanged.
- [ ] `git diff --stat prospects/ahead_of_consensus.py scripts/build_ahead_of_consensus_scorecard.py prospects/rank_v1.py` → **empty** (frozen + parallel-session files untouched).
- [ ] `git diff --name-only` shows ONLY: `prospects/consensus_gap.py`, `app.py`, `templates/gaps.html`, `tests/test_consensus_gap.py`, `data/models/valucast_consensus_gap.json`, and optionally `templates/partials/_gaps_stale_notice.html` — plus the pre-existing parallel-session dirty files, which you did not touch. Byproduct restored (not listed).
- [ ] `plans/README.md` status row updated.

## STOP conditions

- The board-source mtime fallback (Step 1a) reads **today's** date for PL/STS/FG
  in your environment (a checkout re-stamped the files) — shipping would recreate
  the exact "today's date on 2-week-old boards" lie the register flags. Report; do
  NOT ship a "today" vintage. (The durable fix is builder-side internal
  `source_date` stamping — a follow-up, not this plan.)
- `prospects/ahead_of_consensus.py::_divergence_row` no longer returns a `boards`
  dict on each row (a parallel edit removed it) — the dispersion source is gone.
  Report; do NOT re-add `boards` to the frozen file.
- `tests/test_consensus_gap.py:41` (`"boards" not in payload["higher"][0]`) fails
  after your change — you leaked the per-source dict into the artifact. Fix the
  builder; never relax that assertion.
- The `gaps()` route in app.py no longer matches the HEAD shape (the parallel
  session or plan 017 landed in it) — re-read, reconcile, and if a
  `gap_boards_stale`/`board_min_date` key is already present, report instead of
  duplicating.
- `_within_stale_window` changed signature or return polarity — re-derive the
  stale sense and note it; do NOT hand-roll a second date-diff.
- Any change would require editing `prospects/ahead_of_consensus.py`,
  `scripts/build_ahead_of_consensus_scorecard.py`, or `prospects/rank_v1.py` — all
  out of scope (frozen or parallel-session). Stop.

## Maintenance notes

- **The board-vintage plumbing is the honest-but-fragile part.** Today only HKB
  and Pipeline snapshots carry an internal date; PL/STS derive from source-CSV
  mtime and FG has none. The durable fix is to have the PL/STS/FG snapshot BUILDERS
  write an internal `source_date`/`generated_at` (like HKB/Pipeline already do),
  after which `_board_source_date` can drop the mtime fallback and read the field
  directly. That is a separate cross-file plan (touches the snapshot builders);
  file it if the mtime path ever proves unreliable in CI.
- **The excluded per-row "as of <board date>" (register Surface-3 gap 6) is
  intentionally SUBSUMED** by the page-level "boards last refreshed <date>"
  fineprint — do not later add a redundant per-row "as of" string. If the boards
  ever refresh on genuinely different per-board cadences that matter per row,
  revisit, but the min-date page fineprint is the honest minimal disclosure today.
- **The STS-double-count and fade-truncation gaps are deliberately left to their
  own themes** (board-independence relabeling; plan 017's ledger-lifecycle). If
  plan 017 lands the "showing 15 of 46" line, do NOT duplicate it here.
- **Dispersion is aggregate-only by ToS.** `board_min`/`board_max` are the ceiling
  of what may be published — never the per-source `boards` dict, never a
  board-attributed rank. The frozen `_divergence_row` keeps `boards` internal; this
  plan reads it and emits two anonymous integers. Keep it that way.
- The gaps staleness flag is single-sourced on `_within_stale_window` /
  `MAX_SNAPSHOT_STALE_DAYS` — if the site's 7-day bar changes, /gaps follows
  automatically. Do not hardcode 7 in the template or the route.
