#!/usr/bin/env bash
# scripts/prograudit6b_pg_runner.sh
# Живой Postgres для AUDIT-6B (план §17 GREEN: «Fault tests с настоящими
# тестовыми PostgreSQL/устойчивым хранилищем обязательны для заявления
# гарантии»): pgserver (переносимые бинарники PostgreSQL в pip-окружении)
# поднимает временный сервер, DSN отдаётся в CISSTAT_TEST_PG_DSN -- тот
# же контракт, что у CI с настоящим PG и у runner'а AUDIT-6A.
#
# Использование:
#   bash scripts/prograudit6b_pg_runner.sh "<pytest args>"
# Пример:
#   bash scripts/prograudit6b_pg_runner.sh \
#     "tests/api/test_progress_audit_6b.py tests/api/test_progress_audit_6a.py -q"
set -euo pipefail
PY=${PY:-python3}
PGDIR=$(mktemp -d /tmp/cisstat6b-pg-XXXX)
export CISSTAT6B_PGDIR="$PGDIR"
export PYTEST_ARGS="$*"

exec $PY - <<'EOF'
import os
import pgserver

server = pgserver.get_server(
    os.environ["CISSTAT6B_PGDIR"], cleanup_mode="delete"
)
os.environ["CISSTAT_TEST_PG_DSN"] = server.get_uri()
print("PG URI:", server.get_uri(), file=os.sys.stderr)

import pytest

args = os.environ.get("PYTEST_ARGS", "").split()
code = pytest.main(args)
raise SystemExit(code)
EOF
