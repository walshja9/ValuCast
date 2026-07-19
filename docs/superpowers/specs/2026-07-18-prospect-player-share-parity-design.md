# Prospect Player-Card / Share-Graphic Parity Design

**Date:** 2026-07-18
**Status:** Approved visual direction; probability requirements superseded by `2026-07-19-prospect-evidence-honesty-design.md`
**Branch:** `codex/role-watch-implementation`

## Purpose

Make the existing prospect player share graphic carry every decision-relevant
field shown on the prospect player card. Keep one player-card system: the HTML
detail and PNG are two renderings of the same context, not separate products.

The work follows the evidence-honesty contract: shadow outcome percentages and
heuristic Peak percentages stay off public HTML and PNG surfaces. It changes
presentation, not models, ranks, values, caps, or publication decisions.

## Approved Product Rule

The prospect player card remains the source of truth. When a decision-relevant
section is present on that card, the PNG must carry the same values, meaning,
sample/provenance disclosure, and availability state. When a section has no
data, both surfaces omit it rather than render an empty shell.

The PNG does not reproduce navigation, interactive links, collapsed duplicate
raw tables, or every individual external-board row. Those are access mechanics
or drill-down data, not separate decisions. The QR code continues to return the
reader to the complete live card.

## Existing Components to Reuse

- `app.py::_build_dynasty_player_detail_context` is the existing complete
  player-detail context builder. The prospect PNG route will reuse it instead of
  independently reassembling card data.
- `web.public_snapshot_models.DynastyRankingRow` already exposes the value,
  confidence, qualitative peak outlook, attribution, and role fields.
- Existing percentile, plate-discipline, AAA Statcast, rank-history, shape-comps,
  scouting, FanGraphs, consensus, and forward-ledger readers remain unchanged.
- The existing Pillow renderer, graphic palette, typography, QR helper, wrapping
  helpers, and dynamic-height pattern remain in place.

No dependency, client-side code, new model artifact, or second card component is
introduced.

## Data Flow

1. `GET /prospects/player-card/<player_id>.png` calls
   `_build_dynasty_player_detail_context(player_id, request.args)`.
2. The route rejects unavailable, missing, or non-prospect rows exactly as today.
3. The renderer receives the shared detail context and uses `context["row"]` plus
   the same prepared sections consumed by `player_detail_dynasty.html`.
4. Conditional sections derive their height before drawing.
5. The PNG draws available sections in the order below and retains the live-card
   QR/footer.

Direct unit-test calls to `_prospect_player_card_png(row)` may keep a small
fallback that builds the minimum context from existing readers. Production uses
the shared context path so future player-card additions have one obvious parity
point.

## PNG Information Order

### 1. Identity and current decision

- Player, team, positions, level, age.
- ValuCast value and current prospect rank.
- ETA and confidence when present.
- Format ranks.
- Availability warning when present.
- Ahead-of-consensus or dated rank receipt when present.

### 2. How ValuCast graded him

- Existing `why_rank_chips`, up to the same four-chip page limit.
- Material attribution effects and confidence drivers when present, including
  availability discounts, calibration adjustments, sample sufficiency, and the
  value range. Context-only items stay explicitly labeled as context.
- A compact accountability footer points to Model Verdicts through the live card;
  no clickable-link simulation is drawn into the PNG.

### 3. Current evidence

- The same current-sample label and skill percentile bars.
- The current/projected skill-shape comparison.
- Existing 2026 MiLB production table.
- Headline plate-discipline rows with the existing source and estimate labels.
- AAA Statcast pitch-shape/contact-quality evidence when present, with the same
  `AAA only`, `display context`, and `not a model input` disclosure.
- Raw observed Strike% when present, carrying its existing context-only note.

The PNG keeps the headline plate-discipline selection already used for sharing;
the collapsed raw MiLB and MLB-equivalent tables remain live-card drill-downs.

### 4. Interpretation and movement

- Full ValuCast Read, using the same scouting report selected for the HTML card.
- Recent-form and buy-board context when present.
- The real VC rank-trend sparkline, first/current rank, and archive dates.
- The qualitative Peak Outlook: ceiling scenario, floor scenario, evidence
  strength, and window.
- Shape comparisons and resolved-cohort disclosure when present.

### 5. Source and confidence context

- Current level/sample and value range.
- Consensus median, number of boards, and ValuCast gap/receipt when available.
- Forward Ledger claim badge only when its existing public gate allows it.
- FanGraphs FV and key tool/pitch grades when present.
- Explicit statement that external boards and scouting grades are context only
  and do not feed ValuCast rank or value.

Individual external-board rows, duplicated full raw-stat grids, and navigation
links remain on the live card behind the QR code.

## Layout

- Preserve the existing vertical social-card format and 1080-pixel width.
- Use one continuous card with section dividers, not nested poster systems.
- Measure optional sections first and grow the canvas; never squeeze, overlap, or
  clip content to retain a fixed height.
- Keep outcome explanation and current evidence above the fold of the preview.
- Long prose uses the existing sentence-safe wrapping helper.
- All graphics retain readable contrast, non-color labels, and source/as-of text.
- No empty section is drawn.

The approved Kade Anderson mockup establishes the composition, not hard-coded
player values or player-specific logic.

## Wording Guard

`bust_risk` and `row.outcome_mix` remain internal research fields because changing
the data contract is outside this work. Neither public HTML nor any share graphic
may render them.

## Testing

### Focused behavior tests

- The production PNG route builds and passes the shared detail context.
- A prospect with outcome data never renders outcome percentages or `Bust risk`
  in shared public render data.
- Peak ceiling, floor, evidence strength, and window match the HTML context;
  Peak score, upside, generic risk, and role probabilities do not render.
- Rank-trend, AAA Statcast, plate-discipline, shape-comps, external-context,
  FanGraphs, and ledger sections render only when present.
- Material attribution/uncertainty fields match the HTML context.
- Missing optional data produces no empty panel.
- The PNG remains valid and grows when optional sections are added.
- Injured/inactive availability disclosure travels with the graphic.

### Regression and visual checks

- Run focused prospect-card, outcome-language, card-intelligence, rank-history,
  AAA Statcast, plate-discipline, comps, and receipt tests.
- Run the complete automated suite.
- Render Kade Anderson plus one hitter, one player with AAA Statcast, one injured
  player, and one sparse-data negative control.
- Inspect each PNG at native resolution and in the phone-width preview.
- Confirm no overlap, clipping, unreadable source text, empty panels, or public
  `Bust risk` wording.
- Confirm model artifacts, rank/value outputs, pitcher caps, publication gates,
  Role Watch hold, failed decay flag, and League Connect state are unchanged.

## Expected File Scope

- Modify `app.py` for the shared context handoff and Pillow sections.
- Modify focused tests, primarily `tests/test_app.py` and existing section-specific
  prospect-card tests.
- Modify no template unless testing reveals a genuine meaning mismatch; the HTML
  card is already the source of truth.
- Add no CSS, JavaScript, dependency, model, or generated daily artifact.

## Launch Gate

Implementation completion is not deployment authorization. Before release:

1. Full tests pass on the release commit.
2. Desktop/native PNG and phone-preview visual checks pass for the five cases.
3. Public HTML and PNG show identical supported decision fields and no shadow
   outcome or heuristic Peak percentages.
4. Model/rank/value/publication outputs remain unchanged.
5. Role Watch remains held unless separately authorized.
6. Production deployment receives explicit approval.

The no-push window and workflow-dispatch restrictions remain in force.
