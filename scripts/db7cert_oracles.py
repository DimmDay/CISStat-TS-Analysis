# scripts/db7cert_oracles.py
"""
Независимая сертификация UPLOAD-DB-7 — оракулы на СВОИХ данных.

Корпус «высокогорная метеосеть Памира» (гляциологический пост,
ледник Федченко) ДИЗЪЮНКТЕН repo-корпусу (h/db.corp/dw/pw/mysql-pw/
mssql-pw) и корпусам прошлых сертификаций (db4cert «припортовая
гидрологическая сеть»; db3cert — embedded-файлы). Пароли содержат
юникод и спецсимволы ODBC (';{}') — честная проверка экранирования.

Поверхности глубже/дизъюнктны repo-тестам: env-переопределения
таймаутов, кейс/пробелы в UPLOAD_DB_MSSQL_DRIVER, D4-матрица всех
серверных путей (включая pymssql), сквозное делегирование
file_loader.init_db_connection, handshake pymssql-диалекта,
статические пины requirements/Dockerfile.

Запуск: DATABASE_URL="" python -m pytest scripts/db7cert_oracles.py -q
"""
from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app.data.db_connectors as dc  # noqa: E402
from app.data.db_connectors import (  # noqa: E402
    DB_CONNECTORS,
    build_server_url,
    get_connector,
    open_server_engine,
)
# _odbc_quote импортируется ЛОКАЛЬНО в test_o09: поверхность целиком
# отсутствует на родителе e2fa9a1 — локальный импорт даёт честную
# по-оракульную гранулярность RED вместо ошибки коллекции всего файла.

# --- Корпус «высокогорная метеосеть Памира» (свой, дизъюнктный) ---------
HOST = "meteo.pamir.gla"          # гляциологический пост, ледник Федченко
DB = "pamir_observations"
USER = "hydrolog_pamir"
PWD_MYSQL = "ледник;Федченко{2026}"       # юникод + ';' + '{}' (спецсимволы ODBC)
PWD_MSSQL = "p@ss;w0rd}}Памир"            # ';' + удвоенная '}' — жёсткий пин экранирования
PWD_PLAIN = "snyeg2026"


def _mssql(**kw):
    base = dict(host=HOST, port=1433, database=DB, username=USER, password=PWD_MSSQL)
    base.update(kw)
    return build_server_url(get_connector("mssql"), **base)


