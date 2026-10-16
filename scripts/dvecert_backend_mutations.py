#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""МУТАЦИОННЫЙ ПРОГОН независимой сертификации DATASET-VIEW-EDITOR-1-CERT
-- БЭКЕНД (свои мутанты аудитора поверх продовых файлов задач 1c9eb29+68fd65d).

Двухканальная схема (прецедент PROGR-25-A/B-CERT): каждый мутант обязан
быть убит ОБОИМИ каналами НЕЗАВИСИМО:
  repo   -- адресные тесты репозитория задачи (tests/api/
            test_dataset_derived_columns.py + ..._delete.py);
  oracle -- 18 оракулов аудитора (scripts/dvecert_backend_oracles.py,
            свои данные «порт-звонки»; exit != 0 == убит).

Контроль харнесса «мутант на мутанте»: MB-0 -- no-op мутант обязан
ВЫЖИТЬ в ОБОИХ каналах; иначе харнесс ложно убивает и прогон
недостоверен. В счёт убитости не входит.

Восстановление каждого файла -- побайтовое, md5-контроль (урок PROGR-19).
Использование: python scripts/dvecert_backend_mutations.py [first last]
Правила AGENTS.md: локальное измерение, без commit/push.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "scripts" / "dvecert_backend_mutation_results.txt"

REPO_TESTS = [
    "tests/api/test_dataset_derived_columns.py",
    "tests/api/test_dataset_derived_columns_delete.py",
]

SESSION_PY = "apps/api/routers/session.py"

_lines: list[str] = []


def emit(text: str = "") -> None:
    print(text, flush=True)
    _lines.append(text)


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


# ── Мутанты: (id, файл, [ (старый_фрагмент, новый_фрагмент), ... ], описание, ожидание)
MUTANTS: list[tuple[str, str, list[tuple[str, str]], str, str]] = [
    (
        "MB-0", SESSION_PY,
        [("    registry = session.derived_columns or {}",
          "    registry = session.derived_columns or {}  # MB-0")],
        "no-op контроль харнесса (обязан ВЫЖИТЬ в обоих каналах)",
        "control",
    ),
    (
        "MB-1", SESSION_PY,
        [("    columns_out.sort(key=lambda entry: entry.created_at)",
          "    columns_out.sort(key=lambda entry: entry.created_at, reverse=True)  # MB-1")],
        "GET: сортировка реестра инвертирована (порядок появления нарушен)",
        "kill",
    ),
    (
        "MB-2", SESSION_PY,
        [("    columns_out.sort(key=lambda entry: entry.created_at)\n    return DatasetDerivedColumnsResponse(columns=columns_out, total=len(columns_out))",
          "    columns_out.sort(key=lambda entry: entry.created_at)\n    session.touch()  # MB-2: GET мутирует сессию (анти-read-only)\n    get_session_store().save(session)\n    return DatasetDerivedColumnsResponse(columns=columns_out, total=len(columns_out))")],
        "GET: touch+save -- чтение не является read-only (анти-R6)",
        "kill",
    ),
    (
        "MB-3", SESSION_PY,
        [("    for name in derived_columns_in_frame(session):",
          "    for name in (session.derived_columns or {}):  # MB-3")],
        "GET: область = весь реестр БЕЗ пересечения с кадром (анти-append-only)",
        "kill",
    ),
    (
        "MB-4", SESSION_PY,
        [("    deletable = set(derived_columns_in_frame(session))\n    offending = [name for name in targets if name not in deletable]\n    if offending:",
          "    deletable = set(derived_columns_in_frame(session))\n    offending = []  # MB-4: гейт снят\n    if offending:")],
        "POST: проверка offending снята -- канонические колонки удаляемы (ГЛАВНАЯ гарантия безопасности источника)",
        "kill",
    ),
    (
        "MB-5", SESSION_PY,
        [("    unregister_derived_columns(session, targets)",
          "    pass  # MB-5: каскад реестра снят")],
        "POST: unregister снят -- реестр расходится с фактом (скрытые долги)",
        "kill",
    ),
    (
        "MB-6", SESSION_PY,
        [("    targets = list(dict.fromkeys(str(name) for name in payload.columns))",
          "    targets = [str(name) for name in payload.columns]  # MB-6")],
        "POST: дубли имени не схлопываются (drop по дубликату -- KeyError/500)",
        "kill",
    ),
    (
        "MB-7", SESSION_PY,
        [("    if session.dataset is not None:\n        session.dataset.rows = len(next_df)\n        session.dataset.columns = len(next_df.columns)",
          "    if False:  # MB-7: счётчики не обновляются")],
        "POST: счётчики session.dataset не обновляются",
        "kill",
    ),
    (
        "MB-8", SESSION_PY,
        [("    remaining_total = len(derived_columns_in_frame(session))\n    return DatasetDerivedColumnsDeleteResponse(deleted=targets, remaining_total=remaining_total)",
          "    return DatasetDerivedColumnsDeleteResponse(deleted=targets, remaining_total=0)  # MB-8")],
        "POST: remaining_total жёстко 0 (ответ врёт о состоянии реестра)",
        "kill",
    ),
    (
        "MB-9", SESSION_PY,
        [("    session.touch()\n    store.save(session)",
          "    session.touch()  # MB-9: save снят (персистенция потеряна)")],
        "POST: store.save снят -- на production-бэкенде Redis удаление не переживает save→get (Memory-бэкенд маскирует)",
        "kill",
    ),
    (
        "MB-10", SESSION_PY,
        [("    if not targets:\n        raise HTTPException(status_code=422, detail=\"Не указаны колонки для удаления\")",
          "    if False:  # MB-10")],
        "POST: пустой список не отклоняется (анти-гейт 422)",
        "kill",
    ),
    (
        "MB-11", SESSION_PY,
        [("    session.set_dataframe(next_df, reason=\"dataset:derived_columns_delete\")",
          "    session.dataframe = next_df  # MB-11: мимо ЕДИНОЙ ТОЧКИ set_dataframe")],
        "POST: замена кадра мимо set_dataframe -- ревизия данных не растёт (анти-AUDIT-C)",
        "kill",
    ),
]


