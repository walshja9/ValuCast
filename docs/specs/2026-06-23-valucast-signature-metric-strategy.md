# ValuCast Signature Metric — Competitive Strategy & Build Plan

**Date:** 2026-06-23
**Status:** Strategy / roadmap (planning — no code yet)
**Origin:** Competitive research + self-benchmark (workflow run w4hn27q44) following the
6/22-6/23 model-improvement sprint (pitcher FIP-ERA shipped; prospect stat-prediction
ceiling and grade-redundancy established).

---

## TL;DR / Thesis

ValuCast does **not** need a new projection engine, and should **not** try to win on raw
accuracy. Prospect statistical prediction has a low, *shared* ceiling (~0.26 correlation on
MiLB→MLB) that every public system hits — OOPSY, KATOH, PARS, us. We already run a **more
rigorous and more transparent** stack than most of the field; our differentiated outputs are
just hidden (`shadow_only`).

The win is to **surface and brand what we've already built**, plus one honest engine fix
(the hitter model), and to plant a flag on the one genuinely **unoccupied** wedge: a
**provable, timestamped "Ahead of the Curve" track record.** That is the metric nobody else
has and the one that earns citations.

Frame the positioning as: the **transparent, settings-aware, provably-early** option in a
field of paywalled black boxes (Prospects Live) and unvalidated formulas (PARS).

---

## Competitive landscape

### Our peers — statistical projections
- **OOPSY** (Jordan Rosenblum; FanGraphs + Scout the Statline, ~$5/mo). The closest analog.
  Builds on Marcel; projects **peak** (age-28) production; regresses to a *make-the-majors
  probability* mean keyed on **age-relative-to-level**; per-component aging curves; ingests
  modern signals (bat/swing speed, barrel, EV90/"Prospect Savant", Stuff+). Dynasty-native,
  partly free on FanGraphs. **Weaknesses:** no scouting/amateur/intl, playing-time- and
  injury-neutral, volatile for recent draftees, **no per-prospect track record ledger**,
  ranked *2nd* (not 1st) in FanGraphs' own debut review. Beatable.
- **KATOH** (Chris Mitchell, FanGraphs, ~2014-2018, retired). Canonical stats-only MiLB→WAR
  model (probit regressions by level). The template we compete in. Retired; WAR not fantasy;
  weak on level-skippers.

### Scouting / consensus reference (the vocabulary, not a target)
- **FanGraphs FV / The Board** (Longenhagen). 20-80 scale; FV → annual-WAR / surplus-value.
  The consensus reference the whole market speaks. Free interactive board. Subjective,
  not reproducible, penalizes low-level. → Use FV as the *baseline we diverge from*, never a
  score input.
- **Baseball America.** Gold-standard scouting authority; ranks anchor the market. Editorial,
  subscription-gated, no fantasy-category model.

### Most direct head-to-head
- **Prospects Live (PLIVE+).** The most feature-complete dynasty ecosystem: scout ranks +
  stats-only peak projections + league-customized values + roster upload + trade tools (~$12/mo,
  free = top 10 only). **Weaknesses we exploit:** opaque value math (black box), almost
  everything paywalled, **no public track record**, value math undisclosed.

### Foils & precedents
- **HarryKnowsBall** — crowdsourced market value (KeepTradeCut-style). *Is* consensus →
  structurally **late** on breakouts. The perfect contrast for an "ahead of the curve" brand.
- **Razzball** — format-customized *value* (Player Rater), but redraft-first, not dynasty-peak.
- **The Dynasty Guru / Pitcher List / The Dynasty Dugout** — editorial ranks or single-format
  trade calcs; no transparent model, no customization at the prospect level, no track record.
- **PARS** (Rick Mahieu, Prospects1500) — a *rating* system (7 weighted categories → 0-100),
  rate-stat philosophy. **Proprietary/unauditable, no Statcast, monthly/manual, and crucially
  publishes NO accuracy/validation.** Easy win on rigor.

---

## The two wedge verdicts

1. **League-settings-customized values — PARTIALLY OCCUPIED.** Razzball, Prospects Live, and
   Scout the Statline already do *some* of it. "Customizable values" alone is **not** a clean
   differentiator. The still-open, narrower version: **arbitrary per-category / points custom
   scoring applied to dynasty *peak* prospect value.** Frame it precisely or it's contested.
2. **Provable, timestamped early-call track record — ESSENTIALLY UNOCCUPIED.** No system
   publishes a per-prospect dated ledger with a measured hit rate. The "before the market
   moves" *claim* is everywhere; the *receipts* are nowhere. **This is the wedge. Prioritize it.**

---

## Where ValuCast stands (self-benchmark)

