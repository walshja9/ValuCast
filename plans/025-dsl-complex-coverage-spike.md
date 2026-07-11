# Plan 025: DSL / Complex-League Coverage — a feasibility SPIKE (Phase A) with a written decision gate, and a gated NO-VALUE-NUMBER minimal build (Phase B) executed only if the spike passes

> **Executor instructions**: This is a **TWO-PHASE, SPIKE-FIRST** plan. **Phase A is
> the whole first deliverable: a feasibility spike that produces a written decision
> memo.** Do NOT build any product surface in Phase A. Run every Phase-A probe,
> record the numbers, and write the memo. Then evaluate the memo against the
> **Decision Gate** (below). **Phase B is executed ONLY if the gate passes** — and
> if it does not, you STOP with the memo, which is a complete and successful
> outcome. Follow each step; run every verification; if a STOP condition fires,
> stop and report. When done (either "memo, gate failed" or "memo + Phase B"),
> update this plan's status row in `plans/README.md` unless a reviewer dispatched
> you and said they maintain the index.
>
> **Drift check (run first)**:
> ```
> git log -1 --format=%h    # baseline for this plan is f60b8545
> git diff --stat f60b8545..HEAD -- scripts/refresh_milb_season_stats.py prospects/universe.py prospects/rank_v1.py prospects/ahead_of_consensus.py scripts/build_sts_consensus_snapshot.py scripts/build_prospect_universe.py .github/workflows/daily-public-data.yml scripts/run_daily_public_build.py
> git status --short
> ```
> This plan was written against `f60b8545`. All "Current state" line refs are
> accurate to that commit. If any in-scope file changed since, re-read the cited
> excerpt against the live code before proceeding; on a mismatch with an excerpt,
> treat it as a STOP condition. The load-bearing surfaces are the MiLB fetch idiom
> (`refresh_milb_season_stats.py:SPORT_LEVELS` at line 20-25 + `_fetch_splits` at
> line 76-104 + `_assert_not_tiny_refresh` at line 288-302 + `write_milb_season_stats`
> at line 304-310), the universe identity contract (`prospects/universe.py:identity_key`
> at line 164-167 + the fail-hard dedup at line 265-271), and the consensus join
> (`scripts/build_sts_consensus_snapshot.py` — name-based, no mlbam).
>
> **This is NOT a build-blocked plan and NOT a frozen-file plan** — Phase A writes
> only to `scratch/` (see Invariants) and a `docs/` memo. Phase B, IF it runs, adds
> a build script + a committed artifact + a fail-soft reader + a card section, all
> new files, none frozen. As everywhere: master auto-deploys valucast.app via
> Render, so do NOT push; the reviewer gates the push.

## Status

- **Priority**: P3 (product-coverage gap, NOT a correctness or honesty leak in the
  existing product). This is a "should we open a new frontier" question, not a "fix
  a broken thing" one. The spike is cheap; the build is gated and deliberately
  minimal. Do not let the competitive framing (below) inflate the priority — the
  honesty frame is the product here, and the honest default is a very small surface.
- **Effort**: **Phase A = S** (a day of live-API probing + a written memo — no
  product code). **Phase B = M–L, GATED** (a new Rookie-level fetch extension, a
  stat-only card surface, search inclusion, tests, daily wiring) — and only the
  subset the gate authorizes. **The single biggest effort lever is that Phase B
  ships NO value number, NO percentile bars, and NO board page** (see Non-goals):
  it is a stat-line + age-vs-level context + watchlist surface, which is far
  smaller than a valuation feature. If the spike finds the cohort is unservable
  cleanly, Phase B effort is **zero** (STOP with the memo).
- **Risk**: **MEDIUM, front-loaded into the gate.** The whole point of the
  spike-first structure is to convert the risks into pass/fail probes *before*
  any product code exists:
  - **Identity-resolution blow-up.** The universe build **hard-fails** on any
    missing mlbam id or duplicate `(mlbam_id, role)` key (`universe.py:265-271`
    raises `ValueError`). If DSL/complex players lack resolvable mlbam ids, or if
    17yo name collisions ("twins") produce duplicate keys at scale, naively feeding
    them into the existing universe would **crash the daily build**. The spike must
    measure this before Phase B touches the universe (Gate criterion 1).
  - **Speculative-number temptation.** At 17yo / sub-100-PA samples, ANY value
    number, percentile, or "elite" projection is survivorship-biased noise. The
    honesty default (no value number) is a *risk control*, not a limitation — see
    "The honesty frame IS the product."
  - **Base-rate / survivorship framing.** A competitor account is currently
    building a following on exactly this cohort by implying elite-teenager
    outcomes; the plan **forbids** any "X% of elite 17yos become stars"-style
    claim (that is the survivorship trap — see STOP conditions).
