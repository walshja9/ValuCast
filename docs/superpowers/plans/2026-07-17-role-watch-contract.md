# Role Watch Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct the existing role and four-year-outcome display contracts, then add a fail-closed `/role-watch` review page that remains dark by default and cannot affect rankings, values, caps, or pitcher publication.

**Architecture:** Extend the existing playing-time tracker with explicit source fields, contradiction blockers, and a pure candidate-screen helper. Flask reads that same artifact behind an environment hold and renders an HTML-only page using existing styles. Prospect outcome percentages stay unchanged; only their public labels and horizon note change.

**Tech Stack:** Python 3.10+, Flask, Jinja, pytest, existing ValuCast JSON artifacts and CSS. No new dependency or JavaScript.

**Spec:** `docs/superpowers/specs/2026-07-17-role-watch-contract-design.md`

## Global Constraints

- Preserve the model freeze and failed pitcher pedigree-decay flag.
- Do not change ranks, values, buy scores, pitcher caps, or publication decisions.
- Keep League Connect paused.
- `ROLE_WATCH_HOLD` defaults held; add no navigation or footer link.
- Do not commit a regenerated daily data artifact.
- Do not edit `.github/`, frozen forward modules/tests, or the three protected untracked files.
- Do not deploy, dispatch a workflow, push, or change a production environment variable.
- Do not dispatch workflows near 00:00 UTC; retain the existing no-push window.

---

## File Structure

- **Modify** `mlb/playing_time_role.py` — correct pitcher role classification, emit the explicit field contract and blockers, and select Role Watch rows.
- **Modify** `scripts/validate_playing_time_role_tracker.py` — validate every profile and the new contract.
- **Modify** `web/prospect_context.py` — replace career-sounding outcome labels without touching percentages.
- **Modify** `templates/partials/player_detail_dynasty.html` — publish the exact four-year outcome definition.
- **Modify** `app.py` — add the held flag and fail-closed route.
- **Create** `templates/role_watch.html` — accessible, HTML-only review page using existing front-office card classes.
- **Modify** `tests/test_playing_time_role_tracker.py` — role-contract, blocker, and candidate-screen tests.
- **Modify** `tests/test_app.py` — outcome-copy rendering assertions.
- **Create** `tests/test_role_watch_page.py` — hold, artifact-contract, suppression, and rendering tests.

No stylesheet change is planned. The page reuses `front-office-report`,
`front-office-hero`, `front-office-grid`, `front-office-card`, and their existing
mobile rules.

---

### Task 1: Correct the role contract at its shared source

**Files:**
- Modify: `tests/test_playing_time_role_tracker.py`
- Modify: `mlb/playing_time_role.py`

**Interfaces:**
- Produces: tracker profiles with `source_pool`, `starter_probability`, `projected_starts_ros`, `projected_innings_ros`, `role_context_status`, and `role_context_blockers`.
- Preserves: `projected_role`, `projected_volume`, `role_basis`, availability fields, `usage`, and all live-rank/value false guards.

- [ ] **Step 1: Write failing role-contract tests**

Append to `tests/test_playing_time_role_tracker.py`:

