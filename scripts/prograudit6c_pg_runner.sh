#!/usr/bin/env bash
# scripts/prograudit6c_pg_runner.sh
# Живой Postgres для AUDIT-6C (план §18 GREEN: фактическая долговечность
# наблюдаема на настоящем хранилище; тот же контракт, что 6A/6B):
# pgserver (переносимые бинарники PostgreSQL в pip-окружении) поднимает
# временный сервер, DSN отдаётся в CISSTAT_TEST_PG_DSN.
#
# Использование:
#   bash scripts/prograudit6c_pg_runner.sh "<pytest args>"
# Пример:
#   bash scripts/prograudit6c_pg_runner.sh \
#     "tests/api/test_progress_audit_6c.py tests/api/test_progress_audit_6b.py -q"
set -euo pipefail
PY=${PY:-python3}
PGDIR=$(mktemp -d /tmp/cisstat6c-pg-XXXX)
export CISSTAT6C_PGDIR="$PGDIR"
export PYTEST_ARGS="$*"

exec $PY - <<'EOF'
import os
import pgserver

server = pgserver.get_server(
    os.environ["CISSTAT6C_PGDIR"], cleanup_mode="delete"
)
os.environ["CISSTAT_TEST_PG_DSN"] = server.get_uri()
print("PG URI:", server.get_uri(), file=os.sys.stderr)

import pytest

args = os.environ.get("PYTEST_ARGS", "").split()
code = pytest.main(args)
raise SystemExit(code)
EOF
