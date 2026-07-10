# Plan 022: Trade Analyzer V1 — a free, no-login /trade page that renders the board's verdict on any two-sided trade from existing served values

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> ```
> git log -1 --format=%h    # baseline for this plan is 1ec235a0
> git diff --stat 1ec235a0..HEAD -- app.py web/public_snapshot_store.py web/public_snapshot_models.py templates/base.html templates/partials/_footer_provenance.html templates/partials/_board_nav.html static/style.css
> git status --short
> ```
> This plan was written against `1ec235a0`. All "Current state" line refs are
> accurate to that commit. If any in-scope file changed since, re-read the cited
> excerpt against the live code before proceeding; on a mismatch with an excerpt,
> treat it as a STOP condition. In particular the PNG cache-key config
> (`_PNG_CACHE_PARAMS`, app.py:153) and the `gaps()`/`movers()` route shapes are
> the load-bearing reuse surfaces — re-verify them at HEAD.
>
> **This is a NEW-FEATURE plan, not a fix.** Unlike the batch-1/2/3 honesty plans,
> nothing here is frozen-file-blocked and there is no pre-existing in-flight work
> in these files. But the same guardrails apply: master auto-deploys, so do NOT
> push; the reviewer gates the push.

## Status

- **Priority**: P2 (product growth, not a correctness/honesty leak — but it is the
  most-requested thing the account does by hand in mentions, so it earns a slot)
- **Effort**: M (one new route + one context builder + one template + one JS island
  reusing the existing JSON payload + one PNG builder + a one-line cache-key add +
  footer link). **Honest scope note**: the full ask (verdict page + share PNG +
  form-input labels + footer affordance) is at the TOP of M and tips toward L if
  the PNG fights. The **cut-to-M lever is the PNG** (Step 6): ship the verdict page
  first (Steps 1-5, 7-8), and treat `/trade/share-card.png` as a fast-follow that
  can be dropped or deferred without touching the core. The verdict page is the
  product; the PNG is the amplifier. See "Scope" for the explicit cut line.
- **Risk**: LOW-MEDIUM. The page is read-only over existing served values (no new
  math beyond sums, no scoring touched, no data written, no accounts/DB). The ONE
  sharp edge is the PNG cache key (a cross-user trade-poisoning bug if `give`/`get`
  are not added to the cache vocabulary — Step 6 handles it explicitly and it is a
  STOP condition if skipped).
- **Depends on**: none. Coordinates with nothing in flight. (Reads the same
  `dd_store` and `/api/value-map-players` payload the board/map already serve.)
- **Category**: feature (product — trade analyzer, free tier)
- **Planned at**: commit `1ec235a0`, 2026-07-10
- **Execution window**: anytime. No frozen-file dependency; no daily-build timing.

## Why this matters

The account already does this by hand: a follower literally asked "Clark for
De Vries?" tonight, and the reply is a manual lookup of two served ValuCast
numbers plus a one-line verdict. **`/trade` productizes that exact interaction** —
two sides ("You give" / "You get"), add players via the existing search, and the
page renders the board's verdict computed entirely from values ValuCast already
serves. It is the natural top-of-funnel: shareable, no login, and it puts the
0-100 dynasty number to work on the one question every dynasty manager actually
has. It is also on-brand for the standing product line — **the analyzer is free,
like every ValuCast number** ("signal free forever"); the league-aware version
(roster import, league settings, contention window) is the future premium tier and
is **explicitly out of scope** here, carried only as a zero-infrastructure "coming"
affordance (a `mailto:` in the footer style the site already uses).

The honesty bar is the same as everywhere else on the site: **the verdict must not
claim more precision than the numbers support.** Three features enforce that and
are non-negotiable for v1 (Step 4): (a) a margin inside the noise says "call it
even" instead of minting a false-precision winner; (b) unequal player counts show
a static "fewer, better players usually win dynasty trades" note; (c) a trade that
crosses the MLB/prospect universe boundary discloses that the two 0-100 scales are
separate normalizations — the exact language the methodology already uses.

## Current state

Verified against the live files at `1ec235a0`. Read each cited line yourself
before building on it.

### There is NO JSON search endpoint — but there is a reusable JSON player payload

- **Search today is server-rendered, not an autocomplete API.** The board routes
  take a `search` query param and re-render the whole ranked table filtered by
  name. `dd_store.filter(..., search=...)` does the folding
  (`web/public_snapshot_store.py:295-297`):
  ```python
  if search:
      query = fold(search)
      results = [row for row in results if query in fold(row.name)]
  ```
  There is no `/api/search`, no typeahead route. Do NOT invent a new search route —
  reuse the JSON payload below and fold client-side.
- **The accent-tolerant folder** is `web/search_fold.py:12`:
  ```python
  def fold(text: str | None) -> str:
      decomposed = unicodedata.normalize("NFKD", str(text or ""))
      return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()
  ```
  It is imported in app.py as `fold_search` (app.py:57). "Héctor Rodríguez" matches
  "hector rodriguez" because both sides are folded before the substring check.
- **The reusable candidate list** is the value-map JSON payload, already served and
  memoized. `/api/value-map-players` (app.py:6701-6708) returns
  `{"players": [...], "count", "generated_at"}` where each item is built by
  `_value_map_players` (app.py:6656-6683):
  ```python
  payload.append({
      "id": row.id, "name": row.name, "age": row.age,
      "value": row.dynasty_value, "position": primary, "group": group,
      "player_type": row.player_type, "prospect_rank": row.prospect_rank,
  })
  ```
  This is exactly the slim shape a client-side autocomplete needs: `id`, `name`,
  `value`, `position`, `player_type` (mlb/prospect), `prospect_rank`. It is
  `dd_store`-derived (spans BOTH universes) and cached on the DD generation
  (`_value_map_payload`, app.py:6639-6653). **Caveat, verified**: it DROPS any row
  with `age is None or dynasty_value is None` (app.py:6661) — a handful of players
  may be unsearchable via this list. That is acceptable for v1 (search is a
  convenience; the server resolves the authoritative row by id). Note it; do not
  widen the payload in this plan.

### The authoritative id -> row resolution already exists — `dd_store.get_by_id`

- **`web/public_snapshot_store.py:271-272`**:
  ```python
  def get_by_id(self, row_id: str) -> PublicSnapshotRow | None:
      return self._by_id.get(row_id)
  ```
  O(1), returns `None` for unknown ids. This is the resolution surface for `/trade`
  — cleaner than `/compare`'s `next((row for row in rows if row.id == pX), None)`
  linear scan over the top-200 board slice (app.py:8238-8239), which would MISS any
  player outside the top 200. **Use `get_by_id`, not a board-row scan** — a trade
  can involve any player, not just a top-200 one.