def _mysql(**kw):
    base = dict(host=HOST, port=None, database=DB, username=USER, password=PWD_MYSQL)
    base.update(kw)
    return build_server_url(get_connector("mysql"), **base)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Детерминизм: env-переключатели сертифицируемого кода очищены."""
    for name in ("UPLOAD_DB_MSSQL_DRIVER", "UPLOAD_DB_CONNECT_TIMEOUT",
                 "UPLOAD_DB_QUERY_TIMEOUT", "UPLOAD_DB_HOST_WHITELIST"):
        monkeypatch.delenv(name, raising=False)


# --- O01-O04: MySQL/MariaDB (mysql+pymysql, порт 3306) -------------------

def test_o01_mysql_d4_unicode_password_nowhere_in_url():
    """D4: юникод-пароль с ';'/'{}' отсутствует ВЕЗДЕ в URL-объекте
    (str(), render_as_string(hide_password=False), url.password) —
    и в connect_args приходит СЫРЫМ (PyMySQL — нативный API)."""
    url, connect_args = _mysql()
    assert url.password is None
    assert PWD_MYSQL not in str(url)
    assert PWD_MYSQL not in url.render_as_string(hide_password=False)
    assert connect_args["password"] == PWD_MYSQL
    assert "PWD" not in connect_args


def test_o02_mysql_default_port_3306_rendered():
    url, _ = _mysql(port=None)
    assert url.drivername == "mssql+pymysql" or url.drivername == "mysql+pymysql"
    assert url.drivername == "mysql+pymysql"
    assert url.port == 3306
    assert "meteo.pamir.gla:3306" in url.render_as_string(hide_password=False)
    assert url.host == HOST and url.database == DB


def test_o03_mysql_ssl_flags_exclusive():
    """D3 MySQL: ssl=True -> ssl_verify_cert (проверка сертификата) БЕЗ
    ssl_disabled; ssl=False -> ssl_disabled БЕЗ verify. Флаги — в
    connect_args (PyMySQL), в query URL их нет."""
    url_on, ca_on = _mysql(ssl=True)
    url_off, ca_off = _mysql(ssl=False)
    assert ca_on["ssl_verify_cert"] is True and "ssl_disabled" not in ca_on
    assert ca_off["ssl_disabled"] is True and "ssl_verify_cert" not in ca_off
    assert "ssl" not in url_on.query and "ssl" not in url_off.query


def test_o04_mysql_connect_timeout_and_env_override():
    """S4-паритет: connect_timeout=10 (дефолт); env UPLOAD_DB_CONNECT_TIMEOUT
    переопределяет (поверхность repo не пинит для mysql)."""
    _, ca = _mysql()
    assert ca["connect_timeout"] == 10
    import os
    with patch.dict(os.environ, {"UPLOAD_DB_CONNECT_TIMEOUT": "7"}):
        _, ca_env = _mysql()
    assert ca_env["connect_timeout"] == 7


# --- O05-O09: MSSQL pyodbc (пересмотр D4, ODBC-экранирование) ------------

def test_o05_mssql_d4_password_not_in_url_object():
    """Пересмотр D4 (главное изменение DB-7): пароль ВЫВЕДЕН из URL-объекта —
    url.password is None, сырья нет даже в render_as_string(hide_password=False)."""
    url, connect_args = _mssql()
    assert url.drivername == "mssql+pyodbc"
    assert url.password is None
    assert PWD_MSSQL not in str(url)
    assert PWD_MSSQL not in url.render_as_string(hide_password=False)


def test_o06_mssql_pwd_odbc_escaped_special_passwords():
    """PWD в connect_args с ODBC-экранированием: ';' и '}' спец-пароля
    не ломают строку соединения; '}' удваивается, обёртка в скобки."""
    _, ca = _mssql()
    assert ca["PWD"] == "{p@ss;w0rd}}}}Памир}"  # }} -> }}}} (удвоение каждой)
    _, ca_mysql_pw = _mssql(password=PWD_MYSQL)
    # только '}' удваивается ('{' не трогается): raw 'ледник;Федченко{2026}'
    assert ca_mysql_pw["PWD"] == "{ледник;Федченко{2026}}}"


def test_o07_mssql_query_odbc_flags():
    """ODBC-параметры в query URL (не секреты): driver ODBC 18 всегда;
    Encrypt no/yes; TrustServerCertificate=no ТОЛЬКО при ssl."""
    url_off, _ = _mssql(ssl=False)
    url_on, _ = _mssql(ssl=True)
    assert url_off.query["driver"] == "ODBC Driver 18 for SQL Server"
    assert url_off.query["Encrypt"] == "no"
    assert "TrustServerCertificate" not in url_off.query
    assert url_on.query["Encrypt"] == "yes"
    assert url_on.query["TrustServerCertificate"] == "no"
    # render_as_string URL-энкодит query (пробелы -> '+')
    assert "ODBC+Driver+18+for+SQL+Server" in url_off.render_as_string()


def test_o08_mssql_login_timeout_and_env_override():
    """S4-паритет: kwarg timeout (login-таймаут pyodbc) = 10; env-переопределение."""
    _, ca = _mssql()
    assert ca["timeout"] == 10
    import os
    with patch.dict(os.environ, {"UPLOAD_DB_CONNECT_TIMEOUT": "3"}):
        _, ca_env = _mssql()
    assert ca_env["timeout"] == 3


def test_o09_odbc_quote_own_pins():
    """_odbc_quote — таблица экранирования на своих данных: пустая строка,
    кавычка (легальна внутри скобок), '}', ';', юникод, уже-удвоенные."""
    from app.data.db_connectors import _odbc_quote  # отсутствует на родителе
    assert _odbc_quote("") == "{}"
    assert _odbc_quote("a'b") == "{a'b}"
    assert _odbc_quote("}") == "{}}}"  # '}' -> '}}', обёртка всегда
    assert _odbc_quote(";;") == "{;;}"
    assert _odbc_quote(PWD_MYSQL) == "{ледник;Федченко{2026}}}"  # удвоение только '}'
    # уже удвоенная '}' удваивается КАЖДАЯ скобка (idempotency НЕ заявлена)
    assert _odbc_quote("x}}y") == "{x}}}}y}"


# --- O10-O16: fallback pymssql (S2/RP2) -----------------------------------

def test_o10_pymssql_explicit_raw_password_no_odbc():
    """S2-fallback: mssql+pymssql — пароль СЫРОЙ (нативный API pymssql,
    БЕЗ ODBC-скобок), без PWD; login_timeout; ODBC-флагов в query нет;
    D4: и в pymssql-пути пароля в URL-объекте нет."""
    url, ca = _mssql(mssql_driver="pymssql")
    assert url.drivername == "mssql+pymssql"
    assert ca["password"] == PWD_MSSQL          # сырое значение, без '{...}'
    assert "PWD" not in ca
    assert ca["login_timeout"] == 10
    assert url.password is None
    assert PWD_MSSQL not in url.render_as_string(hide_password=False)
    assert "driver" not in url.query and "Encrypt" not in url.query


def test_o11_pyodbc_explicit():
    url, ca = _mssql(mssql_driver="pyodbc")
    assert url.drivername == "mssql+pyodbc"
    assert ca["PWD"] == "{p@ss;w0rd}}}}Памир}"
    assert ca["timeout"] == 10


def test_o12_unknown_explicit_driver_valueerror():
    with pytest.raises(ValueError, match="mssql_driver"):
        _mssql(mssql_driver="adonet")


def test_o13_env_switch_case_whitespace_normalized():
    """env UPLOAD_DB_MSSQL_DRIVER нормализуется (регистр/пробелы) —
    переключатель деплоя устойчив к формату значения."""
    import os
    with patch.dict(os.environ, {"UPLOAD_DB_MSSQL_DRIVER": " PYMSSQL "}):
        url, ca = _mssql()
    assert url.drivername == "mssql+pymssql"
    assert ca["password"] == PWD_MSSQL and "PWD" not in ca


def test_o14_env_invalid_value_loud_valueerror():
    import os
    with patch.dict(os.environ, {"UPLOAD_DB_MSSQL_DRIVER": "jtds"}):
        with pytest.raises(ValueError, match="UPLOAD_DB_MSSQL_DRIVER"):
            _mssql()


def test_o15_auto_resolution_matrix(monkeypatch):
    """Авто-резолюция: оба -> pyodbc (S2 основной); только pymssql -> fallback;
    оба отсутствуют -> детерминированный дефолт pyodbc (D2-подсказка)."""
    monkeypatch.setattr(dc, "pyodbc", object())
    monkeypatch.setattr(dc, "pymssql", object())
    assert _mssql()[0].drivername == "mssql+pyodbc"
    monkeypatch.setattr(dc, "pyodbc", None)
    assert _mssql()[0].drivername == "mssql+pymssql"
    monkeypatch.setattr(dc, "pymssql", None)
    assert _mssql()[0].drivername == "mssql+pyodbc"


def test_o16_mssql_driver_rejected_for_mysql():
    """Защита от тихого misuse: mssql_driver только для mssql."""
    with pytest.raises(ValueError, match="только для mssql"):
        _mysql(mssql_driver="pymssql")


# --- O17-O18: реестр — probes, пины, fallback -----------------------------

def test_o17_version_probe_matrix():
    """version_probe (вендор-детекция UPLOAD-DB-8): MySQL/MariaDB —
    SELECT VERSION(), MSSQL — SELECT @@VERSION; pg/ch не тронуты."""
    assert get_connector("mysql").version_probe.text == "SELECT VERSION()"
    assert get_connector("mssql").version_probe.text == "SELECT @@VERSION"
    assert get_connector("postgresql").version_probe.text == "SELECT version()"
    assert get_connector("clickhouse").version_probe.text == "SELECT version()"
    for cid in ("mysql", "mssql"):
        probe = get_connector(cid).version_probe
        assert probe is not None and hasattr(probe, "type")


def test_o18_registry_pip_hints_and_fallback():
    """D2-подсказки: mysql — 'PyMySQL cryptography' (extra не существует,
    cryptography пиннен отдельно); mssql — pyodbc + fallback pymssql;
    прочим fallback не объявлен."""
    assert get_connector("mysql").pip_package == "PyMySQL cryptography"
    mssql = get_connector("mssql")
    assert mssql.pip_package == "pyodbc"
    assert mssql.fallback_pip_package == "pymssql"
    for cid in ("postgresql", "clickhouse", "mysql", "duckdb", "sqlite"):
        assert get_connector(cid).fallback_pip_package is None, cid


# --- O19-O20: D2-подсказка ModuleNotFoundError (эксперимент E4-correct) ---

class _ModuleBlocker:
    """meta_path-блокировщик: модуль «отсутствует» (эксперимент E4-correct —
    create_engine инициализирует dbapi и даёт СЫРОЙ ModuleNotFoundError)."""

    def __init__(self, name: str):
        self._name = name

    def find_spec(self, name, path=None, target=None):
        if name == self._name:
            raise ModuleNotFoundError(f"No module named '{self._name}'")
        return None


def test_o19_mssql_missing_pyodbc_friendly_d2_with_fallback():
    """D2+S2: ImportError дружелюбен — label, основной драйвер, fallback,
    env-переключатель; сырой ModuleNotFoundError не доходит до пользователя."""
    spec = get_connector("mssql")
    url, ca = _mssql()
    with patch.dict(sys.modules, {"pyodbc": None}), \
            patch("sys.meta_path", [_ModuleBlocker("pyodbc"), *sys.meta_path]):
        with pytest.raises(ImportError) as ei:
            open_server_engine(spec, url, ca)
    msg = str(ei.value)
    assert "MS SQL Server" in msg          # label реестра
    assert "pyodbc" in msg                 # основной (pip_package)
    assert "pymssql" in msg                # fallback (S2)
    assert "UPLOAD_DB_MSSQL_DRIVER=pymssql" in msg  # переключатель деплоя


def test_o20_mysql_missing_pymysql_friendly_d2():
    spec = get_connector("mysql")
    url, ca = _mysql()
    with patch.dict(sys.modules, {"pymysql": None}), \
            patch("sys.meta_path", [_ModuleBlocker("pymysql"), *sys.meta_path]):
        with pytest.raises(ImportError) as ei:
            open_server_engine(spec, url, ca)
    msg = str(ei.value)
    assert "MySQL / MariaDB" in msg
    assert "PyMySQL" in msg
    assert "cryptography" in msg           # подсказка перечисляет оба пакета
    assert "fallback" not in msg           # у mysql fallback не объявлен


# --- O21-O22: handshake — что реально получает драйвер (эксперимент E2) ---

def _fake_dbapi(name: str, connect_capture: dict, connect_fn):
    """Честная DBAPI-поверхность (классUPLOAD-DB-7: SQLAlchemy обращается
    к исключениям/константам dbapi в путях инициализации и ошибок)."""

    class Fake:
        pass

    for attr in (
        "Warning", "Error", "InterfaceError", "DatabaseError", "DataError",
        "OperationalError", "IntegrityError", "InternalError",
        "ProgrammingError", "NotSupportedError",
        "Connection", "Cursor", "Row", "Binary", "Date", "Time", "Timestamp",
        "DATETIME", "STRING", "NUMBER", "BINARY",
    ):
        setattr(Fake, attr, type(attr, (Exception,), {}))
    Fake.version = "5.2.0"
    Fake.__version__ = "5.2.0"  # pymssql-диалект SQLAlchemy читает __version__
    Fake.apilevel = "2.0"
    Fake.threadsafety = 1
    Fake.paramstyle = "qmark" if name == "pyodbc" else "format"
    Fake.connect = staticmethod(connect_fn)
    return types.SimpleNamespace(**vars(Fake))


def test_o21_pyodbc_handshake_pamir_password_kwarg():
    """E2-паритет на СВОИХ данных: pyodbc.connect получает строку соединения
    БЕЗ PWD и сырья пароля, PWD — отдельным kwarg-ом (экранирован),
    timeout — kwarg-ом (login-таймаут)."""
    captured = {}

    def _capture(*a, **kw):
        captured.update(args=a, kwargs=kw)
        raise RuntimeError("captured — соединение не открываем")

    spec = get_connector("mssql")
    url, ca = _mssql()
    fake = _fake_dbapi("pyodbc", captured, _capture)
    with patch.dict(sys.modules, {"pyodbc": fake}):
        engine = open_server_engine(spec, url, ca)
        with pytest.raises(Exception, match="captured"):
            engine.connect()
    conn_str = captured["args"][0]
    assert "PWD" not in conn_str
    assert PWD_MSSQL not in conn_str            # сырья нет и в ODBC-строке
    assert f"UID={USER}" in conn_str            # username пришёл из URL
    assert "DRIVER={ODBC Driver 18 for SQL Server}" in conn_str
    assert "Encrypt=no" in conn_str
    assert captured["kwargs"]["PWD"] == "{p@ss;w0rd}}}}Памир}"
    assert captured["kwargs"]["timeout"] == 10


def test_o22_pymssql_handshake_raw_password_kwarg():
    """Fallback-диалект mssql+pymssql: pymssql.connect получает пароль
    kwarg-ом СЫРЫМ (нативный API — без ODBC-скобок), login_timeout — kwarg-ом."""
    captured = {}

    def _capture(*a, **kw):
        captured.update(args=a, kwargs=kw)
        raise RuntimeError("captured — соединение не открываем")

    spec = get_connector("mssql")
    url, ca = _mssql(mssql_driver="pymssql")
    fake = _fake_dbapi("pymssql", captured, _capture)
    with patch.dict(sys.modules, {"pymssql": fake}):
        engine = open_server_engine(spec, url, ca)
        with pytest.raises(Exception, match="captured"):
            engine.connect()
    assert captured["kwargs"]["password"] == PWD_MSSQL  # сырое, без '{...}'
    assert captured["kwargs"]["login_timeout"] == 10
    sent = str(captured["args"]) + str(captured["kwargs"])
    assert PWD_MSSQL in sent  # пароль дошёл до connect (kwarg)


# --- O23: импорт-безопасность без pyodbc/pymysql --------------------------

def test_o23_import_safety_without_drivers():
    """Реестр читается в процессе БЕЗ pyodbc/pymysql; авто-резолюция даёт
    детерминированный дефолт; build_server_url работает (диалект — строка)."""
    code = (
        "import sys\n"
        "sys.modules['pyodbc'] = None\n"
        "sys.modules['pymssql'] = None\n"
        "import app.data.db_connectors as dc\n"
        "assert dc.pyodbc is None and dc.pymssql is None\n"
        "spec = dc.get_connector('mssql')\n"
        "assert spec.fallback_pip_package == 'pymssql'\n"
        "url, ca = dc.build_server_url(spec, host='meteo.pamir.gla', port=None,"
        " database='pamir_observations', username='hydrolog_pamir',"
        " password='snyeg2026')\n"
        "assert url.drivername == 'mssql+pyodbc'  # авто-дефолт детерминирован\n"
        "assert ca['PWD'] == '{snyeg2026}'\n"
        "assert dc.get_connector('mysql').pip_package == 'PyMySQL cryptography'\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True,
        text=True, timeout=120,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "OK" in result.stdout


# --- O24-O25: сквозное делегирование + D4-матрица -------------------------

def test_o24_init_db_connection_e2e_connect_args_reach_engine(monkeypatch):
    """Сквозной пин: file_loader.init_db_connection (слой DB-1) НЕ
    теряет connect_args DB-7 — PWD/timeout доходят до create_engine,
    URL без пароля; ошибка транспорта обёрнута в ConnectionError
    с маскированием (D4)."""
    from app.data import file_loader

    captured = {}

    class _Sentinel(Exception):
        pass

    def _capture_engine(url, connect_args=None, **kw):
        captured.update(url=url, connect_args=dict(connect_args or {}))
        raise _Sentinel(PWD_MSSQL + " — транспорт недоступен (сентинел)")

    monkeypatch.setattr(dc, "create_engine", _capture_engine)
    with pytest.raises(ConnectionError) as ei:
        file_loader.init_db_connection(
            db_type="mssql", host=HOST, port=1433, user=USER,
            password=PWD_MSSQL, db_name=DB, ssl=False,
        )
    assert captured["connect_args"]["PWD"] == "{p@ss;w0rd}}}}Памир}"
    assert captured["connect_args"]["timeout"] == 10
    assert captured["url"].password is None
    masked = str(ei.value)
    assert PWD_MSSQL not in masked          # D4: сырья пароля в ошибке нет
    assert "****" in masked                 # mask_secrets заменил секрет


def test_o25_d4_matrix_all_server_paths():
    """D4-паритет ВСЕХ серверных путей (замысел пересмотра DB-7):
    ни для одной серверной СУБД пароль не попадает в URL-объект."""
    cases = [
        ("postgresql", dict(password=PWD_PLAIN), {}),
        ("mysql", dict(password=PWD_MYSQL), {}),
        ("mssql", dict(password=PWD_MSSQL), {}),                       # pyodbc (дефолт)
        ("mssql", dict(password=PWD_MSSQL), dict(mssql_driver="pymssql")),
    ]
    for cid, kw, extra in cases:
        url, _ = build_server_url(get_connector(cid), host=HOST, port=None,
                                  database=DB, username=USER, **kw, **extra)
        assert url.password is None, (cid, extra)
        raw = kw["password"]
        assert raw not in url.render_as_string(hide_password=False), (cid, extra)


# --- O26-O27: статические пины поставки (requirements, Dockerfile) --------

def _code_lines(path: Path) -> list[str]:
    return [
        ln.strip() for ln in path.read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


def test_o26_requirements_pins_phase_c():
    """Пины фазы C в ОБОИХ requirements: PyMySQL, cryptography, pyodbc;
    fallback pymssql СОЗНАТЕЛЬНО не пиннен (RP2)."""
    for rel in ("requirements.txt", "apps/api/requirements.txt"):
        lines = _code_lines(ROOT / rel)
        assert any(ln.startswith("PyMySQL>=") for ln in lines), rel
        assert any(ln.startswith("cryptography>=") for ln in lines), rel
        assert any(ln.startswith("pyodbc>=") for ln in lines), rel
        assert not any(ln.startswith("pymssql") for ln in lines), (
            f"{rel}: fallback pymssql не должен быть пиннен"
        )


def test_o27_dockerfile_odbc_layer_and_build_guard():
    """apps/api/Dockerfile: условный слой unixodbc+msodbcsql18 (RP2) с
    гвардом регистрации odbcinst; build-гвард pip-цепочки; unixodbc
    обязателен в обоих режимах (без libodbc.so.2 не импортируется pyodbc)."""
    dockerfile = (ROOT / "apps/api/Dockerfile").read_text()
    assert "ARG INSTALL_MSODBCSQL18=" in dockerfile          # условный слой
    assert "msodbcsql18" in dockerfile
    assert "unixodbc" in dockerfile
    assert 'odbcinst -q -d -n "ODBC Driver 18 for SQL Server"' in dockerfile
    assert "packages.microsoft.com" in dockerfile            # apt-репозиторий MS
    assert "import pyodbc, pymysql, cryptography" in dockerfile  # build-гвард