def apply_mutant(path: Path, replacements: list[tuple[str, str]]) -> None:
    s = path.read_text(encoding="utf-8")
    for old, _new in replacements:
        if old not in s:
            raise AssertionError(f"паттерн не найден в {path}: {old[:60]!r}")
        s = s.replace(old, _new, 1)
    path.write_text(s, encoding="utf-8")


def run_repo_tests() -> tuple[bool, str]:
    """True = зелёные (мутант ВЫЖИЛ в канале repo)."""
    cmd = ["/home/z/.venv/bin/python", "-m", "pytest", "-q", "--no-header", "-x"] + REPO_TESTS
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=1200)
    tail = (r.stdout + r.stderr).strip().splitlines()
    note = next((ln.strip() for ln in tail if ln.strip().startswith("=")), "?")
    return r.returncode == 0, note[:60]


def run_oracle() -> tuple[bool, str]:
    """True = зелёные (мутант ВЫЖИЛ в канале oracle)."""
    cmd = ["/home/z/.venv/bin/python", "scripts/dvecert_backend_oracles.py"]
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=1200)
    note = next((ln.strip() for ln in (r.stdout + r.stderr).splitlines() if ln.strip().startswith("ИТОГО")), "?")
    return r.returncode == 0, note


def main() -> int:
    first = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    last = int(sys.argv[2]) if len(sys.argv) > 2 else len(MUTANTS)
    batch = MUTANTS[first - 1 : last]

    emit("=" * 78)
    emit("МУТАЦИОННЫЙ ПРОГОН DATASET-VIEW-EDITOR-1-CERT -- БЭКЕНД (свои мутанты)")
    emit(f"Каналы: repo (2 repo-сюиты задачи) + oracle (18 оракулов dvecert_backend_oracles)")
    emit(f"База: 68fd65d; партия мутантов: {first}..{last} из {len(MUTANTS)}")
    emit("=" * 78)

    backups: dict[str, tuple[Path, str]] = {}
    results: list[tuple[str, str, str, str, str]] = []
    try:
        for mid, rel, replacements, desc, expect in batch:
            path = REPO / rel
            emit("")
            emit(f"── Мутант {mid}: {desc}")
            if rel not in backups:
                bak = path.with_suffix(path.suffix + ".certbak")
                bak.write_bytes(path.read_bytes())
                backups[rel] = (bak, md5(path))
            try:
                apply_mutant(path, replacements)
            except AssertionError as e:
                emit(f"    ОШИБКА ПАТТЕРНА: {e}")
                return 2
            try:
                repo_ok, repo_note = run_repo_tests()
                oracle_ok, oracle_note = run_oracle()
            finally:
                bak, base_md5 = backups[rel]
                path.write_bytes(bak.read_bytes())
                if md5(path) != base_md5:
                    emit("    RESTORE MISMATCH -- КРИТИЧНО")
                    return 2
            repo_kill = "KILLED" if not repo_ok else "SURVIVED"
            oracle_kill = "KILLED" if not oracle_ok else "SURVIVED"
            if expect == "control":
                verdict = "OK-CONTROL" if (repo_ok and oracle_ok) else "HARNESS-BUG"
            else:
                verdict = "KILLED" if (not repo_ok and not oracle_ok) else "SURVIVED"
            emit(f"    repo   : {repo_kill:8s} ({repo_note})")
            emit(f"    oracle : {oracle_kill:8s} ({oracle_note})")
            emit(f"    вердикт: {verdict}")
            results.append((mid, repo_kill, oracle_kill, desc, expect))
    finally:
        # Страховка: восстановить всё, что осталось под бэкапом.
        for rel, (bak, base_md5) in backups.items():
            path = REPO / rel
            path.write_bytes(bak.read_bytes())
            if md5(path) != base_md5:
                emit(f"RESTORE MISMATCH (finally): {rel}")
                return 2
            bak.unlink(missing_ok=True)
        emit("")
        emit("Восстановление: все файлы побайтово восстановлены (md5 сошёлся).")

    emit("")
    emit("─" * 78)
    killed_both = [r for r in results if r[4] == "kill" and r[1] == "KILLED" and r[2] == "KILLED"]
    survived = [r for r in results if r[4] == "kill" and (r[1] != "KILLED" or r[2] != "KILLED")]
    controls = [r for r in results if r[4] == "control"]
    emit(f"ИТОГО партии: убиты ОБОИМИ каналами: {len(killed_both)}; пережили хотя бы один: {len(survived)}")
    for mid, repo_k, oracle_k, desc, _ in survived:
        emit(f"    ПЕРЕЖИЛ {mid} (repo={repo_k}, oracle={oracle_k}): {desc}")
    for mid, repo_k, oracle_k, desc, _ in controls:
        status = "ОК (выжил -- харнесс достоверен)" if (repo_k == "SURVIVED" and oracle_k == "SURVIVED") else "СБОЙ ХАРНЕССА"
        emit(f"    КОНТРОЛЬ {mid}: repo={repo_k}, oracle={oracle_k} -- {status}")
    emit("─" * 78)
    (OUT).write_text("\n".join(_lines) + "\n", encoding="utf-8")
    print(f"Протокол: {OUT}")
    bad = len(survived) + sum(1 for c in controls if c[1] != "SURVIVED" or c[2] != "SURVIVED")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
