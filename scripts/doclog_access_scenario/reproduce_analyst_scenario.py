#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Воспроизведение пользовательского сценария тимлида (2026-10-27).

СЦЕНАРИЙ: аналитик загружает демо-датасет forecast_monitor_synthetic_n150.csv
(ПЕРВАЯ демо-карточка вкладки «Загрузка», packages/ui/lib/demoDatasets.ts;
CSV здесь -- НАСТОЯЩИЕ байты TS-генератора, дамп dump_demo_csv.mjs), проходит
весь этап «Загрузка» (Структура: подтверждение одномерного ряда
target=value/date=date; Паспорт свойств ряда -- passport/start), нажимает
кнопку «Документы» -- и все виды документов в модуле «Версии» отвечают:
«Доступ запрещён -- документы этого исследования недоступны вашему субъекту».

МЕТОД: изолированный TestClient, disposable Memory-сторы
(CISSTAT_*_BACKEND=memory, CISSTAT_IDENTITY_MODE=session_scoped -- честный
дефолт прод-развёртывания Render/Vercel), без DATABASE_URL/REDIS_URL/ключей.
Никаких патчей продукта; только наблюдение HTTP-контракта, решающей таблицы
identity и durable audit-потока.

ВОСПРОИЗВОДИМЫЕ ВЕТВИ:
  S1  Здоровый путь владельца: список документов 200 (пустой реестр,
      §12.1 «открытие не создаёт документ фактом открытия»).
  S2  Здоровый путь владельца: создать черновик D02 (Паспорт свойств
      ряда) -> PDF- rendition -> скачать содержимое. Владелец МОЖЕТ скачать.
  S3a ЧУЖАЯ cookie-сессия (новый браузер / инкогнито / другой профиль /
      второй человек): list 404 + revision 404 («Запуск не найден» /
      «Документ недоступен»), audit reason=foreign_session.
  S3b АНОНИМ (cookie не дошла до API): list 404, reason=anonymous.
  S4  ПОТЕРЯ RUN при живой сессии (симуляция рестарта/выселения free-tier
      процесса с Memory-сторами при частично durable-сессии; ЭКВИВАЛЕНТ
      наблюдаемого симптома: trace отдаёт run_id, список отвечает 404 ->
      UI «Доступ запрещён»).
  S5  Полный рестарт (все Memory-сторы пусты): trace -> run_id=null ->
      UI-фаза no-run («Исследование не выбрано...») -- ДРУГОЕ сообщение,
      не запрет. Дифференцирует наблюдаемый симптом.
  S6  Контраст режима: CISSTAT_IDENTITY_MODE=dev_single_user -- чужой
      клиент получает 200 (почему локальная демонстрация не видит отказа).

ВЫВОД: protocols/scenario.json + консольный протокол.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "protocols"
CSV_PATH = Path(__file__).resolve().parent / "forecast_monitor_synthetic_n150.csv"
import sys  # noqa: E402

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