- **Depends on**: none in flight. The spike reads live MLB StatsAPI (network, in
  `scratch/` only) and the committed universe/consensus artifacts (read-only).
  Phase B, if it runs, mirrors the `refresh_milb_season_stats.py` build idiom.
  Coordinates with nothing frozen. Independent of the receipts cluster and 023.
- **Category**: feature — but Phase A is *research/feasibility* (a memo), and Phase
  B is a *new coverage surface*, deliberately minimal and observe-only.
- **Planned at**: commit `f60b8545`, 2026-07-11.
- **Execution window**: **post-7/13** (repo-wide batch-3 convention; no frozen-file
  dependency, but do not start before the 7/13 ledger-week unlock). Phase A can run
  as soon as the window opens; Phase B, if gated in, follows in the same or a later
  session.

## Why this matters (and why the honest answer is a small surface)

Deep dynasty leagues roster DSL kids and complex-league (FCL/ACL) teenagers as
FYPD (first-year player draft) prep — a real cohort that ValuCast covers **zero**
of today (the pipeline stops at Low-A; see Current state). A competitor,
**eephus.io**, tracks 453 DSL + 525 complex players and puts a DSL kid at #36
overall on their board; grassroots scouting accounts (e.g. Seed Stage Scouting)
are building followings on exactly this cohort. So there is a genuine coverage gap
and a genuine audience.

**But the honesty bar is what makes this a ValuCast feature instead of a hype
feed.** At 17yo, in 40–200 PA of DSL/complex ball, any *value number* or
*percentile* is speculative to the point of being misleading — it is precisely the
survivorship-biased noise that ValuCast's whole grammar (numbers reproducible from
a committed artifact, honest sample floors, no straw-man consensus) exists to
refuse. Two hard consequences shape the plan:

1. **The default Phase-B surface carries NO value number and NO rank** — stat
   lines, age-vs-level context, a watchlist, and explicit "too early to price"
   labels, in the spirit of a ProspectSavant-style data page that presents the
   data without asserting a rank. A value number appears **only if** the spike
   finds defensible signal (it almost certainly will not at these sample sizes),
   and even then behind the same min-sample discipline the rest of the site uses.
2. **No base-rate claims.** The plan forbids "X% of elite 17yos hit" framing
   anywhere — that is the survivorship trap the competitor account is
   demonstrating. The cohort is presented as *watch-list context*, never as an
   outcome prediction.

The spike exists so we make this call on **measured facts** (does the API even
serve these players; do they have resolvable ids; do our boards rank them; does
our identity layer survive them at scale) instead of on the competitor's framing.

## Current state

Verified against the live files at `f60b8545`. Read each cited line yourself before
building on it.

### The affiliated-MiLB fetch stops at Low-A — the whole reason the cohort is absent

- **`scripts/refresh_milb_season_stats.py:SPORT_LEVELS` (line 20-25)** is
  `{11:"AAA", 12:"AA", 13:"A+", 14:"A"}`. **There is no Rookie / complex / DSL
  sportId anywhere in the pipeline** — a repo-wide grep for `sportId` beyond this
  map finds only MLB (`sportId=1`, `fetch_mlb_history_seasons.py:39`) and this
  affiliated block. Stateside complex ball (FCL/ACL) is **sportId 16** and the
  Dominican Summer League is (per one probe-target the spike must CONFIRM, not
  assume) **sportId 17** — **neither is fetched**, so those players never enter the
  dynasty layer, never reach the universe. This is a pure source-coverage gap, not
  a filter — the extend-probe starts here. (`prospects/universal.py:1028` and
  `prospects/index.py:177` both state it in prose: "Complex-league and rookie-ball
  prospects remain outside the statistical scope"; it is `docs/universal-prospect-model.md`
  "Next Research Blocker #1".)
- **A second, redundant level gate exists in the model** even if raw rows were
  fetched: `prospects/universal.py:LEVEL_CODE` is `{"A","A+","AA","AAA"}` only, and
  `raw_input_builder._eligible_current_row` hard-restricts `level in
  {"A","A+","AA","AAA"}` — so a DSL/CPX/ROK row would be silently excluded from the
  trained model too. This is *why the separate-artifact design is clean*: the value
  model already fails-closed on these levels, so a stat-only surface that never
  touches the model is the path of least resistance.
- **`rank_v1.py` already carries partial DSL/CPX/ROK awareness** in its non-statistical
  pedigree fallback (`PEDIGREE_LEVEL_BASELINE_AGE` includes `"DSL":18, "CPX":19,
  "ROK":19`; `milb_translation`/`availability`/`forward_validation` treat DSL as the
  lowest tier). This is a *latent* path, not an active surface — the memo should note
  it so nobody assumes the cohort is entirely un-modeled, but Phase B must NOT lean on
  it to manufacture a value number (that would reintroduce a speculative rank).
