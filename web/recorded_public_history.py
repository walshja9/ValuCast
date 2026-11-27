"""Prospective accepted-public values over explicitly retained legacy history.

Only prior canonical own rows are promoted. The current candidate is not accepted
evidence until a later caller supplies its exact bytes as the canonical prior.
Point epochs identify actual metadata provenance; comparison epochs change only
when a known method component changes. Missing metadata never supplies a method.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math

LIMIT = 30
BASIS = "recorded_canonical_public_row_value"
BRIDGE = "mlb_prospect_bridge"
PROSPECT_UNIT = "0_100_valucast_prospect_score"
DOMAINS = {"mlb", "prospect", BRIDGE}
ROLES = {"hitter", "pitcher", "two_way"}


def _day(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date().isoformat()
    except (TypeError, ValueError):
        raise ValueError("Public history requires a valid canonical date") from None


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _scale(row):
    context = row.get("context")
    calibration = context.get("cross_universe_calibration") if isinstance(context, dict) else None
    calibration = calibration if isinstance(calibration, dict) else {}
    raw = calibration.get("raw_value_scale")
    if (calibration.get("unit_mapping_applied") is False and calibration.get("value_mutation") == "none"
            and isinstance(raw, str) and raw):
        return raw
    return row.get("value_scale")


def _key(row):
    if not isinstance(row, dict):
        raise ValueError("Malformed public history identity record")
    identity, domain, role = row.get("mlbam_id"), row.get("player_type", row.get("domain")), row.get("role")
    if domain == "mlb" and row.get("active_mlb_callup_bridge") is True:
        if _scale(row) != PROSPECT_UNIT:
            raise ValueError("Bridge valuation unit is unqualified")
        domain = BRIDGE
    if isinstance(identity, bool) or not str(identity or "").isdigit() or domain not in DOMAINS or role not in ROLES:
        raise ValueError("Public history requires explicit MLBAM identity, domain and valuation role")
    return str(int(identity)), domain, role


def _method(payload, domain):
    artifacts = payload.get("input_artifacts")
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    if domain == "mlb":
        return {"method_id": artifacts.get("mlb_dynasty_method_id")}
    return {"rank_version": artifacts.get("prospect_rank_v1_version"),
            "score_source": artifacts.get("prospect_score_source")}


def _valid_method(method, domain):
    keys = {"method_id"} if domain == "mlb" else {"rank_version", "score_source"}
    return (isinstance(method, dict) and set(method) == keys
            and all(value is None or isinstance(value, str) and bool(value) for value in method.values()))


def _known(method):
    return all(isinstance(value, str) and bool(value) for value in method.values())


def _rows(payload):
    rows, groups = {}, {}
    skipped = {"unqualified_identity_or_role": 0, "unqualified_value_or_unit": 0, "ambiguous_identity_rows": 0}
    for row in payload.get("players", []):
        try:
            key = _key(row)
        except ValueError:
            skipped["unqualified_identity_or_role"] += 1
            continue
        groups.setdefault(key[0], []).append((key, row))
    for group in groups.values():
        if len(group) != 1:
            skipped["ambiguous_identity_rows"] += len(group)
            continue
        key, row = group[0]
        if not _finite(row.get("value")) or not isinstance(_scale(row), str) or not _scale(row):
            skipped["unqualified_value_or_unit"] += 1
            continue
        rows[key] = row
    return rows, skipped


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate public history JSON key")
        result[key] = value
    return result


def _prior(raw):
    if raw is None:
        return None
    if not isinstance(raw, bytes) or not raw:
        raise ValueError("Prior canonical snapshot must be nonempty explicit bytes")
    try:
        payload = json.loads(raw, object_pairs_hook=_object)
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("Malformed prior canonical snapshot") from None
    if (not isinstance(payload, dict) or payload.get("artifact") != "valucast_public_dynasty_snapshot"
            or not isinstance(payload.get("players"), list)):
        raise ValueError("Prior input is not a canonical public snapshot")
    _day(payload.get("generated_at"))
    artifacts = payload.get("input_artifacts")
    if artifacts is not None and not isinstance(artifacts, dict):
        raise ValueError("Malformed prior public method metadata")
    if any(not _valid_method(_method(payload, domain), domain) for domain in DOMAINS):
        raise ValueError("Malformed prior public method contract")
    return payload


def _validate_carrier(carrier, prior_date):
    if (not isinstance(carrier, dict) or type(carrier.get("schema_version")) is not int
            or carrier["schema_version"] != 1 or carrier.get("basis") != BASIS or carrier.get("as_of") != prior_date):
        raise ValueError("Unknown or malformed recorded public history carrier")
    digest = carrier.get("previous_snapshot_sha256")
    if digest is not None and (not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)):
        raise ValueError("Malformed public history prior-input digest")
    dates = carrier.get("accepted_dates")
    if (not isinstance(dates, list) or len(dates) > LIMIT or dates != sorted(set(dates))
            or any(_day(day) != day or day > prior_date for day in dates)):
        raise ValueError("Malformed accepted publication-date window")
    domains = carrier.get("domains")
    if not isinstance(domains, dict) or set(domains) != DOMAINS:
        raise ValueError("Malformed public history domains")
    for domain, state in domains.items():
        if (not isinstance(state, dict) or type(state.get("epoch")) is not int or state["epoch"] < 1
                or not _valid_method(state.get("method"), domain) or not isinstance(state.get("epochs"), dict)
                or type(state.get("comparison_epoch")) is not int or not 1 <= state["comparison_epoch"] <= state["epoch"]
                or not _valid_method(state.get("comparison_method"), domain)
                or any(value is not None and state["comparison_method"].get(name) != value for name, value in state["method"].items())):
            raise ValueError("Malformed public history comparison epoch")
        for epoch, metadata in state["epochs"].items():
            if (not epoch.isdigit() or not 1 <= int(epoch) <= state["epoch"] or not isinstance(metadata, dict)
                    or not _valid_method(metadata.get("method"), domain)
                    or type(metadata.get("comparison_epoch")) is not int
                    or not 1 <= metadata["comparison_epoch"] <= state["comparison_epoch"]
                    or metadata.get("scale") is not None and not isinstance(metadata["scale"], str)):
                raise ValueError("Malformed public history epoch provenance")
        comparison_order = [state["epochs"][epoch]["comparison_epoch"] for epoch in sorted(state["epochs"], key=int)]
        if comparison_order != sorted(comparison_order):
            raise ValueError("Public comparison epochs are out of publication order")
        if state["epochs"].get(str(state["epoch"])) != {
                "method": state["method"], "scale": state.get("scale"), "comparison_epoch": state["comparison_epoch"]}:
            raise ValueError("Current public history epoch provenance conflicts")
        if state.get("since") is not None and (_day(state["since"]) != state["since"] or state["since"] > prior_date):
            raise ValueError("Future public history method boundary")
    identities = {}
    if not isinstance(carrier.get("identities"), list) or not isinstance(carrier.get("observations"), list):
        raise ValueError("Malformed public history records")
    for state in carrier["identities"]:
        key = _key(state)
        if key[:2] in identities or type(state.get("epoch")) is not int or state["epoch"] < 1:
            raise ValueError("Duplicate or malformed public history role epoch")
        if state.get("since") is not None and (_day(state["since"]) != state["since"] or state["since"] > prior_date):
            raise ValueError("Future public history role boundary")
        identities[key[:2]] = state
    active = carrier.get("active_domains")
    if not isinstance(active, dict) or any(not identity.isdigit() or domain not in DOMAINS or (identity, domain) not in identities for identity, domain in active.items()):
        raise ValueError("Malformed active public valuation domain")
    seen, accepted_dates = set(), set(dates)
    for group in carrier["observations"]:
        key = _key(group)
        if (set(group) != {"mlbam_id", "domain", "role", "points"} or key in seen or key[:2] not in identities
                or not isinstance(group.get("points"), list) or not 1 <= len(group["points"]) <= LIMIT):
            raise ValueError("Malformed or duplicate public history observation group")
        seen.add(key)
        point_dates = set()
        for point in group["points"]:
            # Fixed tuple: canonical date, public value, method epoch, role epoch.
            if (not isinstance(point, (list, tuple)) or len(point) != 4
                    or not isinstance(point[0], str) or point[0] not in accepted_dates or point[0] in point_dates
                    or not _finite(point[1]) or type(point[2]) is not int or str(point[2]) not in domains[key[1]]["epochs"]
                    or type(point[3]) is not int or not 1 <= point[3] <= identities[key[:2]]["epoch"]
                    or point[3] == identities[key[:2]]["epoch"] and key[2] != identities[key[:2]]["role"]):
                raise ValueError("Malformed, duplicate or future recorded public observation")
            metadata = domains[key[1]]["epochs"][str(point[2])]
            if not isinstance(metadata["scale"], str) or metadata["scale"] != domains[key[1]]["scale"]:
                raise ValueError("Recorded units require an explicit movement migration")
            point_dates.add(point[0])


def _check_canonical_consistency(payload, carrier, rows):
    """One shared invariant for prior preflight, promotion and the new candidate."""
    for domain in DOMAINS:
        scales = {_scale(row) for key, row in rows.items() if key[1] == domain}
        if len(scales) > 1:
            raise ValueError("Canonical valuation units conflict within domain")
        if carrier is not None and _method(payload, domain) != carrier["domains"][domain]["method"]:
            raise ValueError("Canonical method metadata conflicts with carrier provenance")
    if carrier is None:
        return
    roles = {_key(state)[:2]: state for state in carrier["identities"]}
    for key, row in rows.items():
        state = roles.get(key[:2])
        if (state is None or state["role"] != key[2] or carrier["active_domains"].get(key[0]) != key[1]
                or _scale(row) != carrier["domains"][key[1]]["scale"]):
            raise ValueError("Canonical own row conflicts with carried role/domain/unit provenance")


def _validated_prior(raw):
    prior = _prior(raw)
    if prior is None:
        return None, None, {}, {}
    carrier = None
    if "recorded_public_history" in prior:
        carrier = prior["recorded_public_history"]
        _validate_carrier(carrier, _day(prior["generated_at"]))
    rows, skips = _rows(prior)
    _check_canonical_consistency(prior, carrier, rows)
    return prior, carrier, rows, skips


def validate_prior_canonical_snapshot(raw):
    if _validated_prior(raw)[0] is None:
        raise ValueError("An explicit prior canonical snapshot is required")


def _series(points):
    result = {}
    for point in points or []:
        if not isinstance(point, (list, tuple)) or len(point) != 2 or not _finite(point[1]):
            raise ValueError("Malformed legacy public history point")
        day = _day(point[0])
        if day in result:
            raise ValueError("Duplicate legacy public history date")
        result[day] = point[1]
    return result


def apply_recorded_public_history(payload, previous_public_snapshot_bytes=None, *, legacy_mlb_policy=None,
                                  prospect_history_epoch_date=None):
    """Pure prospective overlay; retain legacy values without certifying their basis."""
    result = deepcopy(payload)
    current_date = _day(result.get("generated_at"))
    current, current_skips = _rows(result)
    prior, carrier, prior_rows, prior_skips = _validated_prior(previous_public_snapshot_bytes)
    prior_date = _day(prior["generated_at"]) if prior else None
    if prior_date and current_date < prior_date:
        raise ValueError("Stale public history build cannot replace later observations")
    states = deepcopy(carrier["domains"]) if carrier else {}
    roles = {_key(state)[:2]: deepcopy(state) for state in (carrier or {}).get("identities", [])}
    active = deepcopy((carrier or {}).get("active_domains", {}))
    observations = {_key(group): {point[0]: tuple(point) for point in group["points"]}
                    for group in (carrier or {}).get("observations", [])}
    dates = sorted(set((carrier or {}).get("accepted_dates", []) + ([prior_date] if prior_date else [])))[-LIMIT:]
    for domain in sorted(DOMAINS):
        if domain not in states:
            scales = {_scale(row) for key, row in prior_rows.items() if key[1] == domain}
            method, scale = _method(prior or result, domain), next(iter(scales), None)
            states[domain] = {"method": method, "scale": scale, "epoch": 1, "since": None,
                              "comparison_method": deepcopy(method), "comparison_epoch": 1,
                              "epochs": {"1": {"method": method, "scale": scale, "comparison_epoch": 1}}}
    for key, row in prior_rows.items():
        state = roles.setdefault(key[:2], {"mlbam_id": key[0], "domain": key[1], "role": key[2], "epoch": 1, "since": None})
        active[key[0]] = key[1]
        domain = states[key[1]]
        method, scale = _method(prior, key[1]), _scale(row)
        epoch = domain["epoch"]
        domain["epochs"][str(epoch)] = {"method": method, "scale": scale, "comparison_epoch": domain["comparison_epoch"]}
        observations.setdefault(key, {})[prior_date] = (prior_date, row["value"], epoch, state["epoch"])
    for domain, state in states.items():
        scales = {_scale(row) for key, row in current.items() if key[1] == domain}
        if len(scales) > 1:
            raise ValueError("Conflicting current valuation units")
        scale = next(iter(scales), state["scale"])
        if state["scale"] is not None and scale != state["scale"]:
            raise ValueError("Public unit/scale change requires an explicit movement migration")
        method = _method(result, domain)
        if not _valid_method(method, domain):
            raise ValueError("Malformed current public method contract")
        # Preserve missing metadata honestly without treating disappearance as
        # evidence of a different method or changing legacy-selected membership.
        changed = any(value is not None and state["comparison_method"].get(name) is not None
                      and state["comparison_method"][name] != value for name, value in method.items())
        if state["method"] != method:
            state["epoch"] += 1
        if changed:
            state.update(comparison_epoch=state["comparison_epoch"] + 1, since=current_date)
        state["comparison_method"].update({name: value for name, value in method.items() if value is not None})
        state.update(method=method, scale=scale)
        state["epochs"][str(state["epoch"])] = {"method": method, "scale": scale, "comparison_epoch": state["comparison_epoch"]}
    for key in current:
        state = roles.setdefault(key[:2], {"mlbam_id": key[0], "domain": key[1], "role": key[2], "epoch": 1, "since": None})
        if state["role"] != key[2] or key[0] in active and active[key[0]] != key[1]:
            state.update(role=key[2], epoch=state["epoch"] + 1, since=current_date)
        active[key[0]] = key[1]
    by_key, by_identity, accepted_dates = {}, {}, set(dates)
    for key, dated_points in observations.items():
        points = sorted(point for day, point in dated_points.items() if day in accepted_dates)
        if points:
            by_key[key] = points
            by_identity.setdefault(key[0], []).append((key, points))
    retained = [{"mlbam_id": key[0], "domain": key[1], "role": key[2], "points": by_key[key]}
                for key in sorted(by_key)]
    live_keys = {key[:2] for key in by_key} | {key[:2] for key in current}
    roles = {key: state for key, state in roles.items() if key in live_keys}
    active = {identity: domain for identity, domain in active.items() if (identity, domain) in roles}
    for domain, state in states.items():
        needed = {str(state["epoch"])} | {str(point[2]) for key, points in by_key.items() if key[1] == domain for point in points}
        state["epochs"] = {epoch: metadata for epoch, metadata in state["epochs"].items() if epoch in needed}
    view_dates = set(sorted(set(dates + [current_date]))[-LIMIT:])
    prospect_cutoff = _day(prospect_history_epoch_date) if prospect_history_epoch_date is not None else None
    for key, row in current.items():
        context = row.setdefault("context", {})
        cutoff = prospect_cutoff if key[1] == "prospect" else None
        if cutoff and current_date < cutoff:
            # Preserve the existing prospect display policy, not a new method.
            for name in ("value_history", "chart_value_history", "value_history_basis"):
                context.pop(name, None)
            continue
        full = _series(context.get("value_history"))
        chart = _series(context.get("chart_value_history", context.get("value_history")))
        if cutoff:
            full = {day: value for day, value in full.items() if day >= cutoff}
            chart = {day: value for day, value in chart.items() if day >= cutoff}
        if key[1] == BRIDGE:
            # These legacy points were attached from MLB archives, not from
            # this bridge's prospect-valued method. Keep full records only.
            chart.clear()
        if any(day > current_date for day in full.keys() | chart.keys()):
            raise ValueError("Future legacy point cannot enter a stale public build")
        domain, role = states[key[1]], roles[key[:2]]
        lower = [value for value in (domain["since"], role["since"]) if value]
        boundary = max(lower) if lower else None
        raw_boundary = (legacy_mlb_policy or {}).get("latest_incompatible_date") if key[1] == "mlb" else None
        if raw_boundary and (_day(raw_boundary) != raw_boundary or raw_boundary > current_date):
            raise ValueError("Invalid legacy method boundary")
        chart = {day: value for day, value in chart.items()
                 if (not boundary or day >= boundary) and (not raw_boundary or day > raw_boundary)}
        recorded = set()
        for point in by_key.get(key, []):
            point_date, point_value, epoch, role_epoch = point
            if point_date not in view_dates or cutoff and point_date < cutoff:
                continue
            full[point_date] = point_value
            recorded.add(point_date)
            metadata = domain["epochs"][str(epoch)]
            same = (metadata["comparison_epoch"] == domain["comparison_epoch"]
                    and role_epoch == role["epoch"] and metadata["scale"] == _scale(row)
                    and (not boundary or point_date >= boundary) and (not raw_boundary or point_date > raw_boundary))
            known = _known(metadata["method"]) and metadata["method"] == domain["comparison_method"]
            selected_legacy = point_date in chart and not _known(metadata["method"])
            if same and (known or selected_legacy):
                chart[point_date] = point_value
        full[current_date] = chart[current_date] = row["value"]
        context["value_history"] = sorted(full.items())[-LIMIT:]
        context["chart_value_history"] = sorted(chart.items())[-LIMIT:]
        retained_dates = {day for day, _ in context["value_history"]}
        legacy_dates = retained_dates - recorded - {current_date}
        known_other = {point[0] for other_key, points in by_identity.get(key[0], [])
                       if other_key != key for point in points if point[0] in legacy_dates}
        if key[1] == BRIDGE:
            known_other.update(legacy_dates)
        context["value_history_basis"] = {"basis": "legacy_with_recorded_public_overlay",
            "recorded_points": sum(day in recorded and day != current_date for day, _ in context["value_history"]),
            "legacy_points": sum(day not in recorded and day != current_date for day, _ in context["value_history"]),
            "current_point": "current_final_candidate_row", "legacy_role_provenance": "unqualified",
            "movement_comparable": not bool(known_other), "known_other_valuation_dates": len(known_other)}
    result["recorded_public_history"] = {"schema_version": 1, "basis": BASIS, "as_of": current_date,
        "previous_snapshot_sha256": hashlib.sha256(previous_public_snapshot_bytes).hexdigest() if previous_public_snapshot_bytes is not None else None,
        "accepted_dates": dates, "domains": states, "active_domains": active,
        "identities": [roles[key] for key in sorted(roles)], "observations": retained,
        "skipped_rows": {"current": current_skips, "prior": prior_skips}}
    _validate_carrier(result["recorded_public_history"], current_date)
    _check_canonical_consistency(result, result["recorded_public_history"], current)
    return result
