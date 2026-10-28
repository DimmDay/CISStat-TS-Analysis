#!/usr/bin/env python3
# scripts/pgv01cert/run_campaign.py
#
# PGV-01-CERT — мутационная кампания «мутанты на своих мутантах» + MV-самопроверки.
#
# Каналы:
#   REPO   — repo jest printSchema.test.ts + repo pytest test_pgv01_print_schema.py
#            + doc-гвард scripts/pgv01/check_documents.py + doc-гвард pgv00;
#   ORACLE — Класс A корпуса сертификатора (static + parity; Класс B/F-кейсы
#            исключены, чтобы фикс-эффект не засчитывался как «kill»).
#
# Протокол: каждый мутант применяется к единственному якорю, каналы гоняются,
# файл восстанавливается байт-честно (md5 == HEAD). Исход сверяется с
# прегистрированным ожиданием. MV-самопроверки:
#   MV1 — dry-run: якоря уникальны, замены не no-op;
#   MV2 — самопроверка силы компаратора: полная сила (multiset code+path)
#         ловит декой F2a, ослабленная (только коды) — ПРОПУСКАЕТ (декой
#         выживает под ослабленным оракулом) — «мутанты на своих мутантах»;
#   MV3 — байт-честность восстановления после каждого мутанта и в конце;
#   MV4 — контроли ALIVE в обоих каналах;
#   MV5 — атрибуция: исход каждого мутанта совпал с прегистрированным,
#         чужих киллов/выживаний нет.
#
# Запуск: python3 scripts/pgv01cert/run_campaign.py   (из корня репозитория)

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

CERT_DIR = Path(__file__).resolve().parent
REPO = CERT_DIR.parents[1]
PROTOCOLS = CERT_DIR / "protocols"
sys.path.insert(0, str(CERT_DIR))

import mutations  # noqa: E402
import p1cases  # noqa: E402
import p1harness  # noqa: E402

FINDINGS_IDS = {"F1a", "F1b", "F1c", "F1d", "F2a", "F2b", "F2c"}


def _run(cmd: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True, timeout=timeout)


def repo_channel() -> bool:
    """REPO-канал: GREEN, если все четыре repo-проверки зелёны."""
    steps = [
        ["npx", "jest", "packages/ui/print/printSchema.test.ts"],
        [sys.executable, "-m", "pytest", "tests/api/test_pgv01_print_schema.py", "-q"],
        [sys.executable, "scripts/pgv01/check_documents.py"],
        [sys.executable, "scripts/pgv00/check_documents.py"],
    ]
    return all(_run(step).returncode == 0 for step in steps)


def oracle_channel() -> bool:
    """ORACLE-канал: Класс A корпуса (без Класса B — findings)."""
    proc = _run(
        [sys.executable, "-m", "pytest", "scripts/pgv01cert/", "-q", "-k", "not findings_evidence"]
    )
    return proc.returncode == 0


