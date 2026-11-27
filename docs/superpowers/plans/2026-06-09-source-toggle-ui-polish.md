# Source Toggle UI Polish + ValuCast Methodology — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the plain source `<select>` with an accessible segmented control, add an HTMX-fresh provenance caption when ValuCast is active, make the footer source/page-aware, render blank teams as `—` in HTML only, and ship an internal methodology doc plus a public `/methodology` page.

**Architecture:** Pure presentation + docs — no projection/data/run changes. The control is two `name="source"` radios styled as pills (reusing the `.mode-btn` active-state idiom). The caption is DRY'd into a tiny include and kept fresh via htmx out-of-band swap (`hx-swap-oob`) emitted on every `/rankings` response, mirroring the existing `#setup-panel` OOB pattern. `/methodology` is a static read-only route distilled from the canonical internal doc.

**Tech Stack:** Flask, Jinja2, htmx 2.0, vanilla CSS, Python `unittest` (run via `pytest`).

**Spec:** `docs/specs/2026-06-09-source-toggle-ui-polish-design.md`

---

## File Structure

- `templates/index.html` — replace the source `<select>` (lines 55-61) with the segmented `<fieldset>`; add the `#source-caption` placeholder after the config-bar.
- `templates/partials/_source_caption.html` — **NEW.** The single source of the locked caption text (DRY across full-page render + OOB swap).
- `templates/partials/rankings_response.html` — emit the OOB `#source-caption` fragment on every response (gated by source + non-dynasty).
- `templates/partials/rankings_table.html` — team cell (line 43) renders `team or '—'`. HTML only; export untouched.
- `templates/base.html` — footer "how" + "data" lines become source/page-aware (steamer / valucast / dynasty / methodology).
- `templates/methodology.html` — **NEW.** Public "How ValuCast works" page (extends base).
- `static/style.css` — `.source-seg` / `.source-opt` segmented-control styles: equal active weight, clip-hidden-but-focusable radios, `:focus-visible` ring, mobile-safe.
- `app.py` — add the `/methodology` route.
- `docs/valucast-methodology.md` — **NEW.** Canonical internal methodology reference.
- `tests/test_app_source.py` — update the one `<select>`-era test; add control/caption/footer/dash/methodology tests.

**Test command (all tasks):** `python -m pytest tests/test_app_source.py -q` (run from repo root; the test file inserts `src/` onto `sys.path`). Full suite: `python -m pytest tests -q`.

---

### Task 1: Segmented source control (accessible radios)

Replace the `<select name="source">` with two `name="source"` radio pills. Same `name`, so form serialization + stickiness are unchanged and the form's existing `change` trigger re-renders.

**Files:**
- Modify: `templates/index.html:55-61`
- Modify: `static/style.css` (append after the `.mode-btn` block, ~line 54)
- Test: `tests/test_app_source.py`

- [ ] **Step 1: Update the existing `<select>`-era test to expect radios**

The current `test_full_page_reflects_selected_source` asserts `value="valucast" selected`, which is `<select>` markup. Replace that single test method body with radio expectations (in `tests/test_app_source.py`):

```python
    def test_full_page_reflects_selected_source(self):
        # Loading /?source=valucast renders the ValuCast radio pre-checked.
        r = self.client.get("/?source=valucast")
        self.assertIn(b'value="valucast" checked', r.data)
```

- [ ] **Step 2: Add new tests for the segmented control (append to `TestSourceSelection`)**

```python
    def test_source_control_is_segmented_radios(self):
        # The plain <select> is gone; two name="source" radios remain.
        r = self.client.get("/")
        self.assertNotIn(b'<select name="source"', r.data)
        self.assertIn(b'name="source"', r.data)
        self.assertIn(b'type="radio"', r.data)
        self.assertIn(b'aria-label="Projection source"', r.data)

    def test_source_control_equal_weight_no_valucast_badge(self):
        # Equal visual weight: no ValuCast-only badge/marketing class.
        r = self.client.get("/")
        self.assertNotIn(b'vc-badge', r.data)
        self.assertNotIn(b'IN-HOUSE', r.data)

    def test_source_radios_are_focusable_not_display_none(self):
        # Accessibility: radios hidden via clip (focusable), with a focus ring,
        # NOT display:none (which removes them from tab order).
        css = self.client.get("/static/style.css").data
        self.assertIn(b'.source-seg', css)
        self.assertIn(b'clip-path', css)
        self.assertIn(b':focus-visible', css)
        self.assertNotIn(b'.source-opt input[type="radio"] { display: none', css)
```

