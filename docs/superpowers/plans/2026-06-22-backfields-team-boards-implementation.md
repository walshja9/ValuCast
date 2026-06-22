# Backfields Team Boards Implementation Plan

> For Alex or the next implementation agent: REQUIRED SUB-SKILL: Use `test-driven-development` before writing production code. Use `verification-before-completion` before claiming done. If executing in a fresh branch/worktree, use `using-git-worktrees` first.

## Goal

Make Backfields the single public prospect hub by adding MLB organization Team Boards and shareable Top 10 / Top 20 organization graphics, while demoting duplicate top-nav destinations.

The implementation must preserve these product rules:

- Backfields is the public prospect destination.
- `Buys` and `Scouting` remain live routes, but are not primary top-nav peers.
- Team Boards group by canonical MLB org from `row.team`.
- MiLB affiliate is display-only via `context.stat_line_team`.
- Team Boards source the full prospect pool, not the current top-200 Backfields slice.
- Share graphics use the current app-export visual system: no headshots, no team-color flood, neutral base, teal values, clay declines, slate labels.

## Current State

Files already in place:

- `app.py`
  - `/backfields` route exists.
  - `_build_backfields_page_context()` exists and builds rankings, risers, callups, stats, scouting feed.
  - `_prospect_rows()` returns only the top 200 public-board rows.
  - `affiliate_for(row)` inside `_build_backfields_page_context()` uses `context.stat_line_team` and is display-only.
  - Existing share-card helpers exist: `_graphic_header`, `_graphic_footer`, `_graphic_fill_background`, `_graphic_font`, `_draw_buys_spark`, `_buys_share_card_png`, `_value_map_share_card_png`, `_prospect_graphic_png`.
- `templates/backfields.html`
  - Warm Backfields page exists.
  - Rankings, Ahead of the Curve, Call-Up Desk, Stats, and scouting feed exist.
  - Several links already use player detail/report URLs.
- `templates/base.html`
  - Primary nav still includes `/buys` and `/scouting`.
- `tests/test_backfields_page.py`
  - Existing Backfields coverage exists and should be extended.

## Task 1 - Demote Duplicate Top-Nav Destinations

### Red Test

Edit `tests/test_backfields_page.py`.

Add:

```python
def test_primary_nav_uses_backfields_as_prospect_hub(client):
    response = client.get("/")
    html = response.get_data(as_text=True)
    nav_start = html.index('<nav class="site-nav"')
    nav_end = html.index("</nav>", nav_start)
    nav_html = html[nav_start:nav_end]

    assert 'href="/backfields"' in nav_html
    assert 'href="/buys"' not in nav_html
    assert 'href="/scouting"' not in nav_html


def test_backfields_keeps_buys_and_scouting_as_deep_links(client):
    response = client.get("/backfields")
    html = response.get_data(as_text=True)

    assert 'href="/buys"' in html
    assert 'href="/scouting' in html
```

Run:

```bash
python -m pytest tests/test_backfields_page.py -k "primary_nav_uses_backfields_as_prospect_hub or keeps_buys_and_scouting" -q
```

Expected before implementation: first test fails because `/buys` and `/scouting` are in primary nav. Second test may fail if `/buys` has no Backfields deep link.

### Implementation

Edit `templates/base.html`.

Remove these primary-nav anchors:

```html
<a href="/buys" class="{{ 'current' if request.path.startswith('/buys') else '' }}">Buys</a>
<a href="/scouting" class="{{ 'current' if request.path.startswith('/scouting') else '' }}">Scouting</a>
```

Keep:

```html
<a href="/backfields" class="{{ 'current' if request.path.startswith('/backfields') else '' }}">Backfields</a>
```

Edit `templates/backfields.html`.

Inside the Ahead of the Curve section header, add a deep link:

```html
<a class="bf-section-link" href="/buys">Open full buys board</a>
```

Inside the scouting reports section header, keep or add:

```html
<a class="bf-section-link" href="/scouting">Open scouting reports</a>
```

If `.bf-section-link` does not already exist in the inline Backfields CSS, add:

```css
.bf-section-link {
  color: var(--bf-signal);
  font: 700 0.78rem/1 var(--font-mono);
  letter-spacing: 0.04em;
  text-decoration: none;
}

.bf-section-link:hover,
.bf-section-link:focus {
  text-decoration: underline;
}
```

