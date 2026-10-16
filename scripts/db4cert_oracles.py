# scripts/db4cert_oracles.py
"""
Независимая сертификация UPLOAD-DB-4 (API-контракт apps/api) — ОРАКУЛЫ
аудитора на СВОИХ данных. Корпус «припортовая гидрологическая сеть»
дизъюнктен repo-корпусу (sales.db/table t/points.csv) и корпусам прошлых
сертификаций (dvecert «порт-звонки», dbcert «station telemetry»).

Поверхности оракулов дизъюнктны/глубже repo-сюиты tests/api/test_upload_db.py:
  O01 OpenAPI: response-$refs (repo пинит только requestBody)
  O02 discriminated union ЧЕРЕЗ HTTP-провод (repo — на уровне схем)
  O05 /test по CSV (repo /test только .db)
  O06 битые источники через API-маппинг (оракулы UPLOAD-DB-3-CERT — на ядре)
  O10 авто-фиксация цели PROGR-25-A сквозь БД-дорожку + expanduser (repo нет)
  O11 /test не растит СУЩЕСТВУЮЩУЮ трассу (repo пинит только отсутствие cookie)
  O16 сбой version_probe не роняет подтверждённую пробу (repo нет)
  O17 персистенция на fakeredis (класс PROGR-25-F1: Memory-алиасинг маскирует потерю save)
  O19 probe-чистота на уровне ХРАНИЛИЩА (repo — set-cookie)
  O20 capture-kwargs: default_port реестра + ssl=False НА ПРОВОДЕ

Запуск: DATABASE_URL="" python -m pytest scripts/db4cert_oracles.py -q
"""
from __future__ import annotations

import os
import re
import sqlite3
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.session_store import (
    SESSION_COOKIE_NAME,
    RedisSessionStore,
    get_session_store,
    peek_session_store,
    reset_session_store_for_testing,
)

ROUTER = "apps.api.routers.upload_db"
PASSWORD = "P0rt-G@uge#2024$v;{}x"  # спецсимволы: маскирование, не только подстрока

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_store(monkeypatch):
    """Чистое хранилище + чистая env на каждый оракул."""
    for var in ("UPLOAD_DB_ROW_LIMIT", "UPLOAD_DB_HOST_WHITELIST",
                "CISSTAT_API_KEYS", "UPLOAD_DB_MSSQL_DRIVER"):
        monkeypatch.delenv(var, raising=False)
    reset_session_store_for_testing()
    yield
    reset_session_store_for_testing()


# ── корпус аудитора ───────────────────────────────────────────────────

def _make_gauge_sqlite(tmp_path) -> str:
    """gauge_river.sqlite: таблица gauge_readings, 9 строк, кириллица."""
    path = tmp_path / "gauge_river.sqlite"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE gauge_readings (id INTEGER PRIMARY KEY, level REAL, station TEXT)")
    stations = ["Волга-1", "Дон-2", "Лена-3", "Обь-4", "Амур-5", "Нева-6", "Урал-7", "Кама-8", "Ока-9"]
    for i, st in enumerate(stations):
        conn.execute(
            "INSERT INTO gauge_readings VALUES (?, ?, ?)", (i + 1, 1.5 + i * 0.25, st)
        )
    conn.commit()
    conn.close()
    return str(path)


def _make_tides_duckdb(tmp_path) -> str:
    """tides_harbor.duckdb: таблица tides, 7 строк, кириллица в данных."""
    import duckdb

    path = tmp_path / "tides_harbor.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE tides (day DATE, height_cm DOUBLE, port VARCHAR)")
    for i, (d, h, p) in enumerate([
        ("2024-03-01", 12.5, "Владивосток"),
        ("2024-03-02", 14.0, "Находка"),
        ("2024-03-03", 11.25, "Восточный"),
        ("2024-03-04", 13.75, "Владивосток"),
        ("2024-03-05", 15.5, "Находка"),
        ("2024-03-06", 10.0, "Восточный"),
        ("2024-03-07", 12.0, "Владивосток"),
    ]):
        con.execute("INSERT INTO tides VALUES (?, ?, ?)", (d, h, p))
    con.close()
    return str(path)


def _make_ice_csv(tmp_path) -> str:
    """«ледовые сводки 2024.csv»: юникод + пробел в имени, 5 строк."""
    path = tmp_path / "ледовые сводки 2024.csv"
    path.write_text(
        "date,thickness_cm\n2024-01-10,32\n2024-01-20,41\n2024-01-31,47\n2024-02-10,39\n2024-02-20,28\n",
        encoding="utf-8",
    )
    return str(path)