- **The fetch idiom to mirror in Phase B** (do NOT reinvent): `_fetch_splits`
  (line 76-104) builds a `urllib.request.Request` against
  `https://statsapi.mlb.com/api/v1/stats?...` with `sportIds=<id>`,
  `playerPool=ALL`, `limit=10000`, and a `User-Agent` header. `write_milb_season_stats`
  (line 304-310) does the **atomic write** (`.tmp` + `os.replace`), guarded by
  `_assert_not_tiny_refresh` (line 288-302, a `max(500, prior*0.5)` floor with a
  `VALUCAST_SKIP_MILB_TINY_GUARD=1` escape hatch for legit small windows).
  `_normalize_name` (line 28-32) is the NFKD-strip + lowercase name normalizer —
  the accent-heavy DSL names make this **load-bearing** (see spike Q4).

### The universe identity contract will HARD-FAIL on unresolved ids or twins

- **`prospects/universe.py:identity_key(mlbam_id, role)` (line 164-167)** returns
  `(str(mlbam_id), role)` or **`None`** when `mlbam_id in (None, "")`. In
  `build_universe` (line 218-244), a `None` key increments `missing_identity_count`
  and the player is skipped; a repeat key appends to `duplicate_keys`.
- **The fail-hard gate (line 265-271):** if `missing_identity_count or
  duplicate_keys`, `build_universe` **raises `ValueError("invalid ValuCast prospect
  universe (...)")`.** This is the crux of the decision gate: **you cannot naively
  add a cohort with unresolved mlbam ids or twin-name duplicate `(id, role)` keys —
  it would crash the entire daily universe build.** Note the leniency asymmetry
  downstream: `prospects/rank_v1.py` re-derives the same key but on a dup **logs +
  `continue`s** (drops the second row) rather than raising (line 1928/1960), yet its
  publication gate still sets `public_migration_ready: False` and blocks promotion
  when `duplicate_keys`/`missing_mlbam_count` is non-zero (validation, line ~1832 /
  2107). So a collision doesn't just crash — even where it doesn't crash, it blocks
  the public flip. Phase B's ingest MUST either (a) resolve mlbam ids at >95% and
  de-collide twins before the universe sees them, or (b) route the cohort to a
  **separate stat-only artifact** that never enters `build_universe` (the preferred
  design — see Phase B sketch).
- **`MAX_PROSPECT_AGE = 25` (line 21):** 17yo DSL players clear the age gate, so age
  is not the blocker — coverage is. Membership is **model-owned** (`source_policy.kind
  = "valucast_model_universe"`, line 285-292; `external_rankings_used: False`), so a
  new cohort is a source-ingest decision, not a board decision.

### Our consensus boards do NOT rank this cohort — so the model-vs-consensus framing does not apply

- **The consensus join is NAME-BASED and depth-limited.**
  `scripts/build_sts_consensus_snapshot.py` (docstring line 11-14): "Join is
  name-based (STS carries no mlbam)… keyed by mlbam_id (str)", building a
  `normalized_name -> {role: mlbam_id}` index (line 61-72) **from the already-mlbam-keyed
  affiliated universe**. A player who is not already in that universe **cannot be
  joined** → no consensus record. The snapshot even asserts
  `matched_to_mlbam >= 1800` (line 146) — the consensus universe is ~1,800
  affiliated players, not the teenage complex cohort.
- **Board depth stops well above this cohort.** `prospects/consensus_gap.py`
  (line 51-58) caps gaps at `MAX_VALUCAST_RANK` (top ~300); the PL board is
  `prospectslive_top600.csv` (line 69). A gap/AOTC claim requires **`>= 3` public
  boards** (`ahead_of_consensus.py` guards, line 12; `FEATURED_MIN_BOARDS`). A DSL
  17yo appears in **zero** of these boards.
- **This empty-consensus path is already exercised in production, not theoretical.**
  In the live `valucast_prospect_rank_v1.json`, **255 of 2,831 board rows (~9%)
  carry no `source_ranks` at all** — `rank_v1.py:448` only sets the key `if
  source_ranks:`, and the template gates the whole external-board section on `{% if
  row.source_ranks %}` (`player_detail_dynasty.html:481`), so a zero-coverage player
  renders no external section, no median, no AOTC chip — by construction. `MIN_BOARDS
  = 2` (`ahead_of_consensus.py:42`) makes an "ahead of consensus" claim structurally
  impossible below 2 boards, and `FEATURED_MIN_BOARDS = 3` for a badge.
- **DSL/complex players ALREADY appear as `unmatched` in the raw board exports** — so
  we know empirically they fall into the empty path. ProspectsLive's raw
  `prospectslive_top600.csv` carries **36 "CPX" + 32 "DSL"** teenage rows (e.g.
  16–18yo international names); **all landed in the snapshot's `unmatched` list**
  because there is no mlbam-keyed ValuCast row to join them to. HKB's source carries
  **61 "ROK"** rows, likewise unmatched. The boards' *effective* universe (after the
  name→mlbam join against ValuCast's own affiliated board) is A-through-AAA; the live
  board level breakdown is `A+:857, A:814, AA:685, AAA:475` — **zero ROK/CPX/DSL.**
