# Plan 030: The Forward Ledger — a pre-registered, commit-dated forward accuracy benchmark: dated cohorts, frozen scoring rules, ValuCast scored against the aggregate public consensus, standings that resolve forward on a published schedule (registration document + S1 cohort registry + S2 scoreboard roll-up)

> **Plan-number note (read first).** Registered as plan 030; the 029 slot was
> already held by plate-discipline-leaders. This document is titled and registered
> as **Plan 030** (`plans/030-forward-ledger.md`) throughout; the registration
> semantics below are unaffected by the filename.

> **Executor instructions**: This is a REGISTRATION document as much as a build
> plan. PART A is the frozen, commit-dated registration — the product itself: it is
> published *before any outcome is known*, and once committed its scoring rules do
> not change (a metric/dial change is a NEW dated registration, never an edit).
> PARTS B and C are the S1/S2 builds that emit the standings artifacts. Run every
> verification command and confirm the expected result before moving on. If a STOP
> condition occurs, stop and report — do not improvise. When done, update the status
> row in `plans/README.md` unless a reviewer told you they maintain the index.
>
> **This plan points 028-grade discipline OUTWARD.** It formalizes what the
> receipts/claims machinery already does into a public forward benchmark. The
> non-negotiable posture: the scoreboard **inherits frozen protocols by
> redeclaration, never by modifying or importing them**. It reads committed
> ARTIFACTS; it re-derives nothing the frozen modules own.

## Status

- **Priority**: **P2** (accountability surface / product moat — a pre-registered,
  commit-dated forward benchmark is the uncontested "call-level accountability" lane
  the product strategy readout named). Not a correctness fix; a credibility
  instrument.
- **Effort**: **M** across S1+S2 (this session builds S1+S2; S3 CI wiring and S4
  public page are separate sessions). Registration text (PART A) is the load-bearing
  artifact; the builders are mechanical roll-ups.
- **Risk**: **MEDIUM**. Sharp edges: (1) **leaking a per-source third-party rank**
  into a public-repo artifact (invariant 1 — median + board_count only); (2)
  **re-implementing a frozen protocol** instead of rolling it up (invariant —
  redeclare, never import the frozen scorecard / ledger modules); (3) **a role field
  or pitcher/hitter split** on a standings artifact (invariant — the registered
  one-look protocol from plan 028 forbids it); (4) **back-dating a cohort** (the
  single practice this benchmark exists to reject).
- **Depends on**: the SHIPPED gaps claim ledger (plan 017,
  `data/models/valucast_gaps_claim_ledger.json`), the daily
  `valucast_prospect_rank_v1/<date>.json` archive, and the outcome backtest artifact
  (`valucast_prospect_outcome_backtest.json`). Composes with — never modifies — the
  frozen AOTC scorecard.
- **Category**: accountability / public benchmark (new surface).
- **Planned at**: commit `33bee4de`, 2026-07-16. Brief:
  `2026-07-16-plan030-forward-ledger-brief.md` (repo-grounded against
  origin/master @ 33bee4de).

## Non-negotiable invariants

1. **Roll-up, never re-implementation.** The scoreboard reads committed ARTIFACTS
   (`valucast_gaps_claim_ledger.json`, `valucast_prospect_rank_v1/<date>.json`,
   `valucast_prospect_outcome_backtest.json`). It MUST NOT import
   `gaps_claim_ledger`, `ahead_of_consensus*`, `call_up_receipts`, any frozen
   scorecard, or re-derive their resolutions. Frozen protocols are decoupled by
   **redeclaration**, not import (repo rule; the consensus reconstruction is ported
   verbatim into `prospects/forward_cohort.py`, not imported).
2. **No per-source third-party ranks in any NEW artifact.** A cohort stores VC served
   rank + consensus **median** + **board_count** only — never
   `context_only.source_ranks` or any per-source rank. This is a public repo. The
   `source_ranks` block is read to COMPUTE the median in memory and then discarded.
