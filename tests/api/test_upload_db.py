# tests/api/test_upload_db.py
"""
UPLOAD-DB-4 (spec_database_plan.md, фаза B): API-контракт сервисов
«Загрузка → База данных (SQL)».

Проверяемые контракты (DoD UPLOAD-DB-4):
  * POST /v1/internal/upload/db/test + POST /v1/internal/upload/db/load
    и зеркальные /v1/public/upload/db/* (конвенция платформы
    public/internal: один модуль реализации, две точки монтирования --
    паритет с файловым /upload, см. upload_common.py);
  * discriminated union по db_type: ServerDbCredentials (4 серверные
    СУБД) | EmbeddedDbSource (DuckDB/SQLite), лишние поля профиля
    запрещены (extra=forbid);
  * ответ /load -- ТОТ ЖЕ UploadResponse, что у файла (паритет
    preview/columns_info/quality/parse_warnings), датасет регистрируется
    в SessionStore -> существующий 5-остановочный пайплайн «Загрузки»
    без новых типов событий трассы (upload_completed, узел overview);
  * безопасные дефолты фазы B: ssl=False, whitelist off (S5);
    row_limit None -> env-потолок ядра (S4);
  * отрицательные сценарии: неверные креды -> маскированная ошибка
    (D4: пароль не появляется ни в одном теле ответа), read-only guard
    -> 422 (DoD), whitelist -> 422, невалидная схема -> 422;
  * «Тест» -- probe-семантика: транспорт/аутентификация/драйвер/файл
    -> 200 {ok:false, error маскирован}; контрактные нарушения -> 422;
    /test НЕ трассируется и НЕ создаёт сессию (probe, не факт анализа);
  * OpenAPI задокументирован (оба семейства, requestBody -> схемы).

Интеграционные тесты -- на реальных embedded-СУБД (SQLite/DuckDB):
CI без внешних сервисов (матрица «зажигания»: SQLite 3+4+5, DuckDB
3+4+5). Серверные СУБД (PG/CH) -- mock-пины на границе роутера
(init_db_connection/load_db_dataframe: ядро Фазы A покрыто своими
тестами, здесь -- контракт маршрутизации/маппинга ошибок).
"""
from __future__ import annotations

import sqlite3
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from apps.api.main import app
from apps.api.session_store import (
    SESSION_COOKIE_NAME,
    get_session_store,
    reset_session_store_for_testing,
)

ROUTER = "apps.api.routers.upload_db"
PASSWORD = "s3cr3t-P@ssw0rd"

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_store():
    reset_session_store_for_testing()
    yield
    reset_session_store_for_testing()


# ── helpers ──────────────────────────────────────────────────────────


def _fresh_client() -> TestClient:
    """Чистая cookie-банка: для тестов, чующих set-cookie сессии."""
    return TestClient(app)


def _make_sqlite(tmp_path, rows: int = 12, name: str = "sales.db", table: str = "t") -> str:
    path = tmp_path / name
    conn = sqlite3.connect(str(path))
    conn.execute(
        f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, value REAL, label TEXT)"
    )
    for i in range(rows):
        conn.execute(f"INSERT INTO {table} VALUES (?, ?, ?)", (i, float(i), f"row-{i}"))
    conn.commit()
    conn.close()
    return str(path)


def _server_payload(**over: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "db_type": "postgresql",
        "host": "db.example.com",
        "port": 5432,
        "database": "sales",
        "user": "analyst",
        "password": PASSWORD,
        "ssl": False,
    }
    payload.update(over)
    return {"connection": payload}


def _embedded_payload(path: str, **over: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"db_type": "sqlite", "path": path}
    payload.update(over)
    return {"connection": payload}


def _fake_engine_version(version: str) -> MagicMock:
    engine = MagicMock(name="engine")
    engine.connect.return_value.__enter__.return_value.execute.return_value.scalar.return_value = version
    return engine


# ── 1. Схемы: discriminated union и safe-дефолты ─────────────────────


