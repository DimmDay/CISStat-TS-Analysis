#!/usr/bin/env python3
# scripts/local_gates.py
"""Локальный прогон CI-гейтов перед пушем (паритет .github/workflows).

Зачем: локальная верификация задачи обычно адресная (jest/pytest по
затронутым областям), а CI на каждый push гоняет ВСЕ workflows. Этот
скрипт запускает те же команды тем же порядком, что и CI, до пуша:

  auth06  (auth06.yml)            proxy / CSRF / login contracts
  auth06-postgres (auth06.yml)     live PG + two-origin HTTPS
  auth05  (auth05.yml)            MFA/bootstrap/recovery contracts
  auth05-postgres (auth05.yml)     native PG MFA lifecycle / replay / HTTP
  auth04  (auth04.yml,   push/PR)   password/CSRF/route contracts
  auth04-postgres (auth04.yml)     native PG session/HTTP/fault contracts
  auth03  (auth03.yml,   push/PR)   unified context/ASGI compatibility contracts
  auth03-postgres (auth03.yml)     live PG context/currentness; test DSN required
  auth02  (auth02.yml,   push/PR)   storage unit contracts (no DB required)
  auth02-postgres (auth02.yml)     live PG; --with-auth02-postgres + test DSN
  auth01  (auth01.yml,   push/PR)   dependencies + registry tests + generated parity
  auth00  (auth00.yml,   push/PR)   unittest auth00 + inventory --check
                                     + INDEX reviewed parity после git add;
                                     --auth00-target head перед push;
                                     ловит пропущенные файлы/изменения
                                     (класс инцидента AUTH-07-HOTFIX1: файл
                                     на диске, но скрыт .gitignore из коммита)
  auth07  (auth07.yml,   push/PR)   named-session admin / MFA / logs contracts
                                     + windows-паритет (windows_parity.py):
                                     тот же pytest с блокировкой Unix-only
                                     stdlib (resource и др.) -- ловит класс
                                     инцидента AUTH-07-HOTFIX2 «локально
                                     зелено, на windows-2025
                                     ModuleNotFoundError на collection»
  auth23  (auth23.yml, push/PR)    Refund/dispute/chargeback contracts
  auth23-postgres (auth23.yml)    native PG refund saga / exposure flows
  auth22  (auth22.yml, push/PR)    Top-up quote/checkout/credit contracts
  auth22-postgres (auth22.yml)    native PG top-up duplicates/spoof/tamper flows
  auth13  (auth13.yml contracts)  Bounded worker / stop proof / fencing contracts
  auth13-postgres (auth13.yml)   Native worker publication / races / adapters
  auth12  (auth12.yml, push/PR)    Atomic ledger/reservation contracts
  auth12-postgres (auth12.yml)    native PG CU/API/analysis races and rollback
  auth11  (auth11.yml, push/PR)    Scientific current Account / object / execution guards
  auth11-postgres (auth11.yml)    native PG all routes / downgrade / baseline pipeline
  auth10  (auth10.yml, push/PR)    Durable API keys / scopes / operator
  auth10-postgres (auth10.yml)    native PG rotation / lifecycle / audit rollback
  auth09  (auth09.yml, push/PR)    Object ownership / legacy migration
  auth09-postgres (auth09.yml)    native PG ownership / restore / audit rollback
  auth08  (auth08.yml, push/PR)    Account entitlements / lifecycle / me contracts
  auth08-postgres (auth08.yml)    native PG CAS/expiry/revoke/audit fault proof
  rules   (test_rules.yml, push/PR) sanity-проверка валидационных правил
  session-postgres (test.yml + V2.3) live PG session backend: CAS/TTL/REST;
                                     нужен disposable CISSTAT_TEST_PG_DSN
  jest    (jest.yml,     push/PR)   npm ci + test:ci + renderer build + typecheck:all
  pytest  (test.yml,     ТОЛЬКО develop/refactor/*) полный python -m pytest tests/

По умолчанию (пуш в main): auth23 + auth22 + auth21 + auth20 + auth19 + auth18 + auth17 + auth16 + auth15 + auth14 + auth13 + auth12 + auth11 + auth10 + auth09 + auth08 + auth06 + auth07 + auth05 + auth04 + auth03 + auth02 + auth01 + auth00 + rules + jest. Для пуша в
develop/refactor добавьте --with-pytest. Гейты идут от быстрых к
тяжёлым; по умолчанию все выбранные выполняются, итог — сводка и
exit code. Использование в VS Code: интегрированный терминал (Ctrl+`),
`python scripts/local_gates.py`; повторные прогоны — с --skip-install.

Stdlib only; ничего не коммитит и не пушит (AGENTS.md)."""
from __future__ import annotations