```python
def _role_row(*, pool="reliever", ip=60.0, gs=0.0, p_sp=0.2, mlbam_id="901"):
    return {
        "name": "Role Test Arm",
        "pool": pool,
        "team": "SEA",
        "positions": ["P"],
        "stats": {"IP": ip, "GS": gs, "SV_HLD": 0.0},
        "metadata": {"mlbam_id": mlbam_id, "p_sp": p_sp},
    }


def test_high_ip_reliever_with_zero_starts_stays_relief():
    payload = build_playing_time_role_tracker(
        projections=[_role_row(ip=70.0, gs=0.0)],
        generated_at="2026-07-17T12:00:00+00:00",
    )
    profile = payload["profiles"][0]
    assert profile["projected_role"] == "middle_relief"
    assert profile["source_pool"] == "reliever"
    assert profile["starter_probability"] == 0.2
    assert profile["projected_starts_ros"] == 0.0
    assert profile["projected_innings_ros"] == 70.0
    assert profile["role_context_status"] == "ready"
    assert profile["role_context_blockers"] == []


def test_generic_pitcher_with_starter_volume_is_rotation_starter():
    payload = build_playing_time_role_tracker(
        projections=[_role_row(pool="pitcher", ip=60.0, gs=8.0)],
        generated_at="2026-07-17T12:00:00+00:00",
    )
    assert payload["profiles"][0]["projected_role"] in {
        "rotation_starter", "rotation_workhorse"
    }


def test_projected_starts_with_zero_innings_blocks_role_context():
    payload = build_playing_time_role_tracker(
        projections=[_role_row(pool="starter", ip=0.0, gs=7.0, p_sp=0.95)],
        generated_at="2026-07-17T12:00:00+00:00",
    )
    profile = payload["profiles"][0]
    assert profile["role_context_status"] == "blocked"
    assert "projected_starts_without_innings" in profile["role_context_blockers"]


def test_invalid_probability_and_negative_volume_block_role_context():
    payload = build_playing_time_role_tracker(
        projections=[_role_row(ip=-1.0, gs=-1.0, p_sp=1.2)],
        generated_at="2026-07-17T12:00:00+00:00",
    )
    blockers = payload["profiles"][0]["role_context_blockers"]
    assert blockers == [
        "starter_probability_out_of_range",
        "negative_projected_starts",
        "negative_projected_innings",
    ]
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
py -m pytest tests/test_playing_time_role_tracker.py -q
```

Expected: the new assertions fail because the fields do not exist and the
high-IP reliever is currently labeled as a starter.

- [ ] **Step 3: Implement the minimal shared-source correction**

In `mlb/playing_time_role.py`:

1. Change `TRACKER_VERSION` from `0.1.0` to `0.2.0`.
2. Replace the starter branch in `_pitcher_role` so innings alone cannot create
   starter evidence:

```python
def _pitcher_role(pool: str, stats: dict, pace: float = 1.0) -> tuple[str, float, str]:
    ip = _clean_float(stats.get("IP"))
    starts = _clean_float(stats.get("GS")) * pace
    sv_hld = (_clean_float(stats.get("SV_HLD")) or (
        _clean_float(stats.get("SV")) + _clean_float(stats.get("HLD"))
    )) * pace
    season_ip = ip * pace
    if pool == "starter" or starts >= 18:
        if season_ip >= 150 or starts >= 24:
            return "rotation_workhorse", ip, "starter volume"
        return "rotation_starter", ip, "starter-leaning volume"
    if pool == "reliever" or sv_hld >= 12:
        if sv_hld >= 22:
            return "leverage_reliever", ip, "save/hold leverage"
        return "middle_relief", ip, "relief volume"
    if season_ip >= 75:
        return "swingman_or_bulk", ip, "bulk innings"
    return "depth_arm", ip, "thin projected innings"
```

3. Add the profile-contract helper before `_row_profile`:

```python
def _role_contract_fields(row: dict) -> dict:
    pool = str(row.get("pool") or "").lower()
    if pool == "hitter":
        return {
            "source_pool": pool,
            "starter_probability": None,
            "projected_starts_ros": None,
            "projected_innings_ros": None,
            "role_context_status": "ready",
            "role_context_blockers": [],
        }
    stats = row.get("stats") or {}
    metadata = row.get("metadata") or {}
    raw_probability = metadata.get("p_sp")
    probability = _opt_float(raw_probability)
    starts = _clean_float(stats.get("GS"))
    innings = _clean_float(stats.get("IP"))
    blockers = []
    if raw_probability not in (None, "") and (
        probability is None or not 0.0 <= probability <= 1.0
    ):
        blockers.append("starter_probability_out_of_range")
    if starts < 0:
        blockers.append("negative_projected_starts")
    if innings < 0:
        blockers.append("negative_projected_innings")
    if starts >= 0.5 and innings == 0:
        blockers.append("projected_starts_without_innings")
    return {
        "source_pool": pool,
        "starter_probability": round(probability, 4) if probability is not None else None,
        "projected_starts_ros": round(starts, 4),
        "projected_innings_ros": round(innings, 1),
        "role_context_status": "blocked" if blockers else "ready",
        "role_context_blockers": blockers,
    }
```

