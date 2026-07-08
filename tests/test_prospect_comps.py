"""Tests for the measured prospect shape-comp builder."""
from __future__ import annotations

from prospects.comps import (
    CompPool,
    build_prospect_comps,
    comp_for_target,
    eligible_prospects,
)


def _season_row(pid, name, season, age, pa, k_pct, bb_pct, iso, avg=0.260, pos="RF", bats="L"):
    """Build a raw history row from target rates (counts derived)."""
    return {
        "id": pid,
        "name": name,
        "season": season,
        "age": age,
        "pos": pos,
        "bats": bats,
        "pa": pa,
        "so": round(pa * k_pct / 100),
        "bb": round(pa * bb_pct / 100),
        "hr": 20,
        "avg": avg,
        "obp": avg + 0.070,
        "slg": avg + iso,
    }


def _filler_pool(season, start_pid=1000, n=12, age=25):
    """A spread of regulars so per-season z-stats exist (std > 0)."""
    rows = []
    for i in range(n):
        rows.append(_season_row(
            start_pid + i, f"Filler {start_pid + i}", season, age, 500,
            k_pct=14.0 + i * 1.6, bb_pct=5.0 + i * 0.9, iso=0.090 + i * 0.014,
        ))
    return rows


def test_era_normalization_prefers_the_era_relative_match():
    # Two candidate seasons with IDENTICAL raw rates (K 22, BB 9, ISO .180).
    # In the low-K 2005 era that shape is an outlier; in high-K 2025 it sits
    # near the league middle. The target (translated to TODAY's environment,
    # slightly above 2025's middle) must match the 2025 season first.
    rows = []
    # 2005: league regulars around K 15 / BB 8 / ISO .150
    for i in range(12):
        rows.append(_season_row(1 + i, f"Old {i}", 2005, 25, 500,
                                14.0 + i * 0.4, 7.4 + i * 0.12, 0.140 + i * 0.003))
    # 2025: league regulars around K 22 / BB 9 / ISO .175
    for i in range(12):
        rows.append(_season_row(100 + i, f"New {i}", 2025, 25, 500,
                                20.5 + i * 0.4, 8.4 + i * 0.12, 0.160 + i * 0.005))
    rows.append(_season_row(50, "Era Outlier", 2005, 24, 520, 22.0, 9.0, 0.180))
    rows.append(_season_row(51, "Era Normal", 2025, 24, 520, 22.0, 9.0, 0.180))
    pool = CompPool(rows)

    # Same raw rates, different eras -> different era-relative distances.
    from prospects.comps import _distance
    target = pool.target_z({"k_pct": 22.4, "bb_pct": 9.1, "iso": 0.184})
    by_name = {r["name"]: r for r in pool.match_rows}
    d_normal = _distance(target, by_name["Era Normal"]["z"])
    d_outlier = _distance(target, by_name["Era Outlier"]["z"])
    assert d_normal < d_outlier


def test_outcome_tiers_and_resolution_window():
    rows = _filler_pool(2010)
    # League context for the follow-up seasons, so era-relative OPS has a real
    # denominator (without these, the league mean IS the stud's own line).
    for season in range(2011, 2016):
        rows.extend(_filler_pool(season, start_pid=8000 + season * 20))
    # Stud: matched 2010 season + five 600-PA follow-ups well above league OPS.
    rows.append(_season_row(1, "Stud", 2010, 23, 550, 20.0, 9.0, 0.180))
    for offset in range(1, 6):
        rows.append(_season_row(1, "Stud", 2010 + offset, 23 + offset, 600,
                                20.0, 9.0, 0.230, avg=0.300))
    # Bust: matched 2010 season, never appears again.
    rows.append(_season_row(2, "Bust", 2010, 23, 549, 20.1, 9.1, 0.181))
    # Recent: identical shape but 2024 -> follow-up window incomplete.
    rows.extend(_filler_pool(2024, start_pid=2000))
    rows.append(_season_row(3, "Recent", 2024, 23, 551, 20.0, 9.0, 0.180))
    rows.append(_season_row(9, "Latest", 2025, 25, 500, 21.0, 8.5, 0.170))
    rows.extend(_filler_pool(2025, start_pid=3000))
    pool = CompPool(rows)

    assert pool.resolved_through == 2020
    stud = pool.outcome(1, 2010)
    assert stud["tier"] == "impact_regular" and stud["pa_per_year"] == 600.0
    assert pool.outcome(2, 2010)["tier"] == "faded"
    assert pool.outcome(3, 2024) is None  # window not complete -> excluded

    comp = comp_for_target(pool, {"k_pct": 20.0, "bb_pct": 9.0, "iso": 0.180})
    # Cohort counts only resolved matches; Recent (2024) must not be in it.
    tiers = comp["cohort"]["tiers"]
    assert tiers["impact_regular"] >= 1 and tiers["faded"] >= 1
    assert comp["cohort"]["resolved_through"] == 2020
    # Twins may include the unresolved Recent season, but with outcome None.
    recent_twin = next((t for t in comp["twins"] if t["name"] == "Recent"), None)
    if recent_twin:
        assert recent_twin["outcome"] is None


