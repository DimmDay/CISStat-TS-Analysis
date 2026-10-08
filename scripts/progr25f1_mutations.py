#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""МУТАЦИОННЫЙ ПРОГОН исправления F1 (PROGR-25-A-CERT → фикс F1).

Мутанты СВОЕГО исправления (сериализация target_column_source,
apps/api/session_store.py::session_to_dict/session_from_dict) --
«мутанты на своих мутантах»: объект мутации -- сам фикс, найденный
сертификацией (находка F1, docs/cert_progr25a_2026-10-08.md §7).

Каналы убийства (независимые):
  repo   -- tests/api/test_session_store.py ПОЛНОСТЬЮ (включая новые
            тесты F1: roundtrip-контракт обеих реализаций store,
            legacy backcompat, пин сырого Redis-документа);
  oracle -- 57 оракулов сертификации (progr25acert_oracles.py, свой
            датасет energy_hourly.csv). КРИТЕРИЙ УБИЙСТВА после фикса:
            в выводе ОТСУТСТВУЕТ «ИТОГ ОРАКУЛОВ: 57/57 PASS» (D1/D2
            перевернулись из expected-FAIL в PASS -- простой exit==0
            больше НЕ доказательство выживания: EXPECTED_FAILS маскирует
            повторный FAIL D1/D2).

Мутанты:
  MF-0  контроль харнесса (no-op) -- обязан ВЫЖИТЬ в обоих каналах;
  MF-1  ключ удалён из session_to_dict;
  MF-2  восстановление удалено из session_from_dict;
  MF-3  session_from_dict жёстко кодирует "auto" -- ожидание: убит
        ТОЛЬКО repo (оракульный D-сюит не прогоняет user-значение
        через roundtrip -- документированный гэп прикрытия, убийца --
        user-ветка roundtrip-теста);
  MF-4  session_to_dict пишет чужое значение (date_column).

Восстановление каждого файла -- побайтовое, md5-контроль (урок
PROGR-19). Использование: python progr25f1_mutations.py [first last].
Правила AGENTS.md: локальное измерение, без commit/push.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "scripts" / "progr25f1_mutation_results.txt"
BACKUP = Path("/home/z/my-project/scripts/cert_backup")

ORACLE = REPO / "scripts" / "progr25acert_oracles.py"
REPO_TESTS = ["tests/api/test_session_store.py"]

TO_DICT_LINE = '        "target_column_source": session.target_column_source,\n'
FROM_DICT_LINE = "        target_column_source=d.get(\"target_column_source\"),\n"

# (id, файл, старый фрагмент, новый фрагмент, описание, ожидание: both|repo|survive)
MUTANTS: list[tuple[str, str, str, str, str, str]] = [
    ("MF-0", "apps/api/session_store.py",
     TO_DICT_LINE,
     '        "target_column_source": session.target_column_source,  # no-op\n',
     "КОНТРОЛЬ харнесса: no-op мутант обязан ВЫЖИТЬ в обоих каналах",
     "survive"),
    ("MF-1", "apps/api/session_store.py",
     TO_DICT_LINE,
     "",
     "ключ удалён из session_to_dict -- документ снова теряет origin",
     "both"),
    ("MF-2", "apps/api/session_store.py",
     FROM_DICT_LINE,
     "",
     "восстановление удалено из session_from_dict -- roundtrip теряет",
     "both"),
    ("MF-3", "apps/api/session_store.py",
     FROM_DICT_LINE,
     '        target_column_source="auto",\n',
     "from_dict жёстко кодирует \"auto\" -- убит repo (user-ветка roundtrip) "
     "И oracle (C1: legacy-документ обязан читаться source=None)",
     "both"),
    ("MF-4", "apps/api/session_store.py",
     TO_DICT_LINE,
     '        "target_column_source": session.date_column,\n',
     "to_dict пишет чужое значение (date_column) -- документ врёт",
     "both"),
]

ORACLE_GREEN_MARK = "ИТОГ ОРАКУЛОВ: 57/57 PASS"


def emit(text: str = "") -> None:
    print(text, flush=True)
    _lines.append(text)


_lines: list[str] = []


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def flush_protocol() -> None:
    OUT.write_text("\n".join(_lines) + "\n", encoding="utf-8")


def run_oracle() -> tuple[bool, str]:
    """True = оракулы 57/57 (мутант ВЫЖИЛ в канале oracle)."""
    proc = subprocess.run(
        [sys.executable, str(ORACLE)], capture_output=True, text=True, timeout=1200,
    )
    green = proc.returncode == 0 and ORACLE_GREEN_MARK in proc.stdout
    summary = next((ln for ln in proc.stdout.strip().splitlines()
                    if "ИТОГ ОРАКУЛОВ" in ln), "ИТОГ ОРАКУЛОВ: ?/?")
    return green, summary


