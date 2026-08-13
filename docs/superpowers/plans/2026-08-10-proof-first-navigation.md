# Proof-First Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Movers, Buys, and Receipts the stable first three navigation destinations, consolidate lower-frequency research routes behind one native disclosure, and remove the duplicate Backfields horizon tab.

**Architecture:** Restructure the existing server-rendered Jinja navigation only. Reuse the current hold flags and branded hold routes, use native `<details>` for the Research menu, and retain the existing aggregate route metrics for evaluation.

**Tech Stack:** Flask, Jinja2, HTML, CSS, vanilla JavaScript, pytest.

## Global Constraints

- Primary order is exactly `Movers`, `Buys`, `Receipts`, `Rankings`, `Farm Systems`, `Research`.
- Research contains exactly `Disagreements`, `The Ledger`, `Glossary`, `Archives`, `Map`, and `Methodology` in that order.
- Held Buys and Receipts links remain visible and clickable and lead to their existing branded hold pages.
- Do not change routes, route handlers, hold constants, prospect scoring, quality-governor policy, metrics schema, artifacts, or pipeline stages.
- Use native `<details>` and the existing disclosure-close pattern; add no dependency or navigation framework.
- Remove Backfields only from the board horizon selector, never the `/backfields` route or primary Farm Systems link.
- Preserve unrelated working-tree changes and stage files explicitly.

---

### Task 1: Lock the proof-first primary-navigation contract

**Files:**

- Modify: `tests/test_scouting_page.py:300-340`
- Modify: `tests/test_launch_polish.py:38-55`
- Modify: `templates/base.html:32-45`
- Modify: `static/style.css:195-225`
- Modify: `static/style.css:1170-1185`
- Modify: `templates/base.html:88-108`

**Interfaces:**

- Consumes: Flask template globals `request.path`, `aotc_hold`, and `receipts_hold`.
- Produces: `.site-nav`, `.site-nav-link`, `.site-nav-held`, `.site-nav-research`, and `.site-nav-research-menu` markup shared by every HTML page.

- [ ] **Step 1: Replace the broad primary-nav test with proof-first order, Research membership, and active-state assertions**

```python
def test_primary_nav_is_proof_first_and_groups_research_routes():
    client = app.test_client()
    html = client.get("/").data.decode("utf-8")
    site_nav = re.search(r'<nav class="site-nav".*?</nav>', html, re.S).group(0)

    positions = [
        site_nav.index(f'href="{path}"')
        for path in ("/movers", "/buys", "/receipts", "/", "/backfields")
    ]
    assert positions == sorted(positions)
    assert '<details class="site-nav-research">' in site_nav
    for marker in (
        'href="/gaps">Disagreements</a>',
        'href="/ledger">The Ledger</a>',
        'href="/glossary">Glossary</a>',
        'href="/board">Archives</a>',
        'href="/map">Map</a>',
        'href="/methodology">Methodology</a>',
    ):
        assert marker in site_nav
    assert 'href="/intelligence"' not in site_nav
    assert 'href="/scouting"' not in site_nav

    ledger_nav = re.search(
        r'<nav class="site-nav".*?</nav>',
        client.get("/ledger").data.decode("utf-8"),
        re.S,
    ).group(0)
    assert '<details class="site-nav-research has-current">' in ledger_nav
    assert 'href="/ledger" aria-current="page">The Ledger</a>' in ledger_nav
```

- [ ] **Step 2: Add the stable hold-anchor regression**

```python
def test_primary_nav_hold_flags_keep_honest_anchor_positions(monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module, "AHEAD_OF_THE_CURVE_HOLD", True)
    monkeypatch.setattr(app_module, "RECEIPTS_HOLD", True)
    html = app.test_client().get("/").data.decode("utf-8")
    site_nav = re.search(r'<nav class="site-nav".*?</nav>', html, re.S).group(0)

    for path, label in (("/buys", "Buys"), ("/receipts", "Receipts")):
        anchor = re.search(
            rf'<a href="{path}"[^>]*>.*?</a>', site_nav, re.S
        ).group(0)
        assert "is-held" in anchor
        assert f'aria-label="{label}, temporarily held"' in anchor
        assert '<span class="site-nav-held" aria-hidden="true">Held</span>' in anchor

    assert site_nav.index('href="/movers"') < site_nav.index('href="/buys"')
    assert site_nav.index('href="/buys"') < site_nav.index('href="/receipts"')
```