4. In `_row_profile`, build `contract = _role_contract_fields(row)` and merge
   `**contract` into the returned profile. Leave all existing fields intact.

- [ ] **Step 4: Run the focused tests and verify GREEN**

```powershell
py -m pytest tests/test_playing_time_role_tracker.py -q
```

Expected: all playing-time role tests pass.

- [ ] **Step 5: Commit Task 1**

```powershell
git add mlb/playing_time_role.py tests/test_playing_time_role_tracker.py
git commit -m "fix: make pitcher role context evidence-led"
```

---

### Task 2: Make the artifact validator enforce the full contract

**Files:**
- Modify: `tests/test_playing_time_role_tracker.py`
- Modify: `scripts/validate_playing_time_role_tracker.py`

**Interfaces:**
- Consumes: tracker v0.2.0 profiles from Task 1.
- Produces: validation errors for any malformed profile, not only the first 200.

- [ ] **Step 1: Write failing validator tests**

Append:

```python
def test_validator_checks_profiles_after_first_200(tmp_path):
    payload = build_playing_time_role_tracker(
        projections=[
            _role_row(mlbam_id=str(10_000 + index), p_sp=0.2)
            for index in range(201)
        ],
        generated_at="2026-07-17T12:00:00+00:00",
    )
    payload["profiles"][200].pop("source_pool")
    path = tmp_path / "role.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    _, problems = validate_playing_time_role_tracker(path)
    assert any("profile 201 missing source_pool" in problem for problem in problems)


def test_validator_rejects_incoherent_status_and_blockers(tmp_path):
    payload = build_playing_time_role_tracker(
        projections=[_role_row()],
        generated_at="2026-07-17T12:00:00+00:00",
    )
    payload["profiles"][0]["role_context_status"] = "ready"
    payload["profiles"][0]["role_context_blockers"] = ["contradiction"]
    path = tmp_path / "role.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    _, problems = validate_playing_time_role_tracker(path)
    assert any("ready profile has blockers" in problem for problem in problems)
```

- [ ] **Step 2: Run and verify RED**

```powershell
py -m pytest tests/test_playing_time_role_tracker.py::test_validator_checks_profiles_after_first_200 tests/test_playing_time_role_tracker.py::test_validator_rejects_incoherent_status_and_blockers -q
```

Expected: both tests fail against the current first-200 validator and absent
contract checks.

- [ ] **Step 3: Extend the existing validation loop**

In `scripts/validate_playing_time_role_tracker.py`:

- Change `for index, row in enumerate(profiles[:200], 1):` to
  `for index, row in enumerate(profiles, 1):`.
- Require key presence for the new fields:

```python
for field in (
    "source_pool",
    "starter_probability",
    "projected_starts_ros",
    "projected_innings_ros",
    "role_context_status",
    "role_context_blockers",
):
    if field not in row:
        problems.append(f"profile {index} missing {field}")
```

- Add coherence checks:

```python
probability = row.get("starter_probability")
if probability is not None and (
    not isinstance(probability, (int, float)) or not 0.0 <= probability <= 1.0
):
    problems.append(f"profile {index} invalid starter_probability")
status = row.get("role_context_status")
blockers = row.get("role_context_blockers")
if status not in {"ready", "blocked"}:
    problems.append(f"profile {index} invalid role_context_status")
if not isinstance(blockers, list):
    problems.append(f"profile {index} role_context_blockers must be a list")
elif status == "ready" and blockers:
    problems.append(f"profile {index} ready profile has blockers")
elif status == "blocked" and not blockers:
    problems.append(f"profile {index} blocked profile has no blockers")
```

- Keep every existing source-policy, v2, identity, and usage check.

- [ ] **Step 4: Run focused validation tests**

