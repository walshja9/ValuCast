# Unified Track Record Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing `/ledger` page into one plain-English Track Record hub for Forward Calls, Consensus Movement, and Call-Up Timing while preserving each evidence lane's distinct cohort and denominator.

**Architecture:** Reuse the three committed artifacts and their existing loaders. Add one shared request context used by the `/ledger` page and its PNG, reuse a small scoring-rules partial on both Track Record and Receipts, and leave every builder and scoring rule unchanged.

**Tech Stack:** Flask, Jinja2, Pillow, existing CSS, pytest.

## Global Constraints

- Do not change any model, rank, value, cap, Role Watch, publication decision, artifact builder, or registered scoring rule.
- Do not blend rates across the three evidence populations.
- Every percentage must render beside its numerator and denominator.
- Preserve `SCOREBOARD_HOLD` and `RECEIPTS_HOLD`; held data must never leak into `/ledger` or its PNG.
- Keep `/ledger`, `/track-record`, `/scoreboard`, and `/receipts` working; `/track-record` remains the permanent redirect to `/ledger`.
- The current working tree already contains in-scope edits to `templates/track_record.html` and `tests/test_aotc_scorecard.py`; review and incorporate them instead of overwriting them.
- Do not stage unrelated changes in `plans/034-post-2026-prospect-challenger-epoch.md`, audit files, `.claude/`, or `data/dd/dd_dynasty_feed.json`.
- Use no new dependency and add no new scoring artifact.

---

### Task 1: Compose the three existing evidence contexts

**Files:**
- Modify: `app.py:8560-8608`
- Modify: `app.py:8777-8796`
- Modify: `app.py:9188-9245`
- Test: `tests/test_aotc_scorecard.py`

**Interfaces:**
- Consumes: `_load_scorecard_payload() -> dict | None`, `_load_forward_scoreboard_payload() -> dict | None`, `_scoreboard_view(dict) -> dict`, `_build_receipts_page_context() -> dict`, `SCOREBOARD_HOLD`, and `RECEIPTS_HOLD`.
- Produces: `_track_record_context() -> dict` with keys `sc`, `forward_sc`, and the existing receipt-context keys; `_scoreboard_view()` additionally returns `clean_retractions` and `win_rate_pct`.

- [ ] **Step 1: Write failing context tests**

Add these tests to `tests/test_aotc_scorecard.py`:

```python
def test_track_record_context_composes_existing_artifacts_and_rates(monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module, "SCOREBOARD_HOLD", False)
    monkeypatch.setattr(app_module, "RECEIPTS_HOLD", False)
    monkeypatch.setattr(app_module, "_load_scorecard_payload", lambda: {"artifact": "consensus"})
    monkeypatch.setattr(app_module, "_load_forward_scoreboard_payload", lambda: {
        "anticipation_score": {"pool_size": 70, "provisional": True},
        "funnel": {
            "wins": 39,
            "losses": 31,
            "open": 102,
            "total_claims": 258,
            "excluded_from_pool": 188,
            "unscored_or_unclassified": 0,
            "buckets": {"clean_retraction": 86},
            "self_retraction_rate": {"retracted": 117, "total": 258, "rate": 117 / 258},
        },
        "cohorts": {"cohort_count": 4},
    })
    monkeypatch.setattr(app_module, "_load_receipts_payload", lambda: {
        "generated_at": "2026-07-21T00:00:00+00:00",
        "receipts": [{"name": str(i)} for i in range(7)],
        "misses": [],
        "no_claim_rows": [{"name": str(i)} for i in range(33)],
        "summary": {
            "no_claim_call_up_count": 33,
            "maturation": {"pending": 7, "confirmed": 0, "decayed": 0},
        },
    })

    context = app_module._track_record_context()

    assert context["sc"] == {"artifact": "consensus"}
    assert context["forward_sc"]["wins"] == 39
    assert context["forward_sc"]["losses"] == 31
    assert context["forward_sc"]["win_rate_pct"] == 56
    assert context["forward_sc"]["clean_retractions"] == 86
    assert context["receipt_count"] == 7
    assert context["miss_count"] == 0
    assert context["no_claim_call_up_count"] == 33


def test_track_record_context_respects_both_hold_gates(monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module, "SCOREBOARD_HOLD", True)
    monkeypatch.setattr(app_module, "RECEIPTS_HOLD", True)
    monkeypatch.setattr(app_module, "_load_scorecard_payload", lambda: {"artifact": "consensus"})
    monkeypatch.setattr(
        app_module,
        "_load_forward_scoreboard_payload",
        lambda: (_ for _ in ()).throw(AssertionError("held scoreboard was loaded")),
    )

    context = app_module._track_record_context()

    assert context["forward_sc"] is None
    assert context["receipts_available"] is False
    assert context["receipt_count"] == 0
    assert context["miss_count"] == 0
    assert context["no_claim_call_up_count"] == 0
```

