# tests/api/test_research_runs.py
"""Тесты Task PROGR-5 (plan_progress.md): долговременный слой трассы
«Прогресса» (spec_progress.md §5 слой 2, Postgres §12 п.1) + чекпоинты
(§5.1, паттерн PassportCheckpoint) + пауза (§5.2) + restore (§5.3).

Контуры:

  1. Модель данных: ResearchRun / ResearchCheckpoint (ссылка на событие,
     не копия -- §5.1), форматы идентификаторов.
  2. MemoryResearchRunStore: upsert/get/supersede, append-only события
     (глубокая копия payload -- R1 сертификации PROGR-1-CERT), чекпоинты.
  3. DatasetFileStore (§12 п.3): файлы uploads по dataset_fingerprint,
     снимки чекпоинтов (§12 п.4, последние 5 на run_id).
  4. Фабрика хранилища по env (паттерн get_session_store):
     DATABASE_URL -> Postgres (лениво, без коннекта при конструировании),
     иначе Memory.
  5. Зеркало долговременного слоя: middleware-хук (§5 дословно: «сюда
     пишет middleware из §4.2 -- В ДОПОЛНЕНИЕ к внутрисессионному буферу»)
     + унификация Прогнозирования (решение PROGR-3, events живут в
     ForecastRun.trace до PROGR-5).
  6. REST /v1/progress/runs/{run_id}[...]: детали, пауза, resume,
     чекпоинты, restore. Restore -- новая сессия/новый cookie, run_id
     ПЕРЕЖИВАЕТ cookie (приёмка плана), прогресс из trace_events.
  7. N-2 (PROGR-4): stage-level события (node_id=None) не создают
     узловых фактов -- restore сохраняет их как есть, фантомов нет.
     N-4 (PROGR-4): ответы PROGR-5 не содержат семантики закрытия
     панели (панель живёт во фронте; deep-link не закрывает её).

Postgres-реализация в этой среде не выполняется (драйвера/сервера нет):
покрываются DDL-константы, ленивый импорт и выбор фабрики; поведенческие
интеграционные тесты -- на Memory (тот же контракт базового класса).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.session_store import (
    DatasetInfo,
    AnalysisSession,
    get_session_store,
    reset_session_store_for_testing,
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
)
from apps.api.trace_events import make_trace_event


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Изоляция КАЖДОГО теста: свои каталоги данных, чистые синглтоны
    (заводские тесты фабрики не должны протекать в поведенческие)."""
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CISSTAT_RUNS_BACKEND", raising=False)
    reset_session_store_for_testing()
    from apps.api import research_runs

    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    yield
    reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_run_with_event(run_id: str = "RUN-AAA00001", **event_kwargs):
    """Прямое наполнение Memory-хранилища: запуск + одно событие."""
    from apps.api import research_runs

    store = research_runs.get_research_run_store()
    store.upsert_run(
        research_runs.ResearchRun(
            run_id=run_id,
            session_id="seed-session",
            dataset_fingerprint="f" * 64,
            dataset_name="seed.csv",
            created_at=_now_iso(),
            last_active_at=_now_iso(),
        )
    )
    event = make_trace_event(
        "upload_completed", stage="upload", node_id="structure_confirmed",
        run_id=run_id, name="seed.csv",
    )
    store.append_event(run_id, event)
    return store, event


# ── Контур 1: модель данных ──────────────────────────────────────────


class TestResearchRunModel:
    def test_run_statuses_canonical(self):
        from apps.api import research_runs

        assert research_runs.RUN_STATUSES == (
            "active", "paused", "completed", "abandoned",
        )

    def test_run_roundtrip_dict(self):
        from apps.api import research_runs

        run = research_runs.ResearchRun(
            run_id="RUN-8F2A91C4",
            session_id="sess-1",
            dataset_fingerprint="ab" * 32,
            dataset_name="prices.csv",
            target_column="Price",
            created_at="2026-09-25T08:00:00+00:00",
            last_active_at="2026-09-25T09:00:00+00:00",
            status="paused",
        )
        restored = research_runs.ResearchRun.from_dict(run.to_dict())
        assert restored == run
        # run_id -- PK, показывается пользователю (§5): читаемый формат.
        assert run.run_id.startswith("RUN-")

    def test_checkpoint_is_reference_not_copy(self):
        """Чекпоинт = именованная ссылка на событие (§5.1, паттерн
        PassportCheckpoint -- «ссылка на снимок, а не копия данных»):
        модель хранит event_id, а не событие."""
        from apps.api import research_runs

        checkpoint = research_runs.ResearchCheckpoint(
            checkpoint_id=str(__import__("uuid").uuid4()),
            run_id="RUN-8F2A91C4",
            event_id="evt-123",
            label="перед экспериментом со сглаживанием",
            has_snapshot=False,
            created_at="2026-09-25T09:00:00+00:00",
        )
        data = checkpoint.to_dict()
        assert data["event_id"] == "evt-123"
        assert "event" not in data and "payload" not in data
        assert research_runs.ResearchCheckpoint.from_dict(data) == checkpoint


# ── Контур 2: MemoryResearchRunStore ─────────────────────────────────