### Verify

```bash
python -m pytest tests/test_backfields_page.py -k "primary_nav_uses_backfields_as_prospect_hub or keeps_buys_and_scouting" -q
```

Expected: 2 passed.

## Task 2 - Add Canonical Org Helpers

### Red Test

Edit `tests/test_backfields_page.py`.

Add:

```python
def test_team_board_org_normalization():
    assert app_module._canonical_team_board_org("KC") == "KC"
    assert app_module._canonical_team_board_org("KCR") == "KC"
    assert app_module._canonical_team_board_org("kcr") == "KC"
    assert app_module._canonical_team_board_org("ATH") == "ATH"
    assert app_module._canonical_team_board_org("FA") is None
    assert app_module._canonical_team_board_org("") is None
    assert app_module._canonical_team_board_org(None) is None
```

Run:

```bash
python -m pytest tests/test_backfields_page.py -k "team_board_org_normalization" -q
```

Expected before implementation: fails because helper does not exist.

### Implementation

Edit `app.py`.

Add near other Backfields/prospect helpers:

```python
_TEAM_BOARD_ORG_ALIASES = {
    "KCR": "KC",
}

_TEAM_BOARD_EXCLUDED_ORGS = {"FA"}

_TEAM_BOARD_ORG_NAMES = {
    "ARI": "Arizona Diamondbacks",
    "ATH": "Athletics",
    "ATL": "Atlanta Braves",
    "BAL": "Baltimore Orioles",
    "BOS": "Boston Red Sox",
    "CHC": "Chicago Cubs",
    "CHW": "Chicago White Sox",
    "CIN": "Cincinnati Reds",
    "CLE": "Cleveland Guardians",
    "COL": "Colorado Rockies",
    "DET": "Detroit Tigers",
    "HOU": "Houston Astros",
    "KC": "Kansas City Royals",
    "LAA": "Los Angeles Angels",
    "LAD": "Los Angeles Dodgers",
    "MIA": "Miami Marlins",
    "MIL": "Milwaukee Brewers",
    "MIN": "Minnesota Twins",
    "NYM": "New York Mets",
    "NYY": "New York Yankees",
    "PHI": "Philadelphia Phillies",
    "PIT": "Pittsburgh Pirates",
    "SDP": "San Diego Padres",
    "SEA": "Seattle Mariners",
    "SFG": "San Francisco Giants",
    "STL": "St. Louis Cardinals",
    "TBR": "Tampa Bay Rays",
    "TEX": "Texas Rangers",
    "TOR": "Toronto Blue Jays",
    "WSN": "Washington Nationals",
}


def _canonical_team_board_org(value: object) -> str | None:
    code = str(value or "").strip().upper()
    if not code:
        return None
    code = _TEAM_BOARD_ORG_ALIASES.get(code, code)
    if code in _TEAM_BOARD_EXCLUDED_ORGS:
        return None
    return code


def _team_board_org_name(org: str) -> str:
    return _TEAM_BOARD_ORG_NAMES.get(org, org)
```

### Verify

```bash
python -m pytest tests/test_backfields_page.py -k "team_board_org_normalization" -q
```

Expected: 1 passed.

## Task 3 - Source Team Boards From Full Prospect Pool

### Red Test

Edit `tests/test_backfields_page.py`.

Add:

```python
from types import SimpleNamespace


def _row(name, team, prospect_rank=None, dynasty_rank=None, value=0):
    return SimpleNamespace(
        id=name.lower().replace(" ", "-"),
        mlbam_id=None,
        name=name,
        team=team,
        position="SS",
        level="AA",
        prospect_rank=prospect_rank,
        dynasty_rank=dynasty_rank,
        dynasty_value=value,
        value=value,
        age=20,
        eta=2027,
        context={},
        source_ranks={},
    )


def test_team_board_pool_uses_full_prospect_pool_not_top_200_slice():
    rows = [
        _row("Top Public", "BOS", prospect_rank=1, dynasty_rank=1, value=60),
        _row("Deep Prospect", "BOS", prospect_rank=650, dynasty_rank=650, value=12),
    ]

    ordered = app_module._team_board_prospect_rows(rows)

    assert [row.name for row in ordered] == ["Top Public", "Deep Prospect"]
    assert len(ordered) == 2


def test_team_board_sort_places_ranked_rows_before_fallback_rows():
    rows = [
        _row("Dynasty Only", "BOS", prospect_rank=None, dynasty_rank=20, value=20),
        _row("Ranked Prospect", "BOS", prospect_rank=5, dynasty_rank=50, value=50),
    ]

    ordered = app_module._team_board_prospect_rows(rows)

    assert [row.name for row in ordered] == ["Ranked Prospect", "Dynasty Only"]
```

