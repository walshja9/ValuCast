# Card Intelligence + Liquid Glass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **In this repo the executor is Codex (CLAUDE.md division of labor): one dispatch implements all tasks, Fable reviews the complete diff, runs the suite, and gates.**

**Goal:** Enrich prospect/MLB dynasty cards and the prospects board with percentile context, consensus visualization, movers, and ETA — from v1.0 feed data only — plus a liquid-glass treatment on floating surfaces of the Broadcast Dark theme.

**Architecture:** One new pure module (`web/prospect_percentiles.py`) computes percentiles/captions/movers/identity lines from `DDFeedStore` rows at startup; `app.py` passes results as template context; templates render new elements inside the existing card sections (component contract preserved — enrich in place, no restructure). Glass is CSS-only utilities applied to existing surfaces.

**Tech Stack:** Flask + Jinja2, stdlib only (bisect), unittest. No new dependencies. No new JS beyond a 6-line `moverJump` helper.

**Spec:** `docs/superpowers/specs/2026-06-12-card-intelligence-design.md`

---

## Hard constraints (violations fail review)

1. Work ON TOP of the committed Broadcast Dark theme (style.css/base.html). Do not revert any of it. Do NOT commit — leave the tree dirty for Fable's review gate.
2. `DynastyRankingRow` is a frozen dataclass — do not add fields. The ONLY model change allowed is Task 2's `_INTERNAL_SOURCES` edit.
3. v1.0/v1.1 schema gating semantics untouched (`v11` flags, dormant confidence/range/fit columns). No feed-version badge on any public toolbar.
4. Feed JSON, deploy tooling, league_settings/HX-Replace-Url plumbing: out of scope, do not touch.
5. No `!important`. No backdrop-filter on per-tile elements (only the six floating surfaces + sticky thead). Keep `tabular-nums`.
6. Match template idioms: `is not none` guards, existing chip/section classes, `{% if %}` omission over empty markup.
7. Honesty: percentile pool labeled "vs ValuCast prospect pool"; captions only from the fixed bank; no invented composites or grades.

---

### Task 1: `web/prospect_percentiles.py` (new)

**Files:** Create `web/prospect_percentiles.py`. Test: `tests/test_card_intelligence.py` (Task 6 holds the test code).