- [ ] **Step 3: Run the new tests to verify they fail**

Run: `python -m pytest tests/test_app_source.py -q`
Expected: FAIL — `<select name="source"` still present; no `.source-seg`/`clip-path` in CSS; `value="valucast" checked` not yet rendered.

- [ ] **Step 4: Replace the `<select>` with the segmented fieldset**

In `templates/index.html`, replace lines 55-61 (the `<label class="source-selector">…</label>` block) with:

```html
        <fieldset class="source-seg" aria-label="Projection source">
            <label class="source-opt">
                <input type="radio" name="source" value="steamer"
                       {% if (source or 'steamer') != 'valucast' %}checked{% endif %}>
                <span>Steamer</span>
            </label>
            <label class="source-opt">
                <input type="radio" name="source" value="valucast"
                       {% if source == 'valucast' %}checked{% endif %}>
                <span>ValuCast H+P</span>
            </label>
        </fieldset>
```

- [ ] **Step 5: Add the segmented-control styles**

Append to `static/style.css` immediately after line 54 (`.mode-btn:has(input:checked)…`):

```css
.source-seg {
    display: inline-flex;
    border: 1px solid #d1d5db;
    border-radius: 8px;
    overflow: hidden;
    padding: 0;
    margin: 0;
    min-width: 0;
}
.source-opt { cursor: pointer; display: inline-flex; }
.source-opt > span {
    padding: 0.4rem 0.9rem;
    font-size: 0.8rem;
    font-weight: 500;
    background: #fff;
    color: #334155;
    white-space: nowrap;
}
.source-opt + .source-opt > span { border-left: 1px solid #d1d5db; }
/* Hidden but focusable — NOT display:none (which drops it from tab order). */
.source-opt input[type="radio"] {
    position: absolute;
    width: 1px;
    height: 1px;
    clip-path: inset(50%);
    overflow: hidden;
}
/* Equal weight: whichever source is checked gets the SAME blue treatment. */
.source-opt:has(input:checked) > span { background: #2563eb; color: #fff; }
.source-opt input:focus-visible + span { outline: 2px solid #1e40af; outline-offset: -2px; }
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_app_source.py -q`
Expected: PASS (all source tests, including the pre-existing stickiness/error tests).

- [ ] **Step 7: Commit**

```bash
git add templates/index.html static/style.css tests/test_app_source.py
git commit -m "feat: segmented accessible source control (replaces select)"
```

---

### Task 2: HTMX-fresh provenance caption

A one-line caption appears only on the ValuCast board, and stays fresh on source/filter switches via an out-of-band swap emitted on every `/rankings` response.

**Files:**
- Create: `templates/partials/_source_caption.html`
- Modify: `templates/index.html` (add placeholder after the config-bar `</div>`, ~line 63)
- Modify: `templates/partials/rankings_response.html` (emit OOB fragment at top)
- Test: `tests/test_app_source.py`

- [ ] **Step 1: Write failing tests for caption gating + freshness**

Append to `tests/test_app_source.py`:

```python
    def test_caption_present_on_valucast_response(self):
        r = self.client.get("/rankings?source=valucast")
        self.assertIn(b'pitching model is fully in-house', r.data)
        self.assertIn(b'hx-swap-oob', r.data)
        self.assertIn(b'id="source-caption"', r.data)
        self.assertIn(b'/methodology', r.data)

    def test_caption_empty_on_steamer_response(self):
        # OOB element still ships (to clear a stale caption) but carries no text.
        r = self.client.get("/rankings")
        self.assertIn(b'id="source-caption"', r.data)
        self.assertNotIn(b'pitching model is fully in-house', r.data)

    def test_caption_absent_in_dynasty(self):
        r = self.client.get("/rankings?mode=dd_dynasty")
        self.assertNotIn(b'pitching model is fully in-house', r.data)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_app_source.py -k caption -q`
Expected: FAIL — caption text/markup not yet rendered.

- [ ] **Step 3: Create the DRY caption include**

Create `templates/partials/_source_caption.html` (exact locked text):

```html
<strong>ValuCast H+P</strong> &mdash; full-season projections: hitters use Savant xBA/xSLG de-noising; the <strong>pitching model is fully in-house</strong>. Steamer remains the default external benchmark. <a href="/methodology">How ValuCast works &rarr;</a>
```

