#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""МУТАЦИОННЫЙ ПРОГОН независимой сертификации задачи A (PROGR-24-CERT).

13 СВОИХ мутантов аудитора (НЕ копия чужих; задача A разработчиком
мутировалась впервые). Каждый мутант обязан быть убит ОБОИМИ каналами
НЕЗАВИСИМО:
  repo   -- адресные тесты репозитория (test_status_original_series.py +
            test_session_store.py + test_progress_progr23.py);
  oracle -- 38 оракулов аудитора (progr24acert_oracles.py, свой датасет).

Восстановление каждого файла -- из побайтовой backup-копии с md5-контролем
(урок PROGR-19). Правила AGENTS.md: локальное измерение, без commit/push.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "scripts" / "progr24acert_mutation_results.txt"
BACKUP = Path("/home/z/my-project/scripts/cert_backup")

ORACLE = REPO / "scripts" / "progr24acert_oracles.py"
REPO_TESTS = [
    "tests/api/test_status_original_series.py",
    "tests/api/test_session_store.py",
    "tests/api/test_progress_progr23.py",
]

_lines: list[str] = []


def emit(text: str = "") -> None:
    print(text, flush=True)
    _lines.append(text)


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


# (id, файл относительно REPO, старый фрагмент, новый фрагмент, описание)
MUTANTS = [
    ("CM-1", "apps/api/column_origin.py",
     "    registry = session.derived_columns or {}\n    return scope_columns(session.dataframe, registry.keys())",
     "    registry = {}\n    return scope_columns(session.dataframe, registry.keys())",
     "canonical_columns игнорирует реестр -- производные возвращаются в гейты"),
    ("CM-2", "apps/api/column_origin.py",
     "    return [str(name) for name in session.dataframe.columns if str(name) in registry]",
     "    return [str(name) for name in registry]",
     "derived_columns_in_frame отдаёт сырой реестр без пересечения с датафреймом (ghost-утечка)"),
    ("CM-3", "apps/api/column_origin.py",
     "    added = [str(name) for name in df.columns if str(name) not in before]",
     "    added = [str(name) for name in df.columns]",
     "register_derived_columns регистрирует ВСЕ колонки, а не разность до/после"),
    ("CM-4", "apps/api/column_origin.py",
     '        session.derived_columns[name] = {\n            "stage": stage,\n            "source": source,\n            "created_at": created_at,\n        }',
     "        session.derived_columns[name] = {}",
     "метаданные {stage, source, created_at} не записываются"),
    ("CM-5", "apps/api/column_origin.py",
     '            "created_at": created_at,\n        }\n    return added',
     '            "created_at": created_at,\n        }\n    return []',
     "хелпер всегда отчитывается пустым списком добавленных колонок"),
    ("CM-6", "apps/api/column_origin.py",
     "    return df.loc[:, [str(name) for name in columns]]",
     "    return df",
     "scope_frame игнорирует список колонок -- профили всегда по полному датафрейму"),
    ("CM-7", "apps/api/column_origin.py",
     "    before = {str(name) for name in before_columns}\n    return [str(name) for name in after_df.columns if str(name) not in before]",
     "    return []",
     "operation_added_columns всегда пуст -- флаг-колонки операции возвращаются в карточную шкалу preview"),
    ("CM-8", "apps/api/column_origin.py",
     "    derived_set = {str(name) for name in derived}\n    return [str(name) for name in df.columns if str(name) not in derived_set]",
     "    derived_set = {str(name) for name in derived}\n    return [str(name) for name in df.columns if str(name) in derived_set]",
     "scope_columns инвертирован -- канонической объявляется производная область"),
    ("CM-9", "apps/api/session_store.py",
     '        derived_columns={\n            str(name): dict(entry)\n            for name, entry in (d.get("derived_columns", {}) or {}).items()\n            if isinstance(entry, dict)\n        },',
     '        derived_columns=dict(d.get("derived_columns", {}) or {}),',
     "guard мусорных записей реестра снят при чтении документа (деградация Task 143)"),
    ("CM-10", "apps/api/session_store.py",
     "        self.derived_columns = {}\n        self.preprocessing_spectral_selection = {}",
     "        self.preprocessing_spectral_selection = {}",
     "set_dataset НЕ сбрасывает реестр -- происхождение перетекает в новый анализ"),
    ("CM-11", "apps/api/session_store.py",
     "SESSION_SCHEMA_VERSION = 3",
     "SESSION_SCHEMA_VERSION = 2",
     "версия схемы сессии не поднята (спека §Реализация п.3)"),
    ("CM-12", "apps/api/routers/session.py",
     "    if not derived_names:\n        return None\n    profiles = profile_missing(scope_frame(df, derived_names))",
     "    if True:\n        return None\n    profiles = profile_missing(scope_frame(df, derived_names))",
     "информационный канал derived_summary пропусков отрезан (всегда None)"),
    ("CM-13", "apps/api/routers/session.py",
     "    if column is not None and str(column) in session.derived_columns:",
     "    if False and column is not None and str(column) in session.derived_columns:",
     "методологический guard 422 на per-column проверку производной колонки снят"),
]