```powershell
py -m pytest tests/test_playing_time_role_tracker.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 2**

```powershell
git add scripts/validate_playing_time_role_tracker.py tests/test_playing_time_role_tracker.py
git commit -m "test: enforce role tracker contract across every profile"
```

---

### Task 3: Add the pure Role Watch opportunity screen

**Files:**
- Modify: `tests/test_playing_time_role_tracker.py`
- Modify: `mlb/playing_time_role.py`

**Interfaces:**
- Produces: `role_watch_rows(profiles: list[dict]) -> list[dict]`.
- The returned row adds only `opportunity_explanation`; it does not mutate input.

- [ ] **Step 1: Write failing candidate-screen tests**

Add `role_watch_rows` to the test import and append:

```python
def _watch_profile(**overrides):
    profile = {
        "name": "Opportunity Arm",
        "source_pool": "reliever",
        "starter_probability": 0.42,
        "projected_starts_ros": 2.0,
        "projected_innings_ros": 30.0,
        "active_mlb_roster": True,
        "active_injury_risk": False,
        "availability_status": "active_mlb_roster",
        "role_context_status": "ready",
        "role_context_blockers": [],
    }
    profile.update(overrides)
    return profile


def test_role_watch_includes_only_explainable_active_opportunity():
    rows = role_watch_rows([_watch_profile()])
    assert len(rows) == 1
    assert "2.0 starts and 30.0 innings" in rows[0]["opportunity_explanation"]
    assert "42%" in rows[0]["opportunity_explanation"]


def test_role_watch_suppresses_injury_inactive_noise_and_blockers():
    rows = role_watch_rows([
        _watch_profile(name="Injured", active_injury_risk=True),
        _watch_profile(name="Inactive", active_mlb_roster=False),
        _watch_profile(name="Unknown", availability_status="unknown"),
        _watch_profile(name="Fractional", projected_starts_ros=0.9),
        _watch_profile(name="No innings", projected_innings_ros=0.0),
        _watch_profile(name="No probability", starter_probability=None),
        _watch_profile(name="Blocked", role_context_status="blocked",
                       role_context_blockers=["contradiction"]),
        _watch_profile(name="Starter pool", source_pool="starter"),
    ])
    assert rows == []


def test_role_watch_orders_by_projected_starts_then_name_without_mutation():
    profiles = [
        _watch_profile(name="Zulu", projected_starts_ros=2.0),
        _watch_profile(name="Alpha", projected_starts_ros=2.0),
        _watch_profile(name="First", projected_starts_ros=3.0),
    ]
    rows = role_watch_rows(profiles)
    assert [row["name"] for row in rows] == ["First", "Alpha", "Zulu"]
    assert all("opportunity_explanation" not in row for row in profiles)
```

- [ ] **Step 2: Run and verify RED**

```powershell
py -m pytest tests/test_playing_time_role_tracker.py -q
```

Expected: import failure because `role_watch_rows` does not exist.

- [ ] **Step 3: Implement the screen in the existing module**

Add to `mlb/playing_time_role.py`:

```python
ROLE_WATCH_EXCLUDED_STATUSES = {
    "injured", "rehab", "inactive", "stale_or_inactive", "unknown", ""
}


def role_watch_rows(profiles: list[dict]) -> list[dict]:
    rows = []
    for profile in profiles:
        status = str(profile.get("availability_status") or "").strip().lower()
        probability = _opt_float(profile.get("starter_probability"))
        starts = _clean_float(profile.get("projected_starts_ros"))
        innings = _clean_float(profile.get("projected_innings_ros"))
        if (
            profile.get("source_pool") != "reliever"
            or profile.get("role_context_status") != "ready"
            or profile.get("active_mlb_roster") is not True
            or profile.get("active_injury_risk") is True
            or status in ROLE_WATCH_EXCLUDED_STATUSES
            or probability is None
            or starts < 1.0
            or innings <= 0.0
        ):
            continue
        row = dict(profile)
        row["opportunity_explanation"] = (
            f"Projected for {starts:.1f} starts and {innings:.1f} innings the rest "
            f"of the season while the source role remains relief. Starter "
            f"probability is {probability:.0%}. Roster status is "
            f"{status.replace('_', ' ')}."
        )
        rows.append(row)
    return sorted(
        rows,
        key=lambda row: (
            -_clean_float(row.get("projected_starts_ros")),
            str(row.get("name") or "").casefold(),
        ),
    )
```

- [ ] **Step 4: Run focused tests and verify GREEN**

```powershell
py -m pytest tests/test_playing_time_role_tracker.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 3**

```powershell
git add mlb/playing_time_role.py tests/test_playing_time_role_tracker.py
git commit -m "feat: derive explainable role watch opportunities"
```

