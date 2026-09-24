# scripts/progr2_extract_eda_checks.py
# Task PROGR-2 -- §12 п.2: вынос EDA CHECKS из TsAnalysisEDA.tsx
# в общий JSON shared/pipeline_nodes/eda_checks.json.
# Извлекает id/label/description ДОСЛОВНО (байт-в-байт строки компонента),
# чтобы рефакторинг .tsx не менял ни одного видимого текста.
"""Извлечение реестра EDA CHECKS в общий JSON (spec_progress.md §12 п.2).

Одноразовый скрипт миграции: читает packages/ui/components/TsAnalysisEDA.tsx,
парсит литерал CHECKS, записывает shared/pipeline_nodes/eda_checks.json.
Повторный запуск перезаписывает файл тем же содержимым (идемпотентен,
пока литерал в .tsx не удалён рефакторингом).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TSX_PATH = REPO_ROOT / "packages" / "ui" / "components" / "TsAnalysisEDA.tsx"
JSON_PATH = REPO_ROOT / "shared" / "pipeline_nodes" / "eda_checks.json"

EXPECTED_IDS = (
    "descriptive", "correlation", "ih_analysis", "seasonality",
    "stationarity", "distribution", "structural", "feature_select",
    "validation_strategy", "model_matrix",
)

# Структура записи литерала (TsAnalysisEDA.tsx, до Task PROGR-2):
#   { id: "descriptive", label: "Описательные статистики", status: "pending", count: null,
#     description: "..." },
ENTRY_RE = re.compile(
    r'\{\s*id:\s*"(?P<id>[a-z_]+)",\s*'
    r'label:\s*"(?P<label>[^"]*)",\s*'
    r'status:\s*"pending",\s*count:\s*null,\s*'
    r'description:\s*"(?P<description>[^"]*)"\s*,?\s*\}',
    re.DOTALL,
)


def main() -> int:
    src = TSX_PATH.read_text(encoding="utf-8")
    entries = [
        {"id": m["id"], "label": m["label"], "description": m["description"]}
        for m in ENTRY_RE.finditer(src)
    ]
    ids = tuple(e["id"] for e in entries)
    if ids != EXPECTED_IDS:
        print(f"FAIL: извлечённые id не совпали с §2: {ids}", file=sys.stderr)
        return 1
    payload = {
        "version": 1,
        "stage": "eda",
        "comment": (
            "Единый реестр 10 исследований EDA -- spec_progress.md §2, §12 п.2 "
            "(Task PROGR-2). Читают оба потребителя: "
            "packages/ui/components/TsAnalysisEDA.tsx (CHECKS) и "
            "app/core/pipeline_graph.py (EDA_STAGE_IDS). Порядок объектов = "
            "порядок остановок степпера. Изменение реестра -- синхронно в "
            "JSON и в рантайм-маппинге статусов TsAnalysisEDA.tsx; тесты "
            "tests/api/test_pipeline_graph.py ловят рассинхрон."
        ),
        "nodes": entries,
    }
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(f"OK: {len(entries)} узлов -> {JSON_PATH.relative_to(REPO_ROOT)}")
    for e in entries:
        print(f"  {e['id']}: {e['label']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
