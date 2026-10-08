#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""МУТАЦИОННЫЙ ПРОГОН независимой сертификации задачи A (PROGR-25-A-CERT).

15 СВОИХ мутантов аудитора (набор НЕ копирует ни мутанты разработчика --
их не было: задача A мутируется впервые -- ни planned М1–М5 задачи D,
ни мутантов PROGR-24-CERT). Каждый мутант обязан быть убит ОБОИМИ
каналами НЕЗАВИСИМО:
  repo   -- адресные тесты репозитория (test_progress_progr25a.py +
            test_target_column.py + test_session_store.py +
            test_progress_trace_hook.py), fail-fast;
  oracle -- 55 оракулов аудитора (progr25acert_oracles.py, свой датасет;
            exit != 0 == убит; 53 PASS + 2 expected-FAIL F1 -- база).

Контроль харнесса (мета-проверка «мутант на мутанте»): TM-0 -- no-op
мутант (семантика не меняется) обязан ВЫЖИТЬ в ОБОИХ каналах; иначе
харнесс ложно убивает и весь прогон недостоверен. В счёт убитости не
входит.

Восстановление каждого файла -- побайтовое, md5-контроль (урок PROGR-19).
Использование: python progr25acert_mutations.py [first_idx last_idx]
(1-based включительно; по умолчанию -- все). Правила AGENTS.md: локальное
измерение, без commit/push.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "scripts" / "progr25acert_mutation_results.txt"
BACKUP = Path("/home/z/my-project/scripts/cert_backup")

ORACLE = REPO / "scripts" / "progr25acert_oracles.py"
REPO_TESTS = [
    "tests/api/test_progress_progr25a.py",
    "tests/api/test_target_column.py",
    "tests/api/test_session_store.py",
    "tests/api/test_progress_trace_hook.py",
]

_lines: list[str] = []


def emit(text: str = "") -> None:
    print(text, flush=True)
    _lines.append(text)


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def flush_protocol() -> None:
    OUT.write_text("\n".join(_lines) + "\n", encoding="utf-8")


# (id, файл относительно REPO, старый фрагмент, новый фрагмент,
#  описание, ожидание: kill | survive)
MUTANTS: list[tuple[str, str, str, str, str, str]] = [
    ("TM-0", "apps/api/target_column_rule.py",
     "AUTO_SOURCE = \"auto\"",
     "AUTO_SOURCE = \"auto\"  # harness control: no-op",
     "КОНТРОЛЬ харнесса: no-op мутант обязан ВЫЖИТЬ в обоих каналах",
     "survive"),
    ("TM-1", "apps/api/target_column_rule.py",
     "    excluded = {session.date_column} | set(session.derived_columns or {})",
     "    excluded = {session.date_column}",
     "снят вычет реестра производных -- производная становится кандидатом (R4)",
     "kill"),
    ("TM-2", "apps/api/target_column_rule.py",
     "    excluded = {session.date_column} | set(session.derived_columns or {})",
     "    excluded = set(session.derived_columns or {})",
     "снят вычет session.date_column -- дата-ось становится кандидатом (R4)",
     "kill"),
    ("TM-3", "apps/api/target_column_rule.py",
     "    if len(candidates) != 1:\n        return None",
     "    if not candidates:\n        return None",
     "фиксация при 2+ кандидатах -- честная неоднозначность сломана",
     "kill"),
    ("TM-4", "apps/api/target_column_rule.py",
     "    session.append_trace_event(\n"
     "        make_trace_event(\n"
     "            \"target_column_changed\",\n"
     "            stage=\"validation\",\n"
     "            node_id=None,\n"
     "            run_id=session.run_id,\n"
     "            actor=\"system\",\n"
     "            target_column=column,\n"
     "            source=AUTO_SOURCE,\n"
     "        )\n"
     "    )",
     "    _ = column",
     "посев события удалён -- фиксация без трассы (план М5)",
     "kill"),
    ("TM-5", "apps/api/target_column_rule.py",
     "    session.target_column_source = AUTO_SOURCE",
     "    session.target_column_source = USER_SOURCE",
     "инверсия origin сессии auto->user при авто-фиксации",
     "kill"),
    ("TM-6", "apps/api/target_column_rule.py",
     "            source=AUTO_SOURCE,",
     "            source=USER_SOURCE,",
     "инверсия source в payload события auto->user (трасса врёт)",
     "kill"),
    ("TM-7", "apps/api/target_column_rule.py",
     "    return candidates[0] if candidates else None",
     "    return candidates[-1] if candidates else None",
     "рекомендация -- последний кандидат вместо первого (порядок сломан)",
     "kill"),
    ("TM-8", "apps/api/target_column_rule.py",
     "    return [str(c) for c in df.select_dtypes(include=\"number\").columns]",
     "    return [str(c) for c in df.columns]",
     "numeric_columns отдаёт ВСЕ колонки -- авто-фиксация нечисловой",
     "kill"),
    ("TM-9", "apps/api/routers/session.py",
     "    session.set_target_column(column)\n"
     "    # PROGR-25-A: ручной выбор -- источник \"user\" (last-wins после авто).\n"
     "    session.target_column_source = USER_SOURCE",
     "    session.set_target_column(column)",
     "ручной маршрут не ставит source=user -- last-wins сломан",
     "kill"),
    ("TM-10", "apps/api/upload_common.py",
     "        auto_fix_and_seed(session)\n"
     "        # КОНТРАКТ SessionStore: после мутации -- обязательно save().",
     "        # КОНТРАКТ SessionStore: после мутации -- обязательно save().",
     "точка фиксации upload снята -- Г1 возвращается",
     "kill"),
    ("TM-11", "apps/api/routers/session.py",
     "    auto_fix_and_seed(session)\n"
     "    # КОНТРАКТ SessionStore: мутация -- обязательно save().",
     "    # КОНТРАКТ SessionStore: мутация -- обязательно save().",
     "точка фиксации demo снята (R2 нарушен)",
     "kill"),
    ("TM-12", "apps/api/trace_hook.py",
     "        \"target_column_changed\", payload_keys=(\"target_column\", \"source\"),",
     "        \"target_column_changed\", payload_keys=(\"target_column\",),",
     "канал source в payload_keys снят -- готовность канала потеряна",
     "kill"),
    ("TM-13", "apps/api/session_store.py",
     "        self.target_column = None\n"
     "        # PROGR-25-A: источник выбора сбрасывается вместе с целью --\n"
     "        # новый датасет = новый анализ; авто-фиксация применит правило\n"
     "        # к новому фрейму в точке загрузки.\n"
     "        self.target_column_source = None",
     "        self.target_column = None",
     "set_dataset не сбрасывает source -- устаревший origin перетекает",
     "kill"),
    ("TM-14", "apps/api/routers/session.py",
     "            session.target_column = None\n"
     "            # PROGR-25-A: источник выбора сбрасывается вместе с целью --\n"
     "            # иначе устаревший \"auto\" указывал бы на несуществующий выбор.\n"
     "            session.target_column_source = None",
     "            session.target_column = None",
     "convert-types не сбрасывает source -- устаревший auto у пустой цели",
     "kill"),
    ("TM-15", "apps/api/routers/progress.py",
     "        target_column=session.target_column,\n"
     "        target_column_source=session.target_column_source,",
     "        target_column=None,\n"
     "        target_column_source=None,",
     "носитель задачи B в /trace отрезан (всегда None)",
     "kill"),
]