---

### Task 4: Correct the four-year prospect outcome language

**Files:**
- Modify: `tests/test_app.py`
- Modify: `web/prospect_context.py`
- Modify: `templates/partials/player_detail_dynasty.html`

**Interfaces:**
- Preserves: `outcome_mix(signal)` signature and percentage partition.
- Changes only the three public labels and explanatory note.

- [ ] **Step 1: Change the helper test first**

In `tests/test_app.py::TestOutcomeMixHelper`, replace the old label assertions
and add the negative assertions:

```python
labels = [segment["label"] for segment in segs]
self.assertEqual(
    labels,
    ["Impact season", "Established MLB role", "Not established by Year 4"],
)
self.assertNotIn("Star ceiling", labels)
self.assertNotIn("Everyday role", labels)
self.assertNotIn("Bust risk", labels)
```

In `TestProspectAttributionPanel.test_panel_renders_high_on_prospect_card`, add:

```python
self.assertIn("Four-year MLB outlook", body)
self.assertIn("not a career verdict", body)
self.assertNotIn("Bust risk", body)
```

- [ ] **Step 2: Run and verify RED**

```powershell
py -m pytest tests/test_app.py::TestOutcomeMixHelper tests/test_app.py::TestProspectAttributionPanel::test_panel_renders_high_on_prospect_card -q
```

Expected: failures show the old labels and old template note.

- [ ] **Step 3: Replace labels and note without touching math**

In `web/prospect_context.py::outcome_mix`, replace only `raw`:

```python
raw = [
    ("star", "Impact season", "signal", star),
    ("everyday", "Established MLB role", "slate", everyday),
    ("bust", "Not established by Year 4", "clay", bust),
]
```

Update the helper docstring to call the three buckets `Impact season / Established
MLB role / Not established by Year 4`.

In `templates/partials/player_detail_dynasty.html`, replace the existing
`attribution-mix-note` paragraph with:

```html
<p class="attribution-mix-note">Four-year MLB outlook. &ldquo;Not established&rdquo;
means no applicable 300-PA hitter or 50-IP pitcher season within four years
&mdash; not a career verdict.</p>
```

- [ ] **Step 4: Run focused tests and verify GREEN**

```powershell
py -m pytest tests/test_app.py::TestOutcomeMixHelper tests/test_app.py::TestProspectAttributionPanel::test_panel_renders_high_on_prospect_card -q
```

Expected: all selected tests pass and percentages still total 100.

- [ ] **Step 5: Commit Task 4**

```powershell
git add web/prospect_context.py templates/partials/player_detail_dynasty.html tests/test_app.py
git commit -m "fix: describe prospect outcomes as four-year establishment"
```

---

### Task 5: Add the held, fail-closed Role Watch page

**Files:**
- Create: `tests/test_role_watch_page.py`
- Modify: `app.py`
- Create: `templates/role_watch.html`

**Interfaces:**
- Consumes: tracker version `0.2.0`, ready validation, false rank/value feed flags, and `role_watch_rows`.
- Produces: `GET /role-watch`, 404 while held or artifact-invalid.

- [ ] **Step 1: Write failing route tests**

Create `tests/test_role_watch_page.py`:

