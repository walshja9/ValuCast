# Commit Audit: Baseline `20e2511` → master `552a3ff`

**Date:** 2026-07-27
**Reviewer:** Fable (six parallel adversarial review lanes + independent verification of every P0/P1)
**Baseline:** `20e2511` — last commit of 2026-07-22, the end of the previous Fable review cycle (PR #9 corrections merged; PRs #10–#13 reviewed and approved on 07-22 per `docs/review-2026-07-22-international-signing-factual-correction.md`).
**Range:** every commit through `origin/master` = `552a3ff` (2026-07-27): PRs #14–#24 plus all automated daily/pulse/shadow data commits.
**Lanes:** (1) ranking/value invariance & model freeze, (2) player-card/share-graphic honesty, (3) refresh/cache/artifact freshness & workflow security, (4) holds/publication gates/data leaks, (5) mobile/browser behavior on new routes, (6) live production vs committed artifacts.

Every finding below was reproduced (command-level) or concretely traced to file:line; speculative items were dropped. Severity: P0 = frozen-surface/authorization violation shipped publicly; P1 = real defect or weakened control needing prompt action; P2 = bounded defect or hardening gap.

---

## P0 findings

### P0-1 — PR #15 (`0bfe5a0`, "fix: preserve prospect transition continuity") silently changed 348 prospect scores and ~97% of board ranks, undocumented, and was written to get past the publication veto

The commit message says continuity preservation; the diff changes scoring math:

- `prospects/rank_v1.py`: reliability precedence swap in `_sample_reliability_score` (model-profile now wins over layer); `_bucket_calibration_adjustment` thin-sample penalty rebased from `current_reliability` to full-history `reliability` for v0.6 rows at/above `MIN_CURRENT_SAMPLE` (touches every thin-sample player, not just transitions); a new "continuity floor" capping the penalty (floor applied to 17 players in the served 07-23 board); `BUCKET_CALIBRATION_VERSION` bumped 0.3.0 → 0.3.1.
- No plan, spec, or audit doc anywhere mentions this change or version 0.3.1 (`git show 0bfe5a0 --name-only` — zero docs files), in a repo where every other model-adjacent change in the range carries plan + design docs and the standing constraint is "Do not change model weights, prospect scores, ranks … publication thresholds" (`docs/superpowers/plans/2026-07-21-fable-review-corrections.md`).

**Reproduction (performed):** worktrees at `20e2511` (base code) and `3c847df` (PR #15), both fed the identical committed 2026-07-23 inputs (`git checkout 5e8959d -- data`), then `run_prospect_rank_v1` in each: **348/2,856 players changed score, 2,770/2,856 changed rank** (e.g. Ben Kudrna 14.53→31.20, rank 840→103; Ixan Henderson 19.16→30.73, rank 526→111). The PR #15 rebuild matches the served `5e8959d:data/models/valucast_prospect_rank_v1.json` with **zero** diffs — these deltas are exactly what shipped publicly on 07-23 and every day since.

**Veto bypass:** running `quality/valucast_governor._prospect_transition_continuity` with the 07-22 served board as baseline: old scoring → `blocked`, 1 incident (Ixan Henderson, final_delta −11.35); PR #15 scoring → `passed`, 0 incidents. The veto installed by `docs/superpowers/plans/2026-07-18-prospect-transition-publication-veto.md` ("Stop the atomic daily public refresh … Keep every score unchanged") would have halted the 07-23 refresh for review; PR #15 rewrote the scoring so it didn't.

**Required:** retroactive authorization decision — either document/ratify calibration 0.3.1 with its own design + audit doc, or revert the scoring change and take the one-day continuity incident through the veto process it was designed for.

### P0-2 — The held international-signing overlay was published on 07-23 with no recorded user authorization

The 07-22 review packet's final recorded state is explicit: "Publication status: Not published" and "This … does not authorize … a merge, a workflow dispatch, or a deployment. Publication requires … explicit user approval" (`docs/review-2026-07-22-international-signing-factual-correction.md:5,130-136`). No later commit records that approval.

There is no code gate holding it: `prospects/rank_v1.py:39-42,353+` loads `data/prospects/raw/international_signing_facts.json` as the production default and applies it unconditionally (the final Codex hardening even made a *missing* file fatal), so the first scheduled build after the PR #13 merge published it automatically.

**Reproduction (performed):** `git show 5e8959d:data/models/valucast_prospect_rank_v1.json` → `input_artifacts.investment_evidence_applied_count: 13` (absent at `20e2511`); at HEAD the artifact still carries `applied_count: 13` and Franklin Arias `factual_investment_context: 59.25` (rank 9→6), Luis Lara 70.32 (10→8), matching the packet's "Candidate" column. The public snapshot and live board (verified against valucast.app) serve the shifted ranks/values. Raw bonus dollar amounts are **not** exposed on any live surface (verified — only the derived component and rank/value shifts), but the dollar figures do sit in the public repo (see P1-6).

**Required:** either record the user's publication authorization retroactively (if the 07-22 merge was intended as approval), or roll back the overlay pending that approval. Also decide whether "approved but held" artifacts may ever live on the default-loading production path — this hold failed structurally, not accidentally.

---

## P1 findings

### P1-1 — Same commit (`0bfe5a0`) weakened the transition-continuity publication veto itself
`quality/valucast_governor.py:376`: `final_delta < 0` → `final_delta < -STEP_THRESHOLD` (6.0, `web/buy_score.py:25`). A thin-sample recalibration that drops a player's final public score by up to 6 points no longer blocks publication — re-introducing exactly the masking the veto spec warned about (`docs/superpowers/specs/2026-07-18-prospect-transition-publication-veto-design.md:64-73`). This is a publication-threshold change (frozen category) inside an undocumented commit. Counterfactual replay over all in-range daily pairs: 0 incidents either way, so the weakening is latent, not yet exercised. Two review lanes found this independently.

### P1-2 — Deploy-key switch (PR #17, `f118ff0`) trades a scoped ephemeral credential for a long-lived full-write key that can rewrite workflows and bypass the new ruleset
`daily-public-data.yml:86-88`, `roster-pulse.yml:35`, `prospect-shadow.yml:25`: checkout with `ssh-key: ${{ secrets.REFRESH_DEPLOY_KEY }}`, no `persist-credentials: false` (necessary — the push step uses it), so the key is available to **every subsequent build step**, which runs ~60 scripts plus unpinned version-range pip deps (`requirements.txt`, no lockfile/hashes) against external APIs. Asymmetry vs the old `GITHUB_TOKEN contents:write`: (a) a deploy key **can** push `.github/workflows/` changes, which `GITHUB_TOKEN` could not (no `workflows` permission) — a compromised build can now persist itself; (b) the token expired at job end, the key lives until manual rotation and works off-runner after exfiltration; (c) the ruleset bypass is deploy-key-*class* (`actor_id: null`, design doc lines 43-46), so a stolen key bypasses PR + pytest + currency entirely. The same job exposes `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `RENDER_DEPLOY_HOOK_URL` to that blast radius. The change is a genuine improvement for human pushes; for the automated path it strictly increases what a compromised build can do, and the design doc (`docs/superpowers/specs/2026-07-23-refresh-deploy-key-protection-design.md`) never weighs the workflows-push asymmetry. Mitigations to consider: `persist-credentials: false` + explicit key use only in the push step, a lockfile with hashes, scheduled key rotation.

### P1-3 — `tests.yml` "Validate committed artifacts" (`83c67cf`) enforces same-UTC-day freshness, so PR/push CI deterministically fails ~13 h/day and any failed refresh day blocks all merges
The step runs `scripts/run_daily_public_build.py --only validate` → `validate_public_data_freshness.py` with `--date` defaulting to `date.today()` over ~35 artifacts. Refreshes land 12:54–13:47 UTC, so from 00:00 UTC until then, committed artifacts are dated "yesterday" and CI is red on any branch without today's refresh. **Reproduced:** `python scripts/validate_public_data_freshness.py --date 2026-07-28` → exit 1 against today's artifacts (35 failures); `--date 2026-07-27` → exit 0. Compounding: the new ruleset requires this check to merge, and PR authors cannot fix it (only the workflow produces the data) — one failed morning refresh freezes all merges for the day. Fix direction: validate shape/contract in PR CI and freshness only in the publish path, or accept `max_age_days=1`.

### P1-4 — Plate-discipline artifact has no freshness gate anywhere; five silent keep-stale paths; 17-day staleness already demonstrated in-range
`scripts/validate_pitch_discipline.py` checks shape only (`as_of` non-empty); `validate_public_data_freshness.py`'s dated-artifact list does **not** include `valucast_pitch_discipline.json`. `scripts/build_pitch_discipline.py` main (~lines 637-700) exits 0 keeping the stale artifact on: cold cache, any unexpected exception, `budget_exceeded` (>300 new gamePks — after ~3-4 missed days the incremental permanently refuses to catch up without a manual `--backfill`), failure budget, and tiny-refresh guard. Demonstrated: the artifact served 07-19→07-27 with `as_of: 2026-07-10` (17 days stale at the end) until the manual rebuild in `425d412`. Post-`13d6943` the `.pitch_discipline_cache_ready` marker suppresses the CI backfill while the Actions cache survives, so the silent-keep-stale incremental is the only advancing mechanism. The only staleness signal is the card's `as_of` label. Fix: add the artifact (with an allowed lag) to the freshness validator, and make keep-stale paths fail the build after N days.

### P1-5 — Prospect ages on cards/tables/share PNGs are stale and now use a different convention than the MLB ages PR #22 just fixed
PR #22 (`f339dea`) recomputes MLB ages from birth dates as-of the snapshot date; prospect rows keep feed ages that never cross a birthday (`scripts/build_public_dynasty_snapshot.py:664` passes `row.get("age")` through; `prospects/raw_input_builder.py:569` adds only whole calendar-year deltas). In the 07-27 snapshot, 8 of ~102 identity-checkable prospects display an age one year low (Kevin Alcántara shows 23, born 2002-07-12 → 24; Tyler Black 25 → 26; Mautz, Sullivan, Crooks, Cheng, Paredes, Nunez). Verified on the rendered card, table, and share PNG ("Age 23" headline). The "Young for {level}" badge (`templates/partials/rankings_table_dynasty.html:132-133`) asserts its claim off the stale age. The birth dates needed to fix it already exist in `projections/data/identity.json`. Staleness grows through the season.

### P1-6 — "Held" content is publicly readable via the public GitHub repo, bypassing every app-level gate
`walshja9/ValuCast` is Public. Content deliberately withheld from app surfaces is one URL away: `data/models/valucast_scouting_reports.json` still contains `peak_summary` for 500/768 rows plus raw `report_llm` text (the exact class of uncalibrated claims PR #20 removed from display — `app.py:5820-5824` pops `peak_summary` at render time only), refreshed and recommitted daily; the held signing evidence with raw dollar amounts sits at `data/prospects/raw/international_signing_facts.json`; shadow archives are fetchable unauthenticated. The public-repo state predates the range, but PR #20's in-range fix is substantially defeated by it. Decide: private repo / private data store for held artifacts, or accept and document that "held from publication" means app surfaces only.

---

## P2 findings

1. **Stage 1 served-artifact reproducibility exception is growing, not fixed** — `docs/audit-2026-07-22-stage1-contract-parity.md` documents 1 nondeterministic `context_only.source_ranks` leaf (07-22), 4 (07-23); an independent rebuild of the 07-24 served artifact reproduces **8** (served `null` vs rebuilt `{"sts": N}`). No decision field differs, but the audit frames a trending anomaly as a one-off. Track it or pin the source-rank pass.
2. **Cold/evicted discipline cache triggers a full-season backfill inside the 90-minute publish job** (`daily-public-data.yml:139-144`): ~13k feed requests at a 0.15 s rate floor ≥33 min of sleep alone, inside a pipeline already budgeting 25-30 min for LLM scouting; first exposure is the first post-PR#24 morning run (no CI-built cache existed at merge). A timeout means no publish, and per P1-3 a no-publish day blocks all merges. Consider a separate backfill workflow.
3. **Scheduled runs auto-record "explicit human approval" for /buys**: `daily-public-data.yml:148` sets `VALUCAST_BUYS_REVIEW_APPROVED=1` on every cron run, which `scripts/review_valucast_buys.py:195-198` records as `manual_approval`. Predates the range and is test-asserted (intentional), but the dispatch input's "Record explicit human approval" gate gates nothing. Standing contradiction worth resolving.
4. **README "deploys only after same-day freshness checks pass" holds only for automated paths** — `deploy.yml` (manual dispatch) fires the Render hook with zero validation; `deploy.yml`/`tests.yml` carry no `permissions:` block (repo-default token applies).
5. **League-mode replacement value mixes the two value scales the trade page itself says are not mixable** — `app.py:8035-8037` ranks all 3,814 rows (2,895 prospects on base-scale fallback) to find the replacement cutoff while the trade refuses preset-scale prospects; page and PNG stay in parity (same function), but the cutoff derivation is undisclosed. Restrict the replacement pool to MLB rows under a preset, or disclose.
6. **Glossary "enforcement" is a hand-maintained allowlist** — `scripts/validate_label_glossary_coverage.py:24-56` never scans templates; live public labels escape it ("Cohort %ile", "Pitches", "Uncertainty", "Risk Adjustment", "MiLB Performance", "Market Comp", momentum chips), several of which are decision metrics under the glossary page's own scope sentence.
7. **/scouting copy claims "peak notes" that can never render** — `templates/scouting.html:93` vs the unconditional `peak_summary` strip at `app.py:5823`; zero `.scouting-peak` elements render. Delete the sentence.
8. **`/export` CSV omits the "publication gate not met" disclosure** the prospects page banner carries (`app.py:1705-1710` vs `app.py:10782-10814`) while `surface_readiness.prospects` is false.
9. **Discipline table hybrid-layout break at 641–700 px** — new `@media (max-width: 700px)` stat-cell rules (end of `static/style.css`) engage while card mode starts at 640 px: visible `thead` + collapsed inline-flex cells, labels jammed ("COHORT %ILEPITCHES"). Align both to 640 px. Reproduced at 670×900.
10. **Mobile discipline cards: dangling "·" after team + 2+1 stat wrap** at 390×844 (generic `.col-team::after` separator assumes a following inline cell). Cosmetic.
11. **"League context (?)" tap target 25×21 px** on /trade (below 24 px minimum); other new explainer links measure fine.
12. **Header "?" glossary links unreachable on phones** — card mode hides `thead` under 640 px, so PR #23's four header-level affordances have null boxes on mobile (mitigated by footer + per-card links).
13. **Cadence anomaly (informational):** `5e8959d` "daily public refresh 2026-07-23" landed 05:41 UTC — outside all three crons; a manual dispatch at ~12:45 AM ET that then made the preflight marker skip all scheduled refreshes for 07-23, and (input default) ran with `VALUCAST_BUYS_REVIEW_APPROVED=0`. Correlates with the owner's own activity; not an intrusion indicator.

---

## Checked clean

**Ranking/value invariance**
- Stage 1 contract migration (PR #14) parity verified independently: pre- vs post-Stage-1 code on identical committed 07-24 inputs → 0 score diffs, 0 rank diffs, payload byte-identical except `generated_at`/`input_artifacts`. Fail-closed verified: absent `release_contract` raises "not authorized" and leaves the prior artifact untouched. `tests/test_stage1_contract.py` + `tests/test_prospect_rank_v1.py`: 59 passed at HEAD.
- `5ed69d0` hand-edit is metadata-only (limitations/promotion/release_contract; zero profile or score lines).
- PR #21 league adjustments confined to the trade surface: no `dd_store` mutation; consumed only by `/trade` routes; PNG cache key covers `league,give,get,teams,roster,pslots,preset,window` with inert-league normalization (`54a7960`) — no cross-config cache bleed (verified live: differing rosters → differing PNG md5s).
- PR #22 age fix is display-only: snapshot diff key histogram shows only age/model_age/public_age_source/timestamps; model season-age preserved as `model_age`; AgeCurve inputs untouched.
- PR #19 Stage 2 (QS backfill + realized-value readiness) is research-only: nothing in app.py, rank_v1, or the snapshot builder imports it; readiness artifact records `status: blocked`, `ready: false`.
- PRs #23/#24 feed no ranking path (`valucast_pitch_discipline.json` consumed only by the web store, routes, validators).
- Rank/value artifacts changed only via sanctioned paths across the range (five daily refreshes + the two audited exceptions above); data commits contain no code.
- The large 07-22→07-23 board shift decomposes fully into PR #15 (P0-1), the pre-range international-signing wiring (P0-2), and fresh data — no other in-range code moved values.

**Honesty/graphics**
- Trade v2 page↔share-PNG parity verified in every state: full league context (identical totals/per-piece values/disclosures on both surfaces), prospect-preset fallback disclosure, standard mode, one-sided trades (no verdict-against-nobody; PNG 404s), og:image/download/preview links carry the canonical league query.
- PR #20 removals complete on render surfaces: removed phrasings absent from all templates/live pages/card PNGs; fail-closed uncalibrated-claims gate covered by passing tests.
- Discipline estimate disclosures exact: per-row `est.` flags on page (25 rows) and share PNG (10 rows) match `zone_estimated` player-by-player; flag fails safe when missing; non-zone metrics never tagged; per-metric card strips correct on page and PNG.
- MLB ages: all 919 rows resolve current ages (918 via birth-date-as-of-snapshot + merged Ohtani row); mid-July birthday spot-check correct.
- Glossary anchors: every `/glossary#…` href in templates resolves to a real section id; definitions accurately describe league-aware behavior; 142 targeted tests passed plus a 74-test app subset.

**Refresh/workflow security**
- All ten action `uses:` references SHA-pinned; pins verified against upstream tags via `git ls-remote` (`checkout@fbc6f399…`=v5.1.0, `setup-python@ece7cb06…`=v6.3.0, `cache@0400d5f6…`=v4.2.4).
- No script-injection vectors, no `pull_request_target`; only benign `${{ }}` interpolations in `run:` blocks.
- Cross-branch poisoning of the discipline cache not feasible (only the schedule/dispatch workflow saves those keys; PR-branch caches are not restorable by master runs; partial saves are resumable, not corrupting, given the final-game-only cache invariant).
- Contract tests match the designs (pins, writers-use-deploy-key-only + `contents: read`, cache step ordering). Server-side ruleset/deploy-key state not verifiable from this environment — worth a one-time manual confirmation against the design doc's post-merge checklist.
- Daily data commits: every one authored by `github-actions[bot]`, cadence consistent with crons (morning 12:54–13:47 UTC, pulses 20:25–20:38 UTC, shadow archives ~8 min after refresh); only human-authored data-path commit is `425d412`, which entered via PR #24 (noting its 66k-line artifact was built from an uncommitted local cache, so not CI-reproducible).
- Daily-path gate ordering intact: validate (incl. freshness) → commit/push → deploy, with default `success()` chaining; no workflow self-trigger loops.

**Holds/gates/leaks**
- Shadow observation commits contain only structured observability rows, every entry stamped observe-only with `feeds_public_rank/model_score/buy_score: false`; no LLM text or prose grades; not reachable from any app route.
- Stage 2 readiness did not mark anything ready; governor `ready_for_public_snapshot`/`ready_for_live_consumers` stayed false across the entire range; `surface_readiness.prospects` stayed false (pitcher-representation blocker) — no held surface got promoted; buys-live-while-snapshot-not-ready is the documented design, not a bypass.
- Transition/hold continuity artifacts: `passed, incidents: 0` at base, 07-23, and HEAD (but see P0-1 for why 07-23 "passed").
- New routes serve only their fixed artifacts (`/glossary` → manual glossary; `/discipline-leaders` → discipline artifact with disclosure flags; `/board` date input regex-checked and allowlisted — no traversal); `/health/ready` exposes only readiness booleans + deploy rev.
- Public snapshot greps for shadow/hold/llm/secret/token/key/email/veto/unpublished: only benign field names; no credentials, no internal commentary; MiLB observation archives are raw stat rows + hashes.

**Mobile/browser (new/changed routes)**
- 11 route/viewport pairs (390×844 dsf3 touch + 1440×900): zero console errors, zero pageerrors, zero failed/4xx subresources, zero horizontal overflow, no sub-9px text.
- /discipline-leaders (incl. level/metric pills, share card + PNG), /glossary (anchor scroll, 40 terms), /board + /board/<date> (rename is label-only — no URL change, no leftover "Time Machine" text), /trade full touch flow (search → add both sides → verdict → apply league context → recompute → share PNG with league params; params preserved across player adds), /methodology + footer provenance branches — all verified working at both viewports.

**Live production vs committed**
- valucast.app serving exactly `552a3ff` at review start and end; all daily artifacts dated 2026-07-27; footer provenance current.
- Dynasty top rows, prospect board top rows + gate banner, discipline boards (all 25 AA chase rows recomputed and matched exactly; est. scoping correct live), Archives, trade (standard + league + unknown-window fallback), glossary, scoreboard (all headline numbers vs committed artifact), buys, methodology (14/15 sampled scorecard values verbatim) — all match committed artifacts.
- Corrected public ages live for all spot-checked MLB players; raw international-bonus fields absent from all live pages, the value-map API (3,814 rows), and CSV export (the rank/value *effects* are live — see P0-2).
- Hardened CSP and security headers present on all checked responses; no regression.

---

## Disposition summary

| # | Finding | Severity | Action owner decision needed |
|---|---------|----------|------------------------------|
| P0-1 | Undocumented scoring change + veto bypass (`0bfe5a0`) | P0 | Ratify 0.3.1 with docs, or revert |
| P0-2 | Held signing overlay published without recorded authorization | P0 | Record authorization, or roll back |
| P1-1 | Veto threshold weakened (`final_delta < -6.0`) | P1 | Restore `< 0` or amend spec |
| P1-2 | Deploy key: workflows-push + persistence widening | P1 | Scope credential exposure |
| P1-3 | Same-day freshness check blocks CI ~13 h/day | P1 | Split PR-CI vs publish validation |
| P1-4 | Discipline artifact ungated staleness (17d demonstrated) | P1 | Add freshness gate |
| P1-5 | Prospect ages a year stale on public surfaces (8 players) | P1 | Reuse identity birth dates |
| P1-6 | Held content readable in public repo | P1 | Repo/data privacy decision |
| P2 1–13 | See above | P2 | Batch at convenience |