- **The row object (`PublicSnapshotRow`, web/public_snapshot_models.py:60-104)**
  carries every display field the verdict needs — no new computation:
  - `id`, `name`, `team`, `player_type` (`"mlb"` | `"prospect"`), `role`,
    `positions`, `level`, `eta`/`eta_display` (props at :106-122).
  - `value` / `dynasty_value` (0-100 float; prop at :110-112), `rank` /
    `dynasty_rank` (:106-108), `prospect_rank: int | None` (:90).
  - `confidence` (:72) — coerced to `{"level": "<word>"}` by `_coerce_confidence`
    (web/public_snapshot_models.py:707-713). **Verified: in the served data
    `confidence` is ALWAYS `{"level": "high"|"medium"|"low"}`** (never a bare
    string, never carries a numeric `range`). So the confidence word is
    `row.confidence["level"]` — read it that way, and do NOT rely on any
    `confidence.range`/`value_range` (the `/export` path reads those but they are
    empty on today's data).
  - `is_prospect` property (:132-134): `self.player_type == "prospect"`.
  - **`tier` is ALWAYS `None` on the served row** (web/public_snapshot_models.py:80,
    verified). The request-time tier lives ONLY in the `_dynasty_metadata(settings)`
    tiers map (`tiers[row.id]`, app.py:926-958), not on the row. **v1 decision: the
    per-player line shows value + rank + confidence + momentum and OMITS tier** (the
    brief lists "tier" but `row.tier` is dead; pulling the map is extra coupling for
    marginal value). If a tier badge is wanted, take it from
    `_, tiers = _dynasty_metadata(parse_league_settings(args)); tiers.get(row.id)` —
    never `row.tier`. Treat adding tier as an OPTIONAL polish, not core.
  - **Uncertainty band (prospect-only, verified):** `uncertainty_context`
    (:467-470) reads `prospect_components["uncertainty"]` — a dict with `band`,
    `lower`, `upper`; `uncertainty_label` (:472-480) renders `"<Band> band:
    <lower>-<upper>"`. **There is NO equivalent per-row error bar on MLB rows**
    (`prospect_components` is empty for MLB). So a per-player numeric noise band is
    NOT uniformly available across both universes — Step 4a must use a fixed
    heuristic tolerance, not a false per-row band (see Step 4a).
- **`/compare` (app.py:8227-8266)** is the closest existing analog and proves the
  pattern: it resolves two ids against `dd_store` rows and passes `dynasty_dollars`,
  `tiers` from `_build_dynasty_context` into a compare template. **Read it as the
  reference**, but for `/trade` resolve via `get_by_id` (arbitrary players) and do
  NOT rebuild the full board context per request unless you need the `tiers` map.

### The 0-100 scale disclosure copy already exists — mirror it, don't invent it

- **`templates/methodology.html:52-64`** has the canonical language under
  `id="dynasty-value-scale"`:
  > "MLB players and prospects are each run through their own 0-100 normalization
  > and then aligned at the top of the board. We do not claim a single
  > unit-reconciled calibration across the two universes — treat a prospect's
  > number and a big-leaguer's number as **comparable in ballpark, not to the
  > decimal**."
  The cross-universe verdict copy (Step 4c) must say the same thing and link to
  `/methodology#dynasty-value-scale`. Do NOT mint a different claim.

### Recent-form momentum: load-and-key pattern already established

- **`app.py:1392-1404`** (`_apply_prospect_board_context`) loads
  `data/models/valucast_recent_form_signal.json`, builds `form_by_key` from the
  `heating_up` + `cooling_off` arrays keyed by `_identity_key(mlbam_id, role)`, then
  maps `row.id -> entry` via `_row_identity_key(row)`:
  ```python
  recent_form = _load_artifact(... "valucast_recent_form_signal.json") or {}
  form_by_key = {}
  for entry in (recent_form.get("heating_up") or []) + (recent_form.get("cooling_off") or []):
      key = _identity_key(entry.get("mlbam_id"), entry.get("role"))
      if key:
          form_by_key[key] = entry
  ctx["momentum_by_id"] = {row.id: form_by_key[key] for row in rows if (key := _row_identity_key(row)) in form_by_key}
  ```
  **The brief mentions `by_identity`** — note the recent-form file exposes
  `heating_up`/`cooling_off` arrays (this load path), whereas `by_identity` is the
  shape used by the intelligence route (app.py:5060-5061) and the call-up pulse.
  Use the `heating_up`/`cooling_off` load pattern above (the one the board itself
  uses) so /trade momentum matches the board exactly. Momentum is a **when-present**
  label: only prominent movers (top-25 heating/cooling) have an entry, so most rows
  will have no momentum chip — that is correct and honest (do not fabricate one).
- `_identity_key` and `_row_identity_key` are existing helpers (grep app.py to
  confirm their signatures at HEAD before reusing).

### The PNG share-card system + its cache (the one sharp edge)

- **1080x1350 Pillow cards**, RGB mode, self-hosted fonts (plan 008). Exemplars:
  `_receipts_share_card_png` (app.py:7206-7332) and `_movers_share_card_png`
  (app.py:6976-7057). Both: `Image.new("RGB",(1080,1350),bg)` ->
  `_graphic_fill_background(img)` -> `ImageDraw.Draw` -> `_graphic_header(...)` ->
  section panels -> `_graphic_footer(...)` -> `img.save(out, "PNG", optimize=True)`.
  Receipts is the closest layout (two-sided AHEAD/BEHIND panels) — model the trade
  card's GIVE/GET split on it.
- **Helper signatures (verified):**
  - `_GRAPHIC_PALETTE = {...}` (app.py:2000) — keys incl. `bg`(18,19,31),
    `card`, `card_2`, `border`, `green`/`teal`(52,226,196), `slate`/`blue`,
    `clay`(208,116,92), `text`(231,233,240), `muted`(150,151,166). Convention: teal
    = favorable/positive, clay = unfavorable/negative, slate = structure (ranks).
  - `def _graphic_header(img, draw, *, headline, subtitle, extra_line=None, tagline="Ahead of the Curve", value_history=None)` (app.py:2198).
  - `def _graphic_footer(draw, *, right_note=None, card_height=1350)` (app.py:2222)
    — SHARED across many cards; do NOT change its signature.
  - `def _graphic_font(size, *, bold=False, serif=False, mono=False)` (app.py:2263, lru_cached).
  - `def _graphic_fit_text(draw, text, fnt, max_width)` (app.py:2314) — truncates to width.
  - `def _graphic_wrap_text(draw, text, fnt, max_width, max_lines=3)` (app.py:2324).
- **ASCII-only rule in card strings (load-bearing, verified app.py:7246-7247):**
  "the Pillow brand font + Windows PS5.1 tooling choke on em-dashes." Every string
  drawn on the PNG must be ASCII — use `" - "` not em-dashes, no `middot`/smart
  quotes/non-ASCII glyphs. (The newest cards — movers/receipts — deliberately use
  ASCII hyphens; follow them, not the older positional card's `middot`.)
- **The PNG route return pattern (app.py:7335-7349):** `make_response(png)` +
  `Content-Type: image/png` + `Content-Disposition: inline; filename="..."`. The
  route does NOT set `Cache-Control` — `_maybe_cache_png` injects it centrally.
- **THE CACHE KEY — this is the poisoning risk.** `_png_cache_key()` (app.py:188-198):
  ```python
  return (
      _png_cache_generation(),          # dd_store.generated_at | store.as_of | buy_store.generated_at
      request.path,
      tuple(sorted((k, v) for k, v in request.args.items(multi=True)
                   if k in _PNG_CACHE_PARAMS or k in _PNG_CACHE_PREFIXED_KEYS)),
  )
  ```
  The key is `(generation, path, ALLOWLISTED params)` — **NOT the full query
  string.** `_PNG_CACHE_PARAMS` (app.py:153-158) is a fixed frozenset that does
  **NOT** include `give` or `get`. **So if `/trade/share-card.png` ships without a
  cache-config change, `give`/`get` are filtered OUT of the key** — every trade
  collapses to the single key `(generation, "/trade/share-card.png", ())`, and the
  first trade rendered is cached and served to everyone. That is exactly the
  cross-user poisoning plan 007 calls "worse than the DoS." Plan 007's invariant
  (app.py:159-168): **"any param that affects rendering must be in the cache-key
  vocabulary."** Step 6 adds `give`/`get` to `_PNG_CACHE_PARAMS` — a one-line,
  plan-007-compliant fix. The generation string already carries the snapshot
  vintage, so a stale-after-refresh card self-invalidates.

### Nav, footer, base layout, mobile

- **Two nav layers.** Top `site-nav` (base.html:31-37): Board / Backfields / Map /
  Intelligence Hub / Methodology. Board-level `horizon-tabs` macro
  (`templates/partials/_board_nav.html`): up to 11 tabs (Redraft, Dynasty,
  Prospects, Backfields, Map, Movers, Gaps, Receipts, Buys, Ledger, Cards).
- **The nav went on a "diet" (7/1) and the tab bar OVERFLOWS on mobile** — there is
  a live patch for it (`static/style.css:4210-4236`, `@media (max-width:640px)`
  wrapping the tabs as pills because "6 tabs overflow the viewport ... clips the
  last one"). **Adding a top tab would resurrect that overflow.** So the smallest
  honest placement for `/trade` is a **footer link**, matching the existing
  Intelligence Hub / Ledger / Scouting Reports / Front Office Track / Send feedback
  inline links in `templates/partials/_footer_provenance.html`. **Adding `/trade`
  to `horizon-tabs` or `site-nav` is Alex's call — flag it, do not do it in this
  plan.** (See STOP conditions / Maintenance.)
- **The feedback mailto** is `valucast.feedback@gmail.com`, appearing 4x in
  `_footer_provenance.html` (one per page-mode branch, ~lines 22/29/36/43) as the
  tail of a dash-joined link list:
  ```html
  - <a href="mailto:valucast.feedback@gmail.com">Send feedback</a>
  ```
  The "League-aware version coming" affordance follows this exact pattern (a
  `mailto:` with a `?subject=`), added to the SAME branches.
- **Base layout:** `templates/base.html` (77 lines). Blocks: `title`, the OG/Twitter
  meta blocks (`og_title`, `og_description`, `og_url`, `og_image`,
  `og_image_width`, `og_image_height`, `twitter_*`), and `content` (the only body
  block). No `head`/`scripts` block — pages inline `<script>` inside `content`. A
  page: `{% extends "base.html" %}` -> OG block overrides -> `{% block content %}`
  -> import the `editorial_date` macro + `board_nav` macro -> heading -> content.
  `templates/gaps.html` and `templates/movers.html` are the closest structural
  templates to copy.
- **Context processors auto-inject** `snapshot_stale` (app.py:276-281) and
  `aotc_hold`/`receipts_hold` (app.py:284-286) into every template — available
  without passing through `render_template`. `editorial_date` is a Jinja MACRO
  (`{% from "partials/_editorial_date.html" import editorial_date %}`), not a
  context var.
- **Mobile / glass / responsive columns.** Breakpoint is **640px** (dominant).
  `.glass` (style.css:2084-2093) is for section-level containers only ("never on
  per-tile elements"). The two-column -> one-column collapse to reuse for "You
  give" / "You get" is **`.movers-grid`** (style.css:2353,
  `grid-template-columns: repeat(2, minmax(0,1fr))`) which collapses to `1fr` at
  640px (style.css:2389). Reuse `.movers-grid` directly, or clone its exact rule
  under a `.trade-grid` class. Row pattern: `.buys-list` / `.movers-row` (a CSS grid
  row that drops a column on mobile rather than shrinking). `.buys-tag`
  (style.css:2326) and `.buys-fineprint` (style.css:2310) are the small-caption
  classes for per-player lines and disclosures.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| App tests (route/render) | `python -m pytest -q tests/test_app.py` | all pass |
| Snapshot store tests | `python -m pytest -q tests/test_public_dynasty_snapshot.py tests/test_dynasty_models.py` | all pass |
| PNG cache-key tests | `python -m pytest -q tests/test_png_cache.py` (or grep `tests/` for the file that imports `_png_cache_key`; if none, add coverage there) | all pass |
| /trade page renders (empty) | `python -c "import app; c=app.app.test_client(); r=c.get('/trade'); print(r.status_code, len(r.data))"` | `200` and a byte count > 0 |
| /trade renders a verdict from params | `python -c "import app; s=app.dd_store; ids=[r.id for r in s.get_all()[:3]]; import urllib.parse as u; q=u.urlencode({'give':ids[0], 'get':','.join(ids[1:3])}); c=app.app.test_client(); r=c.get('/trade?'+q); print(r.status_code); print(b'inside the noise' in r.data or b'edge' in r.data.lower())"` | `200`, prints a bool (verdict rendered) |
| Trade PNG renders | `python -c "import app; s=app.dd_store; ids=[r.id for r in s.get_all()[:3]]; png=app._trade_share_card_png(ids[:1], ids[1:3]); open('/tmp/trade.png','wb').write(png); print(len(png))"` | non-zero byte count, no exception (adjust signature to what Step 6 defines) |
| Template smoke | `python -c "import jinja2; jinja2.Environment(loader=jinja2.FileSystemLoader('templates')).get_template('trade.html')"` | no exception |
| Full suite (final gate) | `python -m pytest -q` | ~1829+ pass, 0 fail; then restore the byproduct (below) |
| Restore pytest byproduct | `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json` | file back to HEAD (pytest dirties it — NEVER commit it) |

## Scope

**In scope** (the only files you modify or create):
- **NEW `templates/trade.html`** — the two-sided page (extends base.html).
- **`app.py`** — (i) a `_build_trade_page_context(args)` helper + a `_trade_verdict(give_rows, get_rows)` pure function; (ii) the `/trade` route; (iii) `_trade_share_card_png(...)` + the `/trade/share-card.png` and `/trade/share-card` routes (Step 6 — the cut-line item); (iv) **one-line add of `"give"`, `"get"` to `_PNG_CACHE_PARAMS`** (app.py:153). No other app.py cache/scoring region.
- **`templates/partials/_footer_provenance.html`** — add the `/trade` link and the "League-aware version coming" mailto affordance to the existing dash-joined link branches.
- **`static/style.css`** — a small `.trade-grid` (or reuse `.movers-grid`) block + minimal per-side/verdict styling. Prefer reusing `.glass` / `.buys-list` / `.movers-row` / `.buys-tag` / `.buys-fineprint`; add new rules only where those don't cover it.
- **Tests**: `tests/test_app.py` (route + verdict function + honesty features), `tests/test_png_cache.py` (the `give`/`get` cache-key entry — the poisoning guard), and a template render smoke.

**Cut line to hold Effort at M (the reviewer decides at planning time):**
- **CORE (must ship): Steps 1-5, 7, 8** — the verdict page, search-add UX, the
  three honesty features, the footer affordance. This IS the product.
- **CUT-CANDIDATE: Step 6 (the PNG)** — if the PNG fights the layout or the day
  runs long, ship the page without `/trade/share-card.png` and file it as a
  fast-follow. The page stands alone. **If you DO ship the PNG, the cache-key add
  is mandatory, not optional** (Step 6). Do not ship a `.png` route without it.
- **Secondary cut (only if still over): the momentum label (Step 3 per-player
  line)** — it is a nice-to-have "when available" chip; the value/rank/tier/
  confidence line is the core. Cut momentum before cutting an honesty feature.

**Out of scope** (do NOT touch):
- **Any league-aware / premium functionality** — roster import, league settings,
  contention window, accounts, login, payments, a database, trade-history storage.
  v1 is stateless: the trade lives entirely in the URL query params. The premium
  tier is a `mailto:` affordance ONLY.
- **`RECEIPTS_HOLD` (app.py:79)** — do not read, flip, or reference it. It is
  unrelated to this page.
- **Frozen files** — `prospects/ahead_of_consensus.py`,
  `scripts/build_ahead_of_consensus_scorecard.py` (pre-registered AOTC scoring,
  ~7/13 unlock). This plan does not need them.
- **Any DD (`dd_*`) feed** — ValuCast is DD-independent. Resolve values ONLY through
  `dd_store` (the ValuCast public snapshot store) and the `/api/value-map-players`
  payload. Do NOT read `data/dd/*` or any `dd_dynasty_feed` / DD raw feed.
- **The value/scoring math** — no new valuation, no re-normalization, no
  cross-universe reconciliation. The verdict is `sum(value)` per side + the margin,
  read straight off `row.dynasty_value`. Any temptation to "convert" prospect
  values to MLB-equivalent is a STOP condition (it would fabricate the exact
  cross-scale calibration the methodology explicitly disclaims).
- **The search backend** — do not add a `/api/search` route or change
  `dd_store.filter`. Reuse `/api/value-map-players` + client-side `fold`.
- **Per-source board ranks (ToS)** — the page shows ValuCast's own value/rank/tier
  only. Do NOT render any per-source outside-board rank (`source_ranks`) or a
  consensus figure. No aggregate-consensus reference is needed on this page; do not
  add one.
- **`_graphic_footer` signature / the shared PNG helpers** — call them, don't change
  them. Do not add `/trade` to `horizon-tabs` or `site-nav` (Alex's call — flag it).

## Git workflow

- Work directly on `master` (repo convention — direct-to-main), but **do NOT push**:
  master auto-deploys valucast.app via Render. Commit locally; the reviewer gates
  the push.
- NEVER `git add -A` or `commit -am` (repo guardrail — the untracked
  `data/dd/dd_dynasty_feed.json` and pytest byproducts must not be swept in). Stage
  each in-scope file explicitly by path. **Never `git stash`.**
- Do NOT stage `data/prediction_archive/.../2026-06-15.json` (pytest byproduct) or
  the untracked `data/dd/dd_dynasty_feed.json`.
- Commit message style (short imperative subject), e.g.
  `Add free Trade Analyzer v1 (/trade): two-sided verdict from served values + share card`.

## Steps

### Step 0: Confirm the reuse surfaces are live before building

```
# The JSON player payload exists and carries id/name/value/player_type/prospect_rank:
python -c "import app; c=app.app.test_client(); import json; d=json.loads(c.get('/api/value-map-players').data); p=d['players'][0]; print(sorted(p.keys())); print(d['count'])"
# expect: keys include age,group,id,name,player_type,position,prospect_rank,value ; count ~2700
# The id->row resolver exists and spans both universes:
python -c "import app; s=app.dd_store; r=s.get_all(); print(len(r)); print(any(x.is_prospect for x in r), any(not x.is_prospect for x in r)); one=r[0]; print(s.get_by_id(one.id) is one)"
# expect: ~3700 ; True True ; True
# give/get are NOT yet in the PNG cache vocabulary (the poisoning gap):
python -c "import app; print('give' in app._PNG_CACHE_PARAMS, 'get' in app._PNG_CACHE_PARAMS)"
# expect: False False   (Step 6 fixes this)
# no /trade route yet:
python -c "import app; print([r.rule for r in app.app.url_map.iter_rules() if 'trade' in r.rule])"
# expect: []  (or only unrelated matches)
```
**Verify**: all four confirm the state above. If `/trade` already exists or
`give`/`get` are already in the cache params, someone landed here first — STOP and
reconcile.

### Step 1: The pure verdict function `_trade_verdict(give_rows, get_rows)`

Add a **pure, testable** function in app.py (near the other `_build_*`/`_dynasty_*`
helpers) that takes two lists of resolved `PublicSnapshotRow` objects and returns a
verdict dict. No I/O, no request access — so a unit test can call it with fixture
rows. It computes ONLY sums and reads existing fields:

```python
# Trade Analyzer v1 (plan 022): the verdict is sums + margin over the SAME 0-100
# dynasty values the board serves. No new math, no cross-universe reconciliation.
# The honesty guards below are the whole point: never claim precision the two
# separate 0-100 normalizations do not support.
_TRADE_NOISE_PER_PLAYER = 9.0  # a fixed tolerance (~+/-9/player). MLB rows carry no
# per-row error bar (only prospect rows have uncertainty.lower/upper), so a uniform
# heuristic band is the honest choice over a false per-row band. See plan 022 4a.
_TRADE_MAX_PER_SIDE = 6         # guard: cap each side (matches the URL param cap)

def _trade_verdict(give_rows, get_rows):
    def _val(r): return float(getattr(r, "dynasty_value", 0.0) or 0.0)
    give_total = sum(_val(r) for r in give_rows)
    get_total = sum(_val(r) for r in get_rows)
    margin = get_total - give_total                     # + = you win, - = you lose
    n = max(len(give_rows), len(get_rows), 1)
    noise = _TRADE_NOISE_PER_PLAYER * n                 # band scales with side size
    inside_noise = abs(margin) <= noise
    crosses_universes = (
        any(r.is_prospect for r in give_rows + get_rows)
        and any(not r.is_prospect for r in give_rows + get_rows)
    )
    count_mismatch = len(give_rows) != len(get_rows)
    if inside_noise:
        headline = "Inside the noise band - call it even"
    elif margin > 0:
        headline = "You come out ahead"
    else:
        headline = "You give up more than you get"
    return {
        "give_total": round(give_total, 1),
        "get_total": round(get_total, 1),
        "margin": round(margin, 1),
        "abs_margin": round(abs(margin), 1),
        "noise": round(noise, 1),
        "inside_noise": inside_noise,
        "crosses_universes": crosses_universes,
        "count_mismatch": count_mismatch,
        "headline": headline,
        "favored_side": None if inside_noise else ("get" if margin > 0 else "give"),
    }
```
Keep the constants module-level so a test can assert the band boundary. Do NOT
special-case a single-player-per-side trade differently from a multi-player one —
the band scaling handles both.

**Verify**:
- `python -c "import app; from types import SimpleNamespace as N; g=[N(dynasty_value=80,is_prospect=False)]; r=[N(dynasty_value=82,is_prospect=False)]; v=app._trade_verdict(g,r); print(v['inside_noise'], v['headline'])"` -> `True Inside the noise band - call it even` (margin 2 <= 9).
- Same with `r=[N(dynasty_value=95,...)]` (margin 15 > 9) -> `False` and a winner headline.

### Step 2: The route + context builder `_build_trade_page_context(args)`

Add `_build_trade_page_context(args)` and the `/trade` route. The route parses the
`give` / `get` query params (comma-separated ids), caps each side at
`_TRADE_MAX_PER_SIDE`, resolves each id via `dd_store.get_by_id`, drops unknown ids,
builds the per-player display rows (Step 3), computes the verdict (Step 1), and
renders `trade.html`.

```python
def _parse_trade_ids(raw):
    ids = [s for s in (raw or "").split(",") if s.strip()]
    seen, out = set(), []
    for pid in ids:
        pid = pid.strip()
        if pid and pid not in seen:      # dedupe, preserve order (URL is canonical)
            seen.add(pid); out.append(pid)
        if len(out) >= _TRADE_MAX_PER_SIDE:
            break
    return out

def _build_trade_page_context(args):
    give_ids = _parse_trade_ids(args.get("give"))
    get_ids = _parse_trade_ids(args.get("get"))
    give_rows = [row for pid in give_ids if (row := dd_store.get_by_id(pid))]
    get_rows = [row for pid in get_ids if (row := dd_store.get_by_id(pid))]
    verdict = _trade_verdict(give_rows, get_rows) if (give_rows or get_rows) else None
    return {
        "mode": "dd_dynasty",                 # so footer/context branches match the board
        "give_pieces": [_trade_piece(r) for r in give_rows],
        "get_pieces": [_trade_piece(r) for r in get_rows],
        "give_ids": give_ids, "get_ids": get_ids,
        "verdict": verdict,
        "map_data_url": "/api/value-map-players",   # the search payload the JS loads
        "as_of": dd_store.generated_at or store.as_of,
        "dd_generated_at": dd_store.generated_at,
        "dd_available": dd_store.is_available,
        "trade_page": True,
    }

@app.route("/trade")
def trade():
    return render_template("trade.html", **_build_trade_page_context(request.args))
```
Follow the `/movers` convention (a `_build_*_page_context` helper unpacked with
`**`). Resolve via `get_by_id` (NOT a board-row scan) so any player is reachable.
If `dd_store` is unavailable, the page still renders (empty state) — mirror how the
board handles `dd_available` false.

**Verify**:
- `python -c "import app; c=app.app.test_client(); print(c.get('/trade').status_code)"` -> `200` (empty state).
- The verdict render command from the Commands table -> `200` with a verdict present.

### Step 3: The per-player display row `_trade_piece(row)`

A small helper that reads existing row fields into a template-friendly dict — name,
team/pos/level, dynasty value, rank (P# for prospects), confidence word, and the
momentum label WHEN available. No computation:

```python
def _trade_piece(row):
    is_prospect = row.is_prospect
    rank_label = (f"P#{row.prospect_rank}" if is_prospect and row.prospect_rank
                  else (f"#{row.dynasty_rank}" if row.dynasty_rank else None))
    pos = "/".join(row.positions or ()) or (row.role or "")
    # confidence is coerced to {"level": "<word>"} in the served data (verified);
    # read ["level"]. Handle a bare string defensively.
    confidence = (row.confidence.get("level") if isinstance(row.confidence, dict)
                  else row.confidence if isinstance(row.confidence, str) else None)
    return {
        "id": row.id, "name": row.name, "team": row.team,
        "pos": pos, "level": row.level if is_prospect else None,
        "is_prospect": is_prospect,
        "value": round(float(row.dynasty_value or 0.0), 1),
        "rank_label": rank_label,
        "confidence": confidence,
        "momentum": _trade_momentum_label(row),   # None when not a prominent mover
    }
```
For `_trade_momentum_label`, reuse the board's load-and-key pattern
(app.py:1392-1404): load `valucast_recent_form_signal.json` ONCE (memoize on the DD
generation, mirroring `_value_map_payload`'s cache pattern — do NOT reload per
piece), build `form_by_key` from `heating_up`+`cooling_off` keyed by
`_identity_key(mlbam_id, role)`, look up `_row_identity_key(row)`, and return the
entry's **`momentum_label`** string. **Verified vocabulary: `"Heating Up"` /
`"Steady"` / `"Cooling Off"`** (display-only, tagged
`usage="recent_form_context_not_live_rank_or_value"`). Momentum is
**omit-when-absent** — only prominent movers appear in `heating_up`/`cooling_off`,
so most rows return `None`, which is correct.
- **Two-way caveat (verified):** a two-way MLB player's identity key
  (`<mlbam>_two_way`) is NOT in the recent-form map (it only holds `hitter`/
  `pitcher`), so two-way MLB players simply get no momentum chip — fine for v1.
- **Alternative signal (do NOT mix in v1):** `_value_momentum_label(row)`
  (app.py:747) derives an `"UP/DOWN/FLAT ... OVER Nd"` label from `row.value_history`
  and is available for ALL rows. It is a DIFFERENT signal (value-history slope, not
  recent on-field form). Pick ONE for the piece line — the recent-form
  `momentum_label` matches the board's chip, so prefer it. Do not render both.

**Verify**:
- `python -c "import app; s=app.dd_store; r=next(x for x in s.get_all() if x.is_prospect); p=app._trade_piece(r); print(p['rank_label'], p['is_prospect'], p['value'])"` -> a `P#...` label, `True`, a 0-100 float.
- `python -c "import app; s=app.dd_store; r=next(x for x in s.get_all() if not x.is_prospect); print(app._trade_piece(r)['rank_label'])"` -> a `#...` (not P#).

### Step 4: The three honesty features (non-negotiable) in `trade.html`

Build `templates/trade.html` extending base.html (copy the gaps/movers skeleton).
Two `.movers-grid` columns ("You give" / "You get"), each a `.buys-list.glass`
section of `.movers-row` per-player rows rendering the `_trade_piece` fields. Below
the grid, the verdict panel. The three honesty features MUST all render:

**4a — Inside-the-noise "call it even".** When `verdict.inside_noise`, the verdict
headline is `"Inside the noise band - call it even"` and it must NOT display a
winner or a false-precision margin as the headline. Show the totals and the margin
as context, but framed as within tolerance, e.g.:
> "Totals are within the value band (about +/-9 per player). That is a coin-flip on
> these numbers - call it even, not a win."

Rationale for the fixed band (state it in a code comment, per Current state): MLB
rows carry no per-row error bar; only prospect rows have `uncertainty.lower/upper`.
A uniform `_TRADE_NOISE_PER_PLAYER` heuristic is the honest choice over inventing a
per-player band the data does not uniformly support. Do NOT try to read
`uncertainty.lower/upper` for the band (it is prospect-only and would make the
threshold asymmetric and misleading across a mixed trade).

**4b — Player-count mismatch note (static).** When `verdict.count_mismatch`, render
a static consolidation note (no computation), e.g.:
> "Heads up: the sides have different player counts. Fewer, better players usually
> win dynasty trades - a pile of depth sums to a big number but you still start one
> lineup. Sums flatter the quantity side."

**4c — Cross-universe disclosure.** When `verdict.crosses_universes`, render a note
that mirrors the methodology language and LINKS to it:
> "This trade mixes prospects and big-leaguers. Their 0-100 values come from two
> separate normalizations aligned at the top - comparable in ballpark, not to the
> decimal. <a href='/methodology#dynasty-value-scale'>How the value scale works</a>."

Use the EXACT phrase "comparable in ballpark, not to the decimal" (the methodology's
own words). Do NOT invent a stronger cross-scale claim.

Also render the **free-forever framing** in the page copy (heading or fineprint):
"The Trade Analyzer is free, like every ValuCast number." And the search-add UX
(Step 5) sits above the two columns.

**Verify**:
- The three verdict command variants (equal single-player near-even; unequal
  counts; a prospect-vs-MLB pair) each render their respective note. Grep the
  rendered HTML: `python -c "import app,urllib.parse as u; s=app.dd_store; pros=next(x for x in s.get_all() if x.is_prospect); mlb=next(x for x in s.get_all() if not x.is_prospect); c=app.app.test_client(); h=c.get('/trade?'+u.urlencode({'give':pros.id,'get':mlb.id})).data.decode(); print('comparable in ballpark' in h)"` -> `True`.
- Template smoke passes.

### Step 5: The search-add UX (client-side, reusing the JSON payload)

In `trade.html`, inline a small `<script>` island (base.html has no scripts block;
pages inline in `content`). No new endpoint, no new dependency:
1. On load, `fetch(map_data_url)` (`/api/value-map-players`) once into memory.
2. Two search inputs (one per side). On input, fold the query the SAME way the
   server does — replicate `fold` in ~2 lines of JS
   (`str.normalize('NFKD').replace(/\p{Diacritic}/gu,'').toLowerCase()`) so
   "hector" matches "Héctor" — and filter the in-memory list by substring on the
   folded name. Show a small dropdown of matches (name + pos + value + P#/rank).
3. Clicking a match appends its `id` to that side's list and updates the URL
   (`history.replaceState`) to `/trade?give=...&get=...` so the state is always
   shareable, then re-requests the server render (an htmx `hx-get` on the form to
   `#trade-result`, mirroring the board's `hx-get="/rankings"` pattern, OR a full
   navigation — pick the lighter one; htmx is already loaded site-wide).
4. Cap each side at 6 in the JS too (defense-in-depth; the server also caps).
5. A remove-piece control per selected player that drops the id and re-renders.

Keep the JS small and dependency-free. The server is the source of truth for the
verdict (the JS only manages the id lists + search); a user with JS off can still
share and view a `/trade?give=...&get=...` URL because the server renders from
params.

**Verify**:
- Manual: `python -c "import app; c=app.app.test_client(); h=c.get('/trade').data.decode(); print('/api/value-map-players' in h and 'search' in h.lower())"` -> `True`.
- Load `/trade` in a browser (reviewer smoke), type an accented name, confirm the
  fold matches and a click builds the URL + renders a verdict. (If the executor
  can't run a browser, the reviewer does this smoke.)

### Step 6: (CUT-CANDIDATE) The share-card PNG + the mandatory cache-key add

**If cutting to hold M, skip this step and file it as a fast-follow.** If shipping
it, the cache-key add is mandatory.

**6a — Add `give`/`get` to the PNG cache vocabulary FIRST (the poisoning guard).**
In app.py, add the two exact param names to `_PNG_CACHE_PARAMS` (app.py:153-158):
```python
_PNG_CACHE_PARAMS = frozenset({
    "n", "limit", "pool", "position", "search", "callups",
    "mode", "source", "cats", "pcats", "rules", "split_rp", "display",
    "fit_cats", "preset", "rank_by",
    "teams", "budget", "roster", "pslots",
    "give", "get",     # plan 022: the /trade card renders from these; they MUST be
    # in the cache key or every trade collapses to one key and the first-rendered
    # card is served to everyone (cross-user poisoning). Fixed names, not prefixed.
})
```
These are exact param names (not `w_`/`pt_` open suffixes), so the plain allowlist
is the right place. The key already includes `_png_cache_generation()` (snapshot
vintage) and `request.path`, so `(generation, "/trade/share-card.png", (("get",...),("give",...)))`
is unique per ordered trade and self-invalidates on refresh. **Canonicalize the id
lists the same way in the URL and the card** (the same comma-joined ordered dedup
from `_parse_trade_ids`) so two URLs meaning the same trade share a key.

**6b — `_trade_share_card_png(give_ids, get_ids)`** following `_receipts_share_card_png`
(app.py:7206): 1080x1350 RGB, `_graphic_fill_background`, `_graphic_header(headline=..., subtitle=<editorial date>, extra_line=...)`, two panels (GIVE teal-favored / GET, or color the favored side teal and the other clay per the verdict), each listing the side's players (name - value), then the margin line and the honesty caveat line, then `_graphic_footer(right_note="valucast.app/trade")`. Resolve ids via `dd_store.get_by_id` and reuse `_trade_verdict`. **All strings ASCII** (use `" - "`, no em-dashes, no `middot`). Truncate names with `_graphic_fit_text`. The headline is the verdict headline; the caveat line is the shortest honest caveat that applies (inside-noise OR cross-universe OR count-mismatch — pick the most salient; if inside-noise, say "call it even").

**6c — The routes** (mirror app.py:7335-7349): `/trade/share-card.png` returns
`make_response(png)` + `Content-Type: image/png` + inline `Content-Disposition`; a
`/trade/share-card` HTML preview route if the other cards have one (grep — receipts
has `/receipts/share-card`). Wire the PNG as the page's `og_image` block in
`trade.html` so a shared `/trade?...` link unfurls the card (build the absolute URL
the way the other pages build their `og_image`).

**Verify**:
- `python -c "import app; print('give' in app._PNG_CACHE_PARAMS and 'get' in app._PNG_CACHE_PARAMS)"` -> `True`.
- **The poisoning guard**: two different trades produce DIFFERENT cache keys.
  `python -c "import app; app.app.config['TESTING']=False;` build two request
  contexts with different `give`/`get` and assert `_png_cache_key()` differs — OR
  add the equivalent as a unit test (Test plan). This is the load-bearing check.
- The trade PNG render command -> non-zero bytes, no exception.

### Step 7: The footer link + the "League-aware version coming" affordance

In `templates/partials/_footer_provenance.html`, in EACH of the dash-joined link
branches (the ~4 page-mode blocks around lines 22/29/36/43), add a `/trade` link and
the premium affordance, matching the existing `Send feedback` pattern:
```html
- <a href="/trade">Trade Analyzer</a>
- <a href="mailto:valucast.feedback@gmail.com?subject=League-aware%20trade%20analyzer%20interest">League-aware version coming</a>
```
The mailto is the zero-infrastructure premium affordance (no route, no form, no DB)
— it reuses the existing feedback address. Keep it consistent across all branches
(the file already duplicates these lines per mode — match that, don't refactor it).

**Verify**:
- `python -c "import app; c=app.app.test_client(); h=c.get('/').data.decode(); print('/trade' in h and 'League-aware' in h)"` -> `True`.
- `grep -n "League-aware\|/trade" templates/partials/_footer_provenance.html` -> appears in each branch.

### Step 8: Full suite + restore the byproduct

```
python -m pytest -q
git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json
git status --short
```
**Verify**: full suite green (~1829+ pass, plus your new assertions); `git status`
shows ONLY your in-scope files (`templates/trade.html`, `app.py`,
`templates/partials/_footer_provenance.html`, `static/style.css`, the test files) —
the untracked `data/dd/dd_dynasty_feed.json` is NOT staged and the archive byproduct
is restored.

## Test plan

- `tests/test_app.py`:
  1. **Verdict math + inside-noise**: call `_trade_verdict` with fixture rows
     (SimpleNamespace with `dynasty_value`/`is_prospect`). Assert: equal-ish totals
     (margin within `9*n`) -> `inside_noise True`, headline contains "call it even",
     `favored_side is None`; a clear-margin trade -> `inside_noise False`, correct
     `favored_side`, winner headline. Pin the band boundary (margin == noise is
     inside; margin == noise+0.1 is outside).
  2. **Count-mismatch flag**: 2-vs-1 rows -> `count_mismatch True`.
  3. **Cross-universe flag**: one prospect + one MLB across the two sides ->
     `crosses_universes True`; two MLB -> `False`.
  4. **Route empty state**: `GET /trade` -> 200, renders the search UI, no verdict.
  5. **Route from params**: `GET /trade?give=<real mlb id>&get=<real prospect id>`
     -> 200, HTML contains "comparable in ballpark" (cross-universe note) and the
     `/methodology#dynasty-value-scale` link.
  6. **Unknown/junk ids are dropped, not fatal**: `GET /trade?give=nonsense,<real id>`
     -> 200, only the real player resolves (no 500).
  7. **Side cap**: `give` with 8 ids resolves at most 6 pieces.
  8. **No per-source ranks leak (ToS)**: assert the rendered `/trade` HTML for a
     resolved trade does NOT contain any outside-board source key (grep for the
     board source names used elsewhere, e.g. `hkb`/`pipeline`/`fg_ord`) — the page
     shows ValuCast value/rank only.
- `tests/test_png_cache.py` (or wherever `_png_cache_key` is exercised) — **the
  poisoning guard, load-bearing**:
  1. With `give`/`get` in `_PNG_CACHE_PARAMS`, two requests to
     `/trade/share-card.png` with DIFFERENT `give`/`get` produce DIFFERENT
     `_png_cache_key()` tuples (use `app.test_request_context('/trade/share-card.png?give=a&get=b')`
     vs `...?give=c&get=d`). Assert the two keys are unequal. (Regression lock: if
     someone later removes `give`/`get` from the vocabulary, this fails.)
  2. Same trade, same key: identical `give`/`get` -> identical key.
  - Only add the PNG tests if Step 6 ships. If Step 6 is cut, still add a tiny
    guard test asserting the `/trade` route exists and renders — and note in the
    plan status that the PNG (and its cache entry) is deferred.
- Template render smoke: `jinja2 ... get_template('trade.html')` raises nothing.
- Final: `python -m pytest -q` all green, then restore the archive byproduct.

## Done criteria

- [ ] `python -m pytest -q` exits 0 (~1829+ pass); the byproduct file restored after.
- [ ] `GET /trade` returns 200 with the search UI (empty state).
- [ ] `GET /trade?give=<id>&get=<id>` renders a verdict computed from
      `dd_store.get_by_id` rows (sums + margin), NOT a board-row scan.
- [ ] The three honesty features render on the right inputs: inside-noise "call it
      even" (no false winner), count-mismatch note, and the cross-universe note that
      contains "comparable in ballpark, not to the decimal" and links
      `/methodology#dynasty-value-scale`.
- [ ] The page copy states the analyzer is free ("free, like every ValuCast number"
      or equivalent).
- [ ] Search adds players via `/api/value-map-players` + client-side fold (no new
      search endpoint); the URL updates to a shareable `/trade?give=...&get=...`.
- [ ] Footer carries a `/trade` link and the "League-aware version coming" mailto
      affordance, in the existing footer-link style, across all branches.
- [ ] `grep -n "give\|get" app.py | grep _PNG_CACHE_PARAMS` (or read app.py:153) ->
      `give`/`get` in the PNG cache vocabulary **IF** the PNG shipped; the cache-key
      poisoning test passes. **If the PNG was cut**, the status row and README say so
      explicitly and `give`/`get` are NOT added (don't add cache params for a route
      that doesn't exist).
- [ ] `git grep -n "dd_dynasty_feed\|data/dd/" templates/trade.html app.py` shows no
      NEW DD-feed read from the trade code (DD-independence preserved).
- [ ] `RECEIPTS_HOLD`, `prospects/ahead_of_consensus.py`,
      `scripts/build_ahead_of_consensus_scorecard.py` untouched
      (`git diff --stat` empty for them).
- [ ] No `/trade` tab added to `horizon-tabs`/`site-nav` (flagged for Alex, not done).
- [ ] `plans/README.md` status row updated.

## STOP conditions

- **The verdict would require any cross-universe value conversion or new
  normalization** to compare a prospect's 0-100 to an MLB player's 0-100 "fairly."
  It must not — the methodology explicitly disclaims a unit-reconciled calibration.
  The honest v1 sums the served values as-is and DISCLOSES the cross-scale caveat
  (Step 4c). If you find yourself writing a conversion factor, STOP.
- **`_PNG_CACHE_PARAMS` no longer exists or the cache key shape changed** (a refactor
  moved the PNG cache) — re-read app.py:153-198 and re-derive where `give`/`get`
  must enter. Do NOT ship a `.png` route whose params are outside the cache
  vocabulary (cross-user poisoning). If you cannot add them safely, cut the PNG.
- **`dd_store.get_by_id` no longer exists** (store refactor) — re-locate the id->row
  resolver before wiring. Do NOT fall back to a top-200 board scan (misses most
  players).
- **`/api/value-map-players` no longer returns `id`/`name`/`value`/`player_type`**
  in its items — re-check the payload shape; the search UX depends on it. If the
  payload dropped `id`, the search-add cannot capture a resolvable id — STOP and
  report (do NOT add a new search endpoint without a decision).
- **The methodology `#dynasty-value-scale` anchor or its "comparable in ballpark,
  not to the decimal" language was removed** — the cross-universe note links/quotes
  it. If it's gone, do NOT invent replacement copy; report so the source of truth is
  reconciled first.
- **Effort is clearly exceeding one day** after Steps 1-5 — invoke the cut line: cut
  the PNG (Step 6), then the momentum label (Step 3), before cutting any honesty
  feature. Report what was cut.
- **Adding `/trade` to `horizon-tabs` or `site-nav`** — that is Alex's product call
  (and would resurrect the mobile tab-overflow bug). Do NOT do it in this plan;
  flag it.

## Maintenance notes

- **v1 is deliberately stateless.** The trade lives entirely in the URL query
  params — no storage, no accounts, no league context. That is what keeps it free,
  linkable, and zero-infrastructure. The premium tier (roster import, league
  settings, contention window, "should I do this given MY roster and window") is the
  future paid layer; it is captured here only as a `mailto:` affordance. When the
  premium tier is built, it becomes a separate authenticated surface — do not
  retrofit accounts onto this free page.
- **The cross-universe honesty is the same claim the methodology makes** — the two
  0-100 scales are separate normalizations aligned at the top. The page's note and
  the methodology section are two renderings of one claim; if the methodology
  language changes, update the trade note (and vice versa). The link keeps them
  discoverable together.
- **The noise band is a heuristic, not a per-row error bar.** `_TRADE_NOISE_PER_PLAYER`
  is a fixed tolerance because MLB rows carry no uncertainty band (only prospect
  rows do). If ValuCast ever ships a uniform per-row confidence interval across both
  universes, revisit Step 4a to use the real band instead of the constant — but do
  NOT use the prospect-only `uncertainty.lower/upper` for a mixed trade (it would
  make the threshold asymmetric and dishonest).
- **The PNG cache entry is the sharp edge.** `give`/`get` MUST stay in
  `_PNG_CACHE_PARAMS` for as long as `/trade/share-card.png` exists. The poisoning
  test is the regression lock. If the card is ever retired, remove both together.
- **Nav placement is footer-only by design.** The horizon-tab bar already overflows
  on mobile; a `/trade` tab is Alex's explicit call. If he wants it promoted, that
  is a one-line macro edit in `_board_nav.html` PLUS a re-check of the 640px
  tab-wrap rule (style.css:4210-4236) — a separate, tiny follow-up.
- **The value-map payload drops age-less/value-less rows** — a few players are
  unsearchable via the autocomplete but ARE resolvable by id (the server uses
  `get_by_id`). If that gap ever matters, the fix is a dedicated slim search payload
  (all rows, id+name only), not widening the value-map payload — file it separately.
```
