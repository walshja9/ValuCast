# ValuCast adversarial review — codex/share-distribution + master 7/18-20 governance wave

> **Resolution status (2026-07-21): historical pre-merge snapshot.** The two P1
> findings and follow-up P2 items #7-#9 were fixed in `3d24305f` and `d50c7659`,
> then merged to master in `5226001e`. The comps artifact has since refreshed.
> The findings below remain as the review record, not an open-fixes list.

**Date:** 2026-07-20. **Reviewer:** Fable 5, 8-agent parallel fan-out + independent skeptic
verification of every P0. Read-only — no edits, commits, merges, pushes, or workflow
dispatches were performed by this review.

**Scope:**
- Branch: `origin/codex/share-distribution` (9 commits, one daily-refresh commit behind
  master, no open PR) vs `origin/master` at `f6fb64fd`.
- Master governance range: `88367648..f6fb64fd` (7/18-20) — Role Watch, prospect-transition
  publication veto, card decision hierarchy, prospect evidence-language honesty correction,
  player-only trade disclosure, Forward Ledger public release, CSP/governance hardening,
  Competition Proof foundation (plan 032).

**Method:** every finding below was personally verified by the reviewing agent — real diffs
read, real test-client renders, a real `git merge --no-commit` test-merge, a real re-run of
`scripts/build_prospect_comps.py`, hand-recomputed arithmetic against committed data. Nothing
was reported on a commit message alone. All P0s got one additional, independent skeptic
re-check before being included here.

**Bottom line:** no functional or governance defect blocks merging `codex/share-distribution`.
Two real P1s need a fix before merge (a hold-gate bypass and a mislabeled arithmetic scope).
One mechanical P0 fired against the literal "plans/ stays untouched" rule — see the note
below; I believe it's a false alarm given how this repo's plan registry actually works, but
I'm reporting it as instructed rather than silently downgrading it myself.

---

## P0

### 1. `plans/` touched within the reviewed master range — likely a false positive, read the note

- **File:** `plans/032-competition-proof-lane.md` (new, 96 lines), `plans/README.md` (+3/-1)
- **Commit:** `dbf319c2` ("feat: establish competition proof foundation"), inside `88367648..f6fb64fd`
- **Pre-existing:** No — newly introduced by this range.
- **Confidence:** High (mechanical fact) / see note on severity.
- **Exact test:** `git diff 88367648..f6fb64fd --stat -- plans/` — non-empty (expected empty
  per the literal constraint text every review agent was given).

**What happened:** commit `dbf319c2` registers plan 032 (the Competition Proof lane) the same
way every other plan in this repo has ever been registered — a new numbered file under
`plans/`, plus a new row in `plans/README.md`. My review brief told every agent that `plans/`
touched anywhere in the range is an automatic P0, with no carve-out, and one agent correctly
and mechanically caught it. A skeptic independently re-verified the diff, the commit range
membership, and the literal wording of the rule — CONFIRMED as written.

**My honest read, as the orchestrator, not as a reviewer:** I built that "frozen `plans/`"
constraint into the brief from this session's own standing convention — and that convention
has *always* carried an implicit exception for plan *registration* itself. Every plan in this
repo (001 through 031) required exactly this kind of edit to get registered; the actual rule,
as applied all session, is "an executor mid-implementation of an unrelated task shouldn't
touch `plans/`," not "no commit may ever add a row to the plan registry." Plan 032's actual
content was independently reviewed clean by a separate agent (see M3 below: fail-closed claim
authorization, zero path into production scoring, zero eligible public claims) — the
substance is fine. This P0 is a mechanical trip on a rule I wrote too bluntly, not a real
defect. I'm reporting it because you asked for exactly this kind of literal check, but I'd
recommend treating it as informational, not blocking.

---

## P1

### 2. `/backfields/team/<org>` bypasses `AHEAD_OF_THE_CURVE_HOLD`

- **File:** `app.py:6412-6446` (`_team_board_buys`, `_team_board_system_summary`), `app.py:6498`
  (context wiring), `app.py:7440-7466` (`_team_board_share_card_png` VALUCAST BUYS panel),
  `templates/backfields.html:406-419`
