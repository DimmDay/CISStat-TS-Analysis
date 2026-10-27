#!/usr/bin/env python3
# scripts/pgv00cert/red_parent.py
#
# PGV-00-CERT — протокол RED на родителе (754219a) через git-worktree.
# Доказывает, что корпус сертификатора проверяет ИМЕННО поставку PGV-00:
# без неё все каналы падают (Import-RED / JSON-отсутствие / правок спеки нет).

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PARENT = "754219a"
WT = REPO.parent / "wt-pgv00cert-red"
PROT = HERE / "protocols"
PROT.mkdir(exist_ok=True)


def run(cmd: list[str], cwd: Path, timeout: int = 600) -> tuple[int, str]:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr)


def main() -> int:
    summary: dict = {"parent": PARENT, "worktree": str(WT), "channels": {}}

    # Чистый worktree родителя
    if WT.exists():
        shutil.rmtree(WT, ignore_errors=True)
    rc, out = run(["git", "worktree", "add", "--detach", str(WT), PARENT], REPO)
    assert rc == 0, out
    # корпус сертификатора копируется в worktree (он не закоммичен — урок DOCLOG-CERT)
    dst = WT / "scripts" / "pgv00cert"
    dst.mkdir(parents=True, exist_ok=True)
    for f in HERE.glob("*.py"):
        shutil.copy2(f, dst / f.name)

    # 1) ORACLE-канал (Class A) — ожидаем collection/asset RED
    rc, out = run([sys.executable, "-m", "pytest",
                   "scripts/pgv00cert/test_p0cert_oracle_static.py",
                   "scripts/pgv00cert/test_p0cert_oracle_coverage.py",
                   "-q", "--no-header", "-p", "no:cacheprovider"], WT)
    summary["channels"]["oracle_class_a"] = {"rc": rc, "red": rc != 0, "tail": out.strip().splitlines()[-3:]}
    (PROT / "red_parent_oracle.txt").write_text(out, encoding="utf-8")

    # 2) REPO-канал: repo coverage-оракул jest — ожидаем Import-RED (TS2307).
    # node_modules линкуется из основного дерева (package.json у родителя
    # идентичен: PGV-00 не трогал зависимости) — иначе RED по средовой причине.
    nm = WT / "node_modules"
    if not nm.exists():
        nm.symlink_to(REPO / "node_modules")
    rc, out = run(["npx", "jest", "packages/ui/lib/visualExportRegistry.coverage.test.ts"], WT, timeout=900)
    summary["channels"]["repo_jest_coverage"] = {"rc": rc, "red": rc != 0, "tail": out.strip().splitlines()[-6:]}
    (PROT / "red_parent_repo_jest.txt").write_text(out, encoding="utf-8")

    # 3) REPO-канал: guard check_documents.py — ожидаем RED (JSON/спеки нет)
    rc, out = run([sys.executable, "scripts/pgv00/check_documents.py"], WT)
    summary["channels"]["repo_check_documents"] = {"rc": rc, "red": rc != 0, "tail": out.strip().splitlines()[-5:]}
    (PROT / "red_parent_check_documents.txt").write_text(out, encoding="utf-8")

    # 4) Класс B (находки) — тоже RED на родителе (реестра нет)
    rc, out = run([sys.executable, "-m", "pytest", "scripts/pgv00cert/test_p0cert_findings_evidence.py",
                   "-q", "--no-header", "-p", "no:cacheprovider"], WT)
    summary["channels"]["findings_class_b"] = {"rc": rc, "red": rc != 0, "tail": out.strip().splitlines()[-3:]}
    (PROT / "red_parent_findings.txt").write_text(out, encoding="utf-8")

    summary["verdict"] = "RED" if all(c["red"] for c in summary["channels"].values()) else "NOT-RED"
    (PROT / "red_parent_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    # Разборка worktree (дерево родителя больше не нужно)
    run(["git", "worktree", "remove", "--force", str(WT)], REPO)
    return 0 if summary["verdict"] == "RED" else 1


if __name__ == "__main__":
    sys.exit(main())
