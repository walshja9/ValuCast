"""Tests for MLB dynasty preset value parity."""

from dataclasses import replace

import mlb.dynasty as dynasty
from mlb.dynasty import build_mlb_dynasty_layer, identity_key
from test_mlb_dynasty_layer import _hitter, _pitcher, _reliever


PRESET_IDS = ["5x5", "obp", "6x6", "sv_hld", "7x7", "7x7_ops", "points"]


def _hold_reliever():
    player = _reliever(
        player_id="rp_hold",
        mlbam_id="4",
        name="Holds Monster",
        metadata={"age": 27},
    )
    stats = dict(player.stats)
    stats.update(
        {
            "SV": 2,
            "HLD": 38,
            "SV_HLD": 40,
            "K": 110,
            "K_BB": 5.5,
        }
    )
    return replace(player, stats=stats)


def _closer():
    player = _reliever(
        player_id="rp_save",
        mlbam_id="5",
        name="Save Monster",
        metadata={"age": 29},
    )
    stats = dict(player.stats)
    stats.update(
        {
            "SV": 36,
            "HLD": 1,
            "SV_HLD": 37,
            "K_BB": 6.0,
        }
    )
    return replace(player, stats=stats)


def test_mlb_dynasty_rows_carry_all_preset_values_with_5x5_parity():
    payload = build_mlb_dynasty_layer(
        [
            _hitter(
                player_id="h_power",
                mlbam_id="1",
                name="Power Bat",
                hr=42,
                sb=3,
                avg=.270,
                metadata={"age": 26},
            ),
            _hitter(
                player_id="h_speed",
                mlbam_id="2",
                name="Speed Bat",
                hr=12,
                sb=38,
                avg=.285,
                metadata={"age": 24},
            ),
            _pitcher(
                player_id="sp_anchor",
                mlbam_id="3",
                name="Starter Anchor",
                metadata={"age": 28},
            ),
            _hold_reliever(),
            _closer(),
        ],
        "2026-06-13",
    )

    assert payload["value_by_preset_menu"] == PRESET_IDS
    for row in payload["players"]:
        # The points preset has no pitcher model yet, so pitcher rows omit it
        # (the PTS chip is suppressed) while hitters keep every preset.
        expected = set(PRESET_IDS)
        if row.get("role") == "pitcher":
            expected.discard("points")
        assert set(row["value_by_preset"]) == expected
        assert row["value_by_preset"]["5x5"] == row["value"]


def test_mlb_dynasty_preset_values_are_settings_aware():
    payload = build_mlb_dynasty_layer(
        [
            _hitter(
                player_id="h_power",
                mlbam_id="1",
                name="Power Bat",
                hr=48,
                sb=2,
                avg=.265,
                metadata={"age": 26},
            ),
            _hitter(
                player_id="h_contact",
                mlbam_id="2",
                name="Contact Bat",
                hr=18,
                sb=12,
                avg=.310,
                metadata={"age": 25},
            ),
            _pitcher(
                player_id="sp_anchor",
                mlbam_id="3",
                name="Starter Anchor",
                metadata={"age": 28},
            ),
            _hold_reliever(),
            _closer(),
        ],
        "2026-06-13",
    )

    hold_reliever = next(row for row in payload["players"] if row["name"] == "Holds Monster")
    assert hold_reliever["value_by_preset"]["sv_hld"] != hold_reliever["value_by_preset"]["5x5"]

    assert any(
        row["value_by_preset"][preset_id] != row["value_by_preset"]["5x5"]
        for row in payload["players"]
        for preset_id in PRESET_IDS
        if preset_id != "5x5"
    )


def test_missing_preset_key_is_omitted_not_defaulted(monkeypatch):
    """A preset missing a player's score must omit that preset (hide the chip),
    NOT silently fall back to the default 5x5 value."""
    speed_bat = _hitter(
        player_id="h_speed",
        mlbam_id="2",
        name="Speed Bat",
        hr=12,
        sb=38,
        avg=.285,
        metadata={"age": 24},
    )
    drop_key = identity_key(speed_bat)

    real_scores_for_config = dynasty._scores_for_config

    # Category ids that uniquely identify the 7x7 preset (HLD + OBP + SO, no OPS).
    seven_by_seven_cats = {"R", "HR", "RBI", "SB", "AVG", "OBP", "SO",
                           "W", "QS", "SV", "HLD", "K", "ERA", "WHIP"}

    def _patched_scores_for_config(engine, eligible, league, *args, **kwargs):
        eligible = list(eligible)
        scores = real_scores_for_config(engine, eligible, league, *args, **kwargs)
        # Simulate the 7x7 preset lacking a score for Speed Bat only.
        league_cats = {getattr(c, "id", None) for c in getattr(league, "categories", ())}
        if league_cats == seven_by_seven_cats and drop_key in scores:
            scores = {k: v for k, v in scores.items() if k != drop_key}
        return scores

    monkeypatch.setattr(dynasty, "_scores_for_config", _patched_scores_for_config)

    payload = build_mlb_dynasty_layer(
        [
            _hitter(
                player_id="h_power",
                mlbam_id="1",
                name="Power Bat",
                hr=42,
                sb=3,
                avg=.270,
                metadata={"age": 26},
            ),
            speed_bat,
        ],
        "2026-06-13",
    )

    speed_row = next(row for row in payload["players"] if row["name"] == "Speed Bat")
    # The preset whose score map dropped the key must be omitted entirely...
    assert "7x7" not in speed_row["value_by_preset"]
    # ...and crucially must NOT have been defaulted to the 5x5 value.
    assert speed_row["value_by_preset"].get("7x7") != speed_row["value_by_preset"]["5x5"]
    # Other presets are unaffected and remain present.
    assert "5x5" in speed_row["value_by_preset"]


def test_points_preset_omitted_for_pitchers_kept_for_hitters():
    """The points preset has no pitcher model yet: pitchers omit the PTS chip,
    hitters keep their points value."""
    payload = build_mlb_dynasty_layer(
        [
            _hitter(
                player_id="h_power",
                mlbam_id="1",
                name="Power Bat",
                hr=42,
                sb=3,
                avg=.270,
                metadata={"age": 26},
            ),
            _pitcher(
                player_id="sp_anchor",
                mlbam_id="3",
                name="Starter Anchor",
                metadata={"age": 28},
            ),
            _closer(),
        ],
        "2026-06-13",
    )

    for row in payload["players"]:
        if row.get("role") == "pitcher":
            assert "points" not in row["value_by_preset"]
        else:
            assert "points" in row["value_by_preset"]