class TestSchemas:
    def test_server_credentials_ssl_default_false(self):
        """Safe-дефолт фазы B (указание тимлида): ssl=False при отсутствии
        поля -- паритет legacy-прототипа (D3), TLS только явно."""
        from apps.api.schemas import DbTestRequest, ServerDbCredentials

        req = DbTestRequest.model_validate(_server_payload())
        assert isinstance(req.connection, ServerDbCredentials)
        assert req.connection.ssl is False
        assert req.connection.port == 5432

    def test_discriminator_resolves_embedded(self):
        from apps.api.schemas import DbTestRequest, EmbeddedDbSource

        req = DbTestRequest.model_validate(_embedded_payload("/data/x.db"))
        assert isinstance(req.connection, EmbeddedDbSource)
        assert req.connection.path == "/data/x.db"

    def test_unknown_db_type_rejected(self):
        from apps.api.schemas import DbTestRequest

        with pytest.raises(ValidationError):
            DbTestRequest.model_validate(_server_payload(db_type="oracle"))

    def test_extra_fields_forbidden(self):
        """Смешение профилей -- ошибка контракта: server-payload с path и
        embedded-payload с host отклоняются (не игнорируются молча)."""
        from apps.api.schemas import DbTestRequest

        with pytest.raises(ValidationError):
            DbTestRequest.model_validate(_server_payload(path="/tmp/x.db"))
        with pytest.raises(ValidationError):
            DbTestRequest.model_validate(
                _embedded_payload("/data/x.db", host="db.example.com")
            )

    def test_load_request_requires_sql(self):
        from apps.api.schemas import DbLoadRequest

        with pytest.raises(ValidationError):
            DbLoadRequest.model_validate(_embedded_payload("/data/x.db"))
        with pytest.raises(ValidationError):
            DbLoadRequest.model_validate(
                {**_embedded_payload("/data/x.db"), "sql": "SELECT 1", "row_limit": 0}
            )
        ok = DbLoadRequest.model_validate(
            {**_embedded_payload("/data/x.db"), "sql": "SELECT 1"}
        )
        assert ok.row_limit is None  # None -> env-потолок ядра (S4)


# ── 2. TRACE_ROUTES: регистрация по конвенции платформы ──────────────


class TestTraceRegistration:
    def test_trace_routes_registered_for_db_load(self):
        """DoD: БД-датасет идёт пайплайном файла БЕЗ новых типов событий
        трассы -- (upload, overview, upload_completed), payload -- форма
        UploadResponse. Оба семейства."""
        from apps.api.trace_hook import TRACE_ROUTES

        keys = {(spec.method, spec.path_template): spec for spec in TRACE_ROUTES}
        spec = keys[("POST", "/v1/internal/upload/db/load")]
        assert spec.stage == "upload"
        assert spec.node_id == "overview"
        assert spec.event_type == "upload_completed"
        assert spec.payload_keys == ("name", "rows", "columns", "size_label")
        assert ("POST", "/v1/public/upload/db/load") in keys

    def test_test_endpoint_not_traced(self):
        """«Тест» -- probe, не факт анализа: fail-closed (маршрут вне
        таблицы не трассируется middleware)."""
        from apps.api.trace_hook import TRACE_ROUTES

        keys = {(spec.method, spec.path_template) for spec in TRACE_ROUTES}
        assert ("POST", "/v1/internal/upload/db/test") not in keys
        assert ("POST", "/v1/public/upload/db/test") not in keys


# ── 3. OpenAPI: контракт задокументирован ────────────────────────────


class TestOpenApi:
    def test_openapi_documents_db_upload_endpoints(self):
        schema = app.openapi()
        paths = schema["paths"]
        for path in (
            "/v1/internal/upload/db/test",
            "/v1/internal/upload/db/load",
            "/v1/public/upload/db/test",
            "/v1/public/upload/db/load",
        ):
            assert path in paths, path

    def test_openapi_request_bodies_reference_schemas(self):
        schema = app.openapi()
        ref = (
            schema["paths"]["/v1/internal/upload/db/load"]["post"]["requestBody"]
            ["content"]["application/json"]["schema"]["$ref"]
        )
        assert ref.endswith("DbLoadRequest")
        ref = (
            schema["paths"]["/v1/internal/upload/db/test"]["post"]["requestBody"]
            ["content"]["application/json"]["schema"]["$ref"]
        )
        assert ref.endswith("DbTestRequest")


# ── 4. POST /upload/db/test ──────────────────────────────────────────


