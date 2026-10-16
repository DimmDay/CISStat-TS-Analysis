"""RED-протокол UPLOAD-DB-7: точные факты несоответствия текущего кода
Фазы A целевому контракту (до GREEN-реализации). Запуск: python3 scripts/...py
"""
import sys

sys.path.insert(0, "/home/z/my-project/CISStat-TS-Analysis")

import app.data.db_connectors as dc

facts = []


def fact(name, fn):
    try:
        value = fn()
        facts.append(f"FAIL | {name}: {value}")
    except Exception as e:
        facts.append(f"FAIL | {name}: {type(e).__name__}: {str(e)[:90]}")


# 1. MSSQL-пароль в URL-объекте (пересмотр не сделан)
def _f1():
    url, _ = dc.build_server_url(
        dc.get_connector("mssql"), host="h", port=1433, database="d",
        username="u", password="mssql-pw",
    )
    return f"url.password == {url.password!r} (цель: None)"


fact("mssql url.password", _f1)

# 2. version_probe отсутствует у mysql/mssql
fact(
    "mysql.version_probe",
    lambda: f"{dc.get_connector('mysql').version_probe} (цель: TextClause SELECT VERSION())",
)
fact(
    "mssql.version_probe",
    lambda: f"{dc.get_connector('mssql').version_probe} (цель: TextClause SELECT @@VERSION)",
)

# 3. pip_package mysql без cryptography; fallback_pip_package нет
fact(
    "mysql.pip_package",
    lambda: f"{dc.get_connector('mysql').pip_package!r} (цель: 'PyMySQL cryptography')",
)
fact(
    "mssql.fallback_pip_package",
    lambda: f"{getattr(dc.get_connector('mssql'), 'fallback_pip_package', '<нет атрибута>')}"
    " (цель: 'pymssql')",
)

# 4. _odbc_quote отсутствует
fact("_odbc_quote", lambda: dc._odbc_quote("p;a"))

# 5. mssql_driver параметр не принят
def _f5():
    dc.build_server_url(
        dc.get_connector("mssql"), host="h", port=1433, database="d",
        username="u", password="pw", mssql_driver="pymssql",
    )
    return "принят (цель: ValueError/TypeRED)"


fact("mssql_driver param", _f5)

# 6. PWD через connect_args отсутствует
def _f6():
    _, ca = dc.build_server_url(
        dc.get_connector("mssql"), host="h", port=1433, database="d",
        username="u", password="pw",
    )
    return f"connect_args keys={sorted(ca)} (цель: PWD='{{pw}}', timeout=10)"


fact("mssql connect_args", _f6)

# 7. ModuleNotFoundError без D2-хинта (эксперимент E4-correct)
def _f7():
    import importlib
    import sqlalchemy.dialects.mssql.pyodbc as mspy
    importlib.reload(mspy)

    class Blocker:
        def find_spec(self, name, path=None, target=None):
            if name == "pyodbc":
                raise ModuleNotFoundError("No module named 'pyodbc'")
            return None

    spec = dc.get_connector("mssql")
    url, ca = dc.build_server_url(
        spec, host="h", port=1433, database="d", username="u", password="pw"
    )
    sys.meta_path.insert(0, Blocker())
    import unittest.mock as _mock
    try:
        with _mock.patch.dict(sys.modules, {"pyodbc": None}):
            try:
                dc.open_server_engine(spec, url, ca)
                return "исключения нет"
            except ImportError as e:
                msg = str(e)
                if "pymssql" in msg and "pyodbc" in msg:
                    return "GREEN: хинт с fallback есть"
                return f"сырой ImportError без D2-хинта: {msg[:80]!r}"
    finally:
        sys.meta_path.pop(0)


fact("missing pyodbc D2-hint", _f7)

print("RED-протокол UPLOAD-DB-7 (до GREEN):")
for line in facts:
    print(" ", line)
