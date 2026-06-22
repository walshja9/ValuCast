# Backfields Consolidation + Team Prospect Graphics Design

## Summary

Backfields becomes the public prospect hub for ValuCast. The old prospect-adjacent destinations still exist as deeper utility routes, but they stop competing in the primary navigation. Users should understand one rule: if it is about prospects, call-ups, minor-league signals, scouting reads, or prospect share graphics, start in Backfields.

The new functional addition is MLB-organization prospect share graphics. ValuCast already lets users filter scouting/prospect context by organization; the missing product surface is a shareable `Top 10` / `Top 20` graphic for that organization. This should reuse ValuCast's own prospect order filtered to an MLB organization, not public team rankings.

## Goals

- Make Backfields the single prospect front door.
- Remove the remaining top-nav redundancy between `Backfields`, `Scouting`, and the old prospects board. `Buys` has already been removed from the top nav and should stay demoted.
- Keep `/buys`, `/scouting`, and `/?mode=prospects` alive as deep routes and engines.
- Add MLB-organization team boards inside Backfields.
- Add shareable MLB-organization `Top 10` and `Top 20` prospect graphics.
- Preserve the current Backfields warm dialect and the Broadcast/app-export graphic style.
- Avoid adding new data pipelines. Reuse the public snapshot, existing scouting reports, current prospect rows, recent signal report, and Buys context.

## Non-Goals

- Do not create a separate Backfields sub-brand.
- Do not remove `/buys` or `/scouting`; demote them from top-level discovery only.
- Do not introduce public MLB Pipeline, FanGraphs, HKB, or consensus team ranks into the team graphics.
- Do not add headshots to Backfields lists or team graphics.
- Do not build full organization landing pages with custom long-form copy in this pass.
- Do not rebuild the old prospect board table. Backfields remains the public hub; the board remains the detail/table engine.

## Current State

Backfields already has the right foundation:

- Header nav includes Backfields.
- Buys has already been demoted from the top nav; Scouting still appears there and should move behind Backfields.
- Backfields Ahead of the Curve uses the live Buys graphic source.
- Visible player names open inline player detail.
- `Report` links stay distinct and open scouting report search.
- Rankings sort client-side by rank, player, level, move, and value.
- Call-Up Desk, Stats, and Scouting Reports are deeper than the original reference stub.

The remaining issue is product hierarchy. Users can still perceive overlapping prospect surfaces instead of one hub with drill-down tools.

## Information Architecture

Primary nav should become:

- `Board`
- `Backfields`
- `Map`
- `Intelligence Hub`
- `Methodology`

`Scouting` should be removed from the top nav. `Buys` should remain out of the top nav. Both remain accessible as:

- Backfields `Ahead of the Curve` section -> `/buys`
- Backfields `Latest Reports` / `Scouting Reports` section -> `/scouting`
- Player row `Report` link -> `/scouting?q=<player>`

The old prospects mode should no longer be promoted as a top-level destination. It remains available as:

- inline detail source for Backfields player cards
- full prospect table fallback/deep link where needed
- search-target fallback when a direct player route is unavailable

Backfields in-page sections:

- `Rankings`
- `Ahead of the Curve`
- `Call-Up Desk`
- `Team Boards`
- `Stats`
- `Latest Reports`

## Team Boards

Add a Backfields module named `Team Boards`.

Behavior:

- Show an MLB organization selector.
- Default state can show the first few organizations with strong current signal, or a compact selector only.
- Selecting an organization filters ValuCast prospect rows to that MLB organization.
- Display the organization's top prospects in ValuCast prospect order.
- Show latest scouting reports for that organization when available.
- Show Call-Up Desk candidates for that organization when available.
- Show share actions:
  - `Share Top 10`
  - `Share Top 20`

Team board labels should use MLB organization names in public copy:

- `Boston Red Sox`
- `Cleveland Guardians`
- `Los Angeles Dodgers`

Where space is tight, use team abbreviations in metadata:

- `BOS`
- `CLE`
- `LAD`

## Organization Source And Normalization

Team Boards must group by MLB organization, not minor-league affiliate.

Use `row.team` as the grouping key. In the current public snapshot this is the MLB organization abbreviation (`BOS`, `LAD`, `MIL`, etc.) and it matches the scouting report `team` field. Do not group on Backfields' current `affiliate_for(row)` display helper, because that prefers `context.stat_line_team` and returns minor-league affiliates such as `Portland Sea Dogs` or `St. Paul Saints`.

Keep affiliate as row display context only. A team-board row can show `level / affiliate` so users know where the player is playing, but filtering and URLs are always MLB-org based.

Normalize organization aliases before grouping and routing:

- `KCR` -> `KC`
- `ATH` remains `ATH` unless the data source has already switched to another Athletics abbreviation.
- `FA` is not an MLB organization and should be excluded from Team Boards.

The route param should resolve aliases. For example, `/backfields/team/KCR` should serve the canonical `KC` board or redirect to `/backfields/team/KC`; it should not create a separate partial Royals board.

If a player has only an affiliate team and no MLB org, exclude them from team boards rather than guessing.

## Team Board Data Source

Team Boards must use the full prospect pool, not the top-200 public board slice.