- [ ] **Step 3: Update the positioning regression to expect former flat links inside the Research disclosure**

Keep its label assertions, add `The Ledger` and `Glossary`, and assert that `Archives`, `Disagreements`, `Map`, and `Methodology` occur after `<summary>Research</summary>` rather than as direct-child pills.

- [ ] **Step 4: Run the new tests and confirm the current flat/gated navigation fails**

Run:

```powershell
python -m pytest -q tests/test_scouting_page.py::test_primary_nav_is_proof_first_and_groups_research_routes tests/test_scouting_page.py::test_primary_nav_hold_flags_keep_honest_anchor_positions tests/test_launch_polish.py::TestLaunchPolish::test_positioning_message_metadata_nav_board_and_footer_are_aligned
```

Expected: failures because the existing nav starts with Rankings, has no Research disclosure, and removes held anchors.

- [ ] **Step 5: Replace the primary-nav block in `templates/base.html`**

```jinja2
        {% set research_active = (
            request.path == '/gaps'
            or request.path == '/ledger'
            or request.path == '/glossary'
            or request.path == '/board'
            or request.path.startswith('/board/')
            or request.path == '/map'
            or request.path == '/methodology'
        ) %}
        <nav class="site-nav" aria-label="Primary navigation">
            <a href="/movers" class="site-nav-link"{% if request.path == '/movers' %} aria-current="page"{% endif %}>Movers</a>
            <a href="/buys" class="site-nav-link{% if aotc_hold %} is-held{% endif %}"{% if request.path == '/buys' %} aria-current="page"{% endif %}{% if aotc_hold %} aria-label="Buys, temporarily held"{% endif %}>Buys{% if aotc_hold %}<span class="site-nav-held" aria-hidden="true">Held</span>{% endif %}</a>
            <a href="/receipts" class="site-nav-link{% if receipts_hold %} is-held{% endif %}"{% if request.path == '/receipts' %} aria-current="page"{% endif %}{% if receipts_hold %} aria-label="Receipts, temporarily held"{% endif %}>Receipts{% if receipts_hold %}<span class="site-nav-held" aria-hidden="true">Held</span>{% endif %}</a>
            <a href="/" class="site-nav-link"{% if request.path == '/' %} aria-current="page"{% endif %}>Rankings</a>
            <a href="/backfields" class="site-nav-link"{% if backfields_page %} aria-current="page"{% endif %}>Farm Systems</a>
            <details class="site-nav-research{% if research_active %} has-current{% endif %}">
                <summary>Research</summary>
                <div class="site-nav-research-menu">
                    <a href="/gaps"{% if request.path == '/gaps' %} aria-current="page"{% endif %}>Disagreements</a>
                    <a href="/ledger"{% if request.path == '/ledger' %} aria-current="page"{% endif %}>The Ledger</a>
                    <a href="/glossary"{% if request.path == '/glossary' %} aria-current="page"{% endif %}>Glossary</a>
                    <a href="/board"{% if request.path == '/board' or request.path.startswith('/board/') %} aria-current="page"{% endif %}>Archives</a>
                    <a href="/map"{% if request.path == '/map' %} aria-current="page"{% endif %}>Map</a>
                    <a href="/methodology"{% if request.path == '/methodology' %} aria-current="page"{% endif %}>Methodology</a>
                </div>
            </details>
        </nav>
```

- [ ] **Step 6: Generalize the existing disclosure-close selectors**

In both the outside-click and Escape handlers, replace:

```javascript
details.graphic-menu[open]
```

with:

```javascript
details.graphic-menu[open], details.site-nav-research[open]
```