- **Consequence for what we can honestly display:** for this cohort the **consensus
  column is empty**, so the "ahead of consensus" / `/gaps` / AOTC framing — the
  spine of the existing prospect product — **simply does not apply.** Phase B must
  NOT show a consensus comparison, a divergence badge, or an AOTC-style "ValuCast
  vs the field" claim for these players (there is no field). This is a *display*
  consequence the spike confirms with production data, not an opinion.
- **The per-source-rank prohibition still binds** (`ahead_of_consensus.py`
  `_public_source_ranks` at line 97-105 drops proprietary signals; the site shows
  aggregate median + board count only, never a per-source third-party rank). Phase
  B shows **no** external rank for this cohort either — there is none, and even if
  a grassroots list existed we would not republish per-source ranks.

### There is no `scratch/` directory yet — the spike creates it, and it stays out of git

- A repo-wide look finds **no `scratch/` dir**. The `.gitignore` (verified at
  `f60b8545`) ignores agent/test scratch (`.tmp-tests/`, `tmp*/`, `_qa/`, etc.) and
  the plate-discipline pixel cache, but **does not yet ignore `scratch/`.** So the
  spike's Step 0 adds `scratch/` to `.gitignore` (one line) BEFORE writing any probe
  script there, so nothing under it is ever stageable. The spike scripts live in
  `scratch/`, are throwaway, and are never committed (Invariants).
- The **pytest byproduct** to restore after any full-suite run is
  `data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json`
  (present at `f60b8545`) — `git checkout --` it; NEVER stage it.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Drift baseline | `git log -1 --format=%h` | `f60b8545` (or re-verify excerpts) |
| Confirm the level map still stops at A | `python -c "import scripts.refresh_milb_season_stats as m; print(m.SPORT_LEVELS)"` | `{11:'AAA',12:'AA',13:'A+',14:'A'}` (no Rookie) |
| Confirm the universe fail-hard identity gate exists | `python -c "import prospects.universe as u; print(u.identity_key(None,'hitter'), u.MAX_PROSPECT_AGE)"` | `None 25` |
| Confirm consensus is name-based/mlbam-keyed | `python -c "import pathlib; print('name-based' in pathlib.Path('scripts/build_sts_consensus_snapshot.py').read_text()[:800] or True)"` | truthy (or read the docstring) |
| Spike probe: DSL/complex rosters + stats (Step A1) | `python scratch/spike_dsl_probe.py --season 2026` | prints coverage/id/sample tables, writes `scratch/spike_dsl_findings.json`, no exception |
| Full suite (only if Phase B runs) | `python -m pytest -q` | pass count ≥ current baseline, 0 fail; then restore the byproduct |
| Restore pytest byproduct | `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json` | file back to HEAD |
| Phase-A "no product code" proof | `git status --short` | shows ONLY `.gitignore` (+scratch line) and `docs/specs/2026-07-1x-dsl-complex-coverage-spike.md` staged; `scratch/*` untracked & ignored |

## Phase A — the feasibility SPIKE (the first and possibly only deliverable)

**Phase A writes NO product code.** It writes throwaway probe scripts to `scratch/`
(gitignored), hits the live StatsAPI, and produces one committed artifact: the
**decision memo** at `docs/specs/2026-07-1x-dsl-complex-coverage-spike.md`. The memo
answers all five spike questions with measured numbers and renders an explicit
gate verdict (PASS → Phase B scope; FAIL → STOP, with the reasons).

### Step A0: Create the scratch sandbox and confirm the baseline

```
# add scratch/ to .gitignore (one line) so nothing under it is ever stageable:
#   scratch/
mkdir -p scratch
python -c "import scripts.refresh_milb_season_stats as m; print(m.SPORT_LEVELS)"   # {11..14}, no Rookie
python -c "import prospects.universe as u; print(u.identity_key(None,'hitter'))"    # None
```
**Verify**: `.gitignore` contains a `scratch/` line; `git status --short` shows
`scratch/` is NOT listed (ignored). If `scratch/` is already tracked or the level
map already carries a Rookie id, someone landed here first — STOP and reconcile.

### Step A1: Probe the API — does StatsAPI serve DSL + complex rosters, stat lines, and game feeds? (Spike Q1)

Write `scratch/spike_dsl_probe.py` mirroring `refresh_milb_season_stats._fetch_splits`
(User-Agent Request, timeout, `sportIds` param). **Extend-probe from the map's edge**
(the map stops at 14/A): stateside complex (FCL/ACL) is **sportId 16**; DSL is
**believed to be sportId 17** — the spike must CONFIRM this, not hard-code it. Probe
precisely and record what actually distinguishes DSL from FCL/ACL in the API:

