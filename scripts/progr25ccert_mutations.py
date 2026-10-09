#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""МУТАЦИОННЫЙ ПРОГОН независимой сертификации задачи C (PROGR-25-C-CERT).

8 СВОИХ мутантов аудитора поверх продовых файлов задачи PROGR-25-C
(коммит d703407). Набор НЕ копирует мутанты разработчика (MC-1..MC-5):
пересечение по семантике только на каноническом зеркале слоя 2 (CC-4),
реализация своя; новые классы -- инверсия ПОРЯДКА реестра (CC-1),
нечестный гейт пометки (CC-2), first-wins факта подстановки (CC-3),
снятие Mapping-щита origin (CC-5), инверсия структурного гейта (CC-6),
пробой fail-closed валидатора whitelist (CC-7).

Каждый мутант обязан быть убит каналами НЕЗАВИСИМО:
  repo   -- адресные тесты репозитория задачи C (TestPhaseTextUploadOrigin
            + TestProgr25CStageLevelReasonOrigin + test_progress_progr25c.py);
  oracle -- 22 оракула аудитора (scripts/progr25ccert_oracles.py, свои
            данные; exit != 0 == убит; 22/22 PASS -- база).

Контроль харнесса «мутант на мутанте»: CC-0 -- no-op мутант обязан
ВЫЖИТЬ в ОБОИХ каналах; иначе харнесс ложно убивает и прогон
недостоверен. В счёт убитости не входит.

Восстановление каждого файла -- побайтовое, md5-контроль (урок PROGR-19).
Использование: python progr25ccert_mutations.py [first_idx last_idx]
(1-based включительно; по умолчанию -- все). Правила AGENTS.md: локальное
измерение, без commit/push.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "scripts" / "progr25ccert_mutation_results.txt"

REPO_TESTS = [
    "tests/api/test_mentor_rules.py::TestPhaseTextUploadOrigin",
    "tests/api/test_node_status_engine.py::TestProgr25CStageLevelReasonOrigin",
    "tests/api/test_progress_progr25c.py",
]
ORACLE = "scripts/progr25ccert_oracles.py"

MENTOR = "app/core/mentor_rules.py"
NODE_STATUS = "app/core/node_status.py"
RULE = "apps/api/target_column_rule.py"

_lines: list[str] = []


def emit(text: str = "") -> None:
    print(text, flush=True)
    _lines.append(text)


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


# ── Мутанты: (id, файл, [ (старый_фрагмент, новый_фрагмент), ... ], описание, ожидание)
MUTANTS: list[tuple[str, str, list[tuple[str, str]], str, str]] = [
    (
        "CC-0", RULE,
        [('AUTO_SOURCE = "auto"', 'AUTO_SOURCE = "auto"  # CC-0')],
        "КОНТРОЛЬ харнесса: no-op (семантика не меняется) -- обязан ВЫЖИТЬ в обоих каналах",
        "control",
    ),
    (
        "CC-1", MENTOR,
        [("""        PhaseTextRule(
            _upload_structure_and_target_auto,
            _UPLOAD_STRUCTURE_DONE_TARGET_AUTO,
        ),
        PhaseTextRule(_upload_structure_and_target_done, _UPLOAD_STRUCTURE_DONE_BOTH),""",
          """        PhaseTextRule(_upload_structure_and_target_done, _UPLOAD_STRUCTURE_DONE_BOTH),
        PhaseTextRule(
            _upload_structure_and_target_auto,
            _UPLOAD_STRUCTURE_DONE_TARGET_AUTO,
        ),""")],
        "инверсия ПОРЯДКА реестра upload: оба-правило перехватывает auto-факт "
        "(текст без имени колонки и с потерянной семантикой авто)",
        "kill",
    ),
    (
        "CC-2", NODE_STATUS,
        [('mark = " (авто)" if source == "auto" else ""',
          'mark = " (авто)" if source is not None else ""  # CC-2')],
        "нечестный гейт пометки: «(авто)» ставится при любом непустом source "
        "(ручной выбор выдаётся за авто; legacy-корпус без поля не помечается)",
        "kill",
    ),
    (
        "CC-3", MENTOR,
        [('            column = str(payload.get("target_column"))',
          '            column = column or str(payload.get("target_column"))  # CC-3')],
        "first-wins факта подстановки: текст называет ПЕРВУЮ колонку истории "
        "(last-wins сломан -- самоутверждение расходится с фактом условия)",
        "kill",
    ),
    (
        "CC-4", RULE,
        [("    session.append_trace_event(event)\n    record_run_event(session, event)",
          "    session.append_trace_event(event)  # CC-4")],
        "зеркало слоя 2 удалено (канонический анти-исправление бага тимлида: "
        "Наставник вновь не видит авто-фиксацию)",
        "kill",
    ),
    (
        "CC-5", MENTOR,
        [('        if isinstance(payload, Mapping) and payload.get("target_column"):\n            origin = (',
          '        if payload.get("target_column"):\n            origin = (')],
        "снятие Mapping-щита в _target_origin: dict-событие с payload=None "
        "роняет подстановку (анти-деградация «событие мимо фактов, не 500»)",
        "kill-oracle-only",
    ),
    (
        "CC-6", MENTOR,
        [('        _summary_node_status(summary, "structure") == "done"\n        and _target_confirmed(events)\n        and _target_origin(events) == _TARGET_SOURCE_AUTO',
          '        _summary_node_status(summary, "structure") != "done"\n        and _target_confirmed(events)\n        and _target_origin(events) == _TARGET_SOURCE_AUTO')],
        "инверсия структурного гейта auto-правила: авто-текст при НЕподтверждённой "
        "структуре (честная просьба о структуре подменена)",
        "kill",
    ),
    (
        "CC-7", MENTOR,
        [('    {"stage", "total_nodes", "done_count", "warning_nodes", "target_column"}',
          '    {"stage", "total_nodes", "done_count", "warning_nodes"}  # CC-7')],
        "whitelist теряет target_column: fail-closed валидатор реестра обязан "
        "уронить импорт (демонстрация пояса G2 канона PROGR-19)",
        "kill",
    ),
]