def test_cohort_dedupes_players_and_twins_dedupe_too():
    rows = _filler_pool(2012)
    # One player with two nearly identical qualifying seasons.
    rows.append(_season_row(7, "Twice", 2012, 24, 500, 20.0, 9.0, 0.180))
    rows.append(_season_row(7, "Twice", 2013, 25, 500, 20.1, 9.0, 0.181))
    rows.extend(_filler_pool(2013, start_pid=4000))
    rows.extend(_filler_pool(2025, start_pid=5000))
    pool = CompPool(rows)

    comp = comp_for_target(pool, {"k_pct": 20.0, "bb_pct": 9.0, "iso": 0.180})
    assert [t["name"] for t in comp["twins"]].count("Twice") == 1
    # cohort size can never exceed unique players in the pool
    unique_players = len({r["id"] for r in pool.match_rows})
    assert comp["cohort"]["size"] <= unique_players


def test_eligibility_gates_on_translation_quality():
    def snap_row(mlbam_id, rank, confidence="high", low_sample=False, role="hitter"):
        return {
            "player_type": "prospect",
            "mlbam_id": mlbam_id,
            "name": f"P{mlbam_id}",
            "prospect_rank": rank,
            "stat_line_translated": {
                "role": role,
                "confidence": confidence,
                "low_sample": low_sample,
                "stats": [
                    {"key": "k_pct", "mlb": 21.0},
                    {"key": "bb_pct", "mlb": 9.0},
                    {"key": "iso", "mlb": 0.180},
                ],
            },
        }

    snapshot = {"players": [
        snap_row(1, 10),
        snap_row(2, 20, confidence="medium"),      # gated: not high confidence
        snap_row(3, 30, low_sample=True),           # gated: thin sample
        snap_row(4, 999),                           # gated: outside rank cap
        snap_row(5, 40, role="pitcher"),            # gated: hitters only in v1
    ]}
    eligible = eligible_prospects(snapshot)
    assert [p["mlbam_id"] for p in eligible] == ["1"]


def test_build_artifact_shape_and_policy():
    history = {
        "seasons": [2010, 2025],
        "rows": _filler_pool(2010) + _filler_pool(2025, start_pid=6000),
    }
    snapshot = {"players": [{
        "player_type": "prospect",
        "mlbam_id": 42,
        "name": "Artifact Kid",
        "prospect_rank": 5,
        "stat_line_translated": {
            "role": "hitter", "confidence": "high", "low_sample": False,
            "stats": [
                {"key": "k_pct", "mlb": 20.0},
                {"key": "bb_pct", "mlb": 9.0},
                {"key": "iso", "mlb": 0.150},
            ],
        },
    }]}
    payload = build_prospect_comps(history, snapshot, generated_at="2026-07-08T00:00:00+00:00")

    assert payload["source_policy"]["display_only"] is True
    assert payload["source_policy"]["feeds_live_valucast_rank"] is False
    kid = payload["players"]["42"]
    assert kid["prospect_rank"] == 5
    assert len(kid["twins"]) == 3
    assert set(kid["cohort"]["tiers"]) == {"impact_regular", "everyday", "part_time", "faded"}
    # every twin carries the receipt: its own matched rates
    for twin in kid["twins"]:
        assert {"k_pct", "bb_pct", "iso"} <= set(twin)


def test_detail_card_renders_comps_from_the_committed_artifact():
    import json
    from pathlib import Path

    root = Path(__file__).parent.parent
    artifact = json.loads(
        (root / "data" / "models" / "valucast_prospect_comps.json").read_text(encoding="utf-8")
    )
    snapshot = json.loads(
        (root / "data" / "public" / "public_dynasty_snapshot.json").read_text(encoding="utf-8")
    )
    assert artifact["source_policy"]["display_only"] is True
    comped = artifact["players"]
    assert comped, "artifact must comp at least one prospect"

    row = next(
        r for r in snapshot["players"]
        if str(r.get("mlbam_id")) in comped and r.get("player_type") == "prospect"
    )
    import app as app_module
    client = app_module.app.test_client()
    html = client.get(
        f"/player/{row['id']}?mode=prospects", headers={"HX-Request": "true"}
    ).data.decode("utf-8")

    comp = comped[str(row["mlbam_id"])]
    assert "Closest MLB Shapes" in html
    for twin in comp["twins"]:
        assert twin["name"] in html
    assert "How this shape aged" in html
    assert f"the {comp['cohort']['size']} nearest matches" in html
    # the disclosure is load-bearing (7/8 review): descriptive lens, never a
    # forecast; cohort bars are counts, not odds; tiers measure playing time.
    assert "not a forecast" in html
    assert "counts of matched careers, not odds" in html
    assert "PA/yr" in html