```python
"""Percentile context, captions, movers, and identity lines for prospect cards.

Pool = feed prospects with a stat_line and pa >= MIN_PA ("ValuCast prospect pool").
Pure functions over DynastyRankingRow; no I/O. Built once at app startup.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right

METRICS = ("avg", "obp", "slg", "ops", "iso", "k_pct", "bb_pct")
LOWER_IS_BETTER = frozenset({"k_pct"})
MIN_PA = 100
CAPTION_METRICS = ("ops", "k_pct", "iso")

# Percentile here is ALWAYS quality-direction: high percentile = good,
# so k_pct values are inverted before banding.
_CAPTIONS = {
    "ops": ((90, "Elite all-around production"), (75, "Strong production for the level"),
            (10, "Bat has been overmatched"), (25, "Production lags the level")),
    "k_pct": ((90, "Elite bat-to-ball — rarely strikes out"), (75, "Advanced contact skills"),
              (10, "Serious swing-and-miss risk"), (25, "Swing-and-miss concerns")),
    "iso": ((90, "Elite raw power output"), (75, "Real power in the profile"),
            (10, "Minimal power impact"), (25, "Light power so far")),
}

_STANDOUT_NOUN = {
    "ops": "production", "iso": "power", "slg": "power",
    "k_pct": "bat-to-ball skills", "bb_pct": "plate discipline",
    "avg": "hit ability", "obp": "on-base skills",
}


def _eligible(row) -> bool:
    line = row.stat_line or {}
    pa = line.get("pa")
    return bool(row.is_prospect and line and isinstance(pa, (int, float)) and pa >= MIN_PA)


def build_pool(rows) -> dict[str, list[float]]:
    """Sorted per-metric value arrays over eligible prospects."""
    pool: dict[str, list[float]] = {m: [] for m in METRICS}
    for row in rows:
        if not _eligible(row):
            continue
        for m in METRICS:
            v = (row.stat_line or {}).get(m)
            if isinstance(v, (int, float)):
                pool[m].append(float(v))
    return {m: sorted(vs) for m, vs in pool.items() if vs}


def percentile_for(pool: dict, metric: str, value) -> int | None:
    """Midrank percentile of value within the pool, quality-direction, clamped 1..99."""
    values = pool.get(metric)
    if not values or not isinstance(value, (int, float)):
        return None
    v = float(value)
    below = bisect_left(values, v)
    ties = bisect_right(values, v) - below
    pct = 100.0 * (below + 0.5 * ties) / len(values)
    if metric in LOWER_IS_BETTER:
        pct = 100.0 - pct
    return max(1, min(99, round(pct)))


def card_percentiles(pool: dict, row) -> dict[str, int]:
    """{metric: percentile} for an eligible prospect; {} otherwise."""
    if not _eligible(row):
        return {}
    out = {}
    for m in METRICS:
        pct = percentile_for(pool, m, (row.stat_line or {}).get(m))
        if pct is not None:
            out[m] = pct
    return out


def caption_for(metric: str, pct: int | None) -> str | None:
    """Threshold-banded caption; None in the neutral band or for non-headline metrics."""
    if pct is None or metric not in _CAPTIONS:
        return None
    bands = _CAPTIONS[metric]
    if pct >= bands[0][0]:
        return bands[0][1]
    if pct >= bands[1][0]:
        return bands[1][1]
    if pct <= bands[2][0]:
        return bands[2][1]
    if pct <= bands[3][0]:
        return bands[3][1]
    return None


def top_movers(rows, limit: int = 5, min_change: int = 5, max_rank: int = 200) -> list[dict]:
    """Largest |breakout_rank_change| among visible-board prospects. [] when quiet."""
    candidates = [
        r for r in rows
        if r.is_prospect
        and isinstance(r.breakout_rank_change, int)
        and abs(r.breakout_rank_change) >= min_change
        and r.prospect_rank is not None
        and r.prospect_rank <= max_rank
    ]
    candidates.sort(key=lambda r: (-abs(r.breakout_rank_change), r.prospect_rank))
    return [
        {"id": r.id, "name": r.name, "prospect_rank": r.prospect_rank,
         "change": r.breakout_rank_change}
        for r in candidates[:limit]
    ]


def identity_line(row, percentiles: dict) -> str | None:
    """One deterministic sentence from feed fields. None for non-prospects."""
    if not row.is_prospect:
        return None
    pos = row.positions[0] if row.positions else None
    if not pos:
        return None
    base = f"{row.age}-year-old {pos}" if row.age is not None else pos
    head = f"{base} at P#{row.prospect_rank}" if row.prospect_rank is not None else base

    bits = []
    consensus = row.public_source_consensus
    if consensus is not None and row.prospect_rank is not None:
        diff = consensus - row.prospect_rank
        if abs(diff) <= 10:
            bits.append("the public boards see it the same way")
        elif diff > 10:
            bits.append(f"we're higher than the boards (P#{row.prospect_rank} vs ~P#{consensus})")
        else:
            bits.append(f"we're lower than the boards (P#{row.prospect_rank} vs ~P#{consensus})")

    if percentiles:
        metric, pct = max(percentiles.items(), key=lambda kv: kv[1])
        if pct >= 90:
            bits.append(f"carried by elite {_STANDOUT_NOUN[metric]}")
        elif pct >= 75:
            bits.append(f"standout {_STANDOUT_NOUN[metric]}")

    return head + (" — " + "; ".join(bits) if bits else "")
```

- [ ] Create the module exactly as above.

### Task 2: Exclude `cfr_raw` from public boards

**Files:** Modify `web/dynasty_models.py:9`.

`cfr_raw` is the unrounded duplicate of `cfr`, not an independent board; today it leaks into `public_source_ranks` (board count, consensus median, board list, spread all skewed).

