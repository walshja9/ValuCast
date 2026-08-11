# Proof-First Navigation Design

## Decision

ValuCast's primary navigation will lead with its differentiated signal and proof surfaces: `Movers`, `Buys`, and `Receipts`. The header will keep the core board and prospect hub immediately available, while lower-frequency research and utility destinations move into one semantic `Research` disclosure.

This implements the approved Option 1. It does not add a product surface, route, data source, or analytics system.

## Evidence

The public aggregate metrics endpoint reported this seven-day route mix at `2026-08-11T02:54:08Z`:

| Route | Pageviews |
|---|---:|
| `/` | 976 |
| `/buys` | 55 |
| `/movers` | 54 |
| `/glossary` | 44 |
| `/backfields/team/<org>` | 35 |
| `/ledger` | 29 |
| `/backfields` | 28 |
| `/gaps` | 21 |
| `/methodology` | 19 |
| `/receipts` | 19 |

The exact counts have moved since the earlier read, but the decision is unchanged: Movers and Buys already demonstrate demand, Receipts materially trails them despite carrying the strongest proof, and trust-seeking routes such as Glossary and Ledger have meaningful usage. Farm-system discovery is already healthy enough that it does not need to displace the proof layer.

## Approaches Considered

### 1. Proof-first primary navigation plus Research disclosure — selected

Keep the differentiated trio visible, retain the two broad entry points, and place secondary research destinations in a native disclosure. This gives the header a clear positioning statement without deleting access.

Trade-off: secondary destinations take one additional click from the header.

### 2. Proof-first flat navigation

Reorder the existing nine links but keep every destination visible. This has the smallest code diff and no extra click, but it preserves the crowded, wrapping header and weakens the hierarchy the change is meant to create.

### 3. Two-row grouped navigation

Put proof on one row and boards/research on another. This keeps everything visible, but makes the header taller on the mobile devices that account for many social arrivals and introduces a second visual hierarchy above the page content.

## Information Architecture

The primary header order will be:

1. `Movers` -> `/movers`
2. `Buys` -> `/buys`
3. `Receipts` -> `/receipts`
4. `Rankings` -> `/`
5. `Farm Systems` -> `/backfields`
6. `Research` -> native disclosure

The `Research` disclosure will contain:

1. `Disagreements` -> `/gaps`
2. `The Ledger` -> `/ledger`
3. `Glossary` -> `/glossary`
4. `Archives` -> `/board`
5. `Map` -> `/map`
6. `Methodology` -> `/methodology`

Trade, cards, scouting, model verdicts, and other specialized tools remain available through their existing contextual links, Intelligence Hub, and footer. They are not added to the header.

The board-level horizon selector will remain a horizon selector rather than a second destination menu:

- `Redraft`
- `Dynasty`
- `Prospects`

The current `Backfields` tab will be removed from that selector because the same destination is already represented by the primary `Farm Systems` entry. No route is removed; `/backfields` remains the prospect hub.

## Held-Surface Contract

`Buys` and `Receipts` remain in their fixed primary positions when their hold flags are true.

- The link remains clickable.
- A compact visible `Held` marker appears with the label.
- Accessible text identifies the destination as temporarily held.
- The link continues to the existing branded hold page.
- The held route continues to protect board rows and share graphics under the existing route contract.
- No disabled link, silent disappearance, replacement destination, or data-pipeline behavior is introduced.

This keeps the information architecture stable and makes a hold an honest product state rather than an absent product.

## Interaction and Accessibility

`Research` will use native `<details>` and `<summary>` behavior. This provides keyboard and touch activation without a navigation framework.

- Each destination remains a real anchor.
- The current destination receives `aria-current="page"`.
- The `Research` control receives an active visual state when one of its destinations is current.
- Escape and outside-click behavior will follow the app's existing disclosure-menu pattern.
- Focus-visible styling will match existing site navigation controls.
- Desktop renders the menu as a compact anchored panel.
- At `640px` and below, the menu becomes a full-width row beneath the primary pills so it cannot overflow the viewport.

## Metrics Evaluation

No new tracking event or schema is needed. The existing aggregate `/metrics/summary` route is the evaluation source.

Record the pre-change seven-day baseline above. After seven complete days in production, compare:

- `/receipts` pageviews and its ratio to `/` pageviews;
- `/movers` and `/buys` pageviews as demand controls;
- `/backfields` plus `/backfields/team/<org>` as the prospect-workflow control;
- `/gaps`, `/ledger`, `/glossary`, `/board`, `/map`, and `/methodology` for any Research-menu discoverability loss.

Annotate any interval where Buys or Receipts was held. At this scale, treat direction and route share as the primary signal; do not claim causality from a one-week count alone. Repeat at fourteen days if the seven-day sample is noisy.

## Files and Boundaries

Expected implementation scope:

- `templates/base.html`: primary hierarchy, held markers, Research disclosure.
- `templates/partials/_board_nav.html`: remove the duplicate Backfields destination.
- `static/style.css`: primary group, held marker, disclosure, desktop/mobile behavior.
- Existing navigation tests: update order, hold-state, disclosure, active-state, and horizon assertions.

No changes are expected in:

- routes or route handlers;
- prospect scoring or quality-governor policy;
- the metrics store or schema;
- hold flag definitions;
- data artifacts or daily pipeline stages.

## Testing

Focused tests will prove:

- primary links appear in the approved order;
- Buys and Receipts remain visible and clickable when held;
- held links expose visible and accessible hold state;
- Research contains the six approved destinations;
- a Research child receives `aria-current` and activates its parent control;
- the horizon selector contains Redraft, Dynasty, and Prospects but not Backfields;
- existing hold pages still suppress protected content;
- no route or data behavior changed.

Browser verification will cover keyboard operation and 390px/desktop layouts. Repository-wide pytest remains the final automated gate, with any unrelated live-data fixture failure reported separately rather than hidden.

## Acceptance Criteria

- `Movers`, `Buys`, and `Receipts` are the first three primary-navigation destinations.
- The header teaches ValuCast's signal-and-proof identity before its utilities.
- Buys and Receipts never silently disappear during a hold.
- Rankings and Farm Systems stay one tap away.
- All former primary destinations remain reachable through Research or existing contextual/footer links.
- The duplicate Backfields horizon tab is removed without removing `/backfields`.
- The mobile header is shorter and has no horizontal overflow.
- Existing metrics can support a seven-day and fourteen-day before/after read.

