# League Values Product Design

**Date:** 2026-05-18
**Status:** Approved, ready for implementation planning

## Problem

Fantasy baseball valuation tools either hardcode one league format or require users to upload their own projection CSVs. There's no tool where you pick your league's categories and instantly see ranked player values backed by real projections.

## Goal

A standalone web app where users configure their league format (H2H categories, roto, or points), select categories, set roster sizes, and instantly see ranked dynasty player values. Built-in projections — no uploads, no friction. Year-round dynasty valuations plus draft-day rankings.

## Target Users

Fantasy baseball players who want dynasty valuations or draft rankings tuned to their specific league format. Both mid-season check-ins and startup draft prep.

## MVP Scope (Phase B)

- League setup: scoring format, category/points picker, roster settings
- Ranked player table with per-category breakdowns
- Pool/position filtering and player search
- Two-player comparison
- Shareable URLs (config in query params)
- No auth, no saved configs (Phase C follow-up)

## Phase C Follow-Up (post-launch)

- Saved league configs (localStorage or accounts)
- Auction dollar conversion
- Tier breakdown visualization
- CSV export

---

## 1. Data Pipeline

### Sources

FanGraphs Steamer and ZiPS projections — freely available, widely trusted. Scraped via Playwright.

### Scraper

`scraper/fangraphs.py` — Playwright hits FanGraphs projection pages for Steamer hitters, Steamer pitchers, ZiPS hitters, ZiPS pitchers. Downloads raw data, saves to `data/projections/` as JSON.

### Blending

