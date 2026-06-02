"""Player identity / age crosswalk from MLB Stats API /people."""
from __future__ import annotations

from datetime import date

from scraper.mlb_actuals import MLB_API_BASE, _fetch_json

REFERENCE_MONTH_DAY = (4, 1)  # age computed as of April 1 of the projection season


def age_for(birth_date: str | None, season: int) -> int | None:
    """Age as of April 1 of `season`. None if birth_date missing/unparseable."""
    if not birth_date:
        return None
    try:
        y, m, d = (int(x) for x in birth_date.split("-"))
    except (ValueError, AttributeError):
        return None
    ref = date(season, *REFERENCE_MONTH_DAY)
    age = ref.year - y - ((ref.month, ref.day) < (m, d))
    return age


def parse_people_payload(payload: dict) -> dict[str, dict]:
    """Convert an MLB /people response into {mlbam_id: identity record}."""
    out: dict[str, dict] = {}
    for person in payload.get("people", []):
        out[str(person["id"])] = {
            "mlbam_id": str(person["id"]),
            "name": person.get("fullName", ""),
            "birth_date": person.get("birthDate", ""),
            "bats": person.get("batSide", {}).get("code", ""),
            "throws": person.get("pitchHand", {}).get("code", ""),
        }
    return out


def fetch_identities(mlbam_ids: list[str]) -> dict[str, dict]:
    """Batch-fetch identity records. Chunks ids to keep URLs sane."""
    result: dict[str, dict] = {}
    for i in range(0, len(mlbam_ids), 100):
        chunk = mlbam_ids[i : i + 100]
        url = f"{MLB_API_BASE}/people?personIds={','.join(chunk)}"
        result.update(parse_people_payload(_fetch_json(url)))
    return result
