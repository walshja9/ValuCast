# Audit: Plate-Discipline & AAA Statcast Metric Definitions

**Date:** 2026-07-30. **Scope (owner-set):** metric definitions across A-ball
play-by-play, AAA Statcast, cards and share graphics; foul-tip/swing/whiff/
contact treatment; estimated-zone accuracy vs measured AAA locations;
EV90/HardHit coverage, BBE denominators, missingness by level; sample
thresholds and measured-vs-estimated labels; confirmation that none of it
affects ranks or values. **Read-only** — no fix is implemented in this
commit; per owner instruction, definition fixes happen once at the shared
source **after this audit is reviewed**, and the scoring freeze holds.

Two independent lanes; all evidence at file:line against origin/master. The
paired pixel cache and AAA pitch cache are uncommitted (Actions-cache /
absent), so calibration claims were verified by code inspection plus a
fresh-data spot check (4 unseen AAA game feeds; 7 small read-only requests
total) rather than byte-for-byte recomputation.

## Verdict in one paragraph

No P0: every displayed rate matches its own layer's documented formula, the
`est.` labeling machinery is sound and consistently enforced, thresholds
are enforced everywhere, and **the freeze is confirmed intact** (both
artifacts observe-only; complete consumer inventory is display, archival,
or promotion-blocked offline evaluation, with validators that fail the
build if a promotion flag flips). The real problems are four P1s: a
foul-tip definition split between the two layers under one label; a share
PNG that grades a metric the web card deliberately refuses to grade; a
calibration validity claim quoted for levels it was never measured at; and
a silently 16-day-stale AAA Statcast artifact with no staleness gate and no
visible date — the exact keep-stale pattern the plate-discipline layer was
already hardened against.

## P1 findings (each with its single shared-source fix location)

**F1 — Foul-tip convention split.** Play-by-play classifies a foul tip as
swing+contact (substring "foul" wins in `_is_whiff`,
`prospects/pitch_discipline.py:55-62`); the AAA Statcast layer deliberately
counts it as swing+whiff per Savant (`_WHIFF_DESCS`,
`scripts/build_aaa_statcast_features.py:66-69`; the test at
`tests/test_build_aaa_statcast_features.py:194-209` calls contact-treatment
"the pre-review bug"). Result: the same "Whiff%" label on one AAA hitter's
card carries two different numerators, and the glossary's "share of swings
that miss" fits only one of them. Methodology frames the layers as
differing only in zone *measurement*, never event definitions
(`templates/methodology.html:447-521`). **Owner decision required: pick the
convention.** Savant-align PBP: add `"foul tip"` to `_is_whiff` (one line;
propagates to every PBP surface; note the module's re-baseline warning and
the fixture lock). Or PBP-align AAA: remove `foul_tip` from
`_WHIFF_DESCS`. Either way, state the rule in the glossary
`whiff-percent`/`swstr-percent` entries. Related P2: decide `bunt_foul_tip`
and `foul_pitchout` (absent from the AAA swing set, counted by PBP) at the
same time.

**F2 — Share PNG grades a position-only metric.**
`_prospect_discipline_card_rows` (`app.py:3157-3195`) drops the store's
`positional` flag, so the PNG renderer (`app.py:3563-3572`) colors the
contextual Swing% chip elite/amber/low — presenting a cohort *position* as
a quality grade that the web card renders deliberately neutral
("position only, not a grade", `web/pitch_discipline_store.py:222-246`,
`templates/partials/player_detail_dynasty.html:241,255-263`). Fix: carry
`positional` through and render those chips neutral in the PNG.

**F3 — Calibration validity claim doesn't transfer below AAA.** The
committed 97.5% held-out agreement is real and honestly computed
(deterministic disjoint split, held-out-only scoring, 85% floor genuinely
gates zone shipping; fresh-game reproduction 98.5% on 1,275 unseen pairs) —
but it is measured at AAA, where legacy pixels are effectively a derived
transform of the tracked coordinates (median residual 0.1–0.4 in with a ~1%
gross-outlier tail). AA and A+ zone calls are **100% pixel-calibrated with
zero ground truth** (A: 70.9%; AAA: 0.3%), i.e. the levels the 97.5% is
quoted for are the levels it was never measured at; borderline agreement
degrades to 96.7% within 3 in and 91.4% within 1 in of the zone edge even
on AAA pixels. Fix: record the measurement scope in `build_calibration`
meta (`scripts/build_pitch_discipline.py:400-410`), emit banded agreement
from `calibration_agreement` (`prospects/pitch_discipline.py:312`), and add
the caveat to `templates/methodology.html#plate-discipline`.

