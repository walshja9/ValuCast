# Player Card Decision Hierarchy Design

**Date:** 2026-07-19
**Status:** Approved in conversation

## Goal

Make every interactive ValuCast player card answer four questions without requiring the reader to leave the card:

1. **Skill:** What performance does the evidence support?
2. **Opportunity:** How much playing time is projected, and what role or availability facts matter?
3. **ValuCast Value:** What does that combination mean in the selected fantasy format?
4. **Confidence:** How much evidence supports the answer, and what could change it?

The product should use the same plain-language hierarchy for prospects, MLB dynasty players, and redraft players while preserving the detail appropriate to each surface.

## Design

### Shared reading contract

The existing card header remains the fastest answer and labels the headline number **ValuCast Value**. A short description identifies it as the fantasy decision number for the selected format; the underlying value and scale do not change.

Existing card sections adopt the same vocabulary:

- **Skill** introduces expected or projected performance. Prospect cards keep their percentile, translated-rate, skill-shape, and Statcast evidence. Redraft cards keep their trusted projection and category-rate evidence.
- **Opportunity** introduces projected PA/IP, role, level, and genuine availability information. A field renders only when the existing card payload provides it; the UI never infers a role or declares a player healthy from missing data.
- **ValuCast Value** introduces the league-fit read and category/value explanation.
- **Confidence** introduces the existing range, sample, calibration, and uncertainty context. It is not a new score.

The first occurrence of each concept uses a one-sentence layman's explanation. Deeper technical material remains available below it rather than being removed.

### Prospect and dynasty cards

`templates/partials/player_detail_dynasty.html` keeps all existing evidence and conditional rendering. The visible hierarchy changes are limited to:

- relabeling the headline `Dynasty Value` as `ValuCast Value`, with dynasty context retained beside it;
- relabeling the existing skill card as **Skill** and explaining that its bars describe performance, not fantasy value;
- relabeling the existing `Role & Read` block as **Opportunity**, using its current projected role, volume, roster context, and availability fields;
- relabeling `Confidence & Context` as **Confidence**, preserving all existing sample and calibration caveats;
- describing the outcome mix as a range of possible four-year paths. `Not established` remains explicitly defined and must never be presented as `Bust risk`.

No current percentile, Peak Outlook, scouting, rank-trend, Forward Ledger, or format-rank content is removed.

### Redraft cards

`templates/partials/player_detail.html` keeps the existing valuation and projection data. The visible hierarchy changes are limited to:

- relabeling the headline `Value` as `ValuCast Value` and stating that it is specific to the selected league settings;
- labeling the trusted projected rates as **Skill** and projected PA/IP as **Opportunity** within the existing projection section;
- relabeling the existing `League Fit` read as **ValuCast Value**, followed by the existing category math;
- explaining that missing role, availability, or confidence information is not rated on this card instead of manufacturing a label.

Actual-stat and Statcast sections remain supporting evidence and keep their current source distinctions.

### Presentation and accessibility

Reuse the existing card typography, section containers, and responsive layout. Add CSS only if the existing classes cannot express the hierarchy clearly. Any new explanatory text must wrap at 390px without horizontal overflow. Headings remain semantic, links and controls retain keyboard focus states, and percentile/probability graphics keep their current accessible labels.

## Data and Model Boundaries

- Display changes only: no new metric, data field, transformation, or dependency.
- Do not change ranks, values, replacement calculations, scarcity, pitcher caps, or publication decisions.
- Do not change model flags, Role Watch, share-graphic calculations, Forward Ledger claims, or League Connect.
- Preserve the model freeze and `PITCHER_STALE_PEDIGREE_DECAY_ENABLED = False`.
- Omit missing evidence; never substitute a neutral, healthy, available, or low-risk claim.

## Verification

Focused render tests cover prospect, MLB dynasty, and redraft cards. They must assert the four plain-language concepts, preserve the existing technical/source disclosures, omit unsupported opportunity claims, and reject the phrase `Bust risk`.

Then run the relevant card/share parity tests, the full automated suite when its runtime permits, and browser checks at 390x844 and desktop width. The browser pass must show no horizontal overflow, clipped headings, broken links or images, keyboard-focus regression, or console errors.

## Explicitly Deferred

- standalone glossary and glossary validators;
- Hitter Skill+ or Pitcher Skill+;
- new opportunity, confidence, or risk scores;
- share-graphic redesign;
- any ranking, model, or publication behavior.

Add these only when card-comprehension testing shows a remaining user problem that the inline hierarchy cannot solve.