```python
_INTERNAL_SOURCES = frozenset({"milb_perf", "milb_breakout", "cfr_raw"})
```

- [ ] Apply the one-line change. If any existing test pinned a 4-board count or cfr_raw-inclusive consensus, fix the pin (verify the test meant "public boards" before changing it).

### Task 3: App wiring

**Files:** Modify `app.py` (dd_store init site; `/player/<player_id>` prospect branch; the dd-modes context builder used by both `/` and `/rankings`).

- [ ] After `dd_store` construction (module level):

```python
from web import prospect_percentiles

prospect_pool = prospect_percentiles.build_pool(dd_store.get_all()) if dd_store.is_available else {}
```

- [ ] In the `/player/<player_id>` prospect-mode branch (the `render_template("partials/player_detail_dynasty.html", ...)` call): build and pass

```python
stat_percentiles = prospect_percentiles.card_percentiles(prospect_pool, dd_row)
stat_captions = {
    m: c for m in prospect_percentiles.CAPTION_METRICS
    if (c := prospect_percentiles.caption_for(m, stat_percentiles.get(m))) is not None
}
identity = prospect_percentiles.identity_line(dd_row, stat_percentiles)
```

as `stat_percentiles=stat_percentiles, stat_captions=stat_captions, identity=identity` (MLB branch unaffected — template guards handle absence).

- [ ] Wherever the dd-board context is assembled for BOTH the full page and the HTMX `/rankings` partial (so swaps keep the strip): when `mode == 'prospects'` AND no search AND no position filter AND default pool, set

```python
prospect_movers = prospect_percentiles.top_movers(dd_store.filter(player_type="prospect"))
```

else `prospect_movers = []`. Pass into the rankings partial context. Movers always derive from the FULL prospect pool, never the filtered rows.

### Task 4: Templates

**Files:** Modify `templates/partials/player_detail_dynasty.html`, `templates/partials/rankings_table_dynasty.html`, `templates/partials/_statcast_bars.html`, `templates/index.html`, `templates/partials/_welcome_strip.html`, `templates/partials/compare_modal.html`, `templates/partials/setup_dynasty.html` (+ the redraft setup panel / toolbar / compare bar wherever `rank-toolbar`, `setup-panel`, `compare-bar` live — also check `rankings_response.html`).

- [ ] **Identity line** (`player_detail_dynasty.html`, inside `.detail-identity`, after the `detail-meta` span, before the `dna` paragraph):

```html
{% if identity %}<p class="identity-line">{{ identity }}</p>{% endif %}
```

- [ ] **Ordinal macro + percentile rails on stat tiles** (same file). Add macro next to `stat_value`:

```html
{% macro ordinal(n) -%}
{{ n }}{% if 10 <= n % 100 <= 13 %}th{% elif n % 10 == 1 %}st{% elif n % 10 == 2 %}nd{% elif n % 10 == 3 %}rd{% else %}th{% endif %}
{%- endmacro %}
```

In the Rate Stats and Plate Discipline `{% for key in ... %}` tile loops, extend each `stat-item` (keep existing label/value spans; `stat_percentiles`/`stat_captions` may be undefined for in-board MLB renders — guard with `stat_percentiles is defined and stat_percentiles`):

```html
{% set pct = stat_percentiles.get(key) if stat_percentiles is defined and stat_percentiles else none %}
{% if pct is not none %}
<div class="pct-rail" role="img" aria-label="{{ ordinal(pct) }} percentile vs ValuCast prospect pool">
    <span class="pct-rail-fill {{ 'good' if pct >= 75 else ('bad' if pct <= 25 else '') }}" style="width: {{ pct }}%"></span>
</div>
<span class="pct-ord">{{ ordinal(pct) }}</span>
{% endif %}
{% set cap = stat_captions.get(key) if stat_captions is defined and stat_captions else none %}
{% if cap %}<span class="stat-caption">{{ cap }}</span>{% endif %}
```

- [ ] **Pool label + small-sample tag** (same file, MiLB Stats `h4`):

