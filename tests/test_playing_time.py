import unittest

from league_values.models import PlayerProjection
from league_values.playing_time import filter_by_playing_time, strip_suffix


def _hitter(pid, pa=None, ab=None, base_id=None, name="H"):
    stats = {}
    if pa is not None:
        stats["PA"] = pa
    if ab is not None:
        stats["AB"] = ab
    meta = {"base_id": base_id} if base_id else {}
    return PlayerProjection(id=pid, name=name, pool="hitter", stats=stats, metadata=meta)


def _pitcher(pid, ip, pool="starter", base_id=None, name="P"):
    meta = {"base_id": base_id} if base_id else {}
    return PlayerProjection(id=pid, name=name, pool=pool, stats={"IP": ip}, metadata=meta)


THRESH = dict(hitter_pa=100, sp_ip=40, rp_ip=20)


class TestStripSuffix(unittest.TestCase):
    def test_strips_pitcher_suffix(self):
        self.assertEqual(strip_suffix("19755_P"), "19755")

    def test_strips_hitter_suffix(self):
        self.assertEqual(strip_suffix("19755_H"), "19755")

    def test_leaves_plain_id(self):
        self.assertEqual(strip_suffix("19755"), "19755")

    def test_leaves_base_id_namespace(self):
        self.assertEqual(strip_suffix("mlbam_660271"), "mlbam_660271")


class TestPlayingTimeFilter(unittest.TestCase):
    def test_hitter_kept_at_threshold(self):
        kept = filter_by_playing_time([_hitter("a", pa=100)], **THRESH)
        self.assertEqual([p.id for p in kept], ["a"])

    def test_hitter_dropped_below_threshold(self):
        kept = filter_by_playing_time([_hitter("a", pa=99)], **THRESH)
        self.assertEqual(kept, [])

    def test_hitter_uses_ab_when_pa_missing(self):
        kept = filter_by_playing_time([_hitter("a", ab=150)], **THRESH)
        self.assertEqual([p.id for p in kept], ["a"])

    def test_hitter_missing_volume_dropped(self):
        kept = filter_by_playing_time([_hitter("a")], **THRESH)
        self.assertEqual(kept, [])

    def test_starter_threshold(self):
        players = [_pitcher("a", 40), _pitcher("b", 39)]
        kept = filter_by_playing_time(players, **THRESH)
        self.assertEqual([p.id for p in kept], ["a"])

    def test_reliever_threshold(self):
        players = [_pitcher("a", 20, pool="reliever"), _pitcher("b", 19, pool="reliever")]
        kept = filter_by_playing_time(players, **THRESH)
        self.assertEqual([p.id for p in kept], ["a"])

    def test_generic_pitcher_uses_rp_bar(self):
        # generic 'pitcher' pool: 25 IP clears rp_ip(20) but not sp_ip(40) -> kept
        kept = filter_by_playing_time([_pitcher("a", 25, pool="pitcher")], **THRESH)
        self.assertEqual([p.id for p in kept], ["a"])

    def test_always_keep_retains_subthreshold_by_id(self):
        kept = filter_by_playing_time([_hitter("a", pa=1)], **THRESH, always_keep={"a"})
        self.assertEqual([p.id for p in kept], ["a"])

    def test_two_way_kept_by_display_id(self):
        # both rows share base_id; passing the hitter display id keeps both
        players = [
            _hitter("19755", pa=1, base_id="mlbam_660271"),
            _pitcher("19755_P", 1, base_id="mlbam_660271"),
        ]
        kept = filter_by_playing_time(players, **THRESH, always_keep={"19755"})
        self.assertEqual({p.id for p in kept}, {"19755", "19755_P"})

    def test_two_way_kept_by_suffixed_id(self):
        players = [
            _hitter("19755", pa=1, base_id="mlbam_660271"),
            _pitcher("19755_P", 1, base_id="mlbam_660271"),
        ]
        kept = filter_by_playing_time(players, **THRESH, always_keep={"19755_P"})
        self.assertEqual({p.id for p in kept}, {"19755", "19755_P"})

    def test_two_way_kept_by_base_id(self):
        players = [
            _hitter("19755", pa=1, base_id="mlbam_660271"),
            _pitcher("19755_P", 1, base_id="mlbam_660271"),
        ]
        kept = filter_by_playing_time(players, **THRESH, always_keep={"mlbam_660271"})
        self.assertEqual({p.id for p in kept}, {"19755", "19755_P"})

    def test_subthreshold_without_base_id_kept_by_stripped_id(self):
        # no base_id: matched by its own suffix-stripped id
        kept = filter_by_playing_time([_hitter("99_H", pa=1)], **THRESH, always_keep={"99"})
        self.assertEqual([p.id for p in kept], ["99_H"])
