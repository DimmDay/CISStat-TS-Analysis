#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Репродукция дефектов панели «Прогресс» (постановка тимлида, 2026-10-02).

Сценарий пользователя (дословно):
  1. Загружаю датасет forecast_monitor_synthetic_n150.csv.
  2. Модуль «Загрузка»: Превью/График/Распределение -- зелёные,
     Структура и Качество -- жёлтые. Фиксирую свойства в Паспорте.
  3. Открываю «Прогресс»: ДЕФЕКТ 1 -- в стадии «Загрузка» видна ТОЛЬКО
     одна остановка «Структура данных», и она ЗЕЛЁНАЯ, хотя в самом
     модуле «Структура» ЖЁЛТАЯ; остальные остановки в прогрессе вообще
     отсутствуют.
  4. Нажимаю «Наставник»: ДЕФЕКТ 2 -- «Идёт этап «Валидация»…», хотя
     пользователь НЕ переходил на стадию «Валидация».

Скрипт эмулирует фронтенд-поток честно (те же HTTP-вызовы в том же
порядке, включая АВТО-POST /target-column из useTargetColumn
-- packages/ui/hooks/useTargetColumn.ts, fetchAndMaybeAutoSelect) и
печатает фактические ответы API.

Запуск: python3 scripts/progr13_repro_defects.py
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Долговременный слой -- in-memory (как в тестах; DATABASE_URL на хосте нет).
os.environ.setdefault("CISSTAT_RUNS_BACKEND", "memory")

import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from apps.api.main import app  # noqa: E402
from apps.api.session_store import (  # noqa: E402
    SESSION_COOKIE_NAME,
    get_session_store,
    reset_session_store_for_testing,
)

CSV_PATH = Path("/tmp/forecast_monitor_synthetic_n150.csv")


def section(title: str) -> None:
    print(f"\n{'=' * 72}\n== {title}\n{'=' * 72}")


