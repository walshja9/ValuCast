# ValuCast Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebrand League Values to ValuCast with collapsible config panel, CSV export, visual polish, and Render deployment.

**Architecture:** Flask + htmx stays as-is. Changes are purely frontend (templates, CSS, JS) plus one new `/export` route and Render config files. Engine, data pipeline, and all existing routes remain untouched.

**Tech Stack:** Flask, Jinja2, htmx 2.0.4, gunicorn (new), vanilla CSS + JS

**Test runner:** `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`

---

### Task 1: Rebrand to ValuCast

**Files:**
- Modify: `templates/base.html`
- Modify: `tests/test_app.py` (line 19 — update assertion from "League Values" to "ValuCast")

- [ ] **Step 1: Update the test assertion**

In `tests/test_app.py`, update `test_index_contains_league_values`:

```python
def test_index_contains_valucast(self):
    response = self.client.get("/")
    self.assertIn(b"ValuCast", response.data)
```

Also rename the method from `test_index_contains_league_values` to `test_index_contains_valucast`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest tests.test_app.TestIndexRoute.test_index_contains_valucast -v`
Expected: FAIL — response still contains "League Values", not "ValuCast"

- [ ] **Step 3: Update base.html**

In `templates/base.html`:

Change the `<title>` tag:
```html
<title>{% block title %}ValuCast{% endblock %}</title>
```

Change the header:
```html
<header class="site-header">
    <h1><a href="/">ValuCast</a></h1>
    <p class="tagline">Player values tuned to your league</p>
</header>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add templates/base.html tests/test_app.py
git commit -m "feat: rebrand to ValuCast — header, title, tagline"
```

---

### Task 2: Collapsible Config Panel

The setup panel (category checkboxes / points table) should be collapsed by default, showing a summary line like "Standard 5x5 · 12 teams · $200 budget". A "Customize" button toggles it open.

**Files:**
- Modify: `templates/index.html`
- Modify: `templates/partials/rankings_response.html`
- Modify: `static/style.css`
- Modify: `app.py` (add `config_summary` to context)
- Modify: `tests/test_app.py` (add test for collapsed state)

- [ ] **Step 1: Write tests for the collapsible panel**

Add to `tests/test_app.py` in the `TestIndexRoute` class:

```python
def test_index_contains_config_summary(self):
    """Default page load should show the config summary line."""
    response = self.client.get("/")
    self.assertIn(b"config-summary", response.data)

def test_index_setup_panel_collapsed_by_default(self):
    """Setup panel should have the collapsed class by default."""
    response = self.client.get("/")
    self.assertIn(b"setup-panel collapsed", response.data)

def test_index_contains_customize_button(self):
    """Page should have a Customize toggle button."""
    response = self.client.get("/")
    self.assertIn(b"customize-toggle", response.data)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest tests.test_app.TestIndexRoute -v`
Expected: 3 new tests FAIL

- [ ] **Step 3: Add config_summary to _build_context in app.py**

In `app.py`, add a helper function before `_build_context`:

```python
def _config_summary(mode: str, cats: list[str], pcats: list[str], split_rp: bool) -> str:
    """Build a human-readable summary of the active config."""
    from web.category_registry import CATEGORY_PRESETS
    if mode == "points":
        return "Points League · 12 teams · $200 budget"
    # Check if it matches a preset
    for name, preset in CATEGORY_PRESETS.items():
        if cats == preset["cats"] and pcats == preset["pcats"]:
            label = "Standard 5x5" if name == "5x5" else "6x6 (OBP/QS)" if name == "6x6" else name
            suffix = " · SP/RP split" if split_rp else ""
            return f"{label} · 12 teams · $200 budget{suffix}"
    cat_count = len(cats) + len(pcats)
    suffix = " · SP/RP split" if split_rp else ""
    return f"Custom {cat_count} categories · 12 teams · $200 budget{suffix}"
```

Then in `_build_context`, add `config_summary` to the returned dict:

```python
"config_summary": _config_summary(mode, cats, pcats, split_rp),
```

Add this line after the `"tiers": tiers,` line in the return dict.

- [ ] **Step 4: Update templates/index.html for collapsible panel**

Replace the `<section id="setup-panel" ...>` block (lines 28-34) and add the summary bar above it:

```html
    <div class="config-bar">
        <span class="config-summary">{{ config_summary }}</span>
        <button type="button" class="customize-toggle" onclick="toggleSetup()">Customize</button>
    </div>

    <section id="setup-panel" class="setup-panel collapsed">
        {% if mode == 'points' %}
            {% include "partials/setup_categories.html" if mode != 'points' else "partials/setup_points.html" %}
        {% else %}
            {% include "partials/setup_categories.html" %}
        {% endif %}
    </section>