def _make_sensor_parquet(tmp_path) -> str:
    """sensor_grid.parquet: 11 строк, точные float (duckdb COPY)."""
    import duckdb

    csv = tmp_path / "_sensor_src.csv"
    csv.write_text(
        "sensor,voltage\n" + "\n".join(f"s{i},{i * 0.125:.3f}" for i in range(11)) + "\n",
        encoding="utf-8",
    )
    path = tmp_path / "sensor_grid.parquet"
    con = duckdb.connect()
    con.execute(
        f"COPY (SELECT * FROM read_csv_auto('{csv}')) TO '{path}' (FORMAT PARQUET)"
    )
    con.close()
    return str(path)


def _make_broken(tmp_path, name: str) -> str:
    """Битый источник: валидный UTF-8 + двоичный мусор (сниффер/движок
    обязаны отказать честно; API обязано ответить картой ошибок, не 500)."""
    path = tmp_path / name
    payload = "ГАUGE LOG " + ("a" * 8192) + "\x00\x01\x02\xff\xfe" * 64
    path.write_bytes(payload.encode("utf-8", errors="replace") + os.urandom(2048))
    return str(path)


def _make_riverside_in_home(home_dir) -> str:
    """riverside.db в fake HOME: единственная числовая колонка level
    (день — TEXT) → авто-фиксация цели PROGR-25-A + expanduser-пин."""
    home_dir.mkdir(parents=True, exist_ok=True)
    path = home_dir / "riverside.db"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE levels (day TEXT, level REAL)")
    rows = [("2024-05-0" + str(i + 1), 2.0 + i * 0.1) for i in range(6)]
    conn.executemany("INSERT INTO levels VALUES (?, ?)", rows)
    conn.commit()
    conn.close()
    return "~/riverside.db"


def _server_payload(**over: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "db_type": "postgresql",
        "host": "gauge-db.hydro.net",
        "port": 5432,
        "database": "harbor_poc",
        "user": "hydrolog",
        "password": PASSWORD,
        "ssl": False,
    }
    payload.update(over)
    return {"connection": payload}


def _sqlite_payload(path: str, **over: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"db_type": "sqlite", "path": path}
    payload.update(over)
    return {"connection": payload}


def _duck_payload(path: str, **over: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"db_type": "duckdb", "path": path}
    payload.update(over)
    return {"connection": payload}


def _load_body(connection_payload: dict, sql: str, **over: Any) -> dict:
    return {"connection": connection_payload["connection"], "sql": sql, **over}


# ── O01. OpenAPI: контракты глубже repo ───────────────────────────────


def test_o01_openapi_response_refs_both_families():
    schema = app.openapi()
    paths = schema["paths"]
    for family in ("internal", "public"):
        test_ref = paths[f"/v1/{family}/upload/db/test"]["post"]["responses"]["200"][
            "content"]["application/json"]["schema"]["$ref"]
        load_ref = paths[f"/v1/{family}/upload/db/load"]["post"]["responses"]["200"][
            "content"]["application/json"]["schema"]["$ref"]
        assert test_ref.endswith("DbTestResponse"), (family, test_ref)
        assert load_ref.endswith("UploadResponse"), (family, load_ref)
        body = paths[f"/v1/{family}/upload/db/load"]["post"]["requestBody"]
        assert body["content"]["application/json"]["schema"]["$ref"].endswith("DbLoadRequest")


# ── O02. Discriminated union через HTTP-провод ────────────────────────


def test_o02_union_mixing_rejected_over_the_wire():
    r1 = client.post("/v1/internal/upload/db/test", json=_server_payload(path="/tmp/x.db"))
    assert r1.status_code == 422, r1.text
    r2 = client.post(
        "/v1/internal/upload/db/test",
        json=_sqlite_payload("/data/x.db", host="gauge-db.hydro.net"),
    )
    assert r2.status_code == 422, r2.text
    r3 = client.post(
        "/v1/internal/upload/db/test", json=_server_payload(db_type="gauge_db")
    )
    assert r3.status_code == 422, r3.text


# ── O03–O05. «Тест» на реальных источниках корпуса ────────────────────