- [ ] **Step 2: Run the context tests and verify RED**

Run:

```powershell
python -m pytest -q tests/test_aotc_scorecard.py -k "track_record_context"
```

Expected: both tests fail because `_track_record_context` and the two display fields do not exist.

- [ ] **Step 3: Add the minimum shared context**

Extend `_scoreboard_view()` in `app.py`:

```python
    buckets = funnel.get("buckets") or {}
    wins = funnel.get("wins")
    pool_size = headline.get("pool_size")
    win_rate_pct = (
        round(wins / pool_size * 100)
        if isinstance(wins, int) and isinstance(pool_size, int) and pool_size > 0
        else None
    )
```

Use those values in its returned mapping:

```python
        "pool_size": pool_size,
        "wins": wins,
        "win_rate_pct": win_rate_pct,
        "clean_retractions": buckets.get("clean_retraction"),
```

Add this helper beside the existing ledger loaders:

```python
def _track_record_context():
    context = {
        "sc": _load_scorecard_payload(),
        **_build_receipts_page_context(),
        "forward_sc": None,
    }
    if not SCOREBOARD_HOLD:
        payload = _load_forward_scoreboard_payload()
        context["forward_sc"] = _scoreboard_view(payload) if payload else None
    return context
```

Also make `_build_receipts_page_context()` fail closed while held:

```python
    no_claim_count = 0 if RECEIPTS_HOLD else summary.get("no_claim_call_up_count") or 0
    maturation = (
        {"pending": 0, "confirmed": 0, "decayed": 0}
        if RECEIPTS_HOLD
        else summary.get("maturation") or {"pending": 0, "confirmed": 0, "decayed": 0}
    )
```

Return `no_claim_count` and `maturation` instead of reading those values directly from `summary`. This fixes the shared source once, so no future consumer of the receipt context can leak held totals.

Update `/ledger` to use it:

```python
    return render_template("track_record.html", **_track_record_context())
```

- [ ] **Step 4: Run the context tests and verify GREEN**

Run:

```powershell
python -m pytest -q tests/test_aotc_scorecard.py -k "track_record_context"
```

Expected: `2 passed`.

- [ ] **Step 5: Commit the shared context**

```powershell
git add -- app.py tests/test_aotc_scorecard.py
git diff --cached --check
git commit -m "feat: compose track record evidence"
```

---

### Task 2: Render the unified Track Record and exact scoring rules

**Files:**
- Create: `templates/partials/_call_up_scoring_rules.html`
- Modify: `templates/track_record.html`
- Modify: `static/style.css:4638-4710`
- Test: `tests/test_aotc_scorecard.py`

**Interfaces:**
- Consumes: Task 1's `forward_sc`, existing `sc`, and existing receipt-context keys.
- Produces: three separate overview cards and a reusable, variable-free scoring-rules partial.

- [ ] **Step 1: Write failing render and disclosure tests**

Add to `tests/test_aotc_scorecard.py`:

