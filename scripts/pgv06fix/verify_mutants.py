#!/usr/bin/env python3
# scripts/pgv06fix/verify_mutants.py
"""PGV-06-FIX: адресная ремутация на своих мутантах (прецедент
scripts/pgv04fix/verify_mutants.py и кампания PGV-06-CERT
scripts/pgv06cert/run_mutation_campaign.py; акт
docs/cert_pgv06_2026-10-29.md, находка F-P6C1).

Обязательство акта PGV-06-CERT: Class B B1 (F-P6C1 -- дисклоужение
существования чужой rs-записи через различающие detail-строки
trajectory-гэпов) RED до фикса, GREEN после -- БЕЗ ослабления смысла.
Здесь -- пять боевых мутантов над ИСПРАВЛЕННЫМ кодом
(apps/api/passport_comparison.py) + один нейтральный контроль:

  FM1 -- нормализация убрана (reader-гэпы пробрасываются AS-IS,
         поведение до фикса): обязан убиваться REPO-каналом
         (новые пины поставки uniform-detail) и CLASS_B (B1);
         ORACLE-канал (Class A акта) trajectory-гэпы чужих refs
         не покрывает -- честная граница (поэтому пины добавлены
         в корпус поставки).
  FM2 -- частичная нормализация: только позиции stage_refs
         (подтверждённый ref и previous остаются с reader-деталью):
         обязан убиваться REPO-каналом (пин по осям snapshot_ref /
         previous_snapshot_ref); B1 при этом GREEN -- ось stage_refs
         у него закрыта, классификация честная.
  FM3 -- сверх-нормализация: content-гэпы тоже получают uniform-
         строку (диагностика порчи потеряна, AC12): обязан убиваться
         REPO-каналом (пин «content-гэп не нормализуется»).
  FM4 -- нормализация огрубляет АДРЕС дыры (at := "trajectory"):
         обязан убиваться REPO-каналом (пины адреса at/snapshot_ref).
  FM5 -- хрупкая строковая нормализация (по подстроке «не принадлежит»
         вместо reason): absent-гэп остаётся с reader-деталью --
         обязан убиваться REPO-каналом и CLASS_B (дифференциалы).
  KFIX01 -- нейтральный контроль (комментарий): обязан SURVIVED
         (честность харнесса: канал не ловит не-поведенческие замены).

Протокол MV (паритет кампании PGV-04-FIX):
  MV0 -- базовые прогоны каналов без мутантов (все GREEN);
  MV1 -- все замены уникальны (count==1, иначе APPLY-FAIL);
  MV2 -- md5 файла восстановлен после каждого мутанта;
  MV3 -- финал: md5 файла == исходному.

Каналы: REPO = tests/api/test_pgv06_passport_comparison.py (корпус
поставки, 34 теста -- с пинами фикса), ORACLE =
tests/api/test_pgv06_cert_oracles.py (Class A акта, 28), CLASS_B =
tests/api/test_pgv06_cert_findings.py (B1 -- RED-свидетельство,
ставшее GREEN; независимый третий канал доказательства убийства).

Запуск: python3 scripts/pgv06fix/verify_mutants.py
Вывод: scripts/pgv06fix/protocols/fix_mutation_report.json + stdout.
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

MODULE = REPO / "apps/api/passport_comparison.py"

REPO_SUITE = "tests/api/test_pgv06_passport_comparison.py"
ORACLE_SUITE = "tests/api/test_pgv06_cert_oracles.py"
CLASS_B_SUITE = "tests/api/test_pgv06_cert_findings.py"

# ── Мутанты фикса (над ИСПРАВЛЕННЫМ кодом) ───────────────────────────

NORM_LOOP = (
    "    gaps: list[dict[str, Any]] = []\n"
    "    for raw_gap in trajectory.get(\"gaps\") or []:\n"
    "        gap = dict(raw_gap)\n"
    "        if gap.get(\"reason\") == \"missing_snapshot_record\":\n"
    "            gap[\"detail\"] = _UNIFORM_MISSING_RECORD_DETAIL\n"
    "        gaps.append(gap)\n"
)

MUTANTS: list[dict] = [
    dict(
        id="FM1",
        desc="нормализация убрана: reader-гэпы AS-IS (поведение до фикса)",
        old=NORM_LOOP,
        new=(
            "    gaps: list[dict[str, Any]] = [\n"
            "        dict(gap) for gap in (trajectory.get(\"gaps\") or [])\n"
            "    ]  # P6FIXMUT01: normalization removed\n"
        ),
    ),
    dict(
        id="FM2",
        desc="частичная нормализация: только stage_refs-позиции "
             "(snapshot_ref/previous_snapshot_ref -- с reader-деталью)",
        old=(
            "        if gap.get(\"reason\") == \"missing_snapshot_record\":\n"
            "            gap[\"detail\"] = _UNIFORM_MISSING_RECORD_DETAIL\n"
        ),
        new=(
            "        if gap.get(\"reason\") == \"missing_snapshot_record\" "
            "and str(gap.get(\"at\", \"\")).startswith(\"stage_refs\"):\n"
            "            gap[\"detail\"] = _UNIFORM_MISSING_RECORD_DETAIL\n"
            "        # P6FIXMUT02: partial scope\n"
        ),
    ),
    dict(
        id="FM3",
        desc="сверх-нормализация: content-гэпы получают uniform-строку "
             "(диагностика порчи потеряна, AC12)",
        old='        "detail": record.get("content_gap_reason") or str(status),',
        new=(
            "        \"detail\": _UNIFORM_MISSING_RECORD_DETAIL,  "
            "# P6FIXMUT03: content diagnostics lost\n"
        ),
    ),
    dict(
        id="FM4",
        desc="нормализация огрубляет адрес дыры (at := trajectory)",
        old=(
            "        if gap.get(\"reason\") == \"missing_snapshot_record\":\n"
            "            gap[\"detail\"] = _UNIFORM_MISSING_RECORD_DETAIL\n"
        ),
        new=(
            "        if gap.get(\"reason\") == \"missing_snapshot_record\":\n"
            "            gap[\"detail\"] = _UNIFORM_MISSING_RECORD_DETAIL\n"
            "            gap[\"at\"] = \"trajectory\"  # P6FIXMUT04\n"
        ),
    ),
    dict(
        id="FM5",
        desc="хрупкая строковая нормализация (по подстроке, не по reason): "
             "absent-гэп остаётся с reader-деталью",
        old='        if gap.get("reason") == "missing_snapshot_record":',
        new='        if "не принадлежит" in str(gap.get("detail", "")):',
    ),
    dict(
        id="KFIX01",
        desc="контроль: нейтральный комментарий (обязан SURVIVED)",
        old=(
            "_UNIFORM_MISSING_RECORD_DETAIL = (\n"
            "    \"rs-запись отсутствует/чужая/не паспортная -- сравнение "
            "не фабкуется\"\n"
            ")"
        ),
        new=(
            "_UNIFORM_MISSING_RECORD_DETAIL = (\n"
            "    \"rs-запись отсутствует/чужая/не паспортная -- сравнение "
            "не фабкуется\"\n"
            ")\n"
            "# P6FIXCTRL01 (нейтральный комментарий)"
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
    subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=900)
    failed: dict[str, list[str]] = {"repo": [], "oracle": [], "class_b": []}
    root = ET.parse(junit).getroot()
    for case in root.iter("testcase"):
        classname = case.get("classname", "")
        failure = case.find("failure")
        if failure is None:
            continue
        if "test_pgv06_passport_comparison" in classname:
            failed["repo"].append(case.get("name", ""))
        elif "test_pgv06_cert_oracles" in classname:
            failed["oracle"].append(case.get("name", ""))
        elif "test_pgv06_cert_findings" in classname:
            failed["class_b"].append(case.get("name", ""))
    return failed


def main() -> int:
    tmpdir = Path(tempfile.mkdtemp(prefix="p6fix-mut-"))
    original = MODULE.read_text(encoding="utf-8")
    baseline_md5 = md5_of(MODULE)

    # MV0: базовые прогоны каналов без мутантов
    base = run_channels(tmpdir)
    report: dict = {
        "campaign": "PGV-06-FIX targeted re-mutation (на своих мутантах)",
        "parent": "3d04f88 (PGV-06-CERT)",
        "module": "apps/api/passport_comparison.py",
        "finding": "F-P6C1 (AC18-дух: uniform detail trajectory-гэпов)",
        "repo_suite": REPO_SUITE,
        "oracle_suite": ORACLE_SUITE,
        "class_b_suite": CLASS_B_SUITE,
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
            if repo_killed and (oracle_killed or class_b_killed):
                verdict = "DUAL-KILLED"
            elif oracle_killed:
                verdict = "ORACLE-ONLY"
            elif class_b_killed:
                verdict = "CLASS-B-KILLED"
            elif repo_killed:
                verdict = "REPO-KILLED"
            else:
                verdict = "SURVIVED"
            entry.update({
                "repo_failed_n": len(failed["repo"]),
                "oracle_failed_n": len(failed["oracle"]),
                "class_b_failed_n": len(failed["class_b"]),
                "repo_failed_ids": failed["repo"][:6],
                "oracle_failed_ids": failed["oracle"][:6],
                "class_b_failed_ids": failed["class_b"][:6],
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
        "obligation_F_P6C1_B1": killed,  # обязательство акта: F-P6C1 закрыт
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
