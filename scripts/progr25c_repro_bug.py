#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""REPRODUCTION: баг тимлида (PROGR-25-C, постановка 2026-10-08).

Сценарий тимлида: аналитик загружает датасет с ЕДИНСТВЕННОЙ числовой
колонкой. Панель «Прогресс» показывает «value (авто)» (задачи A/B/F1),
но Наставник пишет:

    «Исследование на этапе «Загрузка»: структура данных подтверждена.
    Подтвердите целевой признак, чтобы пошли проверки качества.»

Второе предложение ошибочно: просьба «подтвердите» при уже
авто-зафиксированном признаке. Ожидаемое поведение (спека
spec_progress_target_column.md §4-C): «Исследуемый признак выбран
автоматически: value» (без просьбы выбрать).

Скрипт только ВОСПРОИЗВОДИТ и ИЗМЕРЯЕТ (read-only относительно репо):
никаких правок кода. Все обращения к API -- штатные эндпоинты, тот же
TestClient-паттерн, что в tests/api.

Гипотезы:
  H-A: сеемое задачей A событие target_column_changed(source="auto")
       живёт в слое 1 (session.pipeline_trace) и НЕ доходит до слоя 2
       (store.list_events(run_id)), откуда get_mentor_next_step читает
       events (progress.py:1396) -> _target_confirmed=False ->
       правило _upload_structure_done даёт текст-просьбу.
  H-B: событие в слое 2 есть, но условие правила не срабатывает по
       иной причине (порядок правил реестра, payload).
"""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

# Тот же паттерн изоляции, что в tests/api (conftest-фикстуры
# test_progress_progr16/17): Memory-бэкенды обоих хранилищ.
os.environ.pop("DATABASE_URL", None)
os.environ["CISSTAT_RUNS_BACKEND"] = "memory"

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from fastapi.testclient import TestClient  # noqa: E402

from apps.api.main import app  # noqa: E402
from apps.api import research_runs  # noqa: E402
from apps.api.session_store import (  # noqa: E402
    reset_session_store_for_testing,
)

CSV_ONE_NUMERIC = (
    "date,value\n"
    "2023-01-01,10.5\n"
    "2023-01-02,20.1\n"
    "2023-01-03,30.2\n"
)

BUGGY_TEXT = (
    "Исследование на этапе «Загрузка»: структура данных подтверждена. "
    "Подтвердите целевой признак, чтобы пошли проверки качества."
)

client = TestClient(app)


def main() -> int:
    reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()
    try:
        print("=== ШАГ 1: upload датасета с единственной числовой (date,value)")
        file = io.BytesIO(CSV_ONE_NUMERIC.encode("utf-8"))
        resp = client.post(
            "/v1/internal/upload", files={"file": ("single.csv", file, "text/csv")}
        )
        assert resp.status_code == 200, resp.text
        print(f"  upload -> {resp.status_code}")

        print("\n=== ШАГ 2: факт панели /v1/session/current (шапка «Прогресса»)")
        cur = client.get("/v1/session/current").json()
        print(f"  target_column={cur.get('target_column')!r} "
              f"target_column_source={cur.get('target_column_source')!r}")
        panel_ok = cur.get("target_column") == "value" and \
            cur.get("target_column_source") == "auto"
        print(f"  панель: {'«value (авто)» -- ОК' if panel_ok else 'НЕ авто'}")

        print("\n=== ШАГ 3: слой 1 /v1/progress/trace")
        trace = client.get("/v1/progress/trace").json()
        run_id = trace.get("run_id") or ""
        print(f"  run_id={run_id!r} "
              f"target_column={trace.get('target_column')!r} "
              f"target_column_source={trace.get('target_column_source')!r}")
        layer1 = [e for e in trace["events"]
                  if e.get("event_type") == "target_column_changed"]
        print(f"  событий target_column_changed в слое 1: {len(layer1)}")
        for e in layer1:
            print(f"    stage={e.get('stage')!r} node_id={e.get('node_id')!r} "
                  f"run_id={e.get('run_id')!r} payload={json.dumps(e.get('payload'), ensure_ascii=False)}")

        print("\n=== ШАГ 4а: UI-автопревью Загрузки -- POST /date-column "
              "(UploadAutoPreviewPipeline: уверенная дата фиксируется сама, "
              "узел structure становится done)")
        resp = client.post("/v1/session/date-column", json={"column": "date"})
        assert resp.status_code == 200, resp.text
        print(f"  date-column -> {resp.status_code}")

        print("\n=== ШАГ 4б: слой 2 research_runs.list_events(run_id) -- источник Наставника")
        store = research_runs.get_research_run_store()
        layer2 = store.list_events(run_id) if run_id else []
        l2_names = {}
        for e in layer2:
            d = e.to_dict() if hasattr(e, "to_dict") else dict(e)
            l2_names.setdefault(d.get("event_type"), []).append(d)
        print(f"  всего событий слоя 2: {len(layer2)}; типы: "
              f"{sorted(l2_names)}")
        l2_target = l2_names.get("target_column_changed", [])
        print(f"  target_column_changed в слое 2: {len(l2_target)}")
        for d in l2_target:
            print(f"    stage={d.get('stage')!r} payload={json.dumps(d.get('payload'), ensure_ascii=False)}")

        print("\n=== ШАГ 5: Наставник GET /v1/progress/runs/{id}/mentor/next-step")
        resp = client.get(f"/v1/progress/runs/{run_id}/mentor/next-step")
        assert resp.status_code == 200, resp.text
        nxt = resp.json()
        print(f"  last_active_stage={nxt['last_active_stage']!r}")
        print(f"  summary={json.dumps(nxt['summary'], ensure_ascii=False)}")
        print(f"  phase_text={nxt['phase_text']!r}")

        print("\n=== ШАГ 6: вердикт воспроизведения")
        status_ok = nxt["summary"].get("nodes") and any(
            n.get("node_id") == "structure" and n.get("status") == "done"
            for n in []
        ) or nxt["summary"].get("done_count", 0) >= 1
        bug = nxt["phase_text"] == BUGGY_TEXT
        print(f"  структура подтверждена (done_count/узлы): "
              f"done_count={nxt['summary'].get('done_count')}, "
              f"total={nxt['summary'].get('total_nodes')}")
        print(f"  панель показывает авто: {panel_ok}")
        print(f"  Наставник даёт ТЕКСТ-ПРОСЬБУ («Подтвердите целевой признак...»): {bug}")
        print(f"  Событие авто-фиксации в слое 2: {len(l2_target)} "
              f"(H-A подтверждена, если 0)")
        if bug:
            print("\n  БАГ ВОСПРОИЗВЕДЁН: Наставник просит подтвердить признак, "
                  "уже зафиксированный автоматически (задача A).")
        else:
            print("\n  БАГ НЕ воспроизведён этим сценарием -- см. гипотезу H-B.")
        return 0 if bug else 1
    finally:
        reset_session_store_for_testing()
        research_runs.reset_research_run_store_for_testing()


if __name__ == "__main__":
    sys.exit(main())