3. **Quarantine (one-look protocol from plan 028):** no `role` field and no
   pitcher/hitter split of any kind in any emitted standings artifact. The cohort
   registry uses role-BLIND identity (`mlbam_id`). Higher/lower CLAIM-SIDE splits are
   fine (that is claim direction, not player role). The S2 validator ASSERTS the
   role-field absence.
4. **No back-dating.** The registry builder registers a cohort dated TODAY only
   (`registration_date = today`), reading the LATEST committed archive (recording
   `archive_date` explicitly — it may lag `registration_date` by a day). Earlier
   archive dates are never used to synthesize older cohorts.
5. **Never push while a daily-public-data run is queued/in flight** (check
   `gh run list --workflow=daily-public-data.yml --limit 1`). Cron primary 11:30
   UTC, fallbacks 12:20/13:30.
6. **Lead-time citations use the ledger's `resolved_date − claim_date`** — never
   AOTC "days ahead" (three different "days ahead" notions exist; only the ledger's
   is the true claim→event lead time).
7. **Determinism:** bootstrap/permutation seed **29016**, 10,000 resamples,
   percentile **95%** CI; sha256 content hashes over the deterministic JSON body.

---

## PART A — the registration (freeze all of this)

This is the commit-dated registration. Committing it, in a public repo, before any
outcome is known, IS the product. Nothing below is re-tuned in place: a change is a
new dated registration, and prior cohorts run to term under their original rules.

### A1. Purpose and entrants

A forward accuracy benchmark. Entrants at v1:

- **ValuCast** — the served board (public ordinal `rank`).
- **The Aggregate Public Consensus** — the rounded median across external public
  boards with `board_count >= 2`, computed exactly per
  `prospects/ahead_of_consensus.py:97-123 (ported verbatim from
  web/public_snapshot_models.py)`. The reconstruction is REDECLARED in
  `prospects/forward_cohort.py`, never imported: drop the internal sources
  (`cfr`, `cfr_raw`, `milb_perf`, `milb_breakout`) and any `dd_*` key, cap numeric
  ranks at 600, take the rounded median, and define a consensus only when
  `board_count >= 2`. The redeclared consensus additionally drops any dd_-prefixed
  source key (inert today — zero dd_ keys in the archive); if a dd_ source ever
  appears in source_ranks, reconcile this drop with the ledger's own reconstruction
  before trusting adverse-movement splits.

The entrant schema carries an `additional_entrants` slot for future dated public
boards; none enter at v1.

**Statement of independence (verbatim, published with every standings view):**

> *"ValuCast scores are computed without any consensus input; external source ranks
> are carried as context only and never feed the model. This independence is
> validator-enforced."*

The S2 validator adds the enforcement (asserts the attestation string is present and
that no per-source rank leaks into the artifact).

### A2. Registration events

- **Cohort #1: registered 2026-07-16**, boards as-of the latest committed daily
  archive on the registration date. **NO back-dating, ever** — earlier archive dates
  are NOT used to synthesize older cohorts. Public-board coverage jumped **2→5
  boards between 6/13 and 6/30**, so pre-6/30 cohorts would be non-comparable; and
  back-dating is precisely the practice this benchmark exists to reject
  (the **coverage-discontinuity rationale**). This is stated as a discipline feature,
  not a limitation to apologize for.
- **Subsequent registrations: quarterly on the first daily build of Oct / Jan / Apr
  / Jul** (next: **2026-10-01**).
- Each registration freezes, per eligible player: `mlbam_id`, `name`, role-blind
  identity, **VC served `rank`** (the public ordinal, not raw `score`), **consensus
  median**, **board_count**. Plus cohort-level: registration date, `archive_date`
  (recorded separately — may lag by a day), content hash (sha256), protocol version.
- **Board vintages** are captured **prospectively only**, at registration time, as
  cohort-level metadata (a source→date map from the live vintage machinery). Stated
  plainly: **vintages are not reconstructable for past dates from committed data**,
  so no historical vintage claims are made and `board_vintages` is null on any
  back-fill/dev run.

### A3. Eligibility (frozen)

A player enters the cohort **iff `(board_count >= 2)` OR `(VC served rank <= 250)`**.

