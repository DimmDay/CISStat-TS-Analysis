"""Read-only product audit on disposable owned data; no external servers.

Run from repository: python scripts/database_connections_audit.py
Outputs JSON observations, not a blanket certification of all vendors.
Only fixture files and temporary test sessions are created/modified.
"""
import io
import json
import logging
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    # These are process-local test settings, never deployment mutations.
    for name in ("DATABASE_URL", "REDIS_URL"):
        os.environ.pop(name, None)
    os.environ.update(CISSTAT_RUNS_BACKEND="memory", CISSTAT_SESSION_BACKEND="memory",
                      CISSTAT_STORAGE_MODE="advisory", CISSTAT_DELIVERY_WORKER_ENABLED="0")
    import duckdb
    import pandas as pd
    from fastapi.testclient import TestClient
    from apps.api.main import app
    from apps.api.routers import upload_db
    from app.data import db_connectors as dc
    from app.data.db_guard import load_db_dataframe, validate_readonly_sql

    observations = {"base_commit": "079e352bd924c708ea6d563c1d01b2a5007882d1", "external_db_tests": "not run", "embedded": []}
    with tempfile.TemporaryDirectory(prefix="db-audit-", dir=ROOT.parent) as folder:
        tmp = Path(folder)
        os.environ["CISSTAT_DATA_DIR"] = str(tmp / "data")
        rows = [(f"2026-01-{i:02d}", float(i * 3)) for i in range(1, 13)]
        sqlite_path = tmp / "series.sqlite"
        with sqlite3.connect(sqlite_path) as conn:
            conn.execute("CREATE TABLE series (date TEXT, value REAL)")
            conn.executemany("INSERT INTO series VALUES (?, ?)", rows)
        duck_path = tmp / "series.duckdb"
        parquet_path = tmp / "series.parquet"
        csv_path = tmp / "series.csv"
        with duckdb.connect(str(duck_path)) as conn:
            conn.execute("CREATE TABLE series (date VARCHAR, value DOUBLE)")
            conn.executemany("INSERT INTO series VALUES (?, ?)", rows)
            conn.execute(f"COPY series TO '{parquet_path}' (FORMAT PARQUET)")
        pd.DataFrame(rows, columns=["date", "value"]).to_csv(csv_path, index=False)
        for kind, path, sql in (
            ("sqlite", sqlite_path, "SELECT * FROM series ORDER BY date"),
            ("duckdb", duck_path, "SELECT * FROM series ORDER BY date"),
            ("duckdb", csv_path, f"SELECT * FROM '{csv_path}' ORDER BY date"),
            ("duckdb", parquet_path, f"SELECT * FROM '{parquet_path}' ORDER BY date"),
        ):
            with TestClient(app) as client:
                connection = {"db_type": kind, "path": str(path)}
                test = client.post("/v1/internal/upload/db/test", json={"connection": connection})
                no_cookie = not client.cookies
                loaded = client.post("/v1/internal/upload/db/load", json={"connection": connection, "sql": sql, "row_limit": 5})
                body = loaded.json()
                trace = client.get("/v1/progress/trace").json()
                rejected = client.post("/v1/internal/upload/db/load", json={"connection": connection, "sql": "DELETE FROM series"})
                record = {"kind": kind, "extension": path.suffix, "test_http": test.status_code, "ok": test.json().get("ok"),
                          "probe_created_no_cookie": no_cookie, "load_http": loaded.status_code, "rows": body.get("rows"),
                          "warnings": body.get("parse_warnings"), "cookie": bool(client.cookies),
                          "upload_event": any(e["event_type"] == "upload_completed" for e in trace.get("events", [])),
                          "delete_http": rejected.status_code}
                assert record["ok"] is True and record["load_http"] == 200 and record["rows"] == 5, record
                assert record["upload_event"] and record["delete_http"] == 422 and no_cookie, record
                observations["embedded"].append(record)

        # A controlled ClickHouse-like response proves the boundary ambiguity;
        # it is not presented as a live ClickHouse observation.
        class NativeClient:
            def query_df(self, sql, settings):
                return pd.DataFrame({"value": range(12)}).head(settings["max_result_rows"])
        limited = load_db_dataframe(NativeClient(), "SELECT value FROM series", row_limit=5)
        observations["clickhouse_simulated_exact_boundary"] = {"owned_source_rows": 12, "returned_rows": limited.rows_loaded,
                                                               "truncated": limited.truncated}

        # Prove SELECT is not a file sandbox, reading ONLY an owned marker.
        marker = tmp / "owned-marker.txt"
        marker.write_text("OWNED_AUDIT_MARKER")
        sql = f"SELECT content FROM read_text('{marker}')"
        validate_readonly_sql(sql)
        engine = dc.open_embedded(dc.get_connector("duckdb"), path=str(csv_path))
        try:
            loaded_marker = load_db_dataframe(engine, sql, row_limit=1)
            observations["duckdb_query_can_read_other_owned_file"] = loaded_marker.dataframe.iloc[0, 0] == "OWNED_AUDIT_MARKER"
        finally:
            engine.dispose()

        # Exercise the version probe failure log with a fictitious secret.
        secret = "OWNED_AUDIT_SENTINEL"
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        upload_db.logger.addHandler(handler)
        try:
            with patch.object(upload_db, "init_db_connection", return_value=object()), patch.object(upload_db, "_server_version", side_effect=RuntimeError(f"password={secret}")):
                response = TestClient(app).post("/v1/internal/upload/db/test", json={"connection": {"db_type": "postgresql", "host": "owned.test", "database": "owned", "user": "reader", "password": secret}})
            observations["version_error_log"] = {"probe_ok": response.json()["ok"], "fictitious_secret_in_log": secret in stream.getvalue(),
                                                 "fictitious_secret_in_response": secret in response.text}
        finally:
            upload_db.logger.removeHandler(handler)

        observations["driver_kwargs"] = []
        for kind, driver in (("postgresql", None), ("mysql", None), ("mssql", "pyodbc"), ("mssql", "pymssql")):
            options = []
            for tls in (False, True):
                url, kwargs = dc.build_server_url(dc.get_connector(kind), host="owned.test", port=None, database="owned", username="reader", password=secret, ssl=tls, mssql_driver=driver)
                options.append({"ssl": tls, "dialect": url.drivername,
                                "kwargs": {k: "<masked>" if k.lower() in ("password", "pwd") else v for k, v in kwargs.items()}, "query": dict(url.query)})
            observations["driver_kwargs"].append({"db_type": kind, "driver": driver, "options": options})
        observations["pyodbc_import_available"] = dc.pyodbc is not None
        observations["pymssql_import_available"] = dc.pymssql is not None
    destination = ROOT / "scripts/database_connections_audit_results.json"
    destination.write_text(json.dumps(observations, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(observations, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
