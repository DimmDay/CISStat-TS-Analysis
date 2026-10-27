#!/usr/bin/env python3
# scripts/pgv00cert/build_check.py
#
# PGV-00-CERT — сборочные проверки: import apps.api.main (маршруты/каталоги
# без изменений), typecheck:all (TS-реестр в ts-jest и проектах).

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PROT = HERE / "protocols"
PROT.mkdir(exist_ok=True)


def run(cmd: list[str], timeout: int = 1800) -> tuple[int, str]:
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr)


def main() -> int:
    summary: dict = {}

    # import apps.api.main — бэкенд не задет поставкой
    code = (
        "import apps.api.main as m\n"
        "routes = [r.path for r in m.app.routes]\n"
        "import apps.api.research_runs as rr\n"
        "import apps.api.security_audit as sa\n"
        "print(json.dumps({'routes': len(routes), "
        "'migrations': len(rr.MIGRATION_STATEMENTS), "
        "'audit_actions': len(sa.AUDIT_ACTIONS)}))"
    )
    rc, out = run([sys.executable, "-c", code], timeout=600)
    summary["import_api_rc"] = rc
    try:
        summary["import_api"] = json.loads(out.strip().splitlines()[-1])
    except Exception:
        summary["import_api_raw"] = out[-800:]

    # typecheck:all (embedded + standalone)
    rc, out = run(["npm", "run", "typecheck:all"], timeout=2400)
    summary["typecheck_rc"] = rc
    (PROT / "build_typecheck.txt").write_text(out[-6000:], encoding="utf-8")

    (PROT / "build_check.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