1. **Teams endpoint** — enumerate the leagues/teams under BOTH candidate sport ids to
   see how the API separates DSL from the domestic complex leagues:
   `https://statsapi.mlb.com/api/v1/teams?sportId=16&season=2026` and
   `...sportId=17&season=2026` (record each team's `league.id`/`league.name` and
   `parentOrgId`/`parentOrgName`, and which sportId actually returns DSL teams).
   **The memo must state the concrete discriminator** — whether DSL is a distinct
   `sportId` (17) vs. FCL/ACL (16), or a `league.id` split within one sportId, and
   whether a `leagueId` filter is needed on the stats call. (Report the observed
   field; do not guess.)
2. **Stats endpoint** — pull hitting + pitching season splits at BOTH Rookie sport
   ids:
   `https://statsapi.mlb.com/api/v1/stats?stats=season&group=hitting&sportIds=16&season=2026&playerPool=ALL&limit=10000`
   (and `sportIds=17`, and `group=pitching`). Record: how many players per sportId;
   do the splits carry `player.id` (mlbam), `team`, `league`, `stat.age`, PA/AB; can
   DSL be separated from FCL/ACL via the `league`/`team`/`sportId` on each split.
3. **Game feed** — pull one Rookie-level game's live feed
   (`https://statsapi.mlb.com/api/v1.1/game/<gamePk>/feed/live`, gamePk discovered
   via a Rookie-level `schedule?sportId=16` call) and confirm whether `allPlays`
   exist (relevant only if a future pitch layer is ever considered — **not** Phase B).

Record every count and field-presence rate to `scratch/spike_dsl_findings.json`.

**Verify**: the probe prints a table of {level bucket (DSL / FCL / ACL / other
Rookie), player count, % with mlbam id, PA distribution} and writes the findings
JSON, with no exception. **STOP-and-reconcile** if the Rookie stats endpoint returns
nothing or the shape differs from the affiliated splits shape (the memo can't be
written on a guess).

### Step A2: Sample sizes — what PA distributions exist for the 17yo cohort? (Spike Q2)

From the Step A1 splits, compute the **PA (hitters) / IP or BF (pitchers)
distribution for the 17-and-under and 18-and-under cohorts** at each Rookie bucket:
min / p25 / median / p75 / max, and the count clearing plausible display floors
(e.g. ≥ 40 PA, ≥ 80 PA). This quantifies exactly how thin the samples are — the
evidence base for the "no value number / too early to price" default. Record the
distribution in the findings JSON and the memo.

**Verify**: the memo carries a real PA-distribution table (not adjectives). If the
median 17yo PA is (as expected) very low, that is a *finding that supports the
no-number default*, not a failure.

### Step A3: Do ANY of our consensus boards rank these players? (Spike Q3)

Load the committed consensus/board artifacts (read-only) and check, by the
**name-based** join the boards actually use (`build_sts_consensus_snapshot.py`
`normalized_name` index), how many of the Step-A1 Rookie players appear in ANY
board (STS, PL top-600, HKB, Pipeline). Expectation from Current state: **≈0**.

**The memo must state the display consequence explicitly:** if boards don't cover
the cohort, the consensus column is empty, so **the model-vs-consensus / AOTC /
`/gaps` framing does not apply** and Phase B shows no consensus comparison,
divergence badge, or "vs the field" claim for these players. (If, surprisingly, a
board *does* rank some, the memo records how many and which — but per-source ranks
are still never republished.)

**Verify**: the memo reports the measured board-coverage count for the cohort and
the resulting "what we can honestly display" conclusion.

### Step A4: Identity resolution at scale — mlbam ids + twin collisions (Spike Q4)

This is the **gate-critical** probe, because `universe.build_universe` **raises** on
unresolved ids or duplicate `(mlbam_id, role)` keys (`universe.py:265-271`).

1. **mlbam resolvability**: from Step A1, what fraction of Rookie/DSL players carry a
   usable `player.id` on the stats split? (Record the exact %.) Players without one
   would be dropped by `identity_key` → `None` — or, if force-added, crash the
   build.
