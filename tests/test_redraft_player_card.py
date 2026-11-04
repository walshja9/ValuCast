"""Redraft individual player share-card routes."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from werkzeug.datastructures import MultiDict

import app as app_module
from mlb.availability import availability_lookup, build_mlb_availability

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _first_redraft_player_id(role: str) -> str:
    ctx = app_module._build_context(MultiDict())
    for result in ctx["results"]:
        is_pitcher = result.player.pool in app_module._PITCHER_POOLS
        if (role == "pitcher" and is_pitcher) or (role == "hitter" and not is_pitcher):
            return result.player.id
    pytest.skip(f"no valued redraft {role} available")


def _redraft_results():
    ctx = app_module._build_context(MultiDict())
    return app_module._redraft_value_players(
        app_module._valuation_players(active_store=ctx["active_store"]),
        ctx["config"],
    )


def _first_raw_out_of_scale_result():
    for result in _redraft_results():
        if result.total_value < 0 or result.total_value > 100:
            return result
    pytest.skip("no out-of-scale redraft result available")


def _first_redraft_player_id_with_dynasty_match() -> str:
    if not app_module.dd_store.is_available:
        pytest.skip("needs dynasty feed")
    identities = {
        (str(row.mlbam_id), row.role)
        for row in app_module.dd_store.get_all()
        if row.mlbam_id and row.role in {"hitter", "pitcher"}
    }
    ctx = app_module._build_context(MultiDict())
    for result in ctx["results"]:
        player = result.player
        mlbam_id = (player.metadata or {}).get("mlbam_id")
        role = "pitcher" if player.pool in app_module._PITCHER_POOLS else "hitter"
        if mlbam_id and (str(mlbam_id), role) in identities:
            return player.id
    pytest.skip("no redraft player with dynasty snapshot match")


@pytest.mark.parametrize("role", ["hitter", "pitcher"])
def test_redraft_player_card_png_renders_for_hitters_and_pitchers(client, role):
    player_id = _first_redraft_player_id(role)

    response = client.get(f"/redraft/player-card/{player_id}.png")

    assert response.status_code == 200
    assert response.data[:8] == PNG_MAGIC
    assert "image/png" in response.content_type
    assert len(response.data) > 1000


def test_redraft_player_card_value_is_scaled_to_zero_100():
    raw_result = _first_raw_out_of_scale_result()

    context, status = app_module._build_redraft_player_card_context(
        raw_result.player.id,
        MultiDict(),
    )
    fields = app_module._card_value_fields("redraft", context["player"], context)

    assert status == 200
    assert 0 <= fields["value"] <= 100
    assert fields["value"] != raw_result.total_value
    assert any("0-100" in note for note in fields["value_notes"])


def test_redraft_share_row_value_is_scaled_to_zero_100():
    raw_result = _first_raw_out_of_scale_result()
    ctx = app_module._build_context(MultiDict())

    row = app_module._RedraftShareRow(raw_result, ctx["redraft_value_scale"])

    assert 0 <= row.value <= 100


def test_dynasty_snapshot_identity_lookup_matches_mlbam_and_role():
    if not app_module.dd_store.is_available:
        pytest.skip("needs dynasty feed")
    expected = next(
        (
            row for row in app_module.dd_store.get_all()
            if row.mlbam_id and row.role in {"hitter", "pitcher"}
        ),
        None,
    )
    if expected is None:
        pytest.skip("no MLBAM-keyed dynasty snapshot rows")

    assert app_module._dynasty_snapshot_row_for(expected.mlbam_id, expected.role) is expected
    assert app_module._dynasty_snapshot_row_for("not-a-real-id", expected.role) is None


def test_artifact_context_falls_back_from_pitcher_to_starter_role_tracker(monkeypatch):
    def fake_load_artifact(path):
        if str(path).endswith("valucast_playing_time_role_tracker.json"):
            return {
                "profiles": [
                    {
                        "identity_key": "123_starter",
                        "mlbam_id": "123",
                        "pool": "starter",
                        "projected_role": "rotation_starter",
                    }
                ]
            }
        return {}

    monkeypatch.setattr(app_module, "_load_artifact", fake_load_artifact)

    context = app_module._artifact_context_for_row(
        SimpleNamespace(mlbam_id="123", role="pitcher")
    )

    assert context["role_profile"]["projected_role"] == "rotation_starter"


def test_artifact_context_hides_clamped_opportunity_judgment(monkeypatch):
    def fake_load_artifact(path):
        if str(path).endswith("valucast_playing_time_role_tracker.json"):
            return {
                "profiles": [
                    {
                        "identity_key": "701398_hitter",
                        "mlbam_id": "701398",
                        "pool": "hitter",
                        "projected_role": "bench_or_depth",
                        "projected_volume": 0.0,
                        "projected_volume_unit": "PA",
                        "role_basis": "thin projected plate appearances",
                        "role_context_status": "blocked",
                        "role_context_blockers": ["remaining_opportunity_clamped"],
                        "remaining_opportunity_clamped": True,
                        "availability_status": "active_mlb_roster",
                    }
                ]
            }
        return {}

    monkeypatch.setattr(app_module, "_load_artifact", fake_load_artifact)

    context = app_module._artifact_context_for_row(
        SimpleNamespace(mlbam_id="701398", role="hitter")
    )

    profile = context["role_profile"]
    assert profile["projected_role_label"] == "Not rated"
    assert profile["projected_volume"] is None
    assert profile["availability_status_label"] == "Active Mlb Roster"
    assert profile["role_basis"] == (
        "ROS opportunity unavailable because current playing time exceeded "
        "the projection baseline"
    )
    read = app_module._dynasty_card_read(
        SimpleNamespace(
            name="Sal Stewart",
            dna="",
            dynasty_rank=11,
            dynasty_value=73.5,
            positions=("1B",),
            stat_line=None,
            role="hitter",
        ),
        context,
    )
    assert "depth role" not in read
    assert "0 PA" not in read
    assert "active MLB roster" in read


def test_redraft_context_joins_dynasty_age_for_matched_player():
    player_id = _first_redraft_player_id_with_dynasty_match()

    context, status = app_module._build_redraft_player_card_context(player_id, MultiDict())
    fields = app_module._card_value_fields("redraft", context["player"], context)

    assert status == 200
    assert "Age " in fields["meta"]


def test_redraft_context_without_dynasty_match_does_not_crash(monkeypatch):
    player_id = _first_redraft_player_id("hitter")
    monkeypatch.setattr(
        app_module,
        "_dynasty_snapshot_row_for",
        lambda _mlbam_id, _role: None,
        raising=False,
    )

    context, status = app_module._build_redraft_player_card_context(player_id, MultiDict())
    fields = app_module._card_value_fields("redraft", context["player"], context)

    assert status == 200
    assert "Age " not in fields["meta"]


def _card_dynasty_row(value_history=()):
    return SimpleNamespace(
        name="Momentum Bat",
        team="BOS",
        positions=("SS",),
        level="MLB",
        age=25,
        dynasty_value=70.0,
        dynasty_rank=12,
        confidence={"level": "high", "range": {"low": 66, "high": 74}},
        value_by_preset={},
        dna="Card read.",
        value_history=value_history,
    )


def test_dynasty_player_card_fields_include_value_momentum():
    row = _card_dynasty_row((
        ("2026-06-12", 66.8),
        ("2026-06-28", 70.0),
    ))

    fields = app_module._card_value_fields("dynasty", row, {"statcast_groups": []})

    assert fields["momentum_label"] == "UP +3.2 OVER 16D"


def test_dynasty_player_card_fields_skip_empty_value_momentum():
    fields = app_module._card_value_fields(
        "dynasty",
        _card_dynasty_row(()),
        {"statcast_groups": []},
    )

    assert fields["momentum_label"] == ""


def test_redraft_player_card_fields_use_joined_dynasty_value_history():
    row = SimpleNamespace(
        id="redraft-1",
        name="Redraft Bat",
        pool=app_module.PlayerPool.HITTER,
        positions=("OF",),
        metadata={"team": "BOS"},
        stats={},
    )
    context = {
        "as_of": "2026-06-28",
        "dyn_result": SimpleNamespace(total_value=12.0),
        "overall_ranks": {"redraft-1": 7},
        "redraft_value_scale": (0.0, 20.0),
        "redraft_dynasty_row": _card_dynasty_row((
            ("2026-06-12", 66.8),
            ("2026-06-28", 70.0),
        )),
        "statcast_groups": [],
    }

    fields = app_module._card_value_fields("redraft", row, context)

    assert fields["momentum_label"] == "UP +3.2 OVER 16D"


def test_redraft_player_card_fields_skip_joined_dynasty_row_without_history():
    row = SimpleNamespace(
        id="redraft-1",
        name="Redraft Bat",
        pool=app_module.PlayerPool.HITTER,
        positions=("OF",),
        metadata={"team": "BOS"},
        stats={},
    )
    context = {
        "as_of": "2026-06-28",
        "dyn_result": SimpleNamespace(total_value=12.0),
        "overall_ranks": {"redraft-1": 7},
        "redraft_value_scale": (0.0, 20.0),
        "redraft_dynasty_row": _card_dynasty_row(()),
        "statcast_groups": [],
    }

    fields = app_module._card_value_fields("redraft", row, context)

    assert fields["momentum_label"] == ""


@pytest.mark.parametrize("role", ["hitter", "pitcher"])
def test_redraft_player_card_preview_renders_for_hitters_and_pitchers(client, role):
    player_id = _first_redraft_player_id(role)

    response = client.get(f"/redraft/player-card/{player_id}")

    assert response.status_code == 200
    assert "text/html" in response.content_type
    assert b"Redraft Value Card" in response.data
    assert f"/redraft/player-card/{player_id}.png".encode() in response.data


@pytest.mark.parametrize(
    "profile, on_board",
    [
        ({"status": "injured", "offseason_hold": True}, True),
        ({"status": "rehab", "offseason_hold": True}, True),
        ({"status": "injured"}, False),
        ({"status": "rehab"}, False),
        ({"status": "available"}, True),
    ],
)
def test_offseason_hold_stays_on_the_redraft_board(monkeypatch, profile, on_board):
    monkeypatch.setattr(app_module, "_mlb_availability_by_id", lambda: {"1": profile})
    player = SimpleNamespace(metadata={"mlbam_id": 1})

    assert app_module._is_live_redraft_projection(player) is on_board


def _transaction(transaction_id, day, text):
    return {
        "id": transaction_id, "date": day, "effectiveDate": day,
        "person": {"id": 1, "fullName": "Guy"}, "description": text,
    }


_PLACED = _transaction(1, "2026-08-01", "Club placed RHP Guy on the 60-day injured list. Elbow.")
_ACTIVATED = _transaction(2, "2026-11-02", "Club activated RHP Guy from the 60-day injured list.")


@pytest.mark.parametrize(
    "transactions, held, on_board",
    [
        # MLB's paperwork activation is the only thing the exemption covers.
        ([_PLACED, _ACTIVATED], True, True),
        # A later record is a current injury, so the normal redraft check applies.
        ([_PLACED, _ACTIVATED, _transaction(
            3, "2027-02-15", "Club placed RHP Guy on the 60-day injured list. Shoulder.")], False, False),
        ([_PLACED, _ACTIVATED, _transaction(
            3, "2027-02-15", "Club sent RHP Guy on a rehab assignment to Iowa.")], False, False),
        # No activation means no hold: an old status stays under the normal check.
        ([_PLACED], False, False),
        # Hitters are not held, and their activation is accepted.
        ([_transaction(1, "2026-08-01", "Club placed 1B Guy on the 60-day injured list. Knee."),
          _transaction(2, "2026-11-02", "Club activated 1B Guy from the 60-day injured list.")], False, True),
    ],
)
def test_redraft_exemption_covers_only_the_administrative_hold(monkeypatch, transactions, held, on_board):
    payload = build_mlb_availability(
        [{"metadata": {"mlbam_id": "1"}}],
        generated_at="2027-02-20",
        season=2026,
        transactions=transactions,
        schedule_fetcher=lambda season: [
            {"date": "2026-09-27", "games": [{"status": {"detailedState": "Final"}}]},
        ] if season == 2026 else [],
        game_log_fetcher=lambda *_: [],
    )
    availability = availability_lookup(payload)
    monkeypatch.setattr(app_module, "_mlb_availability_by_id", lambda: availability)

    assert (availability["1"].get("offseason_hold") is True) is held
    assert app_module._is_live_redraft_projection(
        SimpleNamespace(metadata={"mlbam_id": 1})) is on_board


def test_held_player_keeps_another_exclusion(monkeypatch):
    monkeypatch.setattr(app_module, "_mlb_availability_by_id", lambda: {
        "1": {"status": "injured", "offseason_hold": True},
    })
    monkeypatch.setattr(app_module, "_ineligible_mlbam_ids", lambda: frozenset({"1"}))
    monkeypatch.setattr(app_module, "filter_by_playing_time", lambda players, **_: players)
    player = SimpleNamespace(id="1", metadata={"mlbam_id": 1})

    assert app_module._valuation_players(active_store=SimpleNamespace(get_all=lambda: [player])) == []


def test_offseason_hold_shows_on_redraft_row_and_detail(client, monkeypatch):
    player = app_module.store.get_by_id(_first_redraft_player_id("pitcher"))
    note = "End-of-season injury status held."
    monkeypatch.setattr(app_module, "_mlb_availability_by_id", lambda: {
        str(player.metadata["mlbam_id"]): {
            "status": "injured", "offseason_hold": True, "hold_note": note,
        },
    })
    headers = {"HX-Request": "true"}

    detail = client.get(f"/player/{player.id}", headers=headers).get_data(as_text=True)
    table = client.get("/rankings", query_string={"search": player.name},
                       headers=headers).get_data(as_text=True)

    assert note in detail
    assert "no injury discount to this redraft value" in detail
    assert "Injury hold" in table


def test_redraft_player_detail_share_link_carries_query_string(client):
    player_id = _first_redraft_player_id("hitter")
    query = "mode=categories&cats=R,HR&pcats=K,ERA&source=steamer"

    response = client.get(
        f"/player/{player_id}?{query}",
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'class="player-share-link"' in html
    assert (
        f'href="/redraft/player-card/{player_id}?'
        "mode=categories&amp;cats=R,HR&amp;pcats=K,ERA&amp;source=steamer"
        '"'
    ) in html


@pytest.mark.skipif(not app_module.dd_store.is_available, reason="needs dynasty feed")
def test_dynasty_player_card_still_renders_after_shared_renderer_refactor(client):
    response = client.get("/dynasty/player-card/vc_mlb_687462_hitter.png")

    assert response.status_code == 200
    assert response.data[:8] == PNG_MAGIC
    assert "image/png" in response.content_type
    assert len(response.data) > 1000


def test_redraft_player_card_shows_every_category_not_just_top_four(client):
    """A league format with more than 4 hitting categories must render all of
    them (wrapped across rows), not silently drop everything past the 4th."""
    from io import BytesIO

    from PIL import Image

    player_id = _first_redraft_player_id("hitter")
    base = client.get(f"/redraft/player-card/{player_id}.png?cats=R,HR&pcats=K")
    many = client.get(
        f"/redraft/player-card/{player_id}.png?cats=R,HR,RBI,SB,AVG,OPS,TB&pcats=K"
    )

    assert base.status_code == 200 and many.status_code == 200
    base_h = Image.open(BytesIO(base.data)).height
    many_h = Image.open(BytesIO(many.data)).height
    # 7 categories need 2 rows (4-per-row); the card must grow to fit the 2nd row
    # rather than clipping categories 5-7.
    assert many_h > base_h
