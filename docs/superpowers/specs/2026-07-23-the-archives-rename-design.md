# The Archives Rename Design

## Goal

Rename the public Board Time Machine surface to **The Archives** so ValuCast
uses distinct product language while preserving the existing historical-board
feature exactly.

## Public Copy

- Primary navigation: `The Archives`
- Page title and social title: `The Archives | ValuCast`
- Page eyebrow and empty-state heading: `THE ARCHIVES`
- Methodology heading: `The Archives: committed boards, replayed`
- Methodology and page links: `How The Archives works` and `The Archives`

The dated state continues to lead with `BOARD AS OF <date>` because that is the
clearest description of what the user is viewing.

## Unchanged

- Routes remain `/board` and `/board/<date>`.
- Archive data, dates, quality flags, consensus aggregation, and rendering
  behavior remain unchanged.
- Internal Python names, filenames, CSS selectors, methodology anchor
  `#board-time-machine`, and historical plans remain unchanged.
- No model, ranking, value, refresh, workflow, or deployment changes.

## Testing

Update the existing navigation assertion to expect `The Archives`, add no new
test framework or helper, and run the focused Board route tests plus the full
suite before publishing.
