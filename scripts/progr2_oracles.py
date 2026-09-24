# scripts/progr2_oracles.py
# Task PROGR-2 -- независимые оракул-тесты на СВОИХ данных аудитора.
# Не импортируют tests/api/test_pipeline_graph.py: ожидания закодированы
# независимо из текста spec_progress.md (§2, §3, §12 п.2/п.10), данные
# синтетические (своя нумерация стадий, свои статусы/причины/счётчики).
"""Оракул-проверки графа пайплайна (Task PROGR-2).

Группы:
  A. Граф §2 -- 6 стадий, 46 узлов, идентичность реестрам, EDA из JSON.
  B. Модель узла §3 -- словари статусов по классу стадии, mode, счётчик.
  C. Свёртка §12 п.10 -- полная матрица на своих комбинациях статусов,
     включаяprecedence-кейс «все done, один error -> жёлтый».
  D. Общий JSON §12 п.2 -- структурные инварианты и дословные строки
     .tsx после рефакторинга.
Запуск: python3 scripts/progr2_oracles.py  (exit 0 = все оракулы зелёные).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.pipeline_graph import (  # noqa: E402
    EDA_STAGE_IDS,
    PROCESS_STATUS_VALUES,
    STAGES,
    STAGE_NODES,
    TOTAL_NODE_COUNT,
    PipelineNodeState,
    fold_stage_status,
    fold_status_values,
    is_known_node,
    make_node_state,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FAILED: list[str] = []
PASSED = 0


def oracle(name: str, condition: bool, detail: str = "") -> None:
    global PASSED
    if condition:
        PASSED += 1
        print(f"  PASS {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL {name} {detail}")


# ── A. Граф §2 ────────────────────────────────────────────────────

print("A. Граф §2 (6 стадий / 46 узлов, идентичность реестрам)")
oracle("A1 шесть стадий в порядке спецификации", STAGES == (
    "upload", "validation", "preprocessing", "eda", "modeling", "forecasting"))
oracle("A2 всего 46 узлов", TOTAL_NODE_COUNT == 46, str(TOTAL_NODE_COUNT))
oracle("A3 upload = structure_confirmed", STAGE_NODES["upload"] == ("structure_confirmed",))
oracle("A4 валидация 10 узлов", len(STAGE_NODES["validation"]) == 10)
oracle("A5 предобработка 10 узлов", len(STAGE_NODES["preprocessing"]) == 10)
oracle("A6 eda 10 узлов", len(STAGE_NODES["eda"]) == 10)
oracle("A7 моделирование 11 узлов", len(STAGE_NODES["modeling"]) == 11)
oracle("A8 прогнозирование 4 узла", len(STAGE_NODES["forecasting"]) == 4)
oracle("A9 forecasting-узлы = 4 типа события §5.9", STAGE_NODES["forecasting"] == (
    "forecast_generated", "forecast_compared",
    "forecast_sensitivity_computed", "forecast_exported"))

# Своя независимая кодировка реестров (из §2, не из исходников реестров).
own_modeling = (
    "problem_definition", "data_structure", "constraint_mapping",
    "candidate_generation", "baseline_estimation", "backtest", "tuning",
    "diagnostics", "comparison", "selection", "model_card",
)
oracle("A10 modeling дословно §2", STAGE_NODES["modeling"] == own_modeling)
own_eda = (
    "descriptive", "correlation", "ih_analysis", "seasonality",
    "stationarity", "distribution", "structural", "feature_select",
    "validation_strategy", "model_matrix",
)
oracle("A11 eda дословно §2", EDA_STAGE_IDS == own_eda)
oracle("A12 stationarity легитимно в двух стадиях",
       is_known_node("preprocessing", "stationarity")
       and is_known_node("eda", "stationarity")
       and not is_known_node("modeling", "stationarity"))
oracle("A13 граф не содержит узел passport",
       all("passport" not in nodes for nodes in STAGE_NODES.values()))

# ── B. Модель узла §3 (свои данные) ───────────────────────────────

print("B. Модель узла §3 (свои данные: свой reason/count/timestamp)")
node = make_node_state(
    "preprocessing", "outliers", status="warning",
    status_reason="IQR-множитель 1.5: 4 кандидата",
    mode="enabled", last_touched_at="2026-09-24T09:30:00+03:00", summary_count=4,
)
oracle("B1 узел хранит все поля §3",
       (node.stage, node.node_id, node.status, node.status_reason, node.mode,
        node.last_touched_at, node.summary_count)
       == ("preprocessing", "outliers", "warning",
           "IQR-множитель 1.5: 4 кандидата", "enabled",
           "2026-09-24T09:30:00+03:00", 4))
try:
    node.status = "done"  # type: ignore[misc]
    oracle("B2 узел заморожен", False)
except Exception:
    oracle("B2 узел заморожен", True)
try:
    make_node_state("forecasting", "forecast_generated", status="skipped")
    oracle("B3 StageStatus-стадия отвергает CheckStatus", False)
except ValueError:
    oracle("B3 StageStatus-стадия отвергает CheckStatus", True)
try:
    make_node_state("validation", "sufficiency", mode="auto")
    oracle("B4 mode валиден на Валидации", True)
except ValueError:
    oracle("B4 mode валиден на Валидации", False)
try:
    make_node_state("upload", "structure_confirmed", status="warning")
    oracle("B5 warning выразим на Загрузке (UPLOAD-1)", True)
except ValueError:
    oracle("B5 warning выразим на Загрузке (UPLOAD-1)", False)
oracle("B6 словари статусов §3",
       set(PROCESS_STATUS_VALUES) == {"pending", "in_progress", "done"})

# ── C. Свёртка §12 п.10 (своя матрица, свои длины) ────────────────

print("C. Свёртка §12 п.10 (полная матрица на своих комбинациях)")
cases: list[tuple[str, list[str], str]] = [
    ("C1 пустая стадия", [], "not_started"),
    ("C2 всё pending", ["pending"] * 7, "not_started"),
    ("C3 всё skipped", ["skipped"] * 7, "not_started"),
    ("C4 pending+skipped", ["pending", "skipped"] * 3, "not_started"),
    ("C5 всё done", ["done"] * 7, "passed"),
    ("C6 done+skipped с done", ["done", "skipped", "done", "skipped"], "passed"),
    ("C7 один warning среди done", ["done"] * 6 + ["warning"], "attention"),
    ("C8 один error среди done", ["done"] * 6 + ["error"], "attention"),
    ("C9 warning первый", ["warning"] + ["done"] * 6, "attention"),
    ("C10 error+warning вместе", ["error", "warning", "done", "done"], "attention"),
    ("C11 частичная работа", ["done", "done", "pending"] * 2, "attention"),
    ("C12 running", ["pending", "running", "pending"], "attention"),
    ("C13 in_progress", ["in_progress", "pending"], "attention"),
    ("C14 done+in_progress+pending", ["done", "in_progress", "pending"], "attention"),
    ("C15 всё running", ["running"] * 4, "attention"),
    ("C16 warning без done", ["warning"], "attention"),
    ("C17 warning среди pending", ["pending", "warning", "pending"], "attention"),
    ("C18 error среди skipped", ["skipped", "error"], "attention"),
]
for name, statuses, expected in cases:
    got = fold_status_values(statuses)
    oracle(f"{name} -> {expected}", got == expected, f"получено {got!r}")

# Свёртка по узлам -- свои узлы с метаданными, игнорирующими агрегат.
nodes = [
    make_node_state("eda", "descriptive", status="done", summary_count=12),
    make_node_state("eda", "correlation", status="done"),
    make_node_state("eda", "ih_analysis", status="error", status_reason="падение перестановочной проверки"),
]
oracle("C19 fold_stage_status по узлам", fold_stage_status(nodes) == "attention")
same_status_different_meta = [
    make_node_state("eda", "descriptive", status="done"),
    make_node_state("eda", "correlation", status="done"),
    make_node_state("eda", "ih_analysis", status="error"),
]
oracle("C20 метаданные не влияют на свёртку",
       fold_stage_status(nodes) == fold_stage_status(same_status_different_meta))

# Своя генерация: все пары (позиция проблемы, тип проблемы) на 11 узлах
# моделирования -- §12 п.10 обязан держать для КАЖДОЙ позиции.
for pos in range(11):
    statuses = ["done"] * 11
    statuses[pos] = "error" if pos % 2 == 0 else "warning"
    if fold_status_values(statuses) != "attention":
        oracle(f"C21 позиция {pos}", False)
        break
else:
    oracle("C21 каждая позиция warning/error перекрашивает 11-узловую стадию", True)

try:
    fold_status_values(["done", "exploded"])
    oracle("C22 неизвестный статус fail-closed", False)
except ValueError:
    oracle("C22 неизвестный статус fail-closed", True)

# ── D. Общий JSON §12 п.2 ─────────────────────────────────────────

print("D. Общий JSON §12 п.2")
raw = json.loads((REPO_ROOT / "shared" / "pipeline_nodes" / "eda_checks.json").read_text(encoding="utf-8"))
oracle("D1 stage=eda", raw.get("stage") == "eda")
oracle("D2 10 узлов", len(raw["nodes"]) == 10)
oracle("D3 id уникальны", len({n["id"] for n in raw["nodes"]}) == 10)
oracle("D4 ids == EDA_STAGE_IDS модуля", tuple(n["id"] for n in raw["nodes"]) == EDA_STAGE_IDS)
tsx = (REPO_ROOT / "packages" / "ui" / "components" / "TsAnalysisEDA.tsx").read_text(encoding="utf-8")
oracle("D5 .tsx импортирует JSON", "shared/pipeline_nodes/eda_checks.json" in tsx)
oracle("D6 .tsx не держит вшитый литерал CHECKS", '{ id: "descriptive", label:' not in tsx)
oracle("D7 дословная строка метки descriptive",
       any(n["label"] == "Описательные статистики" for n in raw["nodes"]))

print(f"\nИтог: {PASSED} PASS / {len(FAILED)} FAIL")
if FAILED:
    print("Упавшие оракулы:", ", ".join(FAILED))
    raise SystemExit(1)
print("ВСЕ ОРАКУЛЫ ЗЕЛЁНЫЕ")