class TestMemoryResearchRunStore:
    def test_upsert_get_roundtrip(self):
        from apps.api import research_runs

        store = research_runs.MemoryResearchRunStore()
        run = research_runs.ResearchRun(run_id="RUN-1", session_id="s1")
        store.upsert_run(run)
        assert store.get_run("RUN-1") == run
        assert store.get_run("RUN-404") is None

    def test_upsert_replaces_previous_state(self):
        from apps.api import research_runs

        store = research_runs.MemoryResearchRunStore()
        store.upsert_run(research_runs.ResearchRun(run_id="RUN-1"))
        store.upsert_run(research_runs.ResearchRun(run_id="RUN-1", status="paused"))
        assert store.get_run("RUN-1").status == "paused"

    def test_append_event_chronological_and_deep_copied(self):
        """Append-only (§5: trace_events append-only); payload копируется
        глубоко (R1): мутация источника после записи не меняет stored."""
        from apps.api import research_runs

        store = research_runs.MemoryResearchRunStore()
        store.upsert_run(research_runs.ResearchRun(run_id="RUN-1"))
        event = make_trace_event(
            "correction_applied", stage="validation", node_id="formats",
            run_id="RUN-1", applied=True, meta={"nested": [1, 2]},
        )
        store.append_event("RUN-1", event)
        event.payload["meta"]["nested"].append(999)
        stored = store.list_events("RUN-1")
        assert [e.event_type for e in stored] == ["correction_applied"]
        assert stored[0].payload["meta"]["nested"] == [1, 2]

    def test_list_events_returns_copies_not_live_objects(self):
        from apps.api import research_runs

        store = research_runs.MemoryResearchRunStore()
        store.upsert_run(research_runs.ResearchRun(run_id="RUN-1"))
        store.append_event(
            "RUN-1", make_trace_event("upload_completed", stage="upload",
                                      node_id="structure_confirmed", run_id="RUN-1")
        )
        first = store.list_events("RUN-1")[0]
        second = store.list_events("RUN-1")[0]
        assert first == second
        assert first is not second

    def test_append_event_backfills_missing_event_id(self):
        """R4 (сертификация PROGR-3-CERT): записи без event_id получают
        детерминированный backfill при записи -- повторное чтение не
        перегенерирует идентификатор."""
        from apps.api import research_runs

        store = research_runs.MemoryResearchRunStore()
        store.upsert_run(research_runs.ResearchRun(run_id="RUN-1"))
        event = make_trace_event("upload_completed", stage="upload",
                                 node_id="structure_confirmed", run_id="RUN-1")
        object.__setattr__(event, "event_id", "")
        store.append_event("RUN-1", event)
        stored = store.list_events("RUN-1")[0]
        assert stored.event_id
        assert store.list_events("RUN-1")[0].event_id == stored.event_id

    def test_get_event_scoped_by_run(self):
        from apps.api import research_runs

        store = research_runs.MemoryResearchRunStore()
        for run_id in ("RUN-1", "RUN-2"):
            store.upsert_run(research_runs.ResearchRun(run_id=run_id))
            store.append_event(
                run_id, make_trace_event("upload_completed", stage="upload",
                                         node_id="structure_confirmed", run_id=run_id)
            )
        found = store.get_event("RUN-2", store.list_events("RUN-2")[0].event_id)
        assert found is not None and found.run_id == "RUN-2"
        # Событие RUN-2 не видно из RUN-1 -- ссылки чекпоинтов не должны
        # уметь указывать на чужой запуск.
        assert store.get_event("RUN-1", found.event_id) is None

    def test_set_run_status_touches_last_active_at(self):
        from apps.api import research_runs

        store = research_runs.MemoryResearchRunStore()
        run = research_runs.ResearchRun(run_id="RUN-1", last_active_at="2000-01-01T00:00:00+00:00")
        store.upsert_run(run)
        store.set_run_status("RUN-1", "paused")
        stored = store.get_run("RUN-1")
        assert stored.status == "paused"
        assert stored.last_active_at > "2000-01-01"

    def test_supersede_active_runs_marks_abandoned(self):
        """Новый датасет в той же сессии = новое исследование (§3.1):
        предыдущие АКТИВНЫЕ запуски сессии уходят в abandoned; paused и
        прочие статусы не трогаются."""
        from apps.api import research_runs

        store = research_runs.MemoryResearchRunStore()
        store.upsert_run(research_runs.ResearchRun(run_id="RUN-OLD", session_id="s1"))
        store.upsert_run(
            research_runs.ResearchRun(run_id="RUN-PAUSED", session_id="s1", status="paused")
        )
        store.supersede_active_runs("s1", keep_run_id="RUN-NEW")
        assert store.get_run("RUN-OLD").status == "abandoned"
        assert store.get_run("RUN-PAUSED").status == "paused"

    def test_checkpoints_add_list_scoped_by_run(self):
        from apps.api import research_runs

        store = research_runs.MemoryResearchRunStore()
        store.upsert_run(research_runs.ResearchRun(run_id="RUN-1"))
        checkpoint = research_runs.ResearchCheckpoint(
            checkpoint_id="cp-1", run_id="RUN-1", event_id="evt-1", label="x",
        )
        store.add_checkpoint("RUN-1", checkpoint)
        assert store.list_checkpoints("RUN-1") == [checkpoint]
        assert store.list_checkpoints("RUN-OTHER") == []

    def test_list_events_unknown_run_empty(self):
        from apps.api import research_runs

        store = research_runs.MemoryResearchRunStore()
        assert store.list_events("RUN-NONE") == []


