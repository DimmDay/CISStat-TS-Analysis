# scripts/pgv03cert/red_parent.py
"""RED на родителе поставки PGV-03 (2f412d6 = PGV-02) через
git-worktree: корпус сертификатора копируется в worktree (он не
закоммичен), продуктовое дерево -- родительское. Все каналы обязаны
быть RED (нет apps/api/visual_producers.py и пр.).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

CERT_DIR = Path(__file__).resolve().parent
REPO = CERT_DIR.parents[1]
PARENT = "2f412d6"  # родитель поставки PGV-03 (bf0ae7a)
WT = REPO.parent / "CISStat-TS-Analysis-p3cert-parent"
PROTOCOLS = CERT_DIR / "protocols"

CORPUS_FILES = [
    "conftest.py",
    "p3cases.py",
    "test_p3cert_oracle_unit.py",
    "test_p3cert_oracle_api.py",
    "test_p3cert_oracle_static.py",
    "test_p3cert_findings_evidence.py",
]


def sh(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd or REPO, capture_output=True, text=True)


def main() -> int:
    protocols: dict = {}
    sh(["git", "worktree", "remove", "--force", str(WT)])
    result = sh(["git", "worktree", "add", "--detach", str(WT), PARENT])
    if result.returncode != 0:
        print("worktree add failed:", result.stderr)
        return 1
    try:
        (WT / "scripts/pgv03cert").mkdir(parents=True, exist_ok=True)
        for corpus_file in CORPUS_FILES:
            (WT / "scripts/pgv03cert" / corpus_file).write_text(
                (CERT_DIR / corpus_file).read_text(encoding="utf-8")
            )
        # 1) Class A корпус
        r1 = sh([
            sys.executable, "-m", "pytest",
            "scripts/pgv03cert/test_p3cert_oracle_unit.py",
            "scripts/pgv03cert/test_p3cert_oracle_api.py",
            "scripts/pgv03cert/test_p3cert_oracle_static.py",
            "-q", "--no-header", "-p", "no:cacheprovider", "--tb=line",
        ], cwd=WT)
        protocols["class_a"] = {
            "returncode": r1.returncode,
            "tail": (r1.stdout.strip().splitlines() or [""])[-1],
        }
        # 2) Class B (на родителе RED по другой причине: модуля нет)
        r2 = sh([
            sys.executable, "-m", "pytest",
            "scripts/pgv03cert/test_p3cert_findings_evidence.py",
            "-q", "--no-header", "-p", "no:cacheprovider", "--tb=line",
        ], cwd=WT)
        protocols["class_b"] = {
            "returncode": r2.returncode,
            "tail": (r2.stdout.strip().splitlines() or [""])[-1],
        }
        # 3) repo-канал кампании (сюита поставки)
        r3 = sh([
            sys.executable, "-m", "pytest",
            "tests/api/test_pgv03_producer_adapters.py",
            "-q", "--no-header", "-p", "no:cacheprovider", "--tb=line",
        ], cwd=WT)
        protocols["repo_pgv03"] = {
            "returncode": r3.returncode,
            "tail": (r3.stdout.strip().splitlines() or [""])[-1],
        }
        # 4) продуктовые файлы поставки отсутствуют?
        protocols["visual_producers_absent"] = not (WT / "apps/api/visual_producers.py").exists()
        protocols["repo_suite_absent"] = not (WT / "tests/api/test_pgv03_producer_adapters.py").exists()
        red = (
            r1.returncode != 0
            and r2.returncode != 0
            and r3.returncode != 0
            and protocols["visual_producers_absent"]
            and protocols["repo_suite_absent"]
        )
        protocols["RED"] = red
        PROTOCOLS.mkdir(exist_ok=True)
        (PROTOCOLS / "red_parent_summary.json").write_text(
            json.dumps(protocols, ensure_ascii=False, indent=1)
        )
        print(json.dumps(protocols, ensure_ascii=False, indent=1))
        return 0 if red else 2
    finally:
        sh(["git", "worktree", "remove", "--force", str(WT)])


if __name__ == "__main__":
    sys.exit(main())