```python
def test_track_record_explains_three_evidence_lanes_with_denominators(monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module, "SCOREBOARD_HOLD", False)
    monkeypatch.setattr(app_module, "RECEIPTS_HOLD", False)
    monkeypatch.setattr(app_module, "_load_forward_scoreboard_payload", lambda: {
        "anticipation_score": {"pool_size": 70, "provisional": True},
        "funnel": {
            "wins": 39,
            "losses": 31,
            "open": 102,
            "total_claims": 258,
            "excluded_from_pool": 188,
            "unscored_or_unclassified": 0,
            "buckets": {"clean_retraction": 86},
            "self_retraction_rate": {"retracted": 117, "total": 258, "rate": 117 / 258},
        },
        "cohorts": {"cohort_count": 4},
    })
    monkeypatch.setattr(app_module, "_load_receipts_payload", lambda: {
        "receipts": [{"name": str(i)} for i in range(7)],
        "misses": [],
        "no_claim_rows": [{"name": str(i)} for i in range(33)],
        "summary": {"no_claim_call_up_count": 33, "maturation": {"pending": 7}},
    })

    html = app_module.app.test_client().get("/ledger").data.decode("utf-8")

    assert "TRACK RECORD" in html
    assert "Forward Calls" in html
    assert "39–31 across 70 scored calls (56%)" in html
    assert "86 clean retractions" in html and "102 open" in html
    assert "Consensus Movement" in html
    assert "mature decisions" in html and "matched controls" in html
    assert "Call-Up Timing" in html
    assert "7 clearly ahead" in html and "0 clearly behind" in html
    assert "33 without a large enough ranking gap to score" in html


def test_track_record_discloses_exact_call_up_thresholds():
    from app import app
    from prospects.ahead_of_consensus import MAX_VALUCAST_RANK, MIN_BOARDS, MIN_DIVERGENCE
    from prospects.call_up_receipts import FIELD_UNRANKED_MAX_VALUCAST_RANK

    html = app.test_client().get("/ledger").data.decode("utf-8")

    assert f"at least {MIN_BOARDS} public boards" in html
    assert "inside the top 600" in html
    assert f"top {MAX_VALUCAST_RANK}" in html
    assert f"{MIN_DIVERGENCE} places" in html
    assert f"top-{FIELD_UNRANKED_MAX_VALUCAST_RANK}" in html
    assert "no scoreable ranking gap" in html
    assert "eligible prior call" not in html
```

- [ ] **Step 2: Run the render tests and verify RED**

Run:

```powershell
python -m pytest -q tests/test_aotc_scorecard.py -k "three_evidence_lanes or exact_call_up_thresholds"
```

Expected: both tests fail because the unified overview and exact rules are absent.

- [ ] **Step 3: Add the shared scoring-rules partial**

Create `templates/partials/_call_up_scoring_rules.html`:

```html
<p class="buys-fineprint">Call-ups are scored only when our archived pre-promotion ranking differed clearly from the public field.</p>
<details class="hero-fineprint-details">
    <summary class="buys-fineprint">How scoring works</summary>
    <ul class="buys-fineprint">
        <li>Consensus requires at least 2 public boards, using ranks inside the top 600.</li>
        <li>We score ahead when our rank is top 300 and at least 25 places better than consensus.</li>
        <li>We score behind when consensus is top 300 and our rank is at least 25 places worse.</li>
        <li>With fewer than 2 boards, only top-25 exceptions score: our top-25 ranking can score ahead; one public top-25 ranking can score behind when we are at least 25 places lower.</li>
    </ul>
    <p class="buys-fineprint">Everything else is a post-launch call-up with no scoreable ranking gap—not a win or a loss. Call-up timing measures arrival, not career value.</p>
</details>
```

- [ ] **Step 4: Add the three-card overview without removing the detailed consensus ledger**

In `templates/track_record.html`, rename the page title and hero to **Track Record**, keep the existing detailed consensus ledger below, and insert this overview after the hero:

```html
<section class="track-record-grid" aria-label="Track record overview">
    <article class="ledger-tile glass">
        <span class="ledger-tile-label">Forward Calls</span>
        {% if forward_sc %}
        <span class="ledger-tile-n">{{ forward_sc.wins }}–{{ forward_sc.losses }}</span>
        <strong>{{ forward_sc.wins }}–{{ forward_sc.losses }} across {{ forward_sc.pool_size }} scored calls ({{ forward_sc.win_rate_pct }}%)</strong>
        <span class="ledger-tile-sub">{{ forward_sc.clean_retractions }} clean retractions · {{ forward_sc.open }} open</span>
        {% if forward_sc.provisional %}<span class="ledger-tile-sub">Provisional: the registered expiry window has not matured.</span>{% endif %}
        <a href="/scoreboard">See every registered call</a>
        {% else %}
        <span class="ledger-tile-sub">Held or collecting; no metrics published.</span>
        {% endif %}
    </article>

    <article class="ledger-tile glass">
        <span class="ledger-tile-label">Consensus Movement</span>
        {% if sc and sc.gate.publishable and sc.summary.decided_rate is not none and sc.summary.control_lift and sc.summary.matured_open_rates and sc.summary.control_matured_rates %}
        <span class="ledger-tile-n">{{ sc.summary.wins }}/{{ sc.summary.decided_count }}</span>
        <strong>{{ sc.summary.wins }} of {{ sc.summary.decided_count }} mature decisions ({{ (sc.summary.decided_rate * 100) | round | int }}%)</strong>
        <span class="ledger-tile-sub">The public field later moved toward our different view.</span>
        <span class="ledger-tile-sub">Separate still-open comparison: {{ sc.summary.matured_open_rates.toward }}/{{ sc.summary.matured_open_rates.n }} vs {{ sc.summary.control_matured_rates.toward }}/{{ sc.summary.control_matured_rates.n }} matched controls ({{ sc.summary.control_lift }}x).</span>
        {% else %}
        <span class="ledger-tile-sub">Collecting until the registered publication gate matures.</span>
        {% endif %}
    </article>

    <article class="ledger-tile glass">
        <span class="ledger-tile-label">Call-Up Timing</span>
        {% if receipts_available %}
        <span class="ledger-tile-n">{{ receipt_count }}–{{ miss_count }}</span>
        <strong>{{ receipt_count }} clearly ahead · {{ miss_count }} clearly behind</strong>
        <span class="ledger-tile-sub">{{ no_claim_call_up_count }} without a large enough ranking gap to score</span>
        <span class="ledger-tile-sub">Maturation: {{ maturation.confirmed }} confirmed · {{ maturation.pending }} pending · {{ maturation.decayed }} decayed</span>
        {% include "partials/_call_up_scoring_rules.html" %}
        <a href="/receipts">See every call-up</a>
        {% else %}
        <span class="ledger-tile-sub">Held or collecting; no metrics published.</span>
        {% endif %}
    </article>
</section>
```

