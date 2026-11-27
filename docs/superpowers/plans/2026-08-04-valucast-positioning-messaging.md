# ValuCast Positioning and Messaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Present ValuCast consistently as independent prospect intelligence translated into league-aware dynasty decisions.

**Architecture:** Reuse the existing Jinja templates, flat navigation, shared footer, and `_graphic_header` renderer. Add one compact static strip to the existing homepage flow, update copy contracts in place, and make the share renderer's default prospect positioning explicit while preserving named product taglines.

**Tech Stack:** Python 3.14, Flask/Jinja, Pillow, CSS, pytest/unittest.

## Global Constraints

- Primary positioning: **Independent prospect intelligence, translated for your dynasty league.**
- Product order: Evaluate, Translate, Act, Prove.
- Keep the board immediately accessible; no splash screen, CTA, animation, or JavaScript.
- Keep all routes, URL paths, navigation order, hold gates, saved settings, install behavior, source disclosures, and accessibility semantics.
- Do not change scoring, rankings, values, models, caps, Role Watch, publication, data artifacts, workflows, or analytics events.
- Keep “Ahead of the Curve” as the Buys product name and “The Second Opinion” as the trade product name.
- Do not name competitors or make superiority claims.
- Add no dependency or reusable abstraction.
- Approved design: `docs/superpowers/specs/2026-08-04-valucast-positioning-messaging-design.md`.

---

### Task 1: Align homepage, metadata, navigation, board, and footer copy

**Files:**
- Modify: `templates/base.html:8-46`
- Modify: `templates/index.html:5-30,166`
- Modify: `templates/partials/_footer_provenance.html:1-28`
- Modify: `static/style.css:274-287`
- Modify: `tests/test_launch_polish.py`
- Modify: `tests/test_scouting_page.py:296-324`
- Modify: `tests/test_backfields_page.py:76-90`
- Modify: `tests/test_app.py:3798-3814`

**Interfaces:**
- Consumes: Existing Flask `app.test_client()`, Jinja blocks, `request.path`, and hold flags.
- Produces: Static `.positioning-strip` markup, revised default metadata, four revised primary-nav labels, revised prospect summary, and one shared footer positioning sentence.

- [ ] **Step 1: Rebase the isolated branch onto current master**

```powershell
git fetch origin
git rebase origin/master
git status --short --branch
```

Expected: branch is clean except for the already committed design and plan documents; the main checkout is never touched.

- [ ] **Step 2: Add the failing page-positioning contract test**

Add this method to `TestLaunchPolish` in `tests/test_launch_polish.py`:

```python
def test_positioning_message_metadata_nav_board_and_footer_are_aligned(self):
    html = self.html("/?mode=prospects")

    self.assertIn(
        "<title>ValuCast | Independent Prospect Intelligence for Dynasty Baseball</title>",
        html,
    )
    description = (
        "Independent prospect evaluation for league-aware dynasty rankings, "
        "values, trades, buys and call-up decisions, with public methodology "
        "and receipts."
    )
    self.assertIn(f'<meta name="description" content="{description}">', html)
    self.assertIn(f'<meta property="og:description" content="{description}">', html)
    self.assertIn(f'<meta name="twitter:description" content="{description}">', html)

    self.assertIn('class="positioning-strip"', html)
    self.assertIn(
        "Independent prospect intelligence, translated for your dynasty league.",
        html,
    )
    self.assertIn(
        "ValuCast evaluates players independently, then turns that evidence into "
        "league-aware rankings, values, trades, buys, and call-up decisions.",
        html,
    )

    nav = re.search(r'<nav class="site-nav".*?</nav>', html, re.S).group(0)
    for marker in (
        'href="/" aria-current="page">Rankings</a>',
        'href="/board">Archives</a>',
        'href="/gaps">Disagreements</a>',
        'href="/backfields">Farm Systems</a>',
    ):
        self.assertIn(marker, nav)
    for old_label in (">Board</a>", ">The Archives</a>", ">Gaps</a>", ">Backfields</a>"):
        self.assertNotIn(old_label, nav)

    self.assertIn(
        "Independent prospect evaluation, league-aware value, current evidence, "
        "and actionable signals.",
        html,
    )
    self.assertIn(
        "ValuCast independently evaluates prospects, translates that evidence "
        "into league-specific fantasy decisions, and publishes the methodology "
        "and receipts.",
        html,
    )

    css = self.html("/static/style.css")
    self.assertIn(".positioning-strip {", css)
    self.assertNotIn("min-height:", css[css.index(".positioning-strip {"):css.index(".welcome-strip {")])
```