Run:

```bash
python -m pytest tests/test_backfields_page.py -k "team_board_pool_uses_full_prospect_pool or team_board_sort_places" -q
```

Expected before implementation: fails because helper does not exist.

### Implementation

Edit `app.py`.

Add:

```python
def _rank_sort_value(value: object, fallback: int = 10_000_000) -> int:
    try:
        if value is None:
            return fallback
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _team_board_prospect_sort_key(row: object) -> tuple[int, int, int, str]:
    prospect_rank = getattr(row, "prospect_rank", None)
    dynasty_rank = getattr(row, "dynasty_rank", None)
    has_prospect_rank = 0 if prospect_rank is not None else 1
    return (
        has_prospect_rank,
        _rank_sort_value(prospect_rank),
        _rank_sort_value(dynasty_rank),
        str(getattr(row, "name", "") or "").lower(),
    )


def _team_board_prospect_rows(rows: list[object] | None = None) -> list[object]:
    source_rows = list(rows) if rows is not None else list(dd_store.filter(pool="prospect"))
    return sorted(source_rows, key=_team_board_prospect_sort_key)
```

Do not call `_prospect_rows()` from Team Boards. `_prospect_rows()` remains a top-200 board helper.

### Verify

```bash
python -m pytest tests/test_backfields_page.py -k "team_board_pool_uses_full_prospect_pool or team_board_sort_places" -q
```

Expected: 2 passed.

## Task 4 - Build Shared Team Board Context

### Red Test

Edit `tests/test_backfields_page.py`.

Add:

```python
def test_team_board_context_groups_by_mlb_org_not_affiliate(monkeypatch):
    rows = [
        _row("Portland Guy", "BOS", prospect_rank=1, dynasty_rank=1, value=60),
        _row("Worcester Guy", "BOS", prospect_rank=2, dynasty_rank=2, value=55),
        _row("Kansas City Guy", "KCR", prospect_rank=3, dynasty_rank=3, value=50),
        _row("Free Agent Guy", "FA", prospect_rank=4, dynasty_rank=4, value=45),
    ]
    rows[0].context = {"stat_line_team": "Portland Sea Dogs"}
    rows[1].context = {"stat_line_team": "Worcester Red Sox"}
    rows[2].context = {"stat_line_team": "Omaha Storm Chasers"}

    monkeypatch.setattr(app_module, "_team_board_prospect_rows", lambda rows_arg=None: rows)

    board = app_module._build_team_board_context("BOS", limit=20)
    assert board["selected"]["org"] == "BOS"
    assert [row["name"] for row in board["rows"]] == ["Portland Guy", "Worcester Guy"]
    assert board["rows"][0]["affiliate"] == "Portland Sea Dogs"
    assert board["rows"][0]["team"] == "BOS"
    assert board["rows"][0]["org_rank"] == 1
    assert board["rows"][1]["org_rank"] == 2

    kc_board = app_module._build_team_board_context("KCR", limit=20)
    assert kc_board["selected"]["org"] == "KC"
    assert [row["name"] for row in kc_board["rows"]] == ["Kansas City Guy"]

    all_teams = {team["org"] for team in board["teams"]}
    assert "FA" not in all_teams
```

Run:

```bash
python -m pytest tests/test_backfields_page.py -k "team_board_context_groups" -q
```

Expected before implementation: fails because context helper does not exist.

### Implementation

Edit `app.py`.

Add:

