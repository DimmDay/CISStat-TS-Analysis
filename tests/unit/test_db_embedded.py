"""
Unit-тесты embedded-режима (SQLite + DuckDB) — UPLOAD-DB-3 (spec_database_plan.md, фаза A).

Сквозной Test→Load на встроенных СУБД — работает в CI БЕЗ внешних сервисов
(DoD UPLOAD-DB-3). Реестр несёт path-режим: SQLite (.db/.sqlite), DuckDB
(.db/.duckdb) и прямой DuckDB-SELECT по Parquet/CSV-файлу. Обе встроенные
СУБД открываются ТОЛЬКО в read-only (платформа — потребитель данных).
"""
import duckdb
import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from app.data import db_connectors
from app.data.db_guard import DbQueryRejected, load_db_dataframe
from app.data.file_loader import init_db_connection


def _write_sqlite(path, rows: int = 12) -> None:
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER, name TEXT)"))
        conn.execute(text(
            "INSERT INTO t VALUES " + ",".join(f"({i}, 'row{i}')" for i in range(rows))
        ))
    engine.dispose()  # duckdb/sqlite-пулы: отпустить файл до read_only-открытия


class TestEmbeddedRegistry:
    """Path-метаданные встроенных СУБД в реестре."""

    def test_sqlite_extensions(self):
        spec = db_connectors.get_connector("sqlite")
        assert spec.mode == "embedded"
        assert spec.path_extensions == (".db", ".sqlite")
        assert spec.query_file_extensions == ()

    def test_duckdb_extensions(self):
        spec = db_connectors.get_connector("duckdb")
        assert spec.mode == "embedded"
        assert spec.path_extensions == (".db", ".duckdb", ".parquet", ".csv")
        # прямой SELECT по файлу без сервера (Parquet/CSV)
        assert spec.query_file_extensions == (".parquet", ".csv")

    def test_embedded_have_no_default_port(self):
        for cid in ("sqlite", "duckdb"):
            assert db_connectors.get_connector(cid).default_port is None


class TestSqliteEmbedded:
    """Сквозной Test→Load на SQLite (файл, read-only)."""

    def test_test_then_load_end_to_end(self, tmp_path):
        db_file = tmp_path / "analytics.db"
        _write_sqlite(db_file)
        engine = init_db_connection(
            "sqlite", "ignored-host", 0, "ignored-user", "ignored-pass", "", path=str(db_file)
        )
        # Test-фаза выполнена внутри init_db_connection (контрольный text());
        # Load-фаза: чтение с guard'ом и лимитом.
        result = load_db_dataframe(engine, "SELECT * FROM t")
        assert result.rows_loaded == 12
        assert result.truncated is False
        assert list(result.dataframe.columns) == ["id", "name"]

    def test_read_only_enforced(self, tmp_path):
        """Платформа открывает SQLite ТОЛЬКО mode=ro: запись невозможна."""
        db_file = tmp_path / "ro.db"
        _write_sqlite(db_file)
        engine = init_db_connection("sqlite", "h", 0, "u", "p", "", path=str(db_file))
        with pytest.raises(OperationalError):
            with engine.begin() as conn:
                conn.execute(text("CREATE TABLE hack (id INTEGER)"))

    def test_bad_extension_rejected(self, tmp_path):
        target = tmp_path / "notes.txt"
        target.write_text("hello")
        with pytest.raises(ValueError, match="Недопустимое расширение"):
            init_db_connection("sqlite", "h", 0, "u", "p", "", path=str(target))

    def test_missing_file_rejected(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="не найден"):
            init_db_connection("sqlite", "h", 0, "u", "p", "", path=str(tmp_path / "nope.db"))

    def test_alias_sqlite3_resolves(self, tmp_path):
        db_file = tmp_path / "a.sqlite"
        _write_sqlite(db_file)
        engine = init_db_connection("sqlite3", "h", 0, "u", "p", "", path=str(db_file))
        result = load_db_dataframe(engine, "SELECT count(*) AS n FROM t")
        assert result.rows_loaded == 1 and int(result.dataframe["n"].iloc[0]) == 12