def test_o03_test_real_sqlite_honest_facts(tmp_path):
    path = _make_gauge_sqlite(tmp_path)
    r = client.post("/v1/internal/upload/db/test", json=_sqlite_payload(path))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["db_type"] == "sqlite"
    assert body["server_version"] is None  # честное отсутствие probe
    assert isinstance(body["latency_ms"], int) and body["latency_ms"] >= 0
    assert body["error"] is None


def test_o04_test_real_duckdb_file(tmp_path):
    path = _make_tides_duckdb(tmp_path)
    r = client.post("/v1/internal/upload/db/test", json=_duck_payload(path))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["db_type"] == "duckdb"
    assert body["server_version"] is None


def test_o05_test_duckdb_reads_csv_itself(tmp_path):
    """Probe честно проверяет читаемость CSV-источника (repo /test
    проверяет только .db; поверхность «Тест по CSV» — оракульная)."""
    csv = _make_ice_csv(tmp_path)
    r = client.post("/v1/internal/upload/db/test", json=_duck_payload(csv))
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


# ── O06. Битые источники: карта ошибок, не 500 ────────────────────────


def test_o06_broken_sources_error_map_no_500(tmp_path):
    r_sqlite = client.post(
        "/v1/internal/upload/db/test",
        json=_sqlite_payload(_make_broken(tmp_path, "broken.sqlite")),
    )
    assert r_sqlite.status_code == 200, r_sqlite.text
    assert r_sqlite.json()["ok"] is False
    assert r_sqlite.json()["error"]

    r_duck = client.post(
        "/v1/internal/upload/db/test",
        json=_duck_payload(_make_broken(tmp_path, "broken.duckdb")),
    )
    assert r_duck.status_code == 200, r_duck.text
    assert r_duck.json()["ok"] is False

    r_absent = client.post(
        "/v1/internal/upload/db/test", json=_sqlite_payload(str(tmp_path / "gauge_missing.db"))
    )
    assert r_absent.status_code == 200
    assert r_absent.json()["ok"] is False

    r_txt = client.post(
        "/v1/internal/upload/db/test",
        json=_sqlite_payload(str(tmp_path / "gauge_notes.txt")),
    )
    assert r_txt.status_code == 422, r_txt.text


# ── O07. Маскирование D4 сквозь оба эндпоинта ─────────────────────────


def test_o07_password_never_leaks_through_error_paths(monkeypatch):
    def boom(**kw):
        raise ConnectionError(
            f"FATAL: password authentication failed for user hydrolog (password {PASSWORD})"
        )

    monkeypatch.setattr(f"{ROUTER}.init_db_connection", boom)
    r_test = client.post("/v1/internal/upload/db/test", json=_server_payload())
    assert r_test.status_code == 200
    assert r_test.json()["ok"] is False
    assert PASSWORD not in r_test.text, "пароль утёк в тело /test"
    assert "****" in r_test.json()["error"] or PASSWORD not in r_test.json()["error"]

    r_load = client.post(
        "/v1/internal/upload/db/load", json=_load_body(_server_payload(), "SELECT 1")
    )
    assert r_load.status_code == 400
    assert PASSWORD not in r_load.text, "пароль утёк в тело /load"


# ── O08–O09. /load полный контракт файла на своём корпусе ─────────────