Use the existing corrected consensus copy already present in the dirty `templates/track_record.html`; do not restore the prior sentence that mixed decided calls with still-open control lift.

- [ ] **Step 5: Add only the CSS the three-card layout needs**

Add beside the ledger styles in `static/style.css`:

```css
.track-record-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: .6rem;
    margin-bottom: .9rem;
}
.track-record-grid .ledger-tile { gap: .35rem; }
.track-record-grid a { margin-top: auto; }
```

- [ ] **Step 6: Run the render tests and verify GREEN**

Run:

```powershell
python -m pytest -q tests/test_aotc_scorecard.py -k "ledger_page or three_evidence_lanes or exact_call_up_thresholds or track_record_context"
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit the page and disclosure**

```powershell
git add -- templates/track_record.html templates/partials/_call_up_scoring_rules.html static/style.css tests/test_aotc_scorecard.py
git diff --cached --check
git commit -m "feat: unify public track record"
```

---

### Task 3: Make Receipts use the same honest language

**Files:**
- Modify: `templates/receipts.html:31-42,79-81,108,123-130`
- Modify: `app.py:8875-8955`
- Test: `tests/test_call_up_receipts.py:604-725`

**Interfaces:**
- Consumes: `templates/partials/_call_up_scoring_rules.html` from Task 2 and the existing `flagged_days_early` continuous pre-call-up rank-band count.
- Produces: matching page and PNG language that describes a ValuCast archive streak, never time “before the field.”

- [ ] **Step 1: Change the existing tests to require the provable statement**

Update the lead-time assertions in `tests/test_call_up_receipts.py`:

```python
    assert "12d pre-call-up rank streak" in page
    assert "flagged 12d early" not in page
```

Update the hero assertion:

```python
    assert "Ranked Luis Lara for 24 consecutive archived days before his MLB call-up" in page
    assert "#8 here, #63 field median at promotion" in page
    assert "before the field did" not in page
```

Add this test:

```python
def test_receipts_page_reuses_exact_scoring_disclosure(monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module, "RECEIPTS_HOLD", False)
    html = app_module.app.test_client().get("/receipts").data.decode("utf-8")

    assert "at least 2 public boards" in html
    assert "top 300" in html
    assert "25 places" in html
    assert "top-25 exceptions" in html
    assert "no scoreable ranking gap" in html