- [ ] **Step 4: Add the placeholder to the full page**

In `templates/index.html`, immediately after the non-dynasty config-bar closing `</div>` (currently line 63, before `<section id="setup-panel"…>` on line 65), insert:

```html
    <div id="source-caption" class="source-caption">
        {% if source == 'valucast' %}{% include "partials/_source_caption.html" %}{% endif %}
    </div>
```

- [ ] **Step 5: Emit the OOB caption on every `/rankings` response**

In `templates/partials/rankings_response.html`, add this as the **first** line (above the existing `{% if mode == 'dd_dynasty'… %}`), so it fires for both branches and clears stale captions on mode/source transitions:

```html
<div id="source-caption" class="source-caption" hx-swap-oob="innerHTML:#source-caption">{% if source == 'valucast' and mode not in ['dd_dynasty', 'prospects'] %}{% include "partials/_source_caption.html" %}{% endif %}</div>
```

- [ ] **Step 6: Add caption styling**

Append to `static/style.css` (after the `.source-opt` block from Task 1):

```css
.source-caption:not(:empty) {
    font-size: 0.78rem;
    color: #64748b;
    margin: 0 0 0.6rem;
    padding: 0 0.25rem;
}
.source-caption a { color: #1e40af; text-decoration: none; font-weight: 600; }
.source-caption a:hover { text-decoration: underline; }
```

- [ ] **Step 7: Run to verify pass**

Run: `python -m pytest tests/test_app_source.py -k caption -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add templates/partials/_source_caption.html templates/index.html templates/partials/rankings_response.html static/style.css tests/test_app_source.py
git commit -m "feat: provenance caption with htmx OOB freshness"
```

---

### Task 3: Blank team → `—` in HTML only

Blank teams (~26%, the source ceiling) render as a dash in the table; exports and data stay blank.

**Files:**
- Modify: `templates/partials/rankings_table.html:43`
- Test: `tests/test_app_source.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_app_source.py` (note: source file is UTF-8; `—` is U+2014 em dash):

```python
    def test_blank_team_dash_in_html_blank_in_export(self):
        # ~26% of ValuCast rows have no team -> HTML shows a dash in the team cell.
        html = self.client.get("/rankings?source=valucast").data.decode("utf-8")
        self.assertIn('class="col-team">—<', html)
        # Export keeps the team blank, never the display dash.
        csv = self.client.get("/export?source=valucast").data.decode("utf-8")
        self.assertNotIn("—", csv)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_app_source.py -k blank_team -q`
Expected: FAIL — team cell currently renders empty string, so `col-team">—<` is absent.

- [ ] **Step 3: Render the dash for blank teams**

In `templates/partials/rankings_table.html`, change line 43 from:

```html
            <td class="col-team">{{ result.player.metadata.get('team', '') }}</td>
```

to:

```html
            <td class="col-team">{{ result.player.metadata.get('team') or '—' }}</td>
```

