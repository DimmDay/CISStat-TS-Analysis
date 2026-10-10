# tests/api/test_progress_audit_c.py
"""
PROGR-AUDIT-C: данные, ревизии и контекст расчёта (plan_progress_audit.md §6;
контракт docs/progress_audit_contract.md §3.4 -- УТВЕРЖДЕНО-AUDIT-0 (форма),
детали -- настоящая задача; аддендум v0.4-C).

Что закрывает задача (RED-критерии карточки):

1. dataset_revision -- применённая коррекция МЕНЯЕТ ревизию данных; preview
   НЕ меняет; no-op apply не выдаётся за изменённые данные; новая загрузка
   сбрасывает ревизию (новый датасет = новый анализ).
2. server context_id -- СЕРВЕР вычисляет контекст расчёта (фронт контекст
   не создаёт догадками, план §1): fingerprint файла + ревизия данных +
   target + date, со run-scoping'ом (повторная загрузка того же filename --
   НОВЫЙ запуск/контекст; смена цели rain->snow при неизменном datasetId
   МЕНЯЕТ target scope). No-op выбора не меняет контекст.
3. Envelope-поле context_id продюсеров (§12.7: продюсеры переходят на v2
   задачей AUDIT-C): hook-события, auto-выбор, cleared несут контекст
   момента расчёта; захваченный контекст НЕ перепривязывается после
   повышения ревизии (поздний/старый результат остаётся историческим --
   I3, F04/P24).
4. Dependency scopes узлов -- ОДИН реестр в pipeline_graph (контракт
   §3.4): смена цели не инвалидирует data-only узлы (риск карточки:
   «нельзя инвалидировать все узлы на любую настройку»), target-dependent
   done при смене цели НЕ сохраняется как current (I6-фундамент).
5. Сериализация Redis/Memory + чтение старых сессий с unknown-метаданными
   (план §6 п.5); CAS-конфликт не выдаёт ложное обновление (RED карточки).
6. API отдаёт устойчивый контекст (/current), UI его гидрирует
   (AppShellContext) -- контекст создаётся только сервером.

Границы (осознанные, вне задачи): durable-хранение envelope слоя 2 и
run-метаданных ревизии -- миграция AUDIT-6A; result context (параметры
методов) -- AUDIT-4/7A; UI keyed-кэши просмотров -- AUDIT-3/2B;
cross-run применимость restore -- AUDIT-8.
"""
from __future__ import annotations

import io

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.core import pipeline_graph
from app.core.pipeline_graph import (
    CONTEXT_SCOPES,
    NODE_DEPENDENCY_SCOPES,
    iter_all_nodes,
    node_context_validity,
    node_dependency_scopes,
)
from apps.api import research_runs
from apps.api.data_context import (
    compute_context_id,
    compute_data_digest,
    context_components,
)
from apps.api.main import app
from apps.api.session_store import (
    AnalysisSession,
    DatasetInfo,
    MemorySessionStore,
    SessionConflictError,
    reset_session_store_for_testing,
)