```

Wait — the existing template already has the correct conditional. Keep the include logic as-is:

```html
    <div class="config-bar">
        <span class="config-summary">{{ config_summary }}</span>
        <button type="button" class="customize-toggle" onclick="toggleSetup()">Customize</button>
    </div>

    <section id="setup-panel" class="setup-panel collapsed">
        {% if mode == 'points' %}
            {% include "partials/setup_points.html" %}
        {% else %}
            {% include "partials/setup_categories.html" %}
        {% endif %}
    </section>
```

Add the `toggleSetup` function in the `<script>` block at the bottom:

```javascript
function toggleSetup() {
    const panel = document.getElementById('setup-panel');
    const btn = document.querySelector('.customize-toggle');
    panel.classList.toggle('collapsed');
    btn.textContent = panel.classList.contains('collapsed') ? 'Customize' : 'Hide';
}
```

- [ ] **Step 5: Update templates/partials/rankings_response.html**

The OOB swap needs to include the config bar and keep the collapsed class. Replace the entire file:

```html
{% include "partials/rankings_table.html" %}

<div class="config-bar" hx-swap-oob="innerHTML:.config-summary">{{ config_summary }}</div>

<section id="setup-panel" class="setup-panel" hx-swap-oob="innerHTML:#setup-panel">
    {% if mode == 'points' %}
        {% include "partials/setup_points.html" %}
    {% else %}
        {% include "partials/setup_categories.html" %}
    {% endif %}
</section>
```

Note: We use `innerHTML` swap on the setup panel so it replaces the inner content without touching the `collapsed` class on the outer element. The config summary updates via a targeted OOB swap as well.

- [ ] **Step 6: Add CSS for collapsible panel**

In `static/style.css`, add after the `.setup-panel` rule (around line 57):

```css
.config-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: #fff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 0.6rem 1.25rem;
    margin-bottom: 0.5rem;
}
.config-summary {
    font-size: 0.85rem;
    color: #374151;
    font-weight: 500;
}
.customize-toggle {
    padding: 0.35rem 0.85rem;
    font-size: 0.8rem;
    font-weight: 500;
    background: #fff;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    cursor: pointer;
    color: #374151;
    transition: all 0.15s;
}
.customize-toggle:hover {
    border-color: #2563eb;
    color: #2563eb;
}
.setup-panel.collapsed {
    display: none;
}
```

- [ ] **Step 7: Run all tests**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`
Expected: All tests pass

- [ ] **Step 8: Commit**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add app.py templates/index.html templates/partials/rankings_response.html static/style.css tests/test_app.py
git commit -m "feat: collapsible config panel with summary line"
```

---

### Task 3: CSS Visual Polish

Refinement pass on the existing CSS: tighter table rows, consistent component styling, filter bar background tint, wordmark typography treatment.

**Files:**
- Modify: `static/style.css`
- Modify: `templates/base.html` (wordmark font)

- [ ] **Step 1: Update header/wordmark styling**

In `static/style.css`, update the `.site-header h1` rule:

```css
.site-header h1 {
    font-size: 1.5rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}
