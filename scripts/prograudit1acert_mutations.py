# scripts/prograudit1acert_mutations.py
# -*- coding: utf-8 -*-
"""Мутационная кампания СВОИХ мутантов сертификации PROGR-AUDIT-1A-CERT.

Принцип «мутанты на своих мутантах»: набор ДИЗЪЮНКТЕН по точкам/классам
любым пробам исполнителя задачи 1A (исполнитель мутационной кампании не
вёл — RED-протокол 32/4; набор также не пересекается с CM-1..9 камеры
6A-CERT по классам: там ledger/sequence/receipt/CAS, здесь семантика
choice/reset/origin/пара/restore/марка).

Дисциплина (урок PROGR-19): backup → единственный якорь → патч →
обоих-каналов прогон → побайтовое восстановление → md5-контроль после
каждого мутанта и в finally. Аварийный останов при неединичном якоре.

Каналы убийства:
  * oracle — scripts/prograudit1acert_oracles.py (63 своих оракула,
    EXIT=0 = SURVIVED, != 0 = KILLED);
  * repo   — сюита исполнителя tests/api/test_progress_audit_1a.py
    (36 тестов, 0 failed = SURVIVED, > 0 = KILLED).

Мутанты (12 + контроль CM-0):
  CM-0  no-op контроль харнесса               -> SURVIVED обязан
  CM-1  normalize: мусор -> "user" (фабрика)   I-класс фабрики origin
  CM-2  normalize: None/"" -> None (legacy)    I-класс legacy-контракта
  CM-3  reducer: cleared не сбрасывает         класс сброса
  CM-4  reducer: пустая строка не факт         класс legacy-формы
  CM-5  reducer: мусор -> str(raw) фабрика     класс фабрики цели
  CM-6  record_run_event: resolved-щит снят    класс mirror-инкремента
  CM-7  PG upsert: пара без EXCLUDED           класс прямой записи
  CM-8  restore: редьюсер игнорируется         класс авторитета ledger
  CM-9  restore: числовая проверка снята       класс применимости
  CM-10 restore: origin в сессию не пишется   класс пары сессии
  CM-11 node_status: инверсия марки «(авто)»  класс reason-марки
  CM-12 mentor: текст-условие на origin       класс фаз-фактов

Запуск: python scripts/prograudit1acert_mutations.py [--protocol PATH]
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

ORACLE_SCRIPT = REPO / "scripts/prograudit1acert_oracles.py"
REPO_SUITE = REPO / "tests/api/test_progress_audit_1a.py"

# (id, файл, якорь, замена, класс)
MUTANTS: list[tuple[str, str, str, str, str]] = [
    (
        "CM-0", "app/core/effective_target.py", "",
        "",  # no-op: патч не применяется
        "no-op контроль харнесса",
    ),
    (
        "CM-1", "app/core/effective_target.py",
        "    return None\n\n\n@dataclass(frozen=True)\nclass EffectiveTarget:",
        "    return TARGET_ORIGIN_USER\n\n\n@dataclass(frozen=True)\nclass EffectiveTarget:",
        "фабрика origin: мусорный source читается user",
    ),
    (
        "CM-2", "app/core/effective_target.py",
        '    if raw is None or raw == "":\n        # Отсутствие поля у legacy-ВЫБОРА -- user (§3.7); пустая строка\n        # эквивалентна отсутствию (payload ручного маршрута -- без source).\n        return TARGET_ORIGIN_USER',
        '    if raw is None or raw == "":\n        # МУТАЦИЯ CM-2\n        return None',
        "legacy-контракт сломан: отсутствие source -> unknown",
    ),
    (
        "CM-3", "app/core/effective_target.py",
        '        if event_type == _EVENT_TYPE_CLEARED:\n            # Выделенный сброс (контракт §3.1): payload не требуется;\n            # origin после сброса -- None (unknown, НЕ "user").\n            target = None\n            origin = None',
        '        if event_type == _EVENT_TYPE_CLEARED:\n            # МУТАЦИЯ CM-3: cleared -- не факт\n            continue',
        "выделенный сброс не сбрасывает пару",
    ),
    (
        "CM-4", "app/core/effective_target.py",
        '        elif isinstance(raw_target, str):\n            # ПУСТАЯ строка -- legacy-сброс (канон PROGR-15-B, паритет\n            # run-метаданных и reason-ветки node_status).\n            target = None\n            origin = None\n            source_event_id = str(data.get("event_id") or "") or None',
        '        elif isinstance(raw_target, str):\n            # МУТАЦИЯ CM-4: пустая строка -- не факт\n            continue',
        "legacy-форма пустого target не сброс",
    ),
    (
        "CM-5", "app/core/effective_target.py",
        '        else:\n            # Мусор/отсутствие target -- не факт: состояние не трогаем.\n            continue',
        '        else:\n            # МУТАЦИЯ CM-5: фабрика "123" из мусора\n            target = str(raw_target)\n            origin = normalize_target_origin(payload.get("source"))\n            source_event_id = str(data.get("event_id") or "") or None',
        "фабрика цели из мусорного payload",
    ),
    (
        "CM-6", "apps/api/research_runs.py",
        '            state = effective_target((event,))\n            if state.resolved:\n                run = replace(',
        '            state = effective_target((event,))\n            if True:\n                run = replace(',
        "resolved-щит снят: шум стирает хранимую пару",
    ),
    (
        "CM-7", "apps/api/research_runs.py",
        "            target_column = EXCLUDED.target_column,\n            target_column_source = EXCLUDED.target_column_source,",
        "            target_column = EXCLUDED.target_column,\n            target_column_source = research_runs.target_column_source,",
        "COALESCE-стиль: сброс пары не стирает источник в PG",
    ),
    (
        "CM-8", "apps/api/routers/progress.py",
        "    eff = effective_target(events)\n    if eff.resolved:",
        "    eff = effective_target(events)\n    if False:",
        "авторитет ledger снят: restore верит устаревшим метаданным",
    ),
    (
        "CM-9", "apps/api/routers/progress.py",
        "    if (\n        restore_target\n        and restore_target in df.columns\n        and restore_target in numeric_columns(df)\n    ):",
        "    if (\n        restore_target\n        and restore_target in df.columns\n    ):",
        "применимость цели к raw снята (нечисловая восстанавливается)",
    ),
    (
        "CM-10", "apps/api/routers/progress.py",
        "        session.set_target_column(restore_target)\n        session.target_column_source = restore_origin",
        "        session.set_target_column(restore_target)",
        "origin пары не пишется в сессию (F03-остаток)",
    ),
    (
        "CM-11", "app/core/node_status.py",
        '            mark = (\n                " (авто)"\n                if normalize_target_origin(source) == "auto"\n                else ""\n            )',
        '            mark = (\n                " (авто)"\n                if normalize_target_origin(source) != "auto"\n                else ""\n            )',
        "инверсия reason-марки «(авто)»",
    ),
    (
        "CM-12", "app/core/mentor_rules.py",
        '    eff = effective_target(events)\n    return {"target_column": eff.target} if eff.target else {}',
        '    eff = effective_target(events)\n    return {"target_column": eff.target} if eff.origin else {}',
        "фаз-факты: unknown-origin выбор теряет колонку текста",
    ),
]


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _count_anchor(path: Path, anchor: str) -> int:
    return path.read_text(encoding="utf-8").count(anchor)


def _run_oracle() -> tuple[bool, str]:
    # EXIT=0 — все оракулы PASS -> мутант НЕ обнаружен -> SURVIVED.
    proc = subprocess.run(
        [sys.executable, str(ORACLE_SCRIPT)],
        cwd=REPO, capture_output=True, text=True, timeout=1200,
        env={**__import__("os").environ, "DATABASE_URL": ""},
    )
    return proc.returncode == 0, f"EXIT={proc.returncode}"


def _run_repo_suite() -> tuple[bool, str]:
    # 0 failed — сюита исполнителя зелёная -> мутант НЕ обнаружен -> SURVIVED.
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(REPO_SUITE), "-q", "--disable-warnings"],
        cwd=REPO, capture_output=True, text=True, timeout=1200,
        env={**__import__("os").environ, "DATABASE_URL": ""},
    )
    tail = (proc.stdout or "").strip().splitlines()[-1:] or [""]
    return proc.returncode == 0, tail[0]


def main() -> int:
    protocol: list[str] = []
    results: list[tuple[str, str, str, str]] = []  # id, oracle, repo, verdict
    backups: dict[str, bytes] = {}
    touched: dict[str, Path] = {}

    def _restore_all() -> None:
        for mid, data in backups.items():
            path = touched[mid]
            path.write_bytes(data)
        backups.clear()
        touched.clear()

    print("=" * 72)
    print("PROGR-AUDIT-1A-CERT: мутационная кампания СВОИХ мутантов")
    print("=" * 72)
    try:
        for mid, rel, anchor, mutant, klass in MUTANTS:
            path = REPO / rel
            original = path.read_bytes()
            verdict_parts: list[str] = []

            if mid == "CM-0":
                # Контроль: файл не меняется, оба канала обязаны SURVIVED.
                o_surv, o_note = _run_oracle()
                r_surv, r_note = _run_repo_suite()
                ok = o_surv and r_surv
                verdict = "SURVIVED (харнесс достоверен)" if ok else (
                    "HARNESS-FAIL (контроль убит — харнесс недостоверен!)"
                )
                print(f"{mid} [{klass}]: oracle={o_note} repo={r_note} -> {verdict}")
                protocol.append(f"{mid} [{klass}]: oracle={o_note} repo={r_note} -> {verdict}")
                results.append((mid, o_note, r_note, verdict))
                continue

            n = _count_anchor(path, anchor)
            if n != 1:
                print(f"{mid}: PATTERN-MISS (якорей {n}) — кампания остановлена")
                protocol.append(f"{mid}: PATTERN-MISS (якорей {n})")
                results.append((mid, "PATTERN-MISS", "PATTERN-MISS", "HARNESS-FAIL"))
                break

            backups[mid] = original
            touched[mid] = path
            path.write_text(path.read_text(encoding="utf-8").replace(anchor, mutant, 1), encoding="utf-8")
            try:
                o_surv, o_note = _run_oracle()
                r_surv, r_note = _run_repo_suite()
                if o_surv and r_surv:
                    verdict = "SURVIVED"
                elif o_surv:
                    verdict = "KILLED-REPO-ONLY"
                elif r_surv:
                    verdict = "KILLED-ORACLE-ONLY"
                else:
                    verdict = "KILLED-BOTH"
                print(f"{mid} [{klass}]: oracle={o_note} repo={r_note} -> {verdict}")
                protocol.append(f"{mid} [{klass}]: oracle={o_note} repo={r_note} -> {verdict}")
                results.append((mid, o_note, r_note, verdict))
            finally:
                # Побайтовое восстановление сразу после каждого мутанта.
                path.write_bytes(original)
                del backups[mid]
                del touched[mid]
                restored_md5 = _md5(path)
                orig_md5 = hashlib.md5(original).hexdigest()
                if restored_md5 != orig_md5:
                    print(f"{mid}: RESTORE-FAIL md5 {restored_md5} != {orig_md5}")
                    protocol.append(f"{mid}: RESTORE-FAIL")
                    return 2
    finally:
        _restore_all()

    survivors = [r for r in results if r[3] == "SURVIVED" and r[0] != "CM-0"]
    killed = [r for r in results if r[3].startswith("KILLED")]
    harness_ok = any(r[0] == "CM-0" and "SURVIVED" in r[3] for r in results)
    print("-" * 72)
    print(
        f"ИТОГО: {len(killed)} KILLED / {len(survivors)} SURVIVED "
        f"(мутантов {len(results) - 1}); контроль CM-0: "
        f"{'SURVIVED' if harness_ok else 'FAIL'}"
    )
    protocol.append(
        f"ИТОГО: {len(killed)} KILLED / {len(survivors)} SURVIVED "
        f"(мутантов {len(results) - 1}); контроль CM-0: "
        f"{'SURVIVED' if harness_ok else 'FAIL'}"
    )
    proto_path = REPO / "scripts/prograudit1acert_mutation_results.txt"
    proto_path.write_text("\n".join(protocol) + "\n", encoding="utf-8")
    print(f"Протокол: {proto_path}")
    return 0 if (not survivors and harness_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