```

- [ ] **Step 2: Run the receipt copy tests and verify RED**

Run:

```powershell
python -m pytest -q tests/test_call_up_receipts.py -k "flagged_days_early_when_present or hero_renders_marquee or reuses_exact_scoring"
```

Expected: the updated assertions fail against the old “before the field” and “flagged early” language.

- [ ] **Step 3: Correct the Receipts page**

Replace the marquee sentence in `templates/receipts.html` with:

```html
<p class="buys-heading-sub receipts-marquee">Ranked {{ receipts_marquee.name }} for {{ receipts_marquee.flagged_days_early }} consecutive archived day{{ 's' if receipts_marquee.flagged_days_early != 1 else '' }} before his MLB call-up &mdash; #{{ receipts_marquee.valucast_rank }} here, #{{ receipts_marquee.consensus_rank }} field median at promotion.</p>
```

Replace each row's `flagged Nd early` suffix with:

```html
{% if p.flagged_days_early %} &middot; {{ p.flagged_days_early }}d pre-call-up rank streak{% endif %}
```

Replace the current scoring `<details>` with:

```html
{% include "partials/_call_up_scoring_rules.html" %}
{% if no_claim_call_up_count %}
<p class="buys-fineprint">{{ no_claim_call_up_count }} more post-launch call-ups had no scoreable ranking gap.</p>
{% endif %}
```

Change the no-claim details introduction to:

```html
<p class="buys-fineprint">These post-launch call-ups did not meet the fixed ahead or behind thresholds.</p>
```

- [ ] **Step 4: Correct the Receipts PNG language**

In `_receipts_share_card_png()` replace:

```python
meta_parts.append(f"flagged {row['flagged_days_early']}d early")
```

with:

```python
meta_parts.append(f"{row['flagged_days_early']}d pre-call-up rank streak")
```

Replace the PNG no-claim sentence with:

```python
no_claim_line = f"{no_claim_count} post-launch call-ups had no scoreable ranking gap"
```

- [ ] **Step 5: Run receipt tests and verify GREEN**

Run:

```powershell
python -m pytest -q tests/test_call_up_receipts.py -k "page or png or marquee or no_claim"
```

Expected: all selected receipt render and PNG tests pass.

- [ ] **Step 6: Commit the aligned Receipts language**

```powershell
git add -- app.py templates/receipts.html tests/test_call_up_receipts.py
git diff --cached --check
git commit -m "fix: explain call-up receipts precisely"
```

---

### Task 4: Align the Track Record share graphic

**Files:**
- Modify: `app.py:9001-9165`
- Test: `tests/test_aotc_scorecard.py`

**Interfaces:**
- Consumes: `_track_record_context()` from Task 1.
- Produces: `_ledger_share_card_png(sc, forward_sc=None, receipts_context=None) -> bytes`, with three overview tiles and the existing newest consensus-call rows below.

- [ ] **Step 1: Write a failing share-card contract test**

Add to `tests/test_aotc_scorecard.py`:

```python
def test_track_record_share_card_uses_all_three_lanes(monkeypatch):
    import inspect
    import app as app_module

    monkeypatch.setattr(app_module, "_track_record_context", lambda: {
        "sc": app_module._load_scorecard_payload(),
        "forward_sc": {
            "wins": 39, "losses": 31, "pool_size": 70, "win_rate_pct": 56,
            "clean_retractions": 86, "open": 102, "provisional": True,
        },
        "receipts_available": True,
        "receipt_count": 7,
        "miss_count": 0,
        "no_claim_call_up_count": 33,
        "maturation": {"confirmed": 0, "pending": 7, "decayed": 0},
    })

    response = app_module.app.test_client().get("/ledger/share-card.png")
    source = inspect.getsource(app_module._ledger_share_card_png)

    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert len(response.data) > 10_000
    assert 'headline="TRACK RECORD"' in source
    assert '"FORWARD CALLS"' in source
    assert '"CONSENSUS MOVEMENT"' in source
    assert '"CALL-UP TIMING"' in source
    assert "NEWEST CONSENSUS CALLS" in source
```

- [ ] **Step 2: Run the share-card test and verify RED**

Run:

```powershell
python -m pytest -q tests/test_aotc_scorecard.py -k "share_card_uses_all_three_lanes"
```

Expected: fail because the PNG still renders only the old consensus ledger.

- [ ] **Step 3: Pass the shared context into the PNG and render three honest tiles**

Change the function signature:

```python
def _ledger_share_card_png(sc, forward_sc=None, receipts_context=None):
```

Change the header to:

```python
    _graphic_header(
        img,
        draw,
        headline="TRACK RECORD",
        subtitle="Three public evidence lanes - separate cohorts and denominators",
        extra_line="Forward calls, consensus movement, and call-up timing",
        tagline="Track Record",
    )
