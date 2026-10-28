# scripts/pgv03cert/build_check.py
"""Сборочная проверка дельты-0 PGV-03-CERT: py_compile, import main,
каталоги/маршруты, doc-гварды, чистота дерева."""
from __future__ import annotations

import py_compile
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

FILES = [
    "apps/api/visual_producers.py",
    "apps/api/promotion_integration.py",
    "apps/api/visual_artifacts.py",
    "apps/api/artifact_promotion.py",
]


def main() -> int:
    ok = True
    for rel in FILES:
        try:
            py_compile.compile(str(REPO / rel), doraise=True)
            print(f"py_compile OK: {rel}")
        except py_compile.PyCompileError as exc:
            ok = False
            print(f"py_compile FAIL: {rel}: {exc}")
    r = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, '.'); from apps.api import main; "
         "print(len(main.app.routes))"],
        cwd=REPO, capture_output=True, text=True,
    )
    routes = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "?"
    print(f"import apps.api.main: rc={r.returncode}, routes={routes}")
    ok = ok and r.returncode == 0 and routes == "221"
    for guard in ("scripts/pgv00/check_documents.py", "scripts/pgv01/check_documents.py", "scripts/pgv02/check_documents.py"):
        g = subprocess.run([sys.executable, guard], cwd=REPO, capture_output=True, text=True)
        tail = (g.stdout.strip().splitlines() or [""])[-1]
        print(f"guard {guard}: rc={g.returncode} | {tail}")
        ok = ok and g.returncode == 0
    d = subprocess.run(["git", "diff", "--check"], cwd=REPO, capture_output=True, text=True)
    print("git diff --check:", "PASS" if d.returncode == 0 else f"FAIL: {d.stdout}")
    ok = ok and d.returncode == 0
    print("BUILD:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