(The export route at `app.py:725` already writes `metadata.get("team", "")` — untouched, so CSV stays blank.)

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_app_source.py -k blank_team -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/partials/rankings_table.html tests/test_app_source.py
git commit -m "feat: render blank teams as dash in HTML (exports stay blank)"
```

---

### Task 4: Source/page-aware footer

`base.html` currently always claims "Steamer ROS", which is false on the ValuCast board and on `/methodology`. Make the footer branch on dynasty / valucast / methodology / default.

**Files:**
- Modify: `templates/base.html:18-35`
- Test: `tests/test_app_source.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_app_source.py`:

```python
    def test_footer_valucast_board_no_steamer_claim(self):
        r = self.client.get("/?source=valucast")
        self.assertIn(b'pitching model in-house', r.data)
        self.assertNotIn(b'Redraft values use 2026 actual stats + Steamer', r.data)

    def test_footer_steamer_board_unchanged(self):
        r = self.client.get("/")
        self.assertIn(b'Redraft values use 2026 actual stats + Steamer', r.data)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_app_source.py -k footer -q`
Expected: FAIL — the ValuCast board still shows the Steamer redraft sentence.

- [ ] **Step 3: Make the footer source/page-aware**

In `templates/base.html`, replace the `<footer>` body (lines 18-36) with:

```html
    <footer class="site-footer">
        <div class="footer-about">
            <p class="footer-how">
                {% if methodology_page %}
                ValuCast methodology — how our projections are built and validated. Source for player values is selectable on the main board.
                {% elif mode == 'dd_dynasty' or mode == 'prospects' %}
                Dynasty values blend current MLB value, age-adjusted future value, and prospect value. Dynasty is currently a beta model — league customization is coming.
                {% elif source == 'valucast' %}
                ValuCast H+P projection — hitters Savant-de-noised, pitching model in-house, scored against your league's categories and weights.
                {% else %}
                Redraft values use 2026 actual stats + Steamer rest-of-season projections, scored against your league's categories and weights.
                {% endif %}
            </p>
        </div>
        <p>
            {% if methodology_page %}
            <a href="/">Back to rankings</a> · <a href="mailto:valucast.feedback@gmail.com">Send feedback</a>
            {% else %}
            {% if mode == 'dd_dynasty' or mode == 'prospects' %}
            Data: Dynasty model + prospect feed · MLB stats from FanGraphs Steamer ROS + MLB Stats API{% if as_of %} · Updated {{ as_of }}{% endif %}
            {% elif source == 'valucast' %}
            Data: ValuCast H+P (in-house projections) + MLB Stats API{% if as_of %} · Updated {{ as_of }}{% endif %}
            {% else %}
            Data: FanGraphs Steamer ROS + MLB Stats API{% if as_of %} · Updated {{ as_of }}{% endif %}
            {% endif %}
            · <a href="mailto:valucast.feedback@gmail.com">Send feedback</a>
            {% endif %}
        </p>
    </footer>
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_app_source.py -k footer -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/base.html tests/test_app_source.py
git commit -m "feat: source/page-aware footer provenance"
```

---

### Task 5: Public `/methodology` page

A read-only route + template distilled for a league audience: what ValuCast is, the two boards distinguished, how hitters/pitchers are projected, validation, what's ours vs borrowed, track record, version marker.

**Files:**
- Create: `templates/methodology.html`
- Modify: `app.py` (add route near the other `@app.route` handlers, after `index()`/`rankings()`)
- Test: `tests/test_app_source.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_app_source.py`:

```python
    def test_methodology_page_renders_honest_statements(self):
        r = self.client.get("/methodology")
        self.assertEqual(r.status_code, 200)
        body = r.data
        self.assertIn(b'pitching model is fully in-house', body)
        self.assertIn(b'Savant xBA/xSLG', body)
        self.assertIn(b'did not clear our validation bar', body)
        self.assertIn(b'ValuCast H+P v1', body)
        self.assertIn(b'June 2026', body)
        # The two-boards distinction (comparison, not a formal backtest).
        self.assertIn(b'not an apples-to-apples', body)
        # Public page must NOT leak the internal correlation figure.
        self.assertNotIn(b'0.87', body)

    def test_methodology_footer_has_no_steamer_redraft_claim(self):
        r = self.client.get("/methodology")
        self.assertNotIn(b'Redraft values use 2026 actual stats + Steamer', r.data)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_app_source.py -k methodology -q`
Expected: FAIL — `/methodology` returns 404.

- [ ] **Step 3: Add the route**

In `app.py`, after the `rankings()` function (ends ~line 573), add:

```python
@app.route("/methodology")
def methodology():
    """Public 'How ValuCast works' page. Static render, no data/auth."""
    return render_template("methodology.html", methodology_page=True)
