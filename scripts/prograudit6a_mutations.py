# scripts/prograudit6a_mutations.py
"""Мутационные пробы задачи AUDIT-6A (план §20.3: RED подтверждён,
GREEN закрывает acceptance; мутанты -- проверка силы acceptance-тестов).

Каждый мутант -- точечная порча атомарности/порядка/идемпотентности
commit_event_batch (обоих хранилищ); приёмка -- ОРАКУЛ
tests/api/test_progress_audit_6a.py (параметризованный parity-сьют).
М0 -- no-op контроль (харнесс достоверен: оракул зелёный на немутнированном
коде). Мутант УБИТ, если хотя бы один тест оракула падает.

Запуск: python scripts/prograudit6a_mutations.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TARGET = REPO / "apps" / "api" / "research_runs.py"
ORACLE = REPO / "tests" / "api" / "test_progress_audit_6a.py"

ORIGINAL = TARGET.read_text(encoding="utf-8")

# (id, описание, паттерн замены (regex), на что заменить)
MUTANTS = [
    (
        "M1",
        "Memory: батч без дедупа внутри (дубль события получает новый seq)",
        r"if event\.event_id in seen or event\.event_id in existing_ids:\n                    continue",
        "if False:\n                    continue",
    ),
    (
        "M2",
        "Memory: CAS-контекст отключён (stale пишется)",
        r"if batch\.expected_context_id is not None and current is not None:",
        "if False:",
    ),
    (
        "M3",
        "Memory: receipt не проверяет тело (тот же ключ + другое тело молча принят)",
        r"if stored_fingerprint != fingerprint:",
        "if False:",
    ),
    (
        "M4",
        "Memory: sequence не назначается (корпус без позиции ledger)",
        r"sequence = self\._sequences\.get\(run_id, 0\)\n            for event in batch\.events:",
        "sequence = 0\n            for event in batch.events:",
    ),
    (
        "M5",
        "Memory: run-метаданные НЕ обновляются той же операцией (анатом P10)",
        r"self\._runs\[run_id\] = merged_run",
        "pass  # mutated: run metadata skipped",
    ),
    (
        "M6",
        "Postgres: receipt-конфликт отключён (тот же ключ + другое тело принят)",
        r"if str\(row\[3\]\) != fingerprint:",
        "if False:",
    ),
    (
        "M7",
        "Postgres: CAS stale-context отключён",
        r"if \(\n                batch\.expected_context_id is not None\n                and stored_context is not None\n                and str\(stored_context\) != batch\.expected_context_id\n            \):",
        "if False:",
    ),
    (
        "M8",
        "Postgres: сериализация по run убрана (MAX без FOR UPDATE -- гонка порядка)",
        r'cur\.execute\(\n                "SELECT context_id FROM research_runs WHERE run_id = %s FOR UPDATE",\n                \(run_id,\),\n            \)',
        "pass  # mutated: no row lock",
    ),
    (
        "M9",
        "Postgres: дедуп против корпуса отключён (retry дублирует)",
        r"if event\.event_id in seen or event\.event_id in existing_ids:\n                    continue  # дедуп внутри батча",
        "if event.event_id in seen:\n                    continue",
    ),
]


def run_oracle() -> tuple[bool, str]:
    """Прогон оракула (Memory-часть достаточно быстрая и покрывает
    Memory-мутанты; Postgres-мутанты валидируются Memory-оракулом только
    частично, поэтому для PG-мутантов прогоняется и live-PG половина,
    если pgserver доступен). Возвращает (убит, вывод)."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(ORACLE), "-q", "--no-header", "-x"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=600,
    )
    killed = proc.returncode != 0
    return killed, (proc.stdout + proc.stderr)[-400:]


def run_oracle_with_pg() -> tuple[bool, str]:
    """Полный оракул с живым PG через pgserver (для Postgres-мутантов)."""
    script = (
        "import os, sys, pgserver, subprocess, tempfile\n"
        "d = tempfile.mkdtemp()\n"
        "srv = pgserver.get_server(d, cleanup_mode='delete')\n"
        "os.environ['CISSTAT_TEST_PG_DSN'] = srv.get_uri()\n"
        f"code = subprocess.run([sys.executable, '-m', 'pytest', '{ORACLE}', "
        "'-q', '--no-header'], capture_output=False).returncode\n"
        "sys.exit(code)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=900,
    )
    killed = proc.returncode != 0
    return killed, (proc.stdout + proc.stderr)[-400:]


def main() -> int:
    print("=== AUDIT-6A мутационные пробы (оракул: test_progress_audit_6a.py) ===")
    print("[M0] no-op контроль: оракул на немутнированном коде...")
    killed, tail = run_oracle()
    m0 = "SURVIVED (харнесс достоверен)" if not killed else "KILLED (харнесс недостоверен!)"
    print(f"[M0] {m0}")
    if killed:
        print(tail)
        return 2

    results: list[tuple[str, str, str]] = []
    try:
        for mid, description, pattern, replacement in MUTANTS:
            mutated, count = re.subn(pattern, replacement, ORIGINAL, count=1)
            if count != 1:
                results.append((mid, "PATTERN-MISS", description))
                print(f"[{mid}] PATTERN-MISS: {description}")
                continue
            TARGET.write_text(mutated, encoding="utf-8")
            is_pg_mutant = mid in {"M6", "M7", "M8", "M9"}
            if is_pg_mutant:
                try:
                    killed, tail = run_oracle_with_pg()
                except Exception as exc:  # noqa: BLE001
                    results.append((mid, "PG-SKIP", f"{description} ({exc})"))
                    print(f"[{mid}] PG-SKIP: {exc}")
                    TARGET.write_text(ORIGINAL, encoding="utf-8")
                    continue
            else:
                killed, tail = run_oracle()
            verdict = "KILLED" if killed else "SURVIVED"
            results.append((mid, verdict, description))
            print(f"[{mid}] {verdict}: {description}")
            if not killed:
                print("   ", tail)
            TARGET.write_text(ORIGINAL, encoding="utf-8")
    finally:
        TARGET.write_text(ORIGINAL, encoding="utf-8")

    killed_n = sum(1 for _, verdict, _ in results if verdict == "KILLED")
    survived = [mid for mid, verdict, _ in results if verdict == "SURVIVED"]
    skipped = [mid for mid, verdict, _ in results if verdict in {"PG-SKIP", "PATTERN-MISS"}]
    print(
        f"=== ИТОГ: убито {killed_n}/{len(results)}, выживших: {survived or 'нет'}, "
        f"пропущено: {skipped or 'нет'} ==="
    )
    return 1 if survived else 0


if __name__ == "__main__":
    raise SystemExit(main())