```python
def _row_context(row: object) -> dict:
    context = getattr(row, "context", None)
    return context if isinstance(context, dict) else {}


def _team_board_affiliate(row: object) -> str:
    context = _row_context(row)
    return str(context.get("stat_line_team") or "").strip()


def _team_board_level(row: object) -> str:
    context = _row_context(row)
    return str(context.get("level") or getattr(row, "level", "") or "").strip()


def _team_board_position(row: object) -> str:
    positions = getattr(row, "positions", None)
    if isinstance(positions, (list, tuple)) and positions:
        return str(positions[0] or "").strip()
    return str(getattr(row, "position", "") or "").strip()


def _team_board_eta(row: object) -> str:
    eta = getattr(row, "eta", None)
    if eta in (None, "", "None"):
        return ""
    return str(eta)


def _team_board_value(row: object) -> float:
    for attr in ("dynasty_value", "value", "score"):
        raw = getattr(row, attr, None)
        try:
            if raw is not None:
                return float(raw)
        except (TypeError, ValueError):
            continue
    return 0.0


def _team_board_fmt_value(value: float) -> str:
    if value >= 50:
        return f"{value:.1f}"
    if value >= 10:
        return f"{value:.1f}"
    return f"{value:.2f}"


def _team_board_player_id(row: object) -> str:
    for attr in ("id", "player_id", "mlbam_id"):
        raw = getattr(row, attr, None)
        if raw not in (None, ""):
            return str(raw)
    return str(getattr(row, "name", "") or "").lower().replace(" ", "-")


def _team_board_player_url(row: object) -> str:
    player_id = _team_board_player_id(row)
    return f"/prospects/player/{quote(str(player_id))}"


def _team_board_report_url(row: object) -> str:
    name = str(getattr(row, "name", "") or "").strip()
    return f"/scouting?q={quote(name)}" if name else "/scouting"


def _team_board_signal_key(row: object) -> str:
    mlbam_id = getattr(row, "mlbam_id", None)
    if mlbam_id not in (None, ""):
        return f"mlbam:{mlbam_id}"
    team = str(getattr(row, "team", "") or "").upper()
    name = str(getattr(row, "name", "") or "").strip().lower()
    return f"name:{name}|team:{team}"


def _team_board_row(row: object, org_rank: int, movement_by_key: dict[str, object]) -> dict:
    value = _team_board_value(row)
    org = _canonical_team_board_org(getattr(row, "team", None)) or ""
    move = movement_by_key.get(_team_board_signal_key(row))
    move_value = None
    if isinstance(move, dict):
        move_value = move.get("rank_delta") or move.get("score_delta") or move.get("delta")
    return {
        "id": _team_board_player_id(row),
        "name": str(getattr(row, "name", "") or "").strip(),
        "url": _team_board_player_url(row),
        "detail_url": _team_board_player_url(row),
        "report_url": _team_board_report_url(row),
        "rank": getattr(row, "prospect_rank", None),
        "org_rank": org_rank,
        "team": org,
        "affiliate": _team_board_affiliate(row),
        "position": _team_board_position(row),
        "level": _team_board_level(row),
        "eta": _team_board_eta(row),
        "value": _team_board_fmt_value(value),
        "value_sort": value,
        "move": move_value,
        "has_report": True,
    }
```

Then add:

```python
def _team_board_movements() -> dict[str, object]:
    payload = _load_artifact(BASE_DIR / "data" / "models" / "valucast_recent_signal_report.json")
    movements: dict[str, object] = {}
    for item in payload.get("movers", []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict):
            continue
        mlbam_id = item.get("mlbam_id")
        team = str(item.get("team", "") or "").upper()
        name = str(item.get("name", "") or "").strip().lower()
        if mlbam_id not in (None, ""):
            movements[f"mlbam:{mlbam_id}"] = item
        if name:
            movements[f"name:{name}|team:{team}"] = item
    return movements


def _build_team_board_context(org: str | None = None, limit: int = 20) -> dict:
    movement_by_key = _team_board_movements()
    grouped: dict[str, list[object]] = {}
    for row in _team_board_prospect_rows():
        canonical_org = _canonical_team_board_org(getattr(row, "team", None))
        if canonical_org is None:
            continue
        grouped.setdefault(canonical_org, []).append(row)

    teams = [
        {
            "org": team_org,
            "name": _team_board_org_name(team_org),
            "count": len(rows),
            "url": f"/backfields/team/{team_org}",
        }
        for team_org, rows in sorted(grouped.items(), key=lambda item: _team_board_org_name(item[0]))
    ]

    selected_org = _canonical_team_board_org(org) if org else None
    selected = None
    rows_out: list[dict] = []
    if selected_org is not None:
        selected_rows = grouped.get(selected_org)
        if selected_rows is None:
            raise KeyError(selected_org)
        selected = {
            "org": selected_org,
            "name": _team_board_org_name(selected_org),
            "count": len(selected_rows),
            "url": f"/backfields/team/{selected_org}",
        }
        rows_out = [
            _team_board_row(row, org_rank=index + 1, movement_by_key=movement_by_key)
            for index, row in enumerate(selected_rows[:limit])
        ]

    return {
        "teams": teams,
        "selected": selected,
        "rows": rows_out,
        "limit": limit,
    }
```

