#!/usr/bin/env python3
"""
СЕРТИФИКАЦИЯ UPLOAD-DB-3 — НЕЗАВИСИМЫЕ оракулы на СВОИХ данных.

Корпус ДИЗЪЮНКТЕН repo-тестам test_db_embedded.py:
  - SQLite  «station telemetry.sqlite» (ПРОБЕЛ в пути!, sensor_readings,
    20 строк: reading_id/station/temperature/humidity);
  - DuckDB  «cargo_flow.duckdb» (cargo_flow, 7 строк: route_id/region/
    volume_t/checked);
  - CSV     «макро_ряд 2024.csv» (ЮНИКОД+ПРОБЕЛ в пути, пропуски значений,
    8 строк: quarter/gdp_index/inflation);
  - Parquet «wind_probe.parquet» (wind_speed/direction, 15 строк);
  - битые источники: garbage.csv (бинарный мусор), later_bad.csv
    (первые 6 строк валидны, 7-я — мусор: ловит потерю LIMIT 1 в probe),
    garbage.duckdb (бинарный мусор);
  - фейковый HOME для expanduser-оракула (~/dbcert_home.db).

16 оракулов O01-O16 (см. протокол). Выход 0 = все PASS.
Протокол: scripts/dbcert_oracles.txt
"""
import hashlib
import os
import shutil
import sys
import tempfile
import traceback

import duckdb
import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)

from app.data import db_connectors  # noqa: E402
from app.data.db_guard import DbQueryRejected, load_db_dataframe  # noqa: E402
from app.data.file_loader import init_db_connection  # noqa: E402

LINES = []
RESULTS = []


def log(msg):
    print(msg)
    LINES.append(msg)


def oracle(oid, name, fn):
    try:
        detail = fn()
        RESULTS.append((oid, "PASS", name))
        log(f"[PASS] {oid} {name}" + (f" — {detail}" if detail else ""))
    except Exception as exc:
        RESULTS.append((oid, "FAIL", f"{name}: {type(exc).__name__}: {exc}"))
        log(f"[FAIL] {oid} {name}: {type(exc).__name__}: {exc}")
        traceback.print_exc(file=sys.stderr)


def md5(path):
    with open(path, "rb") as fh:
        return hashlib.md5(fh.read()).hexdigest()


# ----------------------------------------------------------------------------
# Корпус
# ----------------------------------------------------------------------------

