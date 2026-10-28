#!/usr/bin/env python3
# scripts/pgv01cert/red_parent.py
#
# PGV-01-CERT — RED на родителе 2ef6947 (PGV-00, база поставки PGV-01).
#
# Ожидаемая честная RED-картина на родителе:
#   - корпус сертификатора: collection error (нет apps/api/print_schema.py);
#   - TS-драйвер: ERR_MODULE_NOT_FOUND (нет packages/ui/print/printSchema.ts);
#   - repo-сюита PGV-01: файл отсутствует (не часть поставки родителя).
#
# Паттерн PGV-00-CERT: git-worktree родителя, корпус копируется (не
# коммичен), node_modules — симлинк. По завершении worktree удаляется.

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

CERT_DIR = Path(__file__).resolve().parent
REPO = CERT_DIR.parents[1]
PROTOCOLS = CERT_DIR / "protocols"
PARENT_COMMIT = "2ef6947"
WORKTREE = REPO.parent / "cisstat-pgv01-parent-worktree"


def run(cmd: list[str], cwd: Path, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)


def main() -> int:
    PROTOCOLS.mkdir(exist_ok=True)
    protocol: dict = {"parent": PARENT_COMMIT, "checks": {}}

    if WORKTREE.exists():
        shutil.rmtree(WORKTREE, ignore_errors=True)
    add = run(["git", "worktree", "add", str(WORKTREE), PARENT_COMMIT], REPO)
    if add.returncode != 0:
        print(f"worktree add failed: {add.stderr}")
        return 2
    try:
        node_modules = WORKTREE / "node_modules"
        if not node_modules.exists():
            node_modules.symlink_to(REPO / "node_modules", target_is_directory=True)

        # 1) Корпус сертификатора на родителе
        corpus_dst = WORKTREE / "scripts" / "pgv01cert"
        corpus_dst.mkdir(parents=True, exist_ok=True)
        for name in ("p1cases.py", "p1harness.py", "mutations.py",
                     "test_p1cert_oracle_static.py", "test_p1cert_parity.py",
                     "test_p1cert_findings_evidence.py", "p1ts_driver.ts"):
            shutil.copy2(CERT_DIR / name, corpus_dst / name)
        corpus_run = run([sys.executable, "-m", "pytest", "scripts/pgv01cert/", "-q"], WORKTREE)
        corpus_red = corpus_run.returncode != 0
        corpus_marker = "ModuleNotFoundError" in corpus_run.stderr or "ModuleNotFoundError" in corpus_run.stdout
        protocol["checks"]["cert_corpus"] = {
            "RED": corpus_red,
            "module_not_found_evidence": corpus_marker,
            "tail": (corpus_run.stderr or corpus_run.stdout)[-400:],
        }

        # 2) TS-драйвер на родителе (нет printSchema.ts)
        job = {"cases": [{"id": "P1", "kind": "manifest", "payload": {}, "site": None}]}
        job_path = corpus_dst / "_parent_job.json"
        job_path.write_text(json.dumps(job), encoding="utf-8")
        driver_run = run(
            ["node", "--experimental-strip-types", "scripts/pgv01cert/p1ts_driver.ts", str(job_path)],
            WORKTREE,
        )
        driver_red = driver_run.returncode != 0
        driver_marker = "ERR_MODULE_NOT_FOUND" in driver_run.stderr and "printSchema.ts" in driver_run.stderr
        protocol["checks"]["ts_driver"] = {
            "RED": driver_red,
            "module_not_found_evidence": driver_marker,
            "tail": driver_run.stderr[-400:],
        }
        job_path.unlink(missing_ok=True)

        # 3) Repo-сюита PGV-01 отсутствует как часть поставки родителя
        protocol["checks"]["repo_suite_file_absent"] = {
            "RED": not (WORKTREE / "tests/api/test_pgv01_print_schema.py").exists()
            and not (WORKTREE / "packages/ui/print/printSchema.test.ts").exists(),
        }

        protocol["RED_on_parent"] = (
            protocol["checks"]["cert_corpus"]["RED"]
            and protocol["checks"]["ts_driver"]["RED"]
            and protocol["checks"]["repo_suite_file_absent"]["RED"]
        )
    finally:
        run(["git", "worktree", "remove", "--force", str(WORKTREE)], REPO)
        run(["git", "worktree", "prune"], REPO)

    (PROTOCOLS / "red_parent_summary.json").write_text(
        json.dumps(protocol, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    verdict = "RED on parent: OK" if protocol["RED_on_parent"] else "UNEXPECTED: parent not fully RED"
    print(verdict)
    for name, check in protocol["checks"].items():
        print(f"  {name}: {check}")
    return 0 if protocol["RED_on_parent"] else 1


if __name__ == "__main__":
    sys.exit(main())