def run_oracle() -> tuple[bool, str]:
    """True = оракулы зелёные (мутант ВЫЖИЛ в канале oracle)."""
    proc = subprocess.run(
        [sys.executable, str(ORACLE)], capture_output=True, text=True, timeout=600,
    )
    tail = proc.stdout.strip().splitlines()
    summary = next((ln for ln in tail if "ИТОГ ОРАКУЛОВ" in ln), "ИТОГ ОРАКУЛОВ: ?/?")
    return proc.returncode == 0, summary


def run_repo_tests() -> tuple[bool, str]:
    """True = тесты зелёные (мутант ВЫЖИЛ в канале repo)."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *REPO_TESTS, "-q", "-x",
         "-p", "no:cacheprovider"],
        capture_output=True, text=True, timeout=900, cwd=str(REPO),
    )
    last = (proc.stdout.strip().splitlines() or [""])[-1]
    return proc.returncode == 0, last


def main() -> int:
    emit("=" * 100)
    emit("МУТАЦИОННЫЙ ПРОГОН PROGR-24-CERT -- задача A (spec_status_original_series.md)")
    emit(f"Мутантов: {len(MUTANTS)}; каналы: repo (адресные тесты) + oracle (38 оракулов, свой датасет)")
    emit("=" * 100)

    # Предварительный backup оригиналов с md5-контролем.
    files = sorted({m[1] for m in MUTANTS})
    originals: dict[str, bytes] = {}
    for rel in files:
        path = REPO / rel
        originals[rel] = path.read_bytes()
        BACKUP.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, BACKUP / ("mutation_" + Path(rel).name))
        emit(f"backup {rel}: md5={md5(path)}")

    results: list[tuple[str, str, str, str]] = []
    try:
        for mid, rel, old, new, desc in MUTANTS:
            path = REPO / rel
            src = path.read_bytes().decode("utf-8")
            if src.count(old) != 1:
                emit(f"\n!! {mid}: якорь не уникален ({src.count(old)} вхождений) -- мутант пропущен")
                results.append((mid, "SKIP", "SKIP", desc))
                continue
            emit(f"\n── {mid}: {desc}")
            emit(f"    файл: {rel}")
            path.write_text(src.replace(old, new, 1), encoding="utf-8")
            try:
                repo_ok, repo_note = run_repo_tests()
                oracle_ok, oracle_note = run_oracle()
            finally:
                path.write_bytes(originals[rel])
            repo_kill = "KILLED" if not repo_ok else "SURVIVED"
            oracle_kill = "KILLED" if not oracle_ok else "SURVIVED"
            verdict = "KILLED" if (not repo_ok and not oracle_ok) else "SURVIVED"
            emit(f"    repo   : {repo_kill:8s} ({repo_note})")
            emit(f"    oracle : {oracle_kill:8s} ({oracle_note})")
            emit(f"    ВЕРДИКТ: {verdict}")
            results.append((mid, repo_kill, oracle_kill, desc))
            if md5(path) != hashlib.md5(originals[rel]).hexdigest():
                emit(f"    !! ВОССТАНОВЛЕНИЕ {rel} НЕ СОШЛОСЬ ПО MD5")
    finally:
        for rel, blob in originals.items():
            (REPO / rel).write_bytes(blob)
        emit("\nВосстановление оригиналов:")
        for rel in files:
            emit(f"    {rel}: md5={md5(REPO / rel)}")

    emit("\n" + "=" * 100)
    killed = [r for r in results if r[1] == "KILLED" and r[2] == "KILLED"]
    for mid, repo_k, oracle_k, desc in results:
        emit(f"  {mid}: repo={repo_k:8s} oracle={oracle_k:8s} -- {desc}")
    emit(f"\nИТОГ: {len(killed)}/{len(results)} мутантов убиты ОБОИМИ каналами")
    emit("=" * 100)
    emit("AGENTS.md: локальное измерение, commit/push НЕ выполнялись.")
    OUT.write_text("\n".join(_lines) + "\n", encoding="utf-8")
    emit(f"Протокол: {OUT}")
    return 0 if len(killed) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