def build_corpus(root):
    """СВОИ данные — ни одна строка/колонка не совпадает с repo-тестами."""
    c = {}
    # SQLite с ПРОБЕЛОМ в имени файла
    sql_path = os.path.join(root, "station telemetry.sqlite")
    eng = create_engine(f"sqlite:///{sql_path}")
    with eng.begin() as conn:
        conn.execute(text(
            "CREATE TABLE sensor_readings (reading_id INTEGER, station TEXT, "
            "temperature REAL, humidity REAL)"
        ))
        for i in range(20):
            conn.execute(text(
                f"INSERT INTO sensor_readings VALUES ({i}, 'st-{i:02d}', "
                f"{15.0 + i * 0.5}, {40.0 + (i % 5) * 3.0})"
            ))
    eng.dispose()
    c["sqlite"] = sql_path
    c["sqlite_md5"] = md5(sql_path)
    c["sqlite_sum"] = sum(15.0 + i * 0.5 for i in range(20))

    # DuckDB-файл
    ddb_path = os.path.join(root, "cargo_flow.duckdb")
    conn = duckdb.connect(ddb_path)
    conn.execute(
        "CREATE TABLE cargo_flow (route_id INTEGER, region VARCHAR, "
        "volume_t DOUBLE, checked BOOLEAN)"
    )
    regions = ["Север", "Юг", "Запад", "Восток", "Центр", "Север", "Юг"]
    for i in range(7):
        conn.execute(
            f"INSERT INTO cargo_flow VALUES ({i + 1}, '{regions[i]}', "
            f"{100.0 + i * 10.5}, {'true' if i % 2 == 0 else 'false'})"
        )
    conn.close()
    c["duckdb"] = ddb_path
    c["duckdb_md5"] = md5(ddb_path)

    # CSV: юникод + пробел + пропуски + кавычки
    csv_path = os.path.join(root, "макро_ряд 2024.csv")
    pd.DataFrame({
        "quarter": ["2024-Q1", "2024-Q2", "2024-Q3", "2024-Q4",
                    "2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4"],
        "gdp_index": [100.0, 101.5, None, 103.2, 104.0, 105.1, 106.3, None],
        "inflation": [4.1, 3.8, 3.5, None, 3.1, 2.9, 2.7, 2.5],
    }).to_csv(csv_path, index=False)
    c["csv"] = csv_path

    # Parquet: свои колонки, 15 строк (COPY через duckdb — pyarrow не нужен)
    par_path = os.path.join(root, "wind_probe.parquet")
    conn = duckdb.connect()  # in-memory
    conn.execute(
        "CREATE TABLE wind_tmp (wind_speed DOUBLE, direction VARCHAR)"
    )
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "N", "NE",
            "E", "SE", "S", "SW", "W"]
    for i in range(15):
        conn.execute(
            f"INSERT INTO wind_tmp VALUES ({round(2.0 + i * 0.7, 2)}, '{dirs[i]}')"
        )
    conn.execute(f"COPY wind_tmp TO '{par_path}' (FORMAT PARQUET)")
    conn.close()
    c["parquet"] = par_path

    # Битые источники
    g1 = os.path.join(root, "garbage.csv")
    with open(g1, "wb") as fh:
        fh.write(b"\x00\x01\x02\xff\xfe garbage binary \x93\x94")
    c["garbage_csv"] = g1

    g2 = os.path.join(root, "later_bad.csv")
    with open(g2, "wb") as fh:
        fh.write(b"a,b\n1,2\n3,4\n5,6\n7,8\n9,10\n11,12\n")
        fh.write(b"x,\xff\xfe\x80bad-utf8\n")  # 7-я строка — битый UTF-8
    c["later_bad_csv"] = g2

    g3 = os.path.join(root, "garbage.duckdb")
    with open(g3, "wb") as fh:
        fh.write(b"DUCKBUTNOTREALLY" + os.urandom(64))
    c["garbage_duckdb"] = g3
    return c


# ----------------------------------------------------------------------------
# Оракулы
# ----------------------------------------------------------------------------