def file_digest(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def mv2_comparator_power() -> dict:
    """Мутанты на своих мутантах: декой под полной и ослабленной силой."""
    cases = {case["id"]: case for case in p1cases.cases()}
    decoy = cases["F2a"]  # page_order_gap ×N: код один, счётчик и путь различают
    # Истинные исходы каналов на сертифицируемом дереве:
    ts_outcomes = p1harness.run_ts_channel()["F2a"]
    py_outcomes = p1harness.python_outcomes(decoy)
    full = p1harness.compare_channels(ts_outcomes, py_outcomes)
    weakened = p1harness.compare_channels(ts_outcomes, py_outcomes, weakened=True)
    return {
        "decoy": "F2a",
        "full_detects": not full["equal"],          # полная сила ЛОВИТ расхождение
        "weakened_passes": weakened["equal"],       # ослабленная ПРОПУСКАЕТ (декой выживает)
        "ts": ts_outcomes,
        "py": py_outcomes,
    }


def main() -> int:
    PROTOCOLS.mkdir(exist_ok=True)
    report: dict = {"mv": {}, "results": [], "summary": {}}
    ok = True

    # ── MV1: dry-run якорей ─────────────────────────────────────────
    mv1_problems = []
    originals: dict[str, bytes] = {}
    digests_before: dict[str, str] = {}
    for mutant in mutations.MUTANTS:
        path = REPO / mutant.file
        originals.setdefault(mutant.file, path.read_bytes())
        digests_before[mutant.file] = file_digest(path)
        text = originals[mutant.file].decode("utf-8")
        if text.count(mutant.anchor) != 1:
            mv1_problems.append(f"{mutant.mid}: anchor count {text.count(mutant.anchor)}")
        if mutant.anchor == mutant.replacement:
            mv1_problems.append(f"{mutant.mid}: no-op replacement")
    report["mv"]["MV1_anchors_unique"] = not mv1_problems
    ok &= not mv1_problems
    print(f"MV1 anchors unique & non-noop: {'OK' if not mv1_problems else mv1_problems}")

    # ── MV2: сила компаратора (декой выживает под ослабленной силой) ─
    mv2 = mv2_comparator_power()
    mv2_ok = mv2["full_detects"] and mv2["weakened_passes"]
    report["mv"]["MV2_comparator_power"] = mv2
    ok &= mv2_ok
    print(f"MV2 mutants-on-my-mutants (decoy F2a): full_detects={mv2['full_detects']} "
          f"weakened_passes={mv2['weakened_passes']} → {'OK' if mv2_ok else 'FAIL'}")

    # ── Кампания ────────────────────────────────────────────────────
    for mutant in mutations.MUTANTS:
        path = REPO / mutant.file
        original = originals[mutant.file]
        path.write_bytes(path.read_bytes().replace(mutant.anchor.encode("utf-8"), mutant.replacement.encode("utf-8")))
        applied = mutant.replacement.encode("utf-8") in path.read_bytes()
        try:
            repo_killed = not repo_channel()
            oracle_killed = not oracle_channel()
        finally:
            path.write_bytes(original)  # MV3: байт-честное восстановление
        restored = file_digest(path) == digests_before[mutant.file]
        actual = {"REPO": "KILL" if repo_killed else "ALIVE", "ORACLE": "KILL" if oracle_killed else "ALIVE"}
        matched = applied and restored and actual == mutant.expected
        ok &= matched
        row = {
            "id": mutant.mid,
            "class": mutant.klass,
            "file": mutant.file,
            "applied": applied,
            "restored_md5": restored,
            "actual": actual,
            "expected": mutant.expected,
            "matched": matched,
            "note": mutant.note,
        }
        report["results"].append(row)
        marker = "OK" if matched else "MISMATCH"
        print(f"[{marker}] {mutant.mid} ({mutant.klass}): REPO={actual['REPO']} ORACLE={actual['ORACLE']} "
              f"expected REPO={mutant.expected['REPO']} ORACLE={mutant.expected['ORACLE']} — {mutant.note}")

    # ── MV3/MV4/MV5: агрегаты ───────────────────────────────────────
    all_restored = all(row["restored_md5"] for row in report["results"])
    controls = [row for row in report["results"] if row["class"] == "CONTROL"]
    controls_alive = all(row["actual"] == {"REPO": "ALIVE", "ORACLE": "ALIVE"} for row in controls)
    attribution = all(row["matched"] for row in report["results"])
    kills = {
        "DUAL": sum(1 for r in report["results"] if r["class"] == "DUAL"
                    and r["actual"] == {"REPO": "KILL", "ORACLE": "KILL"}),
        "ORACLE_ONLY": sum(1 for r in report["results"] if r["class"] == "ORACLE-ONLY"
                           and r["actual"] == {"REPO": "ALIVE", "ORACLE": "KILL"}),
        "CONTROL_ALIVE": sum(1 for r in report["results"] if r["class"] == "CONTROL"
                             and r["actual"] == {"REPO": "ALIVE", "ORACLE": "ALIVE"}),
    }
    report["mv"]["MV3_restoration_md5"] = all_restored
    report["mv"]["MV4_controls_alive"] = controls_alive
    report["mv"]["MV5_attribution_exact"] = attribution
    report["summary"] = {
        "mutants_total": len(mutations.MUTANTS),
        "battle": len(mutations.MUTANTS) - len(controls),
        "kills": kills,
        "unexpected": [r["id"] for r in report["results"] if not r["matched"]],
    }
    ok &= all_restored and controls_alive and attribution
    print(f"MV3 restoration byte-exact: {all_restored}")
    print(f"MV4 controls ALIVE {len(controls)}/{len(controls)}: {controls_alive}")
    print(f"MV5 attribution exact: {attribution}")
    print(f"Kills: {kills}")

    (PROTOCOLS / "campaign_results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Protocol: {PROTOCOLS / 'campaign_results.json'}")
    if not ok:
        print("CAMPAIGN: MISMATCH — см. протокол")
        return 1
    print("CAMPAIGN: все исходы совпали с прегистрированными ожиданиями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
