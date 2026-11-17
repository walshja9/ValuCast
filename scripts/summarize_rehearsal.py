"""Export only board identities and values; compare hosted rehearsal passes."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil
import uuid
import unicodedata

from scripts.rehearsal_errors import HarnessError

FIELDS = ("name", "type", "role", "age", "rank", "value")
SAMPLE = (
    "Pete Crow-Armstrong", "Junior Caminero", "Elly De La Cruz", "Jackson Merrill",
    "Bobby Witt Jr.", "Sal Stewart", "Jordan Walker", "Juan Soto", "Julio Rodriguez",
    "Paul Skenes", "Tarik Skubal", "Ronald Acuna Jr.", "Nick Kurtz", "Chase Burns",
    "Cristopher Sanchez", "Konnor Griffin", "Garrett Crochet", "Hunter Greene",
)


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(rows):
    return hashlib.sha256(json.dumps(sorted(rows), ensure_ascii=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _prospects(payload):
    rows = payload["board"]
    if not isinstance(rows, list) or not rows:
        raise HarnessError("Prospect board missing or empty")
    scores, ranks, identities = [], [], set()
    for row in rows:
        identity = str(row.get("mlbam_id") or row.get("id") or row["name"]), str(row["role"])
        if identity in identities:
            raise HarnessError("Duplicate prospect identity")
        identities.add(identity)
        score, rank = row["score"], row["rank"]
        if (isinstance(score, bool) or not isinstance(score, (int, float))
                or not math.isfinite(score) or isinstance(rank, bool)
                or not isinstance(rank, int) or rank < 1):
            raise HarnessError("Invalid prospect score or rank")
        scores.append((*identity, score))
        ranks.append((*identity, rank))
    return dict(count=len(rows), scores=_digest(scores), ranks=_digest(ranks),
                identities=_digest(list(identities)))


def _clean(rows, default_type=None):
    cleaned, seen = [], set()
    for row in rows:
        clean = {field: row.get(field) for field in FIELDS}
        clean["type"] = row.get("player_type") or default_type or row.get("type")
        if not all(isinstance(clean[field], str) and clean[field] for field in ("name", "type", "role")):
            raise HarnessError("Missing board identity")
        key = (str(row.get("mlbam_id") or row.get("id") or clean["name"]), clean["type"], clean["role"])
        if key in seen:
            raise HarnessError("Duplicate private board identity")
        seen.add(key)
        rank, value, age = clean["rank"], clean["value"], clean["age"]
        if (clean["type"] not in ("mlb", "prospect") or isinstance(rank, bool)
                or not isinstance(rank, int) or rank < 1 or isinstance(value, bool)
                or not isinstance(value, (int, float)) or not math.isfinite(value)):
            raise HarnessError("Invalid board type, rank or value")
        if age is not None and (isinstance(age, bool) or not isinstance(age, (int, float))
                                or not math.isfinite(age)):
            raise HarnessError("Invalid board age")
        clean["_join_key"] = key
        cleaned.append(clean)
    if not cleaned:
        raise HarnessError("Board missing or empty")
    return sorted(cleaned, key=lambda row: row["rank"])


def _write(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows({field: row[field] for field in FIELDS} for row in rows)


def export_boards(root: Path, out: Path, label: str) -> dict:
    """Return private join keys and fingerprints; write only public CSV fields."""
    if label not in ("before", "after"):
        raise HarnessError("Label must be before or after")
    from scripts.compare_2027_boards import redraft_rows

    players = _load(root / "data/public/public_dynasty_snapshot.json")["players"]
    dynasty = _clean(players)
    if not {"mlb", "prospect"} <= {row["type"] for row in dynasty}:
        raise HarnessError("Combined dynasty board must contain MLB and prospect rows")
    ages = {(row.get("mlbam_id"), row.get("role")): row.get("age")
            for row in players if row.get("player_type") == "mlb"}
    redraft = _clean(redraft_rows(root / "data/projections/current.json", ages), "mlb")
    prospects = _prospects(_load(root / "data/models/valucast_prospect_rank_v1.json"))
    out.mkdir(parents=True, exist_ok=True)
    _write(out / f"board_{label}.csv", dynasty)
    _write(out / f"redraft_{label}.csv", redraft)
    return dict(prospects=prospects,
                visible_prospect_count=sum(row["type"] == "prospect" for row in dynasty),
                boards={prefix: {row["_join_key"]: row for row in rows}
                        for prefix, rows in (("board", dynasty), ("redraft", redraft))})


def _cell(value):
    return str(value if value is not None else "Absent").replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _table(rows):
    lines = ["| Name | Type | Role | Before rank | After rank | Before value | After value |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for key, old, new in rows:
        display = new or old
        lines.append("| " + " | ".join(_cell(v) for v in
                     (display["name"], display["type"], display["role"], old.get("rank"),
                      new.get("rank"), old.get("value"), new.get("value"))) + " |")
    return "\n".join(lines)


def _normalized(name):
    return "".join(c for c in unicodedata.normalize("NFKD", name).casefold()
                   if c.isalnum())


def summarize(out: Path, before: dict, after: dict) -> str:
    lines = ["# 2027 rehearsal board comparison", "",
             "Ranks below are combined dynasty ranks or redraft ranks. Joins use a stable public ID when present, "
             "otherwise name, plus type and role; private join keys stay in memory. "
             "Redraft uses canonical public 5x5 scoring. "
             "Risers/fallers include matched players only; additions/removals are counted separately. "
             "Duplicate groups have at least two name/type/role matches; excess rows count rows beyond the first per group."]
    for title, prefix in (("Dynasty (MLB + prospects)", "board"), ("Redraft 5x5", "redraft")):
        old, new = before["boards"][prefix], after["boards"][prefix]
        duplicates = []
        for label, board in (("before", old), ("after", new)):
            counts = Counter((row["name"], row["type"], row["role"]) for row in board.values())
            duplicates.append(f"{label}: groups={sum(count > 1 for count in counts.values())}, "
                              f"excess rows={sum(count - 1 for count in counts.values())}")
        common = old.keys() & new.keys()
        pairs = [(key, old.get(key, {}), new.get(key, {})) for key in sorted(old.keys() | new.keys())]
        top_old = {key for key in old if old[key]["rank"] <= 50}
        top_new = {key for key in new if new[key]["rank"] <= 50}
        lines += ["", f"## {title}", "",
                  f"Rows: before={len(old)}, after={len(new)}, matched={len(common)}, "
                  f"added={len(new.keys() - old.keys())}, removed={len(old.keys() - new.keys())}. "
                  f"Matched values changed={sum(old[k]['value'] != new[k]['value'] for k in common)}.", "",
                  "Duplicate name/type/role identities (disambiguated privately): " + "; ".join(duplicates) + ".", "",
                  f"Top-50 membership: retained={len(top_old & top_new)}, "
                  f"entered={len(top_new - top_old)}, left={len(top_old - top_new)}.", "",
                  _table([pair for pair in pairs if pair[0] in top_old ^ top_new])]
        for label, direction in (("30 largest risers", -1), ("30 largest fallers", 1)):
            movers = [pair for pair in pairs if pair[0] in common
                      and (pair[2]["rank"] - pair[1]["rank"]) * direction > 0]
            movers.sort(key=lambda pair: (-(pair[2]["rank"] - pair[1]["rank"]) * direction,
                                          pair[2]["rank"], pair[0]))
            lines += ["", f"### {label}", "", _table(movers[:30])]
        lines += ["", "### Named players", ""]
        for name in SAMPLE:
            matches = [pair for pair in pairs if _normalized((pair[2] or pair[1])["name"]) == _normalized(name)]
            lines += [_table(matches) if matches else f"{name}: absent before and after.", ""]
    a, b = before["prospects"], after["prospects"]
    lines += ["## Prospect-only board", "",
              f"Model board rows: before={a['count']}, after={b['count']}. "
              f"Visible combined-board prospect rows: before={before['visible_prospect_count']}, "
              f"after={after['visible_prospect_count']}. "
              f"Prospect membership changed: {a['identities'] != b['identities']}. "
              f"Prospect score changed (including membership): {a['scores'] != b['scores']}. "
              f"Prospect-only rank changed (including membership): {a['ranks'] != b['ranks']}. "
              "These checks use the prospect model board's score and rank, independently of combined dynasty ranks."]
    return "\n".join(lines) + "\n"


def self_test():
    import sys
    from types import ModuleType
    from unittest.mock import patch

    row = dict(name="Juan Soto", type="mlb", role="hitter", age=28, rank=51, value=90)
    prospect = dict(name="Konnor Griffin", role="hitter", mlbam_id=1, score=80, rank=1)
    info = dict(prospects=_prospects(dict(board=[prospect])), visible_prospect_count=1)
    def with_boards(rows):
        indexed = {item["_join_key"]: item for item in _clean(rows)}
        return dict(info, boards={"board": indexed, "redraft": indexed})

    directory = Path(__file__).resolve().parent / (".board-self-test-" + uuid.uuid4().hex)
    directory.mkdir()
    try:
        out = directory
        for prefix in ("board", "redraft"):
            _write(out / f"{prefix}_before.csv", [row])
            _write(out / f"{prefix}_after.csv", [dict(row, rank=1, value=91)])
        text = summarize(out, with_boards([row]), with_boards([dict(row, rank=1, value=91)]))
        assert text.count("entered=1, left=0") == 2
        assert text.count("Matched values changed=1") == 2
        assert "Prospect-only rank changed (including membership): False" in text
        assert "| Juan Soto | mlb | hitter | 51 | 1 | 90 | 91 |" in text
        assert tuple(csv.DictReader((out / "board_before.csv").read_text().splitlines()).fieldnames) == FIELDS
        assert _normalized("Ronald Acuña Jr.") == _normalized("Ronald Acuna Jr.")
        assert _prospects(dict(board=[dict(prospect, score=81)]))["scores"] != info["prospects"]["scores"]
        assert _prospects(dict(board=[dict(prospect, rank=2)]))["ranks"] != info["prospects"]["ranks"]
        homonyms = _clean([dict(row, mlbam_id="private-first", rank=1),
                           dict(row, mlbam_id="private-second", rank=2)])
        assert len(homonyms) == 2
        moved = [dict(row, mlbam_id="private-second", rank=1, value=91),
                 dict(row, mlbam_id="private-first", rank=2, value=89)]
        old = dict(info, boards={prefix: {item["_join_key"]: item for item in homonyms}
                                for prefix in ("board", "redraft")})
        text = summarize(out, old, with_boards(moved))
        assert text.count("matched=2, added=0, removed=0") == 2
        assert text.count("before: groups=1, excess rows=1; after: groups=1, excess rows=1") == 2
        assert "| Juan Soto | mlb | hitter | 1 | 2 | 90 | 89 |" in text
        assert "| Juan Soto | mlb | hitter | 2 | 1 | 90 | 91 |" in text
        assert "private-first" not in text and "private-second" not in text
        _write(out / "board_before.csv", homonyms)
        assert "private-first" not in (out / "board_before.csv").read_text()
        assert "private-second" not in (out / "board_before.csv").read_text()
        for invalid in ([], [row, row], [dict(row, value=float("nan"))]):
            try:
                _clean(invalid)
            except ValueError:
                pass
            else:
                raise AssertionError("Invalid board accepted")
        source = directory / "source"
        for relative, payload in (
            ("data/public/public_dynasty_snapshot.json", {"players": [
                dict(row, player_type="mlb", mlbam_id=2, stats={"private": 123}),
                dict(row, player_type="mlb", mlbam_id=3, rank=50),
                dict(name=prospect["name"], player_type="prospect", role="hitter",
                     age=20, rank=52, value=78, prospect_rank=1, mlbam_id=1)]}),
            ("data/models/valucast_prospect_rank_v1.json", {"board": [prospect]}),
        ):
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")
        fake = ModuleType("scripts.compare_2027_boards")
        def fake_redraft(path, ages):
            assert path == source / "data/projections/current.json"
            assert ages == {(2, "hitter"): 28, (3, "hitter"): 28}
            return [dict(row, type=None, mlbam_id=2, stats={"private": 456}),
                    dict(row, type=None, mlbam_id=3, rank=50)]
        fake.redraft_rows = fake_redraft
        exported = directory / "exports"
        with patch.dict(sys.modules, {"scripts.compare_2027_boards": fake}):
            before = export_boards(source, exported, "before")
            after = export_boards(source, exported, "after")
        assert before == after
        assert before["prospects"] == info["prospects"] and before["visible_prospect_count"] == 1
        assert len(list(exported.iterdir())) == 4
        for path in exported.iterdir():
            with path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                assert tuple(reader.fieldnames) == FIELDS
                rows = list(reader)
                assert rows and all(set(item) == set(FIELDS) for item in rows)
        assert len(before["boards"]["board"]) == 3
        assert "Prospect score changed (including membership): False" in summarize(exported, before, after)
    finally:
        shutil.rmtree(directory)
    print("Board summary synthetic self-test passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", required=True)
    parser.parse_args()
    self_test()