- [ ] **Step 7: Replace the primary pill selectors and add Research/hold styles**

```css
.site-nav > a,
.site-nav-research > summary {
    border: 1px solid rgba(255, 255, 255, .10);
    border-radius: 999px;
    background: rgba(255, 255, 255, .045);
    color: var(--c-text);
    cursor: pointer;
    font-size: .76rem;
    font-weight: 600;
    letter-spacing: .02em;
    line-height: 1.5;
    list-style: none;
    padding: .34rem .58rem;
    text-decoration: none;
}
.site-nav-research { position: relative; }
.site-nav-research > summary::-webkit-details-marker { display: none; }
.site-nav-research > summary::after { content: " \25BE"; color: var(--c-muted); }
.site-nav > a:hover,
.site-nav-research > summary:hover { border-color: rgba(52, 226, 196, .38); color: var(--c-prospect); text-decoration: none; }
.site-nav > a:focus-visible,
.site-nav-research > summary:focus-visible { outline: 2px solid var(--c-blue-strong); outline-offset: 2px; }
.site-nav > a[aria-current="page"],
.site-nav-research.has-current > summary { border-color: rgba(52, 226, 196, .4); background: rgba(52, 226, 196, .12); color: var(--c-prospect); }
.site-nav-held { margin-left: .28rem; color: var(--c-amber); font-size: .56rem; letter-spacing: .05em; text-transform: uppercase; }
.site-nav > a.is-held { border-color: rgba(251, 191, 36, .35); }
.site-nav-research-menu {
    position: absolute;
    right: 0;
    top: calc(100% + .4rem);
    z-index: 500;
    display: grid;
    min-width: 190px;
    overflow: hidden;
    border: 1px solid var(--c-border-strong);
    border-radius: var(--radius);
    background: var(--surface-panel-strong);
    box-shadow: var(--shadow-soft);
}
.site-nav-research-menu a { padding: .55rem .7rem; color: var(--c-text); text-decoration: none; }
.site-nav-research-menu a:hover,
.site-nav-research-menu a:focus-visible,
.site-nav-research-menu a[aria-current="page"] { background: var(--surface-2); color: var(--c-prospect); text-decoration: none; }
.site-nav-research-menu a:focus-visible { outline: 2px solid var(--c-blue-strong); outline-offset: -2px; }
```

At the existing `max-width: 640px` site-nav rules, replace `.site-nav a` with `.site-nav > a, .site-nav-research > summary`, set `.site-header { position: relative; }`, set `.site-nav-research { position: static; }`, and set the menu to `left: 1rem; right: 1rem; top: calc(100% - .25rem); grid-template-columns: repeat(2, minmax(0, 1fr)); min-width: 0;`.

- [ ] **Step 8: Run the focused navigation tests**

Run:

```powershell
python -m pytest -q tests/test_scouting_page.py tests/test_launch_polish.py
```

Expected: all selected tests pass after reconciling only assertions that encode the old flat order.

- [ ] **Step 9: Commit the proof-first header**

```powershell
git add -- templates/base.html static/style.css tests/test_scouting_page.py tests/test_launch_polish.py
git commit -m "feat: make navigation proof first"
```

### Task 2: Keep hold pages protected while anchors remain stable

**Files:**

- Modify: `tests/test_call_up_receipts.py:10-25`
- Modify: `tests/test_buy_score.py:417-445`
- Modify: `tests/test_app.py:3475-3500`

**Interfaces:**

- Consumes: the Task 1 `.site-nav` held-anchor contract and the existing hold-page route behavior.
- Produces: regressions that distinguish stable header discovery from hidden contextual modules and protected share endpoints.

- [ ] **Step 1: Update the Receipts hold test to scope its assertions**

```python
    nav = re.search(r'<nav class="site-nav".*?</nav>', page, re.S).group(0)
    main = page[page.index("<main>"):page.index("</main>")]
    assert re.search(r'href="/receipts"[^>]*is-held', nav)
    assert '<span class="site-nav-held" aria-hidden="true">Held</span>' in nav
    assert 'href="/receipts"' not in main
```

