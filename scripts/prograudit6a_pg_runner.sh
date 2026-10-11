#!/usr/bin/env bash
# scripts/prograudit6a_pg_runner.sh
# Живой Postgres для AUDIT-6A (Донастройка_2 п.1: «живые contract-тесты
# обязательны; mock-SQL не замена»): pgserver (переносимые бинарники
# PostgreSQL в pip-окружении) поднимает временный сервер, DSN отдаётся
# в CISSTAT_TEST_PG_DSN -- тот же контракт, что у CI с настоящим PG.
#
# Использование:
#   bash scripts/prograudit6a_pg_runner.sh "<pytest args>"
# Пример:
#   bash scripts/prograudit6a_pg_runner.sh "tests/api/test_progress_audit_6a.py -q"
set -euo pipefail
PY=${PY:-python3}
PGDIR=$(mktemp -d /tmp/cisstat6a-pg-XXXX)
export CISSTAT6A_PGDIR="$PGDIR"
export PYTEST_ARGS="$*"

exec $PY - <<'EOF'
import os, sys
import pgserver

server = pgserver.get_server(
    os.environ["CISSTAT6A_PGDIR"], cleanup_mode="delete"
)
os.environ["CISSTAT_TEST_PG_DSN"] = server.get_uri()
print("PG URI:", server.get_uri(), file=sys.stderr)

# RED-repro на живом PG (честный RED протокола задачи).
import subprocess
red = subprocess.run(
    [sys.executable, "scripts/prograudit6a_red_repro.py"],
    env=os.environ.copy(),
)

args = os.environ.get("PYTEST_ARGS", "").split()
code = __import__("pytest").main(args)
sys.exit(code)
EOF