**Stack:** `prospects/universal.py` (Universal Prospect Model v0.4, shadow) predicts
league-*independent* factual outcomes (bust/role/star + representative MLB stat line);
`prospects/model.py` (Prospect Model v0.6, hurdle-ridge) drives the live board; `rank_v1.py`
(live 0-100 board) blends v0.6 score 76% + universal index 15% + pedigree 6% + reliability 3%.
Honest player-grouped walk-forward CV with a beat-the-baseline **gate** (≥2% OOS, n≥250).

**Strengths (ahead of the field):**
- Transparency/explainability — per-player drivers (leave-one-feature-out), confidence tiers,
  uncertainty bands. Publishable-grade; ahead of OOPSY and the black boxes.
- **The settings-aware architecture already exists** — `adapters.py` + `league_adapter.py` map
  factual outcomes into *any* category/points league and refuse partial coverage. (Shadow today.)
- Contract-enforced **independence** — provably never sees external ranks/values/market.
- **Daily full-breadth refresh** (2,638 prospects re-scored daily with reliability shrinkage).
- Every prediction **archived per-date** (`data/prediction_archive/*`) — the substrate for a
  receipts product already exists.

**The one honest engine gap:** the **hitter** sub-models currently *lose to their own 25-NN
baseline* (gate = fallback), so for hitters we effectively ship a nearest-neighbor model.
Pitchers clear the gate. This must be fixed before branding a metric.

**Other gaps:** linear ridge vs GBM/ensemble; scope = A-AAA stats only (no scouting/Statcast/
intl); trained through 2019 cohorts (stale supervised signal); no published track record yet;
new/unbranded; the differentiated outputs (settings-aware ranks, bust/role/star probabilities)
are shadow-only and not user-visible.

---

## The metric design — three components

All built mostly from assets we already own.

1. **Headline number — a settings-aware ValuCast value.** Keep the 0-100 score; promote the
   shadow adapters to live so it's *"your prospect rankings, scored for your league's exact
   categories and weights."* The capability exists; this is mostly promotion + surfacing.
   OOPSY/KATOH/PARS structurally cannot match it (their target is baked to one scoring view).
2. **Honesty layer — surface the bust / role / star probability profile + uncertainty** we
   currently hide. "62% role-or-better floor, 18% star ceiling, in *your* categories" is more
   decision-useful and more defensible than any single FV number.
3. **Brand metric — "Ahead of the Curve": a measured, published earliness score with receipts.**
   Mine the dated archives to publish divergences from consensus and how they aged
   ("ValuCast had X on date D, N days before the field moved"). The unoccupied wedge; the
   citable thing no competitor can copy. Directly satisfies the "a new metric people quote" goal.

---

## Positioning (one line each)

- vs **OOPSY/KATOH:** match the projection, beat on **customization + receipts**.
- vs **Prospects Live** (the real rival): beat on **transparency + a public track record + a
  generous free tier** — out-prove the black box.
- vs **PARS:** win on **rigor** — we're validated, they're not.
- vs **HarryKnowsBall:** be the **foresight** answer to their consensus/market price.
- vs **editorial brands:** be the **systematic, full-pool, customizable, provable** alternative.
- "Industry" target = the **dynasty fantasy market** (not MLB front offices, whose internal
  data we can't get and who won't use a public site).

---

## Build plan (sequenced; each phase gated)

**Phase 1 — Hitter gate: RESOLVED 6/23 (no build).** Investigated three ways (diagnosis →
training-window experiment → paired bootstrap) and the conclusion is firm: the hitter gate is
**correctly conservative, not broken.** The hitter outcome/impact sub-models honestly sit at
+0.5%/+1.1% over a 25-NN baseline (bar +2%), and a paired bootstrap shows that edge is
**statistically indistinguishable from zero — the hitter model and the kNN are tied.** No fix
clears it: (a) capacity — a hand-rolled GBT lifts to ~+1.6% honest, still short, and would fall
back anyway; (b) features — adding pedigree *hurt* (−20%, missing-data noise); (c) data — relaxing
maturity to fold in 2021/2022 degrades the gate (model and kNN rise together), AND *acquiring*
pre-2014 cohorts (2009-2013 fetched + rebuilt, ~doubling the star sample to ~192) ALSO fails —
matched-window impact stays flat (~+1.1%) as model and kNN fall together, the gap shrinks not
closes, every bootstrap CI spans zero; 2020 is a COVID hole. (Pre-2014 MiLB IS acquirable via
MLB Stats API — just not a gate-closer.) And the repo is **strictly dependency-free** (no numpy/sklearn) so
a GBM library is off the table regardless. **Decision: keep `MATURE_THROUGH=2019`, accept the
kNN-fallback as validated ground, do NOT lower the bar.** Engine-integrity prerequisite is MET —
the model is honestly validated; for hitters that honest answer is a strong nearest-neighbor
model. Hitter-prospect outcomes are genuinely neighbor-y; there is no separable signal left to
capture. This is the fifth independent confirmation that the prospect *accuracy* frontier is
closed — which is exactly why the strategy is settings-aware + provably-early, not accuracy.
Proceed to Phase 2.