```

Replace the first four funnel tiles with three summary tiles. Build labels from the supplied context and use an em dash when a lane is held or unavailable:

```python
    forward_sc = forward_sc or {}
    receipts_context = receipts_context or {}
    forward_value = (
        f"{forward_sc['wins']}-{forward_sc['losses']}"
        if forward_sc.get("wins") is not None and forward_sc.get("losses") is not None
        else "-"
    )
    consensus_value = (
        f"{summary.get('wins')}/{summary.get('decided_count')}"
        if summary.get("wins") is not None and summary.get("decided_count")
        else "-"
    )
    callup_value = (
        f"{receipts_context.get('receipt_count', 0)}-{receipts_context.get('miss_count', 0)}"
        if receipts_context.get("receipts_available")
        else "-"
    )
    control = summary.get("control_matured_rates") or {}
    matured_open = summary.get("matured_open_rates") or {}
    consensus_rate = summary.get("decided_rate")
    consensus_sub = (
        f"{round(consensus_rate * 100)}% of {summary.get('decided_count')} mature"
        if consensus_rate is not None and summary.get("decided_count")
        else "collecting"
    )
    consensus_foot = (
        f"still-open {matured_open.get('toward')}/{matured_open.get('n')} vs "
        f"{control.get('toward')}/{control.get('n')} controls"
        if matured_open.get("n") and control.get("n")
        else "control comparison collecting"
    )
    tiles = [
        (forward_value, "FORWARD CALLS", f"{forward_sc.get('win_rate_pct')}% of {forward_sc.get('pool_size')} scored" if forward_sc else "held or collecting", f"{forward_sc.get('clean_retractions')} clean retractions - {forward_sc.get('open')} open" if forward_sc else "", green),
        (consensus_value, "CONSENSUS MOVEMENT", consensus_sub, consensus_foot, blue),
        (callup_value, "CALL-UP TIMING", f"{receipts_context.get('no_claim_call_up_count', 0)} no scoreable gap" if receipts_context.get("receipts_available") else "held or collecting", "arrival evidence, not career value" if receipts_context.get("receipts_available") else "", green),
    ]
```

Use three equal columns, draw `sub` and `foot` on separate lines in each tile, and rename the lower section `NEWEST CONSENSUS CALLS`. Preserve the existing consensus call rows below the overview.

Update `ledger_share_card_png()`:

```python
    context = _track_record_context()
    if not context["sc"]:
        abort(404)
    png = _ledger_share_card_png(
        context["sc"],
        context["forward_sc"],
        context,
    )
```

Update the preview title, subtitle, alt text, and filename from “The Ledger” to “Track Record”; keep `/ledger/share-card` and `/ledger/share-card.png` unchanged.

- [ ] **Step 4: Run the share-card test and verify GREEN**

Run:

```powershell
python -m pytest -q tests/test_aotc_scorecard.py -k "share_card or ledger_page"
```

Expected: all selected share-card and ledger tests pass.

- [ ] **Step 5: Commit the Track Record graphic**

```powershell
git add -- app.py tests/test_aotc_scorecard.py
git diff --cached --check
git commit -m "feat: align track record graphic"
```

---

### Task 5: Validate artifacts, regression behavior, and mobile presentation

**Files:**
- Verify only; do not modify generated artifacts.

**Interfaces:**
- Consumes: the completed page, detailed routes, share graphics, and committed artifacts.
- Produces: fresh command and browser evidence suitable for merge review.

- [ ] **Step 1: Run all three artifact validators**

```powershell
python scripts/validate_ahead_of_consensus_scorecard.py
python scripts/validate_forward_scoreboard.py
python scripts/validate_valucast_call_up_receipts.py
```

Expected: each exits `0` and reports no validation problems.

- [ ] **Step 2: Run the focused regression suite**

```powershell
python -m pytest -q tests/test_aotc_scorecard.py tests/test_forward_scoreboard_page.py tests/test_call_up_receipts.py
```

Expected: all tests pass.

- [ ] **Step 3: Run the broader app regression suite**

```powershell
python -m pytest -q tests/test_app.py
```

Expected: all tests pass.

- [ ] **Step 4: Check diff hygiene**

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors; only the pre-existing unrelated working-tree files remain outside the completed commits.

- [ ] **Step 5: Verify the rendered pages at desktop and phone widths**

Start the app in a separate PowerShell window:

```powershell
python app.py
```

Verify `/ledger` at approximately 1440×1000 and 390×844:

- the three overview cards are readable without horizontal scrolling;
- `56%` is always adjacent to `39–31 across 70 scored calls`;
- `31%` is labeled Consensus Movement and remains separate from matched controls;
- the Call-Up Timing rules expand from a keyboard-focusable summary;
- held lanes show no hidden counts;
- `/scoreboard`, `/receipts`, `/ledger/share-card`, and `/ledger/share-card.png` still render as intended.

Do not dispatch deployment or refresh workflows as part of this plan.
