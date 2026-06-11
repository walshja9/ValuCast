# Dynasty League Customization — Design

**Date:** 2026-06-10
**Status:** Approved by Alex (scope, approach, and design sections)

## Problem

The Dynasty toolbar promises "League customization is coming." Dynasty dollars are
hardcoded at 12 teams / $200, tiers are computed over a fixed top slice, and there is
no way to tune the board to a user's league. ValuCast's positioning is
"tuned-to-your-league" — the dynasty board should honor that.

## Scope (agreed)

- **In:** league size, auction budget, roster slots, prospect slots; league-URL
  settings import for **Fantrax + ESPN public leagues**; URL-param + localStorage
  persistence.
- **Out:** rank-order changes (feed is a single composite 0–150 value — league
  settings change what players are *worth*, not who's better), roster/ownership
  import, Yahoo (OAuth wall), server-side league profiles, payments. The import
  endpoint must stay a clean seam so it can be gated as a paid feature later
  without rework.

## Approach

Mirror the redraft `Customize` panel pattern on the dynasty toolbar. Manual knobs
are the primary interface; URL import is a pre-filler that populates the same
knobs. Everything flows through the existing form → GET params → htmx pipeline.
No new architecture, fully stateless server.

## Design

### 1. Knobs and effects

| Param | Range | Default |
|---|---|---|
| `teams` | 4–20 | 12 |
| `budget` | $100–$1000 | $200 |
| `roster` | 10–50 | 26 |
| `pslots` | 0–20 | 5 |

All params clamped server-side; invalid values fall back to defaults.

- **Dollars:** `_compute_dynasty_dollars` becomes replacement-adjusted auction
  math. Rostered pool = `teams × roster` (MLB + prospects combined, by dynasty
  value). Replacement value = the dynasty value at the cutoff rank. Each rostered
  player's dollars = `(value − replacement) / Σ(value − replacement) × (teams ×
  budget)`, min $1 for rostered players; below cutoff = $0. League size now
  genuinely moves dollars.
- **Cutoff line:** a visual divider row in the dynasty table at rank
  `teams × roster` ("≈ replacement level in your league"). On the prospects board,
  the divider sits at `teams × pslots`. `pslots` affects ONLY the prospects-board
  divider — it does not enter the dollar pool (`teams × roster` is the whole
  rostered pool for dollar math; treat `roster` as total slots).
- **Tiers:** same gap-based algorithm, computed over the rostered pool instead of
  the fixed top slice, so tier boundaries respond to league depth.
- **Toolbar:** `config_summary` replaces the "coming" line with the live setup,
  e.g. `12 teams · $200 · 26 roster · 5 prospect slots`.

### 2. Setup panel (UI)

- Dynasty toolbar gains the same `Customize` button as redraft; it toggles a
  `setup-panel` section (collapsed by default) — new partial
  `templates/partials/setup_dynasty.html`.
- Panel contents: the four numeric knobs + a "paste your league URL" text input
  with an Import button.
- Follows the existing setup-panel CSS/markup contract; mobile layout verified
  (mobile is the #1 recurring pain point).
- The hidden `mode` input on non-redraft horizons MUST remain (the 6/10 P0
  regression: dropping `mode` from form requests 404s detail clicks and swaps in
  the redraft board).

### 3. Import endpoint

- `GET /league-import?url=...` → returns an htmx fragment that swaps the setup
  panel back in with knobs filled from the league's real settings.
- **Platform detection** from the URL: Fantrax (league ID in path or query) and
  ESPN fantasy baseball league URLs (`leagueId` param). Anything else → inline
  "unsupported platform" notice.
- **Fetchers** (new module `web/league_import.py`):
  - Fantrax: open `fxea` API (`getLeagueInfo`) — teams, roster slots, budget,
    minor-league slots where exposed.
  - ESPN: `lm-api-reads.fantasy.espn.com` public-league `mSettings` view — works
    only for public leagues; private leagues return an auth error → inline notice
    "this ESPN league is private — enter settings manually."
- **Error handling:** bad URL, private league, network timeout, or unparseable
  response all return the panel unchanged plus an inline notice. Hard timeout
  ~5s per request (Render 30s ceiling must never be near). Nothing fetched is
  stored server-side.
- Endpoint is self-contained: a future paid gate wraps this one route.

### 4. Persistence

- Settings are plain form params — shareable URLs keep working with zero effort.
- Small JS addition: on dynasty form change, save `{teams, budget, roster,
  pslots}` to localStorage; when a user lands on `/?mode=dd_dynasty` with none of
  those params present, reapply the saved values (redirect-free: set the form
  inputs and let the normal htmx flow run). Bare landings with no saved settings
  behave exactly as today.

### 5. Testing

- **Dollar math:** hand-computed cases at 8/12/16 teams; replacement cutoff
  correctness; min-$1 floor; $0 below cutoff; param clamping.
- **Tiers/cutoff:** divider placement; tier computation over variable pool sizes.
- **Import:** URL-detection table (Fantrax, ESPN, garbage); parser tests against
  committed fixture JSON for both platforms (no live network in CI); error paths
  (private ESPN, timeout, malformed response).
- **Templates:** panel renders on dynasty, config summary reflects params, hidden
  `mode` input present in all dynasty form requests, CSV export carries params.
- Existing 675 tests stay green; `scripts/smoke_check.py` untouched.

## Non-goals / future

- Rank-order personalization (needs a component breakdown in the DD feed —
  cross-repo effort).
- Roster/ownership import ("available players only") — separate spec; name-
  matching is the hard part.
- Paid gating of import — later; the endpoint seam is the only prep done now.
- localStorage persistence for redraft — free to add later, out of scope here.