**F4 — AAA Statcast artifact silently stale 16 days.**
`valucast_aaa_statcast_features.json` is as_of 2026-07-14: the daily
workflow persists an Actions cache only for plate-discipline paths, so
every run hits the AAA refresher's cold-cache no-op
(`refresh_aaa_statcast.py:357-363`) and the builder keeps the stale
artifact (`build_aaa_statcast_features.py:402-410`; exactly one build ever,
per `data/aaa_statcast_archive/`). No staleness gate exists in
`validate_aaa_statcast_features.py`, and the card never prints the as_of
date — users see 16-day-old "measured" EV with every gate green. Fix:
cache restore/save for the AAA pitch cache in
`.github/workflows/daily-public-data.yml` + a `_staleness_problem` mirror
in `scripts/validate_aaa_statcast_features.py` + surface the date on the
card.

## P2 findings

1. Hardcoded "minimum 300 pitches" caption (`app.py:10025`) duplicates
   `cohorts.min_pitches` — drift risk on retune.
2. Missing-strike-zone policy differs by layer (PBP default 1.5–3.5 ft band
   counted+flagged; AAA excludes the pitch) — methodology note; plus the
   card's near-unreachable `pct=None` fallback mislabels itself "below the
   cohort sample floor" (`player_detail_dynasty.html:269-275`).
3. Glossary Zone% wording vs the coords-only denominator
   (`zone_pitches_with_coords`).
4. No uncertainty propagation on estimated metrics: est. and measured rows
   sort together at 0.1pp on the leaders board, and AAA percentile pools
   mix measured with estimated buckets (69/233) without attenuation.
5. `validate_pitch_discipline.py:93-99` silently passes when
   `zone_metrics_shipped=true` but the agreement value is absent.
6. **EV90 does not exist in the repo** (aspirational doc mention only);
   shipped features are avg_ev/max_ev/hardhit_pct/avg_la. Hard-Hit% uses
   tracked-EV BBE as denominator (excluding null-EV BBE — mildly inflating;
   ~1.6% missingness on a one-day AAA spot check, 0–7% by park), but the
   artifact stores only `n_bip`, not `ev_n`, so per-player EV coverage is
   unauditable from committed data, and the card labels `n_bip` as
   "tracked balls in play" (`player_detail_dynasty.html:340`). Fix: emit
   `ev_n` (`build_aaa_statcast_features.py:298-310`) and fix the label.
7. Calibration train/held split is within-game interleaved rather than
   game-held-out (fresh-game spot check partially covers the gap).

## Checked clean

- Ratio formulas (numerator/denominator) are identical across layers for
  every shared metric; divergences are event-set only (foul-tip family).
- Swing/whiff/contact treatment matches Statcast convention for balls in
  play, fouls, swinging strikes (incl. blocked), missed/foul bunts,
  pitchouts, HBP, automatic balls/strikes — foul-tip family excepted (F1).
- Zone geometry shared (0.83 ft half-width both layers).
- `MIN_PITCHES=300` floor enforced identically on leaders, PNG, card, and
  percentile pools; sub-floor buckets never render.
- `est.` semantics: measured metrics can never carry the tag; missing flags
  fail conservative (default estimated); glossary matches the semantics;
  AAA surfaces never show est. (asserted by test).
- EV is AAA-only everywhere (fetch filter verified against live StatsAPI
  team list; PBP layer hard-forbids EV via validator; methodology
  disclaims EV below AAA); sub-threshold EV values are structurally absent
  from the artifact, not merely hidden.
- Freeze: `observe_only/feeds_value/feeds_rank` false-flags baked into both
  artifacts; zero imports in any rank/value/score path; the one live-ish
  consumer (`cross_role_shadow`) is promotion-blocked with a validator that
  fails the build if any authorization flag flips; the challenger-eval
  consumer pins a frozen git blob and cannot emit a public claim.

## Owner decisions requested before any fix ships

1. F1 convention: Savant-align PBP (foul tip = whiff) or PBP-align AAA
   (foul tip = contact)? (Savant-align matches industry and the third
   pass-through label family; it re-baselines PBP Whiff%/SwStr%/Z-Contact%
   display values — display-only, no rank/value effect.)
2. F4 remediation may reuse the plate-discipline pattern wholesale
   (bootstrap-workflow cache + bounded staleness gate) — confirm.
3. Fix batching: F1–F4 + P2s as one display-layer PR at the shared sources
   named above, tests first, after this audit is approved.