import argparse
import os
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
    ("auth23", "auth23.yml contracts", "AUTH-23 refund/dispute contracts", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth23/requirements.txt"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit", "-p", "test_auth23*.py", "-v"],
    ]),
    ("auth23-postgres", "auth23.yml postgres", "AUTH-23 native refund saga/dispute/exposure flows", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth23/requirements.txt", "-r", "apps/api/requirements.txt"],
        [sys.executable, "scripts/auth23/verify_postgres.py"],
    ]),
    ("auth22", "auth22.yml contracts", "AUTH-22 top-up quote/checkout/credit contracts", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth22/requirements.txt"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit", "-p", "test_auth22*.py", "-v"],
    ]),
    ("auth22-postgres", "auth22.yml postgres", "AUTH-22 native top-up saga duplicates/spoof/tamper flows", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth22/requirements.txt", "-r", "apps/api/requirements.txt"],
        [sys.executable, "scripts/auth22/verify_postgres.py"],
    ]),
    ("auth21", "auth21.yml contracts", "AUTH-21 wallet/credit-lot contracts", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth21/requirements.txt"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit", "-p", "test_auth21*.py", "-v"],
    ]),
    ("auth21-postgres", "auth21.yml postgres", "AUTH-21 native wallet FEFO/expiry/refund flows", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth21/requirements.txt", "-r", "apps/api/requirements.txt"],
        [sys.executable, "scripts/auth21/verify_postgres.py"],
    ]),
    ("auth20", "auth20.yml contracts", "AUTH-20 audit/ops: lockdown, marks, catalog contracts", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth20/requirements.txt"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit", "-p", "test_auth20*.py", "-v"],
    ]),
    ("auth20-postgres", "auth20.yml postgres", "AUTH-20 native ledger/reconcile/quarantine/lockdown flows", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth20/requirements.txt", "-r", "apps/api/requirements.txt"],
        [sys.executable, "scripts/auth20/verify_postgres.py"],
    ]),
    ("auth19", "auth19.yml contracts", "AUTH-19 OIDC / personal email entry contracts", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth19/requirements.txt"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit", "-p", "test_auth19*.py", "-v"],
    ]),
    ("auth19-postgres", "auth19.yml postgres", "AUTH-19 native trial/OIDC/selection/audit flows", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth19/requirements.txt", "-r", "apps/api/requirements.txt"],
        [sys.executable, "scripts/auth19/verify_postgres.py"],
    ]),
    ("auth18", "auth18.yml contracts", "AUTH-18 provider / quote / proration contracts", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth18/requirements.txt"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit", "-p", "test_auth18*.py", "-v"],
    ]),
    ("auth18-postgres", "auth18.yml postgres", "AUTH-18 native payment / inbox / fencing / rollback", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth18/requirements.txt", "-r", "apps/api/requirements.txt"],
        [sys.executable, "scripts/auth18/verify_postgres.py"],
    ]),
    ("auth17", "auth17.yml contracts", "AUTH-17 invitations / seats / OWNER transfer contracts", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth17/requirements.txt"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit", "-p", "test_auth17*.py", "-v"],
    ]),
    ("auth17-postgres", "auth17.yml postgres", "AUTH-17 native invitations / capacity / OWNER / audit races", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth17/requirements.txt", "-r", "apps/api/requirements.txt"],
        [sys.executable, "scripts/auth17/verify_postgres.py"],
    ]),
    ("auth16", "auth16.yml contracts", "AUTH-16 admission / expiry / quotas / cleanup contracts", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth16/requirements.txt"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit", "-p", "test_auth16*.py", "-v"],
    ]),
    ("auth16-postgres", "auth16.yml postgres", "AUTH-16 native campaign / isolation / audit / races", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth16/requirements.txt", "-r", "apps/api/requirements.txt"],
        [sys.executable, "scripts/auth16/verify_postgres.py"],
    ]),
    ("auth15", "auth15.yml contracts", "AUTH-15 finite campaigns / isolated entry contracts", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth15/requirements.txt"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit", "-p", "test_auth15*.py", "-v"],
    ]),
    ("auth15-postgres", "auth15.yml postgres", "AUTH-15 native campaign / isolation / audit / races", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth15/requirements.txt", "-r", "apps/api/requirements.txt"],
        [sys.executable, "scripts/auth15/verify_postgres.py"],
    ]),
    ("auth14", "auth14.yml contracts", "AUTH-14 fixed-point CU / benchmark / process bounds", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth14/requirements.txt"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit", "-p", "test_auth14*.py", "-v"],
    ]),
    ("auth14-postgres", "auth14.yml postgres", "AUTH-14 native metered adapters / settle / capacity", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth14/requirements.txt", "-r", "apps/api/requirements.txt"],
        [sys.executable, "scripts/auth14/verify_postgres.py"],
    ]),
    ("auth13", "auth13.yml contracts", "AUTH-13 bounded process / stop proof / worker contracts", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth13/requirements.txt"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit", "-p", "test_auth13*.py", "-v"],
    ]),
    ("auth13-postgres", "auth13.yml postgres", "AUTH-13 native worker races / adapters / fencing", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth13/requirements.txt", "-r", "apps/api/requirements.txt"],
        [sys.executable, "scripts/auth13/verify_postgres.py"],
    ]),
    ("auth12", "auth12.yml contracts", "AUTH-12 atomic ledger/reservation contracts", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth12/requirements.txt"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit", "-p", "test_auth12*.py", "-v"],
    ]),
    ("auth12-postgres", "auth12.yml postgres", "AUTH-12 native PostgreSQL resource races / audit rollback", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth12/requirements.txt", "-r", "apps/api/requirements.txt"],
        [sys.executable, "scripts/auth12/verify_postgres.py"],
    ]),
    ("auth11", "auth11.yml contracts", "AUTH-11 scientific admission / workload / execution fence", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth11/requirements.txt"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit", "-p", "test_auth11*.py", "-v"],
    ]),
    ("auth11-postgres", "auth11.yml postgres", "AUTH-11 native PostgreSQL route matrix / baseline / downgrade", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth11/requirements.txt", "-r", "apps/api/requirements.txt"],
        [sys.executable, "scripts/auth11/verify_postgres.py"],
    ]),
    ("auth10", "auth10.yml contracts", "AUTH-10 durable API keys / scope / operator contracts", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth10/requirements.txt"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit", "-p", "test_auth10*.py", "-v"],
    ]),
    ("auth10-postgres", "auth10.yml postgres", "AUTH-10 native PostgreSQL rotation / revoke / audit fault", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth10/requirements.txt", "-r", "apps/api/requirements.txt"],
        [sys.executable, "scripts/auth10/verify_postgres.py"],
    ]),
    ("auth09", "auth09.yml contracts", "AUTH-09 Object ownership / operator / legacy migration", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth09/requirements.txt"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit", "-p", "test_auth09*.py", "-v"],
    ]),
    ("auth09-postgres", "auth09.yml postgres", "AUTH-09 native PostgreSQL ownership / restore / CAS / audit", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth09/requirements.txt"],
        [sys.executable, "-m", "pip", "install", "-r", "apps/api/requirements.txt"],
        [sys.executable, "scripts/auth09/verify_postgres.py"],
    ]),
    ("auth08", "auth08.yml contracts", "AUTH-08 Account-effective capabilities / lifecycle / me", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth08/requirements.txt"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit", "-p", "test_auth08*.py", "-v"],
    ]),
    ("auth08-postgres", "auth08.yml postgres", "AUTH-08 native PostgreSQL lifecycle / CAS / audit", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth08/requirements.txt"],
        [sys.executable, "scripts/auth08/verify_postgres.py"],
    ]),
    ("auth06", "auth06.yml contracts", "AUTH-06 proxy / CSRF / login UI", [
        [sys.executable,"-m","pip","install","-r","scripts/auth06/requirements.txt"],
        ["npm","ci","--ignore-scripts","--no-audit","--no-fund"],
        ["node","node_modules/jest/bin/jest.js","--ci","--runInBand","packages/ui/server/firstPartyProxy.test.ts","packages/ui/lib/browserTransport.test.ts","packages/ui/lib/authClient.test.ts","packages/ui/lib/auth06SourceBoundary.test.ts","packages/ui/components/LoginScreen.test.tsx","packages/ui/context/AuthContext.test.tsx"],
        [sys.executable,"-m","unittest","discover","-s","tests/unit","-p","test_auth06*.py","-v"],
        [sys.executable,"scripts/auth06/generate_proxy_routes.py","--check"],
    ]),
    ("auth06-postgres", "auth06.yml postgres", "AUTH-06 live PostgreSQL / two-origin HTTPS", [
        [sys.executable,"-m","pip","install","-r","scripts/auth06/requirements.txt"],
        ["npm","ci","--ignore-scripts","--no-audit","--no-fund"],
        [sys.executable,"scripts/auth06/verify_postgres.py"],
    ]),
    # AUTH-07 (2026-11-06): named-сессии админ-области вместо key-only.
    # Паритет auth07.yml (ubuntu + windows): pytest tests/api — контракт
    # require_admin_role (роль+MFA), программный канал API-ключей,
    # logs-роутер; Postgres не нужен (фейки через app.state).
    # Шаг 2 (AUTH-07-HOTFIX2): windows-паритет — этот же тест под
    # блокировкой Unix-only stdlib (import resource -> ImportError, как
    # на windows-2025). Без шага класс инцидента «локально зелено,
    # CI красно на Windows» (ModuleNotFoundError на collection) не
    # ловится до пуша.
    ("auth07", "auth07.yml contracts", "AUTH-07 admin named-session / MFA / logs + windows-паритет", [
        [sys.executable,"-m","pip","install","-r","apps/api/requirements.txt",
         "-r","requirements-dev.txt"],
        [sys.executable,"-m","pytest","tests/api/test_auth07_admin_sessions.py","-v"],
        [sys.executable,"scripts/windows_parity.py",
         "tests/api/test_auth07_admin_sessions.py","-v"],
    ]),
    ("auth05", "auth05.yml contracts", "AUTH-05 MFA / bootstrap / recovery contracts", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth05/requirements.txt"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit", "-p", "test_auth05*.py", "-v"],
    ]),
    ("auth05-postgres", "auth05.yml postgres", "AUTH-05 LIVE PostgreSQL MFA / HTTP / replay", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth05/requirements.txt"],
        [sys.executable, "scripts/auth05/verify_postgres.py"],
    ]),
    ("auth04", "auth04.yml contracts", "AUTH-04 password / CSRF / route contracts (no DB)", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth04/requirements.txt"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit", "-p", "test_auth04*.py", "-v"],
    ]),
    ("auth04-postgres", "auth04.yml postgres", "AUTH-04 LIVE PostgreSQL session / HTTP / fault contracts", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth04/requirements.txt"],
        [sys.executable, "scripts/auth04/verify_postgres.py"],
    ]),
    ("auth03", "auth03.yml contracts", "AUTH-03 unified context / ASGI adapters (no DB)", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth03/requirements.txt"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit",
         "-p", "test_auth03*.py", "-v"],
    ]),
    ("auth03-postgres", "auth03.yml postgres", "AUTH-03 LIVE PostgreSQL context/currentness", [
        [sys.executable, "-m", "pip", "install", "-r", "scripts/auth03/requirements.txt"],
        [sys.executable, "scripts/auth03/verify_postgres.py"],
    ]),
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
    ("auth00", "auth00.yml", "AUTH-00 inventory + Git snapshot parity (default INDEX)", [
        # Fail early with an actionable snapshot mismatch before the slow suite.
        # No automatic staging: INDEX after explicit git add; HEAD before push.
        [sys.executable, "scripts/auth00/check_committed.py"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit",
         "-p", "test_auth00*.py", "-v"],
        [sys.executable, "scripts/auth00/inventory.py", "--check"],
        # Keep the final parity fence if sources change during the unit suite.
        [sys.executable, "scripts/auth00/check_committed.py"],
    ]),
    ("rules", "test_rules.yml", "Validation rules sanity check", [
        [sys.executable, "-c", RULES_CHECK],
    ]),
    # V2.3 (2026-11-06): session_backend memory -> Postgres. Живой
    # Postgres-контракт слоя 1 сессий (CAS/TTL/prune/readiness/REST-смоук
    # /health/ops). Опциональный gate (паритет authXX-postgres): нужен
    # disposable DSN в CISSTAT_TEST_PG_DSN; без него gate честно падает
    # (не skip) -- пуш с «непроверенным durable» невозможен молча.
    ("session-postgres", "test.yml (V2.3, live PG opt-in)", "Session backend Postgres: CAS/TTL/prune/health на живой БД", [
        [sys.executable, "-c",
         ("import os; assert os.environ.get('CISSTAT_TEST_PG_DSN'), "
          "'CISSTAT_TEST_PG_DSN обязателен (disposable Postgres DSN, паритет authXX-postgres)'")],
        [sys.executable, "-m", "pip", "install", "-r", "apps/api/requirements.txt"],
        [sys.executable, "-m", "pytest", "tests/api/test_session_store_postgres.py", "-v"],
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


def prepare_commands(commands: list[list[str]], target: str) -> list[list[str]]:
    """Copy gate commands; select the Git snapshot without staging any files."""
    return [[*command, "--target", target]
            if len(command) > 1 and command[1] == "scripts/auth00/check_committed.py"
            else list(command) for command in commands]


def _logged_command(command: list[str], log) -> int:
    """Keep the original exit code; console and UTF-8 file receive one stream."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    with subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                          errors="replace", env=env) as process:
        for line in process.stdout:
            log.write(line)
            log.flush()
            try:
                print(line, end="", flush=True)
            except UnicodeEncodeError:
                # Redirected Windows consoles can still use a legacy codepage.
                encoding = getattr(sys.stdout, "encoding", None) or "ascii"
                print(line.encode(encoding, errors="backslashreplace").decode(encoding),
                      end="", flush=True)
        return process.wait()


def run_gate(name: str, commands: list[list[str]], skip_install: bool,
             failures: dict | None = None) -> tuple[bool, float]:
    started = time.monotonic()
    log = None
    log_path = None
    if name == "auth00":
        log_path = ROOT / "logs/local_gates/auth00.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log = log_path.open("w", encoding="utf-8", newline="\n")
        print("    AUTH-00 full log: " + str(log_path), flush=True)
    try:
        for original in commands:
            command = list(original)
            is_install = command[:2] == ["npm", "ci"] or command[1:3] == ["-m", "pip"]
            if skip_install and is_install:
                print("    (установка зависимостей пропущена: --skip-install)")
                continue
            if command and command[0] == "npm":
                command = [_npm(), *command[1:]]
            heading = "    $ " + " ".join(command)
            print(heading, flush=True)
            if log is not None:
                log.write(heading + "\n")
                log.flush()
                code = _logged_command(command, log)
            else:
                code = subprocess.run(command, cwd=ROOT, check=False).returncode
            if code:
                detail = "    FAILED STEP (exit " + str(code) + "): " + " ".join(command)
                print(detail, flush=True)
                if log is not None:
                    log.write(detail + "\n")
                    print("    Полный вывод: " + str(log_path), flush=True)
                if failures is not None:
                    failures[name] = {"command": command, "log": log_path}
                return False, time.monotonic() - started
        return True, time.monotonic() - started
    finally:
        if log is not None:
            log.close()


def staging_manifests() -> list[str]:
    """Suggest the latest delivered AUTH task, preserving explicit operator staging."""
    candidates = [p for p in (ROOT / "scripts").glob("auth[0-9][0-9]") if (p / "files.txt").is_file()]
    if not candidates:
        return ["scripts/auth10/files.txt", "scripts/auth10/hotfix01/files.txt"]
    task = max(candidates, key=lambda p: int(p.name[4:]))
    paths = [task / "files.txt", *sorted(task.glob("hotfix[0-9][0-9]/files.txt"))]
    return [p.relative_to(ROOT).as_posix() for p in paths]


def main() -> int:
    # Список имён строится из GATES: статические строки в трёх местах
    # расходились с фактом (AUTH-20/21 добавили гейты, но не строки подсказок).
    all_gate_names = ", ".join(g[0] for g in GATES)
    parser = argparse.ArgumentParser(
        description="Локальный прогон CI-гейтов перед пушем (паритет GitHub Actions)")
    parser.add_argument("--only", metavar="a,b,c",
                        help="запустить только выбранные гейты (" + all_gate_names + ")")
    parser.add_argument("--auth00-target", choices=("index", "head"), default="index",
                        help="AUTH-00: index после явного git add (default), head после commit перед push")
    parser.add_argument("--skip-install", action="store_true",
                        help="пропустить npm ci / pip install (повторные локальные прогоны)")
    parser.add_argument("--with-pytest", action="store_true",
                        help="добавить полный pytest-гейт (нужен для push в develop/refactor/*)")
    parser.add_argument("--with-auth02-postgres", action="store_true",
                        help="добавить live PG проверки; нужен disposable CISSTAT_AUTH_TEST_DSN (в CI обязательны)")
    parser.add_argument("--with-auth03-postgres", action="store_true",
                        help="добавить live PG context/currentness; нужен disposable CISSTAT_AUTH_TEST_DSN")
    parser.add_argument("--with-auth06-postgres", action="store_true",
                        help="добавить PostgreSQL / two-origin HTTPS proof")
    parser.add_argument("--with-auth05-postgres", action="store_true",
                        help="добавить PostgreSQL MFA/bootstrap/recovery проверки")
    parser.add_argument("--with-auth04-postgres", action="store_true",
                        help="добавить PostgreSQL session/HTTP/fault проверки; нужен disposable CISSTAT_AUTH_TEST_DSN")
    parser.add_argument("--with-auth23-postgres", action="store_true",
                        help="добавить native PostgreSQL refund/dispute проверки; нужен disposable CISSTAT_AUTH_TEST_DSN")
    parser.add_argument("--with-auth22-postgres", action="store_true",
                        help="добавить native PostgreSQL top-up quote/checkout/credit проверки; нужен disposable CISSTAT_AUTH_TEST_DSN")
    parser.add_argument("--with-auth21-postgres", action="store_true",
                        help="добавить native PostgreSQL wallet/lot проверки; нужен disposable CISSTAT_AUTH_TEST_DSN")
    parser.add_argument("--with-auth20-postgres", action="store_true", help="AUTH-20 native reconcile/quarantine/lockdown/audit delivery")
    parser.add_argument("--with-auth19-postgres", action="store_true", help="AUTH-19 native external entry / selection / audit")
    parser.add_argument("--with-auth18-postgres", action="store_true", help="AUTH-18 native provider saga")
    parser.add_argument("--with-auth17-postgres", action="store_true", help="AUTH-17 native team/capacity/OWNER races")
    parser.add_argument("--with-auth16-postgres", action="store_true", help="AUTH-16 native lifecycle / quotas / cleanup")
    parser.add_argument("--with-auth15-postgres", action="store_true",
                        help="добавить AUTH-15 native PostgreSQL campaign / isolation / races")
    parser.add_argument("--with-auth14-postgres", action="store_true",
                        help="добавить AUTH-14 PostgreSQL metering / capacity / replay")
    parser.add_argument("--with-auth13-postgres", action="store_true",
                        help="добавить AUTH-13 PostgreSQL worker / fencing / reconciliation")
    parser.add_argument("--with-auth12-postgres", action="store_true",
                        help="добавить AUTH-12 native ledger/reservation; disposable CISSTAT_AUTH_TEST_DSN")
    parser.add_argument("--with-auth11-postgres", action="store_true",
                        help="добавить AUTH-11 real PostgreSQL scientific/route proof; disposable CISSTAT_AUTH_TEST_DSN")
    parser.add_argument("--with-auth10-postgres", action="store_true",
                        help="добавить AUTH-10 native key lifecycle; disposable CISSTAT_AUTH_TEST_DSN")
    parser.add_argument("--with-auth09-postgres", action="store_true",
                        help="добавить AUTH-09 native object/migration проверки; disposable CISSTAT_AUTH_TEST_DSN")
    parser.add_argument("--with-auth08-postgres", action="store_true",
                        help="добавить AUTH-08 PostgreSQL Account lifecycle/CAS/audit; нужен disposable CISSTAT_AUTH_TEST_DSN")
    parser.add_argument("--with-session-postgres", action="store_true",
                        help="добавить V2.3 live PG проверку session backend; нужен disposable CISSTAT_TEST_PG_DSN")
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
    if not args.with_auth03_postgres:
        excluded.add("auth03-postgres")
    if not args.with_auth06_postgres:
        excluded.add("auth06-postgres")
    if not args.with_auth05_postgres:
        excluded.add("auth05-postgres")
    if not args.with_auth04_postgres:
        excluded.add("auth04-postgres")
    if not args.with_auth23_postgres:
        excluded.add("auth23-postgres")
    if not args.with_auth22_postgres:
        excluded.add("auth22-postgres")
    if not args.with_auth21_postgres:
        excluded.add("auth21-postgres")
    if not args.with_auth20_postgres:
        excluded.add("auth20-postgres")
    if not args.with_auth19_postgres:
        excluded.add("auth19-postgres")
    if not args.with_auth18_postgres:
        excluded.add("auth18-postgres")
    if not args.with_auth17_postgres:
        excluded.add("auth17-postgres")
    if not args.with_auth16_postgres:
        excluded.add("auth16-postgres")
    if not args.with_auth15_postgres:
        excluded.add("auth15-postgres")
    if not args.with_auth14_postgres:
        excluded.add("auth14-postgres")
    if not args.with_auth13_postgres:
        excluded.add("auth13-postgres")
    if not args.with_auth12_postgres:
        excluded.add("auth12-postgres")
    if not args.with_auth11_postgres:
        excluded.add("auth11-postgres")
    if not args.with_auth10_postgres:
        excluded.add("auth10-postgres")
    if not args.with_auth09_postgres:
        excluded.add("auth09-postgres")
    if not args.with_auth08_postgres:
        excluded.add("auth08-postgres")
    if not args.with_session_postgres:
        excluded.add("session-postgres")
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
              "pytest добавляется --with-pytest; live PG — --with-auth02-postgres/--with-auth03-postgres/"
              "--with-auth04-postgres/--with-auth05-postgres/--with-auth06-postgres/--with-auth08-postgres/"
              "--with-auth09-postgres/--with-auth10-postgres/--with-auth11-postgres/--with-auth12-postgres/"
              "--with-auth13-postgres/--with-auth14-postgres/--with-auth15-postgres/--with-auth16-postgres/"
              "--with-auth17-postgres/--with-auth18-postgres/--with-auth19-postgres/--with-auth20-postgres/"
              "--with-auth21-postgres/--with-auth22-postgres/--with-auth23-postgres/"
              "--with-session-postgres")
        return 0
    if not selected:
        parser.error("ничего не выбрано; доступно: " + all_gate_names)

    rev = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    ).stdout.strip()
    names = ", ".join(g[0] for g in selected)
    print(f"Локальные гейты (база {rev}, AUTH-00 target={args.auth00_target.upper()}): {names}", flush=True)
    failures = {}
    results: list[tuple[str, bool, float]] = []
    failed = False
    for name, origin, description, commands in selected:
        print(f"\n=== ГЕЙТ {name} ({origin}) — {description}", flush=True)
        ok, seconds = run_gate(name, prepare_commands(commands, args.auth00_target), args.skip_install, failures)
        results.append((name, ok, seconds))
        print(f"--- {name}: {'PASS' if ok else 'FAIL'} ({seconds:.1f} c)", flush=True)
        if not ok and args.fail_fast:
            break
    print("\n=== СВОДКА ===")
    for name, ok, seconds in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name:7s} {seconds:7.1f} c")
    for name, detail in failures.items():
        print("  FAILED STEP " + name + ": " + " ".join(detail["command"]))
        if detail["log"]:
            print("  Полный лог: " + str(detail["log"]))
        if name == "auth00" and "scripts/auth00/check_committed.py" in detail["command"]:
            try:
                worktree_failed = detail["log"] is not None and "WORKTREE inventory check failed:" in detail["log"].read_text(encoding="utf-8")
            except OSError:
                worktree_failed = False
            if worktree_failed:
                print("  WORKTREE не соответствует reviewed inventory. Проверьте названные в auth00.log файлы и карту поставки.")
                print("  Одного staging недостаточно; не перегенерируйте inventory только ради PASS.")
            else:
                print("  До commit: просмотрите изменения и явно подготовьте INDEX:")
                for manifest in staging_manifests():
                    print("    git add --pathspec-from-file=" + manifest)
                print("  После commit проверяйте HEAD: --auth00-target head. Автоматического staging нет.")
            print("    python scripts/local_gates.py --only auth00 --skip-install")
    failed = any(not ok for _, ok, _ in results)
    names_run = {name for name, _, _ in results}
    missing_live = [name for name in ("auth02", "auth03", "auth04", "auth05", "auth06", "auth08", "auth09", "auth10", "auth11", "auth12", "auth13", "auth14", "auth15", "auth16", "auth17", "auth18", "auth19", "auth20", "auth21", "auth22", "auth23")
                    if name in names_run and name + "-postgres" not in names_run]
    if not failed and missing_live:
        print("\nИТОГ: выбранные гейты зелёные; live PostgreSQL не проверен: "
              + ", ".join(missing_live) + " (нужны соответствующие --with-authXX-postgres; native CI отдельно)")
    else:
        print("\nИТОГ: " + ("выбранные гейты зелёные" if not failed
                            else "НЕ ПУШТЕ — есть красные гейты"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
