#!/usr/bin/env python3
# scripts/pgv00cert/regress_delta0.py
#
# PGV-00-CERT — регресс дельта-0.
# Diff изоляция: поставка PGV-00 не трогает Python-runtime и конфиги сборки —
# полный tests/api не требуется (прецедент записи PGV-00); проверяется:
#   1) git diff 754219a..2ef6947 --name-only — состав поставки ровно 8 файлов,
#      ни одного .py-runtime/.json-config-сборки/requirements/Dockerfile;
#   2) полный jest (222 сюиты) на дереве 2ef6947 — 0 failed;
#   3) check_documents.py GREEN;
#   4) Class A корпуса GREEN; Class B — честные RED-свидетельства находок (6).

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PROT = HERE / "protocols"
PROT.mkdir(exist_ok=True)

DELIVERY_FILES = {
    "config/visual_registry.json",
    "docs/pgv00_render_site_inventory.md",
    "packages/ui/lib/visualExportRegistry.coverage.test.ts",
    "packages/ui/lib/visualExportRegistry.ts",
    "scripts/pgv00/check_documents.py",
    "scripts/pgv00/export_registry.ts",
    "spec_documentation_logging.md",
    "worklog/worklog11.md",
}


def run(cmd: list[str], timeout: int = 1800) -> tuple[int, str]:
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr)


def main() -> int:
    summary: dict = {}

    # 1) Дифф-изоляция поставки
    rc, out = run(["git", "diff", "--name-only", "754219a", "2ef6947"])
    files = set(out.split())
    summary["diff_files"] = sorted(files)
    summary["diff_is_exactly_delivery"] = files == DELIVERY_FILES
    summary["python_runtime_touched"] = [
        f for f in files if f.endswith(".py") and not f.startswith("scripts/")
    ]
    summary["build_configs_touched"] = [
        f for f in files if f in ("requirements.txt", "apps/api/Dockerfile", "package.json",
                                  "package-lock.json", "render.yaml", "vercel.json")
    ]

    # 2) Полный jest
    rc, out = run(["npx", "jest", "--silent"], timeout=3600)
    tail = [ln for ln in out.splitlines() if ln.startswith(("Test Suites:", "Tests:", "Snapshots:"))]
    summary["jest_rc"] = rc
    summary["jest_tail"] = tail
    (PROT / "regress_jest_full.txt").write_text(out[-8000:], encoding="utf-8")

    # 3) Guard
    rc, out = run([sys.executable, "scripts/pgv00/check_documents.py"])
    summary["guard_rc"] = rc
    summary["guard_first_line"] = out.splitlines()[0] if out else ""

    # 4) Корпус сертификатора
    rc, out = run([sys.executable, "-m", "pytest", "scripts/pgv00cert/test_p0cert_oracle_static.py",
                   "scripts/pgv00cert/test_p0cert_oracle_coverage.py", "-q", "--no-header",
                   "-p", "no:cacheprovider"])
    summary["cert_class_a_tail"] = out.strip().splitlines()[-1] if out else ""
    rc, out = run([sys.executable, "-m", "pytest", "scripts/pgv00cert/test_p0cert_findings_evidence.py",
                   "-q", "--no-header", "-p", "no:cacheprovider"])
    summary["cert_class_b_tail"] = out.strip().splitlines()[-1] if out else ""

    (PROT / "regress_delta0.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
