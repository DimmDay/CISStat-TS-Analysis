#!/usr/bin/env python3
"""DOCLOG-5-CERT: полный регресс дельта-0.
Цель = рабочее дерево (ebbfa87 + корпус сертификатора, продуктовых
изменений НЕТ). База = 2caf08e (родитель DOCLOG-5, до поставки).
FAILED-ID множества обязаны совпасть байт-в-байт; +passed = ровно
прирост тестов tests/ между базами (61 doclog5 + пин-эволюция)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
BASE_SHA = "2caf08e"
WORKTREE = Path("/home/z/my-project/cert-base-2caf08e")
CERT_DIR = REPO / "scripts" / "doclog5cert"
PROTOCOLS = CERT_DIR / "protocols"


def run_full_pytest(cwd: Path, out_txt: Path) -> tuple[set[str], str]:
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest", "tests/",
            "-q", "--tb=no", "-p", "no:cacheprovider", "-rf",
        ],
        cwd=cwd, capture_output=True, text=True, timeout=590,
    )
    out_txt.write_text(result.stdout, encoding="utf-8")
    failed_ids = set(
        re.findall(r"FAILED (tests/\S+)", result.stdout)
    )
    tail_match = re.search(
        r"=+ (?:\d+ failed, )?(\d+) passed.*?=+", result.stdout
    )
    summary = tail_match.group(0) if tail_match else "?"
    return failed_ids, summary


def main() -> int:
    PROTOCOLS.mkdir(parents=True, exist_ok=True)
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("target", "all"):
        target_ids, target_summary = run_full_pytest(
            REPO, PROTOCOLS / "regress_target_full.txt"
        )
        (PROTOCOLS / "regress_target_ids.json").write_text(
            json.dumps(sorted(target_ids)), encoding="utf-8"
        )
        print("target:", target_summary)
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
        base_ids, base_summary = run_full_pytest(
            WORKTREE, PROTOCOLS / "regress_base_full.txt"
        )
        subprocess.run(
            ["git", "worktree", "remove", str(WORKTREE), "--force"],
            cwd=REPO, capture_output=True,
        )
        (PROTOCOLS / "regress_base_ids.json").write_text(
            json.dumps(sorted(base_ids)), encoding="utf-8"
        )
        print("base:", base_summary)
        if mode == "base":
            return 0
    target_ids = set(
        json.loads(
            (PROTOCOLS / "regress_target_ids.json").read_text()
        )
    )
    base_ids = set(
        json.loads((PROTOCOLS / "regress_base_ids.json").read_text())
    )
    only_target = sorted(target_ids - base_ids)
    only_base = sorted(base_ids - target_ids)
    report = {
        "target": "ebbfa87+cert (продукт = ebbfa87)",
        "base": BASE_SHA,
        "target_failed": len(target_ids),
        "base_failed": len(base_ids),
        "only_in_target": only_target,
        "only_in_base": only_base,
        "delta0_identical": target_ids == base_ids,
    }
    (PROTOCOLS / "regress_delta0.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if report["delta0_identical"] else 1


if __name__ == "__main__":
    sys.exit(main())