The existing `_prospect_rows()` helper intentionally caps results at 200 for public board display. That cap is too shallow for organization Top 20 graphics; most teams would not have 20 prospects in the top-200 slice. Build Team Boards from the full prospect universe, equivalent to `dd_store.filter(pool="prospect")`, sorted by the same ValuCast prospect order used by the public board:

1. rows with a `prospect_rank` first,
2. ascending `prospect_rank` when present,
3. ascending `dynasty_rank` as fallback.

Then filter by canonical MLB organization and compute `org_rank` within that filtered set. This keeps team Top 10/20 graphics feasible and honest while preserving ValuCast prospect order.

## Routes

Recommended routes:

```text
/backfields
/backfields/team/<org>
/backfields/team/<org>/share-card
/backfields/team/<org>/share-card.png?n=10
/backfields/team/<org>/share-card.png?n=20
```

`<org>` should accept existing MLB abbreviations from the snapshot/scouting context plus the aliases above. Unknown organizations should return a clean 404 page, not an empty graphic.

The HTML preview route, `/backfields/team/<org>/share-card`, should render the selected organization's share card with download buttons for Top 10 and Top 20.

The PNG route should enforce `n in {10, 20}`. Invalid values should return `400` with a short error message so bad share URLs fail visibly instead of silently producing the wrong graphic.

## Team Graphic Design

The team prospect graphic is an exported Backfields surface, not a sports-card poster.

Format:

- `1080x1350` PNG.
- Uses the current Broadcast/app-export visual system.
- Neutral cool-black base, not the warmer Backfields page background.
- Compact ValuCast lockup.
- One quiet arc signature.
- Teal only on values, upward movement, and the primary signal.
- Clay only on downward movement.
- Slate for rank, structure, and secondary labels.
- No headshots.
- No team-color flood.

Suggested copy:

```text
ValuCast · Backfields
Boston Red Sox Top 20
Prospect board · Updated JUNE 22, 2026
```

Rows:

- organization rank
- player name
- position
- level
- ValuCast value
- recent movement if available

Footer:

```text
valucast.app · Backfields · ValuCast prospect order
```

The graphic should say "ValuCast prospect order" or equivalent so it is clear this is not a public org ranking average.

## Data Flow

Backfields context builder should expose a team-board payload:

```python
{
    "team_boards": {
        "teams": [...],
        "selected": {...} | None,
        "rows": [...],
        "reports": [...],
        "callups": [...],
    }
}
```

Each team row should include:

- `id`
- `name`
- `url`
- `detail_url`
- `report_url`
- `rank`
- `org_rank`
- `team`
- `affiliate`
- `position`
- `level`
- `value`
- `value_sort`
- `move`
- `has_report`

`team` is the canonical MLB organization key used for grouping and routing. `affiliate` is display-only minor-league context. `org_rank` is computed inside the filtered organization set; it is not present in the raw data.

The same row-shaping helper should feed:

- Backfields team module
- team share preview
- team PNG renderer

This prevents the page and share graphic from drifting.

## Error Handling

- If the public snapshot is unavailable, Backfields should keep its existing unavailable/empty states.
- If a valid organization has fewer than 10 prospects, render all available rows and label the graphic `Top prospects`.
- If a valid organization has zero eligible rows, show a clear empty state and do not offer a PNG download.
- If scouting reports are missing, Team Boards still work from prospect rows.
- If movement data is missing, show a neutral dash rather than inventing movement.

## Testing

Add focused tests for:

- Top nav does not include top-level `/scouting`, and `/buys` remains absent from top nav.
- Backfields still links to `/buys` and `/scouting` as deeper surfaces.
- Backfields includes a `Team Boards` section.
- Team selector options are derived from real team/org values.
- Team Boards group on MLB org (`row.team`), not MiLB affiliate.
- `KCR` and `KC` resolve to one canonical Royals board.
- `FA` rows do not appear in Team Boards.
- Team Top 20 routes source from the full prospect pool, not the top-200 board slice.
- `/backfields/team/<org>` returns 200 for a known organization.
- Unknown org returns 404 or the existing clean not-found page.
- Team row names link to player detail.
- Team row report links remain distinct from player links.
- `/backfields/team/<org>/share-card.png?n=10` returns PNG bytes.
- `/backfields/team/<org>/share-card.png?n=20` returns PNG bytes.
- Share graphic route uses ValuCast prospect order filtered by organization.
- No external-rank or consensus language appears in the team graphic.

Keep tests focused; do not snapshot entire HTML pages.

## Rollout Plan

1. Update nav and in-page Backfields copy so Backfields is the sole prospect hub.
2. Add team-board context helpers using existing prospect/scouting data.
3. Add Backfields Team Boards module.
4. Add team routes and preview page.
5. Add PNG renderer for Top 10/Top 20 organization graphics.
6. Add focused route/template/PNG tests.
7. Browser-check `/backfields`, one team page, and both Top 10/Top 20 graphics on desktop and mobile.

## Acceptance Criteria

- A new visitor can start from top nav and understand Backfields is the prospect hub.
- There is no top-nav competition from `Scouting`, and `Buys` remains demoted behind Backfields.
- Backfields still exposes the full Ahead of the Curve board and scouting archive as drill-down links.
- A user can select an MLB organization and generate a Top 10 or Top 20 prospect graphic.
- The organization graphic matches current ValuCast share-graphic quality.
- The organization graphic uses ValuCast prospect order and says so plainly.
- No new data source or ranking methodology is introduced.
