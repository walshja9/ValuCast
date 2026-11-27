# Prospect Evidence Honesty Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove unsupported prospect probabilities and generic risk language from public card surfaces while retaining qualitative ceiling, floor, evidence strength, and timing context.

**Architecture:** Keep every underlying artifact and public row property intact for research. Gate the unsupported material only at the existing Jinja template and public scouting-display adapter, then align the two existing design contracts with that behavior.

**Tech Stack:** Python 3, Flask, Jinja2, Pillow, unittest/pytest.

## Global Constraints

- Preserve the model freeze and failed pitcher-decay flag.
- Do not change universal, dynasty, Peak, rank, value, Role Watch, pitcher cap, League Connect, or publication logic.
- Do not change generated model or public data artifacts.
- Add no dependency, helper layer, CSS, or JavaScript.
- Do not dispatch workflows, deploy, merge, or push.

---

### Task 1: Make the prospect HTML card honest

**Files:**
- Modify: `tests/test_app.py:142-221,2570-2605`
- Modify: `templates/partials/player_detail_dynasty.html:74-105,379-411`

**Interfaces:**
- Consumes: existing `DynastyRankingRow` attribution, Peak role, floor, confidence, and ETA properties.
- Produces: public HTML with no outcome distribution, Peak score, delta, generic risk, trajectory, probability bars, or heuristic card copy.

- [x] **Step 1: Write the failing render assertions**

Update the prospect hierarchy test to select a prospect with Peak context and assert the approved behavior:

```python
row = next(
    (r for r in dd_store.get_all() if r.is_prospect and r.has_peak_projection),
    None,
)
# existing response/status assertions remain
self.assertNotIn("Four-year MLB outlook.", body)
self.assertNotIn("attribution-mix", body)
self.assertIn("<b>Ceiling scenario</b>", body)
self.assertIn("<b>Floor scenario</b>", body)
self.assertIn("<b>Evidence strength</b>", body)
self.assertIn("<b>Window</b>", body)
self.assertNotIn("<b>Peak</b>", body)
self.assertNotIn("<b>Upside</b>", body)
self.assertNotIn("<b>Risk</b>", body)
self.assertNotIn("peak-trajectory-note", body)
for item in row.peak_role_probability_items:
    self.assertNotIn(f"<span>{item['label']}</span>", body)
```

Change the attribution-panel render test to require live grade context without the shadow outcome mix:

```python
self.assertIn("How ValuCast graded him", body)
self.assertNotIn("attribution-mix", body)
self.assertNotIn("Four-year MLB outlook", body)
self.assertNotIn("not a career verdict", body)
```

- [x] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_app.py::TestPlayerCardDecisionHierarchy::test_prospect_card_explains_the_decision_hierarchy tests/test_app.py::TestAttributionPanel::test_panel_renders_high_on_prospect_card -q
```

Expected: both tests fail because the current template still renders the outcome mix and quantitative Peak fields.

- [x] **Step 3: Apply the minimal template deletion**

In the attribution panel:

```jinja2
{% if row.is_prospect and (row.why_rank_chips or row.attribution_components or row.uncertainty_note) %}
```

Delete the complete `{% if row.outcome_mix %}` block. Keep the existing drivers, attribution effects, and uncertainty content unchanged.

Replace the Peak summary strip with:

```jinja2
<div class="peak-summary-strip">
    {% if row.peak_role_label %}<span><b>Ceiling scenario</b>{{ row.peak_role_label }}</span>{% endif %}
    {% if row.peak_floor_label %}<span><b>Floor scenario</b>{{ row.peak_floor_label }}</span>{% endif %}
    {% if row.peak_confidence_label %}<span><b>Evidence strength</b>{{ row.peak_confidence_label }}</span>{% endif %}
    {% if row.peak_eta_label %}<span><b>Window</b>{{ row.peak_eta_label }}</span>{% endif %}
</div>
```

Change the note to literal honest copy and delete the trajectory, role-probability, and `peak_projection_card_copy` blocks:

```jinja2
<p class="profile-note peak-projection-note">Qualitative ceiling and floor scenarios &mdash; separate from today's value.</p>
```

- [x] **Step 4: Run the focused tests and verify GREEN**

Run the command from Step 2.

Expected: `2 passed`.

- [x] **Step 5: Commit the HTML correction**

```powershell
git add -- tests/test_app.py templates/partials/player_detail_dynasty.html
git commit -m "fix: remove unsupported prospect probabilities"
```

### Task 2: Stop stale Peak-risk copy at the public adapter

**Files:**
- Modify: `tests/test_app.py:142-221`
- Modify: `app.py:5610-5622`

**Interfaces:**
- Consumes: `_scouting_display_report(report: dict | None) -> dict | None`.
- Produces: the same public scouting report mapping without `peak_summary`; committed artifacts remain unchanged.

- [x] **Step 1: Write the failing adapter test**

Add to `TestPlayerCardDecisionHierarchy`:

```python
def test_public_scouting_adapter_hides_uncalibrated_peak_summary(self):
    public = app_module._scouting_display_report({
        "report": "Observed performance read.",
        "peak_summary": "Projection: starter with low risk.",
    })

    self.assertEqual(public["display_report"], "Observed performance read.")
    self.assertNotIn("peak_summary", public)
