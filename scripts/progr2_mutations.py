# scripts/progr2_mutations.py
# Task PROGR-2 -- мутационный прогон графа пайплайна.
# Каждый мутант -- точечная порча контракта spec_progress.md (§2/§3/
# §12 п.2/п.10) в app/core/pipeline_graph.py. Мутант прогоняется против
# собственного сьюта задачи (tests/api/test_pipeline_graph.py) И
# оракулов (scripts/progr2_oracles.py). KILLED = хотя бы один красный.
# Файл восстанавливается после каждого мутанта, sha256 верифицируется.
"""Мутационный прогон (Task PROGR-2). Запуск: python3 scripts/progr2_mutations.py."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE = REPO_ROOT / "app" / "core" / "pipeline_graph.py"
TESTS = ["tests/api/test_pipeline_graph.py"]
ORACLE = ["scripts/progr2_oracles.py"]

MUTANTS: list[tuple[str, str, str]] = [
    # (id, что портим, подстрока замены)
    ("MUT-01", "§12 п.10: warning теряет precedence (ловит только error)",
     'if any(s in ("warning", "error") for s in values):'),
    ("MUT-02", "свёртка: all-skipped -> passed (граница skipped)",
     'if any(s == "done" for s in values) and all(\n        s in ("done", "skipped") for s in values\n    ):'),
    ("MUT-03", "свёртка: пустая стадия -> passed",
     '    values = list(statuses)\n    if not values:\n        return NODE_FOLD_NOT_STARTED'),
    ("MUT-04", "§2: граф теряет узел forecast_exported",
     '    "forecast_sensitivity_computed", "forecast_exported",\n)'),
    ("MUT-05", "§2: валидация копией вместо импорта реестра",
     '    "validation": VALIDATION_STAGE_IDS,'),
    ("MUT-06", "§12 п.2: eda id вшитой копией вместо чтения JSON",
     'EDA_CHECK_DEFS: tuple[dict[str, str], ...] = _load_eda_check_defs()'),
    ("MUT-07", "§3: mode допустим на любой стадии",
     '            if self.stage not in _MODE_STAGES:'),
    ("MUT-08", "§3: отрицательный summary_count проходит",
     '        if self.summary_count is not None and self.summary_count < 0:'),
    ("MUT-09", "§2: STAGES переставлены (eda <-> modeling)",
     'STAGES: tuple[str, ...] = (\n    "upload", "validation", "preprocessing", "eda", "modeling", "forecasting",\n)'),
    ("MUT-10", "свёртка: частичная работа -> passed",
     '    if any(s == "done" or s in _STARTED_BEYOND_DONE for s in values):\n        return NODE_FOLD_ATTENTION'),
    ("MUT-11", "§12 п.2: загрузчик не валидирует дубликаты id",
     '        if node_id in seen:\n            raise ImportError(f"Дубликат id узла EDA в реестре: {node_id!r}")'),
]

MUTATION_PATCHES: dict[str, tuple[str, str]] = {
    "MUT-01": (
        'if any(s in ("warning", "error") for s in values):',
        'if any(s == "error" for s in values):',
    ),
    "MUT-02": (
        'if any(s == "done" for s in values) and all(\n        s in ("done", "skipped") for s in values\n    ):',
        'if all(s in ("done", "skipped") for s in values):',
    ),
    "MUT-03": (
        '    values = list(statuses)\n    if not values:\n        return NODE_FOLD_NOT_STARTED',
        '    values = list(statuses)\n    if not values:\n        return NODE_FOLD_PASSED',
    ),
    "MUT-04": (
        '    "forecast_sensitivity_computed", "forecast_exported",\n)',
        '    "forecast_sensitivity_computed",\n)',
    ),
    "MUT-05": (
        '    "validation": VALIDATION_STAGE_IDS,',
        '    "validation": ("data_types", "formats", "ranges", "consistency", "uniqueness",\n        "inclusion", "referential", "text_quality", "regularity", "sufficiency"),',
    ),
    "MUT-06": (
        'EDA_CHECK_DEFS: tuple[dict[str, str], ...] = _load_eda_check_defs()',
        'EDA_CHECK_DEFS: tuple[dict[str, str], ...] = ('
        '{"id": "descriptive", "label": "Описательные статистики", "description": "d"}, '
        '{"id": "correlation", "label": "Корреляция (ACF/PACF)", "description": "d"}, '
        '{"id": "ih_analysis", "label": "IH-анализ", "description": "d"}, '
        '{"id": "seasonality", "label": "Сезонность и периодичность", "description": "d"}, '
        '{"id": "stationarity", "label": "Верификация стационарности", "description": "d"}, '
        '{"id": "distribution", "label": "Распределение", "description": "d"}, '
        '{"id": "structural", "label": "Структурные сдвиги", "description": "d"}, '
        '{"id": "feature_select", "label": "Отбор признаков", "description": "d"}, '
        '{"id": "validation_strategy", "label": "Стратегия валидации", "description": "d"}, '
        '{"id": "model_matrix", "label": "Матрица моделей", "description": "d"})',
    ),
    "MUT-07": (
        '            if self.stage not in _MODE_STAGES:',
        '            if False:',
    ),
    "MUT-08": (
        '        if self.summary_count is not None and self.summary_count < 0:',
        '        if False:',
    ),
    "MUT-09": (
        'STAGES: tuple[str, ...] = (\n    "upload", "validation", "preprocessing", "eda", "modeling", "forecasting",\n)',
        'STAGES: tuple[str, ...] = (\n    "upload", "validation", "preprocessing", "modeling", "eda", "forecasting",\n)',
    ),
    "MUT-10": (
        '    if any(s == "done" or s in _STARTED_BEYOND_DONE for s in values):\n        return NODE_FOLD_ATTENTION',
        '    if any(s in _STARTED_BEYOND_DONE for s in values):\n        return NODE_FOLD_ATTENTION',
    ),
    "MUT-11": (
        '        if node_id in seen:\n            raise ImportError(f"Дубликат id узла EDA в реестре: {node_id!r}")',
        '        if False:',
    ),
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr)[-400:]


def main() -> int:
    original = MODULE.read_bytes()
    original_hash = sha256(original)
    backup = REPO_ROOT / "scripts" / ".pipeline_graph_backup.py"
    shutil.copyfile(MODULE, backup)

    killed = 0
    survived: list[str] = []
    errors: list[str] = []
    try:
        for mut_id, description, anchor in MUTANTS:
            patch_old, patch_new = MUTATION_PATCHES[mut_id]
            src = original.decode("utf-8")
            if patch_old not in src:
                errors.append(f"{mut_id}: якорь не найден: {description}")
                continue
            mutated = src.replace(patch_old, patch_new, 1)
            MODULE.write_text(mutated, encoding="utf-8")

            test_rc, test_tail = run([sys.executable, "-m", "pytest", *TESTS,
                                      "-x", "-q", "--no-header", "-p", "no:cacheprovider"])
            oracle_rc, oracle_tail = run([sys.executable, *ORACLE])

            if test_rc != 0 or oracle_rc != 0:
                killed += 1
                print(f"KILLED   {mut_id}: {description}")
            else:
                survived.append(mut_id)
                print(f"SURVIVED {mut_id}: {description}")
    finally:
        shutil.copyfile(backup, MODULE)
        backup.unlink(missing_ok=True)

    restored_hash = sha256(MODULE.read_bytes())
    print(f"\nФайл восстановлен: sha256 {'совпадает' if restored_hash == original_hash else 'НЕ СОВПАДАЕТ (!)'}")
    print(f"Итог: {killed}/{len(MUTANTS)} KILLED, {len(survived)} survived, {len(errors)} errors")
    for err in errors:
        print(f"ERROR {err}")
    for mut_id in survived:
        print(f"ВЫЖИВШИЙ: {mut_id}")
    return 0 if (not survived and not errors and restored_hash == original_hash) else 1


if __name__ == "__main__":
    raise SystemExit(main())