# ── Контур 3: DatasetFileStore (§12 п.3/п.4) ─────────────────────────


class TestDatasetFileStore:
    def test_save_upload_stores_bytes_by_fingerprint(self, tmp_path: Path):
        from apps.api import research_runs

        store = research_runs.DatasetFileStore(tmp_path)
        contents = b"a,b\n1,2\n3,4\n"
        fingerprint = store.save_upload(
            contents, "prices.csv", rows=2, columns=2, size_label="10 B",
        )
        assert fingerprint == hashlib.sha256(contents).hexdigest()
        source = store.load(fingerprint)
        assert source is not None
        assert source.data == contents
        assert source.meta["name"] == "prices.csv"
        assert source.meta["rows"] == 2
        assert source.meta["source"] == "upload"

    def test_load_unknown_fingerprint_none(self, tmp_path: Path):
        from apps.api import research_runs

        store = research_runs.DatasetFileStore(tmp_path)
        assert store.load("0" * 64) is None

    def test_register_demo_reloads_builtin_file(self, tmp_path: Path):
        """Демо не копируется: meta source=builtin_demo, load перечитывает
        встроенный файл (apps/api/demo_data/sales_demo.csv существует на
        сервере -- §5.3 повторная загрузка не нужна)."""
        from apps.api import research_runs
        from apps.api.routers.session import DEMO_DATASET_PATH

        store = research_runs.DatasetFileStore(tmp_path)
        fingerprint = store.register_demo(
            DEMO_DATASET_PATH, name="demo_sales.csv (демо-датасет)",
            rows=24, columns=3, size_label="3.1 kB",
        )
        source = store.load(fingerprint)
        assert source is not None
        assert source.meta["source"] == "builtin_demo"
        assert source.data == DEMO_DATASET_PATH.read_bytes()

    def test_checkpoint_snapshot_roundtrip_and_prune(self, tmp_path: Path):
        """Снимки чекпоинтов (§12 п.4): последние 5 на run_id, старше --
        вытесняются. Формат -- CSV (pandas native; Parquet рекомендован
        спекой, но pyarrow в среде нет -- отклонение зафиксировано в
        worklog, замена = одна функция). Даты в CSV теряют dtype
        (документированное ограничение) -- кругосветка на числовых."""
        from apps.api import research_runs

        store = research_runs.DatasetFileStore(tmp_path)
        df = pd.DataFrame({"v": [1.0, 2.0, 3.0], "w": ["a", "b", "c"]})
        ids = []
        for i in range(6):
            checkpoint_id = f"cp-{i}"
            assert store.save_checkpoint_snapshot("RUN-1", checkpoint_id, df)
            ids.append(checkpoint_id)
        store.prune_checkpoints("RUN-1", keep=ids[-5:])
        assert store.load_checkpoint_snapshot("RUN-1", "cp-0") is None
        restored = store.load_checkpoint_snapshot("RUN-1", "cp-5")
        assert restored is not None
        # CSV-формат: dtype дат теряется (документированное отклонение
        # от Parquet, §12 п.4 -- см. докстринг DatasetFileStore).
        pd.testing.assert_frame_equal(restored, df, check_dtype=False)

    def test_checkpoint_snapshot_without_dataframe_false(self, tmp_path: Path):
        from apps.api import research_runs

        store = research_runs.DatasetFileStore(tmp_path)
        assert not store.save_checkpoint_snapshot("RUN-1", "cp-x", None)

    def test_default_root_env_override(self, tmp_path: Path, monkeypatch):
        from apps.api import research_runs

        monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "custom"))
        assert research_runs.DatasetFileStore.default_root() == tmp_path / "custom"


# ── Контур 4: фабрика хранилища ──────────────────────────────────────