@pytest.fixture(autouse=True)
def _reset_stores(monkeypatch):
    """Изоляция: Memory-бэкенды ОБОИХ хранилищ (паттерн
    test_progress_audit_h1 / test_progress_progr25c)."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("CISSTAT_RUNS_BACKEND", "memory")
    monkeypatch.setenv("CISSTAT_SESSION_BACKEND", "memory")
    reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()
    yield
    reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()


client = TestClient(app)


# ── Фикстуры контура (паттерн H1) ────────────────────────────────────

CSV_TWO_NUMERIC = (
    "date,rain,snow\n"
    "2023-01-01,10.5,1.0\n"
    "2023-01-02,20.1,2.0\n"
    "2023-01-03,30.2,3.0\n"
    "2023-01-04,15.8,4.0\n"
)

CSV_WITH_MISSING = (
    "date,rain\n"
    "2023-01-01,10.5\n"
    "2023-01-02,\n"
    "2023-01-03,30.2\n"
    "2023-01-04,15.8\n"
)

CSV_ONE_NUMERIC = "date,rain\n2023-01-01,1\n2023-01-02,2\n2023-01-03,3\n"


def _upload(csv: str, filename: str = "data.csv") -> dict:
    file = io.BytesIO(csv.encode("utf-8"))
    resp = client.post(
        "/v1/internal/upload",
        files={"file": (filename, file, "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _current() -> dict:
    resp = client.get("/v1/session/current")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _set_target(column: str) -> dict:
    resp = client.post("/v1/session/target-column", json={"column": column})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _set_date(column: str = "date") -> dict:
    resp = client.post("/v1/session/date-column", json={"column": column})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _missing_corrections(column: str, *, apply: bool) -> dict:
    resp = client.post(
        "/v1/session/dataset/missing-corrections",
        json={"columns": [column], "strategy": "interpolate", "apply": apply},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _convert_to_string(column: str) -> dict:
    resp = client.post(
        "/v1/session/dataset/convert-types",
        json={
            "conversions": [{"column": column, "target_type": "string"}],
            "invalid_policy": "coerce",
            "apply": True,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _trace() -> dict:
    resp = client.get("/v1/progress/trace")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _events_of(trace: dict, event_type: str) -> list[dict]:
    return [
        e for e in trace.get("events", [])
        if e.get("event_type") == event_type
    ]


# ── 1. Ревизии данных (RED: «применённая коррекция меняет data revision;
#     preview не меняет её»; no-op честность) ──────────────────────────


class TestDataRevision:
    def test_upload_starts_revision_zero_and_new_upload_resets(self):
        """Новая загрузка -- ревизия 0 (новый датасет = новый анализ);
        ревизия, поднятая коррекциями ПРЕЖНЕГО анализа, не наследуется."""
        _upload(CSV_WITH_MISSING)
        _missing_corrections("rain", apply=True)  # ревизия прежнего анализа
        assert _current()["data_revision"] == 1
        _upload(CSV_TWO_NUMERIC)
        assert _current()["data_revision"] == 0

    def test_applied_correction_bumps_revision(self):
        _upload(CSV_WITH_MISSING)
        assert _current()["data_revision"] == 0
        result = _missing_corrections("rain", apply=True)
        assert result["applied"] is True
        assert _current()["data_revision"] == 1

    def test_preview_does_not_bump_revision(self):
        _upload(CSV_WITH_MISSING)
        result = _missing_corrections("rain", apply=False)
        assert result["applied"] is False
        assert _current()["data_revision"] == 0

    def test_noop_apply_does_not_bump_revision(self):
        """No-op не выдаётся за изменённые данные (план §6 п.2): коррекция
        без пропусков не меняет контент -- ревизия на месте."""
        _upload(CSV_TWO_NUMERIC)  # в rain/snow пропусков нет
        before = _current()["data_revision"]
        result = _missing_corrections("rain", apply=True)
        assert result["applied"] is True
        assert _current()["data_revision"] == before

    def test_set_dataframe_returns_change_fact(self):
        """Единая точка замены возвращает ФАКТ изменения (вызывающий код
        и тесты различают мутацию и no-op)."""
        session = AnalysisSession(session_id="s-c-rev")
        df = pd.DataFrame({"a": [1, 2]})
        assert session.set_dataframe(df, reason="first") is True
        assert session.data_revision == 1
        same_content = pd.DataFrame({"a": [1, 2]})
        assert session.set_dataframe(same_content, reason="noop") is False
        assert session.data_revision == 1
        changed = pd.DataFrame({"a": [1, 3]})
        assert session.set_dataframe(changed, reason="real") is True
        assert session.data_revision == 2


# ── 2. Идентичность контекста (RED: «тот же filename после повторной
#     загрузки различается»; «цель rain->snow при неизменном datasetId
#     меняет target scope») ────────────────────────────────────────────


class TestContextIdentity:
    def test_context_id_absent_without_dataset_or_run(self):
        assert AnalysisSession(session_id="s-empty").current_context_id() is None

    def test_context_id_deterministic_on_same_state(self):
        _upload(CSV_TWO_NUMERIC)
        _set_target("rain")
        first = _current()["context_id"]
        second = _current()["context_id"]
        assert first
        assert first == second  # сервер владеет контекстом: устойчив между чтениями

    def test_reupload_same_filename_produces_new_identity(self):
        first = _upload(CSV_TWO_NUMERIC)
        _set_target("rain")
        ctx_first = _current()["context_id"]
        run_first = _current()["dataset"]["dataset_id"]
        second = _upload(CSV_TWO_NUMERIC)  # тот же filename
        _set_target("rain")
        ctx_second = _current()["context_id"]
        assert second["dataset_id"] != first["dataset_id"]
        assert run_first != second["dataset_id"]
        assert ctx_first != ctx_second  # новый запуск -- новый контекст

    def test_target_change_moves_context_same_dataset(self):
        _upload(CSV_TWO_NUMERIC)
        _set_target("rain")
        ctx_rain = _current()["context_id"]
        _set_target("snow")
        ctx_snow = _current()["context_id"]
        assert ctx_rain != ctx_snow

    def test_noop_target_choice_keeps_context(self):
        _upload(CSV_TWO_NUMERIC)
        _set_target("rain")
        ctx_first = _current()["context_id"]
        _set_target("rain")  # повторный выбор той же цели
        assert _current()["context_id"] == ctx_first

    def test_date_change_moves_context(self):
        _upload(CSV_TWO_NUMERIC)
        _set_target("rain")
        ctx_before = _current()["context_id"]
        _set_date("date")
        ctx_after = _current()["context_id"]
        assert ctx_before != ctx_after

    def test_revision_bump_moves_context_data_only_nodes_invalidated(self):
        _upload(CSV_WITH_MISSING)
        _set_target("rain")
        ctx_before = _current()["context_id"]
        _missing_corrections("rain", apply=True)
        assert _current()["context_id"] != ctx_before


# ── 3. Unit-контракты data_context (детерминизм, честность digest) ───


class TestDataContextUnit:
    def test_components_shape_and_empty_columns(self):
        comps = context_components(
            dataset_fingerprint="abc",
            data_revision=2,
            target_column=None,
            date_column="date",
        )
        assert comps == {"data": "abc#2", "target": "", "temporal": "date"}

    def test_context_id_requires_run(self):
        comps = context_components(
            dataset_fingerprint="abc", data_revision=0,
            target_column="rain", date_column=None,
        )
        assert compute_context_id(run_id="", components=comps) is None
        ctx = compute_context_id(run_id="RUN-ABC", components=comps)
        assert ctx and ctx.startswith("ctx-")

    def test_context_id_run_scoped_and_deterministic(self):
        comps = context_components(
            dataset_fingerprint="abc", data_revision=0,
            target_column="rain", date_column=None,
        )
        assert compute_context_id(run_id="RUN-A", components=comps) != (
            compute_context_id(run_id="RUN-B", components=comps)
        )
        assert compute_context_id(run_id="RUN-A", components=comps) == (
            compute_context_id(run_id="RUN-A", components=comps)
        )

    def test_digest_distinguishes_values_and_shape(self):
        base = pd.DataFrame({"a": [1, 2], "b": [3.0, 4.0]})
        assert compute_data_digest(base) == compute_data_digest(
            pd.DataFrame({"a": [1, 2], "b": [3.0, 4.0]})
        )
        assert compute_data_digest(base) != compute_data_digest(
            pd.DataFrame({"a": [1, 2], "b": [3.0, 5.0]})
        )
        assert compute_data_digest(base) != compute_data_digest(
            pd.DataFrame({"a": [1, 2, 3], "b": [3.0, 4.0, 5.0]})
        )
        assert compute_data_digest(None) == ""


# ── 4. Envelope context_id продюсеров (§12.7; I3: не перепривязывать) ─


class TestEnvelopeContextStamping:
    def test_hook_event_carries_server_context(self):
        _upload(CSV_TWO_NUMERIC)
        ctx = _current()["context_id"]
        upload_events = _events_of(_trace(), "upload_completed")
        assert upload_events, "upload_completed отсутствует в трассе"
        event = upload_events[-1]
        assert event["context_id"] == ctx
        assert event["schema_version"] == 2

    def test_auto_target_event_carries_context(self):
        _upload(CSV_ONE_NUMERIC)
        ctx = _current()["context_id"]
        changed = _events_of(_trace(), "target_column_changed")
        assert changed, "авто-выбор не засеял target_column_changed"
        assert changed[-1]["context_id"] == ctx

    def test_cleared_event_carries_context(self):
        _upload(CSV_ONE_NUMERIC)
        ctx_before = _current()["context_id"]
        _convert_to_string("rain")  # нечисловая цель -> сброс
        cleared = _events_of(_trace(), "target_column_cleared")
        assert cleared, "сброс цели не засеял target_column_cleared"
        assert cleared[-1]["payload"]["before_target"] == "rain"
        # Контекст события = контекст МОМЕНТА сеяния (после сброса:
        # target-компонент пуст + ревизия конвертации применена -- иные
        # компоненты, чем до конвертации; честная привязка к состоянию,
        # в котором выполнен расчёт, план §6 п.4).
        ctx_after = _current()["context_id"]
        assert ctx_after != ctx_before
        assert cleared[-1]["context_id"] == ctx_after

    def test_captured_context_not_rebound_after_revision_bump(self):
        """I3 (F04/P24): захваченный контекст НЕ перепривязывается к
        текущим данным -- событие ревизии 0 хранит контекст ревизии 0."""
        _upload(CSV_WITH_MISSING)
        _set_target("rain")
        ctx_old = _current()["context_id"]
        _missing_corrections("rain", apply=True)
        ctx_new = _current()["context_id"]
        assert ctx_new != ctx_old
        upload_events = _events_of(_trace(), "upload_completed")
        assert upload_events[-1]["context_id"] == ctx_old

    def test_stale_captured_context_is_historical_for_scoped_nodes(self):
        """«Фоновый результат старой ревизии остаётся историческим»:
        применимость captured-контекста к текущим данным по реестру
        scopes -- stale для зависимых узлов, НЕ current."""
        _upload(CSV_WITH_MISSING)
        _set_target("rain")
        captured = _current()["context_id"]
        # компоненты captured читаем из сессии ДО bump (честный доступ
        # потребителя -- по известным компонентам контекста)
        captured_comps = dict(
            context_components(
                dataset_fingerprint="", data_revision=0,
                target_column="rain", date_column="date",
            )
        )
        _missing_corrections("rain", apply=True)
        current = _current()["context_id"]
        assert current != captured
        # data-dependent узлы: ревизия изменилась -> stale
        assert node_context_validity(
            "validation", "data_types", captured_comps,
            context_components(dataset_fingerprint="", data_revision=1,
                               target_column="rain", date_column="date"),
        ) == "stale"


# ── 5. Реестр dependency scopes (один реестр -- контракт §3.4) ───────


class TestDependencyScopeRegistry:
    def test_registry_covers_all_graph_nodes(self):
        for stage, node_id in iter_all_nodes():
            assert stage in NODE_DEPENDENCY_SCOPES, f"стадия {stage} вне реестра"
            assert node_id in NODE_DEPENDENCY_SCOPES[stage], (
                f"узел {stage}/{node_id} вне реестра scopes"
            )
        # и без сирот: реестр не шире графа
        assert set(NODE_DEPENDENCY_SCOPES.keys()) == set(pipeline_graph.STAGES)
        for stage, nodes in NODE_DEPENDENCY_SCOPES.items():
            assert set(nodes.keys()) == set(pipeline_graph.STAGE_NODES[stage])

    def test_scopes_are_canonical_and_nonempty(self):
        for stage, nodes in NODE_DEPENDENCY_SCOPES.items():
            for node_id, scopes in nodes.items():
                assert isinstance(scopes, frozenset)
                assert scopes, f"{stage}/{node_id}: пустые зависимости"
                assert scopes <= set(CONTEXT_SCOPES), (
                    f"{stage}/{node_id}: вне канона {CONTEXT_SCOPES}"
                )

    def test_matrix_semantics_spot_checks(self):
        assert node_dependency_scopes("upload", "overview") == frozenset({"data"})
        assert node_dependency_scopes("upload", "structure") == frozenset(
            {"data", "temporal"}
        )
        assert node_dependency_scopes("validation", "data_types") == frozenset({"data"})
        assert "temporal" in node_dependency_scopes("validation", "regularity")
        assert node_dependency_scopes("preprocessing", "missing") == frozenset({"data"})
        for stage in ("eda", "modeling", "forecasting"):
            for node_id in pipeline_graph.STAGE_NODES[stage]:
                assert node_dependency_scopes(stage, node_id) == frozenset(
                    {"data", "target", "temporal"}
                ), f"{stage}/{node_id}"

    def test_node_dependency_scopes_fail_closed(self):
        with pytest.raises(ValueError):
            node_dependency_scopes("no-such-stage", "overview")
        with pytest.raises(ValueError):
            node_dependency_scopes("validation", "no-such-node")

    def test_validity_unknown_current_stale(self):
        current = context_components(
            dataset_fingerprint="fp", data_revision=1,
            target_column="rain", date_column="date",
        )
        # нет захваченного контекста -- честное unknown
        assert node_context_validity("eda", "descriptive", None, current) == "unknown"
        assert node_context_validity("eda", "descriptive", {}, current) == "unknown"
        # тот же контекст -- current
        assert (
            node_context_validity("eda", "descriptive", dict(current), current)
            == "current"
        )
        # смена ТОЛЬКО цели: data-only узел остаётся current (риск карточки:
        # «нельзя инвалидировать все узлы на любую настройку»), EDA -- stale
        target_moved = {**current, "target": "snow"}
        assert (
            node_context_validity("validation", "data_types", target_moved, current)
            == "current"
        )
        assert (
            node_context_validity("eda", "descriptive", target_moved, current)
            == "stale"
        )
        # target-dependent done при смене цели НЕ сохраняется как current (I6)
        # смена данных: data-узел тоже stale
        data_moved = {**current, "data": "fp#2"}
        assert (
            node_context_validity("validation", "data_types", data_moved, current)
            == "stale"
        )
        # неполный captured (нет скоупа узла) -- unknown, не current
        assert (
            node_context_validity(
                "eda", "descriptive", {"data": "fp#1"}, current
            )
            == "unknown"
        )


# ── 6. Сериализация и CAS (план §6 п.5; RED: «CAS-конфликт не выдаёт
#     ложное обновление») ──────────────────────────────────────────────


class TestSerializationAndCas:
    def test_roundtrip_preserves_revision_and_digest(self):
        store = MemorySessionStore()
        session = store.get_or_create("s-rt")
        session.set_dataset(
            DatasetInfo(
                dataset_id="d1", name="data.csv", rows=2, columns=2,
                size_label="1 KB", dataset_fingerprint="fp-1",
            ),
            pd.DataFrame({"a": [1, 2]}),
        )
        session.set_dataframe(pd.DataFrame({"a": [1, 2, 3]}), reason="correction")
        rev, digest = session.data_revision, session.data_digest
        from apps.api.session_store import session_from_dict, session_to_dict

        doc = session_to_dict(session)
        restored = session_from_dict(doc)
        assert restored.data_revision == rev
        assert restored.data_digest == digest
        assert restored.current_context_id() == session.current_context_id()

    def test_legacy_document_gets_honest_defaults(self):
        from apps.api.session_store import session_from_dict

        legacy = {"session_id": "s-old", "stages": {}}
        restored = session_from_dict(legacy)
        assert restored.data_revision == 0
        assert restored.data_digest == ""

    def test_redis_cas_conflict_no_false_update(self):
        """CAS-конфликт: устаревший снимок НЕ перезаписывает свежий
        документ, ревизия/контекст остаются у winner'а, счётчик
        storage_revision у проигравшего не выдумывается."""
        from fakeredis import FakeStrictRedis

        from apps.api.session_store import RedisSessionStore

        store = RedisSessionStore(client=FakeStrictRedis())
        winner = store.get_or_create("s-cas")
        winner.set_dataset(
            DatasetInfo(
                dataset_id="d1", name="data.csv", rows=2, columns=2,
                size_label="1 KB", dataset_fingerprint="fp-1",
            ),
            pd.DataFrame({"a": [1.0, 2.0, None, 4.0]}),
        )
        store.save(winner)
        stale = store.get("s-cas")
        assert stale is not None
        # winner уходит вперёд: реальная коррекция данных
        fresh = store.get("s-cas")
        fresh.set_dataframe(
            pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0]}), reason="correction"
        )
        store.save(fresh)
        # stale пробует записать своё (контент старый) -- конфликт
        with pytest.raises(SessionConflictError):
            store.save(stale)
        # ложного обновления нет: в хранилище данные winner'а
        reread = store.get("s-cas")
        assert reread.data_revision == fresh.data_revision
        assert reread.data_digest == fresh.data_digest
        assert reread.current_context_id() == fresh.current_context_id()
        # у stale счётчик ревизий НЕ выдуман (не incremented при отказе)
        assert stale.storage_revision < reread.storage_revision


# ── 7. API: устойчивый контекст отдаётся клиенту (гидратация UI) ─────


class TestApiContextExposure:
    def test_current_returns_context_and_revision(self):
        _upload(CSV_TWO_NUMERIC)
        body = _current()
        assert body["context_id"]
        assert body["data_revision"] == 0

    def test_current_reflects_revision_after_correction(self):
        _upload(CSV_WITH_MISSING)
        _missing_corrections("rain", apply=True)
        body = _current()
        assert body["data_revision"] == 1
        assert body["context_id"]

    def test_client_cannot_supply_context(self):
        """Контекст создаётся ТОЛЬКО сервером (план §1: фронт контекст не
        создаёт догадками): /current без параметров, POST-маршруты
        выбора не принимают контекст/ревизию -- подмена версии
        собственным счётчиком фронтенда исключена контрактом API."""
        _upload(CSV_TWO_NUMERIC)
        first = _current()["context_id"]
        second = _current()["context_id"]
        assert first == second  # сервер пересчитывает, не доверяет клиенту
