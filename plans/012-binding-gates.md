# Plan 012: Gates and disclaimers that actually bind — enforce the prospects readiness gate, travel the arrival-caveat with the receipts PNG, split the ledger Wins tile

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat ac20b1f2..HEAD -- app.py templates/receipts.html templates/track_record.html templates/partials/rankings_table_dynasty.html web/public_snapshot_store.py static/style.css`
> This plan was written at commit `ac20b1f2` (the commit the 7/9 claims-register
> audit was taken against — its line refs are accurate to that commit, NOT to the
> older `72e68864` the sibling plans cite). If any in-scope file changed since,
> re-read the "Current state" excerpts against the live code before proceeding; on
> a mismatch with an excerpt, treat it as a STOP condition.
>
> **In-flight receipts work — RE-VERIFY AT HEAD**: the working tree has
> UNCOMMITTED receipts changes in `prospects/call_up_receipts.py`,
> `tests/test_call_up_receipts.py`, and `templates/receipts.html` (an
> at-promotion rescoring fix landing in parallel). Before editing `receipts.html`
> or the receipts PNG, run `git status` and `git diff -- templates/receipts.html`
> and re-read the CURRENT `templates/receipts.html:32` disclaimer line — Step 2
> copies that exact sentence into the PNG, so it must match whatever is on the
> page at execution time, not the excerpt frozen below. If the disclaimer wording
> has changed, mirror the new wording. Do NOT stage or revert the pre-existing
> receipts changes; touch only the lines this plan names.

## Status

- **Priority**: P1
- **Effort**: M (three independent display/gate fixes: a serving gate + banner, a PNG caveat, a template tile split)
- **Risk**: LOW (banner is additive + fails safe; PNG and tile changes are display-only, no scoring/data touched)
- **Depends on**: none (independent of plans 004/005/007; touches disjoint app.py regions and templates)
- **Category**: bug (governor not binding) + honesty (disclaimers that don't travel)
- **Planned at**: commit `ac20b1f2`, 2026-07-09

## Why this matters

ValuCast's entire pitch is pre-registered gates that actually bind and dated
disclaimers that never lie. The 7/9 claims-register audit found three places where
that promise leaks — a governor the site ignores, a caveat that gets stripped from
the object that travels, and a headline number that sums provisional into final:

**(a) The prospects readiness gate fires "not ready" and the board ships anyway.**
The build computes a per-surface verdict: `validation.surface_readiness.prospects
= false` with blocker `"Top prospect board is too pitcher-heavy for public
promotion."` (confirmed live in `data/public/public_dynasty_snapshot.json` right
now). But `_select_dynasty_store` (app.py:659-680) only ever checks
`snapshot_candidate.dynasty_ready` (which reads `surface_readiness.dynasty`) —
`surface_readiness.prospects` is read NOWHERE in app.py. The `/prospects` board
renders identically whether its own gate says ready or not.
> Embarrassment scenario (audit, verbatim): *"The pipeline computes a per-surface
> readiness verdict and explicitly fails prospects, but `_select_dynasty_store`
> (app.py:659-680) only checks `snapshot_candidate.dynasty_ready` … so the board
> renders identically whether its own gate says ready or not. ValuCast's entire
> pitch is pre-registered gates that actually bind; here a gate fires 'not ready'
> and the surface ships anyway. Anyone who fetches …-style validation (or the
> snapshot) can point to `surface_blockers.prospects` and show the site publishing
> a board its own governor rejected."*
Silently ignoring one's own governor is the brand-worst outcome. This plan
implements the **banner** option: a visible "preliminary — publication gate not
met: <blocker text>" notice on `/prospects` while the gate fails. (The audit's
alternative — downgrade the blocker to advisory so the artifact stops asserting
not-ready — is a data/governor decision that is Alex's to make post-7/13, and is a
STOP condition below, not this plan's job.)