class TestStoreFactory:
    def test_memory_by_default(self, monkeypatch):
        from apps.api import research_runs

        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("CISSTAT_RUNS_BACKEND", raising=False)
        research_runs.reset_research_run_store_for_testing()
        assert isinstance(
            research_runs.get_research_run_store(), research_runs.MemoryResearchRunStore
        )

    def test_database_url_selects_postgres_lazily(self, monkeypatch):
        """DATABASE_URL -> PostgresResearchRunStore; конструирование НЕ
        открывает соединение (ленивый коннект на первой операции) -- заводить
        сервер для создания объекта не требуется."""
        from apps.api import research_runs

        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
        research_runs.reset_research_run_store_for_testing()
        store = research_runs.get_research_run_store()
        assert isinstance(store, research_runs.PostgresResearchRunStore)

    def test_explicit_memory_backend_beats_database_url(self, monkeypatch):
        from apps.api import research_runs

        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
        monkeypatch.setenv("CISSTAT_RUNS_BACKEND", "memory")
        research_runs.reset_research_run_store_for_testing()
        assert isinstance(
            research_runs.get_research_run_store(), research_runs.MemoryResearchRunStore
        )

    def test_singleton_reused(self, monkeypatch):
        from apps.api import research_runs

        research_runs.reset_research_run_store_for_testing()
        assert research_runs.get_research_run_store() is research_runs.get_research_run_store()

    def test_migration_statements_cover_all_tables(self):
        from apps.api import research_runs

        ddl = "\n".join(research_runs.MIGRATION_STATEMENTS)
        for table in ("research_runs", "trace_events", "run_checkpoints"):
            assert f"CREATE TABLE IF NOT EXISTS {table}" in ddl
        # События -- append-only с внешним ключом на запуск (§5).
        assert "REFERENCES research_runs(run_id)" in ddl
        # Миграция доступна как SQL-файл для ops (план: «миграции схемы»).
        sql_file = Path(research_runs.__file__).parent / "migrations" / "0001_research_runs.sql"
        assert sql_file.exists()
        assert "research_runs" in sql_file.read_text(encoding="utf-8")


# ── Контур 5: зеркало долговременного слоя ───────────────────────────


class TestMirrorFromHook:
    def test_upload_creates_run_and_mirrors_event(self, client: TestClient):
        """Первое событие исследования = загрузка (§5: run_id по факту
        первой загрузки): middleware создаёт ResearchRun с fingerprint
        датасета и отражает upload_completed в слой 2."""
        demo = client.post("/v1/session/demo")
        assert demo.status_code == 200

        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        runs = [r for r in store.list_runs() if r.status == "active"]
        assert len(runs) == 1
        run = runs[0]
        assert run.run_id.startswith("RUN-")
        assert run.dataset_name == "demo_sales.csv (демо-датасет)"
        assert run.dataset_fingerprint
        assert run.status == "active"
        events = store.list_events(run.run_id)
        assert [e.event_type for e in events] == ["upload_completed"]
        assert events[0].run_id == run.run_id

    def test_mirrored_event_matches_layer1_payload(self, client: TestClient):
        """Слой 2 -- В ДОПОЛНЕНИЕ к слою 1 (§5): то же событие, те же факты."""
        client.post("/v1/session/demo")
        session_store = get_session_store()
        session = session_store.get(client.cookies.get(SESSION_COOKIE_NAME))
        layer1 = session.read_pipeline_trace()

        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        layer2 = store.list_events(session.run_id)
        assert len(layer2) == len(layer1) >= 1
        assert layer2[-1].to_dict() == layer1[-1].to_dict()

    def test_target_column_changed_updates_run(self, client: TestClient):
        client.post("/v1/session/demo")
        payload = {"column": "sales"}
        resp = client.post("/v1/session/target-column", json=payload)
        assert resp.status_code == 200

        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        runs = [r for r in store.list_runs() if r.status == "active"]
        assert runs[0].target_column == "sales"

    def test_events_without_run_id_skipped(self, client: TestClient):
        """События без датасета не имеют run_id (гейт ensure_run_id) --
        слой 2 их не принимает: run не существует без исследования (§5)."""
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        session = AnalysisSession(session_id="no-dataset-sess")
        event = make_trace_event(
            "passport_captured", stage="eda", node_id=None, run_id=""
        )
        research_runs.record_run_event(session, event)
        assert store.list_runs() == []

    def test_mirror_failure_does_not_break_endpoint(self, client: TestClient, monkeypatch):
        """Best-effort (контур рантайма хука, §4.2): сбой долговременного
        слоя не ломает успешный ответ эндпоинта."""
        from apps.api import research_runs

        def _boom(*args, **kwargs):
            raise RuntimeError("postgres down")

        monkeypatch.setattr(
            research_runs.ResearchRunStore, "upsert_run", _boom
        )
        resp = client.post("/v1/session/demo")
        assert resp.status_code == 200
        # ... при этом событие слоя 1 записано: зеркало вспомогательно.
        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        assert session.read_pipeline_trace()

    def test_new_dataset_supersedes_previous_run(self, client: TestClient):
        """Новый датасет = новое исследование (§3.1): активный запуск
        сессии уходит в abandoned, пишется новый run_id."""
        client.post("/v1/session/demo")
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        first = [r for r in store.list_runs() if r.status == "active"][0]

        contents = b"date,value\n2026-01-01,10\n2026-01-02,11\n"
        resp = client.post(
            "/v1/internal/upload",
            files={"file": ("second.csv", BytesIO(contents), "text/csv")},
        )
        assert resp.status_code == 200
        runs = {r.run_id: r for r in store.list_runs()}
        assert runs[first.run_id].status == "abandoned"
        second_active = [r for r in runs.values() if r.status == "active"]
        assert len(second_active) == 1
        assert second_active[0].run_id != first.run_id
        assert second_active[0].dataset_fingerprint == hashlib.sha256(contents).hexdigest()

    def test_forecasting_events_unified_into_layer2(self):
        """Унификация PROGR-5 (решение PROGR-3): события Прогнозирования,
        живущие в ForecastRun.trace, отражаются в слой 2 при записи."""
        from apps.api import research_runs
        from apps.api.routers import forecasting_session

        session = AnalysisSession(session_id="fc-sess")
        session.run_id = "RUN-FC0001"
        session.dataset = DatasetInfo(
            dataset_id="d1", name="fc.csv", rows=10, columns=2, size_label="1 kB",
            dataset_fingerprint="e" * 64,
        )
        research_runs.get_research_run_store().upsert_run(
            research_runs.ResearchRun(run_id="RUN-FC0001", session_id="fc-sess")
        )
        run_dict = {"trace_events": []}
        event = make_trace_event(
            "forecast_generated", model_id="arima", horizon=7,
        )
        forecasting_session._append_event(session, run_dict, event)
        # В ForecastRun.trace событие на месте (контракт PROGR-1 не тронут).
        assert len(run_dict["trace_events"]) == 1
        # ... и в долговременном слое тоже -- run_id взят из сессии.
        stored = research_runs.get_research_run_store().list_events("RUN-FC0001")
        assert [e.event_type for e in stored] == ["forecast_generated"]
        assert stored[0].run_id == "RUN-FC0001"