```

- [ ] **Step 2: Tighten table styling**

In `static/style.css`, update these existing rules:

`.rankings-table td` — change padding from `0.4rem` to `0.35rem 0.4rem`.

`.rankings-table th` — change padding from `0.5rem 0.4rem` to `0.45rem 0.4rem`.

Add alternating row hover enhancement — update `.player-row:hover`:
```css
.player-row:hover { background: #f0f4ff; }
```
(Change from `#f8faff` to `#f0f4ff` for a slightly more visible hover.)

- [ ] **Step 3: Add filter bar background tint**

In `static/style.css`, update `.filter-bar`:

```css
.filter-bar {
    display: flex;
    align-items: center;
    gap: 1rem;
    margin-bottom: 1rem;
    flex-wrap: wrap;
    background: #f9fafb;
    padding: 0.75rem 1rem;
    border-radius: 8px;
    border: 1px solid #f0f0f0;
}
```

- [ ] **Step 4: Polish tier badges**

In `static/style.css`, update `.tier-badge`:

```css
.tier-badge {
    display: inline-block;
    margin-left: 0.3rem;
    font-size: 0.65rem;
    font-weight: 700;
    color: #fff;
    background: #2563eb;
    border-radius: 3px;
    padding: 0.1rem 0.35rem;
    vertical-align: middle;
}
```
(Slightly larger: font 0.6→0.65rem, padding 0.05→0.1rem vertical.)

- [ ] **Step 5: Add footer to base.html**

In `templates/base.html`, add a footer after `</main>` and before `</body>`:

```html
    <footer class="site-footer">
        <p>Data: FanGraphs Steamer + ZiPS projections</p>
    </footer>
```

- [ ] **Step 6: Add footer CSS**

In `static/style.css`, add:

```css
.site-footer {
    text-align: center;
    padding: 1.5rem 1rem;
    font-size: 0.75rem;
    color: #9ca3af;
    border-top: 1px solid #f0f0f0;
    margin-top: 2rem;
}
```

- [ ] **Step 7: Run all tests**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`
Expected: All tests pass (CSS changes don't break anything)

- [ ] **Step 8: Commit**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add static/style.css templates/base.html
git commit -m "style: visual polish — tighter table, filter bar tint, wordmark, footer"
```

---

### Task 4: CSV Export

New `/export` route that generates a CSV download of the current filtered rankings.

**Files:**
- Modify: `app.py` (add `/export` route)
- Modify: `templates/index.html` (add Export CSV button to filter bar)
- Modify: `tests/test_app.py` (add export tests)

- [ ] **Step 1: Write tests for CSV export**

Add a new test class to `tests/test_app.py`:

```python
import csv
import io


class TestExportRoute(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_export_returns_csv(self):
        response = self.client.get("/export?mode=categories&cats=R,HR&pcats=K,ERA")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.content_type)

    def test_export_has_attachment_header(self):
        response = self.client.get("/export?mode=categories&cats=R,HR&pcats=K,ERA")
        self.assertIn("attachment", response.headers.get("Content-Disposition", ""))
        self.assertIn("valucast-rankings.csv", response.headers.get("Content-Disposition", ""))

    def test_export_has_header_row(self):
        response = self.client.get("/export?mode=categories&cats=R,HR&pcats=K,ERA")
        text = response.data.decode("utf-8")
        reader = csv.reader(io.StringIO(text))
        header = next(reader)
        self.assertIn("Rank", header)
        self.assertIn("Player", header)
        self.assertIn("Value", header)

    def test_export_has_data_rows(self):
        response = self.client.get("/export?mode=categories&cats=R,HR&pcats=K,ERA")
        text = response.data.decode("utf-8")
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        self.assertGreater(len(rows), 1)  # Header + at least one data row

    def test_export_respects_pool_filter(self):
        response = self.client.get("/export?pool=hitter&cats=R,HR&pcats=K,ERA")
        text = response.data.decode("utf-8")
        reader = csv.reader(io.StringIO(text))
        header = next(reader)
        pos_col = header.index("Positions")
        for row in reader:
            self.assertNotIn("SP", row[pos_col].split(", "))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest tests.test_app.TestExportRoute -v`
Expected: FAIL — no `/export` route exists

- [ ] **Step 3: Add /export route to app.py**

Add this import at the top of `app.py`:

```python
import csv
import io
```

Add the route after the `/compare` route:

```python
@app.route("/export")
def export_csv():
    ctx = _build_context(request.args)
    results = ctx["results"]
    display_columns = ctx["display_columns"]
    position_ranks = ctx["position_ranks"]
    dollar_values = ctx["dollar_values"]
    tiers = ctx["tiers"]

    output = io.StringIO()
    writer = csv.writer(output)

    # Header row
    header = ["Rank", "Player", "Positions", "Team", "Position Rank", "Tier", "Auction $", "Value"]
    for col in display_columns:
        header.append(col["label"])
    writer.writerow(header)

    # Data rows
    for i, result in enumerate(results, 1):
        row = [
            i,
            result.player.name,
            ", ".join(result.player.positions) or "DH",
            result.player.metadata.get("team", ""),
            position_ranks.get(result.player.id, ""),
            tiers.get(result.player.id, ""),
            dollar_values.get(result.player.id, 0),
            round(result.total_value, 2),
        ]
        for col in display_columns:
            if col.get("split"):
                sp_raw = result.raw_values.get(col["sp_id"])
                rp_raw = result.raw_values.get(col["rp_id"])
                val = result.category_values.get(col["sp_id"], 0) + result.category_values.get(col["rp_id"], 0)
                row.append(round(val, 1) if sp_raw is not None or rp_raw is not None else "")
            else:
                raw = result.raw_values.get(col["id"])
                val = result.category_values.get(col["id"], 0)
                row.append(round(val, 1) if raw is not None else "")
        writer.writerow(row)

    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = "attachment; filename=valucast-rankings.csv"
    return response
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`
Expected: All tests pass

- [ ] **Step 5: Add Export CSV button to the filter bar in templates/index.html**

In `templates/index.html`, add the export button inside the `<section class="filter-bar">`, after the search input:

```html
        <a id="export-btn" class="export-btn" onclick="exportCsv(event)">Export CSV</a>
```

Add the `exportCsv` function to the `<script>` block:

```javascript
function exportCsv(e) {
    e.preventDefault();
    const params = new URLSearchParams(new FormData(document.getElementById('league-setup')));
    window.location.href = '/export?' + params.toString();
}
```

- [ ] **Step 6: Add CSS for export button**

In `static/style.css`, add:

```css
.export-btn {
    padding: 0.35rem 0.75rem;
    font-size: 0.8rem;
    font-weight: 500;
    background: #fff;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    cursor: pointer;
    color: #374151;
    transition: all 0.15s;
    margin-left: auto;
    text-decoration: none;
}
.export-btn:hover {
    border-color: #2563eb;
    color: #2563eb;
    text-decoration: none;
}
```

- [ ] **Step 7: Run all tests**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`
Expected: All tests pass

- [ ] **Step 8: Commit**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add app.py templates/index.html static/style.css tests/test_app.py
git commit -m "feat: CSV export — /export route with filtered rankings download"
```

---

### Task 5: Render Deployment Config

Add the files needed for Render to build and serve the app.

**Files:**
- Create: `requirements.txt`
- Create: `render.yaml`
- Modify: `app.py` (add host/port binding for production)

- [ ] **Step 1: Create requirements.txt**

Create `requirements.txt` in the project root:

```
flask>=3.0,<4.0
gunicorn>=22.0,<23.0
```

- [ ] **Step 2: Create render.yaml**

Create `render.yaml` in the project root:

```yaml
services:
  - type: web
    name: valucast
    runtime: python
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn app:app
    envVars:
      - key: PYTHON_VERSION
        value: "3.12"
    plan: free
```

- [ ] **Step 3: Update app.py for production binding**

Update the `if __name__` block at the bottom of `app.py`:

```python
if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=True, host="0.0.0.0", port=port)
```

- [ ] **Step 4: Verify the app still runs locally**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add requirements.txt render.yaml app.py
git commit -m "chore: add Render deployment config — requirements.txt, render.yaml"
```

---

### Task 6: Mobile Responsive Fixes for New Components

Ensure the new config bar, customize button, and export button work on mobile (<640px).

**Files:**
- Modify: `static/style.css`

- [ ] **Step 1: Add mobile styles for new components**

In `static/style.css`, add inside the existing `@media (max-width: 640px)` block:

```css
    .config-bar { flex-direction: column; gap: 0.4rem; align-items: stretch; }
    .customize-toggle { width: 100%; text-align: center; }
    .export-btn { width: 100%; text-align: center; margin-left: 0; }
```

- [ ] **Step 2: Run all tests**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add static/style.css
git commit -m "style: mobile responsive fixes for config bar and export button"
```

---

### Task 7: Final Verification and Push

- [ ] **Step 1: Run the full test suite**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`
Expected: All tests pass (177 existing + new tests)

- [ ] **Step 2: Start the app locally and smoke-test**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python app.py`

Verify in browser at http://localhost:5001:
1. Page title says "ValuCast"
2. Header says "ValuCast" with tagline "Player values tuned to your league"
3. Config summary shows "Standard 5x5 · 12 teams · $200 budget"
4. Setup panel is hidden by default
5. "Customize" button expands/collapses the panel
6. Rankings table loads with data
7. "Export CSV" button downloads a CSV file
8. Mode switching (H2H/Roto/Points) works
9. Mobile view (resize to <640px) looks correct

- [ ] **Step 3: Push to GitHub**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git push origin master
```

- [ ] **Step 4: Set up Render deployment**

This step is manual — Alex creates the Render service pointing to the GitHub repo. Render will auto-detect `render.yaml` and deploy.