```html
<h4>MiLB Stats
    {% if stat_percentiles is defined and stat_percentiles %}<span class="profile-note">vs ValuCast prospect pool</span>
    {% elif row.stat_line and row.stat_line.get('pa') is not none and row.stat_line.get('pa') < 100 %}<span class="small-sample">small sample · {{ row.stat_line.get('pa') | int }} PA</span>{% endif %}
</h4>
```

- [ ] **Trend chip color** (same file, Prospect Profile trend tile) — replace the plain `stat-value` span:

```html
{% set tdir = 'up' if (row.breakout_label == 'rising' or (row.breakout_rank_change or 0) > 0) else ('down' if (row.breakout_label == 'falling' or (row.breakout_rank_change or 0) < 0) else none) %}
<span class="trend-chip {% if tdir %}trend-{{ tdir }}{% endif %}">{{ row.breakout_label | replace('_', ' ') | title }}{% if row.breakout_rank_change %} ({{ '+' if row.breakout_rank_change > 0 else '' }}{{ row.breakout_rank_change }}){% endif %}</span>
```

- [ ] **Consensus spread strip** (same file, inside `.source-evidence`, after `.source-summary`, before the boards `details`):

```html
{% set public = row.public_source_ranks %}
{% if public | length >= 2 %}
{% set ranks = public.values() | list %}
{% set lo = ranks | min %}
{% set hi = ranks | max %}
{% set span = (hi - lo) if hi > lo else 1 %}
<div class="spread-strip">
    <div class="spread-rail">
        {% for source, rank in public.items() %}
        <span class="spread-dot" style="left: {{ ((rank - lo) / span * 100) | round(1) }}%" title="{{ source | upper }} #{{ rank | int }}"></span>
        {% endfor %}
        {% if row.milb_performance_rank is not none and row.milb_performance_rank >= lo and row.milb_performance_rank <= hi %}
        <span class="spread-dot ours" style="left: {{ ((row.milb_performance_rank - lo) / span * 100) | round(1) }}%" title="MiLB performance #{{ row.milb_performance_rank | int }}"></span>
        {% endif %}
    </div>
    <span class="spread-bounds">P#{{ lo | int }}–P#{{ hi | int }}</span>
    {% if hi - lo <= 15 %}<span class="spread-chip tight">Tight consensus</span>
    {% elif hi - lo >= 40 %}<span class="spread-chip split">Sources split</span>{% endif %}
</div>
{% endif %}
```

- [ ] **Board: ETA column + movers strip** (`rankings_table_dynasty.html`):
  - Line 9 ncols: `{% set ncols = (10 if v11 else 7) if mode == 'dd_dynasty' else (9 if v11 else 7) %}`
  - After the Dynasty Value `th`: `{% if mode == 'prospects' %}<th class="col-eta sortable" aria-sort="none"><button type="button" class="sort-btn" onclick="sortTable(6)">ETA</button></th>{% endif %}`
  - After the `col-value` td: `{% if mode == 'prospects' %}<td class="col-eta">{{ row.eta or '—' }}</td>{% endif %}`
  - Above `.results-meta`:

```html
{% if mode == 'prospects' and prospect_movers %}
<div class="movers-strip" aria-label="Biggest prospect rank movers">
    <span class="movers-label">Movers</span>
    {% for m in prospect_movers %}
    <button type="button" class="mover-chip {{ 'up' if m.change > 0 else 'down' }}" onclick="moverJump('{{ m.id }}')">
        {{ '▲' if m.change > 0 else '▼' }} {{ m.name }} <span class="mover-delta">{{ '%+d' | format(m.change) }}</span>
    </button>
    {% endfor %}
</div>
{% endif %}
```

- [ ] **`moverJump` helper** (`index.html`, next to `toggleDetail`):

```javascript
function moverJump(id) {
    const row = document.querySelector(`tr.player-row[data-player-id="${id}"]`);
    if (!row) return;
    row.scrollIntoView({ behavior: 'smooth', block: 'center' });
    const detail = document.getElementById(`detail-${id}`);
    if (detail && detail.style.display === 'none') toggleDetail(id, row);
}
```