# ── Контур 6: REST /v1/progress/runs/* ───────────────────────────────


class TestRunDetailEndpoint:
    def test_detail_shape(self, client: TestClient):
        client.post("/v1/session/demo")
        from apps.api import research_runs

        run = [r for r in research_runs.get_research_run_store().list_runs()][0]
        resp = client.get(f"/v1/progress/runs/{run.run_id}")
        assert resp.status_code == 200
        data = resp.json()
        for key in (
            "run_id", "session_id", "dataset_fingerprint", "dataset_name",
            "target_column", "created_at", "last_active_at", "status",
            "events", "checkpoints",
        ):
            assert key in data
        assert data["run_id"] == run.run_id
        assert data["status"] == "active"
        assert data["events"][0]["event_type"] == "upload_completed"
        # Канон §4.1 на границе отдачи.
        assert "timestamp" in data["events"][0]

    def test_detail_404_unknown_run(self, client: TestClient):
        assert client.get("/v1/progress/runs/RUN-DEAD000").status_code == 404

    def test_detail_limit_returns_latest(self, client: TestClient):
        client.post("/v1/session/demo")
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        run = store.list_runs()[0]
        for i in range(3):
            store.append_event(
                run.run_id,
                make_trace_event("passport_captured", stage="eda", node_id=None,
                                 run_id=run.run_id, i=i),
            )
        resp = client.get(f"/v1/progress/runs/{run.run_id}", params={"limit": 2})
        events = resp.json()["events"]
        assert len(events) == 2
        assert events[-1]["payload"]["i"] == 2

    def test_progress_routes_not_traced_by_hook(self, client: TestClient):
        """Ровно как GET /trace у PROGR-4: namespace /v1/progress/* не
        трассируется хуком (иначе действия панели росли бы в собственном
        логе)."""
        from apps.api.trace_hook import resolve_trace_route

        assert resolve_trace_route("GET", "/v1/progress/runs/RUN-1") is None
        assert resolve_trace_route("POST", "/v1/progress/runs/RUN-1/pause") is None
        assert resolve_trace_route("POST", "/v1/progress/runs/RUN-1/resume") is None
        assert resolve_trace_route("POST", "/v1/progress/runs/RUN-1/checkpoints") is None
        assert resolve_trace_route("GET", "/v1/progress/runs/RUN-1/restore") is None

    def test_durable_layer_outage_is_honest_503(self, client: TestClient, monkeypatch):
        """Сбой долговременного слоя (Postgres-бэкенд недоступен) --
        честный 503, а не 500 с сырым трейсом; 404 по неизвестному запуску
        остаётся 404 (факт, не сбой)."""
        from apps.api import research_runs

        research_runs.reset_research_run_store_for_testing()
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
        research_runs.reset_research_run_store_for_testing()

        # 404 требует lookup, который сам упадёт -> 503 (факт недоступности
        # важнее факта отсутствия: сервер не может знать, есть ли запуск).
        resp = client.get("/v1/progress/runs/RUN-DEAD000")
        assert resp.status_code == 503
        assert resp.json()["detail"] == "Долговременный слой недоступен"

        research_runs.reset_research_run_store_for_testing()
        monkeypatch.delenv("DATABASE_URL", raising=False)
        research_runs.reset_research_run_store_for_testing()
        assert client.get("/v1/progress/runs/RUN-DEAD000").status_code == 404


