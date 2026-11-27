# Card Intelligence + Liquid Glass — Design

**Date:** 2026-06-12 · **Approach:** A (in-place enrichment) — approved by Alex.
**Context:** Rides on the uncommitted Broadcast Dark re-skin (style.css + base.html).
Ships as one gate: dark theme → glass tweaks → card additions → screenshots → sign-off →
deploy → X launch post. Reference inspiration: PROSPX/PitchIQ-style cards (no copying;
our own visual language; only honest, feed-available data).

## Scope boundary

**In (v1.0 feed + existing stores only, app-side):** prospect percentile rails + captions,
ETA chip + board column, trend chip color-coding, consensus spread strip, identity line,
Top Movers rail, MLB Statcast chips/captions + season stat strip, liquid glass.

**Out (deferred to the DD v1.1 producer pass):** value-history sparklines, MLB
confidence/range/trend (app gating already built + tested, stays dormant), 20-80 tool
grades (no honest source — never fabricate), org/system pages, headshots.

## Data contract (verified against data/dd/dd_dynasty_feed.json, schema 1.0)

- All records: id, player_type, name, mlbam_id (null today), positions, mlb_team, age,
  dynasty_rank, dynasty_value, status, last_updated.
- Prospects add: level (often null), eta, prospect_rank, source_ranks
  {pipeline, cfr, cfr_raw, hkb, milb_perf}, breakout_label, breakout_rank_change,
  stat_line {avg, obp, slg, ops, iso, k_pct, bb_pct, pa}.
- MLB records are thin in v1.0; card richness comes from the app's own projections +
  statcast stores via the existing safe name-match (unchanged).

## Components

### 1. Prospect percentile layer (new pure module + dd_store precompute)
- At dd_store load, build per-metric sorted arrays over prospects with stat_line and
  pa >= 100 (the "ValuCast prospect pool"). 493 × 8 floats — startup cost negligible
  (Render 30s ceiling unaffected).
- `percentile(metric, value) -> 0..100`, direction-aware: k_pct lower-is-better; all
  others higher-is-better. None-safe: missing metric/empty pool → no rail rendered.
- Card stat tiles (AVG/OBP/SLG/OPS, K%/BB%/ISO) gain a thin percentile rail + ordinal
  annotation ("82nd"). Tiles for pa < 100 prospects render values with a single
  "small sample" tag and no rails/captions.
- Caption phrase bank: deterministic, threshold-banded (>=90 elite, >=75 strong,
  25–75 neutral/no caption, <=25 concern), per-metric phrasing (k_pct inverted →
  "elite bat-to-ball" when its *percentile* is high under inversion). Captions only on
  headline metrics (OPS, K%, ISO). Pool label rendered once: "vs ValuCast prospect pool".

### 2. Prospect profile + consensus
- Profile row adds ETA chip ("ETA 2026"; omit when null) and level chip when present.
- Trend chip color-codes breakout_label: rising → prospect green, falling → neg red,
  steady → muted; keeps the existing (+N) rank-change text.
- Consensus spread strip under the Market Context tiles: one horizontal rail plotting
  the existing public-board ranks (reuse the card's current source grouping — do NOT
  re-derive source semantics) plus milb_perf as a visually distinct dot. Chip computed
  over the public-board ranks only (milb_perf excluded — it is our signal, not consensus):
  spread (max−min) <= 15 → "tight consensus"; >= 40 → "sources split"; else no chip.
- Identity line under the name: template-assembled from feed fields only —
  "{age}-year-old {pos} at P#{rank}" + one consensus clause (agree / we're higher /
  we're lower vs public consensus) + one standout clause (best percentile >= 75 →
  power/contact/discipline/production mapping). Max two clauses. No generated text.

### 3. Prospects board
- ETA column (header "ETA", em-dash when null). Prospects-mode ncols 8 → 9; cutoff
  divider + detail-row colspans follow ncols (known landmine — update the shared
  expression, not call sites; tests pin both modes).
- Top Movers rail: server-rendered strip under the toolbar — top 5 by |breakout_rank_change|,
  risers ▲ green / fallers ▼ red, each linking to its row anchor. Hidden entirely when
  max |change| < 5. Mobile: horizontal scroll. No new JS dependencies.

### 4. MLB dynasty cards
- Existing Statcast sliders gain ordinal chips ("top 10%" at >=75th percentile;
  "bottom X%" at <=25th); keep existing slider colors/markup. Captions stay a
  prospect-tile feature (statcast metric families are too varied for an honest
  fixed phrase bank). Season outlook grids stay as-is — restyling them to a strip
  was trimmed as restructure-risk for no information gain.

### 5. Liquid glass (style.css; rides the Broadcast Dark palette)
- `.glass`: translucent surface rgba(26,27,46,.72) + backdrop-filter blur(14px)
  saturate(140%) (+ -webkit-), hairline border rgba(255,255,255,.06).
  `@supports not (backdrop-filter: blur(1px))` → solid var(--surface) fallback.
- Applied to floating surfaces only: sticky rank-toolbar, sticky table header (styled
  directly on thead th), welcome strip, compare bar, compare modal, Customize panel.
- `.glass-lite` for card tiles (stat-item, source-summary-item): translucent gradient +
  specular top hairline, NO backdrop-filter (hundreds of tiles → mobile paint cost).
- Mobile keeps blur only on the toolbar + thead.

## Guardrails

- Honesty: percentiles labeled vs our pool; no invented composites; no fabricated
  grades; no "beats Steamer / most accurate" language anywhere.
- v1.0/v1.1 schema gating untouched. Public toolbar carries no feed-version badge.
- HX-Replace-Url continues to carry every league_settings._BOUNDS param.
- No `!important`; tabular-nums preserved; component contract (consolidated card
  sections) preserved — enrich in place, no restructure.

## Testing

Unit: percentile math (direction, PA gate, None/empty safety), phrase-bank thresholds,
identity-line composition, spread-chip thresholds. Template: ETA chip presence/absence,
movers rail presence/absence + threshold, board colspans in both modes, small-sample
tag, glass classes present on the six surfaces. Full suite (756 + new) green before the
screenshot gate. Verification: _shots.py + _shots_detail.py reruns, desktop + mobile.

## Ship plan

Commit stack on master (explicit paths, never -A): (1) dark re-skin (style.css,
base.html); (2) card intelligence (templates, web/src module, style.css, tests, this
spec + plan). Push → deploy.ps1 → live spot-checks (Bolte card: #69, ValuCast labels,
dark + rails; movers rail; glass toolbar) → Alex posts launch.
