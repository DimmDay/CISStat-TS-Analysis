# scripts/pgv03cert/regress_delta0.py
"""Дельта-0: полный tests/api на цели (HEAD c60aa21) против родителя
поставки PGV-03 (2f412d6) в git-worktree -- одна среда, один код
сравнения. Кэш pytest отключён (урок DOCLOG-8 о .pytest_cache).
Дельта FAILED-ID обязана быть пустой в сторону цели: поставка PGV-03
не должна добавлять отказов (родительские -- атрибутируются честно).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

CERT_DIR = Path(__file__).resolve().parent
REPO = CERT_DIR.parents[1]
PARENT = "2f412d6"  # родитель поставки PGV-03 (bf0ae7a)
WT = REPO.parent / "CISStat-TS-Analysis-p3cert-delta0"
PROTOCOLS = CERT_DIR / "protocols"


def sh(args: list[str], cwd: Path | None = None, timeout: int = 2400) -> subprocess.CompletedProcess:
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
    return 0 if not summary["diff_target_only"] else 2


if __name__ == "__main__":
    sys.exit(main())