class TestPauseResumeEndpoints:
    def test_pause_active_run(self, client: TestClient):
        client.post("/v1/session/demo")
        from apps.api import research_runs

        run = research_runs.get_research_run_store().list_runs()[0]
        resp = client.post(f"/v1/progress/runs/{run.run_id}/pause")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "paused"
        assert data["event"]["event_type"] == "run_paused"
        assert data["event"]["run_id"] == run.run_id

        store = research_runs.get_research_run_store()
        assert store.get_run(run.run_id).status == "paused"
        assert store.list_events(run.run_id)[-1].event_type == "run_paused"

    def test_pause_writes_run_level_event_to_layer1_of_calling_session(self, client: TestClient):
        """run-level события валидны на любой стадии (§4.1): панель видит
        «Пауза» в трассе слоя 1 той же сессии."""
        client.post("/v1/session/demo")
        from apps.api import research_runs

        run = research_runs.get_research_run_store().list_runs()[0]
        client.post(f"/v1/progress/runs/{run.run_id}/pause")
        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        layer1 = session.read_pipeline_trace()
        assert layer1[-1].event_type == "run_paused"
        assert layer1[-1].run_id == run.run_id

    def test_pause_twice_409(self, client: TestClient):
        client.post("/v1/session/demo")
        from apps.api import research_runs

        run = research_runs.get_research_run_store().list_runs()[0]
        assert client.post(f"/v1/progress/runs/{run.run_id}/pause").status_code == 200
        assert client.post(f"/v1/progress/runs/{run.run_id}/pause").status_code == 409

    def test_pause_unknown_run_404(self, client: TestClient):
        assert client.post("/v1/progress/runs/RUN-DEAD000/pause").status_code == 404

    def test_resume_returns_to_active(self, client: TestClient):
        client.post("/v1/session/demo")
        from apps.api import research_runs

        run = research_runs.get_research_run_store().list_runs()[0]
        client.post(f"/v1/progress/runs/{run.run_id}/pause")
        resp = client.post(f"/v1/progress/runs/{run.run_id}/resume")
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"
        store = research_runs.get_research_run_store()
        assert store.get_run(run.run_id).status == "active"
        assert store.list_events(run.run_id)[-1].event_type == "run_resumed"

    def test_resume_not_paused_409(self, client: TestClient):
        client.post("/v1/session/demo")
        from apps.api import research_runs

        run = research_runs.get_research_run_store().list_runs()[0]
        assert client.post(f"/v1/progress/runs/{run.run_id}/resume").status_code == 409