```

- [ ] **Step 4: Create the page template**

Create `templates/methodology.html`:

```html
{% extends "base.html" %}
{% block title %}How ValuCast Works{% endblock %}
{% block content %}
<article class="methodology">
    <h2>How ValuCast Works</h2>
    <p class="methodology-version">As of June 2026 · ValuCast H+P v1</p>

    <section>
        <h3>What ValuCast is</h3>
        <p>ValuCast turns player projections into values tuned to <em>your</em> league's
        categories, weights, and roster rules. You can value players from two projection
        sources: <strong>Steamer</strong> (the external benchmark, and the default) or
        <strong>ValuCast H+P</strong>, our own in-house projection.</p>
    </section>

    <section>
        <h3>The two boards, distinguished</h3>
        <p>The <strong>default board</strong> values players from current-season actual
        stats plus Steamer rest-of-season projections. The <strong>ValuCast board</strong>
        values players from our own full-season projection, built from prior seasons.</p>
        <p>Because those are two different <em>kinds</em> of number, flipping the source
        toggle is useful for eyeballing differences, but it is <strong>not an
        apples-to-apples formal backtest</strong>. Our real check on accuracy is the
        held-out validation described below.</p>
    </section>

    <section>
        <h3>How hitters are projected</h3>
        <p>A Marcel-style projection (recent seasons weighted, regressed toward league
        average, age-adjusted), with one upgrade: we <strong>de-noise the inputs</strong>
        toward Statcast expected stats (Savant xBA/xSLG) before projecting, which beat the
        plain version on held-out data.</p>
        <p>We also tested an in-house expected-stats model, but it did not clear our
        validation bar, so hitters continue to use Savant xBA/xSLG as inputs.</p>
    </section>

    <section>
        <h3>How pitchers are projected</h3>
        <p>The pitching model is fully in-house: a per-batter-faced, role-routed
        projection that blends a pitcher's starting vs. relieving usage continuously
        rather than forcing a starter/reliever cliff.</p>
    </section>

    <section>
        <h3>How we validate</h3>
        <p>Every model change has to earn its place. We hold out future seasons, project
        forward without peeking, and only keep a change if it beats simple
        baselines (last year's numbers, league average, a plain projection) on data the
        model never saw. Changes that didn't clear that bar were dropped — honestly logged
        either way.</p>
    </section>

    <section>
        <h3>What's ours vs. borrowed</h3>
        <ul>
            <li><strong>Pitching:</strong> model is fully in-house.</li>
            <li><strong>Hitting:</strong> our projection model, using Savant xBA/xSLG as inputs.</li>
            <li><strong>Steamer:</strong> the external benchmark and the default source.</li>
        </ul>
    </section>

    <section>
        <h3>Track record</h3>
        <p>On held-out seasons, both the hitting and pitching models beat their plain
        baselines. A couple of tuning experiments and the in-house expected-stats model did
        not, and were not shipped.</p>
    </section>
</article>
{% endblock %}
```

- [ ] **Step 5: Add light page styling**

Append to `static/style.css`:

```css
.methodology { max-width: 760px; margin: 0 auto; line-height: 1.55; }
.methodology h2 { margin-bottom: 0.2rem; }
.methodology-version { color: #64748b; font-size: 0.8rem; margin-top: 0; }
.methodology section { margin-top: 1.4rem; }
.methodology h3 { color: #1e40af; font-size: 1.05rem; margin-bottom: 0.4rem; }
```

- [ ] **Step 6: Run to verify pass**

Run: `python -m pytest tests/test_app_source.py -k methodology -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app.py templates/methodology.html static/style.css tests/test_app_source.py
git commit -m "feat: public /methodology page"
```

---

### Task 6: Internal methodology doc

The canonical engineering reference the public page distills from. No app wiring; a content file with one existence test to keep the honesty ledger honest.

**Files:**
- Create: `docs/valucast-methodology.md`
- Test: `tests/test_app_source.py`

- [ ] **Step 1: Write the failing existence/content test**

Append to `tests/test_app_source.py`:

```python
    def test_internal_methodology_doc_exists(self):
        doc = Path(__file__).parent.parent / "docs" / "valucast-methodology.md"
        self.assertTrue(doc.exists(), "internal methodology doc missing")
        text = doc.read_text(encoding="utf-8")
        for marker in ("ValuCast H+P v1", "SHORTFALL", "rung", "carryover", "0.87"):
            self.assertIn(marker, text)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_app_source.py -k internal_methodology -q`
Expected: FAIL — doc does not exist.

- [ ] **Step 3: Write the internal doc**

Create `docs/valucast-methodology.md`:

```markdown
# ValuCast Projection Methodology (Internal)

> As of June 2026 · ValuCast H+P v1. Canonical engineering reference. The public
> `/methodology` page is distilled from this; keep this the source of truth.

## The rung program

We built ValuCast's projections as a ladder of rungs, each gated by held-out validation.

### Hitting
1. **Marcel foundation** — recent seasons weighted 5/4/3, regressed toward league mean
   (`n_reg`), age-adjusted, per-PA rate components reconstructed. WIN vs. persistence/
   league-avg baselines (rate-stat MAE ratio ~0.979).
2. **Reliability weighting (Rung 2)** — stabilization-anchored year-to-year reliability.
   TIE — did not clear the carryover guard, not shipped as a win.
3. **Statcast input de-noising (Rung 3)** — blend actual contact/power toward Savant
   xBA/xSLG with mix-preserving redistribution into 1B/2B/3B/HR (knobs
   `alpha_contact`/`alpha_power`; `gamma=0` nests classic). WIN — shipped.
4. **Barrel→HR (Rung 4)** — gated non-build (did not beat baseline).

### Pitching
- **Role-routed Marcel**, per-batter-faced, with a **continuous SP-probability** blend
  (`p_sp`) instead of a starter/reliever cliff; leakage-safe role-shift `f[c]^(h_sp − p_sp)`
  (no double-apply); separate SP/RP usage models. WIN — skill MAE ratio ~0.821. Fully
  in-house (no borrowed projection inputs).

## Validation discipline
- **Immutable historical backbone** (content-compared, Windows-newline-safe).
- **Leakage-safe rolling-origin backtest** — project forward, never peek.
- **Beat-the-baseline gates** — persistence → league-average → classic Marcel.
- **Carryover guard** — a tuning-block win must replicate on a disjoint scoring block.
- Go/no-go gating killed Rung 4 and the own-xBA Phase A.

## Honesty rules (ours vs. borrowed)
- **Pitching:** model fully in-house.
- **Hitting:** our projection model, consuming **Savant xBA/xSLG** as inputs.
- **Own-xBA grid (Phase A): SHORTFALL.** Our EV×LA empirical grid reached corr 0.87 but
  did not beat Savant (sprint-speed component needed). Savant remains the better input;
  we kept the finding and did not ship our own xBA.
- **Steamer:** external benchmark and the default source.

## Verdict ledger
| Rung | Result |
|---|---|
| Hitting foundation | WIN — rate-stat MAE ratio ~0.979 |
| Reliability (Rung 2) | TIE — failed carryover guard |
| Statcast de-noise (Rung 3) | WIN — shipped |
| Barrel→HR (Rung 4) | NO — gated out |
| Pitching foundation | WIN — skill MAE ratio ~0.821 |
| Own-xBA grid (Phase A) | SHORTFALL — corr 0.87, did not beat Savant |

## The workflow
Brainstorm → spec → plan → execute → held-out verdict, recorded honestly either way.
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_app_source.py -k internal_methodology -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/valucast-methodology.md tests/test_app_source.py
git commit -m "docs: canonical internal ValuCast methodology reference"
```

---

### Task 7: Full-suite regression check

- [ ] **Step 1: Run the complete suite**

Run: `python -m pytest tests -q`
Expected: PASS — all source tests green plus the prior ~571 tests; default board unchanged.

- [ ] **Step 2: If green, no commit needed**

Nothing to commit unless a regression surfaced. If one does, STOP and report rather than patching blindly.

---

## Self-Review

**Spec coverage:**
- §1 segmented control → Task 1 (equal weight via shared `:has(input:checked)` rule; accessibility via clip-hidden focusable radios + `:focus-visible`; mobile via config-bar's existing column stack + `white-space:nowrap` pills).
- §2 caption + HTMX freshness → Task 2 (DRY include + OOB emitted on every response, both branches, gated).
- §3 scope (non-dynasty only) → enforced by placeholder living in the non-dynasty `{% else %}` block + the OOB gate `mode not in [dd_dynasty, prospects]`.
- §4 missing-team dash (HTML only) → Task 3 (export path untouched at `app.py:725`).
- §4b source-aware footer → Task 4.
- §5 internal doc → Task 6.
- §6 public page (two-boards distinction, own-xBA disclosure wording, version marker, in-house wording) → Task 5.
- Success criteria 1-9 → each has an asserting test (Tasks 1-6); criterion 9 → Task 7.

**Placeholder scan:** No TBD/TODO/"handle edge cases"; every code step shows complete content.

**Type/name consistency:** `#source-caption` id, `.source-seg`/`.source-opt` classes, `partials/_source_caption.html` include path, `methodology_page` context flag, and `/methodology` route name are used identically across index.html, rankings_response.html, base.html, app.py, and the tests.

**Note on the one modified test:** `test_full_page_reflects_selected_source` is intentionally rewritten in Task 1 Step 1 because the `<select>`-era assertion (`value="valucast" selected`) no longer matches radio markup — this is a deliberate spec-driven change, not a regression.
