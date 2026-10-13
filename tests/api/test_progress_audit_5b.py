# tests/api/test_progress_audit_5b.py
"""AUDIT-5B (plan_progress_audit.md §8): единая полная согласованная
проекция и watermark контура «Прогресс».

Основание аудита: F06/F08/F11 (спека §5), наблюдения P11/P12/P17; карточка
плана §8; контракт docs/progress_audit_contract.md -- инварианты I9
(cap-safety) и I10 (evidence); фундамент 0→S→C→6A.

Контракты задачи (карточка §8, состав):

  PR-1  Один редьюсер и один канонический порядок для панели, Наставника
        и отчёта; источник панели -- ПОЛНЫЙ ledger (слой 2), cap=1000
        ограничивает только отображаемый список, не накопленные
        состояния (I9/P11/F06).
  PR-2  Projection snapshot хранит context, source positions (watermark)
        и сериализуется: replay полного ledger == snapshot+tail;
        restart проекции не теряет ранние статусы.
  PR-3  started_at панели -- run.created_at, не ts первого события
        уцелевшего хвоста (P11).
  PR-4  Historical completion ≠ current validity: факт без известного
        контекста -- unknown, чужой контекст -- stale (не automatic
        current; контракт §3.5).
  PR-5  Каждое поле reason/count ссылается на свой source_event
        (I10); payload невалидного события не меняет детали.
  PR-6  Режимы/контекст из session помечены отдельно от event-derived
        (mode_source="session" vs source_event_id).
  PR-7  Read-after-watermark: consumer видит snapshot не раньше заданной
        позиции либо честное projection_pending (409).
  PR-8  Честная деградация: слой 2 недоступен/запуск не найден --
        проекция помечена неполной (session_tail), не выдаёт хвост за
        полную историю («не выдавать несогласованные snapshots за одну
        позицию истории», карточка §8).

TDD RED → GREEN. На базе a2dcbee (до реализации) API-группы краснеют
ПОВЕДЕНЧЕСКИ (P11/P12/честность), модульные -- ImportError/ImportString
(контрактные API задачи отсутствуют целиком, прецедент RED 6A/CERT).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.research_runs import (
    ResearchRun,
    get_research_run_store,
    reset_research_run_store_for_testing,
)
from apps.api.session_store import (
    SESSION_COOKIE_NAME,
    get_session_store,
    reset_session_store_for_testing,
)
from apps.api.trace_events import make_trace_event

RUN_CREATED_AT = "2026-01-01T00:00:00+00:00"
CTX_A = "ctx-aaaaaaaaaaaaaaaa"
CTX_B = "ctx-bbbbbbbbbbbbbbbb"


@pytest.fixture()
def client():
    reset_session_store_for_testing()
    reset_research_run_store_for_testing()
    with TestClient(app) as test_client:
        yield test_client
    reset_session_store_for_testing()
    reset_research_run_store_for_testing()


# ── Фабрики детерминированного корпуса ───────────────────────────────


def _ts(minutes: int) -> str:
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    return (base + timedelta(minutes=minutes)).isoformat()


def _run_id() -> str:
    """Уникальный run на тест: слой 2 на живом PostgreSQL персистентен
    (сброс singleton не чистит таблицы) -- изоляция через уникальность
    идентичности, а не через схему (урок F-6A2 о тест-гигиене)."""
    return "RUN-5B" + uuid.uuid4().hex[:8].upper()


def _ev(
    event_type: str,
    *,
    run_id: str = "RUN-5B000001",
    stage: str = "validation",
    node_id: str | None = None,
    ts: str,
    payload: dict | None = None,
    event_id: str | None = None,
    sequence: int | None = None,
    context_id: str | None = None,
    actor: str = "user",
):
    """Детерминированное событие канона §4.1 (+ опциональный envelope)."""
    event = make_trace_event(
        event_type,
        stage=stage,
        node_id=node_id,
        run_id=run_id,
        actor=actor,
        **(payload or {}),
    )
    from dataclasses import replace

    event = replace(event, ts=ts)
    if event_id:
        event = replace(event, event_id=event_id)
    if context_id:
        from apps.api.trace_events import stamp_envelope

        event = stamp_envelope(event, context_id=context_id)
    if sequence is not None:
        event = replace(event, sequence=sequence)
    return event


def _seed_session_and_run(
    client: TestClient,
    *,
    run_id: str | None = None,
    events: list,
    created_at: str = RUN_CREATED_AT,
    context_id: str | None = None,
    register_run: bool = True,
    target_column: str | None = "rain",
) -> str:
    """Сессия с cookie + события в слой 1 (с капом) + полный ledger слоя 2.
    Возвращает run_id запуска (уникальный, если не задан явно)."""
    run_id = run_id or _run_id()
    client.get("/v1/progress/trace")  # создаёт сессию и cookie
    session_id = client.cookies.get(SESSION_COOKIE_NAME) or ""
    session = get_session_store().get_or_create(session_id)
    session.run_id = run_id
    for event in events:
        session.append_trace_event(event)
    get_session_store().save(session)
    if register_run:
        store = get_research_run_store()
        store.upsert_run(
            ResearchRun(
                run_id=run_id,
                session_id=session_id,
                dataset_fingerprint="f" * 64,
                dataset_name="5b.csv",
                target_column=target_column,
                created_at=created_at,
                last_active_at=created_at,
                context_id=context_id,
            )
        )
        for event in events:
            store.append_event(run_id, event)
    return run_id


def _big_corpus(total: int = 1050, *, run_id: str = "RUN-5B000001") -> list:
    """Корпус >1000: upload_completed (ранний узел) + хвост проверок.
    ts монотонные, идентичности стабильные; run_id -- тела событий."""
    events = [
        _ev(
            "upload_completed",
            run_id=run_id,
            stage="upload",
            node_id="overview",
            ts=_ts(0),
            payload={"name": "5b.csv"},
            event_id="ev-5b-upload-1",
        )
    ]
    for i in range(1, total):
        events.append(
            _ev(
                "validation_check_status",
                run_id=run_id,
                stage="validation",
                node_id="data_types",
                ts=_ts(i),
                payload={"check_id": "data_types", "status": "done"},
                event_id=f"ev-5b-val-{i:05d}",
            )
        )
    return events


# ── PR-1/PR-2: модуль проекции (контракт) ────────────────────────────


class TestProjectionModuleContract:
    """Контрактные API задачи: build/advance/snapshot/pending/canonical."""

    def test_module_exports_contract_api(self):
        from apps.api import progress_projection as pp

        assert hasattr(pp, "build_projection")
        assert hasattr(pp, "advance_projection")
        assert hasattr(pp, "ProjectionSnapshot")
        assert hasattr(pp, "ProjectionPendingError")
        assert hasattr(pp, "canonical_corpus")

    def test_build_projection_full_replay_watermark_and_started_at(self):
        from apps.api.progress_projection import build_projection

        events = _big_corpus(50)
        corpus = events  # store-порядок == канонический (монотонный ts)
        snapshot = build_projection(
            corpus,
            run_meta={
                "run_id": "RUN-5B000001",
                "created_at": RUN_CREATED_AT,
                "context_id": CTX_A,
            },
        )
        assert snapshot.watermark == 50
        assert snapshot.events_total == 50
        # PR-3: started_at из run.created_at, не из первого события.
        assert snapshot.started_at == RUN_CREATED_AT
        assert snapshot.context_id == CTX_A
        # Единый редьюсер: ранний узел жив (cap-безопасность).
        assert snapshot.node_statuses["upload/overview"] == "done"

    def test_snapshot_roundtrip_and_restart(self):
        from apps.api.progress_projection import build_projection

        corpus = _big_corpus(40)
        snapshot = build_projection(corpus)
        restored = type(snapshot).from_dict(snapshot.to_dict())
        assert restored.node_statuses == snapshot.node_statuses
        assert restored.watermark == snapshot.watermark
        # restart: восстановленный снапшот + хвост == полный replay.
        from apps.api.progress_projection import advance_projection

        tail = [
            _ev(
                "validation_check_status",
                stage="validation",
                node_id="ranges",
                ts=_ts(50),
                payload={"status": "warning"},
                event_id="ev-5b-tail-1",
            )
        ]
        advanced = advance_projection(restored, tail)
        full = build_projection(corpus + tail)
        assert advanced.node_statuses == full.node_statuses
        assert advanced.watermark == full.watermark

    def test_advance_equals_replay_on_load_corpus(self):
        """Нагрузочный корпус (1500 > 2 капов): расщепление в нескольких
        позициях; advance(base, tail) == replay(full) побайтно по
        состояниям; сериализация снапшота переживает roundtrip."""
        from apps.api.progress_projection import (
            advance_projection,
            build_projection,
            canonical_corpus,
        )

        corpus = canonical_corpus(_big_corpus(1500))
        full = build_projection(corpus)
        assert full.watermark == 1500
        for k in (1, 251, 999, 1000, 1499):
            base = build_projection(corpus[:k])
            advanced = advance_projection(base, corpus[k:])
            assert advanced.node_statuses == full.node_statuses, k
            assert advanced.node_states == full.node_states, k
            assert advanced.stage_states == full.stage_states, k
            assert advanced.watermark == full.watermark, k
            # сериализация -- checkpoint проекции
            revived = type(base).from_dict(base.to_dict())
            revived_adv = advance_projection(revived, corpus[k:])
            assert revived_adv.node_statuses == full.node_statuses, k

    def test_min_watermark_pending(self):
        from apps.api.progress_projection import (
            ProjectionPendingError,
            build_projection,
        )

        with pytest.raises(ProjectionPendingError):
            build_projection(_big_corpus(10), min_watermark=11)
        # позиция достигнута -- снапшот отдаётся
        snapshot = build_projection(_big_corpus(10), min_watermark=10)
        assert snapshot.watermark == 10

    def test_p12_sequence_priority_over_ts(self):
        """P12/F08: одинаковый корпус с обратным ts -- проекция по
        sequence (позиция ledger), не по ts; input-порядок не важен."""
        from apps.api.progress_projection import build_projection

        first = _ev(
            "target_column_changed",
            stage="validation",
            node_id=None,
            ts=_ts(10),
            payload={"target_column": "rain"},
            event_id="ev-5b-tc-1",
            sequence=1,
        )
        second = _ev(
            "target_column_cleared",
            stage="validation",
            node_id=None,
            ts=_ts(1),  # ts РАНЬШЕ первого (обратный), sequence 2
            payload={"reset_reason": "type_conversion"},
            event_id="ev-5b-tc-2",
            sequence=2,
        )
        snapshot = build_projection([second, first])  # input в обратном порядке
        # порядок по sequence: cleared ПОСЛЕДНИЙ (выбор снят).
        # reason узла-носителя снят (сброс после выбора).
        states = {s["node_id"]: s for s in snapshot.node_states}
        assert states["sufficiency"]["status_reason"] is None

    def test_p12_equal_ts_legacy_stable_store_order(self):
        """Legacy-корпус (без sequence), одинаковые ts: порядок --
        стабильный store-порядок (не переупорядочивание по часам)."""
        from apps.api.progress_projection import build_projection

        first = _ev(
            "correction_previewed",
            stage="preprocessing",
            node_id="missing",
            ts=_ts(5),
            payload={"total_missing": 7},
            event_id="ev-5b-prev",
        )
        second = _ev(
            "correction_applied",
            stage="preprocessing",
            node_id="missing",
            ts=_ts(5),  # тот же ts
            payload={"rows_removed": 3},
            event_id="ev-5b-appl",
        )
        snapshot = build_projection([first, second])
        states = {s["node_id"]: s for s in snapshot.node_states}
        # append-порядок сохранён: applied последним -> done + его reason.
        assert states["missing"]["status"] == "done"
        assert states["missing"]["status_reason"] == "Коррекция применена"

    def test_p17_dedup_across_sources(self):
        """P17/F11: один факт из двух источников -- один экземпляр;
        watermark считает факты, не копии."""
        from apps.api.progress_projection import build_projection, canonical_corpus

        ledger_event = _ev(
            "forecast_generated",
            stage="forecasting",
            ts=_ts(3),
            payload={"model": "arima"},
            event_id="ev-5b-fc-1",
        )
        artifact_copy = dict(ledger_event.to_dict())  # тот же event_id
        fresh = _ev(
            "forecast_compared",
            stage="forecasting",
            ts=_ts(4),
            payload={"better": "lstm"},
            event_id="ev-5b-fc-2",
        )
        corpus = canonical_corpus(
            [ledger_event.to_dict()], [artifact_copy, fresh.to_dict()]
        )
        snapshot = build_projection(corpus)
        assert snapshot.watermark == 2  # копия снята
        ids = [e["event_id"] for e in snapshot.events]
        assert ids.count("ev-5b-fc-1") == 1

    def test_evidence_and_validity_fields(self):
        """PR-4/PR-5: узлы несут source-ссылки, evidence_level и validity;
        чужой контекст -- stale, отсутствие -- unknown, свой -- current."""
        from apps.api.progress_projection import build_projection

        corpus = [
            _ev(
                "upload_completed",
                stage="upload",
                node_id="overview",
                ts=_ts(0),
                payload={"name": "5b.csv"},
                event_id="ev-5b-up",
                context_id=CTX_A,
            ),
            _ev(
                "validation_check_status",
                stage="validation",
                node_id="data_types",
                ts=_ts(1),
                payload={"check_id": "data_types", "status": "done"},
                event_id="ev-5b-v1",
                context_id=CTX_B,  # чужой контекст
            ),
            _ev(
                "validation_check_status",
                stage="validation",
                node_id="formats",
                ts=_ts(2),
                payload={"check_id": "formats", "status": "done"},
                event_id="ev-5b-v2",
                # legacy: без context_id
            ),
        ]
        snapshot = build_projection(
            corpus,
            run_meta={"run_id": "RUN-5B000001", "context_id": CTX_A,
                      "created_at": RUN_CREATED_AT},
        )
        by_node = {(s["stage"], s["node_id"]): s for s in snapshot.node_states}
        overview = by_node[("upload", "overview")]
        assert overview["source_event_id"] == "ev-5b-up"
        assert overview["validity"] == "current"
        assert overview["evidence_level"] == "server_result"
        data_types = by_node[("validation", "data_types")]
        assert data_types["validity"] == "stale"
        formats = by_node[("validation", "formats")]
        # legacy-факт без контекста -- historical/unknown, не current.
        assert formats["validity"] == "unknown"

    def test_invalid_payload_status_does_not_change_details(self):
        """PR-5 (I10/часть F10): payload-статусное событие с невалидным
        payload не меняет детали узла (reason/count) и учитывается как
        диагностическая аномалия проекции."""
        from apps.api.progress_projection import build_projection

        corpus = [
            _ev(
                "validation_check_status",
                stage="validation",
                node_id="ranges",
                ts=_ts(1),
                payload={"check_id": "ranges", "status": "done"},
                event_id="ev-5b-ok",
            ),
            _ev(
                "validation_check_status",
                stage="validation",
                node_id="ranges",
                ts=_ts(2),
                payload={"check_id": "ranges"},  # невалидно: нет status
                event_id="ev-5b-bad",
            ),
        ]
        snapshot = build_projection(corpus)
        by_node = {(s["stage"], s["node_id"]): s for s in snapshot.node_states}
        ranges = by_node[("validation", "ranges")]
        # статус первого события жив; мусор второго детали не тронул.
        assert ranges["status"] == "done"
        assert ranges["source_event_id"] == "ev-5b-ok"
        assert ranges["status_reason"] == (
            "Статус проверки отчитан модулем «Валидация»"
        )
        assert snapshot.anomalies == 1

    def test_session_mode_marked_separately(self):
        """PR-6: mode -- session-данные, помечены mode_source="session";
        event-derived поля ссылаются на события."""
        from apps.api.progress_projection import build_projection

        corpus = [
            _ev(
                "validation_check_status",
                stage="validation",
                node_id="ranges",
                ts=_ts(1),
                payload={"status": "warning"},
                event_id="ev-5b-w",
            ),
        ]
        snapshot = build_projection(
            corpus, check_modes={"validation": {"ranges": "enabled"}}
        )
        by_node = {(s["stage"], s["node_id"]): s for s in snapshot.node_states}
        ranges = by_node[("validation", "ranges")]
        assert ranges["mode"] == "enabled"
        assert ranges["mode_source"] == "session"
        assert ranges["source_event_id"] == "ev-5b-w"


# ── PR-1/PR-3: панель -- полный ledger (P11/F06) ─────────────────────


class TestPanelFullLedger:
    def test_early_status_and_started_at_survive_cap(self, client: TestClient):
        """P11: корпус 1050 > капа слоя 1; ранний узел upload/overview
        остаётся done, started_at -- run.created_at; ответ несёт
        watermark/сourse events_total; events -- хвост отображения."""
        run_id = _run_id()
        _seed_session_and_run(
            client,
            run_id=run_id,
            events=_big_corpus(1050, run_id=run_id),
            created_at=RUN_CREATED_AT,
        )
        resp = client.get("/v1/progress/trace")
        assert resp.status_code == 200
        data = resp.json()
        # PR-1: ранний статус НЕ потерян (I9); watermark/полнота
        assert data["node_statuses"]["upload/overview"] == "done"
        assert data["node_statuses"]["validation/data_types"] == "done"
        # PR-3: started_at из run.created_at
        assert data["started_at"] == RUN_CREATED_AT
        assert data["watermark"] == 1050
        assert data["events_total"] == 1050
        assert data["projection_complete"] is True
        assert data["projection_source"] == "ledger"
        # cap ограничивает ТОЛЬКО отображаемый список
        assert len(data["events"]) == 1000
        assert data["events"][0]["event_id"] == "ev-5b-val-00050"

    def test_nodes_carry_evidence_fields(self, client: TestClient):
        corpus = [
            _ev(
                "upload_completed",
                stage="upload",
                node_id="overview",
                ts=_ts(0),
                payload={"name": "5b.csv"},
                event_id="ev-5b-up",
                context_id=CTX_A,
            )
        ]
        _seed_session_and_run(
            client, events=corpus, context_id=CTX_A
        )  # run_id уникален; узловые утверждения -- по графу, не по run
        data = client.get("/v1/progress/trace").json()
        node = next(
            n for n in data["nodes"]
            if n["stage"] == "upload" and n["node_id"] == "overview"
        )
        assert node["source_event_id"] == "ev-5b-up"
        assert node["validity"] == "current"


class TestReadAfterWatermark:
    def test_pending_when_position_not_reached(self, client: TestClient):
        run_id = _run_id()
        _seed_session_and_run(
            client, run_id=run_id, events=_big_corpus(30, run_id=run_id)
        )
        resp = client.get("/v1/progress/trace", params={"after_watermark": 31})
        assert resp.status_code == 409
        assert "projection_pending" in str(resp.json()["detail"])

    def test_ok_when_position_reached(self, client: TestClient):
        run_id = _run_id()
        _seed_session_and_run(
            client, run_id=run_id, events=_big_corpus(30, run_id=run_id)
        )
        resp = client.get("/v1/progress/trace", params={"after_watermark": 30})
        assert resp.status_code == 200
        assert resp.json()["watermark"] == 30


class TestHonestDegradation:
    def test_run_missing_marks_session_tail(self, client: TestClient):
        """PR-8: run_id известен, но слоя 2 нет -- проекция честно
        помечена session_tail (хвост не выдаётся за полную историю)."""
        run_id = _run_id()
        _seed_session_and_run(
            client,
            run_id=run_id,
            events=_big_corpus(20, run_id=run_id),
            register_run=False,
        )
        data = client.get("/v1/progress/trace").json()
        assert data["projection_complete"] is False
        assert data["projection_source"] == "session_tail"
        # started_at неизвестен честно (не ts хвоста)
        assert data["started_at"] is None

    def test_empty_session_shape(self, client: TestClient):
        data = client.get("/v1/progress/trace").json()
        assert data["run_id"] is None
        assert data["watermark"] == 0
        assert data["events"] == []
        assert data["projection_complete"] is True


# ── PR-1: согласованность потребителей ───────────────────────────────


class TestConsumerConsistency:
    def test_panel_equals_ledger_projection(self, client: TestClient):
        """Панель (/trace) и Наставник/отчёт -- читатели одной версии
        истории: статусы панели == проекция полного ledger."""
        run_id = _run_id()
        _seed_session_and_run(
            client, run_id=run_id, events=_big_corpus(1050, run_id=run_id)
        )
        from apps.api.progress_projection import build_projection, canonical_corpus

        store = get_research_run_store()
        ledger = [e.to_dict() for e in store.list_events(run_id)]
        expected = build_projection(canonical_corpus(ledger)).node_statuses
        data = client.get("/v1/progress/trace").json()
        assert data["node_statuses"] == expected

    def test_mentor_reports_watermark(self, client: TestClient):
        run_id = _run_id()
        _seed_session_and_run(
            client, run_id=run_id, events=_big_corpus(40, run_id=run_id)
        )
        resp = client.get(f"/v1/progress/runs/{run_id}/mentor/next-step")
        assert resp.status_code == 200
        data = resp.json()
        assert data["watermark"] == 40

    def test_report_canonical_order_not_ts(self, client: TestClient):
        """P12 на отчёте: корпус с sequence и обратным ts -- отчёт
        предъявляет факты в каноническом порядке (позиция ledger)."""
        events = [
            _ev(
                "target_column_changed",
                stage="validation",
                node_id=None,
                ts=_ts(30),
                payload={"target_column": "rain"},
                event_id="ev-5b-r1",
                sequence=1,
            ),
            _ev(
                "target_column_changed",
                stage="validation",
                node_id=None,
                ts=_ts(20),
                payload={"target_column": "snow"},
                event_id="ev-5b-r2",
                sequence=2,
            ),
        ]
        run_id = _run_id()
        _seed_session_and_run(client, run_id=run_id, events=events)
        resp = client.get(f"/v1/progress/runs/{run_id}/report")
        assert resp.status_code == 200
        body = resp.text
        # Versioned-обновление (AUDIT-7B, формат отчёта v2): строка факта
        # выбора цели несёт происхождение (P18/F12 -- payload без source --
        # legacy user, «вручную»; контракт PROGR-25-A). Суть пина --
        # канонический порядок фактов (P12), не формулировка строки.
        pos_rain = body.find("Установлен исследуемый признак вручную: rain.")
        pos_snow = body.find("Установлен исследуемый признак вручную: snow.")
        assert pos_rain != -1 and pos_snow != -1
        # канонический порядок: sequence 1 (rain) раньше sequence 2 (snow)
        assert pos_rain < pos_snow