```python
import json

import pytest

import app as app_module
from app import app
from mlb.playing_time_role import TRACKER_VERSION


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


def _payload():
    return {
        "artifact": "valucast_playing_time_role_tracker",
        "tracker_version": TRACKER_VERSION,
        "generated_at": "2026-07-17T12:00:00+00:00",
        "source_policy": {"feeds_live_rank": False, "feeds_live_value": False},
        "validation": {"ready_for_role_context": True},
        "profiles": [
            {
                "name": "Opportunity Arm",
                "team": "SEA",
                "source_pool": "reliever",
                "starter_probability": 0.42,
                "projected_starts_ros": 2.0,
                "projected_innings_ros": 30.0,
                "active_mlb_roster": True,
                "active_injury_risk": False,
                "availability_status": "active_mlb_roster",
                "role_context_status": "ready",
                "role_context_blockers": [],
            },
            {
                "name": "Injured Arm",
                "team": "BOS",
                "source_pool": "reliever",
                "starter_probability": 0.45,
                "projected_starts_ros": 3.0,
                "projected_innings_ros": 35.0,
                "active_mlb_roster": True,
                "active_injury_risk": True,
                "availability_status": "injured",
                "role_context_status": "ready",
                "role_context_blockers": [],
            },
        ],
    }


def _serve(monkeypatch, tmp_path, payload):
    path = tmp_path / "role.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(app_module, "ROLE_WATCH_HOLD", False)
    monkeypatch.setattr(app_module, "_ROLE_WATCH_ARTIFACT_PATH", path)
    app_module._ARTIFACT_CACHE.clear()


def test_role_watch_held_returns_404(client, monkeypatch):
    monkeypatch.setattr(app_module, "ROLE_WATCH_HOLD", True)
    assert client.get("/role-watch").status_code == 404


@pytest.mark.parametrize("mutation", ["version", "ready", "rank", "value"])
def test_role_watch_invalid_contract_returns_404(client, monkeypatch, tmp_path, mutation):
    payload = _payload()
    if mutation == "version":
        payload["tracker_version"] = "old"
    elif mutation == "ready":
        payload["validation"]["ready_for_role_context"] = False
    elif mutation == "rank":
        payload["source_policy"]["feeds_live_rank"] = True
    else:
        payload["source_policy"]["feeds_live_value"] = True
    _serve(monkeypatch, tmp_path, payload)
    assert client.get("/role-watch").status_code == 404


def test_role_watch_renders_only_eligible_explainable_rows(client, monkeypatch, tmp_path):
    _serve(monkeypatch, tmp_path, _payload())
    response = client.get("/role-watch")
    assert response.status_code == 200
    body = response.data.decode("utf-8")
    assert "ROLE WATCH · PRIVATE REVIEW" in body
    assert "Projected opportunity, not a conversion grade" in body
    assert "Opportunity Arm" in body
    assert "2.0 starts and 30.0 innings" in body
    assert "Injured Arm" not in body
    assert "cannot affect rankings, values, caps, or publication decisions" in body


def test_role_watch_has_no_site_navigation_link(client):
    body = client.get("/").data.decode("utf-8")
    assert 'href="/role-watch"' not in body
```

- [ ] **Step 2: Run and verify RED**

```powershell
py -m pytest tests/test_role_watch_page.py -q
```

Expected: collection or attribute failures because the flag, path, route, and
template do not exist.

- [ ] **Step 3: Add the fail-closed Flask wiring**

In `app.py`, import:

```python
from mlb.playing_time_role import TRACKER_VERSION as ROLE_TRACKER_VERSION
from mlb.playing_time_role import role_watch_rows
```

After `SCOREBOARD_HOLD`, add:

```python
ROLE_WATCH_HOLD = _env_flag_held("ROLE_WATCH_HOLD")
_ROLE_WATCH_ARTIFACT_PATH = (
    Path(__file__).parent / "data" / "models" / "valucast_playing_time_role_tracker.json"
)
```

Add the route near the existing intelligence/role context pages:

```python
@app.route("/role-watch")
def role_watch():
    if ROLE_WATCH_HOLD:
        abort(404)
    payload = _load_artifact(_ROLE_WATCH_ARTIFACT_PATH)
    policy = (payload or {}).get("source_policy") or {}
    validation = (payload or {}).get("validation") or {}
    profiles = (payload or {}).get("profiles")
    if (
        (payload or {}).get("tracker_version") != ROLE_TRACKER_VERSION
        or validation.get("ready_for_role_context") is not True
        or policy.get("feeds_live_rank") is not False
        or policy.get("feeds_live_value") is not False
        or not isinstance(profiles, list)
    ):
        abort(404)
    rows = role_watch_rows(profiles)
    return render_template(
        "role_watch.html",
        rows=rows,
        generated_at=payload.get("generated_at"),
    )
```

Do not add the flag to the global navigation context because no template may link
to the held route.

- [ ] **Step 4: Add the HTML-only page using existing classes**

Create `templates/role_watch.html`:

```html
{% extends "base.html" %}
{% block title %}Role Watch · Private Review | ValuCast{% endblock %}
{% block content %}
{% from "partials/_editorial_date.html" import editorial_date %}
<article class="front-office-report">
    <div class="topline">
        <h2>Role Watch</h2>
        <a href="/" class="back">&larr; Back to board</a>
    </div>

    <section class="front-office-hero glass">
        <div>
            <span class="eyebrow">ROLE WATCH · PRIVATE REVIEW</span>
            <h3>Projected opportunity, not a conversion grade</h3>
            <p>Players appear only when the current projection includes at least one
            rest-of-season start, positive innings, and active healthy roster context.</p>
            {% if generated_at %}<p class="front-office-status">Updated {{ editorial_date(generated_at) }}</p>{% endif %}
        </div>
        <div class="front-office-score">
            <span>{{ rows | length }}</span>
            <small>eligible pitchers</small>
        </div>
    </section>

    {% if rows %}
    <section class="front-office-grid" aria-label="Role Watch candidates">
        {% for row in rows %}
        <article class="front-office-card glass">
            <div class="front-office-card-head">
                <h3>{{ row.name }}</h3>
                <span>{{ row.team or "—" }}</span>
            </div>
            <p class="front-office-status">Opportunity order, not player quality</p>
            <dl>
                <div><dt>Source role</dt><dd>Relief</dd></div>
                <div><dt>Projected starts</dt><dd>{{ "%.1f" | format(row.projected_starts_ros) }}</dd></div>
                <div><dt>Projected innings</dt><dd>{{ "%.1f" | format(row.projected_innings_ros) }}</dd></div>
                <div><dt>Starter probability</dt><dd>{{ "%.0f%%" | format(row.starter_probability * 100) }}</dd></div>
                <div><dt>Roster context</dt><dd>{{ row.availability_status | replace("_", " ") | title }}</dd></div>
            </dl>
            <p>{{ row.opportunity_explanation }}</p>
        </article>
        {% endfor %}
    </section>
    {% else %}
    <section class="front-office-watchlist glass" role="status">
        <strong>No pitchers meet the current evidence gate.</strong>
        <p class="front-office-progress">Role Watch does not fill an empty list with weaker evidence.</p>
    </section>
    {% endif %}

    <section class="front-office-watchlist glass">
        <strong>Display-only contract.</strong>
        <p class="front-office-progress">Role Watch cannot affect rankings, values,
        caps, or publication decisions.</p>
    </section>
</article>
{% endblock %}
```

- [ ] **Step 5: Run route tests and verify GREEN**

```powershell
py -m pytest tests/test_role_watch_page.py -q
```

Expected: all route tests pass.

- [ ] **Step 6: Run the focused cross-surface tests**

```powershell
py -m pytest tests/test_role_watch_page.py tests/test_playing_time_role_tracker.py tests/test_app.py::TestOutcomeMixHelper tests/test_app.py::TestProspectAttributionPanel -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit Task 5**

```powershell
git add app.py templates/role_watch.html tests/test_role_watch_page.py
git commit -m "feat: add held role watch review page"
```

---

### Task 6: Verify the current artifact contract and the whole application

**Files:**
- No planned source changes.
- Do not stage `data/models/valucast_playing_time_role_tracker.json` or its archive.

**Interfaces:**
- Verifies every requirement from the design spec against current source data and browser output.

- [ ] **Step 1: Run the complete automated suite**

```powershell
py -m pytest -q
```

Expected: zero failures.

- [ ] **Step 2: Build and validate a temporary current-data artifact**

```powershell
$reviewRoot = Join-Path $env:TEMP 'valucast-role-watch-review'
New-Item -ItemType Directory -Force $reviewRoot | Out-Null
$env:ROLE_WATCH_REVIEW_ARTIFACT = Join-Path $reviewRoot 'role.json'
$env:ROLE_WATCH_REVIEW_ARCHIVE = Join-Path $reviewRoot 'archive'
@'
import os
from pathlib import Path
from mlb.playing_time_role import run_playing_time_role_tracker
from scripts.validate_playing_time_role_tracker import validate_playing_time_role_tracker