`re` is already imported at the top of this test module.

- [ ] **Step 3: Run the new test and verify it fails**

```powershell
python -m pytest tests/test_launch_polish.py::TestLaunchPolish::test_positioning_message_metadata_nav_board_and_footer_are_aligned -q
```

Expected: FAIL because the new headline and metadata are absent.

- [ ] **Step 4: Update the default metadata and four primary-nav labels**

Replace the default metadata in `templates/base.html` with:

```html
<title>{% block title %}ValuCast | Independent Prospect Intelligence for Dynasty Baseball{% endblock %}</title>
<meta name="description" content="Independent prospect evaluation for league-aware dynasty rankings, values, trades, buys and call-up decisions, with public methodology and receipts.">
<meta property="og:type" content="website">
<meta property="og:site_name" content="ValuCast">
<meta property="og:title" content="{% block og_title %}ValuCast | Independent Prospect Intelligence for Dynasty Baseball{% endblock %}">
<meta property="og:description" content="{% block og_description %}Independent prospect evaluation for league-aware dynasty rankings, values, trades, buys and call-up decisions, with public methodology and receipts.{% endblock %}">
```

Use the same title and description in the existing `twitter:title` and `twitter:description` blocks. Leave route-specific block overrides untouched.

Change only these anchor labels in the existing `site-nav` block:

```html
<a href="/"{% if request.path == '/' %} aria-current="page"{% endif %}>Rankings</a>
<a href="/board"{% if request.path == '/board' or request.path.startswith('/board/') %} aria-current="page"{% endif %}>Archives</a>
<a href="/gaps"{% if request.path == '/gaps' %} aria-current="page"{% endif %}>Disagreements</a>
<a href="/backfields"{% if backfields_page %} aria-current="page"{% endif %}>Farm Systems</a>
```

- [ ] **Step 5: Add the compact homepage strip and prospect-board summary**

In `templates/index.html`, insert this immediately before `{{ board_nav(...) }}`:

```html
<section class="positioning-strip" aria-labelledby="positioning-title">
    <h2 id="positioning-title">Independent prospect intelligence, translated for your dynasty league.</h2>
    <p>ValuCast evaluates players independently, then turns that evidence into league-aware rankings, values, trades, buys, and call-up decisions.</p>
</section>
```

Replace the prospect-board `config-summary` sentence with:

```html
<span class="config-summary">Independent prospect evaluation, league-aware value, current evidence, and actionable signals.{% if dd_generated_at %} - Updated {{ editorial_date(dd_generated_at) }}{% endif %}</span>
```

- [ ] **Step 6: Add minimal static styling**

Add this immediately before `.welcome-strip` in `static/style.css`:

```css
.positioning-strip {
    margin: 0 0 var(--space-2);
    padding: .1rem;
}
.positioning-strip h2 {
    margin: 0;
    color: var(--c-text);
    font-size: clamp(.95rem, 2vw, 1.15rem);
    line-height: 1.25;
}
.positioning-strip p {
    margin: .2rem 0 0;
    color: var(--c-muted);
    font-size: .78rem;
    line-height: 1.4;
}
```

No mobile override is needed: this is normal-flow text with fluid type and native wrapping.