If `quote` is not already imported, add:

```python
from urllib.parse import quote
```

If `BASE_DIR` is not the repo root in this file, use the existing root constant used by other artifact loaders.

### Verify

```bash
python -m pytest tests/test_backfields_page.py -k "team_board_context_groups" -q
```

Expected: 1 passed.

## Task 5 - Render Team Boards In Backfields

### Red Test

Edit `tests/test_backfields_page.py`.

Add:

```python
def test_backfields_exposes_team_boards_module(client):
    response = client.get("/backfields")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Team Boards" in html
    assert "/backfields/team/" in html


def test_team_board_route_serves_known_org_and_alias(client):
    page = client.get("/backfields")
    html = page.get_data(as_text=True)
    marker = 'href="/backfields/team/'
    start = html.index(marker) + len(marker)
    org = html[start : html.index('"', start)]

    response = client.get(f"/backfields/team/{org}")
    assert response.status_code == 200
    assert "Team Boards" in response.get_data(as_text=True)

    if org == "KC":
        alias_response = client.get("/backfields/team/KCR")
        assert alias_response.status_code in {200, 302, 308}


def test_unknown_team_board_returns_404(client):
    response = client.get("/backfields/team/NOTREAL")
    assert response.status_code == 404
```

Run:

```bash
python -m pytest tests/test_backfields_page.py -k "team_boards_module or team_board_route or unknown_team_board" -q
```

Expected before implementation: fails because the module and route do not exist.

### Implementation

Edit `app.py`.

In `_build_backfields_page_context()`, add Team Boards context:

```python
context["team_boards"] = _build_team_board_context()
```

If `_build_backfields_page_context()` returns a literal dict instead of mutating `context`, add this key to the returned dict:

```python
"team_boards": _build_team_board_context(),
```

Add route:

```python
@app.route("/backfields/team/<org>")
def backfields_team(org: str):
    try:
        context = _build_backfields_page_context()
        context["team_boards"] = _build_team_board_context(org, limit=20)
    except KeyError:
        abort(404)
    return render_template("backfields.html", **context)
```

If `abort` is not already imported, extend the Flask import:

```python
from flask import abort
```

Edit `templates/backfields.html`.

Add a Team Boards anchor to the in-page nav:

```html
<a href="#team-boards">Team Boards</a>
```

Add the Team Boards module after the Stats module or below the Rankings table:

```html
<section id="team-boards" class="bf-section bf-team-boards">
  <div class="bf-section-head">
    <div>
      <h2>Team Boards</h2>
      <p>Top prospects by MLB organization, sorted by ValuCast prospect order.</p>
    </div>
    {% if team_boards.selected %}
      <a class="bf-section-link" href="/backfields/team/{{ team_boards.selected.org }}/share-card">Share {{ team_boards.selected.org }} board</a>
    {% endif %}
  </div>

  <div class="bf-team-picker" aria-label="MLB organization team boards">
    {% for team in team_boards.teams %}
      <a
        href="{{ team.url }}"
        class="bf-team-pill{% if team_boards.selected and team_boards.selected.org == team.org %} is-active{% endif %}"
      >
        <span>{{ team.org }}</span>
        <small>{{ team.count }}</small>
      </a>
    {% endfor %}
  </div>

  {% if team_boards.selected %}
    <div class="bf-team-table-wrap">
      <div class="bf-team-title">
        <h3>{{ team_boards.selected.name }} Top Prospects</h3>
        <span>{{ team_boards.selected.count }} tracked</span>
      </div>
      {% if team_boards.rows %}
        <table class="bf-table bf-team-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Player</th>
              <th>Level</th>
              <th>Move</th>
              <th>Value</th>
            </tr>
          </thead>
          <tbody>
            {% for row in team_boards.rows %}
              <tr>
                <td>{{ row.org_rank }}</td>
                <td>
                  <a class="bf-player-link" href="{{ row.detail_url }}">{{ row.name }}</a>
                  <a class="bf-report-link" href="{{ row.report_url }}">Report</a>
                  <div class="bf-meta">
                    {{ row.position }}
                    {% if row.affiliate %} / {{ row.affiliate }}{% endif %}
                    {% if row.eta %} / ETA {{ row.eta }}{% endif %}
                  </div>
                </td>
                <td>{{ row.level or "-" }}</td>
                <td>
                  {% if row.move %}
                    <span class="bf-move{% if row.move < 0 %} is-down{% endif %}">
                      {{ "%+g"|format(row.move) }}
                    </span>
                  {% else %}
                    -
                  {% endif %}
                </td>
                <td class="bf-value">{{ row.value }}</td>
              </tr>
            {% endfor %}
          </tbody>
        </table>
      {% else %}
        <p class="bf-empty">No eligible prospects for this organization yet.</p>
      {% endif %}
    </div>
  {% else %}
    <p class="bf-muted">Choose an organization to open its Top 10 or Top 20 prospect board.</p>
  {% endif %}
</section>
```

