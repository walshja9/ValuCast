"""One-shot, separately authorized execution of the registered trajectory study.

Importing this module does no I/O. Tests supply synthetic directories and feeds.
Prediction construction has no evaluation-loader capability; scoring is a later
phase after every historical prediction artifact has been exclusively written.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from projections.backtest import mlb_trajectory_study as study  # noqa: E402

PINNED_REGISTRATION_HASH = "8d5e4f3b51975795f81ba950aa628577d1fb76c72826fcfbb5afbc81560720f1"
PINNED_CHARTER_HASH = "1a426c00ddfd96b9ed45a405d72fe22da2d234285145026cb19a51fa62e2a165"
REGISTRATION = "docs/registration-2026-11-02-mlb-trajectory.md"
RECEIPT = "docs/registration-2026-11-02-mlb-trajectory/EXECUTION-RECEIPT.md"
CHARTER = "docs/registration-2026-11-02-mlb-trajectory/EVALUATION_CHARTER.md"
HITTER_DEFAULTS = {
    "season_weights": (5.0, 4.0, 3.0), "n_reg": 1200.0,
    "k_young": 0.006, "k_old": 0.003, "pa_w1": 0.5, "pa_w2": 0.1,
    "pa_base": 200.0, "gamma": 0.0, "alpha_contact": 0.0, "alpha_power": 0.0,
}
PITCHER_DEFAULTS = {
    "season_weights": (5.0, 4.0, 3.0), "n_reg": 300.0, "era_from_fip": True,
}
SOURCE_MANIFEST = (
    "scripts/run_mlb_trajectory_study.py",
    "projections/backtest/mlb_trajectory_study.py",
    "projections/export/marcel_run.py", "projections/models/marcel_hitter.py",
    "projections/models/marcel_params.py", "projections/models/marcel_pitcher.py",
    "projections/models/pitcher_params.py", "projections/models/pitcher_role.py",
    "projections/models/league_rates.py", "projections/models/reliability.py",
    "projections/models/statcast_denoise.py", "projections/constants.py",
    "projections/data/historical.py", "projections/data/pitching_historical.py",
    "projections/data/identity.py", "projections/data/statcast.py",
    "scraper/mlb_actuals.py", "src/league_values/engine.py",
    "src/league_values/models.py", "src/league_values/post_processors.py",
    "mlb/dynasty.py", "projections/__init__.py", "projections/export/__init__.py",
    "projections/data/__init__.py", "projections/models/__init__.py",
    "projections/backtest/__init__.py", "scraper/__init__.py", "scraper/season.py",
)


def lf_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def write_json(path: Path, payload: object) -> None:
    with path.open("x", encoding="ascii", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=True, sort_keys=True, indent=2,
                  allow_nan=False)
        handle.write("\n")


def freeze_record(path: Path, record: dict) -> dict:
    if "content_hash" in record:
        raise study.StudyError("Record already contains a content hash")
    encoded = json.dumps(record, ensure_ascii=True, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("ascii")
    frozen = {**record, "content_hash": hashlib.sha256(encoded).hexdigest()}
    write_json(path, frozen)
    return frozen


def verify_record(record: dict) -> None:
    encoded = json.dumps({key: value for key, value in record.items() if key != "content_hash"},
                         ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode("ascii")
    if record.get("content_hash") != hashlib.sha256(encoded).hexdigest():
        raise study.StudyError("Frozen record hash differs")


def guard(root: Path, output: Path, environ: dict | None = None) -> None:
    environ = os.environ if environ is None else environ
    if environ.get("GITHUB_ACTIONS") != "true":
        raise study.StudyError("Hosted execution requires GITHUB_ACTIONS=true")
    if lf_hash(root / REGISTRATION) != PINNED_REGISTRATION_HASH:
        raise study.StudyError("Signed registration hash differs")
    charter = root / CHARTER
    if not charter.is_file() or lf_hash(charter) != PINNED_CHARTER_HASH:
        raise study.StudyError("Reviewed charter hash differs")
    receipt = root / RECEIPT
    if not receipt.is_file() or PINNED_REGISTRATION_HASH not in receipt.read_text(encoding="utf-8"):
        raise study.StudyError("Execution receipt is missing the signed hash")
    if output.exists():
        raise study.StudyError("Output already exists; one-shot execution only")


def _admitted_file(root: Path, relative: str) -> Path:
    if relative not in study.BUILDER_INPUT_MANIFEST:
        raise study.StudyError("Input outside finite manifest")
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise study.StudyError("Input escapes repository boundary")
    if not path.is_file():
        raise study.StudyError("A required admitted file is absent")
    return path


def create_origin_view(root: Path, origin: int, destination: Path, expected_hashes=None) -> Path:
    if not 2012 <= origin <= 2026:
        raise study.StudyError("Unregistered origin")
    destination.mkdir(parents=True, exist_ok=False)
    for relative in study.BUILDER_INPUT_MANIFEST:
        name = Path(relative).name
        if name != "identity.json" and int(Path(name).stem.rsplit("_", 1)[1]) > origin:
            continue
        source = _admitted_file(root, relative)
        target = destination / Path(relative).relative_to("projections/data")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if expected_hashes is not None and lf_hash(target) != expected_hashes[relative]:
            raise study.StudyError("Origin view differs from frozen input hash")
    return destination


def counts_only(root: Path) -> dict:
    counts = {}
    for relative in study.BUILDER_INPUT_MANIFEST:
        if relative.endswith("identity.json"):
            continue
        rows = json.loads(_admitted_file(root, relative).read_text(encoding="utf-8"))
        if not isinstance(rows, list) or len(rows) >= 5000:
            raise study.StudyError("Season row-count admission failed")
        ids = [study.asset_id(row.get("mlbam_id")) for row in rows]
        if len(set(ids)) != len(ids):
            raise study.StudyError("Season unique-identity admission failed")
        counts[relative] = len(ids)
    return counts


def default_forecast(origin: int, view: Path, identities: dict) -> dict:
    from projections.export.marcel_run import build_marcel_projections
    from projections.models.marcel_params import MarcelParams
    from projections.models.marcel_pitcher import build_pitcher_projections
    from projections.models.pitcher_params import PitcherMarcelParams

    if asdict(MarcelParams()) != HITTER_DEFAULTS or asdict(PitcherMarcelParams()) != PITCHER_DEFAULTS:
        raise study.StudyError("Default forecast parameters changed")
    # Builders use permissive missing-count defaults. Validate their entire input
    # contract first so those defaults cannot manufacture a provenance-complete F1.
    required = {
        "historical": ("PA", "AB", "H", "1B", "2B", "3B", "HR", "R", "RBI", "SB",
                       "CS", "BB", "SO", "HBP", "SF"),
        "pitching": ("IP", "BF", "K", "BB", "H_ALLOWED", "HR", "ER", "HBP", "W", "SV",
                     "GS", "G", "HLD", "QS"),
    }
    for year in range(2010, origin + 1):
        for folder, prefix in (("historical", "hitting"), ("pitching", "pitching")):
            for row in json.loads((view / folder / f"{prefix}_{year}.json").read_text(encoding="utf-8")):
                study.asset_id(row.get("mlbam_id"))
                for field in required[folder]:
                    study._number(row.get(field), "forecast dependency " + field, nonnegative=True)
    hitters = build_marcel_projections(origin + 1, view, MarcelParams(**HITTER_DEFAULTS), identities)
    pitchers = build_pitcher_projections(origin + 1, view, PitcherMarcelParams(**PITCHER_DEFAULTS))
    result = {}
    for family, rows in (("hitter", hitters), ("pitcher", pitchers)):
        mapped = {}
        for row in rows:
            pid = study.asset_id(row["metadata"]["mlbam_id"])
            if pid in mapped:
                raise study.StudyError("Duplicate forecast identity")
            mapped[pid] = row["stats"]
        result[family] = mapped
    return result


def read_origin(view: Path, origin: int) -> study.OriginData:
    seasons = {}
    for year in range(2010, origin + 1):
        seasons[year] = {
            "hitter": json.loads((view / "historical" / f"hitting_{year}.json").read_text(encoding="utf-8")),
            "pitcher": json.loads((view / "pitching" / f"pitching_{year}.json").read_text(encoding="utf-8")),
        }
    identities = json.loads((view / "identity.json").read_text(encoding="utf-8"))
    return study.OriginData(origin, seasons, identities)


def freeze_historical(origin_loader, forecaster, save) -> list[dict]:
    """Capabilities here cannot load an evaluation season after the test origin."""
    snapshots = {}
    frozen = []
    for fold in study.FOLDS:
        if fold.name == "P":
            continue
        data, view = origin_loader(fold.origin)
        for year in (*fold.training, fold.origin):
            if year not in snapshots:
                prefix, prefix_view = (data, view) if year == fold.origin else origin_loader(year)
                snapshots[year] = study.build_origin(
                    prefix, lambda d, v=prefix_view: forecaster(d.origin, v, d.identities))
        record = study.fit_origin(fold, snapshots[fold.origin], snapshots, data)
        frozen.append(save(fold.name, record))
    return frozen


def evaluate_frozen(frozen: list[dict], evaluation_loader, schedule_lengths: dict) -> tuple[dict, dict]:
    expected = [fold.name for fold in study.FOLDS if fold.name != "P"]
    if [record["fold"] for record in frozen] != expected or any("content_hash" not in r for r in frozen):
        raise study.StudyError("All four prediction records must be frozen before labels")
    for record, fold in zip(frozen, study.FOLDS[:4]):
        if record["origin"] != fold.origin:
            raise study.StudyError("Frozen fold origin differs")
        verify_record(record)
    matched, populations, sealed = {"full": [], "top300": []}, {"full": [], "top300": []}, []
    top300_evaluations = []
    for record in frozen:
        labels = evaluation_loader(record["origin"])
        scored = study.score_frozen(record, labels, schedule_lengths)
        sealed.append(scored)
        selected = {study.asset_id(pid) for pid in record["top300"]}
        top300_evaluations.append({**scored, "rows": [row for row in scored["rows"]
            if study.asset_id(row["mlbam_id"]) in selected]})
        for row in record["rows"]:
            populations["full"].append(row)
            if study.asset_id(row["mlbam_id"]) in selected:
                populations["top300"].append(row)
        for row in scored["rows"]:
            if row["complete"]:
                matched["full"].append(row)
                if study.asset_id(row["mlbam_id"]) in selected:
                    matched["top300"].append(row)
    aggregate = study.score_gates(matched, populations)
    aggregate["diagnostics"] = {
        "full": study.describe_study(sealed, frozen),
        "top300": study.describe_study(top300_evaluations, frozen, include_top50=False),
    }
    return aggregate, {"evaluations": sealed}


def assert_aggregate_safe(payload: object) -> None:
    forbidden = {"mlbam_id", "name", "player_name", "rows", "players", "top_ids"}
    if isinstance(payload, dict):
        if forbidden.intersection(payload):
            raise study.StudyError("Per-player content in aggregate output")
        if "top300" in payload and not isinstance(payload["top300"], dict):
            raise study.StudyError("Per-player membership in aggregate output")
        for value in payload.values():
            assert_aggregate_safe(value)
    elif isinstance(payload, list):
        for value in payload:
            if isinstance(value, dict) and ("role" in value or "F1" in value or "H3" in value):
                raise study.StudyError("Per-player array in aggregate output")
            assert_aggregate_safe(value)


def _without_values(payload: object) -> object:
    if isinstance(payload, dict):
        return {key: _without_values(value) for key, value in payload.items() if key != "values"}
    if isinstance(payload, list):
        return [_without_values(value) for value in payload]
    return payload


def _validate_admission(admission: dict) -> None:
    for key in ("cross_study_adjudicated", "final_2026_admitted", "lawful_use",
                "finality_departure_accepted", "identity_coverage_verified"):
        if admission.get(key) is not True:
            raise study.StudyError("Execution admission is incomplete: " + key)
    if not admission.get("revision_policy") or not admission.get("source_use_decisions"):
        raise study.StudyError("Version/revision and source-use decisions required")
    files = admission.get("files", {})
    for relative in study.BUILDER_INPUT_MANIFEST:
        metadata = files.get(relative, {})
        if not metadata.get("acquired_at") or not metadata.get("version"):
            raise study.StudyError("Input acquisition/version metadata missing")
        if relative.endswith("identity.json"):
            continue
        if metadata.get("final") is not True:
            raise study.StudyError("Season maturity not admitted")
    for year in range(2010, 2027):
        length = admission.get("schedule_lengths", {}).get(str(year))
        if not isinstance(length, (int, float)) or not 0 < length <= 162:
            raise study.StudyError("Documented league schedule length required")


def run(root: Path, output: Path, admission: dict) -> dict:
    guard(root, output)
    _validate_admission(admission)
    output.mkdir(parents=True, exist_ok=False)
    sealed = output / "sealed"
    sealed.mkdir()
    write_json(sealed / "access-ledger.json", {
        "phase": "hashes-before-rows", "started_at": datetime.now(timezone.utc).isoformat(),
        "admission": admission, "historical_evidence": "development-class; exposed",
    })
    source_diff = subprocess.run(
        ["git", "diff", "--no-ext-diff", "--", *SOURCE_MANIFEST], cwd=root,
        check=True, capture_output=True, text=True).stdout
    custody = freeze_record(sealed / "custody.json", {
        "registration": lf_hash(root / REGISTRATION), "charter": lf_hash(root / CHARTER),
        "receipt": lf_hash(root / RECEIPT), "source_diff": source_diff,
        "sources": {p: lf_hash(root / p) for p in SOURCE_MANIFEST},
        "inputs": {p: {**admission["files"][p], "lf_sha256": lf_hash(_admitted_file(root, p))}
                   for p in study.BUILDER_INPUT_MANIFEST},
        "defaults": {"hitter": HITTER_DEFAULTS, "pitcher": PITCHER_DEFAULTS},
        "folds": [asdict(fold) for fold in study.FOLDS],
        "seed": 20261001, "bootstrap_replicates": 2000,
        "gate_definitions": ["full frozen universe", "frozen F1 top 300; numeric id ties"],
        "reference": "pooled positive role-seasons y-2:y; population SD; raw validated",
        "rules": "PA/IP eligibility; PA>=BF hitter; GS/G>=0.5 SP; true innings; AB<=30/IP<=10 zero",
        "outputs": {"aggregate": (output / "aggregate.json").as_posix(), "sealed": sealed.as_posix()},
        "protected_study_exclusions": admission["source_use_decisions"],
    })
    write_json(sealed / "counts.json", counts_only(root))
    write_json(sealed / "counts-passed.json", {"phase": "counts passed; prediction access begins",
        "at": datetime.now(timezone.utc).isoformat()})
    input_hashes = {p: metadata["lf_sha256"] for p, metadata in custody["inputs"].items()}
    views = {}

    def origin_loader(year):
        if year not in views:
            views[year] = create_origin_view(root, year, sealed / "views" / str(year), input_hashes)
        return read_origin(views[year], year), views[year]

    frozen = freeze_historical(
        origin_loader, default_forecast,
        lambda name, record: freeze_record(sealed / (name + "-predictions.json"), record))
    freeze_record(sealed / "all-predictions-frozen.json", {
        "records": {r["fold"]: r["content_hash"] for r in frozen},
        "at": datetime.now(timezone.utc).isoformat()})
    # Evaluation access is created only after the all-fold prediction barrier.
    def evaluation_loader(origin):
        seasons = {}
        for year in range(origin + 1, origin + 4):
            seasons[year] = {}
            for family, folder, prefix in (("hitter", "historical", "hitting"),
                                            ("pitcher", "pitching", "pitching")):
                relative = f"projections/data/{folder}/{prefix}_{year}.json"
                path = _admitted_file(root, relative)
                if lf_hash(path) != input_hashes[relative]:
                    raise study.StudyError("Evaluation input differs from frozen hash")
                seasons[year][family] = json.loads(path.read_text(encoding="utf-8"))
        return study.OriginData(origin + 3, seasons, origin_loader(origin)[0].identities)

    write_json(sealed / "evaluation-access.json", {"phase": "evaluation labels accessible; exposure spent",
        "at": datetime.now(timezone.utc).isoformat()})
    aggregate, evaluations = evaluate_frozen(frozen, evaluation_loader, admission["schedule_lengths"])
    write_json(sealed / "evaluations.json", evaluations)
    assert_aggregate_safe(aggregate)
    write_json(output / "aggregate.json", aggregate)
    return aggregate


def prospective_freeze(root: Path, output: Path, admission: dict, authority: dict,
                       transfer_loader=None) -> None:
    """Separate authority and exclusive records; transfer cutoff precedes feed access."""
    guard(root, output)
    _validate_admission(admission)
    if authority.get("prospective_freeze_authorized") is not True:
        raise study.StudyError("Separate prospective authority required")
    if authority.get("before_first_2027_game_attested") is not True:
        raise study.StudyError("Timely prospective authority required")
    cutoff = authority.get("transfer_acquired_at")
    if transfer_loader is None or not cutoff or authority.get("first_full_season_2027_feed") is not True:
        raise study.StudyError("First full-season 2027 transfer feed and its cutoff required")
    if authority.get("transfer_system") != "Steamer" or authority.get("transfer_season") != 2027:
        raise study.StudyError("Transfer provenance must identify full-season 2027 Steamer")
    if not authority.get("transfer_eligibility_and_role_provenance"):
        raise study.StudyError("Admitted transfer eligibility and routed-role provenance required")
    try:
        parsed_cutoff = datetime.fromisoformat(cutoff)
        if parsed_cutoff.tzinfo is None:
            raise ValueError("timezone missing")
    except (TypeError, ValueError) as exc:
        raise study.StudyError("Transfer acquisition cutoff requires an aware timestamp") from exc
    output.mkdir(parents=True, exist_ok=False)
    sealed = output / "sealed"
    sealed.mkdir()
    freeze_record(sealed / "authority-before-access.json", {"authority": authority, "admission": admission,
        "registered_information_cutoff": "2026-11-01T00:00:00-04:00",
        "transfer_information_cutoff": cutoff})
    # Reuse the same finite custody and counts requirements in a separate namespace.
    custody = freeze_record(sealed / "custody.json", {
        "registration": lf_hash(root / REGISTRATION), "charter": lf_hash(root / CHARTER),
        "receipt": lf_hash(root / RECEIPT),
        "source_diff": subprocess.run(["git", "diff", "--no-ext-diff", "--", *SOURCE_MANIFEST],
            cwd=root, check=True, capture_output=True, text=True).stdout,
        "sources": {p: lf_hash(root / p) for p in SOURCE_MANIFEST},
        "inputs": {p: lf_hash(_admitted_file(root, p)) for p in study.BUILDER_INPUT_MANIFEST},
        "defaults": {"hitter": HITTER_DEFAULTS, "pitcher": PITCHER_DEFAULTS},
        "folds": [asdict(fold) for fold in study.FOLDS], "output": output.as_posix(),
    })
    write_json(sealed / "counts.json", counts_only(root))
    fold = next(f for f in study.FOLDS if f.name == "P")
    data_views, snapshots = {}, {}
    for year in (*fold.training, fold.origin):
        view = create_origin_view(root, year, sealed / "views" / str(year), custody["inputs"])
        data_views[year] = read_origin(view, year)
        snapshots[year] = study.build_origin(
            data_views[year], lambda d, v=view: default_forecast(d.origin, v, d.identities))
    record = study.fit_origin(fold, snapshots[2026], snapshots, data_views[2026])
    record.update(information_cutoff="2026-11-01T00:00:00-04:00", kind="registered Marcel T_2026")
    freeze_record(sealed / "P-Marcel.json", record)
    feed = transfer_loader()
    transfer = study.build_transfer(record, feed, data_views[2026].identities)
    transfer.update(information_cutoff=cutoff, kind="Steamer transfer check; not T_2026 prediction")
    freeze_record(sealed / "P-Steamer-transfer.json", transfer)
    write_json(output / "aggregate.json", {"status": "FROZEN", "records": 2,
                                          "confirmation": "pending final admitted 2029 labels"})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("historical", "prospective"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--admission", type=Path, required=True)
    parser.add_argument("--authority", type=Path)
    parser.add_argument("--transfer-feed", type=Path)
    args = parser.parse_args(argv)
    # Guard precedes even admission/feed access, as well as all actuals access.
    guard(args.root, args.output)
    admission = json.loads(args.admission.read_text(encoding="utf-8"))
    try:
        if args.command == "historical":
            result = run(args.root, args.output, admission)
            print(json.dumps(_without_values(result), ensure_ascii=True, sort_keys=True, allow_nan=False))
        else:
            if args.authority is None or args.transfer_feed is None:
                raise study.StudyError("Prospective command requires separate authority and feed")
            authority = json.loads(args.authority.read_text(encoding="utf-8"))
            if authority.get("transfer_feed_path") != args.transfer_feed.resolve().as_posix():
                raise study.StudyError("Transfer feed path differs from pre-access authority")
            def transfer_loader():
                if authority.get("transfer_feed_lf_sha256") != lf_hash(args.transfer_feed):
                    raise study.StudyError("Transfer feed differs from pre-access authority")
                return json.loads(args.transfer_feed.read_text(encoding="utf-8"))

            prospective_freeze(args.root, args.output, admission, authority,
                               transfer_loader)
            print('{"status":"FROZEN","records":2}')
    except BaseException as exc:
        try:
            if (args.output / "sealed").is_dir():
                with (args.output / "sealed" / "native-failure.txt").open("x", encoding="utf-8") as handle:
                    traceback.print_exc(file=handle)
        except BaseException:
            pass
        # Native traceback is sealed; public logs contain no exception row values.
        print('{"status":"STOPPED","native_failure":"sealed"}')
        if isinstance(exc, SystemExit):
            return exc.code if isinstance(exc.code, int) and exc.code != 0 else 1
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