class TestDbTestEndpoint:
    def test_ok_engine_version_probe(self, monkeypatch):
        """Серверная СУБД (SQLAlchemy-движок): ok + db_type + server_version
        (version_probe реестра) + latency_ms; error пуст."""
        monkeypatch.setattr(
            f"{ROUTER}.init_db_connection",
            lambda **kw: _fake_engine_version("PostgreSQL 16.2 (Debian)"),
        )
        response = client.post("/v1/internal/upload/db/test", json=_server_payload())
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is True
        assert body["db_type"] == "postgresql"
        assert body["server_version"] == "PostgreSQL 16.2 (Debian)"
        assert isinstance(body["latency_ms"], int)
        assert body["latency_ms"] >= 0
        assert body["error"] is None

    def test_ok_clickhouse_native_version_probe(self, monkeypatch):
        """Нативный клиент CH: версия через query() (TextClause ->
        .text -- сырья строка для нативного клиента)."""
        fake_client = MagicMock(name="ch-client")
        fake_client.query.return_value.result_rows = [["25.3.1.1"]]
        monkeypatch.setattr(
            f"{ROUTER}.init_db_connection", lambda **kw: fake_client
        )
        response = client.post(
            "/v1/internal/upload/db/test",
            json=_server_payload(db_type="clickhouse"),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is True
        assert body["db_type"] == "clickhouse"
        assert body["server_version"] == "25.3.1.1"

    def test_ok_sqlite_real_no_version_probe(self, tmp_path):
        """Реальная embedded-СУБД (CI без сервисов): сквозной вызов ЯДРА
        Фазы A (open_embedded + probe); version_probe у SQLite нет ->
        server_version None (честное отсутствие)."""
        path = _make_sqlite(tmp_path)
        response = client.post(
            "/v1/internal/upload/db/test", json=_embedded_payload(path)
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is True
        assert body["db_type"] == "sqlite"
        assert body["server_version"] is None
        assert isinstance(body["latency_ms"], int)

    def test_connection_failure_ok_false_masked(self, monkeypatch):
        """DoD «неверные креды -> маскированная ошибка»: транспортный сбой
        -> 200 {ok:false}; пароль НИКОГДА не появляется в теле ответа
        (D4; маскирование ядра + страховочный слой роутера)."""
        def boom(**kw):
            raise ConnectionError(
                f"Не удалось подключиться к postgresql: password={PASSWORD}"
            )

        monkeypatch.setattr(f"{ROUTER}.init_db_connection", boom)
        response = client.post("/v1/internal/upload/db/test", json=_server_payload())
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert body["error"]
        assert PASSWORD not in body["error"]
        assert body["latency_ms"] is None

    def test_file_not_found_ok_false(self, tmp_path):
        """Embedded-файл отсутствует -- честный отрицательный результат
        пробы (достижимость источника), реальное ядро без mock'ов."""
        response = client.post(
            "/v1/internal/upload/db/test",
            json=_embedded_payload(str(tmp_path / "missing.db")),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert "не найден" in body["error"].lower()

    def test_driver_missing_ok_false_with_hint(self, monkeypatch):
        """D2: недостающий драйвер -- дружественная подсказка pip."""
        def boom(**kw):
            raise ImportError(
                'Не установлен драйвер MS SQL Server. Установите: pip install "pyodbc"'
            )

        monkeypatch.setattr(f"{ROUTER}.init_db_connection", boom)
        response = client.post(
            "/v1/internal/upload/db/test", json=_server_payload(db_type="mssql")
        )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert "pyodbc" in body["error"]

    def test_bad_extension_422(self, tmp_path):
        """Валидация пути ядра: недопустимое расширение -- нарушение
        контракта -> 422 (probe-семантика не покрывает неверный запрос)."""
        bad = tmp_path / "data.txt"
        bad.write_text("not a database")
        response = client.post(
            "/v1/internal/upload/db/test", json=_embedded_payload(str(bad))
        )
        assert response.status_code == 422
        assert "error" not in response.json() or response.json().get("detail")

    def test_host_not_allowed_422(self, monkeypatch):
        """D5/S5: whitelist ВКЛЮЧЁН env -> хост вне списка отклоняется ДО
        сети (ядро валидирует перед открытием соединения; сеть не
        трогается -- тест безопасен)."""
        monkeypatch.setenv("UPLOAD_DB_HOST_WHITELIST", "10.0.0.1,db.internal")
        response = client.post("/v1/internal/upload/db/test", json=_server_payload())
        assert response.status_code == 422

    def test_test_does_not_create_session(self, tmp_path):
        """Probe-чистота: «Тест» НЕ создаёт сессию/cookie -- фактом пробы
        анализ не начинается (контракт: датасет появляется только у /load)."""
        fresh = _fresh_client()
        path = _make_sqlite(tmp_path)
        response = fresh.post(
            "/v1/internal/upload/db/test", json=_embedded_payload(path)
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True
        set_cookies = response.headers.get_list("set-cookie")
        assert not any(SESSION_COOKIE_NAME in c for c in set_cookies)


# ── 5. POST /upload/db/load: контракт файла ──────────────────────────


class TestDbLoadEndpoint:
    def test_load_sqlite_returns_upload_contract(self, tmp_path):
        """DoD: ответ -- ТОТ ЖЕ UploadResponse (preview/columns_info/
        quality/parse_warnings/size_label), реальная SQLite, ядро Фазы A
        (guard + стриминг) без mock'ов."""
        path = _make_sqlite(tmp_path, rows=12)
        response = client.post(
            "/v1/internal/upload/db/load",
            json={**_embedded_payload(path), "sql": "SELECT * FROM t"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["dataset_id"]
        assert body["name"] == "sales.db"
        assert body["rows"] == 12
        assert body["columns"] == 3
        assert len(body["preview"]["head"]) == 6  # заголовок + 5 строк
        assert len(body["preview"]["tail"]) == 5
        assert body["columns_info"] and len(body["columns_info"]) == 3
        assert body["quality"] is not None
        assert body["size_label"]
        assert isinstance(body["parse_warnings"], list)
        assert body["error"] is None

    def test_load_registers_session_pipeline_entry(self, tmp_path):
        """DoD: БД-датасет проходит существующий 5-остановочный пайплайн
        -- сессия зарегистрирована (cookie), остановка upload=done,
        строки читает СУЩЕСТВУЮЩИЙ GET /dataset/rows; fingerprint пуст
        (контракт «источник без файла», DatasetInfo)."""
        path = _make_sqlite(tmp_path, rows=12)
        response = client.post(
            "/v1/internal/upload/db/load",
            json={**_embedded_payload(path), "sql": "SELECT * FROM t"},
        )
        assert response.status_code == 200
        session_id = client.cookies.get(SESSION_COOKIE_NAME)
        assert session_id, "сессия не создана"
        session = get_session_store().get(session_id)
        assert session is not None
        assert session.dataset.rows == 12
        assert session.dataset.name == "sales.db"
        assert session.dataset.dataset_fingerprint == ""
        assert session.stages["upload"] == "done"

        rows = client.get("/v1/session/dataset/rows")
        assert rows.status_code == 200, rows.text
        assert rows.json()["total_rows"] == 12

    def test_load_writes_upload_completed_trace(self, tmp_path):
        """Трасса без новых типов: событие upload_completed (узел overview)
        пишется middleware на успешном /load, payload -- форма UploadResponse."""
        path = _make_sqlite(tmp_path, rows=12)
        response = client.post(
            "/v1/internal/upload/db/load",
            json={**_embedded_payload(path), "sql": "SELECT * FROM t"},
        )
        assert response.status_code == 200
        session_id = client.cookies.get(SESSION_COOKIE_NAME)
        events = get_session_store().get(session_id).pipeline_trace
        match = [
            e
            for e in events
            if e.get("event_type") == "upload_completed"
            and e.get("node_id") == "overview"
        ]
        assert match, "upload_completed не записан"
        payload = match[-1]["payload"]
        assert payload["name"] == "sales.db"
        assert payload["rows"] == 12
        assert "size_label" in payload

    def test_load_duckdb_csv_direct_select(self, tmp_path):
        """DuckDB по Parquet/CSV (прямой SELECT без сервера) через API:
        реальное ядро, CI без сервисов."""
        csv = tmp_path / "points.csv"
        csv.write_text("date,value\n2024-01-01,1\n2024-01-02,2\n2024-01-03,3\n")
        response = client.post(
            "/v1/internal/upload/db/load",
            json={
                "connection": {"db_type": "duckdb", "path": str(csv)},
                "sql": f"SELECT * FROM '{csv}'",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["rows"] == 3
        assert body["columns"] == 2
        assert body["name"] == "points.csv"

    def test_guard_delete_rejected_422_no_dataset(self, tmp_path):
        """DoD: guard -> 422; DML отклонён, датасет НЕ появляется в
        сессии (fail-closed: отказ = отсутствие мутации)."""
        fresh = _fresh_client()
        path = _make_sqlite(tmp_path, rows=12)
        response = fresh.post(
            "/v1/internal/upload/db/load",
            json={**_embedded_payload(path), "sql": "DELETE FROM t"},
        )
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "SELECT" in detail.upper() or "чтени" in detail.lower()
        assert fresh.cookies.get(SESSION_COOKIE_NAME) is None

    def test_guard_multistatement_rejected_422(self, tmp_path):
        path = _make_sqlite(tmp_path, rows=3)
        response = client.post(
            "/v1/internal/upload/db/load",
            json={
                **_embedded_payload(path),
                "sql": "SELECT 1; DROP TABLE t",
            },
        )
        assert response.status_code == 422

    def test_row_limit_applied_and_warned(self, tmp_path):
        """S4: явный row_limit применяется, усечение -- технический флаг
        parse_warnings (без новых полей схемы и новых событий трассы)."""
        path = _make_sqlite(tmp_path, rows=50)
        response = client.post(
            "/v1/internal/upload/db/load",
            json={
                **_embedded_payload(path),
                "sql": "SELECT * FROM t",
                "row_limit": 10,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["rows"] == 10
        assert any("10" in w for w in body["parse_warnings"])

    def test_env_cap_stronger_than_request(self, tmp_path, monkeypatch):
        """Env-потолок сильнее параметра запроса (ядро Фазы A): запрос 100
        при UPLOAD_DB_ROW_LIMIT=5 отдаёт 5 строк."""
        monkeypatch.setenv("UPLOAD_DB_ROW_LIMIT", "5")
        path = _make_sqlite(tmp_path, rows=50)
        response = client.post(
            "/v1/internal/upload/db/load",
            json={
                **_embedded_payload(path),
                "sql": "SELECT * FROM t",
                "row_limit": 100,
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["rows"] == 5

    def test_connection_failure_400_masked(self, monkeypatch):
        """Операционный сбой /load -> 400 с маскированной деталью (пароль
        не появляется; D4 -- страховочный слой роутера)."""
        def boom(**kw):
            raise ConnectionError(
                f"FATAL: password authentication failed for user analyst "
                f"(password {PASSWORD})"
            )

        monkeypatch.setattr(f"{ROUTER}.init_db_connection", boom)
        response = client.post(
            "/v1/internal/upload/db/load",
            json={**_server_payload(), "sql": "SELECT 1"},
        )
        assert response.status_code == 400
        assert PASSWORD not in response.json()["detail"]

    def test_load_server_name_uses_label_and_database(self, monkeypatch):
        """Имя датасета серверного источника: «{label реестра}: {database}»
        -- человекочитаемая идентификация источника в UI/трассе."""
        fake_result = MagicMock(name="DbLoadResult")
        fake_result.dataframe = pd.DataFrame({"a": [1]})
        fake_result.rows_loaded = 1
        fake_result.truncated = False
        fake_result.row_limit = 1_000_000
        monkeypatch.setattr(f"{ROUTER}.init_db_connection", lambda **kw: object())
        monkeypatch.setattr(f"{ROUTER}.load_db_dataframe", lambda *a, **k: fake_result)
        response = client.post(
            "/v1/internal/upload/db/load",
            json={**_server_payload(), "sql": "SELECT a FROM t"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["name"] == "PostgreSQL / Postgres Pro: sales"


# ── 6. Оба семейства: public/internal ────────────────────────────────


class TestFamilies:
    def test_public_test_requires_api_key(self, tmp_path, monkeypatch):
        """Паритет платформы: public-семейство за API-ключом; без ключа
        запрос не проходит."""
        monkeypatch.setenv("CISSTAT_API_KEYS", "testkey:internal_analyst:")
        path = _make_sqlite(tmp_path)
        fresh = _fresh_client()
        response = fresh.post(
            "/v1/public/upload/db/test", json=_embedded_payload(path)
        )
        assert response.status_code in (401, 422)  # нет ключа / нет заголовка

    def test_public_test_with_api_key_ok(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CISSTAT_API_KEYS", "testkey:internal_analyst:")
        path = _make_sqlite(tmp_path)
        fresh = _fresh_client()
        response = fresh.post(
            "/v1/public/upload/db/test",
            json=_embedded_payload(path),
            headers={"X-API-Key": "testkey"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["ok"] is True

    def test_public_load_with_api_key_ok(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CISSTAT_API_KEYS", "testkey:internal_analyst:")
        path = _make_sqlite(tmp_path, rows=5)
        fresh = _fresh_client()
        response = fresh.post(
            "/v1/public/upload/db/load",
            json={**_embedded_payload(path), "sql": "SELECT * FROM t"},
            headers={"X-API-Key": "testkey"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["rows"] == 5
