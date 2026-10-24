# scripts/doclog8cert/regress_delta0.py
"""DOCLOG-8-CERT: дельта-0 регресс полного tests/api.

Цель:   текущее дерево (659db3d + корпус сертификатора) -- tests/api +
        scripts/doclog8cert.
База:   чистый git-worktree HEAD (659db3d, без корпуса) -- tests/api.
Критерий: множества FAILED-ID байт-идентичны; прирост passed == размер
корпуса сертификатора (78).

Запуск:  /home/z/.venv/bin/python -m scripts.doclog8cert.regress_delta0 target
         /home/z/.venv/bin/python -m scripts.doclog8cert.regress_delta0 base
         /home/z/.venv/bin/python -m scripts.doclog8cert.regress_delta0 diff
(порционно -- среда обрывает долгие фоновые процессы).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
PROTOCOLS = HERE / "protocols"
PY = sys.executable
WORKTREE = Path("/tmp/d8cert-delta0-base")


def _failed_ids(stdout: str) -> list[str]:
    ids = []
    for line in stdout.splitlines():
        if line.startswith("FAILED ") and "::" in line:
            ids.append(line.split()[1])
        elif line.startswith("ERROR ") and "::" in line:
            ids.append(line.split()[1])
    return sorted(ids)


def _passed_count(stdout: str) -> int:
    match = re.search(r"(\d+) passed", stdout)
    return int(match.group(1)) if match else -1


def _summary(stdout: str) -> str:
    for line in stdout.splitlines():
        if "passed" in line and "=====" in line:
            return line.strip()
    return stdout.strip().splitlines()[-1] if stdout.strip() else "???"


def run_side(kind: str) -> None:
    PROTOCOLS.mkdir(exist_ok=True)
    if kind == "target":
        cmd = [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider",
               "tests/api", "scripts/doclog8cert"]
        cwd = REPO_ROOT
    else:
        if WORKTREE.exists():
            subprocess.run(["git", "worktree", "remove", "--force",
                            str(WORKTREE)], cwd=REPO_ROOT,
                           capture_output=True)
        subprocess.run(["git", "worktree", "add", str(WORKTREE), "HEAD"],
                       cwd=REPO_ROOT, capture_output=True, check=True)
        cmd = [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider",
               "tests/api"]
        cwd = WORKTREE
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          timeout=900)
    payload = {
        "side": kind,
        "exit": proc.returncode,
        "summary": _summary(proc.stdout),
        "passed": _passed_count(proc.stdout),
        "failed_ids": _failed_ids(proc.stdout),
    }
    (PROTOCOLS / f"regress_{kind}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    (PROTOCOLS / f"regress_{kind}.txt").write_text(proc.stdout[-4000:],
                                                   "utf-8")
    print(kind, "->", payload["summary"],
          "| failed:", len(payload["failed_ids"]))
    if kind == "base":
        subprocess.run(["git", "worktree", "remove", "--force",
                        str(WORKTREE)], cwd=REPO_ROOT, capture_output=True)


def diff_sides() -> None:
    target = json.loads((PROTOCOLS / "regress_target.json").read_text())
    base = json.loads((PROTOCOLS / "regress_base.json").read_text())
    # passed мог быть не распарсен на прогоне -- пересчёт из сводки.
    if target["passed"] < 0:
        target["passed"] = _passed_count(target["summary"])
    if base["passed"] < 0:
        base["passed"] = _passed_count(base["summary"])
    (PROTOCOLS / "regress_target.json").write_text(
        json.dumps(target, ensure_ascii=False, indent=2), "utf-8")
    (PROTOCOLS / "regress_base.json").write_text(
        json.dumps(base, ensure_ascii=False, indent=2), "utf-8")
    t_ids, b_ids = set(target["failed_ids"]), set(base["failed_ids"])
    payload = {
        "target_summary": target["summary"],
        "base_summary": base["summary"],
        "target_failed": len(t_ids),
        "base_failed": len(b_ids),
        "byte_identical": t_ids == b_ids,
        "only_in_target": sorted(t_ids - b_ids),
        "only_in_base": sorted(b_ids - t_ids),
        "passed_delta": target["passed"] - base["passed"],
        "oracle_corpus_size": 78,
    }
    (PROTOCOLS / "regress_delta0.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({k: payload[k] for k in
                      ("target_summary", "base_summary", "byte_identical",
                       "passed_delta")}, ensure_ascii=False))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "diff"
    if mode in ("target", "base"):
        run_side(mode)
    else:
        diff_sides()
