"""Tests for MLB dynasty preset value parity."""

from dataclasses import replace

from mlb.dynasty import build_mlb_dynasty_layer
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
        assert set(row["value_by_preset"]) == set(PRESET_IDS)
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
