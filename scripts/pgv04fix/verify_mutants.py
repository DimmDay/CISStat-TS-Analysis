#!/usr/bin/env python3
# scripts/pgv04fix/verify_mutants.py
"""PGV-04-FIX: адресная ремутация на своих мутантах (прецедент и
протокол scripts/pgv04cert/run_mutation_campaign.py, акт
docs/cert_pgv04_2026-10-29.md §6/§8).

Обязательство акта: боевой мутант M01 (drop panel-списка backfill'а)
SURVIVED на родителе c4e90b8 ПО ОПРЕДЕЛЕНИЮ (Class B вне каналов
кампании); после PGV-04-FIX обязан быть убит. Здесь -- три боевых
мутанта над ИСПРАВЛЕННЫМ кодом + один нейтральный контроль:

  M01FIX -- drop panel-списка из ИСПРАВЛЕННОЙ строки
            (panel_entry_checkpoints): обязан убиваться repo-каналом
            (новый панельный backfill-тест test_pgv04_passport_
            checkpoints.py) и Class B (B1-B3); ORACLE-канал (Class A --
            оракулы родителя, не расширялись) панельный backfill не
            покрывает -- честная граница.
  M02FIX -- per-entry изоляция убрана (generic-сбой ре-рейзится из
            backfill-цикла): обязан убиваться repo-каналом
            (test_backfill_per_entry_isolation_with_failed_counter) и
            Class B (B4/B5).
  M03FIX -- durable-receipt сбойной записи убран (per-entry сбой
            проглатывается без receipt): обязан убиваться Class B
            (B5 -- receipt-оракул; урок N-P4C5: фильтр по ФАКТИЧЕСКОЙ
            структуре записи -- operation в details, producer_key в
            resource_id).
  KFIX01 -- нейтральный контроль (комментарий): обязан SURVIVED
            (честность харнесса: канал не ловит не-поведенческие
            замены).

Протокол MV (паритет кампании):
  MV0 -- базовые прогоны каналов без мутантов (все GREEN);
  MV1 -- все замены уникальны (count==1, иначе APPLY-FAIL);
  MV2 -- md5 файла восстановлен после каждого мутанта;
  MV3 -- финал: md5 всех файлов == HEAD.

Каналы: REPO = tests/api/test_pgv04_passport_checkpoints.py (корпус
поставки), ORACLE = tests/api/test_pgv04_cert_oracles.py (Class A,
документные пины deselected как в кампании), CLASS_B =
tests/api/test_pgv04_cert_findings.py (Class B -- RED-свидетельства,
ставшие GREEN; в кампании акта не участвовал, здесь -- независимый
третий канал доказательства убийства).

Запуск: python3 scripts/pgv04fix/verify_mutants.py
Вывод: scripts/pgv04fix/protocols/fix_mutation_report.json + stdout.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

MODULE = REPO / "apps/api/passport_checkpoints.py"

REPO_SUITE = "tests/api/test_pgv04_passport_checkpoints.py"
ORACLE_SUITE = "tests/api/test_pgv04_cert_oracles.py"
CLASS_B_SUITE = "tests/api/test_pgv04_cert_findings.py"
ORACLE_DESELECT = [
    "tests/api/test_pgv04_cert_oracles.py::TestStaticPins::test_cert_document_exists_with_verdict",
    "tests/api/test_pgv04_cert_oracles.py::TestStaticPins::test_worklog_entry_present",
]

# ── Мутанты фикса (над ИСПРАВЛЕННЫМ кодом) ───────────────────────────

MUTANTS: list[dict] = [
    dict(
        id="M01FIX",
        desc="drop panel-списка backfill'а (эквивалент M01 акта на исправленной строке)",
        old=(
            '    ) + list(getattr(session, "panel_entry_checkpoints", None) or [])'
        ),
        new="    )  # P4FIXMUT01: panel list dropped",
    ),
    dict(
        id="M02FIX",
        desc="per-entry изоляция убрана: generic-сбой ре-рейзится (поведение до фикса)",
        old=(
            "            _record_backfill_entry_failure(\n"
            "                run_id, subject, session_id, checkpoint, exc\n"
            "            )\n"
            '            counts["failed"] = counts.get("failed", 0) + 1'
        ),
        new="            raise  # P4FIXMUT02: per-entry isolation removed",
    ),
    dict(
        id="M03FIX",
        desc="durable-receipt сбойной записи убран (сбой глотается молча)",
        old=(
            "    try:\n"
            "        from apps.api.promotion_integration import _record_failure"
        ),
        new=(
            "    if True:  # P4FIXMUT03: receipt removed\n"
            "        return\n"
            "    try:\n"
            "        from apps.api.promotion_integration import _record_failure"
        ),
    ),
    dict(
        id="KFIX01",
        desc="контроль: нейтральный комментарий (обязан SURVIVED)",
        old=(
            "# F-P4C1: панельные чекпоинты -- РЕАЛЬНОЕ поле session-контура"
        ),
        new=(
            "# F-P4C1: панельные чекпоинты -- РЕАЛЬНОЕ поле session-контура\n"
            "# P4FIXCTRL01 (нейтральный комментарий)"
        ),
    ),
]


def md5_of(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def apply_mutant(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"MV1 RESTORE-GUARD: замена не уникальна (count={count}): {old[:70]!r}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


def run_channels(tmpdir: Path) -> dict[str, list[str]]:
    """Один pytest-процесс на три канала; парсинг junitxml по файлам."""
    junit = tmpdir / "report.xml"
    cmd = [
        sys.executable, "-m", "pytest",
        REPO_SUITE, ORACLE_SUITE, CLASS_B_SUITE,
        "-q", "--tb=no", "--disable-warnings", "-p", "no:cacheprovider",
        f"--junitxml={junit}",
    ]
    for node in ORACLE_DESELECT:
        cmd += ["--deselect", node]
    subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=900)
    failed: dict[str, list[str]] = {"repo": [], "oracle": [], "class_b": []}
    root = ET.parse(junit).getroot()
    for case in root.iter("testcase"):
        classname = case.get("classname", "")
        failure = case.find("failure")
        if failure is None:
            continue
        if "test_pgv04_passport_checkpoints" in classname:
            failed["repo"].append(case.get("name", ""))
        elif "test_pgv04_cert_oracles" in classname:
            failed["oracle"].append(case.get("name", ""))
        elif "test_pgv04_cert_findings" in classname:
            failed["class_b"].append(case.get("name", ""))
    return failed


def main() -> int:
    tmpdir = Path(tempfile.mkdtemp(prefix="p4fix-mut-"))
    original = MODULE.read_text(encoding="utf-8")
    baseline_md5 = md5_of(MODULE)

    # MV0: базовые прогоны каналов без мутантов
    base = run_channels(tmpdir)
    report: dict = {
        "campaign": "PGV-04-FIX targeted re-mutation (на своих мутантах)",
        "parent": "ad597cb (PGV-04-CERT)",
        "module": "apps/api/passport_checkpoints.py",
        "repo_suite": REPO_SUITE,
        "oracle_suite": ORACLE_SUITE,
        "class_b_suite": CLASS_B_SUITE,
        "oracle_deselected_static_doc_pins": ORACLE_DESELECT,
        "mv0_baseline": {
            "repo_failed": base["repo"],
            "oracle_failed": base["oracle"],
            "class_b_failed": base["class_b"],
            "ok": not base["repo"] and not base["oracle"] and not base["class_b"],
        },
        "mutants": [],
    }

    for mutant in MUTANTS:
        mid = mutant["id"]
        entry: dict = {"id": mid, "desc": mutant["desc"]}
        try:
            apply_mutant(MODULE, mutant["old"], mutant["new"])
            entry["mv1_unique_replacement"] = True
        except RuntimeError as exc:
            entry["mv1_unique_replacement"] = False
            entry["error"] = str(exc)
            entry["verdict"] = "APPLY-FAIL"
            report["mutants"].append(entry)
            continue
        try:
            failed = run_channels(tmpdir)
            repo_killed = bool(failed["repo"])
            oracle_killed = bool(failed["oracle"])
            class_b_killed = bool(failed["class_b"])
            if repo_killed and oracle_killed:
                verdict = "DUAL-KILLED"
            elif oracle_killed:
                verdict = "ORACLE-ONLY"
            elif repo_killed:
                verdict = "REPO-KILLED"
            elif class_b_killed:
                verdict = "CLASS-B-KILLED"
            else:
                verdict = "SURVIVED"
            entry.update({
                "repo_failed_n": len(failed["repo"]),
                "oracle_failed_n": len(failed["oracle"]),
                "class_b_failed_n": len(failed["class_b"]),
                "repo_failed_ids": failed["repo"][:6],
                "oracle_failed_ids": failed["oracle"][:6],
                "class_b_failed_ids": failed["class_b"][:6],
                "class_b_killed": class_b_killed,
                "verdict": verdict,
            })
        except subprocess.TimeoutExpired:
            entry["verdict"] = "TIMEOUT"
        finally:
            # MV2: восстановление после каждого мутанта
            MODULE.write_text(original, encoding="utf-8")
            if md5_of(MODULE) != baseline_md5:
                entry["mv2_restore"] = False
                entry["verdict"] = "RESTORE-FAIL"
            else:
                entry["mv2_restore"] = True
        report["mutants"].append(entry)

    # MV3: финал -- файл == исходный
    report["mv3_final_md5_ok"] = md5_of(MODULE) == baseline_md5

    killed = [
        m["id"] for m in report["mutants"]
        if m.get("verdict")
        in ("DUAL-KILLED", "REPO-KILLED", "ORACLE-ONLY", "CLASS-B-KILLED")
        and m["id"] != "KFIX01"
    ]
    report["summary"] = {
        "battle_killed": killed,
        "battle_survived": [
            m["id"] for m in report["mutants"]
            if m.get("verdict") == "SURVIVED" and m["id"] != "KFIX01"
        ],
        "control": {
            "id": "KFIX01",
            "expected": "SURVIVED",
            "actual": next(
                (
                    m.get("verdict")
                    for m in report["mutants"]
                    if m["id"] == "KFIX01"
                ),
                "ABSENT",
            ),
        },
        "obligation_M01_ac": killed,  # обязательство акта: M01-эквивалент убит
    }

    out_dir = Path(__file__).resolve().parent / "protocols"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "fix_mutation_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report["mv0_baseline"], ensure_ascii=False))
    for m in report["mutants"]:
        print(
            f"{m['id']}: {m.get('verdict')} "
            f"(repo={m.get('repo_failed_n')}, oracle={m.get('oracle_failed_n')}, "
            f"class_b={m.get('class_b_failed_n')}, mv2={m.get('mv2_restore')})"
        )
    print(f"MV3 final md5 ok: {report['mv3_final_md5_ok']}")
    print(f"Report: {out}")

    ok = (
        report["mv0_baseline"]["ok"]
        and report["mv3_final_md5_ok"]
        and not report["summary"]["battle_survived"]
        and report["summary"]["control"]["actual"] == "SURVIVED"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