- Rank-only entrants (`board_count < 2`) have **null consensus fields**. They are
  scoreable on **tier outcomes (A5)** and **ledger claims (A4)**, not on
  consensus-gap metrics.
- The standings **never silently drop** a rank-only entrant. Censored / uncovered
  counts (`rank_only`, and downstream any player uncovered by a given metric) are
  **always reported** alongside every headline.

### A4. Fast layer — inherited claims-ledger protocol + the Anticipation Score

The fast layer rolls up the ALREADY-FROZEN gaps claim ledger. Its dials are cited
verbatim so a reader can verify inheritance — they are **inherited, never restated as
new choices**:

| Dial | Value | Source (frozen) |
|------|-------|-----------------|
| Enrollment min divergence | **25 spots** | `MIN_DIVERGENCE` |
| Gap surface | **3-board gap** | consensus gap board |
| Enrollment VC-rank ceiling | **rank <= 300** | `MAX_VALUCAST_RANK` |
| Consensus-move floor | **10 spots** | `CONSENSUS_MOVE_FLOOR_SPOTS` |
| Model-move floor | **10 spots** | `MODEL_MOVE_FLOOR_SPOTS` |
| Expiry | **60 days** | `EXPIRY_DAYS` |
| Ledger launch | **2026-06-16** | `LAUNCH_DATE` |
| Sides | **higher / lower** | two-sided ledger |

**Anticipation Score (the headline; freeze exactly this):**

- **Scoring pool** = claims with a terminal EXTERNAL resolution only:
  - **Win:** `resolved_by_callup` on the **higher** side, or
    `resolved_by_consensus_move` in the claim's direction → contributes
    **+(resolved_date − claim_date)** days.
  - **Loss:**
    - (i) `resolved_by_callup` **against** a `lower` (fade) claim → contributes
      **−(resolved_date − claim_date)**.
    - (ii) **adverse-at-expiry** — at `expired_unresolved`, the scoreboard recomputes
      consensus from the rank archive at claim_date and at the expiry date; if the
      field moved **>= 10 spots AWAY** from the claim direction, the claim scores
      **−(days to expiry)**; otherwise expiry contributes **nothing** to the median
      (still reported in the funnel).
    - (iii) **adverse-before-retraction** — a `retracted_by_model_move` claim where,
      at the retraction date, the field had ALREADY moved **>= 10 spots away** from
      the claim direction scores as a loss, **−(resolved_date − claim_date)**. This
      closes the "retract at day 59 to dodge the expiry penalty" hole.
  - **Excluded from the median:** **clean retractions** (self-corrections with no
    prior adverse movement) and **open** claims. Both are ALWAYS published in the
    funnel. The **self-retraction rate** (currently **105 / 238** — 28 of which are
    scored as losses under clause (iii); 77 are clean exclusions) is a **mandatory
    companion stat** displayed with the headline. Rationale (state it): the median
    measures what happened when the world resolved the claim; backing off before the
    world resolves earns no credit and hides nothing.
- **Headline = median of the signed pool.** Significance is assessed by the bootstrap
  95% CI against zero; the label reads **"leading, not yet significant"** whenever the
  interval includes zero. A sign-permutation null interval (seed 29016, 10,000
  permutations) is published alongside as context. No p-value is published: a
  sign-permutation p-value is degenerate for low-magnitude-variance pools — identified
  in pre-registration review and removed before freeze. Superiority is never claimed
  inside the band.
- **Honest current state at registration (2026-07-16, computed by the registered
  scoring code against the live ledger):** scoring pool **59** — **31 wins** (4
  call-up resolutions, median lead 11.5 days; 27 consensus-move resolutions, median
  18 days) and **28 losses**, all via the adverse-before-retraction clause (claims
  retracted after the field had already moved >= 10 spots against the claim
  direction). Median signed lead: **+2.0 days**; bootstrap 95% CI **(-6, +13)**. The
  interval includes zero, so the registered label at launch is **"leading, not yet
  significant."** The adverse-at-expiry path has produced 0 losses only because no
  claim has yet reached the 60-day window (earliest possible expiry **2026-08-23**);
  the score remains **provisional** until that first window completes. Of the 105
  self-retractions, 28 are scored as losses under the adverse-before-retraction
  clause; the remaining 77 clean retractions are excluded from the pool and disclosed
  through the self-retraction rate (105/238). This registration publishes a
  not-yet-significant headline knowingly: the metric's first honest reading is the
  point.