def run_repo_tests() -> tuple[bool, str]:
    """True = тесты зелёные (мутант ВЫЖИЛ в канале repo)."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *REPO_TESTS, "-q", "-x",
         "-p", "no:cacheprovider"],
        capture_output=True, text=True, timeout=1200, cwd=str(REPO),
    )
    last = (proc.stdout.strip().splitlines() or [""])[-1]
    return proc.returncode == 0, last


def main() -> int:
    first = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    last = int(sys.argv[2]) if len(sys.argv) > 2 else len(MUTANTS)
    selected = MUTANTS[first - 1:last]

    emit("=" * 100)
    emit("МУТАЦИОННЫЙ ПРОГОН ИСПРАВЛЕНИЯ F1 -- сериализация target_column_source "
         "(session_store.py)")
    emit(f"Мутантов в прогоне: {len(selected)} из {len(MUTANTS)} "
         f"(каналы: repo {REPO_TESTS} + oracle 57 [критерий: {ORACLE_GREEN_MARK}])")
    emit("=" * 100)

    files = sorted({m[1] for m in selected})
    originals: dict[str, bytes] = {}
    for rel in files:
        path = REPO / rel
        originals[rel] = path.read_bytes()
        BACKUP.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, BACKUP / ("mutation25f1_" + Path(rel).name))
        emit(f"backup {rel}: md5={md5(path)}")

    results: list[tuple[str, str, str, str, str]] = []
    try:
        for mid, rel, old, new, desc, expect in selected:
            path = REPO / rel
            src = path.read_bytes().decode("utf-8")
            if src.count(old) != 1:
                emit(f"\n!! {mid}: якорь не уникален ({src.count(old)} вхождений) -- SKIP")
                results.append((mid, "SKIP", "SKIP", desc, expect))
                flush_protocol()
                continue
            emit(f"\n── {mid}: {desc}")
            emit(f"    файл: {rel} (ожидание: {expect})")
            path.write_text(src.replace(old, new, 1), encoding="utf-8")
            try:
                repo_ok, repo_note = run_repo_tests()
                oracle_ok, oracle_note = run_oracle()
            finally:
                path.write_bytes(originals[rel])
            repo_kill = "KILLED" if not repo_ok else "SURVIVED"
            oracle_kill = "KILLED" if not oracle_ok else "SURVIVED"
            if expect == "survive":
                verdict = ("OK-CONTROL" if (repo_ok and oracle_ok) else "HARNESS-BUG")
            elif expect == "both":
                verdict = "KILLED-BOTH" if (not repo_ok and not oracle_ok) else "SURVIVED"
            else:  # "repo"
                verdict = ("KILLED-REPO" if (not repo_ok and oracle_ok) else "UNEXPECTED")
            emit(f"    repo   : {repo_kill:8s} ({repo_note})")
            emit(f"    oracle : {oracle_kill:8s} "
                 f"({oracle_note.split('ИТОГ')[-1].strip(' :') if oracle_note else ''})")
            emit(f"    ВЕРДИКТ: {verdict}")
            results.append((mid, repo_kill, oracle_kill, desc, expect))
            if md5(path) != hashlib.md5(originals[rel]).hexdigest():
                emit(f"    !! ВОССТАНОВЛЕНИЕ {rel} НЕ СОШЛОСЬ ПО MD5")
            flush_protocol()
    finally:
        for rel, blob in originals.items():
            (REPO / rel).write_bytes(blob)
        emit("\nВосстановление оригиналов:")
        for rel in files:
            emit(f"    {rel}: md5={md5(REPO / rel)}")

    emit("\n" + "=" * 100)
    for mid, repo_k, oracle_k, desc, expect in results:
        emit(f"  {mid}: repo={repo_k:8s} oracle={oracle_k:8s} -- {desc}")
    control = next((r for r in results if r[4] == "survive"), None)
    if control:
        ok = control[1] == "SURVIVED" and control[2] == "SURVIVED"
        emit(f"\nКонтроль харнесса {control[0]}: "
             f"{'OK -- no-op выжил в обоих каналах' if ok else 'СБОЙ -- харнесс ложно убивает!'}")
    kill_targets = [r for r in results if r[4] in ("both", "repo")]
    killed = [r for r in kill_targets
              if (r[1] == "KILLED" and (r[4] == "repo" or r[2] == "KILLED"))]
    emit(f"\nИТОГ: {len(killed)}/{len(kill_targets)} мутантов-целей убиты "
         "ожидаемыми каналами"
         + ("" if len(killed) == len(kill_targets) else " -- ЕСТЬ ПЕРЕЖИВШИЕ"))
    emit("=" * 100)
    emit("AGENTS.md: локальное измерение, commit/push НЕ выполнялись.")
    flush_protocol()
    return 0 if (len(killed) == len(kill_targets) and control
                 and control[1] == "SURVIVED" and control[2] == "SURVIVED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
