# ValuCast Design Spec

**Date:** 2026-05-25
**Status:** Approved
**Stack:** Flask + htmx (existing), redesigned frontend, Render deployment

## Overview

Rebrand and redesign the League Values app into **ValuCast** — a clean, modern fantasy baseball valuation tool. The engine, data pipeline, and htmx interactions are already built and working (v0.4.0, 177 tests). This work is purely frontend redesign, CSV export, and deployment.

**Tagline:** "Player values tuned to your league"

## Audience

Fantasy baseball players from casual (leaguemates who want rankings) to power users (tweaking category weights and SP/RP splits). The UX must serve both without compromise.

## UX Philosophy: Progressive Disclosure

- Page loads with Standard 5x5 H2H already applied — rankings visible immediately
- Collapsible "Customize" panel for power users (categories, weights, SP/RP split)
- No accounts, no wizard, no friction
- URL-based config sharing (already implemented)

## Page Layout

Single-page app, three zones top to bottom:

### 1. Header

- ValuCast wordmark left-aligned, tagline right
- Dark navy background (#1a1a2e)
- Bold, condensed typography for the wordmark — styled via CSS or SVG, not a full font swap

### 2. Config Bar

- **Mode selector** always visible — three pill buttons: H2H Categories / Roto / Points
- **"Customize" toggle button** expands the config panel
- **Collapsed state** shows a summary line: "Standard 5x5 - 12 teams - $200 budget" so users know what's active without opening the panel
- **Expanded state** shows: category checkboxes with weight inputs, presets (5x5, 6x6 OBP/QS), SP/RP split toggle
- Defaults to collapsed with Standard 5x5 pre-selected

### 3. Rankings Table (the hero)

- **Filter bar** above table: pool toggle (All/Hitters/Pitchers), position dropdown, search box, CSV export button (right-aligned)
- **Table columns:** Rank, Player Name (with position rank badge + tier badge), Positions, Team, Auction $, Value, then one column per active category
- **Interactions (all existing, no changes):**
  - Click-to-expand player detail
  - Compare mode (select two players, modal comparison)
  - Sortable columns (click headers)
  - Tier break lines between tier groups

### 4. Footer

- Minimal: "Data: FanGraphs Steamer + ZiPS projections" credit
- GitHub link optional

## Visual Design System

### Colors

| Role | Value |
|------|-------|
| Page background | #f5f6f8 |
| Cards/table | #ffffff |
| Header/dark | #1a1a2e |
| Accent | #2563eb |
| Primary text | #1a1a2e |
| Secondary text | #6b7280 |
| Positive | #16a34a |
| Negative | #dc2626 |

No changes from current palette — it already works.

### Typography

- Body: system font stack (-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif)
- Wordmark: bold, condensed, uppercase treatment for "ValuCast" in the header only

### Component Styling

- Setup panel: softer border-radius, smooth collapse/expand transition
- Table: tighter row padding, stronger header separation, hover highlight (not zebra striping)
- Tier badges: keep existing color array, slightly larger
- Buttons/pills: consistent 6px border-radius, uniform hover states
- Filter bar: subtle #f9fafb background tint to separate from table

### Responsive

- Mobile card layout below 640px (existing, no changes)
- Category grid collapses to single column on mobile (existing)
- Filter bar stacks vertically on mobile (existing)

### No Dark Mode

Not worth the complexity for launch. Can add later.

### No CSS Framework

Keep hand-rolled CSS (~360 lines). A framework would bloat it.

## CSV Export

- **Button:** "Export CSV" in the filter bar, right-aligned
- **Behavior:** Exports current filtered view (respects pool, position, search filters and active config)
- **Columns:** Rank, Player Name, Positions, Team, Position Rank, Tier, Auction $, Value, then one column per active category (z-score contribution)
- **Filename:** `valucast-rankings.csv`
- **Implementation:** New `/export` route. Same context-building as `/rankings`, returns CSV with `Content-Disposition: attachment` header. Server-side generation, no JavaScript file creation.

## Render Deployment

- Auto-deploy from GitHub on push (same pattern as Diamond Dynasties)
- **Build command:** `pip install -r requirements.txt`
- **Start command:** `gunicorn app:app`
- **Data:** `data/projections/current.json` ships with the repo (~2MB, 9366 players). No database.
- **Environment:** Python 3.12, no env vars required
- **URL:** `valucast.onrender.com` initially, custom domain later

### New Files

- `requirements.txt` — Flask, gunicorn
- `render.yaml` — explicit Render service config

## What Changes

1. Rebrand: header, page title, tagline — "League Values" becomes "ValuCast"
2. Config panel becomes collapsible with summary line when collapsed
3. CSS visual polish pass (spacing, transitions, component consistency)
4. CSV export button + `/export` route
5. Render deployment files (requirements.txt, render.yaml)

## What Stays the Same

- All engine logic (ValuationEngine, post-processors, models)
- Data pipeline (FanGraphs scraper, blender, refresh)
- All htmx interactions and Flask routes
- Sortable columns, compare mode, player detail expansion
- Tier visualization, position ranks, auction dollars
- Mobile responsive card layout
- Category weight inputs
- URL-based config sharing