artifact = Path(os.environ["ROLE_WATCH_REVIEW_ARTIFACT"])
result = run_playing_time_role_tracker(
    artifact_path=artifact,
    archive_dir=Path(os.environ["ROLE_WATCH_REVIEW_ARCHIVE"]),
)
_, problems = validate_playing_time_role_tracker(artifact)
assert result["ready_for_role_context"] is True
assert problems == [], problems
print(result)
'@ | py -
```

Expected: `ready_for_role_context=True`, no validation problems, and all writes
remain under `%TEMP%\valucast-role-watch-review`.

- [ ] **Step 3: Inspect the real-player acceptance matrix from the temporary build**

Run this read-only script against the temporary payload:

```powershell
@'
import json
import os
from pathlib import Path
from mlb.playing_time_role import role_watch_rows

payload = json.loads(Path(os.environ["ROLE_WATCH_REVIEW_ARTIFACT"]).read_text(encoding="utf-8"))
by_name = {row["name"]: row for row in payload["profiles"]}
watch_rows = role_watch_rows(payload["profiles"])
assert by_name["Tyler Holton"]["projected_role"] == "middle_relief"
assert by_name["Tyler Alexander"]["projected_role"] == "middle_relief"
assert by_name["Tyler Wells"]["role_context_status"] == "blocked"
assert "projected_starts_without_innings" in by_name["Tyler Wells"]["role_context_blockers"]
assert all(row["name"] not in {"Evan Sisk", "Jakob Junis"} for row in watch_rows)
print({"candidate_count": len(watch_rows), "candidates": [row["name"] for row in watch_rows]})
'@ | py -
```

Expected: every assertion passes. If current source data changed, report the exact
new fields instead of weakening the gate.

- [ ] **Step 4: Verify frozen outputs did not change**

```powershell
git diff --exit-code master -- prospects/model.py prospects/rank_v1.py data/models/valucast_prospect_rank_v1.json data/public/public_dynasty_snapshot.json
git diff --name-only master...HEAD
```

Expected: the first command exits zero. The second lists only the approved source,
template, test, spec, and plan files.

- [ ] **Step 5: Start a local held instance and verify 404**

In a separate terminal, run the app with `ROLE_WATCH_HOLD` unset:

```powershell
Remove-Item Env:ROLE_WATCH_HOLD -ErrorAction SilentlyContinue
@'
import app as app_module
app_module.app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
'@ | py -
```

Then verify from the working terminal:

```powershell
Invoke-WebRequest -Uri http://127.0.0.1:5000/role-watch -SkipHttpErrorCheck | Select-Object StatusCode
```

Expected: status 404.

- [ ] **Step 6: Start a local review instance with the temporary v0.2 artifact**

Set `ROLE_WATCH_HOLD=0`, launch the app against the temporary artifact, and use
the browser to verify:

```powershell
$env:ROLE_WATCH_HOLD = '0'
@'
import os
from pathlib import Path
import app as app_module

app_module._ROLE_WATCH_ARTIFACT_PATH = Path(os.environ["ROLE_WATCH_REVIEW_ARTIFACT"])
app_module.app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
'@ | py -
```

Run this in a background terminal process so the browser can connect, then verify:

- desktop layout;
- 390px mobile layout;
- visible keyboard focus;
- candidate and empty states;
- no horizontal overflow;
- complete explanation on every row;
- no navigation/footer link;
- Wells absent;
- injured/inactive players absent.

Expected: all checks pass. Capture screenshots for review but do not commit them.

- [ ] **Step 7: Final repository audit**

```powershell
git diff --check master...HEAD
git status --short
git log --oneline --decorate master..HEAD
```

Expected: no whitespace errors; only the three known protected untracked files
remain; implementation commits are present locally. Do not push or deploy.

---

## Review Checkpoints

1. After Task 1: confirm Holton/Alexander are corrected and Wells is blocked.
2. After Task 3: review the candidate count and explanations; do not loosen the
   1.0-start or availability gates merely to increase the list.
3. After Task 4: inspect one hitter and one pitcher card to ensure the new horizon
   wording is readable and the percentages did not move.
4. After Task 5: review the private page at desktop and mobile widths.
5. After Task 6: stop. Merge, push, deployment, nightly observation, and the
   `ROLE_WATCH_HOLD=0` flip require separate authorization.
