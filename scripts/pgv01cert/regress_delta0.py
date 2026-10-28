#!/usr/bin/env python3
# scripts/pgv01cert/regress_delta0.py
#
# PGV-01-CERT — дельта-0: полный регресс и сборка на сертифицируемом дереве.
#
# Каналы: полный jest; typecheck:all (обе оболочки); py_compile поставки;
# import apps.api.main (маршруты); doc-гварды PGV-00/01; git diff --check;
# чистота продуктового дерева (изменения — только корпус сертификатора,
# worklog и акт сертификации).

from __future__ import annotations

import json
import py_compile
import subprocess
import sys
from pathlib import Path

CERT_DIR = Path(__file__).resolve().parent
REPO = CERT_DIR.parents[1]
PROTOCOLS = CERT_DIR / "protocols"

ALLOWED_DIRTY_PREFIXES = (
    "scripts/pgv01cert/",
    "worklog/worklog11.md",
    "docs/cert_pgv01_2026-10-28.md",
)


def run(cmd: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True, timeout=timeout)


def main() -> int:
    PROTOCOLS.mkdir(exist_ok=True)
    report: dict = {}
    ok = True

    print("1/7 полный jest…")
    jest = run(["npx", "jest", "--silent"])
    jest_tail = (jest.stdout + jest.stderr).strip().splitlines()[-6:]
    report["jest"] = {"rc": jest.returncode, "tail": jest_tail}
    ok &= jest.returncode == 0
    print("   rc =", jest.returncode, "|", jest_tail[-4:-2])

    print("2/7 typecheck:all…")
    typecheck = run(["npm", "run", "typecheck:all"])
    report["typecheck"] = {"rc": typecheck.returncode}
    ok &= typecheck.returncode == 0
    print("   rc =", typecheck.returncode)

    print("3/7 py_compile поставки…")
    compile_ok = True
    for rel in ("apps/api/print_schema.py", "scripts/pgv01/check_documents.py", "tests/api/test_pgv01_print_schema.py"):
        try:
            py_compile.compile(str(REPO / rel), doraise=True)
        except py_compile.PyCompileError as error:
            compile_ok = False
            report.setdefault("py_compile_errors", []).append(str(error))
    report["py_compile"] = {"ok": compile_ok}
    ok &= compile_ok
    print("   ok =", compile_ok)

    print("4/7 import apps.api.main…")
    api_probe = run([sys.executable, "-c", "import apps.api.main as m; print(len(m.app.routes))"])
    routes = api_probe.stdout.strip().splitlines()[-1] if api_probe.returncode == 0 else "ERROR"
    report["api_import"] = {"rc": api_probe.returncode, "routes": routes}
    ok &= api_probe.returncode == 0 and routes == "221"
    print("   routes =", routes)

    print("5/7 doc-гварды…")
    guard01 = run([sys.executable, "scripts/pgv01/check_documents.py"])
    guard00 = run([sys.executable, "scripts/pgv00/check_documents.py"])
    report["guards"] = {"pgv01_rc": guard01.returncode, "pgv00_rc": guard00.returncode}
    ok &= guard01.returncode == 0 and guard00.returncode == 0
    print("   pgv01:", guard01.stdout.strip().splitlines()[0] if guard01.stdout else guard01.returncode)
    print("   pgv00:", guard00.stdout.strip().splitlines()[0] if guard00.stdout else guard00.returncode)

    print("6/7 git diff --check…")
    diff_check = run(["git", "diff", "--check"])
    report["git_diff_check"] = {"rc": diff_check.returncode}
    ok &= diff_check.returncode == 0
    print("   rc =", diff_check.returncode)

    print("7/7 чистота продуктового дерева…")
    status = run(["git", "status", "--porcelain"])
    dirt = [
        line
        for line in status.stdout.splitlines()
        if not any(line.split(maxsplit=1)[-1].startswith(prefix) for prefix in ALLOWED_DIRTY_PREFIXES)
    ]
    report["tree_cleanliness"] = {"unexpected": dirt}
    ok &= not dirt
    print("   unexpected dirt:", dirt if dirt else "нет")

    (PROTOCOLS / "delta0_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("DELTA-0:", "OK" if ok else "FAILED", "| protocol:", PROTOCOLS / "delta0_summary.json")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
