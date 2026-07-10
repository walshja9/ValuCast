"""Synthetic StatsAPI play-by-play fixtures for pitch-discipline counting tests.

Mirrors the real feed shape: allPlays[].matchup.batter.id +
allPlays[].playEvents[] with {isPitch, details:{description,isInPlay},
pitchData:{coordinates:{pX,pZ,x,y}, strikeZoneTop, strikeZoneBottom}}.

PID is our batter; OTHER_PID's pitches must be ignored by the counter.
"""

PID = 701527          # matches the 7/10 spike proof player (Sirota)
OTHER_PID = 999999    # a different batter whose pitches must NOT be counted


def _pitch(description, *, is_in_play=False, coords=None, sz_top=None, sz_bottom=None):
    pitch_data = {}
    if coords is not None:
        pitch_data["coordinates"] = coords
    if sz_top is not None:
        pitch_data["strikeZoneTop"] = sz_top
    if sz_bottom is not None:
        pitch_data["strikeZoneBottom"] = sz_bottom
    return {
        "isPitch": True,
        "details": {"description": description, "isInPlay": is_in_play},
        "pitchData": pitch_data,
    }


# A single plate appearance for PID covering the full description taxonomy plus
# every coordinate case. Counts we expect for PID over this one play:
#   pitches = 8 (all isPitch events below)
#   swings  = 5 (swinging strike, foul, foul bunt, missed bunt, in-play)
#   whiffs  = 2 (swinging strike, missed bunt)
#   contact = 3 (foul, foul bunt, in-play)
_PID_EVENTS = [
    # Real tracked coords, clearly in-zone (|pX|<=0.83, szB<=pZ<=szT):
    _pitch("Swinging Strike",
           coords={"pX": 0.1, "pZ": 2.5, "x": 118.0, "y": 150.0},
           sz_top=3.4, sz_bottom=1.6),
    _pitch("Ball"),                                   # called ball: not a swing
    _pitch("Called Strike"),                          # called strike: not a swing
    _pitch("Foul",                                    # foul = swing + contact
           coords={"pX": 0.2, "pZ": 2.4, "x": 120.0, "y": 155.0},
           sz_top=3.4, sz_bottom=1.6),
    _pitch("Foul Bunt"),                              # bunt attempt = swing + contact
    _pitch("Missed Bunt"),                            # missed bunt = swing + whiff
    _pitch("In play, out(s)", is_in_play=True,        # in play = swing + contact
           coords={"pX": 0.0, "pZ": 2.5, "x": 116.0, "y": 148.0},
           sz_top=3.4, sz_bottom=1.6),
    # Real tracked coords, clearly OUT of zone (|pX| > 0.83); no swing here, so it
    # only affects out_zone / zone denominators, not o_swings:
    _pitch("Ball",
           coords={"pX": 1.6, "pZ": 2.5, "x": 190.0, "y": 150.0},
           sz_top=3.4, sz_bottom=1.6),
]

# A pitch to a DIFFERENT batter — must be completely ignored by the counter.
_OTHER_EVENTS = [
    _pitch("Swinging Strike",
           coords={"pX": 0.0, "pZ": 2.5, "x": 118.0, "y": 150.0},
           sz_top=3.4, sz_bottom=1.6),
]

SYNTHETIC_FEED = [
    {"matchup": {"batter": {"id": PID}}, "playEvents": _PID_EVENTS},
    {"matchup": {"batter": {"id": OTHER_PID}}, "playEvents": _OTHER_EVENTS},
]

# A second game for PID (aggregation test): 2 pitches, 1 swinging strike (whiff)
# + 1 called ball.
SECOND_GAME_FEED = [
    {
        "matchup": {"batter": {"id": PID}},
        "playEvents": [
            _pitch("Swinging Strike",
                   coords={"pX": 0.0, "pZ": 2.5, "x": 118.0, "y": 150.0},
                   sz_top=3.4, sz_bottom=1.6),
            _pitch("Ball"),
        ],
    },
]

# Pixel-only pitches (no pX/pZ) for the calibration path — mimics AA, where tracked
# coords are absent but legacy x,y + strike zone exist.
PIXEL_ONLY_EVENTS = [
    {"matchup": {"batter": {"id": PID}}, "playEvents": [
        _pitch("Foul",
               coords={"x": 118.0, "y": 150.0},   # pixel only
               sz_top=3.4, sz_bottom=1.6),
        _pitch("Ball",
               coords={"x": 200.0, "y": 150.0},   # pixel only, way outside
               sz_top=3.4, sz_bottom=1.6),
        _pitch("Called Strike"),                  # no coords at all -> zone None
    ]},
]

# Coordinate-bearing pitch with MISSING strike zone -> exercises the default-band
# fallback (the pixel classifier still returns a bool, counting toward
# zone_pitches_fallback_sz).
MISSING_SZ_EVENTS = [
    {"matchup": {"batter": {"id": PID}}, "playEvents": [
        _pitch("Ball", coords={"x": 118.0, "y": 150.0}),   # pixel, no sz_top/bottom
    ]},
]