- [ ] **Statcast ordinal chips** (`_statcast_bars.html`, after the `pct-track` div inside `.pct-row`):

```html
{% if m.pct >= 75 %}<span class="pct-chip">top {{ 100 - m.pct }}%</span>
{% elif m.pct <= 25 %}<span class="pct-chip low">bottom {{ m.pct }}%</span>{% endif %}
```

- [ ] **Glass classes:** add `glass` to the root elements of: rank-toolbar (every occurrence — check `index.html` AND `rankings_response.html`), `_welcome_strip.html` root, compare bar, `.compare-modal` (`compare_modal.html`), Customize/setup panels (`setup_dynasty.html` + the redraft setup panel). Sticky `thead` is styled in CSS (Task 5), not classed.

### Task 5: style.css additions (append to the themed file)

- [ ] Glass utilities + surface styles:

```css
/* Liquid glass — floating surfaces only (perf: never on per-tile elements) */
.glass {
    background: rgba(26, 27, 46, .72);
    -webkit-backdrop-filter: blur(14px) saturate(140%);
    backdrop-filter: blur(14px) saturate(140%);
    border: 1px solid rgba(255, 255, 255, .06);
}
@supports not (backdrop-filter: blur(1px)) {
    .glass { background: var(--surface); }
}
.rankings-table > thead { background: rgba(35, 36, 64, .7); }
.rankings-table > thead th {
    background: rgba(35, 36, 64, .7);
    -webkit-backdrop-filter: blur(10px);
    backdrop-filter: blur(10px);
}
@supports not (backdrop-filter: blur(1px)) {
    .rankings-table > thead, .rankings-table > thead th { background: var(--surface-2); }
}
/* Glass-lite: specular hint without blur cost */
.stat-item, .source-summary-item {
    background: linear-gradient(180deg, rgba(255, 255, 255, .045), rgba(255, 255, 255, 0) 42%), var(--surface-2);
    border-top: 1px solid rgba(255, 255, 255, .07);
}

/* Percentile rails on stat tiles */
.pct-rail { position: relative; height: 4px; margin-top: .3rem; background: #2a2c45; border-radius: 2px; overflow: hidden; }
.pct-rail-fill { position: absolute; inset: 0 auto 0 0; background: var(--c-blue); border-radius: 2px; }
.pct-rail-fill.good { background: var(--c-pos); }
.pct-rail-fill.bad { background: var(--c-neg); }
.pct-ord { margin-top: .15rem; font-size: .68rem; color: var(--c-muted); font-variant-numeric: tabular-nums; }
.stat-caption { margin-top: .2rem; font-size: .7rem; line-height: 1.25; color: var(--c-muted); font-style: italic; }
.small-sample { text-transform: none; letter-spacing: 0; font-weight: 600; font-size: .7rem; color: var(--c-amber); background: rgba(251, 191, 36, .14); border-radius: 999px; padding: .12rem .45rem; }
.identity-line { margin-top: .25rem; max-width: 720px; color: var(--c-muted); font-size: .85rem; }

/* Movers strip */
.movers-strip { display: flex; align-items: center; gap: .4rem; overflow-x: auto; padding: .15rem 0; margin-bottom: var(--space-2); }
.movers-label { font-size: .72rem; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; color: var(--c-muted); white-space: nowrap; }
.mover-chip { display: inline-flex; align-items: center; gap: .3rem; border: 1px solid var(--c-border-strong); border-radius: 999px; background: var(--surface-2); color: var(--c-text); font-size: .76rem; font-weight: 600; padding: .25rem .6rem; cursor: pointer; white-space: nowrap; }
.mover-chip:hover { background: #2a2c4a; border-color: var(--c-blue); }
.mover-chip.up { color: var(--c-pos); }
.mover-chip.down { color: var(--c-neg); }
.mover-delta { font-variant-numeric: tabular-nums; }

/* Consensus spread strip */
.spread-strip { display: flex; align-items: center; gap: .55rem; margin-top: .55rem; }
.spread-rail { position: relative; flex: 1; max-width: 340px; height: 6px; background: #2a2c45; border-radius: 3px; }
.spread-dot { position: absolute; top: 50%; width: 10px; height: 10px; border-radius: 50%; transform: translate(-50%, -50%); background: var(--c-blue); border: 2px solid var(--surface); }
.spread-dot.ours { background: var(--c-prospect); border-radius: 2px; transform: translate(-50%, -50%) rotate(45deg); }
.spread-bounds { font-size: .72rem; color: var(--c-muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
.spread-chip { font-size: .72rem; font-weight: 700; border-radius: 999px; padding: .15rem .5rem; white-space: nowrap; }
.spread-chip.tight { background: rgba(52, 211, 153, .14); color: var(--c-prospect); }
.spread-chip.split { background: rgba(251, 191, 36, .14); color: var(--c-amber); }

/* Statcast ordinal chips + ETA column */
.pct-chip { font-size: .68rem; font-weight: 700; color: var(--c-muted); background: var(--surface-2); border-radius: 999px; padding: .1rem .4rem; white-space: nowrap; }
.pct-chip.low { color: var(--c-amber); background: rgba(251, 191, 36, .14); }
.col-eta { color: var(--c-muted); font-variant-numeric: tabular-nums; }
```