Add scoped CSS:

```css
.bf-team-picker {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin: 1rem 0;
}

.bf-team-pill {
  align-items: center;
  border: 1px solid var(--bf-border);
  border-radius: 8px;
  color: var(--bf-text);
  display: inline-flex;
  gap: 0.35rem;
  min-height: 38px;
  padding: 0.45rem 0.65rem;
  text-decoration: none;
}

.bf-team-pill small {
  color: var(--bf-muted);
  font-family: var(--font-mono);
}

.bf-team-pill.is-active {
  background: rgba(200, 146, 63, 0.16);
  border-color: rgba(200, 146, 63, 0.5);
  color: var(--bf-amber);
}

.bf-team-title {
  align-items: baseline;
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  margin: 0.75rem 0;
}

.bf-team-title span,
.bf-muted,
.bf-empty {
  color: var(--bf-muted);
  font-family: var(--font-mono);
}

.bf-player-link {
  color: var(--bf-text);
  font-weight: 700;
  text-decoration: none;
}

.bf-player-link:hover,
.bf-player-link:focus {
  text-decoration: underline;
}

.bf-report-link {
  border: 1px solid var(--bf-border);
  border-radius: 4px;
  color: var(--bf-muted);
  font: 700 0.62rem/1 var(--font-mono);
  margin-left: 0.35rem;
  padding: 0.1rem 0.25rem;
  text-decoration: none;
  text-transform: uppercase;
}

.bf-meta {
  color: var(--bf-amber);
  font: 600 0.72rem/1.4 var(--font-mono);
  margin-top: 0.15rem;
}

.bf-value {
  color: var(--bf-signal);
  font: 800 1.1rem/1 var(--font-display);
  text-align: right;
}
```

### Verify

```bash
python -m pytest tests/test_backfields_page.py -k "team_boards_module or team_board_route or unknown_team_board" -q
```

Expected: 3 passed.

## Task 6 - Add Team Board Share Preview And PNG

### Red Test

Edit `tests/test_backfields_page.py`.

Add:

```python
def _first_team_org(client):
    html = client.get("/backfields").get_data(as_text=True)
    marker = 'href="/backfields/team/'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


def test_team_board_share_preview_and_png(client):
    org = _first_team_org(client)

    preview = client.get(f"/backfields/team/{org}/share-card")
    assert preview.status_code == 200
    preview_html = preview.get_data(as_text=True)
    assert "Download Top 10 PNG" in preview_html
    assert "Download Top 20 PNG" in preview_html
    assert "ValuCast prospect order" in preview_html
    assert "consensus" not in preview_html.lower()

    png = client.get(f"/backfields/team/{org}/share-card.png?n=10")
    assert png.status_code == 200
    assert png.content_type == "image/png"
    assert png.data.startswith(b"\x89PNG")

    png_20 = client.get(f"/backfields/team/{org}/share-card.png?n=20")
    assert png_20.status_code == 200
    assert png_20.data.startswith(b"\x89PNG")


def test_team_board_share_png_rejects_invalid_n(client):
    org = _first_team_org(client)
    response = client.get(f"/backfields/team/{org}/share-card.png?n=11")
    assert response.status_code == 400
```

Run:

```bash
python -m pytest tests/test_backfields_page.py -k "team_board_share" -q
```

Expected before implementation: fails because routes do not exist.

### Implementation

