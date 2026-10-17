# scripts/db7cert_mutations.py
"""
Независимая сертификация UPLOAD-DB-7 — мутационный прогон на СВОИХ
мутантах (app/data/db_connectors.py — единственная точка изменения DB-7).
Двухканальная схема:
  (repo)   repo-сюиты DB-трека: tests/unit/test_db_connectors.py,
           test_db_guard.py, test_db_connection.py, test_db_embedded.py,
           tests/api/test_upload_db.py, tests/api/test_docker_image_layout.py;
  (oracle) свой корпус оракулов scripts/db7cert_oracles.py.
MB-00 — no-op-контроль достоверности харнесса (обязан пережить ОБА
канала). Восстановление файлов побайтовое, md5-паспорт каждого файла,
финальный контроль git diff пуст.

Запуск: DATABASE_URL="" python scripts/db7cert_mutations.py
Протокол: scripts/db7cert_mutations.txt
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "app/data/db_connectors.py"
PYTHON = sys.executable

REPO_SUITE = [
    "tests/unit/test_db_connectors.py",
    "tests/unit/test_db_guard.py",
    "tests/unit/test_db_connection.py",
    "tests/unit/test_db_embedded.py",
    "tests/api/test_upload_db.py",
    "tests/api/test_docker_image_layout.py",
]

# (id, файл, старая строка, новая строка, ожидаемое число вхождений)
MUTANTS: list[tuple[str, Path, str, str, int]] = [
    (
        "MB-00 no-op-контроль (харнесс достоверен, если переживает оба канала)",
        TARGET,
        "logger = logging.getLogger(__name__)",
        "logger = logging.getLogger(__name__)  # db7cert no-op",
        1,
    ),
    (
        "MB-01 _odbc_quote: снята обёртка в фигурные скобки",
        TARGET,
        '    return "{" + str(value).replace("}", "}}") + "}"',
        '    return str(value).replace("}", "}}")',
        1,
    ),
    (
        "MB-02 _odbc_quote: снято удвоение '}' (PWD с '}' ломает строку ODBC)",
        TARGET,
        '    return "{" + str(value).replace("}", "}}") + "}"',
        '    return "{" + str(value) + "}"',
        1,
    ),
    (
        "MB-03 mssql/pyodbc: пароль ВЕРНУТ в URL-объект (регрессия пересмотра D4, E1)",
        TARGET,
        "        url = URL.create(\n"
        "            dialect,\n"
        "            username=username,\n"
        "            host=host,\n",
        "        url = URL.create(\n"
        "            dialect,\n"
        "            username=username,\n"
        "            password=password,\n"
        "            host=host,\n",
        1,
    ),
    (
        "MB-04 mssql/pyodbc: PWD без ODBC-экранирования (сырой пароль)",
        TARGET,
        '            "PWD": _odbc_quote(password),',
        '            "PWD": password,',
        1,
    ),
    (
        "MB-05 mssql/pyodbc: PWD удалён из connect_args (аутентификация потеряна)",
        TARGET,
        "        connect_args = {\n"
        '            "PWD": _odbc_quote(password),\n'
        '            "timeout": connect_timeout,  # pyodbc: login-таймаут (перехватывается)\n'
        "        }",
        "        connect_args = {}",
        1,
    ),
    (
        "MB-06 mssql/pyodbc: login-таймаут снят (S4)",
        TARGET,
        '            "timeout": connect_timeout,  # pyodbc: login-таймаут (перехватывается)',
        "            # timeout снят мутантом",
        1,
    ),
    (
        "MB-07 mssql: Encrypt инвертирован (D3: TLS выключается при ssl=True)",
        TARGET,
        '            "Encrypt": "yes" if ssl else "no",',
        '            "Encrypt": "no" if ssl else "yes",',
        1,
    ),
    (
        "MB-08 mssql: TrustServerCertificate=no снят (ssl=True понижает проверку)",
        TARGET,
        '        if ssl:\n            query["TrustServerCertificate"] = "no"',
        '        if False:\n            query["TrustServerCertificate"] = "no"',
        1,
    ),
    (
        "MB-09 mysql: default_port 3306 -> 3307",
        TARGET,
        "        default_port=3306,",
        "        default_port=3307,",
        1,
    ),
    (
        "MB-10 mysql: ssl-ветки инвертированы (D3: ssl=True отключает TLS)",
        TARGET,
        "        if ssl:  # D3: TLS с проверкой сертификата сервера\n"
        '            connect_args["ssl_verify_cert"] = True\n'
        "        else:\n"
        '            connect_args["ssl_disabled"] = True',
        "        if ssl:  # D3: TLS с проверкой сертификата сервера\n"
        '            connect_args["ssl_disabled"] = True\n'
        "        else:\n"
        '            connect_args["ssl_verify_cert"] = True',
        1,
    ),
    (
        "MB-11 mysql: connect_timeout снят (S4-паритет)",
        TARGET,
        '    elif spec.dialect == "mysql+pymysql":\n'
        '        connect_args["connect_timeout"] = connect_timeout',
        '    elif spec.dialect == "mysql+pymysql":\n'
        "        pass  # мутант: connect_timeout снят",
        1,
    ),
    (
        "MB-12 env UPLOAD_DB_MSSQL_DRIVER: неверное значение тихо игнорируется",
        TARGET,
        "            raise ValueError(\n"
        '                f"Неверное UPLOAD_DB_MSSQL_DRIVER={env_value!r}: ожидается "\n'
        '                f"{\' или \'.join(_MSSQL_DRIVERS)}"\n'
        "            )\n"
        "        return _MSSQL_DIALECTS[env_value]",
        "            pass  # мутант: тихое игнорирование\n"
        '        return _MSSQL_DIALECTS.get(env_value, _MSSQL_DIALECTS["pyodbc"])',
        1,
    ),
    (
        "MB-13 авто-резолюция: pyodbc-ветка возвращает fallback-диалект",
        TARGET,
        '    if pyodbc is not None:  # S2: основной драйвер\n'
        '        return _MSSQL_DIALECTS["pyodbc"]',
        '    if pyodbc is not None:  # S2: основной драйвер\n'
        '        return _MSSQL_DIALECTS["pymssql"]',
        1,
    ),
    (
        "MB-14 D2-подсказка: fallback-драйвер не упомянут (S2)",
        TARGET,
        "        if spec.fallback_pip_package:",
        "        if False:  # мутант: fallback-подсказка снята",
        1,
    ),
    (
        "MB-15 D2: обработчик ModuleNotFoundError снят (сырая ошибка dbapi-слоя)",
        TARGET,
        '        raise ImportError(\n'
        '            f"Не установлен драйвер {spec.label} ({exc.name}). {hint}"\n'
        "        ) from exc",
        "        raise exc",
        1,
    ),
    (
        "MB-16 реестр: version_probe mysql снят (вендор-детекция UPLOAD-DB-8)",
        TARGET,
        '        version_probe=_test_clause("SELECT VERSION()"),  # MySQL и MariaDB',
        "        version_probe=None,  # мутант",
        1,
    ),
    (
        "MB-17 реестр: version_probe mssql испорчен (SELECT 1 вместо @@VERSION)",
        TARGET,
        '        version_probe=_test_clause("SELECT @@VERSION"),  # UPLOAD-DB-7',
        '        version_probe=_test_clause("SELECT 1"),  # мутант',
        1,
    ),
    (
        "MB-18 реестр: D2-подсказка mysql без cryptography (MySQL 8)",
        TARGET,
        '        pip_package="PyMySQL cryptography",',
        '        pip_package="PyMySQL",',
        1,
    ),
    (
        "MB-19 реестр: fallback_pip_package mssql снят (S2)",
        TARGET,
        '        fallback_pip_package="pymssql",  # S2: чистый pip-fallback (RP2)',
        "        fallback_pip_package=None,  # мутант",
        1,
    ),
    (
        "MB-20 misuse-гвард снят: mssql_driver принят для не-mssql",
        TARGET,
        "    if mssql_driver is not None:\n"
        '        raise ValueError(\n'
        '            "Параметр mssql_driver применим только для mssql "\n'
        '            f"(передан для {spec.label})"\n'
        "        )",
        "    if False:  # мутант: misuse-гвард снят\n"
        '        raise ValueError(\n'
        '            "Параметр mssql_driver применим только для mssql "\n'
        '            f"(передан для {spec.label})"\n'
        "        )",
        1,
    ),
    (
        "MB-21 явная валидация mssql_driver снята (неизвестный драйвер без ValueError)",
        TARGET,
        "    if explicit is not None:\n"
        "        if explicit not in _MSSQL_DRIVERS:",
        "    if explicit is not None:\n"
        "        if False and explicit not in _MSSQL_DRIVERS:",
        1,
    ),
]


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def run(cmd: list[str], timeout: int = 900) -> tuple[int, str]:
    proc = subprocess.run(
        cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "DATABASE_URL": "", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return proc.returncode, proc.stdout + proc.stderr


def _summary(out: str) -> str:
    for line in out.splitlines():
        if " passed" in line or " failed" in line or "error" in line.lower():
            return line.strip()[:110]
    return (out.strip().splitlines() or ["нет вывода"])[-1][:110]


def main() -> int:
    passport = TARGET.read_bytes()
    lines: list[str] = [
        "db7cert мутационный прогон UPLOAD-DB-7 (свои мутанты, двухканальная схема repo+oracle)",
        f"объект: {TARGET.relative_to(ROOT)}",
        f"md5 до прогона: {md5(TARGET)}",
        "",
    ]
    survivors = 0
    noop_ok = None
    for mid, path, old, new, expected in MUTANTS:
        text = path.read_text()
        count = text.count(old)
        if count != expected:
            lines.append(f"{mid}: ОШИБКА ХАРНЕССА — вхождений {count}, ожидалось {expected}")
            print(lines[-1])
            return 2
        mutated = text.replace(old, new)
        path.write_text(mutated)
        try:
            rc_repo, out_repo = run(
                [PYTHON, "-m", "pytest", *REPO_SUITE, "-q", "--tb=no",
                 "-p", "no:cacheprovider"]
            )
            rc_oracle, out_oracle = run(
                [PYTHON, "-m", "pytest", "scripts/db7cert_oracles.py", "-q",
                 "--tb=line", "-p", "no:cacheprovider"]
            )
        finally:
            path.write_bytes(passport)  # побайтовое восстановление
        repo_state = "SURVIVED" if rc_repo == 0 else "KILLED"
        oracle_state = "SURVIVED" if rc_oracle == 0 else "KILLED"
        dual = repo_state == "SURVIVED" and oracle_state == "SURVIVED"
        if dual:
            survivors += 1
        if mid.startswith("MB-00"):
            noop_ok = dual
        verdict = "DUAL-SURVIVOR" if dual else "ok"
        repo_tail = [l for l in out_repo.splitlines() if l.startswith(("FAILED", "ERROR"))][:2]
        oracle_tail = [l for l in out_oracle.splitlines() if l.startswith(("FAILED", "ERROR"))][:3]
        detail = (
            f"{mid}\n"
            f"    repo: {repo_state} ({_summary(out_repo)})\n"
            f"    oracle: {oracle_state} ({_summary(out_oracle)})\n"
            + (f"    repo-убийцы: {repo_tail}\n" if repo_tail and not dual else "")
            + (f"    oracle-убийцы: {oracle_tail}\n" if oracle_tail and not dual else "")
            + f"    вердикт: {verdict}"
        )
        lines.append(detail)
        print(f"{mid.split(' (')[0]} -> repo {repo_state} / oracle {oracle_state}")
    md5_after = md5(TARGET)
    restored = md5_after == hashlib.md5(passport).hexdigest()
    diff_empty = subprocess.run(["git", "diff", "--quiet"], cwd=ROOT).returncode == 0
    lines += [
        "",
        f"md5 после прогона: {md5_after} — СХОДИТСЯ = {restored}",
        f"git diff пуст (дерево чистое): {diff_empty}",
        f"no-op-контроль MB-00 пережил оба канала: {noop_ok}",
        f"DUAL-SURVIVORS (без MB-00): {survivors - (1 if noop_ok else 0)}",
    ]
    (ROOT / "scripts/db7cert_mutations.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[-4:]))
    return 0 if restored and diff_empty and noop_ok else 3


if __name__ == "__main__":
    sys.exit(main())
