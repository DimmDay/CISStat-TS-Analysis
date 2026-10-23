#!/usr/bin/env python3
"""DOCLOG-6-CERT: полный регресс дельта-0 (сплит-режим: песочница
убивает фоновые процессы -- полный tests/ делится на две части A/B,
обе стороны прогоняются одинаково).

Цель = рабочее дерево (70c9c1a + корпус сертификатора, продуктовых
изменений НЕТ). База = e573ff3 (родитель DOCLOG-6, до поставки) в
git-worktree. FAILED-ID множества каждой части обязаны совпасть
байт-в-байт; +passed = ровно прирост тестов между базами."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
BASE_SHA = "e573ff3"
WORKTREE = Path("/home/z/my-project/cert6-base")
CERT_DIR = REPO / "scripts" / "doclog6cert"
PROTOCOLS = CERT_DIR / "protocols"

PARTS = {
    "A": ["tests/api", "tests/integration"],
    "B": ["--ignore=tests/api", "--ignore=tests/integration", "tests/"],
}


def failed_ids(stdout: str) -> set[str]:
    return set(re.findall(r"FAILED (tests/\S+)", stdout))


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
    if mode in ("target", "all"):
        for part in ("A", "B"):
            ids, summary = run_part(
                REPO, part, PROTOCOLS / f"regress_target_{part}.txt"
            )
            (PROTOCOLS / f"regress_target_ids_{part}.json").write_text(
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
                WORKTREE, part, PROTOCOLS / f"regress_base_{part}.txt"
            )
            (PROTOCOLS / f"regress_base_ids_{part}.json").write_text(
                json.dumps(sorted(ids)), encoding="utf-8"
            )
            print(f"base[{part}]:", summary, flush=True)
        subprocess.run(
            ["git", "worktree", "remove", str(WORKTREE), "--force"],
            cwd=REPO, capture_output=True,
        )
        if mode == "base":
            return 0
    report: dict = {"target": "70c9c1a+cert (продукт = 70c9c1a)", "base": BASE_SHA}
    ok = True
    for part in ("A", "B"):
        target_ids = set(
            json.loads(
                (PROTOCOLS / f"regress_target_ids_{part}.json").read_text()
            )
        )
        base_ids = set(
            json.loads(
                (PROTOCOLS / f"regress_base_ids_{part}.json").read_text()
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
    (PROTOCOLS / "regress_delta0.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