Edit `app.py`.

Add:

```python
def _parse_team_board_n() -> int:
    raw = request.args.get("n", "10")
    try:
        n = int(raw)
    except ValueError:
        abort(400)
    if n not in {10, 20}:
        abort(400)
    return n
```

Add PNG helper:

```python
def _team_board_share_card_png(board: dict, n: int) -> bytes:
    rows = board.get("rows", [])[:n]
    selected = board.get("selected") or {}
    org_name = selected.get("name") or selected.get("org") or "Team"
    updated = _editorial_date(_latest_public_snapshot_date())

    width, height = 1080, 1350
    image = Image.new("RGB", (width, height), "#0b0d13")
    draw = ImageDraw.Draw(image)
    _graphic_fill_background(draw, width, height)
    _graphic_header(draw, width, "ValuCast - Backfields")

    title_font = _graphic_font(56, weight=700)
    sub_font = _graphic_font(24, weight=500)
    mono_font = _graphic_font(18, mono=True, weight=700)
    row_font = _graphic_font(25, weight=700)
    meta_font = _graphic_font(18, mono=True, weight=500)
    value_font = _graphic_font(30, weight=800)

    draw.text((64, 150), f"{org_name} Top {min(n, len(rows))}", fill="#eceef4", font=title_font)
    draw.text((64, 216), f"Prospect board - Updated {updated}", fill="#9197a5", font=sub_font)

    x0, y0 = 64, 286
    row_h = 48 if n == 20 else 72
    table_w = width - 128
    draw.rounded_rectangle((x0, y0, x0 + table_w, y0 + 58 + row_h * len(rows)), radius=10, outline="#2a2d36", fill="#12141a")
    draw.text((x0 + 18, y0 + 18), "#", fill="#5e6678", font=mono_font)
    draw.text((x0 + 82, y0 + 18), "PLAYER", fill="#5e6678", font=mono_font)
    draw.text((x0 + table_w - 220, y0 + 18), "LEVEL", fill="#5e6678", font=mono_font)
    draw.text((x0 + table_w - 86, y0 + 18), "VALUE", fill="#5e6678", font=mono_font)

    y = y0 + 58
    for row in rows:
        rank = str(row.get("org_rank") or "")
        name = str(row.get("name") or "")
        pos = str(row.get("position") or "")
        affiliate = str(row.get("affiliate") or "")
        level = str(row.get("level") or "-")
        value = str(row.get("value") or "")
        meta = " / ".join(part for part in (pos, affiliate) if part)

        draw.line((x0, y, x0 + table_w, y), fill="#222631", width=1)
        draw.text((x0 + 18, y + 15), rank, fill="#9197a5", font=meta_font)
        draw.text((x0 + 82, y + 9), name, fill="#eceef4", font=row_font)
        draw.text((x0 + 82, y + 37), meta[:58], fill="#c8923f", font=meta_font)
        draw.text((x0 + table_w - 220, y + 18), level, fill="#c8923f", font=meta_font)
        draw.text((x0 + table_w - 92, y + 9), value, fill="#34e2c4", font=value_font)
        y += row_h

    _graphic_footer(draw, width, height, "valucast.app - Backfields - ValuCast prospect order")
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
```

Use the existing latest-date helper if `_latest_public_snapshot_date()` is not the correct name. Do not add render-time `date.today()`.

Add routes:

```python
@app.route("/backfields/team/<org>/share-card")
def backfields_team_share_card(org: str):
    try:
        board = _build_team_board_context(org, limit=20)
    except KeyError:
        abort(404)
    if not board["rows"]:
        abort(404)
    return render_template("backfields_team_share.html", board=board)


@app.route("/backfields/team/<org>/share-card.png")
def backfields_team_share_card_png(org: str):
    n = _parse_team_board_n()
    try:
        board = _build_team_board_context(org, limit=n)
    except KeyError:
        abort(404)
    if not board["rows"]:
        abort(404)
    png = _team_board_share_card_png(board, n=n)
    response = make_response(png)
    response.headers["Content-Type"] = "image/png"
    selected = board["selected"]
    response.headers["Content-Disposition"] = (
        f'inline; filename="valucast-{selected["org"].lower()}-top-{n}-prospects.png"'
    )
    return response
```

If `Image`, `ImageDraw`, and `io` are not available in this file near the graphic helpers, use the existing imports already used by share-card functions.