(Adjust `.stat-item`/`.source-summary-item`: the gradient REPLACES their existing `background: var(--surface-2)` declarations — edit those rules in place rather than appending duplicates.)

### Task 6: Tests — `tests/test_card_intelligence.py` (new)

Follow the fixture pattern of `tests/test_dynasty_v11.py` (temp feed JSON + app test client). Cover, with real assertions:

```python
# Pure module
- percentile midrank: pool [10 values 1..10], value 5 -> 45th; ties counted at midrank
- k_pct inversion: LOW k_pct yields HIGH percentile; caption_for('k_pct', 92) == "Elite bat-to-ball — rarely strikes out"
- clamp: best value in pool -> 99 not 100; worst -> 1 not 0
- empty pool / None value / missing metric -> percentile_for returns None
- card_percentiles: prospect with pa=80 -> {}; non-prospect -> {}
- caption_for neutral band (pct 50) -> None; non-headline metric ('avg', 95) -> None
- top_movers: |change| < 5 filtered; prospect_rank > 200 filtered; sorted by |change| desc; capped at 5; [] when none
- identity_line: agree case (diff <= 10) mentions "see it the same way"; higher case says "we're higher"; standout >= 90 says "carried by elite"; non-prospect -> None
# Model
- public_source_ranks drops cfr_raw (feed record with pipeline/cfr/cfr_raw/hkb/milb_perf -> 3 boards; consensus = median of pipeline/cfr/hkb)
# Flask client (prospects mode, v1.0 fixture)
- board response contains 'col-eta' header and the fixture eta year
- cutoff row (when teams/pslots produce one) has colspan="7"
- movers strip present on unfiltered board when fixture has |change| >= 5; absent with ?search=
- prospect card response contains 'identity-line', 'pct-rail', 'vs ValuCast prospect pool'
- small-sample fixture (pa < 100) card contains 'small sample' and no 'pct-rail'
- '/' response contains 'glass' on the toolbar and welcome strip
```

- [ ] Write all tests; run the new file, then the FULL suite:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests
```

Expected: 756 existing + new tests, 0 failures. Fix regressions you caused; report any pre-existing failure untouched.

---

## Verification (Fable runs at the gate)

1. Review complete diff vs the committed dark theme.
2. Full suite green.
3. `python _shots.py glass "/" "/?mode=dd_dynasty" "/?mode=prospects" "/methodology" "/nonexistent"` and `python _shots_detail.py glasscard "/?mode=prospects|Bolte" "/?mode=prospects|Made" "/?mode=dd_dynasty|Muncy"` (PowerShell, never Git Bash).
4. Screenshots → Alex sign-off → commit stack → push → deploy.ps1 → live spot-check.