- **Branch:** `codex/share-distribution`
- **Pre-existing:** No.
- **Impact:** every other buy-signal surface in the app (`/buys`, the `/backfields` overview's
  "Ahead of the Curve" module) checks `AHEAD_OF_THE_CURVE_HOLD` before rendering named
  prospects/ranks/reasons. The new per-team panel and its PNG do not. If the hold is ever
  flipped back on (the code's own comment notes it was held as recently as 7/1), this one
  surface keeps leaking real buy data — the single documented kill switch for the feature is
  silently defeated for this page.
- **Confidence:** High — directly reproduced.
- **Exact test:**
  ```python
  import app; app.AHEAD_OF_THE_CURVE_HOLD = True
  c = app.app.test_client()
  r = c.get('/backfields/team/ARI')
  assert 'ValuCast buys' not in r.get_data(as_text=True)  # currently FAILS
  ```
  Also render `/backfields/team/ARI/share-card.png` with the flag `True` — the VALUCAST BUYS
  panel still draws.

### 3. Farm "Level distribution" tile silently describes a different population than its neighbors

- **File:** `app.py:6379-6406` (`_team_board_system_summary`), `templates/backfields.html:377-382`
- **Branch:** `codex/share-distribution`
- **Pre-existing:** No.
- **Impact:** the System Snapshot panel has four tiles under one header ("Current ValuCast
  prospect pool"). Three of them — Top-20 value, Top-5 concentration, Top-20 balance — all
  describe the same named top-20 slice and sum/relate correctly to 20. The fourth, "Level
  distribution," has no "Top-20" qualifier but is computed over the *entire* org pool (73-105
  prospects on every real team today). Live example, ARI: "Top-20 balance: 12 H / 8 P" (sums
  to 20) sits directly above "Level distribution: AAA 16 · AA 23 · A+ 29 · A 37" (sums to 105).
  A reader has no textual cue that the scope silently changed mid-panel. Reproduced on ARI,
  NYY, LAD, BOS. The new unit test can't catch this because its fixture happens to supply
  exactly 20 total rows, so `org_rows` and `top20` are identical there by coincidence.
- **Confidence:** High — read the exact source, hand-recomputed against real committed data,
  confirmed the mismatch live on four orgs.
- **Exact test:** render `/backfields/team/ARI` and compare the two tiles' sums; or:
  ```python
  import app as A
  ctx = A._build_team_board_context('ARI', limit=20)
  s = ctx['summary']
  print(sum(l['count'] for l in s['levels']), s['top20_hitters'] + s['top20_pitchers'])
  # 105 vs 20
  ```

---

## P2

### 4. `plans/` boundary — same underlying fact as P0 #1, plus a frozen test file

- **File:** `plans/README.md`, `plans/032-competition-proof-lane.md`, `tests/test_forward_scoreboard_page.py`
- Commit `965424e7` additionally touches a frozen `tests/test_forward_*.py` path — additive
  test coverage for cosmetic cohort-count pluralization on `/scoreboard`, not a scoring or
  backtest change. Same false-positive reasoning as P0 #1 applies.
- **Exact test:** `git diff 88367648..f6fb64fd --stat -- plans/ tests/test_forward_scoreboard_page.py`

### 5. Merging the branch onto current master will hard-conflict

- **File:** `data/models/valucast_prospect_comps.json`
- **Impact:** the branch commits its own comps artifact (generated 7/19, includes
  `pitcher_method` + 40-41 pitchers). Today's master daily refresh (`f6fb64fd`) independently
  regenerated the *same file* (generated 7/20, hitters-only). A real `git merge --no-commit`
  test-merge in an isolated worktree produced exactly one content conflict, right here. It
  fails loud — no silent corruption — but whoever merges needs to take the branch's side and
  let the next nightly rebuild it, not expect a fast-forward or auto-merge.
- **Confidence:** High — reproduced with a real test-merge.
- **Exact test:** in a worktree at `origin/codex/share-distribution`: `git merge --no-commit
  --no-ff f6fb64fd` → `CONFLICT (content)` in this file; `git merge --abort` to clean up.

### 6. The committed comps artifact is one day stale (self-heals, but worth knowing)

- **File:** `data/models/valucast_prospect_comps.json`
- **Impact:** branch artifact is pinned to the 7/19 snapshot; master is already on 7/20. Between
  merge and the next nightly, comp cards render off 7/19 lines while every other prospect
  surface is 7/20. Confirmed the branch's own build script reproduces the committed 7/19 file
  exactly (deep-equal), and separately confirmed re-running that same build against master's
  current 7/20 data produces a correct fresh file (107 hitters + 40 pitchers) — so it self-heals
  on the very next refresh, no action needed beyond knowing the window exists.
- **Confidence:** High.
- **Exact test:** compare `generated_at` between `git show origin/codex/share-distribution:data/models/valucast_prospect_comps.json`
  and `git show f6fb64fd:data/models/valucast_prospect_comps.json`.

### 7. Risers panel hardcodes "spots in 7 days" — recurrence of a previously-fixed bug class

- **File:** `app.py:6167-6172` (`_team_board_move_from_signal`), `templates/backfields.html:398`
- **Impact:** the label is hardcoded regardless of which delta field actually got used; this
  repo already shipped and fixed this exact anti-pattern once (`app.py:8408-8409` comment
  documents a prior incident: a hardcoded "7-day" label next to a metric that actually ran 10
  days). Today it's latent — every row in the live signal artifact has `rank_delta_7d`
  populated, so the fallback path never fires — but there's no test guarding against the
  artifact schema changing again the way it apparently already has once.
- **Confidence:** Medium.
- **Exact test:** confirm `rank_delta_7d` populated on all rows in
  `data/models/valucast_recent_signal_report.json` today; compare the hardcoded template
  string to the artifact-driven pattern already used at `app.py:8408-8414`.

### 8. New comp bars reuse CSS class names an honesty fix deliberately deleted

- **File:** `static/style.css:1894-1920,1963`, `templates/partials/player_detail_dynasty.html:~435-448` (branch)
- **Impact:** the branch's new career-outcome-tier bars reuse `.role-probability-bars` /
  `.role-probability-row` / `.role-probability-track` — the exact class names master's "remove
  unsupported prospect probabilities" commit deleted for rendering unsupported model
  probabilities. Today's copy is compliant ("counts of matched careers, not odds"), so nothing
  is currently misleading — but a future contributor or reviewer grepping the DOM to confirm
  probability-shaped UI was purged will find the name still alive and attached to a bar chart.
  Latent terminology-drift risk against the intent of the honesty guard.
- **Confidence:** Medium.
- **Exact test:** render a pitcher-role comp card and inspect the DOM class names; compare to
  `git show a36b319f -- templates/partials/player_detail_dynasty.html`.

### 9. Scouting-text honesty fallback only patches 3 hardcoded phrases

- **File:** `app.py:5626-5638` (`_public_deterministic_scouting_text`)
- **Impact:** when the LLM/published scouting text fails the `uncalibrated_projection_claims`
  guard, the deterministic fallback only substitutes 3 exact-string phrases and returns
  everything else in the report unrevalidated — so a future stale/legacy report containing a
  different banned phrase (other `SHAPE_LABELS` values, `% chance`, risk-level language) would
  reach the public page without a second guard pass. Currently zero live matches in the
  committed scouting-reports artifact — a design gap, not an active bug.
- **Confidence:** Medium.
- **Exact test:** a new fixture-based test asserting `_scouting_display_report(...)['display_report']`
  never contains a banned phrase outside the 3 hardcoded ones — doesn't exist yet, would
  currently fail if written.

---

## Areas checked with zero findings (explicit, per dimension)

**Role Watch / prospect-transition veto / Skill+ hold (M1):** genuinely new, held dark by
`ROLE_WATCH_HOLD` (unset in `render.yaml`, so live deploy 404s it); no site-nav link; zero
import into any scoring path; the transition-publication-veto check only feeds display
banners, never writes back into a row's score/rank/value, and is explicitly isolated out of
the `/buys` gate. **Your specific claim checked against live data: 22 hitters / 177 pitchers
clamped to zero remaining opportunity — confirmed exact**, read directly from the committed
`run_manifest.json` (`generated_at` 2026-07-20). 193 targeted tests pass.

**Card hierarchy / evidence-language honesty / trade disclosure / Forward Ledger release (M2):**
all copy/disclosure-only — zero scoring-function diffs. The two "remove unsupported
probability" commits leave no orphaned live code path (the Python properties still exist but
are provably unreachable). The Forward Ledger's actual public flip was re-checked against the
frozen-file rule directly (`forward_cohort.py`/`forward_scoreboard.py` empty diff) and by
rendering the live `/scoreboard` page: no per-source ranks, no role field, only aggregate
consensus, no superiority language anywhere. 428 tests pass.