Keep the existing assertions that the hold copy renders and both share-card routes return `404`.

- [ ] **Step 2: Update the Buys hold test to distinguish the stable header from the hidden Backfields module**

```python
        map_nav = re.search(r'<nav class="site-nav".*?</nav>', map_html, re.S).group(0)
        backfields_main = backfields_html[
            backfields_html.index("<main>"):backfields_html.index("</main>")
        ]
        self.assertRegex(map_nav, r'href="/buys"[^>]*is-held')
        self.assertNotIn('href="/buys"', backfields_main)
```

Keep the existing assertions that the Backfields buy-board section and full-board link are absent.

- [ ] **Step 3: Update the Models/Methodology Receipts test to inspect main content rather than the global header**

```python
        models_main = models_body[models_body.index("<main>"):models_body.index("</main>")]
        methodology_main = methodology_body[
            methodology_body.index("<main>"):methodology_body.index("</main>")
        ]
        self.assertNotIn('href="/receipts"', models_main)
        self.assertNotIn('href="/receipts"', methodology_main)
        self.assertRegex(models_body, r'href="/receipts"[^>]*is-held')
```

- [ ] **Step 4: Run the hold-focused tests**

Run:

```powershell
python -m pytest -q tests/test_call_up_receipts.py::test_receipts_page_shows_hold_message_and_hides_share_card_when_held tests/test_buy_score.py::TestBuysRoute::test_aotc_hold_hides_public_navigation_and_backfields_surface tests/test_app.py::TestModelsRegistryPage::test_receipts_link_hidden_on_models_and_methodology_when_held
```

Expected: all three selected tests pass.

- [ ] **Step 5: Commit the hold-contract regression updates**

```powershell
git add -- tests/test_call_up_receipts.py tests/test_buy_score.py tests/test_app.py
git commit -m "test: keep held proof anchors discoverable"
```

### Task 3: Remove the duplicate Backfields horizon destination

**Files:**

- Modify: `templates/partials/_board_nav.html:1-13`
- Modify: `tests/test_ui_tabs.py:21-35`
- Modify: `tests/test_backfields_page.py:90-102`
- Modify: `tests/test_consensus_gap.py:195-200`

**Interfaces:**

- Consumes: the primary `/backfields` Farm Systems anchor from Task 1.
- Produces: a board horizon selector containing only Redraft, Dynasty, and Prospects.

- [ ] **Step 1: Change the horizon regression to reject Backfields inside the scoped horizon nav**

```python
    def test_horizon_tabs_are_links(self):
        html = self.client.get("/").data.decode("utf-8")
        horizon_nav = re.search(
            r'<nav class="horizon-tabs"[^>]*>(.*?)</nav>', html, re.S
        ).group(1)
        self.assertIn('href="/?mode=dd_dynasty"', horizon_nav)
        self.assertIn('href="/?mode=prospects"', horizon_nav)
        self.assertNotIn('href="/backfields"', horizon_nav)
        self.assertIn('class="horizon-tabs"', html)
        self.assertIn('aria-current="page"', horizon_nav)
```

- [ ] **Step 2: Run the horizon regression and confirm it fails on the duplicate destination**

Run:

```powershell
python -m pytest -q tests/test_ui_tabs.py::TestTabMarkup::test_horizon_tabs_are_links
```

Expected: fail because `/backfields` is still inside `.horizon-tabs`.

- [ ] **Step 3: Remove the Backfields anchor from `_board_nav.html` and correct the comment**

