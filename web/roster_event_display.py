"""Presentation badges for independently evidenced MLB roster and debut facts."""


def roster_event_badges(
    *, roster_listed=False, on_40_man=False, active_roster=False,
    debut_recorded=False, rule_5_protection=False,
):
    """Return labels and tooltips for literal True facts."""
    badges = []
    if on_40_man is True:
        protected = rule_5_protection is True
        badges.append({
            "kind": "40_man",
            "label": "40-man roster · Rule 5 protection" if protected else "40-man roster",
            "title": "Added to the 40-man roster for Rule 5 protection." if protected else "Listed on the MLB 40-man roster.",
        })
    if active_roster is True:
        badges.append({
            "kind": "active",
            "label": "Active MLB roster",
            "title": "Listed on the active MLB roster.",
        })
    if roster_listed is True and on_40_man is not True and active_roster is not True:
        badges.append({
            "kind": "roster_listed",
            "label": "MLB roster listed — active status unverified",
            "title": "Roster data lists this prospect. Active roster status is unverified.",
        })
    if debut_recorded is True:
        badges.append({
            "kind": "debut",
            "label": "MLB debut recorded",
            "title": "An MLB appearance is recorded.",
        })
    return badges