def apply_mutant(path: Path, replacements: list[tuple[str, str]]) -> None:
    s = path.read_text(encoding="utf-8")
    for old, _new in replacements:
        if old not in s:
            raise AssertionError(f"паттерн не найден в {path}: {old[:70]!r}")
        s = s.replace(old, _new, 1)
    path.write_text(s, encoding="utf-8")


def run_repo_tests() -> tuple[bool, str]:
    """True = зелёные (мутант ВЫЖИЛ в канале repo)."""
    cmd = [sys.executable, "-m", "pytest", "-q"] + REPO_TESTS
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=900)
    tail = (r.stdout + r.stderr).strip().splitlines()
    note = next((ln.strip() for ln in tail if "passed" in ln or "error" in ln.lower()), "?")
    return r.returncode == 0, note


def run_oracle() -> tuple[bool, str]:
    """True = зелёные (мутант ВЫЖИЛ в канале oracle)."""
    r = subprocess.run(
        [sys.executable, str(REPO / ORACLE)], cwd=REPO,
        capture_output=True, text=True, timeout=900,
    )
    note = next(
        (ln.strip() for ln in r.stdout.splitlines() if ln.startswith("ИТОГ ОРАКУЛОВ")),
        f"exit={r.returncode}",
    )
    return r.returncode == 0, note


def main() -> int:
    first = int(sys.argv[1]) if len(sys.argv) > 2 else 1
    last = int(sys.argv[2]) if len(sys.argv) > 2 else len(MUTANTS)
    batch = MUTANTS[first - 1 : last]

    emit("=" * 100)
    emit("МУТАЦИОННЫЙ ПРОГОН PROGR-25-C-CERT (свои мутанты аудитора)")
    emit("Каналы: repo (3 адресные сюиты задачи C) + oracle (22 оракула, "
         "scripts/progr25ccert_oracles.py)")
    emit(f"База: d703407 (объект -- продовые файлы задачи C); "
         f"партия мутантов: {first}..{last} из {len(MUTANTS)}")
    emit("=" * 100)

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
            elif expect == "kill-oracle-only":
                verdict = "KILLED" if oracle_kill == "KILLED" else "SURVIVED"
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
    emit("─" * 100)
    killed = [r for r in results if r[4] == "kill" and r[1] == "KILLED" and r[2] == "KILLED"]
    killed_oracle = [r for r in results if r[4] == "kill-oracle-only" and r[2] == "KILLED"]
    survived = [
        r for r in results
        if (r[4] == "kill" and (r[1] != "KILLED" or r[2] != "KILLED"))
        or (r[4] == "kill-oracle-only" and r[2] != "KILLED")
    ]
    controls = [r for r in results if r[4] == "control"]
    emit(f"ИТОГО партии: убиты ОБОИМИ каналами: {len(killed)}; "
         f"убиты oracle-каналом (repo-гэп, находка): {len(killed_oracle)}; "
         f"пережили: {len(survived)}")
    for mid, repo_k, oracle_k, desc, _ in killed:
        emit(f"    KILLED-BOTH {mid} (repo={repo_k}, oracle={oracle_k})")
    for mid, repo_k, oracle_k, desc, _ in killed_oracle:
        emit(f"    KILLED-ORACLE {mid} (repo={repo_k}, oracle={oracle_k}): {desc}")
    for mid, repo_k, oracle_k, desc, _ in survived:
        emit(f"    ПЕРЕЖИЛ {mid} (repo={repo_k}, oracle={oracle_k}): {desc}")
    for mid, repo_k, oracle_k, desc, _ in controls:
        status = "ОК (выжил -- харнесс достоверен)" if (repo_k == "SURVIVED" and oracle_k == "SURVIVED") else "СБОЙ ХАРНЕССА"
        emit(f"    КОНТРОЛЬ {mid}: repo={repo_k}, oracle={oracle_k} -- {status}")
    emit("─" * 100)
    (OUT).write_text("\n".join(_lines) + "\n", encoding="utf-8")
    print(f"Протокол: {OUT}")
    bad = len(survived) + sum(1 for c in controls if c[1] != "SURVIVED" or c[2] != "SURVIVED")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