- The **whole-funnel table** (open / callup / consensus-move / retracted / expired /
  adverse) is the permanent denominator display. **No survivorship:** a resolved-only
  view is never shown without the funnel.

### A5. Slow layer — frozen outcome definitions (resolve at +4 years)

- **Tier outcomes** `{bust 0.0, role 0.5, star 1.0}` per the committed constants
  (`OUTCOME_TARGET`, `model.py:56`) and thresholds (`universal.py:144-151`), over a
  fixed **4-year post-cohort window** (cite verbatim; do not re-derive):
  - **STAR** = any season with **≥ 450 PA & ≥ .800 OPS** (hitter) / **≥ 120 IP &
    ≤ 3.75 ERA** (pitcher).
  - **ROLE** = reached established (**≥ 300 PA / ≥ 50 IP**) without a star season.
  - **BUST** = otherwise.
- **Forward Brier:** `_multiclass_brier` (`dynasty_backtest.py:90`) on the frozen
  cohort vs the **level-age prior** baseline (`_fit_prior` / `_prior_predict`,
  `PRIOR_K=40`, serialized under the model artifact's `_runtime.prior`). The
  retrospective OOS reference points to cite: **hitters 0.1577 vs 0.1677
  (−5.95%, n=1091)**, **pitchers 0.2218 vs 0.2277 (−2.58%, n=1127)**. NEVER cite the
  +6.36% figure here (different baseline — kNN; different metric — MAE).
- **Rank-skill confirmers at horizon:** **Spearman AND Kendall tau-b** (tie-corrected;
  outcome mass is ~80% bust) of registered ranks vs realized outcome, per entrant, on
  the matched cohort — **dual-reported** as (i) matched intersection and (ii)
  coverage-penalized (uncovered eligible players imputed at the entrant's median
  rank). Terminal continuous outcome (realized WAR at horizon) is registered as a
  definition now, but its ingestion path ships separately (S5, fWAR via FanGraphs
  export). State plainly: **cohort #1's slow layer first resolves ~2030-07** — the
  registration's value is that **the clock starts today**.

### A6. Standing rules

- **Metric/dial changes = a NEW dated registration.** Prior cohorts run to term under
  their original rules. Nothing in a committed registration is edited in place.
- **Whole-board reporting only.** Role-sliced outcome readouts are **withheld** under
  the registered one-look protocol — this is a **discipline feature**, not an
  omission.
- **Every published standings number resolves to a committed artifact** (S3/S4 extend
  the existing CI number-resolution posture).
- **Unresolved / censored are counted and shown, never dropped.**

---

## PART B — S1: cohort registry (this session)

New modules: `prospects/forward_cohort.py` + `scripts/build_forward_cohort_registry.py`.
Artifacts:
- `data/models/valucast_forward_cohort_registry.json` — the append-only registry,
  keyed by `registration_date`.
- `data/prediction_archive/valucast_forward_cohorts/<date>.json` — per-registration
  frozen snapshot.

**Builder core (`prospects/forward_cohort.py`, pure functions):**

- Read the registration-date board from
  `data/prediction_archive/valucast_prospect_rank_v1/<date>.json` (fields confirmed:
  `rank` = served ordinal, `mlbam_id`, `name`, `role`, `context_only.source_ranks`).
- Compute consensus **median + board_count** per row via the REDECLARED
  `_public_source_consensus` semantics (drop `cfr`/`cfr_raw`/`milb_perf`/
  `milb_breakout` and any `dd_*`; rank cap 600; consensus only when board_count ≥ 2).
  **Store only median + count.**
- **Role-blind dedup:** collapse duplicate `mlbam_id` board rows to the **min(rank)**
  row; count the dedup in cohort metadata (a two-way player with hitter + pitcher
  rows shares one mlbam_id).
- Apply **A3 eligibility** (`board_count >= 2` OR served `rank <= 250`); rank-only
  entrants carry null consensus fields; report `consensus_covered` / `rank_only` /
  `deduped` / `eligible_total`.
- **Frozen output schema:**
  `{registration_date, archive_date, protocol_version: "030-v1", content_sha256,
  board_vintages (nullable, prospective-only), eligibility (dials echoed),
  entrants: [{mlbam_id, name, valucast_rank, consensus_rank|null, board_count}],
  counts: {eligible_total, consensus_covered, rank_only, deduped}}`.
  Entrants sorted by (valucast_rank, mlbam_id). `content_sha256` is computed over the
  deterministic JSON body EXCLUDING the hash field.

**Registry builder (`scripts/build_forward_cohort_registry.py`, CLI):**

- Default: register TODAY's cohort into the registry + snapshot, reading the LATEST
  committed archive (no back-dating). `archive_date` recorded separately.
- **Immutability:** a registered cohort is never recomputed. Re-running on the same
  `registration_date` is a **hash-identical no-op**; a drift (recomputed hash ≠
  committed hash) is a **hard error**, never a silent overwrite. Clone the
  `gaps_claim_ledger` immutability-assert + **atomic tmp + `os.replace`** write idiom.
- **`--dev-run <archive_date> --out <path>`:** builds a cohort from any archive date
  to a temp path for testing; it **NEVER touches anything under `data/`** (rejects an
  `--out` inside `data/`), and never writes the registry.
- **Registering cohort #1 for 2026-07-16 is NOT done in this session.** A fresh
  archive lands after the in-flight daily-public-data CI run; the orchestrator runs
  the real registration afterward. This session only builds + tests the machinery and
  dev-runs it against the 2026-07-15 archive to a temp path.

**Tests (`tests/test_forward_cohort.py`):** eligibility edges (exactly 2 boards; rank
exactly 250 vs 251; rank-only null consensus); internal-source + `dd_*` exclusion
from consensus; no `source_ranks` key anywhere in the output (recursive assert);
role-blind dedup (min rank wins, dedup counted); determinism / hash stability;
immutability violation raises; dev-run isolation.

---

## PART C — S2: scoreboard roll-up (this session, after S1)

New: `prospects/forward_scoreboard.py` + `scripts/build_forward_scoreboard.py` →
`data/models/valucast_forward_scoreboard.json`, plus
`scripts/validate_forward_scoreboard.py`.

- **Inputs:** cohort registry + `valucast_gaps_claim_ledger.json` + the rank archive
  (for the A4 adverse-movement derivations — recompute consensus at claim_date and at
  the expiry/retraction dates from the archived `source_ranks`, **aggregate-median
  only, in-memory**; nothing per-source is written out).
- **Outputs:** the Anticipation Score (median, CI, null, provisional flag); the full
  funnel with **claim-side** splits (higher / lower — direction, NOT player role);
  the self-retraction rate; a cohort table (registered / resolved / censored counts);
  protocol version + registration hashes.
- **Validator asserts:** no `role` field / no pitcher-hitter split anywhere in the
  artifact; every headline number has a matching CI field; funnel totals reconcile
  with the ledger's claim count; the independence attestation string is present.
- **Tests:** signed-pool construction against a fixture ledger (win / loss /
  adverse-before-retraction / clean-retraction / open each covered); CI + null
  determinism at seed 29016; validator role-field rejection.

---

## Follow-up sessions (design for them; do NOT build here)

- **S3 (CI wiring):** wire both builders into `run_daily_public_build.py:BUILD_STEPS`
  (after `build_gaps_claim_ledger.py`, currently step #56) + the validators into
  `VALIDATE_STEPS` + the git-add allowlist in
  `.github/workflows/daily-public-data.yml` (currently lines 164-256 + conditionals
  257-271). The artifact/path names in PARTS B/C are chosen so S3 is mechanical. Do
  NOT touch the workflow file in this session.
- **S4 (public page, after S3 + 2 clean nightlies):** a `/scoreboard` fail-soft route
  + template + share card + a `SCOREBOARD_HOLD` gate (start held), plus the public
  methodology page carrying this registration text.
- **S5 (separate):** the fWAR export routine + internal retrospective diagnostic
  (PRIVATE, whole-board only) for the slow-layer continuous outcome.

## Open items for Alex (not blockers for S1/S2)

1. Public display name for the board (working name "The Ledger"; slug `/scoreboard`
   is neutral and rename-safe).
2. Confirm the quarterly registration dates (Oct 1 / Jan 1 / Apr 1 / Jul 1 pattern).
3. S5 (fWAR export routine + internal retrospective diagnostic) scheduling.
4. **Plan-number reconciliation (resolved):** the file is
   `plans/030-forward-ledger.md`, registered as Plan 030; the 029 slot was already
   held by plate-discipline-leaders.

## Amendment rules (registration discipline)

- **A committed registration is immutable.** Any change to a metric, dial, eligibility
  rule, scoring definition, or entrant set is a **NEW dated registration** with its
  own registration date and protocol version. The prior registration's cohorts run to
  term under their original rules. This file's PART A, once committed, is not edited to
  change scoring — only appended to (or superseded by a new plan).
- **Whole-board only.** No amendment introduces a role-sliced or pitcher/hitter-split
  readout on a standings artifact; the one-look protocol is a registered constraint.
- **Every number resolves to a committed artifact.** No standings figure is published
  that cannot be traced to a committed cohort snapshot, the committed ledger, or the
  committed archive.
- **Censored is never dropped.** Every amendment preserves the rule that uncovered /
  unresolved entrants are counted and displayed.

## Done criteria (S1 + S2)

- [ ] PART A registration text committed verbatim (this file).
- [ ] **S1:** `prospects/forward_cohort.py` + `scripts/build_forward_cohort_registry.py`
      build a frozen cohort with the PART B schema; consensus is median + board_count
      only (no `source_ranks` anywhere); role-blind dedup counts; immutability
      no-op/drift-error holds; `--dev-run` never touches `data/`.
- [ ] **S1 tests** (`tests/test_forward_cohort.py`) all green.
- [ ] **S2:** scoreboard builder + validator emit the Anticipation Score (median, CI,
      null, provisional), the full funnel + self-retraction rate, and the cohort
      table; the validator rejects a `role` field and a missing CI/attestation.
- [ ] **S2 tests** all green.
- [ ] No `role` field / no pitcher-hitter split in any emitted standings artifact.
- [ ] Cohort #1 registration is **deferred to the orchestrator** (fresh archive after
      the in-flight CI run) — NOT generated in this session.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- **A per-source third-party rank is about to be written** into any new artifact. Only
  the consensus median + board_count are carried forward. STOP.
- **The builder imports `gaps_claim_ledger`, `ahead_of_consensus*`,
  `call_up_receipts`, or a frozen scorecard**, or re-derives a resolution the frozen
  ledger owns. Redeclare, roll up committed artifacts. STOP.
- **A `role` field or any pitcher/hitter split** appears in a standings artifact. STOP
  (claim-side higher/lower is fine).
- **A cohort is about to be back-dated** — the registry builder registers TODAY only,
  reading the latest committed archive. STOP.
- **The registration text (PART A) is being edited to change a scoring rule.** That is
  a new dated registration, not an edit. STOP.
- **A frozen file would change** (`gaps_claim_ledger.py`, `ahead_of_consensus*.py`,
  `call_up_receipts.py`, any frozen scorecard, `.github/`, anything under `quality/`
  beyond a new validator). STOP.
- **A push is attempted while a daily-public-data run is queued/in flight.** STOP
  (`gh run list --workflow=daily-public-data.yml --limit 1`).

## Non-goals

- **No modification of any frozen protocol.** Inherit by redeclaration; read committed
  artifacts.
- **No back-dated cohorts.** Coverage discontinuity (2→5 boards, 6/13→6/30) makes them
  non-comparable, and back-dating is what the benchmark rejects.
- **No role-sliced standings.** The one-look protocol is registered.
- **No per-source rank publication.** Aggregate median + board_count only.
- **No CI wiring or public page in this session** (S3/S4).