def run_oracle() -> tuple[bool, str]:
    """True = оракулы зелёные (мутант ВЫЖИЛ в канале oracle)."""
    proc = subprocess.run(
        [sys.executable, str(ORACLE)], capture_output=True, text=True, timeout=900,
    )
    tail = proc.stdout.strip().splitlines()
    summary = next((ln for ln in tail if "ИТОГ ОРАКУЛОВ" in ln),
                   "ИТОГ ОРАКУЛОВ: ?/?")
    return proc.returncode == 0, summary


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
    emit("МУТАЦИОННЫЙ ПРОГОН PROGR-25-A-CERT -- задача A (spec_progress_target_column.md §4-A)")
    emit(f"Мутантов в прогоне: {len(selected)} из {len(MUTANTS)} "
         f"(каналы: repo {len(REPO_TESTS)} файлов + oracle 55 оракулов)")
    emit("=" * 100)

    # Предварительный backup оригиналов с md5-контролем.
    files = sorted({m[1] for m in selected})
    originals: dict[str, bytes] = {}
    for rel in files:
        path = REPO / rel
        originals[rel] = path.read_bytes()
        BACKUP.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, BACKUP / ("mutation25a_" + Path(rel).name))
        emit(f"backup {rel}: md5={md5(path)}")

    results: list[tuple[str, str, str, str, str]] = []
    try:
        for mid, rel, old, new, desc, expect in selected:
            path = REPO / rel
            src = path.read_bytes().decode("utf-8")
            if src.count(old) != 1:
                emit(f"\n!! {mid}: якорь не уникален ({src.count(old)} вхождений) -- мутант пропущен")
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
                verdict = "OK-CONTROL" if (repo_ok and oracle_ok) else "HARNESS-BUG"
            else:
                verdict = "KILLED" if (not repo_ok and not oracle_ok) else "SURVIVED"
            emit(f"    repo   : {repo_kill:8s} ({repo_note})")
            emit(f"    oracle : {oracle_kill:8s} ({oracle_note.split('ИТОГ')[-1].strip(' :') if oracle_note else ''})")
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
    kills = [r for r in results
             if r[4] == "kill" and r[1] == "KILLED" and r[2] == "KILLED"]
    survivors = [r for r in results
                 if r[4] == "kill" and (r[1] != "KILLED" or r[2] != "KILLED")]
    for mid, repo_k, oracle_k, desc, expect in results:
        emit(f"  {mid}: repo={repo_k:8s} oracle={oracle_k:8s} -- {desc}")
    control = next((r for r in results if r[4] == "survive"), None)
    if control:
        ok = control[1] == "SURVIVED" and control[2] == "SURVIVED"
        emit(f"\nКонтроль харнесса {control[0]}: "
             f"{'OK -- no-op выжил в обоих каналах' if ok else 'СБОЙ -- харнесс ложно убивает!'}")
    emit(f"\nИТОГ: {len(kills)}/{len([r for r in results if r[4] == 'kill'])} "
         "мутантов убиты ОБОИМИ каналами"
         + (f"; переживших: {len(survivors)}" if survivors else ""))
    emit("=" * 100)
    emit("AGENTS.md: локальное измерение, commit/push НЕ выполнялись.")
    flush_protocol()
    return 0 if (not survivors and control and control[1] == "SURVIVED"
                 and control[2] == "SURVIVED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
