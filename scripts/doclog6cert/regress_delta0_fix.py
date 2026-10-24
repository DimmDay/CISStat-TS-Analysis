#!/usr/bin/env python3
"""DOCLOG-6-CERT-FIX: полный регресс дельта-0 для исправления F-D6C1.

Сплит-режим (прецедент regress_delta0.py: песочница убивает фоновые
процессы -- полный tests/ делится на две части A/B, обе стороны
прогоняются одинаково).

Цель = рабочее дерево (c9b87a1 + ФИКС F-D6C1: apps/api/
document_lifecycle.py diff_revisions, пин направления в
tests/api/test_doclog6_approvals_archive.py). База = c9b87a1
(сертифицированное состояние DOCLOG-6-CERT, инвертированная
семантика diff) в git-worktree.

Ожидание: FAILED-ID множества каждой части совпадают байт-в-байт;
+passed = ровно +1 (новый пин test_diff_direction_natural_semantics,
зелёный в цели). Исторические протоколы кампании DOCLOG-6-CERT
(regress_*.{txt,json}) НЕ перезаписываются -- фикс пишет протоколы
с префиксом regress_fix_*.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
BASE_SHA = "c9b87a1"
WORKTREE = Path("/home/z/my-project/cert6fix-base")
CERT_DIR = REPO / "scripts" / "doclog6cert"
PROTOCOLS = CERT_DIR / "protocols"

PARTS = {
    "A": ["tests/api", "tests/integration"],
    "B": ["--ignore=tests/api", "--ignore=tests/integration", "tests/"],
}


def failed_ids(stdout: str) -> set[str]:
    return set(re.findall(r"FAILED (tests/\S+)", stdout))


def passed_count(stdout: str) -> int | None:
    m = re.search(r"=+ (?:\d+ failed, )?(\d+) passed", stdout)
    return int(m.group(1)) if m else None


def run_part(cwd: Path, part: str, out_txt: Path) -> tuple[set[str], str]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *PARTS[part],
         "-q", "--tb=no", "-p", "no:cacheprovider", "-rf"],
        cwd=cwd, capture_output=True, text=True, timeout=590,
    )
    out_txt.write_text(result.stdout, encoding="utf-8")
    ids = failed_ids(result.stdout)
    tail_match = re.search(
        r"=+ (?:\d+ failed, )?(\d+) passed.*?=+", result.stdout
    )
    summary = tail_match.group(0) if tail_match else "?"
    return ids, summary


def main() -> int:
    PROTOCOLS.mkdir(parents=True, exist_ok=True)
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    part_arg = sys.argv[2] if len(sys.argv) > 2 else None
    # Посекционные режимы (песочница убивает фоновые процессы; один
    # bash-вызов <= 600s): "target A", "target B", "base A", "base B",
    # "adjudicate".
    if mode in ("target", "base") and part_arg in ("A", "B"):
        cwd = REPO if mode == "target" else None
        if mode == "base":
            subprocess.run(
                ["git", "worktree", "remove", str(WORKTREE), "--force"],
                cwd=REPO, capture_output=True,
            )
            subprocess.run(
                ["git", "worktree", "add", str(WORKTREE), BASE_SHA],
                cwd=REPO, check=True, capture_output=True,
            )
            cwd = WORKTREE
        ids, summary = run_part(
            cwd, part_arg,
            PROTOCOLS / f"regress_fix_{mode}_{part_arg}.txt",
        )
        (PROTOCOLS / f"regress_fix_{mode}_ids_{part_arg}.json").write_text(
            json.dumps(sorted(ids)), encoding="utf-8"
        )
        print(f"{mode}[{part_arg}]:", summary, flush=True)
        if mode == "base":
            subprocess.run(
                ["git", "worktree", "remove", str(WORKTREE), "--force"],
                cwd=REPO, capture_output=True,
            )
        return 0
    if mode == "adjudicate":
        mode = "report"
    if mode in ("target", "all"):
        for part in ("A", "B"):
            ids, summary = run_part(
                REPO, part, PROTOCOLS / f"regress_fix_target_{part}.txt"
            )
            (PROTOCOLS / f"regress_fix_target_ids_{part}.json").write_text(
                json.dumps(sorted(ids)), encoding="utf-8"
            )
            print(f"target[{part}]:", summary, flush=True)
        if mode == "target":
            return 0
    if mode in ("base", "all"):
        subprocess.run(
            ["git", "worktree", "remove", str(WORKTREE), "--force"],
            cwd=REPO, capture_output=True,
        )
        subprocess.run(
            ["git", "worktree", "add", str(WORKTREE), BASE_SHA],
            cwd=REPO, check=True, capture_output=True,
        )
        for part in ("A", "B"):
            ids, summary = run_part(
                WORKTREE, part, PROTOCOLS / f"regress_fix_base_{part}.txt"
            )
            (PROTOCOLS / f"regress_fix_base_ids_{part}.json").write_text(
                json.dumps(sorted(ids)), encoding="utf-8"
            )
            print(f"base[{part}]:", summary, flush=True)
        subprocess.run(
            ["git", "worktree", "remove", str(WORKTREE), "--force"],
            cwd=REPO, capture_output=True,
        )
        if mode == "base":
            return 0
    report: dict = {
        "target": "c9b87a1 + DOCLOG-6-CERT-FIX (F-D6C1)",
        "base": BASE_SHA,
    }
    ok = True
    for part in ("A", "B"):
        target_ids = set(
            json.loads(
                (PROTOCOLS / f"regress_fix_target_ids_{part}.json").read_text()
            )
        )
        base_ids = set(
            json.loads(
                (PROTOCOLS / f"regress_fix_base_ids_{part}.json").read_text()
            )
        )
        only_target = sorted(target_ids - base_ids)
        only_base = sorted(base_ids - target_ids)
        part_ok = target_ids == base_ids
        ok = ok and part_ok
        report[f"part_{part}"] = {
            "target_failed": len(target_ids),
            "base_failed": len(base_ids),
            "only_in_target": only_target,
            "only_in_base": only_base,
            "delta0_identical": part_ok,
        }
    (PROTOCOLS / "regress_fix_delta0.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=1))
    print("DELTA-0:", "OK" if ok else "BROKEN")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
