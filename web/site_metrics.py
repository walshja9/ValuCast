"""First-party, privacy-preserving site metrics (owner-scoped, 2026-07-30).

Narrow by design — NOT an analytics platform. Tracks ONLY what the owner
authorized: pageviews by ROUTE PATTERN (never raw paths), anonymous
unique/returning visitors via the random first-party vc_vid cookie, referrer
domain + UTM fields, X-visit classification, and three named click events
(share_card, trade_analyzer, outbound). NO raw IP, NO stored user agent, NO
fingerprinting — the schema has no column that could hold them, and the
public summary is aggregates only.

Persistence is SQLite at VALUCAST_ANALYTICS_DB (the Render persistent disk),
because "returning visitor" is knowingly false if the store dies with each
deploy. With the env var unset the store is a silent no-op: recording and
summarizing must never break a page or a test run.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Bounded field widths: this store aggregates, it does not archive payloads.
_MAX_ROUTE = 120
_MAX_FIELD = 100

# Retention bound (days). Long enough for year-over-year growth comparisons,
# short enough that the table cannot grow without limit.
RETENTION_DAYS = 400

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    route TEXT,
    metric TEXT,
    target_domain TEXT,
    vid TEXT,
    is_new INTEGER,
    referrer_domain TEXT,
    utm_source TEXT,
    utm_medium TEXT,
    utm_campaign TEXT,
    from_x INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_events_kind_ts ON events(kind, ts);
"""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clip(value, limit: int):
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:limit] if value else None