```

- [x] **Step 2: Run the adapter test and verify RED**

Run:

```powershell
python -m pytest tests/test_app.py::TestPlayerCardDecisionHierarchy::test_public_scouting_adapter_hides_uncalibrated_peak_summary -q
```

Expected: FAIL because `peak_summary` is still present.

- [x] **Step 3: Apply the one-line public guard**

In `_scouting_display_report`, after copying the artifact row:

```python
item = dict(report)
item.pop("peak_summary", None)
```

This existing adapter feeds player HTML, share PNG context, and the scouting route. Do not edit the generated scouting artifact or Pillow renderer.

- [x] **Step 4: Run the adapter and PNG checks**

Run:

```powershell
python -m pytest tests/test_app.py::TestPlayerCardDecisionHierarchy::test_public_scouting_adapter_hides_uncalibrated_peak_summary tests/test_app.py::TestDynastyMode::test_prospect_player_card_preview_and_png -q
```

Expected: `2 passed`.

- [x] **Step 5: Commit the adapter guard**

```powershell
git add -- tests/test_app.py app.py
git commit -m "fix: suppress heuristic peak risk copy"
```

### Task 3: Align the existing design contracts and verify

**Files:**
- Modify: `docs/superpowers/specs/2026-07-18-prospect-player-share-parity-design.md`
- Modify: `docs/superpowers/specs/2026-07-19-player-card-decision-hierarchy-design.md`

**Interfaces:**
- Consumes: the approved `2026-07-19-prospect-evidence-honesty-design.md` behavior.
- Produces: no contradictory requirement to restore outcome percentages or heuristic Peak fields.

- [x] **Step 1: Amend the conflicting requirements**

In both older specs:

- mark the outcome-mix and quantitative Peak requirements as superseded by the evidence-honesty design;
- require live grade drivers instead of `row.outcome_mix`;
- require only qualitative ceiling, floor, evidence strength, and window;
- remove tests requiring outcome percentages, Peak score, delta, generic risk, or role probabilities on HTML/PNG.

- [x] **Step 2: Check the contract and diff**

Run:

```powershell
rg -n "exact `row.outcome_mix`|complete Peak Outlook|role probabilities match|No current percentile, Peak Outlook" docs/superpowers/specs/2026-07-18-prospect-player-share-parity-design.md docs/superpowers/specs/2026-07-19-player-card-decision-hierarchy-design.md
git diff --check
```

Expected: `rg` finds no contradictory requirement; `git diff --check` exits 0.

- [x] **Step 3: Run automated verification**

Run focused coverage:

```powershell
python -m pytest tests/test_app.py::TestPlayerCardDecisionHierarchy tests/test_app.py::TestAttributionPanel tests/test_app.py::TestDynastyMode -q
```

Then run the full suite:

```powershell
python -m pytest -q
```

Expected: all tests pass.

- [x] **Step 4: Verify artifact and model boundaries**

Run:

```powershell
git status --short
git diff --name-only origin/master...HEAD -- data/models data/public data/prediction_archive prospects
```

Expected: only intended source, test, and documentation files are pending; no model or generated data path appears.

- [x] **Step 5: Commit the contract correction**

```powershell
git add -- docs/superpowers/specs/2026-07-18-prospect-player-share-parity-design.md docs/superpowers/specs/2026-07-19-player-card-decision-hierarchy-design.md
git commit -m "docs: align prospect card evidence contracts"
```

Do not push, deploy, merge, or dispatch a workflow.

---

### Task 4: Keep heuristic Peak claims out of prospect narratives

**Files:**
- Modify: `app.py`
- Modify: `scouting/repository.py`
- Modify: `scouting/voice.py`
- Modify: `tests/test_scouting_page.py`
- Modify: `tests/test_scouting_v2.py`

- [x] Add a prospect-only public fallback for cached reads that state role
  probabilities, generic risk bands, likely outcomes, settled role forecasts,
  or any prospect projection language. MLB rate-projection prose remains scoped
  out; prospect MLB-equivalent rates use `translates to` language.
- [x] Report the fallback source honestly as deterministic.
- [x] Route `/scouting` through the same adapter so it cannot leak Peak risk copy
  or mislabel a rejected generated read.
- [x] Reframe the three deterministic `likely outcome` / `profiles as` templates
  as explicit current-performance ceiling scenarios.
- [x] Restrict future LLM grounding to qualitative ceiling, floor, evidence
  strength, and window context.
- [x] Add a hard generation guard against uncalibrated outcome claims without
  blocking supported MLB rate-projection language.
- [x] Audit the committed repository: 209 of 356 generated prospect reads require
  the deterministic fallback; 147 remain generated reads, with zero guarded
  claims served. Seven legacy deterministic reads are relabeled as explicit
  current-performance ceiling scenarios.