UI_FORBIDDEN_TEXT = (
    "Доступ запрещён — документы этого исследования недоступны вашему субъекту"
)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    csv_bytes = CSV_PATH.read_bytes()
    results = {
        "base": "79044e8c91195dcb54969da5b34b77dcd15941da",
        "scope": ("isolated TestClient; disposable memory stores; actual TS demo bytes; "
                  "CISSTAT_IDENTITY_MODE=session_scoped (prod default)"),
        "csv_sha256": hashlib.sha256(csv_bytes).hexdigest(),
        "csv_bytes": len(csv_bytes),
        "ui_forbidden_text": UI_FORBIDDEN_TEXT,
        "steps": [],
        "variants": {},
    }
    with tempfile.TemporaryDirectory(prefix="doclog-access-", dir=ROOT.parent) as tmp:
        for name in ("DATABASE_URL", "REDIS_URL", "CISSTAT_API_KEYS", "ALLOWED_ORIGINS"):
            os.environ.pop(name, None)
        os.environ.update(
            CISSTAT_DATA_DIR=tmp,
            CISSTAT_STORAGE_MODE="advisory",
            CISSTAT_RUNS_BACKEND="memory",
            CISSTAT_SESSION_BACKEND="memory",
            CISSTAT_ARTIFACTS_BACKEND="memory",
            CISSTAT_DOCUMENTS_BACKEND="memory",
            CISSTAT_SNAPSHOTS_BACKEND="memory",
            CISSTAT_IDENTITY_MODE="session_scoped",
            CISSTAT_DELIVERY_WORKER_ENABLED="0",
            CISSTAT_DOCUMENT_RENDER_WORKER_ENABLED="0",
        )
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from apps.api.session_store import (
            SESSION_COOKIE_NAME,
            get_session_store,
        )
        from apps.api.research_runs import get_research_run_store
        from apps.api.identity import get_identity_mode
        from apps.api.security_audit import get_audit_sink

        with TestClient(app) as analyst:
            # ── Этап «Загрузка»: настоящий путь аналитика ────────────────
            def call(client, method, path, **kwargs):
                response = client.request(method, path, **kwargs)
                try:
                    body = response.json()
                except Exception:
                    body = response.text
                results["steps"].append(
                    {"method": method, "path": path, "status": response.status_code}
                )
                return response.status_code, body

            # Демо-карточка -> doUpload(file) -> POST /v1/internal/upload
            status, upload = call(analyst, "POST", "/v1/internal/upload",
                                  files={"file": (CSV_PATH.name, csv_bytes, "text/csv")})
            assert status == 200, (status, upload)
            # Структура: подтверждение одномерного ряда (target/date)
            call(analyst, "POST", "/v1/session/target-column", json={"column": "value"})
            call(analyst, "POST", "/v1/session/date-column", json={"column": "date"})
            # Паспорт свойств ряда
            status, start = call(analyst, "POST", "/v1/session/dataset/passport/start")
            assert status == 200 and start.get("snapshot_id"), (status, start)
            status, trace = call(analyst, "GET", "/v1/progress/trace")
            run_id = trace["run_id"]
            assert run_id, trace
            results["stage_upload"] = {
                "rows": upload["rows"], "run_id": run_id,
                "passport_snapshot": start.get("snapshot_id"),
                "analyst_cookie_session": analyst.cookies.get(SESSION_COOKIE_NAME),
            }

            base_url = f"/v1/documentation/runs/{run_id}/documents"

            # ── S1: владелец открывает «Документы» (здоровый контур) ────
            status, docs = call(analyst, "GET", base_url)
            assert status == 200, (status, docs)
            results["variants"]["S1_owner_list_ok"] = {
                "status": status,
                "documents_count": len(docs["documents"]),
                "ui_phase": "empty" if not docs["documents"] else "ready",
                "ui_message_if_empty": "Документов пока нет — соберите черновик нужного вида",
                "note": "§12.1: открытие раздела не создаёт документ фактом открытия",
            }

            # ── S2: владелец создаёт черновик D02 и СКАЧИВАЕТ pdf ───────
            status, created = call(analyst, "POST", base_url,
                                   json={"kind": "D02", "refresh": True})
            assert status == 201, (status, created)
            revision_id = created["revision"]["revision_id"]
            status, rendition = call(
                analyst, "POST",
                f"/v1/documentation/revisions/{revision_id}/renditions",
                json={"format": "pdf"})
            assert status in (201, 202), (status, rendition)
            job = rendition["job"]
            content_status, content = 0, None
            # pdf -- тяжёлый формат (§7 P1): queued -> рендерит worker
            # (в этой среде CISSTAT_DOCUMENT_RENDER_WORKER_ENABLED=0,
            # прогоняем worker вручную -- паритет reproduce_scenario.py
            # аудита DOCLOG-E2E-RECHECK-1).
            job_id = job["job_id"]
            if job["state"] == "queued":
                from apps.api.document_render_worker import DocumentRenderWorker
                worker_summary = DocumentRenderWorker().run_once()
                results["variants"]["S2_owner_download_ok"] = {
                    "worker_summary": worker_summary}
            for _ in range(10):
                status, job_body = call(analyst, "GET",
                                        f"/v1/documentation/jobs/{job_id}")
                assert status == 200, (status, job_body)
                job = job_body["job"]
                if job["state"] in ("ready", "failed", "cancelled"):
                    break
            assert job["state"] == "ready", job
            rendition_id = job["rendition"]["rendition_id"]
            resp = analyst.get(f"/v1/documentation/renditions/{rendition_id}/content")
            content_status = resp.status_code
            content = resp.content
            assert content_status == 200, resp.text
            s2 = results["variants"].setdefault("S2_owner_download_ok", {})
            s2.update({
                "kind": "D02",
                "revision_id": revision_id,
                "pdf_status": content_status,
                "pdf_sha256": hashlib.sha256(content).hexdigest(),
                "pdf_bytes": len(content),
                "note": "владелец скачивает документы своего исследования",
            })

            # ── S3a: ЧУЖАЯ cookie-сессия (новый браузер аналитика) ──────
            with TestClient(app) as foreign:
                # чужой браузер сначала получает СВОЮ сессию (cookie)
                call(foreign, "GET", "/v1/progress/trace")
                foreign_session = foreign.cookies.get(SESSION_COOKIE_NAME)
                status, body = call(foreign, "GET", base_url)
                assert status == 404, (status, body)
                list_detail = body
                status_r, body_r = call(
                    foreign, "GET", f"/v1/documentation/revisions/{revision_id}")
                assert status_r == 404, (status_r, body_r)
                results["variants"]["S3a_foreign_session"] = {
                    "list_status": status, "list_detail": list_detail,
                    "revision_status": status_r, "revision_detail": body_r,
                    "foreign_session_cookie": foreign_session,
                    "ui_phase": "forbidden",
                    "ui_message": UI_FORBIDDEN_TEXT,
                    "audit_reason_expected": "foreign_session",
                }

            # ── S3b: АНОНИМ (cookie вообще не дошла до API) ─────────────
            with TestClient(app) as anonymous:
                status_a, body_a = call(anonymous, "GET", base_url)
                assert status_a == 404, (status_a, body_a)
                results["variants"]["S3b_anonymous"] = {
                    "list_status": status_a, "list_detail": body_a,
                    "ui_phase": "forbidden",
                    "ui_message": UI_FORBIDDEN_TEXT,
                    "audit_reason_expected": "anonymous",
                }

            # ── S6: контраст режима dev_single_user ─────────────────────
            # (почему локальная демонстрация НЕ воспроизводит отказ).
            # Выполняется ДО симуляций потери: run ещё существует.
            with TestClient(app) as dev:
                call(dev, "GET", "/v1/progress/trace")
                previous_mode = get_identity_mode()
                os.environ["CISSTAT_IDENTITY_MODE"] = "dev_single_user"
                try:
                    status_dev, docs_dev = call(dev, "GET", base_url)
                finally:
                    os.environ["CISSTAT_IDENTITY_MODE"] = previous_mode
                assert status_dev == 200, (status_dev, docs_dev)
                results["variants"]["S6_dev_single_user_contrast"] = {
                    "mode": "dev_single_user",
                    "foreign_list_status": status_dev,
                    "documents_count": len(docs_dev.get("documents", []))
                    if status_dev == 200 else None,
                    "note": ("в dev-режиме cross-session доступ разрешён и "
                             "помечен reason=dev_single_user_isolated -- "
                             "локально отказ не увидеть"),
                }

            # ── S4: ПОТЕРЯ RUN при живой сессии (симуляция рестарта) ────
            # Memory-сторы процесса теряются при рестарте/выселении
            # free-tier инстанса (advisory-режим, H29). Моделируем ЧАСТИЧНУЮ
            # потерю: сессия пережила рестарт (durable/кэш), run-стор пуст.
            store = get_research_run_store()
            assert hasattr(store, "_runs"), type(store)
            with store._lock:
                store._runs.clear()
                store._events.clear()
                store._checkpoints.clear()
            status_t, trace_after = call(analyst, "GET", "/v1/progress/trace")
            status_d, docs_after = call(analyst, "GET", base_url)
            assert status_d == 404, (status_d, docs_after)
            results["variants"]["S4_run_lost_session_alive"] = {
                "trace_status": status_t,
                "trace_run_id_still_returned": trace_after.get("run_id"),
                "trace_projection_source": trace_after.get("projection_source"),
                "trace_projection_complete": trace_after.get("projection_complete"),
                "documents_status": status_d,
                "documents_detail": docs_after,
                "ui_phase": "forbidden",
                "ui_message": UI_FORBIDDEN_TEXT,
                "note": ("ЭКВИВАЛЕНТ наблюдаемого симптома: run_id ещё "
                         "возвращается из записи сессии (advisory-деградация "
                         "session_tail), список документов -- 404; UI "
                         "показывает «Доступ запрещён» вместо честного "
                         "«исследование потеряно средой»"),
            }

            # ── S5: ПОЛНЫЙ рестарт (и сессия тоже потеряна) ─────────────
            # Memory session-стор теряется тем же рестартом (один процесс).
            session_store = get_session_store()
            assert hasattr(session_store, "_sessions"), type(session_store)
            session_store._sessions.clear()
            status_t2, trace2 = call(analyst, "GET", "/v1/progress/trace")
            status_d2, docs2 = call(analyst, "GET", base_url)
            results["variants"]["S5_full_restart"] = {
                "trace_status": status_t2,
                "trace_run_id": trace2.get("run_id"),
                "documents_status": status_d2,
                "documents_detail": docs2,
                "ui_phase_if_run_null": "no-run",
                "ui_message_if_run_null": (
                    "Исследование не выбрано — откройте раздел из исследования "
                    "(«Прогресс» → «Документы») или передайте ?run=…; это не "
                    "пустой реестр активного датасета"),
                "note": ("Полная потеря памяти процесса даёт ДРУГОЕ сообщение "
                         "(no-run), не «Доступ запрещён»: run_id уже не "
                         "возвращается"),
            }

        # ── Durable audit-поток: сервер ЗНАЕТ настоящую причину ────────
        records = get_audit_sink().list_recent(limit=200)
        access = [
            {
                "action": r.get("action"),
                "outcome": r.get("outcome"),
                "reason_code": (r.get("details") or {}).get("reason_code"),
                "run_id": r.get("run_id"),
                "actor_via": r.get("actor_via"),
            }
            for r in records
            if r.get("action") in ("run_access_allowed", "run_access_denied")
        ]
        results["audit_run_access_decisions"] = access

    (OUT / "scenario.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2))
    # ── Консольный протокол ───────────────────────────────────────────
    print(json.dumps({
        "run_id": results.get("stage_upload", {}).get("run_id"),
        "S1_owner_list": results["variants"]["S1_owner_list_ok"]["status"],
        "S2_owner_download_pdf_bytes":
            results["variants"]["S2_owner_download_ok"]["pdf_bytes"],
        "S3a_foreign_list": results["variants"]["S3a_foreign_session"]["list_status"],
        "S3b_anonymous_list": results["variants"]["S3b_anonymous"]["list_status"],
        "S4_run_lost": {
            "trace_run_id": results["variants"]["S4_run_lost_session_alive"]
            ["trace_run_id_still_returned"],
            "documents": results["variants"]["S4_run_lost_session_alive"]
            ["documents_status"]},
        "S5_full_restart": {
            "trace_run_id": results["variants"]["S5_full_restart"]["trace_run_id"],
            "documents": results["variants"]["S5_full_restart"]["documents_status"]},
        "S6_dev_single_user_foreign_list":
            results["variants"]["S6_dev_single_user_contrast"]["foreign_list_status"],
        "audit_decisions": len(results["audit_run_access_decisions"]),
        "protocol": str(OUT / "scenario.json"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