class SiteMetricsStore:
    """Append-only event store + aggregate reader over one SQLite file.

    Every write is wrapped so a metrics failure can never surface as a page
    error — the site's job is serving values, not counting visits.
    """

    def __init__(self, db_path: str | None) -> None:
        self.db_path = str(db_path) if db_path else None
        if self.db_path:
            try:
                Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
                with self._connect() as con:
                    con.executescript(_SCHEMA)
                self.prune()
            except Exception:
                # An unwritable disk disables metrics, never the site.
                self.db_path = None

    @property
    def enabled(self) -> bool:
        return self.db_path is not None

    def _connect(self) -> sqlite3.Connection:
        # Near-zero busy timeout (review F3): the recorder runs synchronously
        # inside after_request, so a locked database must DROP the event, not
        # hold the response. Lost analytics beat delayed pages.
        con = sqlite3.connect(self.db_path, timeout=0.05)
        con.execute("PRAGMA journal_mode=WAL")
        return con

    # -- writers ------------------------------------------------------------
    def record_pageview(
        self,
        *,
        route: str,
        vid: str,
        is_new_visitor: bool,
        referrer_domain: str | None = None,
        utm_source: str | None = None,
        utm_medium: str | None = None,
        utm_campaign: str | None = None,
        from_x: bool = False,
        ts: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        try:
            with self._connect() as con:
                con.execute(
                    "INSERT INTO events (ts, kind, route, vid, is_new,"
                    " referrer_domain, utm_source, utm_medium, utm_campaign,"
                    " from_x) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        ts or _utc_now_iso(),
                        "pageview",
                        _clip(route, _MAX_ROUTE),
                        _clip(vid, _MAX_FIELD),
                        1 if is_new_visitor else 0,
                        _clip(referrer_domain, _MAX_FIELD),
                        _clip(utm_source, _MAX_FIELD),
                        _clip(utm_medium, _MAX_FIELD),
                        _clip(utm_campaign, _MAX_FIELD),
                        1 if from_x else 0,
                    ),
                )
        except Exception:
            pass

    def record_click(
        self,
        *,
        metric: str,
        target_domain: str | None = None,
        vid: str | None = None,
        ts: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        try:
            with self._connect() as con:
                con.execute(
                    "INSERT INTO events (ts, kind, metric, target_domain, vid)"
                    " VALUES (?,?,?,?,?)",
                    (
                        ts or _utc_now_iso(),
                        "click",
                        _clip(metric, _MAX_FIELD),
                        _clip(target_domain, _MAX_FIELD),
                        _clip(vid, _MAX_FIELD),
                    ),
                )
        except Exception:
            pass

    def prune(self, keep_days: int = RETENTION_DAYS) -> None:
        if not self.enabled:
            return
        try:
            cutoff = (
                datetime.now(timezone.utc) - timedelta(days=keep_days)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            with self._connect() as con:
                con.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
        except Exception:
            pass

    # -- reader -------------------------------------------------------------
    def summary(self, days: int = 30) -> dict:
        """Aggregates only — no event rows, no visitor ids, ever."""
        if not self.enabled:
            return {"enabled": False}
        try:
            cutoff = (
                datetime.now(timezone.utc) - timedelta(days=days)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            with self._connect() as con:
                def q(sql, args=()):
                    return con.execute(sql, (cutoff, *args)).fetchall()

                total = q(
                    "SELECT COUNT(*) FROM events"
                    " WHERE kind='pageview' AND ts >= ?"
                )[0][0]
                by_route = q(
                    "SELECT route, COUNT(*) AS n FROM events"
                    " WHERE kind='pageview' AND ts >= ? AND route IS NOT NULL"
                    " GROUP BY route ORDER BY n DESC, route LIMIT 20"
                )
                unique = q(
                    "SELECT COUNT(DISTINCT vid) FROM events"
                    " WHERE kind='pageview' AND ts >= ? AND vid IS NOT NULL"
                )[0][0]
                # Returning (review F2): a visitor whose EARLIEST stored
                # pageview predates the window and who appeared inside it — a
                # same-window revisit five seconds later is not a return. The
                # is_new cookie flag is recorded but deliberately not trusted
                # here.
                returning = q(
                    "SELECT COUNT(*) FROM ("
                    " SELECT vid FROM events"
                    " WHERE kind='pageview' AND vid IS NOT NULL"
                    " GROUP BY vid"
                    " HAVING MAX(ts) >= ? AND MIN(ts) < ?"
                    ")",
                    args=(cutoff,),
                )[0][0]
                referrers = q(
                    "SELECT referrer_domain, COUNT(*) AS n FROM events"
                    " WHERE kind='pageview' AND ts >= ?"
                    " AND referrer_domain IS NOT NULL"
                    " GROUP BY referrer_domain ORDER BY n DESC,"
                    " referrer_domain LIMIT 10"
                )
                campaigns = q(
                    "SELECT utm_source, utm_campaign, COUNT(*) AS n FROM events"
                    " WHERE kind='pageview' AND ts >= ?"
                    " AND (utm_source IS NOT NULL OR utm_campaign IS NOT NULL)"
                    " GROUP BY utm_source, utm_campaign"
                    " ORDER BY n DESC LIMIT 10"
                )
                x_visits = q(
                    "SELECT COUNT(*) FROM events"
                    " WHERE kind='pageview' AND ts >= ? AND from_x = 1"
                )[0][0]
                clicks = q(
                    "SELECT metric, COUNT(*) AS n FROM events"
                    " WHERE kind='click' AND ts >= ? AND metric IS NOT NULL"
                    " GROUP BY metric"
                )
            return {
                "enabled": True,
                "window_days": days,
                "generated_at": _utc_now_iso(),
                "pageviews": {
                    "total": total,
                    "by_route": [{"route": r, "n": n} for r, n in by_route],
                },
                "visitors": {"unique": unique, "returning": returning},
                "referrers": [{"domain": d, "n": n} for d, n in referrers],
                "utm_campaigns": [
                    {"source": s, "campaign": c, "n": n}
                    for s, c, n in campaigns
                ],
                "x_visits": x_visits,
                "clicks": {m: n for m, n in clicks},
            }
        except Exception:
            return {"enabled": False}
