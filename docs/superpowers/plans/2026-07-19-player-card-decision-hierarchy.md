# Player Card Decision Hierarchy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make prospect, MLB dynasty, and redraft player cards explain Skill, Opportunity, ValuCast Value, and Confidence in plain language without changing any calculation.

**Architecture:** Reuse the two existing Jinja player-detail templates and their current data. Add one compact reading guide to each template, then relabel the existing evidence sections so readers can connect the guide to the details below. No Python, data-contract, model, or CSS changes are required.

**Tech Stack:** Flask, Jinja, Python `unittest`/pytest.

## Global Constraints

- Display changes only: no new metric, data field, transformation, or dependency.
- Do not change ranks, values, replacement calculations, scarcity, pitcher caps, or publication decisions.
- Do not change model flags, Role Watch, share-graphic calculations, Forward Ledger claims, or League Connect.
- Preserve the model freeze and `PITCHER_STALE_PEDIGREE_DECAY_ENABLED = False`.
- Omit missing evidence; never substitute a neutral, healthy, available, or low-risk claim.
- Keep `Bust risk` absent from public cards.

---

### Task 1: Add the shared card-reading contract

**Files:**
- Modify: `tests/test_app.py`
- Modify: `templates/partials/player_detail_dynasty.html`
- Modify: `templates/partials/player_detail.html`

**Interfaces:**
- Consumes: existing Flask `/player/<id>` responses and the current `row`, `player`, and `result` template payloads.
- Produces: visible `Skill`, `Opportunity`, `ValuCast Value`, and `Confidence` language on all three player-card types.

- [ ] **Step 1: Write the failing render-contract tests**

Add this class near the existing player-detail tests in `tests/test_app.py`:

```python
class TestPlayerCardDecisionHierarchy(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def assert_decision_hierarchy(self, body):
        self.assertIn('aria-label="How to read this card"', body)
        self.assertIn("Skill", body)
        self.assertIn("Opportunity", body)
        self.assertIn("ValuCast Value", body)
        self.assertIn("Confidence", body)
        self.assertIn("if it is absent, ValuCast has not rated it", body)
        self.assertNotIn("Bust risk", body)

    def test_prospect_card_explains_the_decision_hierarchy(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        row = next((r for r in dd_store.get_all() if r.is_prospect), None)
        if row is None:
            self.skipTest("No prospect rows available")
        response = self.client.get(
            f"/player/{row.id}?mode=prospects",
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 200)
        self.assert_decision_hierarchy(response.data.decode())

    def test_mlb_dynasty_card_explains_the_decision_hierarchy(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        row = next((r for r in dd_store.get_all() if not r.is_prospect), None)
        if row is None:
            self.skipTest("No MLB dynasty rows available")
        response = self.client.get(
            f"/player/{row.id}?mode=dd_dynasty",
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 200)
        self.assert_decision_hierarchy(response.data.decode())

    def test_redraft_card_explains_the_decision_hierarchy(self):
        response = self.client.get(
            "/player/19755?mode=categories",
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 200)
        self.assert_decision_hierarchy(response.data.decode())
```

- [ ] **Step 2: Run the tests and verify the missing guide fails**

Run:

```powershell
python -m pytest tests/test_app.py::TestPlayerCardDecisionHierarchy -q
```

Expected: three failures because `aria-label="How to read this card"` is absent.

- [ ] **Step 3: Add the minimal guide and consistent labels**

In both templates, immediately inside `.detail-body`, add:

```html
<div class="detail-section card-reading-guide" aria-label="How to read this card">
    <p><strong>Skill</strong> is what the performance evidence supports. <strong>Opportunity</strong> is projected playing time, role, and availability. <strong>ValuCast Value</strong> turns both into the fantasy decision for this format. <strong>Confidence</strong> shows how stable that read is; if it is absent, ValuCast has not rated it.</p>
</div>
```

In `templates/partials/player_detail_dynasty.html`:

```html
<span class="headline-value"><span>ValuCast Value <a href="/methodology#dynasty-value-scale" class="value-explainer-link" title="How does this dynasty 0-100 value work?">(?)</a></span>{{ "%.1f" | format(row.dynasty_value) }}</span>
```

Change the existing skill-card kicker and heading to:

```html
<span class="profile-card-kicker">Skill</span>
<h4>What his performance supports</h4>
```

Change the existing scouting-context kicker and heading to:

```html
<span class="profile-card-kicker">Opportunity</span>
<h4>Role, playing time &amp; availability</h4>
```

Change the existing context heading to:

```html
<h4>Confidence</h4>
```

In `templates/partials/player_detail.html`, change the headline to:

```html
ValuCast Value: {{ "%.2f" | format(result.total_value) }}
```

Change the league-read kicker and heading to:

```html
<span class="profile-card-kicker">ValuCast Value</span>
<h4>What this means in your league</h4>
```

Change the season-outlook heading and add its explanation:

```html
<span class="profile-card-kicker">Skill</span>
<h4>Projected performance</h4>
<p class="profile-note"><strong>Opportunity:</strong> PA/IP show projected playing time. Role and availability appear only when supported.</p>
```

- [ ] **Step 4: Run the focused tests and verify they pass**

Run:

```powershell
python -m pytest tests/test_app.py::TestPlayerCardDecisionHierarchy tests/test_app.py::TestAttributionPanel tests/test_app.py::TestDynastyMode::test_redraft_unaffected -q
```

Expected: all selected tests pass and none skips when the checked-in DD feed is available.

- [ ] **Step 5: Run the adjacent share/card contracts**

Run:

```powershell
python -m pytest tests/test_redraft_player_card.py tests/test_consensus_gap_card.py tests/test_app.py::TestDynastyMode::test_prospect_detail_links_player_share_graphic tests/test_app.py::TestPlayerCardDecisionHierarchy -q
```

Expected: all selected tests pass; share rendering remains unchanged.

- [ ] **Step 6: Commit the implementation**

```powershell
git add tests/test_app.py templates/partials/player_detail_dynasty.html templates/partials/player_detail.html
git commit -m "feat: explain player card decision hierarchy"
```

---

### Task 2: Verify the rendered cards

**Files:**
- Verify only: no planned source changes.

**Interfaces:**
- Consumes: the player-detail routes after Task 1.
- Produces: mobile and desktop evidence that the hierarchy remains readable and accessible.

- [ ] **Step 1: Start the local Flask app**

Run:

```powershell
python app.py
```

Expected: the local server starts without an exception.

- [ ] **Step 2: Check mobile prospect, dynasty, and redraft cards**

At a 390x844 viewport, open one card of each type and confirm:

- the reading guide appears directly below the header;
- all four concepts are readable without horizontal scrolling;
- no heading, value, button, image, or table is clipped;
- no console error appears;
- keyboard focus remains visible on the share and methodology links.

- [ ] **Step 3: Check desktop cards**

At 1440px width, repeat the three card checks and confirm the guide does not create an empty or oversized panel.

- [ ] **Step 4: Run final automated verification**

Run:

```powershell
python -m pytest tests/test_app.py::TestPlayerCardDecisionHierarchy tests/test_app.py::TestAttributionPanel tests/test_redraft_player_card.py tests/test_consensus_gap_card.py -q
git diff --check
git status --short --branch
```

Expected: all selected tests pass, `git diff --check` exits 0, and the worktree has no uncommitted files.
