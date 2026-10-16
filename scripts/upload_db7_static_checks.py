"""Проверки UPLOAD-DB-7 без docker-демона:
1) bash -n синтаксис RUN-блока ODBC-слоя (обе ветки build-arg);
2) py_compile всех изменённых python-файлов;
3) pyodbc импортируемость (manylinux-wheel + libodbc.so.2).
"""
import py_compile
import re
import subprocess
import sys

DOCKERFILE = "/home/z/my-project/CISStat-TS-Analysis/apps/api/Dockerfile"

# --- 1. RUN-блок ODBC слоя ---
text = open(DOCKERFILE, encoding="utf-8").read()
m = re.search(r"ARG INSTALL_MSODBCSQL18=true\nRUN (.+?)\n\n", text, re.S)
assert m, "RUN-блок ODBC не найден"
raw = m.group(1)
# docker RUN: обратный слэш в конце строки СКЛЕИВАЕТ строки (перевод строки
# исчезает) — иначе && в начале строки даёт синтаксическую ошибку
script = raw.replace("\\\n", " ")
# санитизация команд (нет сети/root в песочнице) — ТОЛЬКО структура if/else/fi:
sanitized = (
    "set -e\n"
    + script
    .replace("apt-get update", "true")
    .replace("rm -rf /var/lib/apt/lists/*", "true")
)
# apt install / curl / gpg / odbcinst заменены на true точечно ниже
for pat, repl in [
    (r"apt-get install -y --no-install-recommends [a-z0-9 \-]+", "true"),
    (r"curl -fsSL \S+ \\\n\s*\| gpg --dearmor -o \S+", "true"),
    (r"curl -fsSL \S+ \\\n\s*-o \S+", "true"),
    (r"odbcinst -q -d -n \"ODBC Driver 18 for SQL Server\"", "true"),
]:
    sanitized = re.sub(pat, repl, sanitized)
result = subprocess.run(["bash", "-n", "-c", sanitized], capture_output=True, text=True)
print("1) bash -n:", "OK" if result.returncode == 0 else f"FAIL: {result.stderr}")
assert result.returncode == 0

# --- 2. py_compile ---
for path in (
    "/home/z/my-project/CISStat-TS-Analysis/app/data/db_connectors.py",
    "/home/z/my-project/CISStat-TS-Analysis/tests/unit/test_db_connectors.py",
    "/home/z/my-project/CISStat-TS-Analysis/tests/unit/test_db_guard.py",
):
    py_compile.compile(path, doraise=True)
    print(f"2) py_compile {path.rsplit('/', 1)[-1]}: OK")

# --- 3. pyodbc импортируемость в песочнице ---
import pyodbc
print(f"3) pyodbc import: OK ({pyodbc.version})")
import pymysql
print(f"4) pymysql import: OK ({pymysql.__version__})")
import cryptography
print(f"5) cryptography: OK ({cryptography.__version__})")
