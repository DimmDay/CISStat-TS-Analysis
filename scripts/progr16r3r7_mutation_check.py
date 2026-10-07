#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Мутационная верификация Task PROGR-16-A-R3R7 (закрытие находок
R-3..R-7 сертификации PROGR-16-A-CERT тестами).

TDD-инверсия (паттерн PROGR-17-CERT-R1R4 / PROGR-16-A-R2): реализация
корректна, задача ТОЛЬКО тестовая, поэтому RED проверяется на СВОИХ
мутантах -- каждый новый тест обязан убить своего мутанта. Каждый
мутант: точечная правка файла реализации -> прогон целевого теста ->
восстановление git checkout (файлы реализации ЗАКОММИЧЕНЫ в HEAD
7e800c6, рабочий дерево чистое -- restore контролируется git diff).

Мутанты (по определениям находок):
  M-R3  node_status.py   -- снят гейт is_known_node в derive_node_statuses
  M-R4  node_status.py   -- текст причины validation_check_status подменён
  M-R5  progress.py      -- события отчёта пишутся в порядке payload,
                            а не реестра (for node_id in checks)
  M-R6  TsAnalysisValidation.tsx -- снапшот отчитывает сырой check.status
                            (displayedStatus снят -- needs_rule уходит как
                            pending)
  M-R7  TsAnalysisValidation.tsx -- снят сброс маркера отчёта при смене
                            датасета (эффект [activeDataset?.name])
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

NODE_STATUS = REPO / "app" / "core" / "node_status.py"
PROGRESS = REPO / "apps" / "api" / "routers" / "progress.py"
VALIDATION_TSX = REPO / "packages" / "ui" / "components" / "TsAnalysisValidation.tsx"

MUTANTS: list[dict] = [
    {
        "id": "M-R3",
        "file": NODE_STATUS,
        "old": (
            "        if not node_id:\n"
            "            continue\n"
            "        if not is_known_node(stage, node_id):\n"
            "            continue\n"
            "        statuses[f\"{stage}/{node_id}\"] = status"
        ),
        "new": (
            "        if not node_id:\n"
            "            continue\n"
            "        statuses[f\"{stage}/{node_id}\"] = status"
        ),
        "cmd": [sys.executable, "-m", "pytest",
                "tests/api/test_progress_progr16.py::test_phantom_validation_nodes_never_reach_panel",
                "-q"],
        "expect": "FAIL (фантом доезжает до панели)",
    },
    {
        "id": "M-R4",
        "file": NODE_STATUS,
        "old": '"validation_check_status": "Статус проверки отчитан модулем «Валидация»",',
        "new": '"validation_check_status": "Статус исследования отчитан модулем «EDA»",',
        "cmd": [sys.executable, "-m", "pytest",
                "tests/api/test_progress_progr16.py::test_validation_report_sets_node_reason_on_panel",
                "-q"],
        "expect": "FAIL (причина узла подменена)",
    },
    {
        "id": "M-R5",
        "file": PROGRESS,
        "old": (
            "    for node_id in known_ids:\n"
            "        event = make_trace_event(\n"
            "            \"validation_check_status\","
        ),
        "new": (
            "    for node_id in checks:\n"
            "        event = make_trace_event(\n"
            "            \"validation_check_status\","
        ),
        "cmd": [sys.executable, "-m", "pytest",
                "tests/api/test_progress_progr16.py::test_shuffled_client_map_is_written_in_registry_order",
                "-q"],
        "expect": "FAIL (порядок событий следует payload)",
    },
    {
        "id": "M-R6",
        "file": VALIDATION_TSX,
        "old": "          Object.fromEntries(CHECKS.map((c) => [c.id, displayedStatus(c)])),",
        "new": "          Object.fromEntries(CHECKS.map((c) => [c.id, c.status])),",
        "cmd": ["npx", "jest", "packages/ui/components/TsAnalysisValidation.test.tsx",
                "-t", "reports a pending 'needs_rule' check as warning", "--silent"],
        "expect": "FAIL (needs_rule уходит как pending)",
    },
    {
        "id": "M-R7",
        "file": VALIDATION_TSX,
        "old": (
            "    // прежнему исследованию).\n"
            "    lastReportedChecksRef.current = \"\";\n"
            "    return () => {"
        ),
        "new": (
            "    // прежнему исследованию).\n"
            "    return () => {"
        ),
        "cmd": ["npx", "jest", "packages/ui/components/TsAnalysisValidation.test.tsx",
                "-t", "re-reports after a DATASET CHANGE", "--silent"],
        "expect": "FAIL (второй отчёт молча потерян)",
    },
]


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout


def run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr)[-1200:]


def main() -> int:
    dirty = git("status", "--porcelain")
    print("=== Мутационная верификация PROGR-16-A-R3R7 ===")
    print(f"Рабочее дерево (до): {'ЧИСТОЕ (кроме тестов задачи)' if dirty else 'чистое'}")

    results: list[tuple[str, str, str]] = []
    failed_restore: list[str] = []

    for mutant in MUTANTS:
        target: Path = mutant["file"]
        original = target.read_text(encoding="utf-8")
        if mutant["old"] not in original:
            print(f"[{mutant['id']}] ОШИБКА: контекст мутации не найден "
                  f"в {target.name} -- проба НЕ применена")
            results.append((mutant["id"], "APPLY-FAIL", mutant["expect"]))
            continue
        try:
            mutated = original.replace(mutant["old"], mutant["new"], 1)
            target.write_text(mutated, encoding="utf-8")
            code, tail = run(mutant["cmd"])
            verdict = "KILLED" if code != 0 else "SURVIVED"
            last_line = [l for l in tail.strip().splitlines() if l.strip()]
            detail = last_line[-1][:110] if last_line else ""
            print(f"[{mutant['id']}] {verdict} ({detail}) -- ожидание: {mutant['expect']}")
            results.append((mutant["id"], verdict, detail))
        finally:
            git("checkout", "--", str(target.relative_to(REPO)))
            after = git("diff", "--stat", str(target.relative_to(REPO))).strip()
            if after:
                failed_restore.append(target.name)

    print("\n=== Контроль восстановления ===")
    if failed_restore:
        for name in failed_restore:
            print(f"!! {name} НЕ восстановлен байт-в-байт")
        return 2
    print("Все файлы реализации восстановлены байт-в-байт (git diff пуст).")

    print("\n=== Итог ===")
    survived = [m for m, v, _ in results if v != "KILLED"]
    for mid, verdict, detail in results:
        print(f"{mid}: {verdict}  {detail}")
    if survived:
        print(f"\nВЕРДИКТ: ПРОБА НЕ СХОДИТСЯ -- выжили: {survived}")
        return 1
    print("\nВЕРДИКТ: ВСЕ ОЖИДАНИЯ СХОДЯТСЯ -- 5/5 KILLED (по одному на находку)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