- [ ] **Step 7: Lead the existing footer explanation with the approved sentence**

At the start of the existing `.footer-how` paragraph in `templates/partials/_footer_provenance.html`, add:

```html
<span class="footer-positioning">ValuCast independently evaluates prospects, translates that evidence into league-specific fantasy decisions, and publishes the methodology and receipts.</span><br>
```

Do not change any conditional source, freshness, or link text below it.

- [ ] **Step 8: Update existing navigation expectations without renaming route content**

Make these assertion-only changes:

```python
# tests/test_scouting_page.py
assert 'href="/" aria-current="page">Rankings</a>' in html
assert 'href="/backfields"' in html and ">Farm Systems</a>" in html
assert 'href="/gaps">Disagreements</a>' in html

# tests/test_backfields_page.py
assert 'href="/backfields">Farm Systems' in nav
assert re.search(r'<a href="/backfields"\s+aria-current="page">Farm Systems</a>', html)

# tests/test_app.py
self.assertIn('href="/board">Archives</a>', html)
self.assertIn('href="/board" aria-current="page">Archives</a>', html)
```

Keep route-owned headings and titles such as `Backfields` and `The Archives | ValuCast` unchanged.

- [ ] **Step 9: Run the page and navigation tests**

```powershell
python -m pytest tests/test_launch_polish.py tests/test_scouting_page.py tests/test_backfields_page.py tests/test_app.py -q
```

Expected: PASS. If a stale assertion remains, locate only exact primary-nav expectations:

```powershell
rg -n 'href="/(|board|gaps|backfields)".*(Board|The Archives|Gaps|Backfields)</a>' tests
```

Expected after corrections: no stale primary-nav assertion; horizon-tab and route-heading references may remain.

- [ ] **Step 10: Commit the aligned site messaging**

```powershell
git add templates/base.html templates/index.html templates/partials/_footer_provenance.html static/style.css tests/test_launch_polish.py tests/test_scouting_page.py tests/test_backfields_page.py tests/test_app.py
git diff --cached --check
git commit -m "feat: align ValuCast positioning across the site"
```

---

### Task 2: Change the default share-graphic positioning without erasing product names

**Files:**
- Modify: `app.py:2590-2600,10621,10742`
- Modify: `tests/test_launch_polish.py`

**Interfaces:**
- Consumes: Existing `_graphic_header(..., tagline=...)` calls.
- Produces: Default tagline `Independent prospect intelligence`; explicit Buys and held-Buys taglines `Ahead of the Curve`.

- [ ] **Step 1: Add the failing share-tagline contract test**

Add this method to `TestLaunchPolish`:

```python
def test_share_graphic_positioning_preserves_named_products(self):
    import inspect
    import app as app_module

    default = inspect.signature(app_module._graphic_header).parameters["tagline"].default
    self.assertEqual(default, "Independent prospect intelligence")

    for renderer in (app_module._buys_share_card_png, app_module._buys_hold_share_card_png):
        self.assertIn('tagline="Ahead of the Curve"', inspect.getsource(renderer))
```

- [ ] **Step 2: Run the test and verify it fails**

```powershell
python -m pytest tests/test_launch_polish.py::TestLaunchPolish::test_share_graphic_positioning_preserves_named_products -q
```

Expected: FAIL because `_graphic_header` still defaults to `Ahead of the Curve`.

- [ ] **Step 3: Change the renderer default and preserve Buys explicitly**

Change the signature and comment in `app.py` to:

```python
def _graphic_header(
    img,
    draw,
    *,
    headline,
    subtitle,
    extra_line=None,
    tagline="Independent prospect intelligence",
    value_history=None,
):
    # Compact brand lockup, not a billboard. Prospect and player graphics use
    # the company positioning by default; named products override it explicitly.
```

Add this argument to both `_graphic_header` calls inside `_buys_share_card_png` and `_buys_hold_share_card_png`:

```python
tagline="Ahead of the Curve",
```

Do not change existing explicit taglines for Farm-System Rankings, The Second Opinion, Prospect Movers, Discipline Leaders, Call-Up Receipts, Track Record, or Forward Ledger.

- [ ] **Step 4: Run focused share tests**

```powershell
python -m pytest tests/test_launch_polish.py::TestLaunchPolish::test_share_graphic_positioning_preserves_named_products tests/test_buy_score.py tests/test_positional_share_card.py -q
```

Expected: PASS.

- [ ] **Step 5: Verify all named product overrides remain in source**

```powershell
rg -n 'tagline="(Ahead of the Curve|Farm-System Rankings|The Second Opinion|Prospect Movers|Discipline Leaders|Call-Up Receipts|Track Record|Forward Ledger)"' app.py
```

Expected: all eight names appear; `Ahead of the Curve` appears in both Buys renderers.

- [ ] **Step 6: Commit the share-tagline change**

```powershell
git add app.py tests/test_launch_polish.py
git diff --cached --check
git commit -m "feat: align share graphics with ValuCast positioning"
```

---

### Task 3: Verify scope, render behavior, and owner-applied social copy

**Files:**
- No code files created or modified.

**Interfaces:**
- Consumes: Completed Tasks 1 and 2.
- Produces: Test evidence, visual evidence, a data-invariance check, and the exact owner-applied X copy.

- [ ] **Step 1: Run the focused regression set**

```powershell
python -m pytest tests/test_launch_polish.py tests/test_scouting_page.py tests/test_backfields_page.py tests/test_app.py tests/test_buy_score.py tests/test_positional_share_card.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the full suite**

```powershell
python -m pytest -q
```

Expected from the 2026-08-04 baseline plus two new tests: `3187 passed, 3 skipped, 18 subtests passed`.

- [ ] **Step 3: Prove that no data or model artifact changed**

```powershell
git diff --exit-code origin/master...HEAD -- data projections prospects quality .github
git diff --name-only origin/master...HEAD
```

Expected: the first command exits 0 with no output. The second lists only the approved spec/plan, templates, CSS, `app.py`, and test files.

- [ ] **Step 4: Run desktop and mobile browser smoke checks**

Start the app without opening a visible helper window:

```powershell
$server = Start-Process python -ArgumentList '-m','flask','--app','app','run','--port','5055' -PassThru -WindowStyle Hidden
```

Open `http://127.0.0.1:5055/?mode=prospects` in a real browser at 1440×900 and 390×844. Verify:

- the headline and support line wrap without clipping;
- the board navigation remains visible immediately below the strip;
- no horizontal overflow is introduced;
- the four revised primary-nav labels wrap and retain visible keyboard focus;
- footer source/freshness text and the install button remain present;
- `/buys`, `/trade`, `/movers`, and `/methodology` still return 200 and retain their product names.

Stop the local server:

```powershell
Stop-Process -Id $server.Id
```

- [ ] **Step 5: Give the owner the exact X bio and pinned post**

Bio, 137 characters:

```text
Independent prospect intelligence, translated for your dynasty league. Daily rankings, values, trades and receipts. Free at valucast.app.
```

Pinned post, 269 characters:

```text
ValuCast independently evaluates prospects, then translates that evidence into your dynasty league.

Evaluate: prospect + MLB models
Translate: league-aware rankings, values + trades
Act: buys, movers + call-ups
Prove: methodology, Ledger + receipts

Free: valucast.app
```

The owner applies these manually. Do not automate X, request credentials, or add social-posting code.

- [ ] **Step 6: Hand the clean branch to the finishing workflow**

Run `git status --short --branch`; expected: clean branch. Then invoke `superpowers:finishing-a-development-branch` to choose push/PR/merge handling. Do not dispatch a data refresh or model workflow for this copy-only change.
