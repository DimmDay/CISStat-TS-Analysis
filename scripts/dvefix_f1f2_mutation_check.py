#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ВЕРИФИКАЦИЯ РЕАЛИЗАЦИИ НАХОДОК F1/F2 (акт сертификации
DATASET-VIEW-EDITOR-1-CERT, docs/cert_dataset_view_editor_1_2026-10-16.md):
«мутант на мутанте» -- УСИЛЕННЫЕ repo-пины обязаны убить ТЕ ЖЕ мутантов,
которые вскрывали repo-гэпы при сертификации (определения мутантов взяты
БЕЗ ИЗМЕНЕНИЙ из scripts/dvecert_backend_mutations.py).

Проверки:
  1. MB-0 (no-op, контроль харнесса) -- усиленные сюиты задач ОБЯЗАНЫ быть
     ЗЕЛЁНЫМИ (харнесс не убивает правильный код);
  2. MB-2 (GET touch+save -- анти-read-only) -- F1-пин
     test_get_is_read_only_data_revision_unchanged (updated_at + снапшот
     кадра/реестра, уровень оракула B06) ОБЯЗАН убить мутанта
     (при сертификации переживал repo-канал);
  3. MB-9 (снятие store.save в POST delete) -- F2-пины
     ([fakeredis]-параметры трёх персистенционных тестов) ОБЯЗАНЫ убить
     мутанта (при сертификации переживал repo-канал на Memory-бэкенде);
     [memory]-параметры ОБЯЗАНЫ выжить -- задокументированный алиасинг
     MemorySessionStore (ссылка на сессию), ровно ради него вводится
     fakeredis-канал (класс дефекта PROGR-25-F1).

Восстановление каждого файла -- побайтовое, md5-контроль (урок PROGR-19).
Использование: python scripts/dvefix_f1f2_mutation_check.py
Правила AGENTS.md: локальное измерение, без commit/push.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "scripts" / "dvefix_f1f2_mutation_check.txt"

SESSION_PY = "apps/api/routers/session.py"

GET_SUITE = "tests/api/test_dataset_derived_columns.py"
DELETE_SUITE = "tests/api/test_dataset_derived_columns_delete.py"

F1_TEST = f"{GET_SUITE}::test_get_is_read_only_data_revision_unchanged"
F2_FAKEREDIS = [
    f"{DELETE_SUITE}::test_delete_one_of_three_added_columns[fakeredis]",
    f"{DELETE_SUITE}::test_registry_cascade_removes_entry[fakeredis]",
    f"{DELETE_SUITE}::test_dataset_counters_updated_and_persisted[fakeredis]",
]
F2_MEMORY = [
    f"{DELETE_SUITE}::test_delete_one_of_three_added_columns[memory]",
    f"{DELETE_SUITE}::test_registry_cascade_removes_entry[memory]",
    f"{DELETE_SUITE}::test_dataset_counters_updated_and_persisted[memory]",
]

_lines: list[str] = []


def emit(text: str = "") -> None:
    print(text, flush=True)
    _lines.append(text)


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


# ── Мутанты -- ТОЧНЫЕ копии определений из dvecert_backend_mutations.py ──
MUTANTS: dict[str, tuple[str, list[tuple[str, str]], str]] = {
    "MB-0": (
        SESSION_PY,
        [(
            "    registry = session.derived_columns or {}",
            "    registry = session.derived_columns or {}  # MB-0",
        )],
        "no-op контроль харнесса (обязан ВЫЖИТЬ -- усиленные пины зелёные)",
    ),
    "MB-2": (
        SESSION_PY,
        [(
            "    columns_out.sort(key=lambda entry: entry.created_at)\n"
            "    return DatasetDerivedColumnsResponse(columns=columns_out, total=len(columns_out))",
            "    columns_out.sort(key=lambda entry: entry.created_at)\n"
            "    session.touch()  # MB-2: GET мутирует сессию (анти-read-only)\n"
            "    get_session_store().save(session)\n"
            "    return DatasetDerivedColumnsResponse(columns=columns_out, total=len(columns_out))",
        )],
        "GET: touch+save -- чтение не является read-only (анти-R6)",
    ),
    "MB-9": (
        SESSION_PY,
        [(
            "    session.touch()\n    store.save(session)",
            "    session.touch()  # MB-9: save снят (персистенция потеряна)",
        )],
        "POST delete: store.save снят (Memory-бэкенд маскирует, fakeredis -- нет)",
    ),
}


def apply_mutant(path: Path, replacements: list[tuple[str, str]]) -> None:
    s = path.read_text(encoding="utf-8")
    for old, new in replacements:
        if old not in s:
            raise AssertionError(f"паттерн не найден в {path}: {old[:60]!r}")
        s = s.replace(old, new, 1)
    path.write_text(s, encoding="utf-8")


def run_pytest(targets: list[str]) -> tuple[bool, str]:
    """True = зелёные (мутант ВЫЖИЛ в этом канале)."""
    cmd = ["/home/z/.venv/bin/python", "-m", "pytest", "-q", "--no-header"] + targets
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=1200)
    tail = (r.stdout + r.stderr).strip().splitlines()
    note = next((ln.strip() for ln in tail if ln.strip().startswith("=")), "?")
    return r.returncode == 0, note[:70]


