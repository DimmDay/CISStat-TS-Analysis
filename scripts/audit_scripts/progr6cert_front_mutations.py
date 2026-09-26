# scripts/audit_scripts/progr6cert_front_mutations.py
"""Фронтенд-мутационный прогон сертификации PROGR-6 (2026-09-26).

4 мутанта packages/ui/lib/mentor.ts; каждый обязан быть УБИТ контуром
фронтенд-оракулов packages/ui/lib/progr6cert_oracles.test.ts (свои
данные) и/или сьютом коллеги packages/ui/lib/mentor.test.ts. Восстановление
байт-в-байт (sha256).

Прогон: python scripts/audit_scripts/progr6cert_front_mutations.py
Итог:  FRONT-MUTATIONS: N/N KILLED (exit 0) | выжившие (exit 1).
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MENTOR_TS = ROOT / "packages/ui/lib/mentor.ts"
JEST_TARGETS = [
    "packages/ui/lib/progr6cert_oracles.test.ts",
    "packages/ui/lib/mentor.test.ts",
]


@dataclass
class FrontMutation:
    mid: str
    old: str
    new: str
    note: str


def mutations() -> list[FrontMutation]:
    return [
        FrontMutation(
            "F1",
            "if (worst === null || ratio < worst.ratio) {",
            "if (worst === null || ratio > worst.ratio) {",
            "worstStdStats выбирает ЛУЧШУЮ колонку (инверсия минимума) "
            "-- over_aggressive пропускает переглаживание",
        ),
        FrontMutation(
            "F2",
            "    if (stdBefore <= 0) continue;",
            "    if (false) continue;",
            "потеря guard нулевого std_before: деление 0 даёт NaN/Infinity-пару",
        ),
        FrontMutation(
            "F3",
            "    affected_count_before: input.affectedBefore,\n"
            "    changed_count: input.changed,\n"
            "    still_affected_count: input.stillAffected,",
            "    affected_count_before: input.affectedBefore,\n"
            "    changed_count: input.stillAffected,\n"
            "    still_affected_count: input.changed,",
            "перепутаны changed_count и still_affected_count при маппинге §7.2",
        ),
        FrontMutation(
            "F4",
            "    if (!response.ok) return [];",
            "    if (!response.ok) throw new Error(\"http \" + response.status);",
            "ХАРАКТЕРИЗАЦИЯ (поведенчески эквивалентен): throw внутри try "
            "перехватывается catch-all -- best-effort §12 п.8 защищён дважды",
        ),
        FrontMutation(
            "F4b",
            "  } catch {\n    return [];\n  }",
            "  }",
            "потеря catch-all: сбой сети/битый JSON роняет Мастер вместо "
            "пустого списка (нарушение best-effort §12 п.8)",
        ),
    ]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_mutant(mutation: FrontMutation) -> bool:
    original = MENTOR_TS.read_text(encoding="utf-8")
    assert mutation.old in original, (
        f"{mutation.mid}: эталонный фрагмент не найден в mentor.ts"
    )
    try:
        MENTOR_TS.write_text(original.replace(mutation.old, mutation.new, 1),
                             encoding="utf-8")
        result = subprocess.run(
            ["npx", "jest", *JEST_TARGETS, "--silent"],
            cwd=ROOT, capture_output=True, text=True, timeout=900,
        )
        return result.returncode != 0
    finally:
        MENTOR_TS.write_text(original, encoding="utf-8")


def main() -> int:
    digest = sha256(MENTOR_TS)
    results: list[tuple[str, bool, str]] = []
    try:
        for mutation in mutations():
            killed = run_mutant(mutation)
            results.append((mutation.mid, killed, mutation.note))
            print(f"[{'KILLED' if killed else 'SURVIVED'}] {mutation.mid}: {mutation.note}")
    finally:
        if sha256(MENTOR_TS) != digest:
            print("FATAL: mentor.ts не восстановился байт-в-байт")
            return 2
    killed_count = sum(1 for _, killed, _ in results if killed)
    print(f"FRONT-MUTATIONS: {killed_count}/{len(results)} KILLED")
    return 0 if killed_count == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
