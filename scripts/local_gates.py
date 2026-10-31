#!/usr/bin/env python3
# scripts/local_gates.py
"""Локальный прогон CI-гейтов перед пушем (паритет .github/workflows).

Зачем: локальная верификация задачи обычно адресная (jest/pytest по
затронутым областям), а CI на каждый push гоняет ВСЕ workflows. Этот
скрипт запускает те же команды тем же порядком, что и CI, до пуша:

  auth02  (auth02.yml,   push/PR)   storage unit contracts (no DB required)
  auth02-postgres (auth02.yml)     live PG; --with-auth02-postgres + test DSN
  auth01  (auth01.yml,   push/PR)   dependencies + registry tests + generated parity
  auth00  (auth00.yml,   push/PR)   unittest auth00 + inventory --check
  rules   (test_rules.yml, push/PR) sanity-проверка валидационных правил
  jest    (jest.yml,     push/PR)   npm ci + test:ci + renderer build + typecheck:all
  pytest  (test.yml,     ТОЛЬКО develop/refactor/*) полный python -m pytest tests/

По умолчанию (пуш в main): auth02 + auth01 + auth00 + rules + jest. Для пуша в
develop/refactor добавьте --with-pytest. Гейты идут от быстрых к
тяжёлым; по умолчанию все выбранные выполняются, итог — сводка и
exit code. Использование в VS Code: интегрированный терминал (Ctrl+`),
`python scripts/local_gates.py`; повторные прогоны — с --skip-install.

Stdlib only; ничего не коммитит и не пушит (AGENTS.md)."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES_CHECK = (
    "from validation.engine import load_rules, validate_dataframe; "
    "import pandas as pd; "
    "df=pd.read_csv('tests/fixtures/sample_bad_data.csv'); "
    "res=validate_dataframe(df, load_rules()); "
    "print('is_valid =', res['is_valid']); assert not res['is_valid']"
)

# (имя, происхождение в CI, описание, команды)
GATES: list[tuple[str, str, str, list[list[str]]]] = [
    ("auth02", "auth02.yml contracts", "AUTH-02 storage unit contracts (no DB)", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth02/requirements.txt"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit",
         "-p", "test_auth02_storage.py", "-v"],
    ]),
    ("auth02-postgres", "auth02.yml postgres", "AUTH-02 LIVE PostgreSQL (CISSTAT_AUTH_TEST_DSN required)", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth02/requirements.txt"],
        [sys.executable, "scripts/auth02/verify_postgres.py"],
        [sys.executable, "scripts/auth02/mutation_rehearsal.py"],
    ]),
    ("auth01", "auth01.yml", "AUTH-01 registry / OpenAPI / generated TS parity", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth01/requirements.txt"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit",
         "-p", "test_auth01_registry.py", "-v"],
        [sys.executable, "scripts/auth01/windows_locale_check.py"],
        [sys.executable, "scripts/auth01/generate.py", "--check"],
    ]),
    ("auth00", "auth00.yml", "AUTH-00 inventory (unittest + drift check)", [
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit",
         "-p", "test_auth00_inventory.py", "-v"],
        [sys.executable, "scripts/auth00/inventory.py", "--check"],
    ]),
    ("rules", "test_rules.yml", "Validation rules sanity check", [
        [sys.executable, "-c", RULES_CHECK],
    ]),
    ("pytest", "test.yml (develop/refactor only)", "pip install + полный python -m pytest tests/", [
        [sys.executable, "-m", "pip", "install", "--upgrade", "pip"],
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt",
         "-r", "apps/api/requirements.txt", "-r", "requirements-dev.txt"],
        [sys.executable, "-m", "pytest", "tests/", "-v"],
    ]),
    ("jest", "jest.yml", "All Jest tests + renderer build + typecheck:all", [
        ["npm", "ci", "--include=dev", "--workspaces", "--include-workspace-root",
         "--ignore-scripts", "--no-audit", "--no-fund"],
        ["npm", "run", "test:ci"],
        ["npm", "run", "build", "--workspace=@cisstat/print-renderer"],
        ["npm", "run", "typecheck:all"],
    ]),
]


def _npm() -> str:
    found = shutil.which("npm")
    if not found:
        raise SystemExit("npm не найден в PATH — установите Node.js 22 (как в jest.yml)")
    return found


def run_gate(name: str, commands: list[list[str]], skip_install: bool) -> tuple[bool, float]:
    started = time.monotonic()
    for command in commands:
        is_install = command[:2] == ["npm", "ci"] or command[1:3] == ["-m", "pip"]
        if skip_install and is_install:
            print("    (установка зависимостей пропущена: --skip-install)")
            continue
        if command and command[0] == "npm":
            command = [_npm(), *command[1:]]
        print(f"    $ {' '.join(command)}", flush=True)
        result = subprocess.run(command, cwd=ROOT)
        if result.returncode != 0:
            return False, time.monotonic() - started
    return True, time.monotonic() - started


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Локальный прогон CI-гейтов перед пушем (паритет GitHub Actions)")
    parser.add_argument("--only", metavar="a,b,c",
                        help="запустить только выбранные гейты (auth02,auth02-postgres,auth01,auth00,rules,pytest,jest)")
    parser.add_argument("--skip-install", action="store_true",
                        help="пропустить npm ci / pip install (повторные локальные прогоны)")
    parser.add_argument("--with-pytest", action="store_true",
                        help="добавить полный pytest-гейт (нужен для push в develop/refactor/*)")
    parser.add_argument("--with-auth02-postgres", action="store_true",
                        help="добавить live PG проверки; нужен disposable CISSTAT_AUTH_TEST_DSN (в CI обязательны)")
    parser.add_argument("--fail-fast", action="store_true",
                        help="остановиться на первом упавшем гейте")
    parser.add_argument("--jest-workers", metavar="N", type=int, default=None,
                        help="переопределить maxWorkers для test:ci (машины с малой RAM: "
                             "по умолчанию CI держит 2 воркера и на 4 ГБ RAM воркера "
                             "может убить OOM-killer с SIGKILL; CI-раннеры 16 ГБ не страдают)")
    parser.add_argument("--list", action="store_true", help="показать гейты и выйти")
    args = parser.parse_args()

    excluded = set()
    if not args.with_pytest:
        excluded.add("pytest")
    if not args.with_auth02_postgres:
        excluded.add("auth02-postgres")
    order = [g for g in GATES if g[0] not in excluded]
    full = list(GATES)
    if args.only:
        selected = [g for g in full if g[0] in args.only.split(",")]
    else:
        selected = order
    if args.jest_workers:
        for gate in selected:
            if gate[0] == "jest":
                for i, cmd in enumerate(gate[3]):
                    if cmd[:3] == ["npm", "run", "test:ci"]:
                        gate[3][i] = [*cmd, "--", f"--maxWorkers={args.jest_workers}"]
    if args.list:
        for name, origin, description, commands in full:
            mark = "*" if name not in excluded else " "
            print(f" {mark} {name:7s} <- {origin:32s} {description}")
        print("\n* = входит в прогон по умолчанию (push в main); "
              "pytest добавляется --with-pytest; live PG — --with-auth02-postgres")
        return 0
    if not selected:
        parser.error("ничего не выбрано; доступно: auth02,auth02-postgres,auth01,auth00,rules,pytest,jest")

    rev = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout.strip()
    names = ", ".join(g[0] for g in selected)
    print(f"Локальные гейты (база {rev}): {names}", flush=True)
    results: list[tuple[str, bool, float]] = []
    failed = False
    for name, origin, description, commands in selected:
        print(f"\n=== ГЕЙТ {name} ({origin}) — {description}", flush=True)
        ok, seconds = run_gate(name, commands, args.skip_install)
        results.append((name, ok, seconds))
        print(f"--- {name}: {'PASS' if ok else 'FAIL'} ({seconds:.1f} c)", flush=True)
        if not ok and args.fail_fast:
            break
    print("\n=== СВОДКА ===")
    for name, ok, seconds in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name:7s} {seconds:7.1f} c")
    failed = any(not ok for _, ok, _ in results)
    names_run = {name for name, _, _ in results}
    if not failed and "auth02" in names_run and "auth02-postgres" not in names_run:
        print("\nИТОГ: выбранные гейты зелёные; AUTH-02 live PostgreSQL не проверен "
              "(нужен --with-auth02-postgres и отдельная проверка restart/CI)")
    else:
        print("\nИТОГ: " + ("ПУШ РАЗРЕШЁН — все гейты зелёные" if not failed
                            else "НЕ ПУШТЕ — есть красные гейты"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
