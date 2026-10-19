"""Four audit regressions on 354dfa5; no external DB credentials needed."""
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest
from sqlalchemy import event

from app.data import db_connectors as dc
from app.data.db_guard import load_db_dataframe


@pytest.mark.parametrize("ssl,expected", [(True, "require"), (False, "off")])
def test_pymssql_tls_is_explicit(ssl, expected):
    url, args = dc.build_server_url(dc.get_connector("mssql"), host="test", port=None,
        database="test", username="reader", password="owned-secret", ssl=ssl, mssql_driver="pymssql")
    assert args["encryption"] == expected
    assert url.password is None


@pytest.mark.parametrize("db_type,driver,keys", [
    ("mysql", None, ("read_timeout", "write_timeout")),
    ("mssql", "pymssql", ("timeout",)),
])
def test_query_timeout_forwarded(db_type, driver, keys, monkeypatch):
    monkeypatch.setenv("UPLOAD_DB_CONNECT_TIMEOUT", "3")
    monkeypatch.setenv("UPLOAD_DB_QUERY_TIMEOUT", "7")
    _, args = dc.build_server_url(dc.get_connector(db_type), host="test", port=None,
        database="test", username="reader", password="secret", mssql_driver=driver)
    for key in keys:
        assert args[key] == 7
    assert args.get("connect_timeout", args.get("login_timeout")) == 3


def test_pyodbc_query_timeout_on_new_dbapi_connection(monkeypatch):
    monkeypatch.setenv("UPLOAD_DB_QUERY_TIMEOUT", "7")
    engine = SimpleNamespace()
    monkeypatch.setattr(dc, "create_engine", lambda *a, **k: engine)
    registrations = []
    monkeypatch.setattr(event, "listen", lambda *a, **k: registrations.append(a))
    spec = dc.get_connector("mssql")
    url, args = dc.build_server_url(spec, host="test", port=None, database="test", username="u", password="s", mssql_driver="pyodbc")
    dc.open_server_engine(spec, url, args)
    assert len(registrations) == 1
    target, name, callback = registrations[0]
    assert target is engine and name == "connect"
    raw = SimpleNamespace(timeout=0)
    callback(raw, None)
    assert raw.timeout == 7  # pyodbc Connection.timeout, not connect(timeout=...)
    class Unsupported:
        __slots__ = ()
    with pytest.raises(AttributeError):
        callback(Unsupported(), None)  # no silent unlimited-query downgrade


@pytest.mark.parametrize("count,truncated", [(0, False), (4, False), (5, False), (6, True), (12, True)])
def test_clickhouse_boundary_uses_one_extra_row(count, truncated):
    class Native:
        def query_df(self, sql, settings):
            self.requested = settings["max_result_rows"]
            return pd.DataFrame({"value": range(count)}).head(self.requested)
    client = Native()
    result = load_db_dataframe(client, "SELECT value FROM t", row_limit=5)
    assert client.requested == 6
    assert result.rows_loaded == min(count, 5)
    assert result.truncated is truncated


def test_version_probe_log_redacted_and_engine_released(monkeypatch, caplog):
    from fastapi.testclient import TestClient
    from apps.api.main import app
    from apps.api.routers import upload_db
    secret = "OWNED_VERSION_PROBE_SECRET"
    engine = SimpleNamespace(dispose=Mock())
    monkeypatch.setattr(upload_db, "init_db_connection", lambda **kwargs: engine)
    def refusal(*args):
        raise RuntimeError(f"password={secret}")
    monkeypatch.setattr(upload_db, "_server_version", refusal)
    with caplog.at_level("INFO", logger=upload_db.__name__):
        response = TestClient(app).post("/v1/internal/upload/db/test", json={"connection": {
            "db_type": "postgresql", "host": "test", "database": "test", "user": "u", "password": secret}})
    assert response.status_code == 200 and response.json()["ok"] is True
    assert secret not in caplog.text and secret not in response.text
    assert "****" in caplog.text
    engine.dispose.assert_called_once()