def main() -> None:
    client = TestClient(app)
    reset_session_store_for_testing()
    try:
        # ── Шаг 1: загрузка датасета (модуль «Загрузка») ──────────────
        section("ШАГ 1. POST /v1/internal/upload (forecast_monitor_synthetic_n150.csv)")
        csv_text = CSV_PATH.read_text(encoding="utf-8")
        response = client.post(
            "/v1/internal/upload",
            files={"file": ("forecast_monitor_synthetic_n150.csv",
                            io.BytesIO(csv_text.encode()), "text/csv")},
        )
        print(f"HTTP {response.status_code}; rows={response.json().get('rows')}, "
              f"columns={response.json().get('columns')}")

        # ── Шаг 2: авто-POST target-column (фронтенд делает это САМ) ──
        # packages/ui/hooks/useTargetColumn.ts::fetchAndMaybeAutoSelect:
        # target_column в сессии null (set_dataset сбросил), suggested есть
        # -> хук МОЛЧА постит suggested_column. Пользователь ничего не нажимал.
        section("ШАГ 2. GET/POST /v1/session/target-column (автовыбор хука "
                "useTargetColumn -- пользователь не нажимал ничего)")
        current = client.get("/v1/session/target-column").json()
        print(f"GET  -> target_column={current.get('target_column')!r}, "
              f"suggested={current.get('suggested_column')!r}")
        if current.get("target_column") is None and current.get("suggested_column"):
            chosen = client.post(
                "/v1/session/target-column", json={"column": current["suggested_column"]}
            ).json()
            print(f"POST (АВТО) -> target_column={chosen.get('target_column')!r}")

        # ── Шаг 2b: отчёт фактов остановок (PROGR-13-A5) ─────────────
        # Модуль «Загрузка» вычислил stopStatus из СВОИХ данных
        # (TsAnalysisUpload.tsx::stopStatus) и отчитывает снапшот
        # POST /v1/progress/upload-stops. Для датасета сценария модуль
        # показывает: Превью/График/Распределение -- зелёные,
        # Структура/Качество -- жёлтые (confidence<70 / счётчики проблем).
        section("ШАГ 2b. POST /v1/progress/upload-stops (PROGR-13-A5: модуль "
                "отчитывает stopStatus -- прецедент §7.2)")
        module_stops = {
            "overview": "done",
            "chart": "done",
            "distribution": "done",
            "structure": "warning",
            "quality": "warning",
        }
        stops_resp = client.post("/v1/progress/upload-stops", json={"stops": module_stops})
        if stops_resp.status_code == 200:
            print(f"POST /upload-stops -> HTTP {stops_resp.status_code} "
                  f"({stops_resp.json().get('reported')} фактов)")
        else:
            print(f"POST /upload-stops -> HTTP {stops_resp.status_code}")

        # В UI пользователь на остановке «Структура» подтверждает дату
        # (POST /date-column), затем в Паспорте жмёт «Зафиксировать».
        section("ШАГ 3. POST /v1/session/date-column + POST /v1/session/dataset/passport/start "
                "(«Структура» + кнопка «Зафиксировать» в Паспорте)")
        date_resp = client.post("/v1/session/date-column", json={"column": "date"})
        print(f"POST /date-column -> HTTP {date_resp.status_code}")
        # PROGR-13-A5: ре-пост снапшота после подтверждения даты
        # (onDateColumnConfirmed -> reportUploadStopsNow): модуль всё ещё
        # показывает жёлтую «Структуру» (confidence<70) -- панель обязана
        # остаться зеркалом модуля (хронология: последнее событие узла).
        re_post = client.post("/v1/progress/upload-stops", json={"stops": module_stops})
        print(f"POST /upload-stops (ре-пост A5) -> HTTP {re_post.status_code}")
        capture = client.post("/v1/session/dataset/passport/start")
        body = capture.json() if capture.status_code == 200 else {}
        print(f"POST /passport/start -> HTTP {capture.status_code} "
              f"({str(body.get('fingerprint', ''))[:12]}…)")

        # ── Шаг 4: открываю «Прогресс» ────────────────────────────────
        section("ШАГ 4. GET /v1/progress/trace (панель «Прогресс»)")
        trace = client.get("/v1/progress/trace").json()
        print(f"run_id={trace.get('run_id')}")
        print("События трассы (хронология):")
        for event in trace.get("events", []):
            print(f"  - ts={event.get('ts', '')[:19]} stage={event.get('stage')!r:15} "
                  f"node={str(event.get('node_id')):22} type={event.get('event_type')}")
        print("\nСтадии (карточки блок-схемы, ответ бэкенда):")
        for stage in trace.get("stages", []):
            print(f"  {stage['stage']:14} fold={stage['fold']:12} "
                  f"done={stage['done_count']}/{stage['total_nodes']} "
                  f"warning={stage['warning_nodes']}")
        print("\nУзлы стадии upload (то, что видит панель):")
        for node in trace.get("nodes", []):
            if node["stage"] == "upload":
                print(f"  {node['stage']}/{node['node_id']}: status={node['status']!r} "
                      f"reason={node.get('status_reason')!r}")

        # ── Шаг 5: «Наставник» ────────────────────────────────────────
        section("ШАГ 5. GET /v1/progress/runs/{run_id}/mentor/next-step (кнопка «Наставник»)")
        run_id = trace.get("run_id")
        mentor = client.get(f"/v1/progress/runs/{run_id}/mentor/next-step").json()
        print(f"last_active_stage = {mentor.get('last_active_stage')!r}")
        print(f"phase_text        = {mentor.get('phase_text')!r}")
        rec = mentor.get("recommendation")
        print(f"recommendation    = {rec['rule_id']!r} ({rec.get('recommended_action')!r})"
              if rec else "recommendation    = None")

        # ── Шаг 5b: вариант БЕЗ фиксации паспорта ────────────────────
        # (если аналитик только загрузил файл и посмотрел остановки)
        section("ШАГ 5b. Вариант: загрузка + автовыбор признака, БЕЗ паспорта")
        client2 = TestClient(app)
        client2.post(
            "/v1/internal/upload",
            files={"file": ("forecast_monitor_synthetic_n150.csv",
                            io.BytesIO(csv_text.encode()), "text/csv")},
        )
        current2 = client2.get("/v1/session/target-column").json()
        if current2.get("target_column") is None and current2.get("suggested_column"):
            client2.post("/v1/session/target-column", json={"column": current2["suggested_column"]})
        trace2 = client2.get("/v1/progress/trace").json()
        mentor2 = client2.get(
            f"/v1/progress/runs/{trace2.get('run_id')}/mentor/next-step").json()
        print(f"last_active_stage = {mentor2.get('last_active_stage')!r}")
        print(f"phase_text        = {mentor2.get('phase_text')!r}")

        # ── Вердикт ───────────────────────────────────────────────────
        section("ВЕРДИКТ (сопоставление с ожиданием пользователя)")
        upload_stages = next(s for s in trace["stages"] if s["stage"] == "upload")
        upload_nodes = [n for n in trace["nodes"] if n["stage"] == "upload"]
        print(f"ДЕФЕКТ 1: панель показывает остановок стадии «Загрузка»: "
              f"{len(upload_nodes)} "
              f"({[n['node_id'] + '=' + str(trace['node_statuses'].get('upload/' + n['node_id'])) for n in upload_nodes]}), "
              f"карточка fold={upload_stages['fold']!r} "
              f"({upload_stages['done_count']}/{upload_stages['total_nodes']}).")
        print(f"          В самом модуле «Загрузка» остановок ПЯТЬ "
              f"(Превью/График/Распределение зелёные, Структура и Качество -- "
              f"ЖЁЛТЫЕ: confidence<70, счётчики качества). Панель == модулю: "
              f"{all(trace['node_statuses'].get('upload/' + nid) == st for nid, st in module_stops.items())}.")
        print(f"ДЕФЕКТ 2: Наставник говорит «Идёт этап "
              f"«{mentor2.get('last_active_stage')}»» (variant 5b) / "
              f"«{mentor.get('last_active_stage')}» (variant 5), хотя пользователь")
        print(f"          НЕ открывал вкладку «Валидация»: событие "
              f"target_column_changed (stage=validation) засеял АВТО-POST "
              f"хука useTargetColumn на вкладке «Загрузка».")
    finally:
        reset_session_store_for_testing()


if __name__ == "__main__":
    main()
