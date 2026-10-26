# scripts/doclogrecheckfixcert/run_campaign.py
"""
Драйвер мутационной кампании DOCLOG-E2E-RECHECK-1-FIX (аудит 9401fa5).

Работает В ОТДЕЛЬНОМ git-worktree (wt-fix-9401fa5 @ 9401fa5); продуктовое
дерево не трогает. Для каждого мутанта:
  1. GUARD: md5 целевых файлов == базовым (чистота дерева);
  2. применить замену (строго один раз);
  3. прогнать оракулы (backend: repo-корпус + пробы сертификатора +
     динамический C08 acceptance; UI: jest-корпус + пробы);
  4. восстановить файлы (git checkout --) и проверить GUARD снова.

Результаты -- JSON-аккумулятор (среда обрывает долгие процессы, поэтому
прогон порциями по --only/--second, слияние по id).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from mutations import MUTANTS, SECOND_ORDER, by_id  # noqa: E402

WORKTREE = Path("/home/z/my-project/wt-fix-9401fa5")
RESULTS = HERE / "protocols" / "mutation_results.json"

BACKEND_CMD = [
    "python3", "-m", "pytest",
    "tests/api/test_doclog_recheck_fix.py",
    "scripts/doclogrecheckfixcert/test_cert_oracle_unit.py",
    "scripts/doclogcert_2026_10_26/test_acceptance_red.py::test_mandatory_profile_audit_failure_does_not_commit_policy",
    "-q", "-p", "no:cacheprovider", "--no-header", "-x", "--tb=no",
]
UI_CMD = [
    "npx", "jest",
    "scripts/doclogrecheckfixcert/documentation-cert-oracle.test.tsx",
    "packages/ui/components/documentation-recheck-fix.test.tsx",
    "--runInBand",
]


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def base_digests(mutant) -> dict[str, str]:
    files = {mutant.file} | {f for f, _ in mutant.extra}
    return {f: md5(WORKTREE / f) for f in sorted(files)}


def apply_mutant(mutant) -> None:
    edits = [(mutant.file, mutant.old, mutant.new)] + mutant.extra
    for rel, old, new in edits:
        path = WORKTREE / rel
        text = path.read_text()
        count = text.count(old)
        if count != 1:
            raise RuntimeError(f"{mutant.mid}: {rel}: {count} совпадений (нужно 1)")
        path.write_text(text.replace(old, new, 1))


def restore(digests: dict[str, str]) -> None:
    for rel, digest in digests.items():
        path = WORKTREE / rel
        subprocess.run(
            ["git", "checkout", "--", rel], cwd=WORKTREE, check=True
        )
        if md5(path) != digest:
            raise RuntimeError(f"GUARD FAIL после restore: {rel}")


def is_ui(mutant) -> bool:
    return mutant.file.endswith((".tsx", ".ts"))


def run_oracles(mutant) -> dict:
    cmd = UI_CMD if is_ui(mutant) else BACKEND_CMD
    proc = subprocess.run(
        cmd, cwd=WORKTREE, capture_output=True, text=True, timeout=900
    )
    killed = proc.returncode != 0
    failed_ids = [
        line.split(" ")[0].split("::")[-1]
        for line in (proc.stdout + proc.stderr).splitlines()
        if line.startswith("FAILED ")
    ]
    if is_ui(mutant):
        # jest: падение suite не даёт FAILED-строк pytest-формата
        failed_ids = ["UI-SUITE"] if killed else []
    return {
        "id": mutant.mid,
        "killed": killed,
        "killers": failed_ids,
        "expectation": mutant.expectation,
        "note": mutant.note,
        "rc": proc.returncode,
        "tail": (proc.stdout + proc.stderr).strip().splitlines()[-3:] if killed else [],
    }


def run_second(sid: str, parts: list[str]) -> dict:
    ms = [by_id(p) for p in parts]
    files = {m.file for m in ms}
    digests = {f: md5(WORKTREE / f) for f in sorted(files)}
    ui = any(is_ui(m) for m in ms)
    try:
        for m in ms:
            apply_mutant(m)
        cmd = UI_CMD if ui else BACKEND_CMD
        proc = subprocess.run(
            cmd, cwd=WORKTREE, capture_output=True, text=True, timeout=900
        )
        killed = proc.returncode != 0
        killers = ["UI-SUITE"] if (ui and killed) else (
            [
                line.split(" ")[0].split("::")[-1]
                for line in (proc.stdout + proc.stderr).splitlines()
                if line.startswith("FAILED ")
            ]
        )
        return {
            "id": sid,
            "parts": parts,
            "killed": killed,
            "killers": killers,
            "rc": proc.returncode,
            "tail": (proc.stdout + proc.stderr).strip().splitlines()[-3:] if killed else [],
        }
    finally:
        for rel in digests:
            subprocess.run(
                ["git", "checkout", "--", rel], cwd=WORKTREE, check=True
            )
        for rel, digest in digests.items():
            if md5(WORKTREE / rel) != digest:
                raise RuntimeError(f"GUARD FAIL после restore 2-го порядка: {rel}")


def main() -> None:
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    results = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    mode = sys.argv[2] if len(sys.argv) > 2 else "first"

    if mode == "first":
        for mutant in MUTANTS:
            if only and mutant.mid not in only.split(","):
                continue
            if mutant.mid in results:
                continue
            digests = base_digests(mutant)
            for rel, digest in digests.items():
                if md5(WORKTREE / rel) != digest:
                    raise RuntimeError(f"GUARD FAIL до apply: {rel}")
            apply_mutant(mutant)
            try:
                results[mutant.mid] = run_oracles(mutant)
            finally:
                restore(digests)
            print(
                results[mutant.mid]["id"],
                "KILLED" if results[mutant.mid]["killed"] else "SURVIVED",
                results[mutant.mid]["killers"],
                flush=True,
            )
    elif mode == "second":
        for sid, parts in SECOND_ORDER:
            if only and sid not in only.split(","):
                continue
            if sid in results:
                continue
            results[sid] = run_second(sid, parts)
            print(
                sid,
                "DUAL-KILLED" if results[sid]["killed"] else "ALIVE",
                results[sid]["killers"],
                flush=True,
            )

    RESULTS.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"saved -> {RESULTS}")


if __name__ == "__main__":
    main()
