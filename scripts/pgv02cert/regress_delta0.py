# scripts/pgv02cert/regress_delta0.py
"""Дельта-0: полный tests/api на цели (2f412d6) против родителя
(0f8b9a0) в git-worktree -- одна среда, один код сравнения.
Кэш pytest отключён (урок DOCLOG-8 о .pytest_cache). FAILED-ID
обязаны быть байт-идентичны; дельта passed = корпус поставки.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

CERT_DIR = Path(__file__).resolve().parent
REPO = CERT_DIR.parents[1]
PARENT = "0f8b9a03b254262160a1e3427236b55ff906943d"
WT = REPO.parent / "CISStat-TS-Analysis-p2cert-delta0"
PROTOCOLS = CERT_DIR / "protocols"


def sh(args: list[str], cwd: Path | None = None, timeout: int = 1200) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd or REPO, capture_output=True, text=True, timeout=timeout)


def run_full_tests(root: Path) -> dict:
    r = sh([
        sys.executable, "-m", "pytest", "tests/api", "-q", "--no-header",
        "-p", "no:cacheprovider", "--tb=no",
    ], cwd=root)
    tail = (r.stdout.strip().splitlines() or [""])[-1]
    return {"returncode": r.returncode, "tail": tail, "stdout": r.stdout}


def parse_failed_ids(stdout: str) -> list[str]:
    ids = []
    for line in stdout.splitlines():
        if line.startswith("FAILED "):
            ids.append(line[len("FAILED "):].split(" - ")[0].strip())
    return sorted(ids)


def main() -> int:
    # 1) цель
    target = run_full_tests(REPO)
    target_ids = parse_failed_ids(target["stdout"])
    # 2) родитель в worktree
    sh(["git", "worktree", "remove", "--force", str(WT)])
    add = sh(["git", "worktree", "add", "--detach", str(WT), PARENT])
    if add.returncode != 0:
        print("worktree add failed:", add.stderr)
        return 1
    try:
        parent = run_full_tests(WT)
        parent_ids = parse_failed_ids(parent["stdout"])
    finally:
        sh(["git", "worktree", "remove", "--force", str(WT)])
    summary = {
        "target": {"tail": target["tail"], "failed_count": len(target_ids)},
        "parent": {"tail": parent["tail"], "failed_count": len(parent_ids)},
        "failed_ids_identical": target_ids == parent_ids,
        "diff_target_only": sorted(set(target_ids) - set(parent_ids)),
        "diff_parent_only": sorted(set(parent_ids) - set(target_ids)),
    }
    PROTOCOLS.mkdir(exist_ok=True)
    (PROTOCOLS / "delta0_summary.json").write_text(
        json.dumps({**summary, "failed_ids": target_ids}, ensure_ascii=False, indent=1)
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "failed_ids"}, ensure_ascii=False, indent=1))
    return 0 if summary["failed_ids_identical"] else 2


if __name__ == "__main__":
    sys.exit(main())
