"""The metrics transaction context also releases its SQLite connection."""
import sqlite3

import pytest

from web.site_metrics import SiteMetricsStore


def test_metrics_connections_close_after_success_and_rollback(tmp_path, monkeypatch):
    connections = []
    connect = sqlite3.connect

    def tracked_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", tracked_connect)
    store = SiteMetricsStore(str(tmp_path / "metrics.sqlite3"))
    store.record_pageview(route="/", vid="visitor", is_new_visitor=True)
    store.record_click(metric="share_card")
    store.prune()
    assert store.summary()["pageviews"]["total"] == 1
    with pytest.raises(RuntimeError, match="rollback"):
        with store._connect() as connection:
            connection.execute("DELETE FROM events")
            raise RuntimeError("rollback")
    assert store.summary()["pageviews"]["total"] == 1
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