```jinja2
{% macro board_nav(active='', dd_available=true, aria='Board navigation') %}
{# Horizon switch ONLY: destination pages live in the primary nav and footer. #}
<nav class="horizon-tabs" aria-label="{{ aria }}">
    <a href="/" class="htab{% if active == 'redraft' %} on{% endif %}"{% if active == 'redraft' %} aria-current="page"{% endif %}>Redraft</a>
    {% if dd_available is not false %}
    <a href="/?mode=dd_dynasty" class="htab htab-dynasty{% if active == 'dynasty' %} on{% endif %}"{% if active == 'dynasty' %} aria-current="page"{% endif %}>Dynasty</a>
    <a href="/?mode=prospects" class="htab{% if active == 'prospects' %} on{% endif %}"{% if active == 'prospects' %} aria-current="page"{% endif %}>Prospects</a>
    {% endif %}
</nav>
<p class="prov-line">Deterministic &middot; committed daily &middot; {% if active == 'ledger' %}publicly scored{% else %}<a href="/ledger">publicly scored</a>{% endif %} &middot; free, no login</p>
{% endmacro %}
```

- [ ] **Step 4: Reconcile tests that encoded Backfields as a horizon neighbor**

Keep assertions that the primary site nav links `/backfields`, but remove assertions requiring `class="htab htab-prospects"`. Update the consensus-gap comment to say the horizon carries only Redraft/Dynasty/Prospects.

- [ ] **Step 5: Run the scoped horizon and prospect-hub tests**

Run:

```powershell
python -m pytest -q tests/test_ui_tabs.py tests/test_backfields_page.py tests/test_consensus_gap.py
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit the horizon cleanup**

```powershell
git add -- templates/partials/_board_nav.html tests/test_ui_tabs.py tests/test_backfields_page.py tests/test_consensus_gap.py
git commit -m "refactor: keep board navigation to horizons"
```

### Task 4: Verify layout, metrics boundary, and repository health

**Files:**

- Verify only: `templates/base.html`
- Verify only: `templates/partials/_board_nav.html`
- Verify only: `static/style.css`
- Verify only: `web/site_metrics.py`

**Interfaces:**

- Consumes: the completed server-rendered navigation and unchanged `/metrics/summary` endpoint.
- Produces: automated, browser, and diff evidence suitable for adversarial review.

- [ ] **Step 1: Run the complete navigation/hold regression set**

```powershell
python -m pytest -q tests/test_ui_tabs.py tests/test_launch_polish.py tests/test_scouting_page.py tests/test_backfields_page.py tests/test_buy_score.py tests/test_call_up_receipts.py tests/test_app.py tests/test_consensus_gap.py
```

Expected: all selected tests pass.

- [ ] **Step 2: Run the existing Movers/governor/snapshot regression set**

```powershell
python -m pytest -q tests/test_public_dynasty_snapshot.py tests/test_valucast_quality_governor.py tests/test_movers.py
```

Expected: all selected tests pass, including `test_build_snapshot_forwards_movers_to_governor`.

- [ ] **Step 3: Browser-check the proof-first header**

Start the local Flask app without changing committed artifacts. At desktop and a 390px viewport, verify:

- the first three links are Movers, Buys, Receipts;
- Research opens by click and keyboard;
- Escape and outside click close it;
- every Research link is reachable;
- no horizontal overflow appears;
- held-state markup remains readable when both flags are temporarily patched in a test process.

- [ ] **Step 4: Confirm metrics code is unchanged and record the baseline source**

```powershell
git diff -- web/site_metrics.py
```

Expected: no output. Confirm `https://valucast.app/metrics/summary?days=7` remains the post-deploy comparison source.

- [ ] **Step 5: Run repository-wide pytest**

```powershell
python -m pytest -q
```

Expected: all tests pass. If `test_combined_level_shadow_excludes_prior_year_served_model_lines` alone fails because the live board contains zero stale served lines, report that independently reproduced data-dependent fixture failure; do not weaken its production gate inside this navigation plan.

- [ ] **Step 6: Audit the final scope**

```powershell
git diff --check
git status --short
git log -5 --oneline
```

Confirm no data artifact, route handler, metric schema, prospect score, governor threshold, or hold constant changed.

- [ ] **Step 7: Commit any remaining verified plan/test bookkeeping explicitly**

```powershell
git add -- docs/superpowers/plans/2026-08-10-proof-first-navigation.md
git commit -m "docs: plan proof-first navigation"
```