def test_methodology_documents_shape_comps():
    import app as app_module
    client = app_module.app.test_client()
    html = client.get("/methodology").data.decode("utf-8")
    assert "Shape comps" in html
    assert "build_prospect_comps.py" in html
    assert "era-relative" in html
    # 7/8 review: the residual survivorship must be NAMED and the tier cut
    # points published — reproducibility is the product.
    assert "bias we can" in html  # "The bias we can't remove, named"
    assert "450+ PA/yr" in html


def test_comps_wired_into_daily_build_after_snapshot():
    from pathlib import Path

    from scripts import run_daily_public_build

    steps = [" ".join(step) for step in run_daily_public_build.BUILD_STEPS]
    assert steps.index("scripts/build_prospect_comps.py") > steps.index(
        "scripts/build_public_dynasty_snapshot.py"
    )
    # The nightly workflow enumerates commit paths explicitly — a rebuilt
    # artifact that never gets committed silently drifts from the snapshot.
    workflow = (
        Path(__file__).parent.parent / ".github" / "workflows" / "daily-public-data.yml"
    ).read_text(encoding="utf-8")
    assert "data/models/valucast_prospect_comps.json" in workflow


def test_2020_short_season_is_prorated_in_outcomes():
    # Match season 2016 -> follow-up window 2017-2021 includes 2020 (60 games).
    # An everyday player with ~600 PA per full year and ~230 in 2020 must still
    # tier as everyday, not get dragged under the 400 PA/yr bar.
    rows = _filler_pool(2016)
    for season in range(2017, 2022):
        rows.extend(_filler_pool(season, start_pid=9000 + season * 20))
    rows.append(_season_row(1, "Everyday Ed", 2016, 24, 550, 20.0, 9.0, 0.180))
    for season in range(2017, 2022):
        pa = 230 if season == 2020 else 600
        rows.append(_season_row(1, "Everyday Ed", season, season - 1992, pa,
                                20.0, 9.0, 0.180))
    rows.extend(_filler_pool(2025, start_pid=9900))
    pool = CompPool(rows)

    outcome = pool.outcome(1, 2016)
    # raw would be (4*600 + 230) / 5 = 526; pro-rated 2020 keeps it comfortably
    # in everyday territory either way, but the scaled figure must be ~600+.
    assert outcome["pa_per_year"] > 550
    assert outcome["tier"] in ("everyday", "impact_regular")


def test_share_card_comp_lines_formats_and_gates():
    from app import _share_card_comp_lines

    assert _share_card_comp_lines(None) is None
    assert _share_card_comp_lines({"twins": []}) is None
    comp = {
        "twins": [
            {"name": "Max Kepler", "season": 2016, "pos": "RF"},
            {"name": "Paul DeJong", "season": 2019, "pos": "SS"},
        ],
        "cohort": {
            "size": 25,
            "tiers": {"impact_regular": 5, "everyday": 12, "part_time": 8, "faded": 0},
        },
    }
    twins, cohort = _share_card_comp_lines(comp)
    assert "Max Kepler '16 (RF)" in twins
    assert "How the 25 nearest resolved matches aged" in cohort
    assert "5 above-avg regular" in cohort and "0 faded out" in cohort
    # measured playing-time language only — never a role verdict
    assert "platoon" not in cohort


def test_share_card_png_renders_with_comps_strip():
    import json
    from pathlib import Path

    root = Path(__file__).parent.parent
    artifact = json.loads(
        (root / "data" / "models" / "valucast_prospect_comps.json").read_text(encoding="utf-8")
    )
    snapshot = json.loads(
        (root / "data" / "public" / "public_dynasty_snapshot.json").read_text(encoding="utf-8")
    )
    row = next(
        r for r in snapshot["players"]
        if str(r.get("mlbam_id")) in artifact["players"] and r.get("player_type") == "prospect"
    )
    import app as app_module
    client = app_module.app.test_client()
    response = client.get(f"/prospects/player-card/{row['id']}.png")
    assert response.status_code == 200
    assert response.data[:8] == b"\x89PNG\r\n\x1a\n"