class TestCheckpointEndpoints:
    def test_create_checkpoint_references_event(self, client: TestClient):
        client.post("/v1/session/demo")
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        run = store.list_runs()[0]
        event = store.list_events(run.run_id)[0]
        resp = client.post(
            f"/v1/progress/runs/{run.run_id}/checkpoints",
            json={"event_id": event.event_id, "label": "перед агрессивным сглаживанием"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["checkpoint"]["event_id"] == event.event_id
        assert data["checkpoint"]["label"] == "перед агрессивным сглаживанием"
        # Вызывавшая сессия владеет запуском и имеет датасет -- снимок
        # данных захвачен (§12 п.4).
        assert data["checkpoint"]["has_snapshot"] is True
        # checkpoint_saved -- run-level событие (§4.1) в слое 2.
        assert data["event"]["event_type"] == "checkpoint_saved"
        assert store.list_checkpoints(run.run_id)[0].event_id == event.event_id

    def test_create_checkpoint_saved_visible_in_layer1(self, client: TestClient):
        client.post("/v1/session/demo")
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        run = store.list_runs()[0]
        event = store.list_events(run.run_id)[0]
        client.post(
            f"/v1/progress/runs/{run.run_id}/checkpoints",
            json={"event_id": event.event_id},
        )
        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        assert session.read_pipeline_trace()[-1].event_type == "checkpoint_saved"

    def test_checkpoint_unknown_event_404(self, client: TestClient):
        client.post("/v1/session/demo")
        from apps.api import research_runs

        run = research_runs.get_research_run_store().list_runs()[0]
        resp = client.post(
            f"/v1/progress/runs/{run.run_id}/checkpoints",
            json={"event_id": "no-such-event"},
        )
        assert resp.status_code == 404

    def test_checkpoint_unknown_run_404(self, client: TestClient):
        assert client.post(
            "/v1/progress/runs/RUN-DEAD000/checkpoints",
            json={"event_id": "x"},
        ).status_code == 404

    def test_checkpoint_captures_dataframe_snapshot(self, client: TestClient):
        """Снимок данных на чекпоинте (§12 п.4): активная сессия с
        датасетом -- CSV сохранён, has_snapshot=True, последние 5."""
        client.post("/v1/session/demo")
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        file_store = research_runs.get_dataset_file_store()
        run = store.list_runs()[0]
        event = store.list_events(run.run_id)[0]
        resp = client.post(
            f"/v1/progress/runs/{run.run_id}/checkpoints",
            json={"event_id": event.event_id},
        )
        assert resp.json()["checkpoint"]["has_snapshot"] is True
        checkpoint_id = resp.json()["checkpoint"]["checkpoint_id"]
        df = file_store.load_checkpoint_snapshot(run.run_id, checkpoint_id)
        assert df is not None and len(df) > 0

    def test_checkpoint_requires_matching_session_for_snapshot(self, client: TestClient):
        """Снимок пишется только из сессии ЭТОГО запуска: чужая/пустая
        сессия создаёт ссылку без снимка (честный has_snapshot=False)."""
        client.post("/v1/session/demo")
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        run = store.list_runs()[0]
        event = store.list_events(run.run_id)[0]
        # Новая браузерная сессия без датасета, но run существует в слое 2.
        fresh = TestClient(app)
        resp = fresh.post(
            f"/v1/progress/runs/{run.run_id}/checkpoints",
            json={"event_id": event.event_id},
        )
        assert resp.status_code == 201
        assert resp.json()["checkpoint"]["has_snapshot"] is False


class TestRestoreEndpoint:
    def test_restore_unknown_run_404(self, client: TestClient):
        assert client.get("/v1/progress/runs/RUN-DEAD000/restore").status_code == 404

    def test_restore_completed_run_409(self, client: TestClient):
        """§5.3 дословно: restore только если status != completed."""
        client.post("/v1/session/demo")
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        run = store.list_runs()[0]
        store.set_run_status(run.run_id, "completed")
        assert client.get(f"/v1/progress/runs/{run.run_id}/restore").status_code == 409

    def test_restore_without_dataset_file_409(self, client: TestClient):
        """Нет файла по fingerprint -> честный 409: промежуточные состояния
        не восстанавливаются (§5.3), повторная загрузка -- на аналитике."""
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        store.upsert_run(
            research_runs.ResearchRun(
                run_id="RUN-NOFILE01", session_id="s",
                dataset_fingerprint="0" * 64, dataset_name="lost.csv",
            )
        )
        store.append_event(
            "RUN-NOFILE01",
            make_trace_event("upload_completed", stage="upload",
                             node_id="structure_confirmed", run_id="RUN-NOFILE01"),
        )
        resp = client.get("/v1/progress/runs/RUN-NOFILE01/restore")
        assert resp.status_code == 409

    def test_restore_creates_new_session_same_run_id(self, client: TestClient):
        """Ключевая приёмка плана: run_id ПЕРЕЖИВАЕТ cookie. Restore
        строит НОВУЮ сессию (новый cookie), датасет перезагружается из
        файлового слоя (§12 п.3), прогресс -- из trace_events."""
        demo = client.post("/v1/session/demo")
        assert demo.status_code == 200
        # Аналитик поработал: target выбран (факт слоя 2).
        client.post("/v1/session/target-column", json={"column": "sales"})

        from apps.api import research_runs

        run = research_runs.get_research_run_store().list_runs()[0]

        # «Другое устройство»: чистый клиент без cookie.
        fresh = TestClient(app)
        resp = fresh.get(f"/v1/progress/runs/{run.run_id}/restore")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == run.run_id
        assert data["status"] == "active"
        assert data["dataset"]["name"] == "demo_sales.csv (демо-датасет)"
        assert data["target_column"] == "sales"
        assert data["events_restored"] >= 1

        # Новый cookie выдан (§5.3: новая сессия).
        assert SESSION_COOKIE_NAME in fresh.cookies
        new_session_id = fresh.cookies.get(SESSION_COOKIE_NAME)
        assert new_session_id != client.cookies.get(SESSION_COOKIE_NAME)

        # Новая сессия: датасет активен, run_id тот же, трасса засеяна.
        session = get_session_store().get(new_session_id)
        assert session is not None
        assert session.dataset is not None
        assert session.run_id == run.run_id
        restored_trace = session.read_pipeline_trace()
        assert any(e.event_type == "upload_completed" for e in restored_trace)
        assert session.target_column == "sales"
        # session.stages не пишется Прогрессом (§3.1) -- только честный
        # upload=done от set_dataset.
        assert session.stages["upload"] == "done"

        # run перелинкован на новую сессию (§5: session_id -- последний
        # известный), run_resumed записан (возврат к работе).
        store = research_runs.get_research_run_store()
        restored_run = store.get_run(run.run_id)
        assert restored_run.session_id == new_session_id
        assert restored_run.status == "active"
        assert store.list_events(run.run_id)[-1].event_type == "run_resumed"

        # Продолжение исследования пишет в ТОТ ЖЕ run (переживает cookie).
        fresh.post("/v1/session/target-column", json={"column": "profit"})
        assert store.get_run(run.run_id).target_column == "profit"

    def test_restore_seeds_layer1_within_cap(self, client: TestClient):
        """Засев слоя 1 ограничен cap'ом буфера (1000); полная история
        остаётся в слое 2. События идут в хронологическом порядке."""
        client.post("/v1/session/demo")
        from apps.api import research_runs
        from apps.api.session_store import MAX_PIPELINE_TRACE_EVENTS

        store = research_runs.get_research_run_store()
        run = store.list_runs()[0]
        for i in range(MAX_PIPELINE_TRACE_EVENTS + 5):
            store.append_event(
                run.run_id,
                make_trace_event("passport_captured", stage="eda", node_id=None,
                                 run_id=run.run_id, seq=i),
            )
        fresh = TestClient(app)
        resp = fresh.get(f"/v1/progress/runs/{run.run_id}/restore")
        assert resp.status_code == 200
        data = resp.json()
        assert data["events_restored"] == MAX_PIPELINE_TRACE_EVENTS
        assert data["events_total"] == MAX_PIPELINE_TRACE_EVENTS + 6  # upload + 1005

        session = get_session_store().get(fresh.cookies.get(SESSION_COOKIE_NAME))
        trace = session.read_pipeline_trace()
        # Засев (1000) + run_resumed от restore -> cap слоя 1 вытесняет
        # старейший засеянный: буфер остаётся 1000, полный хвост -- тут.
        assert len(trace) == MAX_PIPELINE_TRACE_EVENTS
        assert trace[-1].event_type == "run_resumed"
        # Последнее durable-событие -- перед run_resumed.
        assert trace[-2].payload["seq"] == MAX_PIPELINE_TRACE_EVENTS + 4
        assert trace[0].payload["seq"] == 6  # старейший вытеснен cap'ом

    def test_restore_paused_run_activates(self, client: TestClient):
        client.post("/v1/session/demo")
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        run = store.list_runs()[0]
        client.post(f"/v1/progress/runs/{run.run_id}/pause")
        resp = client.get(f"/v1/progress/runs/{run.run_id}/restore")
        assert resp.status_code == 200
        assert store.get_run(run.run_id).status == "active"

    def test_restore_preserves_stage_level_events_without_nodes(self, client: TestClient):
        """N-2 (находка PROGR-4): stage-level события (node_id=None) не
        влияют на свод стадии -- restore сохраняет их КАК ЕСТЬ (без
        фантомных узлов), свод остаётся честным «не начато» по узлам."""
        client.post("/v1/session/demo")
        from apps.api import research_runs

        store = research_runs.get_research_run_store()
        run = store.list_runs()[0]
        store.append_event(
            run.run_id,
            make_trace_event("mode_changed", stage="validation", node_id=None,
                             run_id=run.run_id, modes={"formats": "disabled"}),
        )
        fresh = TestClient(app)
        resp = fresh.get(f"/v1/progress/runs/{run.run_id}/restore")
        assert resp.status_code == 200
        session = get_session_store().get(fresh.cookies.get(SESSION_COOKIE_NAME))
        trace = session.read_pipeline_trace()
        mode_events = [e for e in trace if e.event_type == "mode_changed"]
        assert len(mode_events) == 1
        assert mode_events[0].node_id is None  # фантомного узла нет (N-2)

    def test_restore_response_has_no_panel_control_semantics(self, client: TestClient):
        """N-4 (находка PROGR-4): контракт restore не несёт команд
        закрытия/открытия панели -- состояние панели живёт во фронте,
        deep-link узла не закрывает её."""
        client.post("/v1/session/demo")
        from apps.api import research_runs

        run = research_runs.get_research_run_store().list_runs()[0]
        data = client.get(f"/v1/progress/runs/{run.run_id}/restore").json()
        forbidden = {"close_panel", "open_panel", "panel", "navigate", "redirect"}
        assert not forbidden & set(data.keys())


# ── Контур 7: DatasetInfo несёт fingerprint (контракт сессии) ────────


class TestDatasetInfoFingerprint:
    def test_dataset_info_has_fingerprint_default(self):
        info = DatasetInfo(dataset_id="d", name="n", rows=1, columns=1, size_label="1 B")
        assert info.dataset_fingerprint == ""

    def test_session_roundtrip_keeps_fingerprint(self):
        """Аддитивное поле сериализации сессии: старые Redis-документы
        (без поля) читаются с пустым fingerprint."""
        from apps.api.session_store import session_from_dict, session_to_dict

        session = AnalysisSession(session_id="s")
        session.dataset = DatasetInfo(
            dataset_id="d", name="n", rows=1, columns=1, size_label="1 B",
            dataset_fingerprint="ab" * 32,
        )
        restored = session_from_dict(session_to_dict(session))
        assert restored.dataset.dataset_fingerprint == "ab" * 32

    def test_legacy_session_document_without_field(self):
        from apps.api.session_store import SESSION_SCHEMA_VERSION, session_from_dict

        legacy = {
            "session_id": "old",
            "session_schema_version": SESSION_SCHEMA_VERSION,
            "stages": {},
            "dataset": {
                "dataset_id": "d", "name": "n", "rows": 1,
                "columns": 1, "size_label": "1 B",
            },
        }
        restored = session_from_dict(legacy)
        assert restored.dataset.dataset_fingerprint == ""

    def test_upload_persists_file_by_fingerprint(self, client: TestClient):
        """Загрузка файла сохраняет байты в файловый слой (§12 п.3) --
        иначе restore невозможен (§5.3)."""
        contents = b"date,value\n2026-01-01,1\n2026-01-02,2\n"
        resp = client.post(
            "/v1/internal/upload",
            files={"file": ("uploaded.csv", BytesIO(contents), "text/csv")},
        )
        assert resp.status_code == 200
        from apps.api import research_runs

        fingerprint = hashlib.sha256(contents).hexdigest()
        source = research_runs.get_dataset_file_store().load(fingerprint)
        assert source is not None
        assert source.data == contents
        # Сессия несёт fingerprint -- зеркало пишет его в ResearchRun.
        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        assert session.dataset.dataset_fingerprint == fingerprint