**(b) The receipts share-card PNG omits the arrival-not-outcome caveat the page
treats as load-bearing.** `templates/receipts.html:32` carries a prominent line:
"Receipts score *arrival*, not career value — who reached the majors while we were
ahead of (or behind) the field, not whether the call-up stuck. Outcome-scored
calls live on the ledger." The share-card PNG (`_receipts_share_card_png`,
app.py:7168) reproduces the ranks and the green "+N / AHEAD" divergence but its
header line (app.py:7200) and footer (app.py:7253) omit that caveat entirely. The
PNG is precisely the object that circulates — it IS the `og:image` and the
Download-PNG target, detached from a page a re-sharer never links to.
> Embarrassment scenario (audit, verbatim): *"A sharp reader sees a permanent
> green '+66 AHEAD OF THE FIELD' card for a prospect who then slashed .180 in the
> majors and reads it as ValuCast claiming a valuation win — the same 'scoring
> arrival as if it were outcome' failure that got the receipts board caught this
> week — because the image never says the number only means 'he got called up
> while we were higher than the field.' The honest framing exists but was stripped
> from the surface that actually travels."*

**(c) The ledger "Wins" tile counts 23 provisional + 8 final as one number: 31.**
`templates/track_record.html:73-77` renders `open_toward + closed_caught_up` as a
single big green "Wins" number, with only the parenthetical "(8 all the way)" as a
signal that 74% of it is provisional (`open_toward` calls can still flip to loss;
the template's own prose says only "caught up" and "we backed off" are final).
> Embarrassment scenario (audit, verbatim): *"A sharp reader adds the tiles: 31
> Wins vs 25 Losses reads like a 55% win rate on a board that elsewhere admits …
> it can't publish a rate yet. … 23 of the 31 Wins are explicitly non-final, yet
> they're summed into the same big green number as the 8 final wins. Someone
> screenshots '31 Wins' next to the '27.9% decided-rate' buried in the artifact
> and calls the funnel misleading."*
The funnel dict already carries the two counts separately — this is a pure
template framing fix. **It does NOT touch the frozen scorecard scoring.**

## Current state

Verified at `ac20b1f2` (the audit commit). Read each cited line yourself before
editing — the in-flight receipts work may have shifted `receipts.html`.

**(a) The serving gate + store surface:**
- `web/public_snapshot_store.py:241-254` already exposes what we need — no store
  change required:
  ```python
  @property
  def surface_readiness(self) -> dict:
      return dict(self._validation.get("surface_readiness") or {})

  @property
  def surface_blockers(self) -> dict:
      return dict(self._validation.get("surface_blockers") or {})

  @property
  def dynasty_ready(self) -> bool:
      surface_readiness = self._validation.get("surface_readiness") or {}
      if "dynasty" in surface_readiness:
          return bool(surface_readiness.get("dynasty"))
      return self.ready_for_live_consumers
  ```
- `app.py:750` — `dd_store, dynasty_data_source = _select_dynasty_store(public_snapshot_store)`. `dd_store` is the module-level served store; `public_snapshot_store` (app.py:596) is the raw candidate that carries the `surface_readiness`/`surface_blockers` properties. `_select_dynasty_store` returns the SAME candidate object when it serves it, so `dd_store.surface_readiness` is valid on the served store.
- `app.py:1349-1469` — `_apply_prospect_board_context(ctx, args)` is the ONLY prospect-board context builder; it ends at `ctx["dd_rows"] = rows` (:1469). It is called from BOTH the full-page route (`index()`, app.py:4417) and the htmx route (`rankings()`, app.py:4444) — so a `ctx` key set here reaches both.
- `templates/partials/rankings_table_dynasty.html:4-5` — the established notice pattern, rendered by both `index.html` (line 233, full page) and `partials/rankings_response.html` (line 5, htmx), so a banner added here shows on both paths:
  ```jinja
  {% if mode == 'prospects' and coverage_notice %}
  <div class="notice coverage-notice" role="status">{{ coverage_notice }}</div>
  {% endif %}
  ```
- Live gate values confirmed (`data/public/public_dynasty_snapshot.json`):
  `surface_readiness = {'buys': True, 'dynasty': True, 'prospects': False}`,
  `surface_blockers.prospects = ['Top prospect board is too pitcher-heavy for public promotion.']`.
- `tests/test_public_dynasty_snapshot.py:496-565`
  (`test_snapshot_decouples_dynasty_readiness_when_only_prospect_surface_blocked`)
  already builds a store with exactly `prospects=False, dynasty=True` and exercises
  `_select_dynasty_store` — this is the fixture/pattern to model the new test on.

**(b) The receipts PNG:**
- `templates/receipts.html:32` — the disclaimer to mirror (RE-VERIFY at HEAD; excerpt at `ac20b1f2`):
  > "Receipts score *arrival*, not career value — who reached the majors while we were ahead of (or behind) the field, not whether the call-up stuck. Outcome-scored calls live on the ledger."
- `app.py:7168-7257` — `_receipts_share_card_png(receipts, misses=None, *, generated_at=None)`. Header at :7195-7202 passes `extra_line="Every prospect call-up vs the public-board consensus, both directions"`; the first section panel starts at `y = 242` (:7248); footer at :7253 is `_graphic_footer(draw, right_note="ValuCast vs the public-board consensus on every call-up")`.
- `app.py:2177-2198` — `_graphic_header(img, draw, *, headline, subtitle, extra_line=None, tagline=..., value_history=None)`. It draws `subtitle` at `y=152` and `extra_line` (green, 15px bold) at `y=183`. The section panels begin at `y=242`, leaving a ~40px band under `extra_line` and above the panel — room for one more small caption line without moving the panels.
- `app.py:2201-2216` — `_graphic_footer(draw, *, right_note=None, card_height=1350)` draws a single rounded bar with "valucast.app" left and one right-aligned `right_note`. It is shared by MANY cards, so DO NOT change its signature or layout for all of them.
- The `/receipts/share-card.png` route (app.py:7260-7271) is the og:image + Download target; `receipts.html:7,12` reference it.

**(c) The ledger Wins tile:**
- `templates/track_record.html:72-93` — the funnel `<section class="ledger-funnel">`. The Wins tile (:73-77):
  ```jinja
  <article class="ledger-tile glass ledger-tile-win">
      <span class="ledger-tile-n">{{ sc.funnel.open_toward + sc.funnel.closed_caught_up }}</span>
      <span class="ledger-tile-label">Wins</span>
      <span class="ledger-tile-sub">field came to us ({{ sc.funnel.closed_caught_up }} all the way)</span>
  </article>
  ```
  The other three tiles are Losses (`open_away`), Our retreats (`retired_we_backed_off`), Undecided (`open_flat`).
- `data/models/valucast_ahead_of_consensus_scorecard.json` funnel keys (live): `open_toward=23`, `closed_caught_up=8`, `open_away=25`, `retired_we_backed_off=55`, `open_flat=78`, `resolved_called_up_or_graduated=0`, `summary.decided_rate=0.279`. (Numbers drift daily — use the KEYS, never hardcode a count.)
- `static/style.css:4395-4407` — `.ledger-funnel` is a `repeat(4, ...)` grid (2-col on mobile, :4462). `.ledger-tile-win .ledger-tile-n` is green (`--c-signal`), `-loss` clay, `-open` slate. `.ledger-tile-sub` is the small muted caption.

Repo conventions: templates are Jinja2; notices use `class="notice"` + `role="status"`; no new CSS variables — reuse existing tile classes; the PNG builders are deterministic Pillow (no new fonts/deps).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| App + snapshot tests | `python -m pytest -q tests/test_app.py tests/test_public_dynasty_snapshot.py tests/test_mlb_track_record.py tests/test_positional_share_card.py tests/test_call_up_receipts.py` | all pass |
| Receipts PNG renders | `python -c "import app; c=app._build_receipts_page_context(); png=app._receipts_share_card_png(c['receipts'], c['misses'], generated_at=c['receipts_generated_at']); open('/tmp/rc.png','wb').write(png); print(len(png))"` | prints a byte count > 0, no exception |
| Ledger template renders | `python -m pytest -q tests/test_mlb_track_record.py` | all pass (this suite renders `/ledger`) |
| Full suite (final gate) | `python -m pytest -q` | all pass; then `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json` (pytest dirties it as a byproduct — NEVER commit it) |

## Scope

**In scope** (the only files you should modify):
- `app.py` — the `_apply_prospect_board_context` banner logic (:1349-1469 region) and the receipts PNG caveat (:7168-7257 region only).
- `templates/partials/rankings_table_dynasty.html` — add the preliminary banner block next to the existing `coverage_notice` block.
- `templates/track_record.html` — split/relabel the Wins tile (:72-93 funnel region only).
- `static/style.css` — ONLY if the split Wins tile needs a minor style tweak (prefer reusing existing `.ledger-tile-*` classes; a CSS edit is optional, not required).
- Tests: `tests/test_app.py` (banner), `tests/test_positional_share_card.py` OR `tests/test_call_up_receipts.py` (PNG caveat — pick whichever already imports the receipts PNG path), `tests/test_mlb_track_record.py` (tile).

**Out of scope** (do NOT touch):
- `scripts/build_ahead_of_consensus_scorecard.py` and `prospects/ahead_of_consensus.py` — the AOTC scorecard scoring rules are FROZEN (pre-registered 7/2) until the ~7/13 gate unlock. Gap (c) is DISPLAY ONLY: the funnel dict already separates `open_toward` from `closed_caught_up`; you re-frame them in the template, you do not recompute anything.
- `web/public_snapshot_store.py` — it already exposes `surface_readiness`/`surface_blockers`; no store change is needed. If you think you need one, STOP and report (you probably want to read the properties, not add one).
- The pre-existing uncommitted receipts changes in `prospects/call_up_receipts.py`, `tests/test_call_up_receipts.py`, `templates/receipts.html` — leave those diffs alone except for the exact caveat-mirroring read in Step 2. Do NOT `git checkout` or `git stash` them.
- The PNG cache key / `_png_cache_generation` (that is a separate audit gap owned by another plan — a staleness-key fix, not a disclaimer fix). Do not fold it in here.
- The `call_up_date` vs `actual_call_up_date` display gap and the board-count-disclosure gap (both separate audit findings) — out of this theme.

## Git workflow

- Work directly on `master` locally (repo convention — direct-to-main), but **do NOT push**: master auto-deploys valucast.app via Render. Commit locally; the reviewer gates the push.
- NEVER `git add -A` or `commit -am` (repo guardrail — parallel sessions leave untracked files, and there is uncommitted receipts work in the tree you must not sweep up). Stage each in-scope file explicitly by path.
- Before committing, `git status` and confirm the ONLY staged files are the in-scope ones above — the uncommitted `prospects/call_up_receipts.py` / `tests/test_call_up_receipts.py` / `templates/receipts.html` receipts work must NOT be in your commit unless you deliberately edited `receipts.html` (you should not need to for this plan — the caveat text is READ from it, copied into the PNG).
- Commit message style (from git log): short imperative subject, e.g. `Bind prospects readiness gate; travel arrival caveat on receipts PNG; split ledger Wins tile`.

## Steps

### Step 1: Surface the prospects readiness blocker as a preliminary banner

The board must visibly say "preliminary" while its own gate fails, instead of
shipping as if ready.

1. In `_apply_prospect_board_context` (app.py:1349), just before `ctx["dd_rows"] = rows` (:1469), read the gate off the served store and set a context key when it fails:
   ```python
   # Bind the prospects publication gate: the build computes a per-surface
   # readiness verdict (surface_readiness.prospects) but serving only ever
   # honored the dynasty verdict. When the governor marks the prospect board
   # not-ready, say so on the surface instead of shipping it as if it passed
   # (7/9 claims-register: a gate that fires "not ready" and ships anyway is
   # the brand-worst failure). Display-only — never reorders or drops rows.
   if dd_store.surface_readiness.get("prospects") is False:
       blockers = dd_store.surface_blockers.get("prospects") or []
       blocker_text = "; ".join(str(b) for b in blockers) or "not yet promoted for public view"
       ctx["prospect_gate_notice"] = (
           f"Preliminary — publication gate not met: {blocker_text}"
       )
   ```
   Notes:
   - Use `is False`, not falsy: a MISSING `prospects` key (older snapshot schema, or an unavailable store whose `surface_readiness` is `{}`) must NOT raise a banner. Only an explicit `False` verdict does. `.get("prospects")` returns `None` when absent → `None is False` is `False` → no banner. Correct.
   - `dd_store` is the module-level served store (app.py:750). It exposes `surface_readiness`/`surface_blockers` (they are properties on `PublicSnapshotStore`). The `_UNAVAILABLE_DYNASTY_STORE` null object returns `{}` for both (its validation is empty) → no banner, which is right (the "unavailable" path already shows its own handling upstream at index():4404).
2. In `templates/partials/rankings_table_dynasty.html`, immediately after the existing `coverage_notice` block (:4-6), add a sibling block using the same notice pattern:
   ```jinja
   {% if mode == 'prospects' and prospect_gate_notice %}
   <div class="notice prospect-gate-notice" role="status">{{ prospect_gate_notice }}</div>
   {% endif %}
   ```
   Reuse the existing `.notice` styling; no new CSS needed. (If you want a subtle amber cue you MAY add a `.prospect-gate-notice` rule in `static/style.css`, but it is optional — the base `.notice` is sufficient and lower-risk.)

**Verify**:
- `python -m pytest -q tests/test_public_dynasty_snapshot.py tests/test_app.py` → all pass.
- Manual context check:
  ```
  python -c "import app; from werkzeug.datastructures import ImmutableMultiDict as I; ctx=app._build_dynasty_context(I([('mode','prospects')])); app._apply_prospect_board_context(ctx, I([('mode','prospects')])); print('BANNER:', ctx.get('prospect_gate_notice'))"
  ```
  With today's snapshot (prospects=False) this must print a banner string containing "pitcher-heavy". If the served store's `dynasty` surface is not available at all in a bare test process, note it and rely on the unit test below instead.

### Step 2: Travel the arrival-not-outcome caveat with the receipts PNG

The caveat that exists on the page must also live on the image that circulates.

1. RE-READ `templates/receipts.html` at HEAD and copy the CURRENT arrival-caveat wording (the line at ~:32). Condense it to a single short line that fits the card width (~940px at the header caption size), preserving the core claim, e.g.:
   `"Scores arrival vs the field, not career outcome — outcome calls live on the ledger"`
   Keep it faithful to the page wording; if the page wording changed under the in-flight receipts work, mirror the new wording's meaning.
2. In `_receipts_share_card_png` (app.py:7168), render this caveat on the card. Prefer the **header band** so it sits with the divergence claim it qualifies. Two safe options — pick the one that reads cleanly without overlapping the first panel (panels start at `y=242`):
   - **Preferred**: draw the caveat as its own muted caption between `extra_line` (y=183) and the first panel (y=242), directly inside `_receipts_share_card_png` after the `_graphic_header(...)` call:
     ```python
     _draw_receipts_caveat = "Scores arrival vs the field, not career outcome - outcome calls live on the ledger"
     draw.text((48, 210), _graphic_fit_text(draw, _draw_receipts_caveat, _graphic_font(14), 984),
               fill=_GRAPHIC_PALETTE["muted"], font=_graphic_font(14))
     ```
     Then, so the caption does not collide with the panel, nudge the section start from `y = 242` to `y = 234`? — NO: 210+14px caption clears 242 with margin; keep `y = 242`. Verify visually via the render command below.
   - **Fallback** (if the header band is too tight after the in-flight changes): append the caveat to the footer instead by rendering a second muted line just ABOVE the footer bar inside `_receipts_share_card_png` (do NOT change `_graphic_footer`'s shared signature). E.g. draw the caveat at `y = card_height - 92` before the footer call.
   Use ASCII hyphens (`-`) not em-dashes in the PNG string (the Pillow font + Windows PS5.1 tooling choke on non-ASCII; the rest of this file already uses `-` in card strings — match it).
3. Do NOT change the header `extra_line` or the footer `right_note` themselves (those are separate claims); you are ADDING the caveat, not replacing existing copy.
4. Note in a code comment that the PNG caveat and `receipts.html`'s disclaimer must stay in sync (they are two renderings of the same load-bearing claim).

**Verify**:
- Render command (from the Commands table) writes a PNG with no exception and non-zero size.
- Grep: `grep -n "arrival" app.py` → your caveat line present in `_receipts_share_card_png`.
- Eyeball the caption position: `python -c "import app; c=app._build_receipts_page_context(); open('/tmp/rc.png','wb').write(app._receipts_share_card_png(c['receipts'], c['misses'], generated_at=c['receipts_generated_at']))"` then open `/tmp/rc.png` — the caveat line must be legible and must NOT overlap the first "AHEAD OF THE FIELD" panel.
- `python -m pytest -q tests/test_positional_share_card.py tests/test_call_up_receipts.py` → all pass.

### Step 3: Split the ledger "Wins" tile into final vs provisional (display only)

Stop summing 23 provisional `open_toward` into the same green number as 8 final
`closed_caught_up`. Do this WITHOUT touching the frozen scorecard builder — the
funnel dict already carries both counts.

Choose ONE of these two framings (both satisfy the audit; pick the one that keeps
the 4-tile grid balanced — Option A keeps four tiles and is lower-risk):

- **Option A — relabel + two-part sub (recommended, keeps the grid intact)**: change the Wins tile so the headline number and label no longer assert 31 final wins. Relabel the big number "Leading" (or keep the sum but make the sub explicit), and split the caption into final vs open:
  ```jinja
  <article class="ledger-tile glass ledger-tile-win">
      <span class="ledger-tile-n">{{ sc.funnel.open_toward + sc.funnel.closed_caught_up }}</span>
      <span class="ledger-tile-label">Leading</span>
      <span class="ledger-tile-sub">{{ sc.funnel.closed_caught_up }} final &middot; {{ sc.funnel.open_toward }} trending our way</span>
  </article>
  ```
  This keeps four tiles, matches the audit's "8 final + 23 trending" suggestion, and removes the word "Wins" from a number that is 74% provisional.
- **Option B — two separate tiles**: replace the single Wins tile with two — "Field caught up (final): {{ sc.funnel.closed_caught_up }}" and "Field moving to us (open): {{ sc.funnel.open_toward }}". If you choose this, the grid becomes 5 tiles; verify `.ledger-funnel` (`repeat(4, ...)`, mobile `repeat(2, ...)`) still wraps cleanly, and adjust the grid to `repeat(5, ...)` (desktop) or a `repeat(3, ...)` layout ONLY if it looks broken. Mobile (2-col) already wraps any count. This is more layout risk — prefer Option A unless Alex has asked for two tiles.

Do NOT change `sc.funnel.*` values, the scorecard artifact, or the builder. The
"Losses / Our retreats / Undecided" tiles are unchanged.

**Verify**:
- `python -m pytest -q tests/test_mlb_track_record.py` → all pass (renders `/ledger`).
- `grep -n "Wins\|Leading\|closed_caught_up\|open_toward" templates/track_record.html` → the headline number is no longer labeled a bare "Wins", and both `closed_caught_up` and `open_toward` appear in the tile (final vs trending are visibly distinct).
- Confirm the frozen builder is untouched: `git status` shows NO change to `scripts/build_ahead_of_consensus_scorecard.py` or `prospects/ahead_of_consensus.py`.

## Test plan

- `tests/test_app.py`: +1 — banner binding. Build a `PublicSnapshotStore` (or monkeypatch `app.dd_store`) with `surface_readiness={'dynasty':True,'prospects':False}` and `surface_blockers={'prospects':['Top prospect board is too pitcher-heavy for public promotion.']}`, call `_apply_prospect_board_context(ctx, ImmutableMultiDict([('mode','prospects')]))`, assert `ctx['prospect_gate_notice']` contains "Preliminary" and "pitcher-heavy". Add a second assertion: with `surface_readiness={'prospects':True}` (or the key absent), `ctx.get('prospect_gate_notice')` is falsy — the banner does NOT fire when the gate passes or is unknown. Model the store construction on `test_snapshot_decouples_dynasty_readiness_when_only_prospect_surface_blocked` in `tests/test_public_dynasty_snapshot.py:496`.
- `tests/test_positional_share_card.py` or `tests/test_call_up_receipts.py`: +1 — PNG caveat. Render the receipts PNG (via `app._receipts_share_card_png(...)` with a minimal receipts list) and assert it returns non-empty PNG bytes without raising. A text-in-image assertion is not practical; instead grep the source in a Done-criteria check that the caveat string literal exists in `_receipts_share_card_png`.
- `tests/test_mlb_track_record.py`: extend the existing `/ledger` render test (or add one) to assert the rendered HTML no longer contains a bare `>Wins<` label on a tile whose number is `open_toward + closed_caught_up`, and DOES contain both the final count and the trending count distinctly (e.g. assert the "final" / "trending" sub-text substrings are present).
- Final: `python -m pytest -q` all green, then `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json`.

## Done criteria

- [ ] `python -m pytest -q` exits 0 (byproduct file restored after).
- [ ] `grep -n "prospect_gate_notice" app.py templates/partials/rankings_table_dynasty.html` → set in `_apply_prospect_board_context`, rendered in the partial (2+ hits total).
- [ ] `grep -n "surface_readiness" app.py` → now read for `prospects` in the board context (previously read nowhere in app.py for prospects).
- [ ] `grep -n "arrival" app.py` → the caveat literal present in `_receipts_share_card_png`; the receipts PNG render command succeeds with non-zero bytes.
- [ ] `grep -n "closed_caught_up\|open_toward" templates/track_record.html` → both appear in the Wins/Leading tile; the big number is no longer labeled a bare "Wins".
- [ ] `git status` shows only in-scope files modified; the uncommitted receipts work (`prospects/call_up_receipts.py`, `tests/test_call_up_receipts.py`, and — unless you deliberately mirrored a changed disclaimer — `templates/receipts.html`) is NOT in your commit; the pytest byproduct file is restored; `scripts/build_ahead_of_consensus_scorecard.py` and `prospects/ahead_of_consensus.py` are untouched.
- [ ] New tests from the test plan exist and pass.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- **Alex's pending pitcher-heavy review resolves the gate first.** This banner is
  the right fix ONLY while `surface_readiness.prospects` is genuinely `False`. If,
  before you execute, the governor has been changed so the prospect board is
  marked ready (`surface_readiness.prospects = true` in a fresh
  `data/public/public_dynasty_snapshot.json`), OR the pitcher-heavy blocker has
  been downgraded to advisory (the audit's alternative option, a post-7/13
  decision that is Alex's to make), then Step 1's banner would never fire and is
  moot — STOP on Step 1 and report; still do Steps 2 and 3. Check with:
  `python -c "import json;print(json.load(open('data/public/public_dynasty_snapshot.json'))['validation']['surface_readiness'])"`.
- `web/public_snapshot_store.py` no longer exposes `surface_readiness`/`surface_blockers` as properties (someone refactored the store) — re-read before wiring the banner.
- `_apply_prospect_board_context` no longer ends at `ctx["dd_rows"] = rows`, or is no longer the shared builder for both `index()` and `rankings()` — re-locate the single prospect-context seam before inserting the banner key.
- The `receipts.html` disclaimer line (arrival-not-outcome) has been REMOVED (not just reworded) by the in-flight receipts work — if the page no longer makes the arrival caveat, do NOT invent one for the PNG; report the discrepancy (the page and PNG must agree, and the page is the source of truth).
- Touching gap (c) would require editing `scripts/build_ahead_of_consensus_scorecard.py` or the funnel computation — it must not. If the funnel dict does NOT already carry `open_toward` and `closed_caught_up` separately, STOP (the scoring is frozen; you cannot recompute).

## Maintenance notes

- **The banner is the enforcement half of a two-sided decision.** The audit offered
  two options for gap (a): enforce (this banner) OR downgrade the blocker to
  advisory. This plan does the honest-now thing (never ship a rejected board
  silently) without pre-empting Alex's product call. When the pitcher-heavy
  concern is resolved post-7/13, the banner self-clears the moment
  `surface_readiness.prospects` flips to `true` — no code change needed. If Alex
  instead decides pitcher-heavy is non-blocking for public view, the governor
  should stop emitting the blocker (a builder-side change, out of this plan), and
  the banner again self-clears. Either way the banner is correct in the interim.
- **Caveat sync (gap b):** the receipts PNG caveat and `receipts.html`'s
  arrival-not-outcome disclaimer are two renderings of one load-bearing claim.
  A future edit to one must update the other; the code comment added in Step 2
  flags this. The page is the source of truth.
- **Display-only ledger fix (gap c):** the funnel counts come straight from the
  frozen scorecard artifact. If the AOTC scoring rules change after the ~7/13
  unlock and the funnel gains/loses a lifecycle bucket, revisit the tile labels —
  but the split (final vs provisional) stays correct as long as `closed_caught_up`
  = final and `open_toward` = provisional, which is the scorecard's own semantics.
- Reviewer scrutiny: confirm Step 1 uses `is False` (not falsy) so a missing key
  or unavailable store never raises a spurious "gate not met" banner; and confirm
  no scoring/builder file is in the diff for gap (c).