def main() -> int:
    path = REPO / SESSION_PY
    bak = path.with_suffix(path.suffix + ".dvefixbak")
    bak.write_bytes(path.read_bytes())
    base_md5 = md5(path)

    results: list[tuple[str, str, str]] = []  # (id, expectation, verdict)
    emit("=" * 78)
    emit("ВЕРИФИКАЦИЯ F1/F2 (DATASET-VIEW-EDITOR-1-CERT) -- мутант на мутанте:")
    emit("усиленные repo-пины против ТЕХ ЖЕ мутантов акта сертификации")
    emit(f"База: HEAD (продовый код не меняется; восстанавливается побайтово, md5)")
    emit("  1. MB-0 no-op        -> сюиты задач (27 тестов) зелёные (OK-CONTROL)")
    emit("  2. MB-2 GET touch+save -> F1-тест (updated_at + снапшот) убивает")
    emit("  3. MB-9 save снят     -> 3x[fakeredis] убивают; 3x[memory] выживают")
    emit("     (документированный алиасинг MemorySessionStore -- причина F2)")
    emit("=" * 78)

    try:
        # ── 1. MB-0: контроль харнесса ────────────────────────────────
        mid = "MB-0"
        mut_file, replacements, desc = MUTANTS[mid]
        emit("")
        emit(f"── Мутант {mid}: {desc}")
        apply_mutant(path, replacements)
        try:
            ok, note = run_pytest([GET_SUITE, DELETE_SUITE])
        finally:
            path.write_bytes(bak.read_bytes())
            if md5(path) != base_md5:
                emit("    RESTORE MISMATCH -- КРИТИЧНО")
                return 2
        verdict = "OK-CONTROL" if ok else "HARNESS-BUG (правильный код красный!)"
        emit(f"    сюиты задач : {'GREEN' if ok else 'RED'} ({note})")
        emit(f"    вердикт     : {verdict}")
        results.append((mid, "control", verdict))

        # ── 2. MB-2: F1-пин обязан убить ──────────────────────────────
        mid = "MB-2"
        mut_file, replacements, desc = MUTANTS[mid]
        emit("")
        emit(f"── Мутант {mid}: {desc}")
        apply_mutant(path, replacements)
        try:
            ok, note = run_pytest([F1_TEST])
        finally:
            path.write_bytes(bak.read_bytes())
            if md5(path) != base_md5:
                emit("    RESTORE MISMATCH -- КРИТИЧНО")
                return 2
        verdict = "KILLED (F1 закрыт)" if not ok else "SURVIVED (F1 НЕ закрыт!)"
        emit(f"    F1-тест     : {'RED' if not ok else 'GREEN'} ({note})")
        emit(f"    вердикт     : {verdict}")
        results.append((mid, "kill", verdict))

        # ── 3. MB-9: [fakeredis] обязаны убить, [memory] -- выжить ────
        mid = "MB-9"
        mut_file, replacements, desc = MUTANTS[mid]
        emit("")
        emit(f"── Мутант {mid}: {desc}")
        apply_mutant(path, replacements)
        try:
            ok_fake, note_fake = run_pytest(F2_FAKEREDIS)
            ok_mem, note_mem = run_pytest(F2_MEMORY)
        finally:
            path.write_bytes(bak.read_bytes())
            if md5(path) != base_md5:
                emit("    RESTORE MISMATCH -- КРИТИЧНО")
                return 2
        v_fake = "KILLED" if not ok_fake else "SURVIVED (F2 НЕ закрыт!)"
        v_mem = "SURVIVED (ожидаемо: алиасинг Memory)" if ok_mem else "RED (неожиданно!)"
        emit(f"    3x[fakeredis]: {'RED' if not ok_fake else 'GREEN'} ({note_fake})")
        emit(f"    3x[memory]   : {'GREEN' if ok_mem else 'RED'} ({note_mem})")
        emit(f"    вердикт     : F2 {'ЗАКРЫТ' if not ok_fake and ok_mem else 'НЕ закрыт / харнесс сломан'}")
        results.append((mid, "kill", f"fakeredis={v_fake}; memory={v_mem}"))
    finally:
        path.write_bytes(bak.read_bytes())
        if md5(path) != base_md5:
            emit(f"RESTORE MISMATCH (finally): {SESSION_PY}")
            return 2
        bak.unlink(missing_ok=True)
        emit("")
        emit("Восстановление: session.py побайтово восстановлен (md5 сошёлся).")

    emit("")
    emit("─" * 78)
    bad = 0
    for mid, expect, verdict in results:
        emit(f"    {mid}: {verdict}")
        if expect == "control" and verdict != "OK-CONTROL":
            bad += 1
        if expect == "kill" and not verdict.startswith(("KILLED", "fakeredis=KILLED")):
            bad += 1
    ok_all = bad == 0
    emit("─" * 78)
    emit(f"ИТОГО: {'ВСЕ ОЖИДАНИЯ СХОДЯТСЯ -- F1/F2 закрыты (мутант на мутанте)' if ok_all else 'ЕСТЬ РАСХОЖДЕНИЯ'}")
    (OUT).write_text("\n".join(_lines) + "\n", encoding="utf-8")
    print(f"Протокол: {OUT}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