2. **Twin collisions at scale**: apply the canonical normalizer —
   `prospects/raw_input_builder._normalize_name` (the one that strips Jr/Sr/III
   suffixes + accents + apostrophes; there are **three divergent `_normalize_name`
   implementations** in the repo, and this is the one Phase B must reuse, NOT
   reinvent) — to the cohort and count **normalized-name collisions**: distinct
   mlbam ids sharing a normalized name, both within the Rookie cohort and against
   the existing affiliated universe. DSL rosters are accent-heavy and share common
   Latin surnames, so this is where collisions concentrate. The "twin guard" in this
   repo IS the `(mlbam_id, role)` composite key (per the milb-translation design
   doc: "MLBAM-keyed only; never name-keyed — reuse the existing (mlbam_id, role)
   selection / twin guard"). The memo must report the **collision rate** and whether
   the composite keeps twins distinct (it does, *iff* mlbam ids resolve — two twins
   with distinct ids are distinct keys; two rows for the SAME id are the real dup
   risk that would raise `build_universe`).
   - **Flag the weakest existing guard as a Phase-B blast-radius note (do NOT edit
     it in the spike):** the **HKB and Pipeline** consensus builders
     (`build_hkb_consensus_snapshot.py:39-55`, `build_pipeline_consensus_snapshot.py:38-55`)
     use a **plain first-seen `normalized_name -> mlbam_id` index with NO role/team
     check** — "first name match wins." At today's ~600–1,000 affiliated volume this
     is benign; adding 1,000+ international teenagers who share common Spanish-language
     names across orgs is exactly the collision scenario it does not guard. The
     FanGraphs builder already solved this with **org-corroboration** (same normalized
     name AND same org, else no match — `build_fangraphs_fv_snapshot.py:92-159`). The
     memo must record whether a Phase-B cohort would ever reach the HKB/Pipeline
     name-join (it should NOT, if the cohort stays in the separate stat-only artifact
     off the consensus path) — and if it ever would, the org-corroboration guard is
     the required pattern to copy, as its own follow-up, before ingest.
3. **Universe blast radius**: state plainly whether these players *should* enter
   `build_universe` at all, or whether Phase B should route them to a **separate
   stat-only artifact** that never touches the universe/rank/consensus path (the
   preferred design if resolvability is imperfect or collisions are material — it
   sidesteps the fail-hard gate entirely).

**Verify**: the memo carries the measured mlbam-resolvable % and the
normalized-name collision count/rate, and a clear recommendation on universe-ingest
vs. separate-artifact.

### Step A5: Does our value model even apply? (Spike Q5)

State, from A2's sample sizes and the model's existing floors (`prospect_percentiles`
100 PA / 20 IP discipline; the peak-projection sample-reliability fields), whether
the value model can produce a *defensible* number for a 17yo with ~40–150 PA of DSL
ball. Expected answer: **no — this is a stats + watchlist surface, not a valuation
surface.** The memo records this as the justification for the no-value-number
default. If (unexpectedly) a defensible signal exists, the memo says exactly what
and at what sample floor — but the burden of proof is on the number, not on its
absence.

### Step A6: Write the decision memo + render the GATE verdict

Write `docs/specs/2026-07-1x-dsl-complex-coverage-spike.md` (match the existing
`docs/specs/` memo grammar, e.g. the 7/8 retention memo). It contains:
- **Findings** for Q1–Q5, each with the measured numbers from A1–A5.
- **The base-rate skepticism note**: explicitly no "X% of elite 17yos hit" claim;
  the cohort is watch-list context, not an outcome prediction (the survivorship
  trap the competitor account demonstrates).
- **The Decision Gate verdict** (below), computed from the recorded numbers, with a
  PASS/FAIL for each criterion and an overall verdict.
- If PASS: the **exact Phase B scope** the numbers authorize (universe-ingest vs.
  separate-artifact; which levels; the sample floor for showing a stat line).
- If FAIL: the reason(s) and the recommendation to STOP.

**Verify**: `git status --short` shows ONLY `.gitignore` and the memo staged;
`scratch/*` is untracked/ignored; no product code changed. **This is a complete
Phase-A deliverable** — whether or not Phase B runs.

## DECISION GATE (must be written into the memo; Phase B runs only if ALL pass)

The executor STOPS with the memo unless every criterion below is met by the
**measured** spike numbers. These are pre-registered so the executor can stop on
sand instead of building on it. (Thresholds are the reviewer's calls; tune only in
the memo, with the data, never silently.)

1. **mlbam resolvability > 95%** of the cohort we would surface (per A4.1). Below
   this, the universe/identity path is unsafe and the cohort must be a separate
   stat-only artifact (which is still a valid Phase B *if* the other criteria pass)
   — or STOP.
2. **Rosters + stat lines are actually served** by StatsAPI at the Rookie level with
   `player.id`, `team`/`league`, `age`, and PA/IP present (per A1) — i.e. the data
   exists and is fetchable with the `refresh_milb_season_stats` idiom.
3. **Identity collisions are manageable**: after `_normalize_name`, the
   `(mlbam_id, role)` composite keeps twins distinct (distinct ids), and any
   same-id duplicate rows are dedupable — i.e. ingesting the cohort would NOT raise
   in `build_universe` (per A4.2/A4.3). If collisions are unmanageable within the
   existing guard, either route to the separate artifact or STOP.
4. **A sample floor exists** at which a stat line is honest to show (per A2/A5) — and
   the cohort has a non-trivial number of players clearing it. If essentially no one
   clears any honest floor, there is nothing to show yet — STOP (revisit next
   season).
5. **The display stays honest under the empty-consensus reality** (per A3): Phase B
   shows no consensus/AOTC/divergence framing for the cohort, no value number by
   default, and no base-rate claim. If the only way to make the surface
   "interesting" is to add a speculative rank, that violates the honesty frame —
   STOP.

**If any criterion fails → STOP with the memo. That is a successful outcome.**

## Phase B — the gated MINIMAL build (SKETCH ONLY; execute only on a PASS)

> This is a **sketch**, not step-by-step build instructions. On a PASS, the executor
> (or a follow-up plan) fleshes these into steps using the memo's authorized scope
> and the `refresh_milb_season_stats.py` / `StatcastStore` / card-context idioms
> that plan 023 documents. **Default to the smallest honest surface.**

- **Universe/ingest scope (memo-authorized):** the **preferred design is a SEPARATE
  stat-only artifact** (e.g. `data/prospects/raw/rookie_complex_stats.json` +
  `data/models/valucast_rookie_watchlist.json`) built by a new
  `scripts/refresh_rookie_complex_stats.py` that mirrors `refresh_milb_season_stats`
  (User-Agent Request, atomic `.tmp`+`os.replace`, a tiny-refresh guard, the sportId
  16/17 + DSL/FCL/ACL discriminator the spike found) and **reuses the canonical
  `prospects/raw_input_builder._normalize_name`** for names (not a new normalizer).
  This artifact **does NOT feed `build_universe` / `rank_v1` / the consensus join** —
  it sidesteps the fail-hard identity gate AND the redundant model-level gate
  (`universal.LEVEL_CODE` / `_eligible_current_row` already reject non-A-to-AAA
  levels), keeping the cohort out of the value/rank/AOTC machinery entirely with no
  change to any existing guarantee. Only if the gate found >95% resolvability *and*
  the reviewer explicitly wants them in the universe would they be routed through
  `identity_key` — and even then as no-value rows, and only after the
  `MIN_CURRENT_SAMPLE` floors and the HKB/Pipeline name-join guard are reconsidered
  for the international-teenager volume.
- **Card / surface:** a stat-line + age-vs-level context surface (a "Complex &
  International (Rookie ball)" watchlist page or card section), presenting: name,
  org, level (DSL/FCL/ACL), age, the raw stat line, and an age-vs-level context
  line — **no value number, no rank, no percentile bar, no consensus comparison.**
  Every row carries a "too early to price" / "watch-list, not a valuation" label,
  mirroring how a ProspectSavant-style page shows data without asserting a rank.
  `as_of` provenance line, network-free reader (fetch lives only in the build
  script), fail-soft (missing artifact → section absent).
- **Search inclusion:** add the cohort to the site search index so a user can find
  a named DSL/complex kid — but the result routes to the stat-only surface, never to
  a value/rank card. (If a name collides with an affiliated player, the existing
  `(mlbam_id, role)` disambiguation governs.)
- **Explicit non-goals (V1) — hard lines:**
  - **No value number, no 0–150 score, no rank** for the cohort. Ever, in V1.
  - **No percentile bars below the sample floor** (and realistically no percentile
    bars at all in V1 — the cohort is too thin and has no honest peer pool yet).
  - **No board / leaderboard page**, no `/dsl` ranked route, no "top DSL prospects"
    ordering (that is the eephus.io framing the honesty frame rejects for V1).
  - **No consensus / AOTC / `/gaps` / divergence framing** for the cohort (there is
    no field to compare against — A3).
  - **No base-rate / survivorship claim** anywhere ("X% of elite 17yos…").
  - **No exit-velocity / pitch-level metric** (out of scope; a separate future
    question, and impossible-at-Rookie the same way it is at AA per plan 023).
  - **No push** — reviewer gates the deploy.

## Invariants (Phase A and Phase B)

- **Serving is network-free.** All network lives in `scratch/` probe scripts (Phase
  A) and in build scripts (Phase B, the `refresh_milb_season_stats` idiom). No
  request-time fetch on Render — the reader reads a committed artifact.
- **Spike scripts live in `scratch/` and are never committed.** Step A0 adds
  `scratch/` to `.gitignore` first. The only Phase-A commit is the `docs/` memo (and
  the one-line `.gitignore` edit).
- **NEVER `git add -A` / `commit -am` / `git stash`.** Stage each in-scope file
  explicitly by path (Phase A: `.gitignore` + the memo; Phase B: the new
  script/reader/artifact/tests/template, each by path).
- **pytest byproduct restore.** After any full-suite run, `git checkout --
  data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json`.
  Never stage it. Never stage untracked `data/dd/*`.
- **Targeted suites during work**; the full suite is the final gate (Phase B only —
  Phase A ships no code, so Phase A's "test" is the memo + the `git status` clean
  check).
- **Frozen files untouched** — `prospects/ahead_of_consensus.py`,
  `scripts/build_ahead_of_consensus_scorecard.py` (pre-registered AOTC scoring,
  ~7/13 unlock). This plan reads consensus surfaces read-only in Phase A and does
  not touch them in Phase B (the cohort deliberately never enters the consensus
  path).
- **No per-source third-party ranks** — the site shows aggregate median + board
  count only; the cohort shows no external rank at all (there is none).
- **Do NOT push** — master auto-deploys valucast.app; the reviewer gates the push.

## Done criteria

**Phase A (always):**
- [ ] `scratch/` is gitignored; probe scripts wrote findings; no product code changed
      (`git status --short` shows only `.gitignore` + the memo).
- [ ] The memo answers Q1–Q5 with **measured numbers** (API coverage, PA
      distributions, board-coverage count, mlbam-resolvable %, normalized-name
      collision rate) — not adjectives.
- [ ] The memo renders the **Decision Gate** with a PASS/FAIL per criterion and an
      overall verdict, and (on PASS) the exact authorized Phase-B scope, or (on FAIL)
      the reasons + STOP recommendation.
- [ ] The memo explicitly records the base-rate/survivorship prohibition and the
      empty-consensus display consequence.

**Phase B (only if the gate PASSED):**
- [ ] The cohort surface carries **NO value number, NO rank, NO percentile bar, NO
      consensus/AOTC framing, NO base-rate claim** — stat lines + age-vs-level
      context + watchlist + "too early to price" labels only.
- [ ] The cohort is built by a new `refresh_*`-idiom script (User-Agent Request,
      atomic write, tiny-guard) into a **separate stat-only artifact** that does NOT
      feed `build_universe`/`rank_v1`/the consensus join (unless the gate explicitly
      authorized universe ingest at >95% resolvability).
- [ ] Serving is network-free (reader imports no network lib); fail-soft (missing
      artifact → section absent); `as_of` provenance shown.
- [ ] Search includes the cohort, routing to the stat-only surface.
- [ ] `python -m pytest -q` passes (≥ baseline count, 0 fail); byproduct restored.
- [ ] Frozen files untouched (`git diff --stat` empty for them).
- [ ] `plans/README.md` status row updated.

## STOP conditions

- **The gate fails on any criterion** — STOP with the memo. Do NOT build a smaller
  "at least ship something" surface on failed data; the memo IS the deliverable.
- **Anyone attaches a value number, rank, or percentile to the cohort in V1** —
  violates the no-value-number default. STOP (or, if the gate explicitly authorized
  a number at a stated floor, hold to exactly that floor and no further).
- **Any "X% of elite 17yos…" / survivorship / base-rate claim appears** anywhere in
  the memo, the card, or copy. That is the exact trap this plan exists to refuse —
  STOP and remove it.
- **The cohort is about to enter `build_universe` / `rank_v1` / the consensus join
  without >95% mlbam resolvability and de-collided twins** — it would crash the
  daily build (`universe.py:265-271` raises). STOP; route to the separate stat-only
  artifact instead.
- **A consensus / divergence / AOTC "vs the field" badge is about to render for a
  cohort with no board coverage** — there is no field. STOP.
- **The StatsAPI Rookie-level shape differs materially from the affiliated splits
  shape** (no `player.id`, no per-player `league`/`team`, no age) such that the memo
  can't be written on measured fact — STOP and reconcile against a live pull before
  guessing.
- **A `scratch/` probe script is about to be committed**, or `git add -A`/`stash` is
  about to run — STOP; stage only the `.gitignore` line and the memo.
- **Effort creep in Phase B** toward a board page, a ranked list, or a value model
  for the cohort — STOP; those are explicit non-goals. The honest surface is small
  by design.

## Non-goals (restated for emphasis)

- No value/score/rank for the cohort in V1.
- No percentile bars below sample floors (realistically none at all in V1).
- No board / leaderboard / ranked page (`/dsl` etc.).
- No consensus/AOTC/`/gaps`/divergence framing for the cohort.
- No base-rate/survivorship claims.
- No pitch-level / exit-velocity metrics.
- No push.

## Notes for the reviewer

- **The spike is the risk control.** Every MEDIUM risk (identity blow-up, speculative
  numbers, survivorship framing) is converted to a measurable pass/fail *before* any
  product code exists. If the numbers say "unservable cleanly," the correct,
  non-embarrassing outcome is a memo and no build.
- **The honest surface is deliberately unglamorous.** eephus.io's ranked DSL board is
  the thing the honesty frame rejects for V1; matching it would mean asserting ranks
  on 40-PA 17yos. The ValuCast move is coverage *without* a false price — which is
  also, not coincidentally, a much smaller build.
- **The separate-artifact design is the safe default** even on a PASS: it keeps the
  cohort entirely out of the value/rank/consensus/AOTC machinery, so nothing about
  the existing product's guarantees changes.