**Phase 2 — Promote settings-aware adapters shadow→live. NEXT (confirmed 6/24).** Surface
`adapters.py` per-league prospect rankings as a URL-driven user feature (mirror the existing
dynasty league customization). Frame the wedge precisely: *arbitrary custom scoring on dynasty
peak prospect value.* Governor/anchor-guarded; refuse partial category coverage (already enforced).

  **6/24 scope clarification (this is the "dynasty/redraft values pass"):** today the dynasty
  board shows a fixed VAL/$ plus a *client-side* "Category Fit" that only RE-RANKS the visible
  pool by current-category z-context — "long-term ValuCast value does not change" (per the panel
  copy), and it dashes out whenever stat context is missing. The real wedge is making the **value
  itself settings-aware**: the dollar value MOVES with league scoring (a SB specialist worth more
  $ in a SB league, an OBP bat worth more in an OBP league), for BOTH **dynasty (peak)** and
  **redraft (current-season)** — driven by the adapters/engine, replacing the shallow re-rank.
  This is what OOPSY (one neutral number) and PL+ (list-side only) structurally cannot match.
  NOTE (6/24): Alex confirmed this is the item but suspects there may have ALSO been a separate
  values-related roadmap item — flagged for the "what's left" sweep to surface.

  **INVESTIGATION 6/24 (plan ready to execute):**
  - REDRAFT is ALREADY fully settings-aware. `/?mode=categories|roto|points` runs the user's
    cats/pcats/weights through `build_config`→`engine.value_players` per request; the engine
    z-scores by category, so SB/OBP value already moves (proven: tests/test_engine.py
    test_category_configuration_changes_rankings). Gap there is only that `_compute_dollar_values`
    (app.py) ignores roster depth (flat 12/$200) — a minor completion, not the wedge. Action:
    ADVERTISE it; optionally add roster-depth to redraft $.
  - DYNASTY PEAK value is BAKED at build with a FIXED default 5×5 (`mlb/dynasty.py` build_config
    mode="categories" → horizon → snapshot). Per-request categories can't reach it. The only
    per-request category-aware dynasty number today is `now_dollars` (`_custom_dynasty_values`,
    CURRENT-season, secondary column). "Category Fit" is client-side display re-rank only.
  - ⚠️ CORRECTNESS TRAP: the prospect within-role-percentile→pooled fix does NOT port (same
    finding as the dynasty pitcher-tilt). Naive per-request peak re-valuation must reproduce the
    horizon + PITCHER_PRODUCTION_ANCHOR + pooled min-max exactly or numbers disagree with the
    snapshot; per-request full-pool horizon also risks the Render ~30s ceiling (2 workers).
  - RECOMMENDED BUILD = precompute peak value under a SMALL MENU of presets (5×5, OBP/OPS,
    points, SV+HLD, 6×6) AT BUILD TIME in mlb/dynasty.py (reuses the exact pipeline → no math
    drift, no per-request cost), store per-player `value_by_preset`, serve by preset (dict
    lookup), make the Category-Fit presets swap the real value. Flag-gated/reversible.
  - PROSPECT side: covered presets (dd_7x7 + any ⊆ adapter SUPPORTED_CATEGORIES) can become a
    settings-aware value (currently rank-only); 5×5/points BLOCKED until universal W + standalone
    SV outcomes exist; DD-7×7 live value gated on the adapter top-quartile-precision guard.
  - Critical files: mlb/dynasty.py (build loop ~:967-1018, the value→horizon→scale→anchor block
    to loop per preset), web/config_builder.py build_config, web/category_registry.py presets,
    app.py _build_dynasty_context / _custom_dynasty_values, templates rankings_table_dynasty.html
    + the Category-Fit JS to retire under flag. Tests: test_engine, test_dynasty_customization,
    test_config_builder, test_league_settings.

**Phase 3 — Build the divergence / receipts layer ("Ahead of Consensus").** Read-only; score
stays 100% ValuCast (independence firewall untouched). Compute `divergence = consensus_rank −
valucast_rank` from existing `_source_rank_min`/context-only plumbing; surface an "Ahead of
Consensus" list; write a timestamped receipts log (reuse `recent_signal` dated-archive pattern)
so caught calls become provable ("called X N days before the field"). This is the brand wedge.