**Competition Proof foundation / CSP hardening (M3):** fail-closed on every axis reachable —
adversarially tried to force a claim through with a loosened regression cap and it still
correctly blocked. Zero competitor names or private-capture identifiers reachable from any
public surface (regex/NFKC-normalized leak guard tested against fullwidth/alias variants).
Zero path into `rank_v1.py`/`model.py`. Empty evidence produces zero public claims — the one
committed evidence run is `research_only` and actually shows ValuCast *behind* its baseline
(0.306 vs 0.277 MAE), so no claim is authorized, correctly. Complexity judged proportionate to
what a claim-authorization system needs. CSP commit tightened policy, didn't touch scoring.
392 tests pass.

**Comp math / pitcher role separation / distance-not-percentage (S1):** Power/Contact/Approach
axis mapping verified correct against real players (traced Tyler Black's three comps by hand).
Starter/reliever pools are provably disjoint — zero rows appear in both across the full
artifact. Ambiguous-role suppression fires on real data (confirmed both a suppressed case and
a working reliever case). Similarity is a real Euclidean z-space distance, never rendered as a
percentage or calibrated probability — methodology copy explicitly disclaims the conversion.
100/100 tests pass.

**Model isolation / artifact regeneration / refresh compatibility (S2):** zero non-test
importer of `prospects/comps.py` anywhere in the codebase; the artifact is read at exactly two
display-only sites in `app.py`, both explicitly commented "do not feed ValuCast Value or
rank." Actually ran the real build script offline and confirmed it reproduces the committed
7/19 artifact exactly, and reproduces a correct fresh artifact against master's current 7/20
data. No collision with the daily workflow's own build steps.

**Player-page / share-graphic parity / mobile / a11y / hold-gates (S3):** hitter and pitcher
comp data confirmed byte-identical between the live HTML page and the Pillow-rendered PNG for
two real players. PNG panel-height formula verified correct for both fixed line counts; long
names ellipsize rather than clip. Mobile CSS collapses correctly at the existing breakpoint.
No unlabelled new interactive controls. (The one hold-gate gap found is P1 #2 above, on the
per-team page specifically — the top-level `/backfields` overview correctly respects the hold.)

**Farm-system arithmetic (S4):** top-20 value concentration, hitter/pitcher balance, buy list,
top-prospects list, and risers filter/sort all hand-recomputed correctly against real data for
four orgs. (The one real defect found is P1 #3 above — the Level Distribution scope mismatch.)

**Terminology / misread risk across all new copy (S5):** "ValuCast Value" naming, Peak Outlook
labels, and trade-disclosure copy are consistent word-for-word across every surface they
appear on (page + PNG). No competitor-beating language anywhere in new copy. (The two findings
above — CSS class reuse and the scouting-fallback gap — are the only items this pass surfaced.)

---

## Recommended next steps, given "what remains"

1. Fix P1 #2 (hold-gate bypass) and P1 #3 (Level Distribution scope) before merge — both are
   small, localized, and already have exact reproduction steps above.
2. Don't "fast-forward" the merge — rebase/merge master onto the branch first and take the
   branch's side of `data/models/valucast_prospect_comps.json` on the conflict (P2 #5), then
   regenerate it against current data per your own plan (P2 #6 confirms the build script does
   this correctly today).
3. The P0 is, in my judgment, not a real blocker — see the note under finding #1. Worth a
   30-second sanity read of plan 032's actual content if you want a second set of eyes, but I
   wouldn't hold the merge on it.
4. P2 #7-#9 are all low-urgency, currently-latent design gaps — worth a follow-up pass, not
   worth blocking this branch.