`scraper/blend.py` — 50/50 Steamer/ZiPS blend for counting stats, weighted average for rate stats. In-season, blending shifts toward actuals as sample size grows (same approach as DD's projection_blender: <30 PA = 95% proj / 5% actual, scaling to 500+ PA = 10% proj / 90% actual).

### Storage

`data/projections/current.json` — flat file with ~800 hitters and ~500 pitchers. Regenerated nightly by cron. App reads on startup, caches in memory.

### Refresh Schedule

Nightly cron (7 AM ET) runs `scraper/refresh.py`: scrape both sources, blend, write `current.json`, commit and push (triggers Render redeploy).

### Stats Stored Per Player

**Hitters:** PA, AB, R, HR, RBI, SB, SO, H, BB, AVG, OBP, OPS, SLG

**Pitchers:** IP, K, W, L, QS, SV, HLD, ERA, WHIP, K_BB, ER, BB, H_ALLOWED

This covers every common category format: standard 5x5, OBP leagues, QS leagues, SV+H leagues, points leagues.

---

## 2. League Setup Flow

Single page, three-step configuration. Every change fires an htmx request that recalculates and swaps the rankings table. No submit button — it's live.

### Step 1: Scoring Format

Radio buttons: H2H Categories | Roto | Points. Selection changes what appears in Step 2.

### Step 2: Categories or Points Rules

**Categories/Roto mode:** Two columns — hitting (left) and pitching (right). Each is a checkbox list of all common categories:

- Hitting: R, HR, RBI, SB, AVG, OBP, OPS, SLG, H, BB, SO, TB, NSB (net steals)
- Pitching: W, L, K, QS, SV, HLD, SV+H, ERA, WHIP, K/BB, IP, K/9, HR/9, BB/9

Presets at top: "Standard 5x5", "Standard 6x6 (OBP/QS)", "Custom". Picking a preset checks the right boxes. User can toggle individual categories after.

**Points mode:** Table of stat-to-points mappings. Presets for ESPN/Yahoo/Fantrax defaults. Point values editable inline.

### Step 3: Roster Settings

- Teams: dropdown (8, 10, 12, 14, 16). Default: 12.
- Positions: checkboxes with count inputs. Default: C:1, 1B:1, 2B:1, SS:1, 3B:1, OF:3, UTIL:1, SP:5, RP:2, Bench:5.

### URL-Based Config

URL updates with query params on every change: `/rankings?mode=categories&cats=R,HR,RBI,SB,OBP&pcats=K,QS,SV_HLD,ERA,WHIP&teams=12`

Config is shareable and bookmarkable. No auth needed.

---

## 3. Rankings Display

### Table

Below the setup controls. Single sortable table, all players ranked by value.

**Columns:**
- Rank (#)
- Player name
- Positions (multi-elig: "SS, 3B")
- MLB Team
- Age
- Value (composite, bold, primary sort)
- Per-category z-scores or points (one column per active category, collapsible on mobile)

### Filtering

- Pool toggle: All / Hitters / Pitchers (tab buttons above table)
- Position filter: dropdown (All, C, 1B, 2B, SS, 3B, OF, SP, RP)
- Search box: player name filter

All filters fire htmx partial swaps.

### Player Detail

Click a row to expand an inline detail card:
- Full stat projections (all stats, not just active categories)
- Per-category z-score breakdown
- Position eligibility
- Age + MLB team

### Compare Mode

Check two players via checkbox on each row. Floating bar at bottom: "Compare (2)". Click opens a modal overlay showing side-by-side values and per-category z-scores. Simple modal, not a separate page.

### Mobile

Table collapses to card layout below 640px. Each card: rank, name, positions, value, top 3 contributing categories. Tap to expand full breakdown.

---

## 4. Application Architecture

### File Structure

```
league-values/
  app.py                    # Flask app, routes, htmx endpoints
  data/
    projections/
      current.json          # Blended projections (nightly)
      steamer_hitters.json  # Raw source
      steamer_pitchers.json
      zips_hitters.json
      zips_pitchers.json
  scraper/
    fangraphs.py            # Playwright scraper
    blend.py                # Blending logic
    refresh.py              # Orchestrator: scrape -> blend -> write
  src/league_values/        # Existing engine (unchanged)
  templates/
    base.html               # Layout, htmx script, minimal CSS
    index.html              # League setup + rankings (single page)
    partials/
      rankings_table.html   # htmx partial — rankings table
      player_detail.html    # htmx partial — inline detail card
      compare_modal.html    # htmx partial — comparison overlay
  static/
    style.css               # Single stylesheet
  tests/                    # Existing engine tests + new app/scraper tests
```

### Routes

| Route | Method | Returns | Purpose |
|-------|--------|---------|---------|
| `/` | GET | Full page | Landing — setup controls + default 5x5 rankings |
| `/rankings` | GET | htmx partial | Rankings table, accepts league config query params |
| `/player/<id>` | GET | htmx partial | Player detail card |
| `/compare` | GET | htmx partial | Two-player comparison, `?p1=<id>&p2=<id>` |

### Request Flow

1. User toggles a category checkbox
2. htmx fires `GET /rankings?mode=categories&cats=R,HR,RBI,SB,OBP&pcats=K,ERA,WHIP&teams=12`
3. Flask parses params, builds `LeagueConfig` from query string
4. Calls `ValuationEngine(post_processors=[...]).value_players(projections, config)`
5. Renders `partials/rankings_table.html` with results
6. htmx swaps the table in the DOM

Sub-second response — projections cached in memory, engine runs in ~10ms for 1300 players.

### Tech Stack

- **Backend:** Flask 3.0, Python 3.12+
- **Frontend:** Jinja2 templates, htmx 2.0, vanilla CSS
- **Scraping:** Playwright (FanGraphs)
- **Engine:** league_values package (existing, in-repo)
- **Deploy:** Render (auto-deploy from GitHub)

---

## 5. Engine Enhancements

Two additions needed before the app produces trustworthy output:

### Volume Multiplier Post-Processor

Players with partial-season projections shouldn't get full value.

- Hitters: `max(0.20, (PA / 550) ^ 0.75)`, 550+ PA = 1.0
- SP: `max(0.20, (IP / 180) ^ 0.75)`, 180+ IP = 1.0
- RP: `max(0.20, (IP / 65) ^ 0.75)`, 65+ IP = 1.0

Reads PA/IP from player stats, applies as a multiplier to total_value. Composable post-processor like ReplacementLevel/PositionScarcity/AgeCurve.

### RP Baseline Handling

Relievers need different baselines (K avg=48 vs SP K avg=120). MVP approach: split pitchers into two pools (`starter` and `reliever`) using a `RELIEVER` pool type. Define separate category baselines per pool. The user picks "pitching categories" and the engine internally evaluates SP and RP against their own baselines.

### Not Needed for MVP

Independence multipliers, market calibration, performance penalties, prospect rank paths. These improve accuracy but the app produces solid rankings without them.

---

## 6. Non-Goals

- **Auth/accounts** — Phase C, not MVP
- **Mobile app** — web-first, responsive design handles mobile
- **Trade analysis** — requires team context, out of scope
- **Live scoring** — this is a projection-based tool
- **Prospect rankings** — only MLB players with projections for MVP

## 7. Success Criteria

- User can configure any common league format in under 30 seconds
- Rankings update in under 1 second after any setting change
- Same projection set + different configs = meaningfully different rankings
- Mobile works (card layout, tap to expand)
- Shareable URL reproduces exact rankings
- Projection data refreshes nightly without manual intervention

## 8. Decomposition

This product has three independent subsystems, each gets its own plan:

1. **Engine enhancements** — volume multiplier + RP baselines (prerequisite)
2. **Data pipeline** — FanGraphs scraper + blending (prerequisite)
3. **Web app** — Flask + htmx + templates (depends on 1 and 2)

Build in this order. Each is independently testable and shippable.
