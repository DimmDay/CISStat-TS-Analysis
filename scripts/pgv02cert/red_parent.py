# scripts/pgv02cert/red_parent.py
"""RED на родителе поставки PGV-02 (0f8b9a0 = PGV-01-CERT) через
git-worktree: корпус сертификатора копируется в worktree (он не
закоммичен), продуктовое дерево -- родительское. Все каналы обязаны
быть RED (нет apps/api/visual_artifacts.py и пр.).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

CERT_DIR = Path(__file__).resolve().parent
REPO = CERT_DIR.parents[1]
PARENT = "0f8b9a03b254262160a1e3427236b55ff906943d"
WT = REPO.parent / "CISStat-TS-Analysis-p2cert-parent"
PROTOCOLS = CERT_DIR / "protocols"

CORPUS_FILES = [
    "conftest.py",
    "p2cases.py",
    "test_p2cert_oracle_unit.py",
    "test_p2cert_oracle_api.py",
    "test_p2cert_oracle_static.py",
]


def sh(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd or REPO, capture_output=True, text=True)


def main() -> int:
    protocols: dict = {}
    # Свежий worktree на родителе
    sh(["git", "worktree", "remove", "--force", str(WT)])
    result = sh(["git", "worktree", "add", "--detach", str(WT), PARENT])
    if result.returncode != 0:
        print("worktree add failed:", result.stderr)
        return 1
    try:
        # node_modules -- симлинк (package.json родителя идентичен)
        (WT / "scripts/pgv02cert").mkdir(parents=True, exist_ok=True)
        for corpus_file in CORPUS_FILES:
            (WT / "scripts/pgv02cert" / corpus_file).write_text(
                (CERT_DIR / corpus_file).read_text()
            )
        # 1) Class A корпус
        r1 = sh([
            sys.executable, "-m", "pytest",
            "scripts/pgv02cert/test_p2cert_oracle_unit.py",
            "scripts/pgv02cert/test_p2cert_oracle_api.py",
            "scripts/pgv02cert/test_p2cert_oracle_static.py",
            "-q", "--no-header", "-p", "no:cacheprovider", "--tb=line",
        ], cwd=WT)
        protocols["class_a"] = {
            "returncode": r1.returncode,
            "tail": (r1.stdout.strip().splitlines() or [""])[-1],
        }
        # 2) Class B (на родителе тоже RED -- но по другой причине:
        #    модуля нет; зафиксируем отдельно)
        r2 = sh([
            sys.executable, "-m", "pytest",
            "scripts/pgv02cert/test_p2cert_findings_evidence.py",
            "-q", "--no-header", "-p", "no:cacheprovider", "--tb=line",
        ], cwd=WT)
        protocols["class_b"] = {
            "returncode": r2.returncode,
            "tail": (r2.stdout.strip().splitlines() or [""])[-1],
        }
        # 3) repo-канал кампании
        r3 = sh([
            sys.executable, "-m", "pytest",
            "tests/api/test_pgv02_durable_inputs.py",
            "-q", "--no-header", "-p", "no:cacheprovider", "--tb=line",
        ], cwd=WT)
        protocols["repo_pgv02"] = {
            "returncode": r3.returncode,
            "tail": (r3.stdout.strip().splitlines() or [""])[-1],
        }
        # 4) продуктовый файл отсутствует?
        protocols["visual_artifacts_absent"] = not (WT / "apps/api/visual_artifacts.py").exists()
        protocols["migration_0016_absent"] = not (WT / "apps/api/migrations/0016_pgv2_print_documents.sql").exists()
        red = (
            r1.returncode != 0
            and r2.returncode != 0
            and r3.returncode != 0
            and protocols["visual_artifacts_absent"]
            and protocols["migration_0016_absent"]
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
