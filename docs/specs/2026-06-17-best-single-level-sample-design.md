# Best Single-Level Sample — design

Date: 2026-06-17
Status: spec (producer side → Codex / DD producer; consumer side → ValuCast app, this repo)

## Problem

When a prospect's current-level sample is too thin to clear the percentile threshold
(hitters < 100 PA, pitchers < 20 IP), the card's skill-shape read degrades to
"The sample is too small to read the skill shape yet." That is honest but unhelpful for
**recently-promoted** players who have a real, large sample one level down (e.g. 250 PA at
AA, then an 83 PA cup of coffee at AAA).

## Decision (do NOT do these)

- **No raw all-level blend.** Summing AA + AAA raw rates pretends competition quality is
  constant and ranks a confounded line against a pool that is "all levels, NOT level-adjusted"
  (each player sits at their own single level). Blending within a player breaks that coherence.
- **No translated-vs-raw-pool ranking.** `stat_line_translated` (MLB-equivalent peripherals)
  must not be ranked against the raw percentile pool unless we build a separate translated pool.

The model distinction stays:
- `stat_line` — current clean single-level sample → current skill percentiles.
- `stat_line_translated` — MLB-equivalent / sticky peripheral context, shown separately.
- (new) `best_single_level_stat_line` — the largest *single-level* 2026 sample that clears the
  threshold, when the current level is thin. Competition-clean, level-labeled. Never blended.

## Producer side (DD producer — `generate_valucast_feed`, separate repo)

Add an OPTIONAL feed field `best_single_level_stat_line` to each prospect row. Emit it ONLY
when BOTH hold:
1. the current-level `stat_line` is **below** threshold (hitters < 100 PA, pitchers < 20 IP), and
2. some **other** single 2026 level has a sample that **clears** threshold.

Selection: among the player's 2026 single-level samples that clear threshold, pick the **largest**
(most PA for hitters, most IP for pitchers). Single level only — never a combine.

Shape (mirrors `stat_line` rate keys + adds provenance):

```json
"best_single_level_stat_line": {
  "level": "AA",
  "sample": 250,
  "sample_unit": "PA",
  "reason": "current_level_too_thin_best_prior_level",
  "avg": 0.290, "obp": 0.360, "slg": 0.480, "ops": 0.840,
  "iso": 0.190, "k_pct": 0.20, "bb_pct": 0.09
  // pitchers: era / whip / k_per_9 / bb_per_9 / k_bb_pct + sample_unit "IP"
}
```

- `level`: the level the line is from (AA/AAA/A+/…). Required.
- `sample` + `sample_unit`: size + "PA" (hitters) or "IP" (pitchers). Required.
- rate stats: the **same keys** the current `stat_line` carries for that player's side. Required.
- `reason`: provenance string, e.g. `current_level_too_thin_best_prior_level`. Required.

Omit the field entirely when current-level clears threshold, or when no other level clears it.
A 1.x feed without the field must keep working (consumer treats absent = current behavior).

## Consumer side (ValuCast app — this repo)

### Line selection precedence (skill-shape read + percentiles)

1. Current-level `stat_line` clears threshold → use it. Label = current level. (unchanged)
2. Current-level thin AND `best_single_level_stat_line` present & clears threshold → use the
   best line for percentiles/skill-shape, **labeled with that line's level, not "current."** Show:
   - "Current level sample is thin."
   - "Best 2026 read: {level}, {sample} {sample_unit}."
3. Neither clears → "The sample is too small to read the skill shape yet." (current fallback)

### Percentile pool rule

The best single-level line is a clean single-level raw line, so it ranks against the existing
raw "all levels" pool exactly like any other player's line — **provided the card labels it with
its own level** (so the user knows the 95th-percentile OPS is an AA read, not AAA). Never relabel
it as the current level. Never substitute the translated line here.

### Consumer touchpoints (file:line — verify before editing)

- `web/dynasty_models.py:70-74` — add `best_single_level_stat_line: dict | None = None`;
  coerce in `from_feed` near `:298-301`.
- `web/prospect_percentiles.py`:
  - `_performance_line` (`:95`) — extend the chooser: current `stat_line` if it clears threshold,
    else `best_single_level_stat_line` if present & clears, else translated/empty. Return enough for
    the caller to know WHICH level/source was used (e.g. add the level label to the return).
  - `card_percentiles` (`:688`) / `qualifies_hitter`/`qualifies_pitcher` (`:646`/`:652`) — gate and
    rank off the chosen line, not unconditionally `row.stat_line`.
  - `pool_label` (`:704`) — when the chosen line is the best-single-level line, label its level
    ("vs ValuCast hitter pool — all levels — 100+ PA · read: AA").
- `app.py`:
  - `_prospect_player_card_read` (`:1313`) + `_graphic_read_intro` (`:1253`) — the thin-sample
    branch shows the "Best 2026 read: {level}, {sample}" framing instead of the bare "too small"
    line when a best-single-level line exists.
- `templates/partials/player_detail_dynasty.html` — surface the "Current level sample is thin /
  Best 2026 read" note alongside the existing Current Level / sample labels.

### Non-goals

- No raw combine across levels. No translated-vs-raw-pool ranking. No change to how the overall
  dynasty value / rank are computed (those already use scouting + breakout, not just the line).

## Test plan

- Producer: emit only when current thin AND another level clears; pick the largest qualifying level.
- Consumer (synthetic rows, no producer dependency):
  - current clears → uses current line, no "best read" note. (unchanged)
  - current thin + best present & clears → percentiles/read use best line, labeled with its level;
    "Best 2026 read: {level}, {sample}" shown.
  - current thin + no best field → "too small to read" fallback. (unchanged)
  - best line never ranked relabeled as current level; translated line never ranked vs raw pool.