Create `templates/backfields_team_share.html`:

```html
{% extends "base.html" %}
{% block title %}{{ board.selected.name }} Team Board | ValuCast{% endblock %}
{% block content %}
<main class="container backfields-page bf-share-preview">
  <a class="back-link" href="{{ board.selected.url }}">Back to {{ board.selected.org }} board</a>
  <section class="bf-hero">
    <p class="bf-kicker">ValuCast - Backfields</p>
    <h1>{{ board.selected.name }} Team Board</h1>
    <p>Shareable Top 10 and Top 20 prospect graphics sorted by ValuCast prospect order.</p>
    <div class="bf-share-actions">
      <a class="bf-action" href="{{ board.selected.url }}/share-card.png?n=10">Download Top 10 PNG</a>
      <a class="bf-action" href="{{ board.selected.url }}/share-card.png?n=20">Download Top 20 PNG</a>
    </div>
  </section>
  <section class="bf-panel">
    <h2>Preview rows</h2>
    <ol>
      {% for row in board.rows[:20] %}
        <li>
          <a href="{{ row.detail_url }}">{{ row.name }}</a>
          <span>{{ row.position }}{% if row.affiliate %} / {{ row.affiliate }}{% endif %}</span>
          <strong>{{ row.value }}</strong>
        </li>
      {% endfor %}
    </ol>
    <p class="bf-muted">ValuCast prospect order. External boards do not feed this score.</p>
  </section>
</main>
{% endblock %}
```

### Verify

```bash
python -m pytest tests/test_backfields_page.py -k "team_board_share" -q
```

Expected: 2 passed.

## Task 7 - Full Verification

Run targeted tests:

```bash
python -m pytest tests/test_backfields_page.py tests/test_public_surfaces_smoke.py -q
```

Expected: all selected tests pass.

Run syntax and lint checks:

```bash
python -m py_compile app.py
python -m ruff check app.py tests/test_backfields_page.py
```

Expected:

```text
All checks passed!
```

Run route smoke manually if possible:

```bash
python -c "import app; c=app.app.test_client(); print(c.get('/backfields').status_code); print(c.get('/backfields/team/BOS').status_code); print(c.get('/backfields/team/BOS/share-card.png?n=10').status_code)"
```

Expected:

```text
200
200
200
```

If `BOS` has no rows in a future snapshot, use the first org link from `/backfields` instead of hardcoding `BOS`.

## Task 8 - Visual QA

Start the app locally:

```bash
python -c "import app; app.app.run(host='127.0.0.1', port=5077, use_reloader=False, threaded=True)"
```

Open:

- `http://127.0.0.1:5077/backfields`
- `http://127.0.0.1:5077/backfields/team/BOS`
- `http://127.0.0.1:5077/backfields/team/BOS/share-card`
- `http://127.0.0.1:5077/backfields/team/BOS/share-card.png?n=10`
- `http://127.0.0.1:5077/backfields/team/BOS/share-card.png?n=20`

Visual checks:

- Primary nav shows Board, Backfields, Map, Intelligence Hub, Methodology.
- Backfields contains deep links to Buys and Scouting.
- Team Boards use warm Backfields styling but teal only for values and movement.
- Team Board rows show affiliate detail but are grouped by MLB org.
- KCR alias opens the KC board.
- Top 10 and Top 20 PNGs are app-export style, not poster style.
- PNG footer says `valucast.app - Backfields - ValuCast prospect order`.
- No headshots, team-color flood, consensus copy, or external-rank language appears.

## Task 9 - Commit And Push

Check status:

```bash
git status --short
```

Only expected implementation files should be staged:

- `app.py`
- `templates/base.html`
- `templates/backfields.html`
- `templates/backfields_team_share.html`
- `tests/test_backfields_page.py`
- optional targeted smoke test file if changed

Do not stage generated screenshot files or unrelated data artifacts.

Commit:

```bash
git add app.py templates/base.html templates/backfields.html templates/backfields_team_share.html tests/test_backfields_page.py
git commit -m "Add Backfields team boards and org share graphics"
git push
```

## Rollback Notes

If the team-board routes cause production issues:

1. Revert the single feature commit.
2. `/backfields` will return to the current hub.
3. `/buys`, `/scouting`, and existing prospect share routes remain independent.

No data artifacts or daily workflow changes are required for rollback.
