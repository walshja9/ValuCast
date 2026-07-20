# Share Distribution Design

**Date:** 2026-07-20
**Status:** Approved direction; awaiting written-spec review
**Scope:** Display and distribution only

## Goal

Make ValuCast's existing farm-system analysis and share graphics easier to find and publish without changing any rank, value, model, cap, hold, or publication decision.

## Release

1. Add a deterministic 1080x1350 farm-system rankings PNG using the existing `/farms` context and existing ValuCast graphic primitives.
2. Add an HTML preview/download route for that PNG using the existing share-preview helper.
3. Add a clear `Share graphic` action to `/farms`.
4. Add the farm-system graphic and the existing default Dynasty and Redraft board graphics to `/cards`. Add the existing Forward Ledger graphic only when its hold is off.
5. Correct the hitter-comp disclosure that still points visitors to removed role probabilities. It will describe Peak Outlook as a separate qualitative scenario layer.

## Farm Graphic Content

The graphic shows all 30 organizations in two columns, ordered exactly as `/farms` orders them. Each row contains:

- farm rank;
- organization name and abbreviation;
- top-20 ValuCast Value total; and
- number of ValuCast top-100 prospects.

The header states the current method: sum of each system's top 20 dynasty values. The footer links to `/farms`, includes the data date, and carries the standard QR code. The graphic must not introduce grades, payroll data, individual player values, or new calculations.

## Data Flow

Both `/farms` and the graphic call `_build_farm_rankings_context()`. The renderer consumes the returned `systems` list; it does not rebuild or reorder the rankings. If no systems are available, the PNG route returns 503 and the HTML page keeps its existing fail-open message.

## Routes

- `/farms/share-card` — preview and download page.
- `/farms/share-card.png` — deterministic PNG.

Existing cache and security response hooks apply automatically.

## Testing

Tests are written first and must prove:

- the PNG route is missing before implementation, then returns a valid 1080x1350 PNG;
- the graphic contains all systems in canonical order through renderer inputs;
- `/farms` links to its share preview;
- `/cards` exposes Farm Systems, Dynasty, and Redraft, while Forward Ledger follows its existing hold;
- the obsolete role-probability disclosure is absent and the qualitative Peak Outlook disclosure is present;
- existing farm, share-card, public-surface, and prospect-comp tests remain green.

## Explicit Non-Goals

- no generic browser screenshot or "share any page" framework;
- no component-level comp model in this release;
- no pitcher comps;
- no new dependency;
- no changes to ranks, values, model inputs, pitcher caps, Role Watch, holds, or publication gates;
- no deployment.