class TestDuckDbEmbedded:
    """Сквозной Test→Load на DuckDB: файл .duckdb, Parquet, CSV."""

    @pytest.fixture()
    def duckdb_file(self, tmp_path):
        db_file = tmp_path / "analytics.duckdb"
        conn = duckdb.connect(str(db_file))
        conn.execute("CREATE TABLE t (id INTEGER, val DOUBLE)")
        conn.execute("INSERT INTO t VALUES " + ",".join(f"({i}, {i * 2.5})" for i in range(9)))
        conn.close()
        return db_file

    def test_test_then_load_duckdb_file(self, duckdb_file):
        engine = init_db_connection(
            "duckdb", "ignored-host", 0, "ignored-user", "ignored-pass", "", path=str(duckdb_file)
        )
        result = load_db_dataframe(engine, "SELECT * FROM t")
        assert result.rows_loaded == 9
        assert list(result.dataframe.columns) == ["id", "val"]

    def test_duckdb_read_only_enforced(self, duckdb_file):
        engine = init_db_connection("duckdb", "h", 0, "u", "p", "", path=str(duckdb_file))
        with pytest.raises(Exception):
            with engine.begin() as conn:
                conn.execute(text("CREATE TABLE hack (id INTEGER)"))

    def test_csv_direct_select(self, tmp_path):
        csv_file = tmp_path / "series.csv"
        pd.DataFrame({"date": ["2026-01-01", "2026-01-02", "2026-01-03"],
                      "value": [10.0, 20.5, 30.1]}).to_csv(csv_file, index=False)
        engine = init_db_connection("duckdb", "h", 0, "u", "p", "", path=str(csv_file))
        result = load_db_dataframe(engine, f"SELECT * FROM '{csv_file}'")
        assert result.rows_loaded == 3
        assert list(result.dataframe.columns) == ["date", "value"]

    def test_parquet_direct_select(self, tmp_path, duckdb_file):
        parquet_file = tmp_path / "export.parquet"
        conn = duckdb.connect(str(duckdb_file))
        conn.execute(f"COPY t TO '{parquet_file}' (FORMAT PARQUET)")
        conn.close()
        engine = init_db_connection("duckdb", "h", 0, "u", "p", "", path=str(parquet_file))
        result = load_db_dataframe(engine, f"SELECT * FROM '{parquet_file}'")
        assert result.rows_loaded == 9
        assert list(result.dataframe.columns) == ["id", "val"]

    def test_csv_with_space_in_path(self, tmp_path):
        csv_file = tmp_path / "my data.csv"
        pd.DataFrame({"x": [1, 2]}).to_csv(csv_file, index=False)
        engine = init_db_connection("duckdb", "h", 0, "u", "p", "", path=str(csv_file))
        result = load_db_dataframe(engine, f"SELECT * FROM '{csv_file}'")
        assert result.rows_loaded == 2

    def test_bad_extension_rejected(self, tmp_path):
        target = tmp_path / "book.xlsx"
        target.write_bytes(b"fake")
        with pytest.raises(ValueError, match="Недопустимое расширение"):
            init_db_connection("duckdb", "h", 0, "u", "p", "", path=str(target))

    def test_missing_file_rejected(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="не найден"):
            init_db_connection("duckdb", "h", 0, "u", "p", "", path=str(tmp_path / "no.duckdb"))

    def test_guard_applies_to_embedded_load(self, duckdb_file):
        """Read-only guard действует и на embedded-дорожке."""
        engine = init_db_connection("duckdb", "h", 0, "u", "p", "", path=str(duckdb_file))
        with pytest.raises(DbQueryRejected):
            load_db_dataframe(engine, "DELETE FROM t")

    def test_embedded_ids_case_insensitive(self):
        """Резолюция embedded-записей по id/alias, а не по UI-подписи."""
        assert db_connectors.get_connector("DuckDB").id == "duckdb"
        assert db_connectors.get_connector("DUCKDB").id == "duckdb"
        assert db_connectors.get_connector("SQLite").id == "sqlite"
        # UI-подпись НЕ является идентификатором реестра (формы Phase B
        # отправляют id селекта) — честный отказ.
        with pytest.raises(ValueError):
            db_connectors.get_connector("DuckDB (встроенная)")
