#!/usr/bin/env python3
"""DOCLOG-7-CERT: полный регресс tests/api дельта-0.

Схема (прецедент DOCLOG-6-CERT):
  TARGET = HEAD (3634052) + корпус сертификатора (scripts/doclog7cert)
  BASE   = чистый git-worktree HEAD (3634052)

Критерий: множества FAILED-ID байт-идентичны; +passed == ровно корпус
сертификатора (73). Все падения -- предсуществующие средовые классы.

Resume: протоколы regress_target.json / regress_base.json не
пересчитываются.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/z/CISStat-TS-Analysis")
BASE_WT = Path("/home/z/wt-d7-base")
PROTOCOLS = REPO / "scripts" / "doclog7cert" / "protocols"


def failed_ids(output: str) -> set[str]:
    r'Только тест-ID (\S+ до пробела) из строк FAILED/ERROR summary.'
    ids: set[str] = set()
    for line in output.splitlines():
        m = re.match(r"^(?:FAILED|ERROR) (\S+)", line.strip())
        if m:
            ids.add(m.group(1))
    return ids


def counts(output: str) -> tuple[int, int, int]:
    m = re.search(
        r"(?:(\d+) failed)?(?:, )?(?:(\d+) passed)?(?:, )?(\d+)? ?(?:warnings)?"
        r"(?:, )? ?(\d+)? ?skipped", output)
    # надёжнее: парсим итоговую строку вида "31 failed, 2696 passed, 42 skipped"
    m2 = re.search(r"=+ (.+?) in [\d\.]+s", output)
    failed = passed = skipped = 0
    if m2:
        summary = m2.group(1)
        fm = re.search(r"(\d+) failed", summary)
        pm = re.search(r"(\d+) passed", summary)
        sm = re.search(r"(\d+) skipped", summary)
        failed = int(fm.group(1)) if fm else 0
        passed = int(pm.group(1)) if pm else 0
        skipped = int(sm.group(1)) if sm else 0
    return failed, passed, skipped


def run_full(cwd: Path, out_name: str) -> dict:
    protocol_file = PROTOCOLS / out_name
    if protocol_file.exists():
        return json.loads(protocol_file.read_text(encoding="utf-8"))
    cmd = [
        sys.executable, "-m", "pytest", "tests/api",
        "-q", "--tb=no", "-p", "no:cacheprovider", "--no-header", "-x",
        "--co" ,  # НЕ собираем заранее; полный прогон ниже
    ]
    # полный прогон; TARGET дополнительно включает корпус сертификатора
    paths = ["tests/api"]
    if (cwd / "scripts" / "doclog7cert").exists():
        paths.append("scripts/doclog7cert")
    cmd = [
        sys.executable, "-m", "pytest", *paths,
        "-q", "--tb=line", "-p", "no:cacheprovider", "--no-header",
    ]
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                            timeout=900)
    output = result.stdout + "\n" + result.stderr
    failed, passed, skipped = counts(output)
    entry = {
        "cwd": str(cwd),
        "returncode": result.returncode,
        "failed": failed,
        "passed": passed,
        "skipped": skipped,
        "failed_ids": sorted(failed_ids(output)),
        "tail": "\n".join(output.strip().splitlines()[-12:]),
    }
    protocol_file.write_text(json.dumps(entry, ensure_ascii=False, indent=1),
                             encoding="utf-8")
    return entry


def main() -> int:
    PROTOCOLS.mkdir(parents=True, exist_ok=True)
    target = run_full(REPO, "regress_target.json")
    print("TARGET:", target["failed"], "F /", target["passed"], "P /",
          target["skipped"], "S", flush=True)
    base = run_full(BASE_WT, "regress_base.json")
    print("BASE:  ", base["failed"], "F /", base["passed"], "P /",
          base["skipped"], "S", flush=True)
    t_ids = set(target["failed_ids"])
    b_ids = set(base["failed_ids"])
    delta_passed = target["passed"] - base["passed"]
    verdict = {
        "failed_sets_identical": t_ids == b_ids,
        "failed_count": len(t_ids),
        "only_in_target": sorted(t_ids - b_ids),
        "only_in_base": sorted(b_ids - t_ids),
        "passed_delta": delta_passed,
        "expected_corpus": 73,
        "passed_delta_ok": delta_passed == 73,  # TARGET включает корпус
    }
    (PROTOCOLS / "regress_delta0.json").write_text(
        json.dumps(verdict, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(verdict, ensure_ascii=False, indent=1))
    return 0 if (verdict["failed_sets_identical"] and verdict["passed_delta_ok"]) else 1


if __name__ == "__main__":
    sys.exit(main())