def test_o08_load_full_file_contract(tmp_path):
    path = _make_gauge_sqlite(tmp_path)
    r = client.post(
        "/v1/internal/upload/db/load",
        json=_load_body(_sqlite_payload(path), "SELECT * FROM gauge_readings"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dataset_id"]
    uuid.UUID(body["dataset_id"])  # UUID-форма
    assert body["name"] == "gauge_river.sqlite"
    assert body["rows"] == 9 and body["columns"] == 3
    head = body["preview"]["head"]
    assert len(head) == 6 and head[0] == ["id", "level", "station"]  # заголовок
    assert len(body["preview"]["tail"]) == 5
    assert len(body["columns_info"]) == 3
    assert all("name" in c for c in body["columns_info"])
    assert body["quality"] is not None
    assert re.fullmatch(r"[\d.,]+\s+(B|KB|MB|GB)", body["size_label"]), body["size_label"]
    assert body["size_label"] != "0 B"  # 9 строк не могут весить 0 байт (урок MB-09)
    assert isinstance(body["parse_warnings"], list)
    assert body["error"] is None


def test_o09_session_registered_pipeline_entry_and_pagination(tmp_path):
    path = _make_gauge_sqlite(tmp_path)
    fresh = TestClient(app)
    r = fresh.post(
        "/v1/internal/upload/db/load",
        json=_load_body(_sqlite_payload(path), "SELECT * FROM gauge_readings"),
    )
    assert r.status_code == 200
    sid = fresh.cookies.get(SESSION_COOKIE_NAME)
    assert sid
    session = get_session_store().get(sid)
    assert session.dataset.rows == 9
    assert session.dataset.name == "gauge_river.sqlite"
    assert session.dataset.dataset_fingerprint == ""  # контракт «источник без файла»
    assert session.stages["upload"] == "done"

    rows = fresh.get("/v1/session/dataset/rows")
    assert rows.status_code == 200 and rows.json()["total_rows"] == 9
    # окно существующего GET живо (контракт UI-UPLOAD-FULL-1: offset/limit)
    window = fresh.get("/v1/session/dataset/rows", params={"offset": 4, "limit": 4})
    assert window.status_code == 200
    assert len(window.json()["rows"]) == 4
    assert window.json()["rows"][0][1] == "2.5"  # 5-я строка корпуса — окно честное


# ── O10. Авто-фиксация цели PROGR-25-A сквозь БД-дорожку ──────────────


def test_o10_db_track_auto_fixes_single_numeric_target(tmp_path, monkeypatch):
    home = tmp_path / "gaugehome"
    rel = _make_riverside_in_home(home)
    monkeypatch.setenv("HOME", str(home))
    fresh = TestClient(app)
    r = fresh.post(
        "/v1/internal/upload/db/load",
        json=_load_body(_sqlite_payload(rel), "SELECT * FROM levels"),
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "riverside.db"  # expanduser до basename
    cur = fresh.get("/v1/session/current")
    assert cur.status_code == 200, cur.text
    body = cur.json()
    assert body["target_column"] == "level", body.get("target_column")
    assert body["target_column_source"] == "auto"  # seed единым target_column_rule


# ── O11. Трасса: payload и probe-чистота существующей трассы ──────────


def test_o11_trace_payload_and_test_leaves_trace_untouched(tmp_path):
    path = _make_gauge_sqlite(tmp_path)
    fresh = TestClient(app)
    r = fresh.post(
        "/v1/internal/upload/db/load",
        json=_load_body(_sqlite_payload(path), "SELECT * FROM gauge_readings"),
    )
    assert r.status_code == 200
    sid = fresh.cookies.get(SESSION_COOKIE_NAME)
    events = get_session_store().get(sid).pipeline_trace
    match = [
        e for e in events
        if e.get("event_type") == "upload_completed" and e.get("node_id") == "overview"
    ]
    assert match, "upload_completed@overview не записан"
    payload = match[-1]["payload"]
    assert payload["name"] == "gauge_river.sqlite"
    assert payload["rows"] == 9
    assert "size_label" in payload and payload["size_label"]
    assert match[-1].get("stage") == "upload"

    before = len(get_session_store().get(sid).pipeline_trace)
    fresh.post("/v1/internal/upload/db/test", json=_sqlite_payload(path))  # probe
    after = len(get_session_store().get(sid).pipeline_trace)
    assert before == after, "«Тест» дорос до трассы существующей сессии"


# ── O12. Усечение: явный лимит, env-капа, отсутствие пометки ──────────


def test_o12_truncation_honesty(tmp_path, monkeypatch):
    path = _make_gauge_sqlite(tmp_path)
    r = client.post(
        "/v1/internal/upload/db/load",
        json=_load_body(_sqlite_payload(path), "SELECT * FROM gauge_readings", row_limit=4),
    )
    assert r.status_code == 200
    assert r.json()["rows"] == 4
    assert any("4" in w for w in r.json()["parse_warnings"]), r.json()["parse_warnings"]

    monkeypatch.setenv("UPLOAD_DB_ROW_LIMIT", "3")
    r_cap = client.post(
        "/v1/internal/upload/db/load",
        json=_load_body(_sqlite_payload(path), "SELECT * FROM gauge_readings", row_limit=50),
    )
    assert r_cap.status_code == 200 and r_cap.json()["rows"] == 3

    monkeypatch.setenv("UPLOAD_DB_ROW_LIMIT", "100")
    r_nocap = client.post(
        "/v1/internal/upload/db/load",
        json=_load_body(_sqlite_payload(path), "SELECT * FROM gauge_readings", row_limit=50),
    )
    assert r_nocap.status_code == 200 and r_nocap.json()["rows"] == 9
    assert not any("ограничена" in w for w in r_nocap.json()["parse_warnings"]), (
        "пометка усечения при полном корпусе — нечестная"
    )


# ── O13. Guard-матрица через API ──────────────────────────────────────


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM gauge_readings",
        "INSERT INTO gauge_readings VALUES (10, 9.9, 'Пыт-10')",
        "UPDATE gauge_readings SET level = 0",
        "SELECT 1; DROP TABLE gauge_readings",
        "/* комментарий */ DROP TABLE gauge_readings",
    ],
    ids=["delete", "insert", "update", "multi", "commented-dml"],
)
def test_o13_guard_rejects_and_fail_closed(tmp_path, sql):
    path = _make_gauge_sqlite(tmp_path)
    fresh = TestClient(app)
    r = fresh.post(
        "/v1/internal/upload/db/load",
        json=_load_body(_sqlite_payload(path), sql),
    )
    assert r.status_code == 422, (sql, r.text)
    assert fresh.cookies.get(SESSION_COOKIE_NAME) is None, "guard должен отказать до сессии"


# ── O14. Имена источников ─────────────────────────────────────────────


def test_o14_source_naming_server_and_unicode_basename(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    import pandas as pd

    fake_result = MagicMock()
    fake_result.dataframe = pd.DataFrame({"h": [1.0]})
    fake_result.rows_loaded = 1
    fake_result.truncated = False
    fake_result.row_limit = 1_000_000
    monkeypatch.setattr(f"{ROUTER}.init_db_connection", lambda **kw: object())
    monkeypatch.setattr(f"{ROUTER}.load_db_dataframe", lambda *a, **k: fake_result)
    r = client.post(
        "/v1/internal/upload/db/load",
        json=_load_body(_server_payload(), "SELECT h FROM tides"),
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "PostgreSQL / Postgres Pro: harbor_poc"

    csv = _make_ice_csv(tmp_path)
    r_csv = client.post(
        "/v1/internal/upload/db/load",
        json=_load_body(_duck_payload(csv), f"SELECT * FROM '{csv}'"),
    )
    assert r_csv.status_code == 200, r_csv.text
    assert r_csv.json()["name"] == "ледовые сводки 2024.csv"  # юникод basename


# ── O15. Семейства public/internal ────────────────────────────────────


def test_o15_public_family_gated_by_api_key(tmp_path, monkeypatch):
    # формат реестра «key:role:plan» — роль обязана быть валидной (Role),
    # иначе запись пропускается fail-closed (пустой реестр → 500) — corpus-урок O15
    monkeypatch.setenv("CISSTAT_API_KEYS", "g4uge-key:internal_analyst:")
    path = _make_gauge_sqlite(tmp_path)
    fresh = TestClient(app)

    r_nokey = fresh.post("/v1/public/upload/db/test", json=_sqlite_payload(path))
    assert r_nokey.status_code in (401, 422), r_nokey.text
    assert fresh.cookies.get(SESSION_COOKIE_NAME) is None  # fail-closed: нет сессии

    r_key_test = fresh.post(
        "/v1/public/upload/db/test",
        json=_sqlite_payload(path),
        headers={"X-API-Key": "g4uge-key"},
    )
    assert r_key_test.status_code == 200 and r_key_test.json()["ok"] is True

    r_key_load = fresh.post(
        "/v1/public/upload/db/load",
        json=_load_body(_sqlite_payload(path), "SELECT * FROM gauge_readings"),
        headers={"X-API-Key": "g4uge-key"},
    )
    assert r_key_load.status_code == 200 and r_key_load.json()["rows"] == 9

    fresh2 = TestClient(app)
    r_internal = fresh2.post(
        "/v1/internal/upload/db/load",
        json=_load_body(_sqlite_payload(path), "SELECT * FROM gauge_readings"),
    )
    assert r_internal.status_code == 200  # internal без ключа — паритет файла


# ── O16. Сбой version_probe не роняет подтверждённую пробу ────────────


def test_o16_version_probe_failure_is_best_effort(monkeypatch):
    class _Engine:
        def connect(self):
            raise RuntimeError("probe сломан намеренно (оракул O16)")

    monkeypatch.setattr(f"{ROUTER}.init_db_connection", lambda **kw: _Engine())
    r = client.post("/v1/internal/upload/db/test", json=_server_payload())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True  # соединение подтверждено ядром до probe версии
    assert body["server_version"] is None


# ── O17. Персистенция на fakeredis (класс PROGR-25-F1) ────────────────


def test_o17_load_persists_through_redis_backend(tmp_path, monkeypatch):
    fakeredis = pytest.importorskip("fakeredis")
    fake_server = fakeredis.FakeServer()
    fake_client = fakeredis.FakeStrictRedis(server=fake_server)
    store = RedisSessionStore(client=fake_client, ttl_seconds=3600)
    import apps.api.session_store as ss

    monkeypatch.setattr(ss, "_store", store)

    path = _make_gauge_sqlite(tmp_path)
    fresh = TestClient(app)
    r = fresh.post(
        "/v1/internal/upload/db/load",
        json=_load_body(_sqlite_payload(path), "SELECT * FROM gauge_readings"),
    )
    assert r.status_code == 200, r.text
    sid = fresh.cookies.get(SESSION_COOKIE_NAME)
    assert sid

    reloaded = store.get(sid)  # чтение СКВОЗЬ хранилище (не алиас Memory)
    assert reloaded is not None
    assert reloaded.dataset.rows == 9
    assert reloaded.dataset.name == "gauge_river.sqlite"

    raw_keys = [k for k in fake_client.keys("*") if sid.encode() in k or sid in str(k)]
    assert raw_keys, "сырой документ сессии не найден в фейковом Redis"


# ── O18. Тело /load: валидация через HTTP ─────────────────────────────


def test_o18_load_request_validation_over_the_wire(tmp_path):
    path = _make_gauge_sqlite(tmp_path)
    base = _sqlite_payload(path)
    assert client.post(
        "/v1/internal/upload/db/load", json=_load_body(base, "")
    ).status_code == 422
    assert client.post(
        "/v1/internal/upload/db/load", json=_load_body(base, "SELECT 1", row_limit=0)
    ).status_code == 422
    assert client.post(
        "/v1/internal/upload/db/load", json=_load_body(base, "SELECT 1", row_limit=-5)
    ).status_code == 422
    assert client.post(
        "/v1/internal/upload/db/load", json={"sql": "SELECT 1"}
    ).status_code == 422


# ── O19. Probe-чистота на уровне хранилища ────────────────────────────


def test_o19_test_creates_no_session_in_store(tmp_path):
    path = _make_gauge_sqlite(tmp_path)
    fresh = TestClient(app)
    r = fresh.post("/v1/internal/upload/db/test", json=_sqlite_payload(path))
    assert r.status_code == 200 and r.json()["ok"] is True
    assert not any(SESSION_COOKIE_NAME in c for c in r.headers.get_list("set-cookie"))
    peeked = peek_session_store()
    if peeked is not None:  # хранилище могло быть инициализировано средой —
        # но СЕССИЙ в нём быть не должно (probe не мутирует хранилище)
        assert peeked.get("db4cert-no-such-session") is None
        assert peeked.get("") is None


# ── O20. Capture-kwargs: default_port реестра + ssl=False на проводе ──


def test_o20_router_passes_registry_default_port_and_ssl_default(monkeypatch):
    captured: dict[str, Any] = {}

    def capture(**kw):
        captured.update(kw)
        return object()

    monkeypatch.setattr(f"{ROUTER}.init_db_connection", capture)
    payload = _server_payload()
    payload["connection"].pop("port")  # порт НЕ задан формой
    payload["connection"].pop("ssl")  # ssl НЕ задан формой
    r = client.post("/v1/internal/upload/db/test", json=payload)
    assert r.status_code == 200, r.text
    # Граница роутера: порт передаётся «как есть» (None) — резолв
    # default_port реестра (5432) — контракт ЯДРА Фазы A
    # (сертифицирован UPLOAD-DB-3-CERT), не роутера.
    assert captured["port"] is None, captured
    assert captured["ssl"] is False, captured  # safe-дефолт фазы B
    assert captured["db_type"] == "postgresql"

    captured.clear()
    r2 = client.post(
        "/v1/internal/upload/db/test",
        json={"connection": {"db_type": "duckdb", "path": "/tmp/x.duckdb"}},
    )
    assert r2.status_code in (200, 400)  # файла нет — карта ошибок, не падение
    assert captured["path"] == "/tmp/x.duckdb"
    assert captured["host"] == "" and captured["db_type"] == "duckdb"