**Phase 4 — Brand + surface + methodology page.** Name the package; publish a transparent
methodology page; surface the bust/role/star probabilities. Ship every cycle (cadence is part of
why OOPSY/PARS get cited).

**Phase 5 — Acquire FV as the consensus *baseline* (not a score input).** Source FV/tool grades
(MLB Pipeline viable; FanGraphs Cloudflare-blocked → committed network-free snapshot) as the
divergence baseline that powers "ahead of consensus" + a context chip. **Policy: display/context
only — never enters the score** (`PROHIBITED_SCORE_INPUTS`). Gate any use with a fresh
incremental-lift test (prior gate: grades add ~0 incremental lift to the score anyway).
**SHIPPED 6/23-24:** FanGraphs FV/tool-grade committed snapshot, card panel + model-vs-scouts
disagreement flag, FV strip on the share card. Display/context only; never in the score.

## Backlog — confirmed dynasty-VALUES items (unscheduled, 6/24)

Surfaced by the 6/24 "what's left" sweep and confirmed by Alex as roadmap items he
wanted tracked (the values work he half-remembered beyond Phase 2):

- **General Dynasty ("Phase G").** Generalize the dynasty *value* model beyond the DD
  7×7 format to arbitrary dynasty leagues (scoring categories + roster + depth). Sibling
  to Phase 2: Phase 2 makes *prospect* value settings-aware; Phase G extends
  settings-awareness across the full MLB+prospect dynasty valuation so the value is
  portable to any league. Shares the adapter/missing-outcome groundwork with Phase 2
  (5×5/points/OBP coverage is blocked on universal W + standalone-SV outcomes).

- **Dynasty-board pitcher-tilt calibration (`mlb/dynasty.py`). SHIPPED 6/24.** Symptom:
  Cristopher Sánchez / Misiorowski sat above Soto in the #9-18 band. Root cause: the
  combine point (`:980-988`) min-maxes the pooled per-role z-sum values on RAW MAGNITUDE,
  and the deeper pitcher pool's top is dense/high, so mid-tier aces priced near elite bats.
  ⚠️ The prospect "within_role_percentile_to_pooled_distribution" fix does NOT port here —
  it makes the tilt WORSE (percentile equalization preserves within-role rank, and the
  pitcher pool simply has more extreme top performers by count). Instead shipped a single
  `PITCHER_PRODUCTION_ANCHOR = 0.92` on the pitcher production score (hitters EXACTLY
  unchanged; within-pitcher order preserved; reversible at 1.0; `LAYER_VERSION` 0.4→0.5,
  `cross_role_calibration` metadata emitted per row). Tuned to the gentlest anchor with a
  durable margin: Soto now clears Sánchez/Misiorowski by ~1.7pt, Skenes holds #5, 4 pitchers
  in top-25 (governor `mlb_top_board_role_shape` passes). Inherited by the Marcel-shadow
  layer. Calibration judgment (ponytail), not outcome-gated. The MLB dynasty board is now
  postable. **NOTE: Kurtz #3 (a HITTER-side aggressive value) is a separate open item.**

## Parked / maybe (not committed)

- **"Model + Scouts" blended view (MAYBE, 6/24).** A separate, clearly-labeled view that blends
  the independent ValuCast rank with FanGraphs FV for users who want consensus baked in — sitting
  *beside* the core rank, never replacing it. Parked deliberately: feeding FV into the core score
  is prohibited (it would destroy the "ahead of the curve" signal and violate independence), and
  grades gated out on accuracy anyway. Revisit only as an optional secondary surface if there's
  demand; the core rank stays FV-free.

---

## Honesty rules / what NOT to do

- **Do not market accuracy superiority.** The ceiling is shared (~0.26); claims get fact-checked.
  Market customization + provable earliness + transparency.
- **Do not put external ranks/FV in the score.** Independence is a trust asset and a policy.
- **Do not chase tracking-data metrics** (Stuff+ clones) on public data — proven dead this
  sprint (own-xBA shortfall, Statcast-pitcher lost to FIP).
- **Gate every build** shadow→active, ≥2% OOS, governor-guarded. Same discipline that shipped
  pitcher FIP-ERA and killed three useless builds.

---

## Sources

Competitive intel from workflow w4hn27q44 (OOPSY, PARS, KATOH, FanGraphs FV/The Board,
Prospects Live, The Dynasty Guru, Pitcher List, The Dynasty Dugout, HarryKnowsBall, Razzball,
Baseball America, FanGraphs Community models). Web-sourced (US), 2026-06-23; some pricing/feature
details from search snippets where pages returned 403 — verify on-site before public claims.