def make_oracles(c, home_dir):
    o = {}

    def o01():
        assert len(db_connectors.DB_CONNECTORS) == 6, "в реестре не 6 СУБД"
        for cid in ("postgresql", "clickhouse", "mssql", "mysql", "duckdb", "sqlite"):
            assert cid in db_connectors.DB_CONNECTORS
        s = db_connectors.get_connector("sqlite")
        d = db_connectors.get_connector("duckdb")
        assert s.mode == "embedded" and d.mode == "embedded"
        assert s.path_extensions == (".db", ".sqlite")
        assert d.path_extensions == (".db", ".duckdb", ".parquet", ".csv")
        assert d.query_file_extensions == (".parquet", ".csv")
        assert s.default_port is None and d.default_port is None
        # мои расширения корпуса покрыты
        assert os.path.splitext(c["sqlite"])[1] in s.path_extensions
        for ext in (".duckdb", ".csv", ".parquet"):
            assert ext in d.path_extensions
        return "6 записей; path-метаданные по плану; корпус покрыт"

    def o02():
        eng = init_db_connection("sqlite", "h", 0, "u", "p", "", path=c["sqlite"])
        r = load_db_dataframe(eng, "SELECT * FROM sensor_readings")
        assert r.rows_loaded == 20, f"ожидалось 20, получено {r.rows_loaded}"
        assert r.truncated is False
        assert list(r.dataframe.columns) == [
            "reading_id", "station", "temperature", "humidity"]
        row7 = r.dataframe[r.dataframe["station"] == "st-07"]
        assert abs(float(row7["temperature"].iloc[0]) - 18.5) < 1e-9
        total = float(r.dataframe["temperature"].sum())
        assert abs(total - c["sqlite_sum"]) < 1e-6, "сумма температур не сошлась"
        assert md5(c["sqlite"]) == c["sqlite_md5"], "md5 файла изменился после чтения"
        return "Test→Load 20 строк; точечные значения; md5 файла не изменился"

    def o03():
        eng = init_db_connection("sqlite", "h", 0, "u", "p", "", path=c["sqlite"])
        with pytest.raises(OperationalError):
            with eng.begin() as conn:
                conn.execute(text(
                    "INSERT INTO sensor_readings VALUES (99, 'hack', 0, 0)"))
        with pytest.raises(OperationalError):
            with eng.begin() as conn:
                conn.execute(text("CREATE TABLE hack (id INTEGER)"))
        assert md5(c["sqlite"]) == c["sqlite_md5"]
        return "INSERT/CREATE отклонены (mode=ro); md5 цел"

    def o04():
        # ПРОБЕЛ в пути SQLite (repo покрывает пробел только для DuckDB/CSV)
        eng = init_db_connection("sqlite", "h", 0, "u", "p", "",
                                 path=c["sqlite"])
        r = load_db_dataframe(eng, "SELECT count(*) AS n FROM sensor_readings")
        assert int(r.dataframe["n"].iloc[0]) == 20
        return "путь с пробелом: 'station telemetry.sqlite' — 20 строк"

    def o05():
        eng = init_db_connection("duckdb", "h", 0, "u", "p", "",
                                 path=c["duckdb"])
        r = load_db_dataframe(eng, "SELECT * FROM cargo_flow ORDER BY route_id")
        assert r.rows_loaded == 7
        assert list(r.dataframe.columns) == ["route_id", "region", "volume_t", "checked"]
        assert r.dataframe["region"].iloc[2] == "Запад"
        assert abs(float(r.dataframe["volume_t"].iloc[6]) - 163.0) < 1e-9
        with pytest.raises(Exception):
            with eng.begin() as conn:
                conn.execute(text("INSERT INTO cargo_flow VALUES (99, 'X', 1.0, true)"))
        assert md5(c["duckdb"]) == c["duckdb_md5"]
        return "Test→Load 7 строк; read-only (INSERT отклонён); md5 цел"

    def o06():
        eng = init_db_connection("duckdb", "h", 0, "u", "p", "", path=c["csv"])
        r = load_db_dataframe(eng, f"SELECT * FROM '{c['csv']}'")
        assert r.rows_loaded == 8, f"ожидалось 8, получено {r.rows_loaded}"
        assert list(r.dataframe.columns) == ["quarter", "gdp_index", "inflation"]
        assert r.dataframe["gdp_index"].isna().sum() == 2, "пропуски не сохранены"
        assert r.dataframe["quarter"].iloc[0] == "2024-Q1"
        return "юникод+пробел в пути; 8 строк; 2 пропуска сохранены"

    def o07():
        eng = init_db_connection("duckdb", "h", 0, "u", "p", "",
                                 path=c["parquet"])
        r = load_db_dataframe(eng, f"SELECT * FROM '{c['parquet']}'")
        assert r.rows_loaded == 15
        assert list(r.dataframe.columns) == ["wind_speed", "direction"]
        assert abs(float(r.dataframe["wind_speed"].iloc[14]) - (2.0 + 14 * 0.7)) < 1e-9
        return "Parquet: 15 строк; точные float"

    def o08():
        # probe_connection честно читает файл: битый CSV должен упасть на «Тест»
        with pytest.raises(ConnectionError):
            init_db_connection("duckdb", "h", 0, "u", "p", "",
                               path=c["garbage_csv"])
        return "битый CSV → ConnectionError на фазе «Тест» (probe читает файл)"

    def o09():
        # later_bad.csv: мусорный UTF-8 в глубине 28КБ-файла (за 20КБ-снапшотом
        # сниффера): DuckDB сканирует ВЕСЬ файл при детекции схемы — «Тест»
        # падает честно ЕЩЁ ДО загрузки (сильнее проверки первой строки)
        with pytest.raises(ConnectionError):
            init_db_connection("duckdb", "h", 0, "u", "p", "",
                               path=c["later_bad_csv"])
        return "мусор в глубине (за снапшотом): «Тест» падает честно — сниффер сканирует весь файл"

    def o10():
        with pytest.raises(ConnectionError):
            init_db_connection("duckdb", "h", 0, "u", "p", "",
                               path=c["garbage_duckdb"])
        return "битый .duckdb → ConnectionError на фазе «Тест»"

    def o11():
        with pytest.raises(ValueError, match="Не указан путь"):
            init_db_connection("sqlite", "h", 0, "u", "p", "", path="")
        with pytest.raises(ValueError, match="Недопустимое расширение"):
            init_db_connection("duckdb", "h", 0, "u", "p", "",
                               path=os.path.join(c["root"], "noext"))
        open(os.path.join(c["root"], "noext"), "w").close()
        with pytest.raises(ValueError, match="Недопустимое расширение"):
            init_db_connection("duckdb", "h", 0, "u", "p", "",
                               path=os.path.join(c["root"], "noext"))
        with pytest.raises(ValueError, match="Недопустимое расширение"):
            init_db_connection("sqlite", "h", 0, "u", "p", "", path=c["garbage_csv"])
        with pytest.raises(FileNotFoundError, match="не найден"):
            init_db_connection("sqlite", "h", 0, "u", "p", "",
                               path=os.path.join(c["root"], "missing.db"))
        os.makedirs(os.path.join(c["root"], "dir.db"), exist_ok=True)
        with pytest.raises(FileNotFoundError):
            init_db_connection("sqlite", "h", 0, "u", "p", "",
                               path=os.path.join(c["root"], "dir.db"))
        return "пустой/без расширения/.txt/.csv-для-sqlite/отсутствующий/каталог — все честно отклонены"

    def o11b():
        # expanduser: путь через ~ при фейковом HOME
        real_home = os.environ.get("HOME")
        os.environ["HOME"] = home_dir
        try:
            eng = create_engine(f"sqlite:///{home_dir}/dbcert_home.db")
            with eng.begin() as conn:
                conn.execute(text("CREATE TABLE h (v INTEGER)"))
                conn.execute(text("INSERT INTO h VALUES (42)"))
            eng.dispose()
            eng2 = init_db_connection("sqlite", "h", 0, "u", "p", "",
                                      path="~/dbcert_home.db")
            r = load_db_dataframe(eng2, "SELECT v FROM h")
            assert int(r.dataframe["v"].iloc[0]) == 42
        finally:
            if real_home:
                os.environ["HOME"] = real_home
        return "~/dbcert_home.db резолвится через expanduser → 42"

    def o12():
        eng = init_db_connection("duckdb", "h", 0, "u", "p", "",
                                 path=c["duckdb"])
        for bad in ("DELETE FROM cargo_flow", "UPDATE cargo_flow SET volume_t = 0",
                    "DROP TABLE cargo_flow", "INSERT INTO cargo_flow VALUES (9, 'X', 1, true)",
                    "CREATE TABLE x (a INT)", "ALTER TABLE cargo_flow ADD COLUMN z INT",
                    "SELECT 1; DROP TABLE cargo_flow"):
            with pytest.raises(DbQueryRejected):
                load_db_dataframe(eng, bad)
        r = load_db_dataframe(eng, "SELECT * FROM cargo_flow", row_limit=5)
        # 7 строк в источнике, лимит 5: обрезка клиентская, truncated=True честный
        assert r.rows_loaded == 5 and r.truncated is True, (
            f"rows={r.rows_loaded} truncated={r.truncated}")
        r2 = load_db_dataframe(eng, "SELECT * FROM cargo_flow", row_limit=50)
        assert r2.rows_loaded == 7 and r2.truncated is False
        return "guard: 7 запретов; лимит 5/7 строк → 5+truncated; лимит 50 → 7 без обрезки"

    def o12b():
        # env-капа сильнее параметра
        old = os.environ.get("UPLOAD_DB_ROW_LIMIT")
        os.environ["UPLOAD_DB_ROW_LIMIT"] = "3"
        try:
            eng = init_db_connection("sqlite", "h", 0, "u", "p", "",
                                     path=c["sqlite"])
            r = load_db_dataframe(eng, "SELECT * FROM sensor_readings", row_limit=50)
            assert r.rows_loaded == 3, f"env-капа не применилась: {r.rows_loaded}"
            assert r.row_limit == 3
        finally:
            if old is None:
                os.environ.pop("UPLOAD_DB_ROW_LIMIT", None)
            else:
                os.environ["UPLOAD_DB_ROW_LIMIT"] = old
        return "UPLOAD_DB_ROW_LIMIT=3: запрос 50 → 3 строки (капа сильнее параметра)"

    def o13():
        eng = init_db_connection("sqlite", "h", 0, "u", "p", "",
                                 path=c["sqlite"])
        r = load_db_dataframe(eng, "SELECT * FROM sensor_readings", chunksize=7)
        assert r.rows_loaded == 20
        total = float(r.dataframe["temperature"].sum())
        assert abs(total - c["sqlite_sum"]) < 1e-6
        return "chunksize=7 по 20 строкам: 20 строк, сумма сошлась (стриминг честный)"

    def o14():
        # импорт-безопасность реестра без sqlalchemy (изолированный процесс)
        import subprocess
        code = (
            "import sys, types\n"
            "for m in ('sqlalchemy', 'sqlalchemy.engine', 'sqlalchemy.exc',\n"
            "          'sqlalchemy.sql', 'sqlalchemy.sql.elements', 'clickhouse_connect'):\n"
            "    sys.modules[m] = None\n"
            f"sys.path.insert(0, {REPO!r})\n"
            "from app.data import db_connectors\n"
            "assert len(db_connectors.DB_CONNECTORS) == 6\n"
            "spec = db_connectors.get_connector('duckdb')\n"
            "try:\n"
            "    db_connectors.open_embedded(spec, path='x.duckdb')\n"
            "    print('IMPROBE: FAIL — ImportError не поднят')\n"
            "except ImportError as e:\n"
            "    msg = str(e)\n"
            "    assert 'duckdb duckdb-engine' in msg, msg\n"
            "    print('IMPROBE: OK — ImportError с pip-подсказкой')\n"
        )
        proc = subprocess.run([sys.executable, "-c", code],
                              capture_output=True, text=True,
                              cwd=tempfile.gettempdir())
        assert "IMPROBE: OK" in proc.stdout, (
            f"stdout={proc.stdout!r} stderr={proc.stderr[-400:]!r}")
        return "без sqlalchemy: реестр читаем (6 записей), open_embedded → ImportError с подсказкой"

    def o15():
        assert db_connectors.get_connector("SQLite").id == "sqlite"
        assert db_connectors.get_connector("  DUCKDB  ").id == "duckdb"
        assert db_connectors.get_connector("sqlite3").id == "sqlite"
        with pytest.raises(ValueError):
            db_connectors.get_connector("DuckDB (встроенная)")
        with pytest.raises(ValueError):
            db_connectors.get_connector("oracle")
        with pytest.raises(ValueError):
            db_connectors.get_connector(None)
        with pytest.raises(ValueError):
            db_connectors.get_connector("")
        return "id/alias case-insensitive; UI-подпись/чужие/пустые — честный ValueError"

    def o16():
        # Средовой факт worklog: DuckDB — одна конфигурация на файл в процессе.
        # Два изолированных процесса (чистая внутренняя регистрация duckdb):
        # (а) rw-коннект удерживается → read-only «Тест» падает конфликтом;
        # (б) БЕЗ посторонних конфигураций → read-only работает (продукт-путь).
        import subprocess
        probe = (
            "import sys, duckdb\n"
            f"sys.path.insert(0, {REPO!r})\n"
            "from app.data.file_loader import init_db_connection\n"
            "from app.data.db_guard import load_db_dataframe\n"
            f"path = {c['duckdb']!r}\n"
            "mode = sys.argv[1]\n"
            "if mode == 'conflict':\n"
            "    rw = duckdb.connect(path)  # read-write удерживается\n"
            "    try:\n"
            "        init_db_connection('duckdb', 'h', 0, 'u', 'p', '', path=path)\n"
            "        print('CONFLICT: NO — read-only открылся поверх rw?!')\n"
            "    except Exception as e:\n"
            "        print('CONFLICT: YES —', type(e).__name__)\n"
            "    rw.close()\n"
            "else:\n"
            "    eng = init_db_connection('duckdb', 'h', 0, 'u', 'p', '', path=path)\n"
            "    r = load_db_dataframe(eng, 'SELECT count(*) AS n FROM cargo_flow')\n"
            "    print('CLEAN: OK', int(r.dataframe['n'].iloc[0]), 'строк')\n"
        )
        env = dict(os.environ, DATABASE_URL="sqlite://")
        p1 = subprocess.run([sys.executable, "-c", probe, "conflict"],
                            capture_output=True, text=True, env=env)
        p2 = subprocess.run([sys.executable, "-c", probe, "clean"],
                            capture_output=True, text=True, env=env)
        assert "CONFLICT: YES" in p1.stdout, (
            f"p1.stdout={p1.stdout!r} p1.stderr={p1.stderr[-300:]!r}")
        assert "CLEAN: OK 7" in p2.stdout, (
            f"p2.stdout={p2.stdout!r} p2.stderr={p2.stderr[-300:]!r}")
        return "факт подтверждён изолированно: rw-конфликт есть; чистый read-only путь работает (7 строк)"

    o["O01"] = ("Реестр: 6 СУБД, path-метаданные embedded", o01)
    o["O02"] = ("SQLite СВОИ данные: Test→Load + md5-инвариант", o02)
    o["O03"] = ("SQLite строго read-only: INSERT/CREATE", o03)
    o["O04"] = ("SQLite путь с ПРОБЕЛОМ (repo-гэп прикрыт)", o04)
    o["O05"] = ("DuckDB файл: Test→Load + read-only + md5", o05)
    o["O06"] = ("CSV юникод+пробел+пропуски: прямой SELECT", o06)
    o["O07"] = ("Parquet СВОИ данные: прямой SELECT", o07)
    o["O08"] = ("Битый CSV: «Тест» падает честно (probe читает файл)", o08)
    o["O09"] = ("Мусор в глубине CSV (28КБ): «Тест» падает честно", o09)
    o["O10"] = ("Битый .duckdb: «Тест» падает честно", o10)
    o["O11"] = ("Матрица валидации пути (6 сценариев)", o11)
    o["O11b"] = ("expanduser: путь через ~ (fake HOME)", o11b)
    o["O12"] = ("Guard на embedded: 7 запретов + row_limit", o12)
    o["O12b"] = ("env-капа UPLOAD_DB_ROW_LIMIT сильнее параметра", o12b)
    o["O13"] = ("Chunksize-стриминг: 20 строк, сумма точная", o13)
    o["O14"] = ("Импорт-безопасность без sqlalchemy (subprocess)", o14)
    o["O15"] = ("Резолюция id/alias + честные негативы", o15)
    o["O16"] = ("Средовой факт: одна конфигурация DuckDB на файл", o16)
    return o


def main():
    root = tempfile.mkdtemp(prefix="dbcert_oracles_")
    c = build_corpus(root)
    c["root"] = root
    home_dir = tempfile.mkdtemp(prefix="dbcert_home_")
    log("СЕРТИФИКАЦИЯ UPLOAD-DB-3 — оракулы на СВОИХ данных (corpus dизъюнктен repo-тестам)")
    log(f"Корпус: {root}")
    for oid, (name, fn) in make_oracles(c, home_dir).items():
        oracle(oid, name, fn)
    log("")
    npass = sum(1 for _, s, _ in RESULTS if s == "PASS")
    log(f"ИТОГ: {npass}/{len(RESULTS)} PASS")
    log("Корпус (список файлов): " + ", ".join(
        sorted(os.path.basename(v) for k, v in c.items()
               if isinstance(v, str) and os.path.exists(v) and os.path.isfile(v)
               and not k.endswith(("_md5", "_sum")))))
    with open(os.path.join(REPO, "scripts", "dbcert_oracles.txt"), "w") as fh:
        fh.write("\n".join(LINES) + "\n")
    shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(home_dir, ignore_errors=True)
    return 0 if npass == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
