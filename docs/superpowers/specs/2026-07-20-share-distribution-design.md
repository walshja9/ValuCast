# Share Distribution Design

**Date:** 2026-07-20
**Status:** Approved
**Scope:** Display and distribution only

## Goal

Make ValuCast's existing farm-system analysis and share graphics easier to find and publish without changing any rank, value, model, cap, hold, or publication decision.

## Release

1. Add a deterministic 1080x1350 farm-system rankings PNG using the existing `/farms` context and existing ValuCast graphic primitives.
2. Add an HTML preview/download route for that PNG using the existing share-preview helper.
3. Add a clear `Share graphic` action to `/farms`.
4. Add the farm-system graphic and the existing default Dynasty and Redraft board graphics to `/cards`. Add the existing Forward Ledger graphic only when its hold is off.
5. Correct the hitter-comp disclosure that still points visitors to removed role probabilities. It will describe Peak Outlook as a separate qualitative scenario layer.
6. Add display-only Power, Contact, and Approach hitter matches to the existing overall hitter comps.
7. Deepen each organization report with value concentration, level distribution, hitter/pitcher balance, risers, buys, and top prospects.
8. Build a separately gated pitcher-comp foundation and publish descriptive pitcher matches only when historical coverage and role classification pass.

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

## Hitter Component Comps

The existing overall hitter match remains an era-normalized K% / BB% / ISO distance. Three component matches reuse those validated translated axes and the same historical pool:

- **Power:** ISO;
- **Contact:** K%; and
- **Approach:** BB%.

Each component shows the closest historical MLB season, the prospect and match values, and the absolute era-normalized distance. It never converts distance into a percentage or probability. The component section is display-only and appears on both the player card and its share graphic when the existing comp eligibility gate passes.

## Organization Reports

`/farms` remains a readable 30-team ranking summary. Each `/backfields/team/<org>` report adds:

- **Top-five concentration:** top-five value divided by top-20 value, labeled as concentration rather than quality;
- **Level distribution:** counts across Rookie, A, A+, AA, and AAA for the full ValuCast organization pool;
- **Top-20 balance:** hitter and pitcher counts among the same 20 players used by the ranking;
- **Risers:** up to three positive movers already present in the committed mover/signal data;
- **Buys:** up to three organization players already present on the committed ValuCast buy board; and
- **Top prospects:** the existing ordered organization board.

The existing organization share graphic carries the headline concentration, level, balance, riser, buy, and prospect information in compact form. Missing mover or buy evidence renders an honest empty state and never removes the underlying team board.

## Pitcher Shape Comps

A one-time/occasional network script creates a committed, runtime-offline MLB pitching-season history for 2000–2025. Runtime and daily card rendering never call the network.

Eligible historical seasons must have an unambiguous usage class:

- **starter:** starts are at least 50% of appearances and innings pitched are at least 50;
- **reliever:** starts are at most 10% of appearances and innings pitched are at least 30; and
- seasons between those role boundaries are excluded.

Prospects must have a high-confidence, non-low-sample translated line and a non-ambiguous current usage role from `components.factual_current_context`: starter requires `starter_role=true` and at least five starts; reliever requires `starter_role=false`, zero starts, and at least 30 IP. Rows with one to four starts, missing usage fields, or thinner samples are suppressed. Starter prospects match only starter seasons; reliever prospects match only reliever seasons. This classification describes current usage for comparison and is not a forecast.

Pitcher distance uses translated K-BB%, K/9, and BB/9, era-normalized within role and season. The public section initially shows only the nearest historical seasons, matched metrics, role pool, and measured distance. It publishes no outcome distribution, success probability, role forecast, or fantasy-useful-result claim. It is display-only and must declare that it does not feed ValuCast Value or rank.

## Testing

Tests are written first and must prove:

- the PNG route is missing before implementation, then returns a valid 1080x1350 PNG;
- the graphic contains all systems in canonical order through renderer inputs;
- `/farms` links to its share preview;
- `/cards` exposes Farm Systems, Dynasty, and Redraft, while Forward Ledger follows its existing hold;
- the obsolete role-probability disclosure is absent and the qualitative Peak Outlook disclosure is present;
- hitter component matches use only ISO, K%, and BB% and expose measured distance rather than percentages;
- organization summaries use the documented top-five/top-20, full-pool level, and top-20 role denominators;
- risers and buys come only from existing committed artifacts and fail soft when missing;
- pitcher matches are role-separated, suppress ambiguous roles, expose measured distance, and remain absent when the historical coverage gate fails;
- existing farm, share-card, public-surface, and prospect-comp tests remain green.

## Explicit Non-Goals

- no generic browser screenshot or "share any page" framework;
- no new dependency;
- no pitcher outcome probabilities or role forecasts;
- no changes to ranks, values, model inputs, pitcher caps, Role Watch, holds, or publication gates;
- no deployment.
