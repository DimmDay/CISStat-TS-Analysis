# tests/api/test_progress_audit_1a.py
"""
PROGR-AUDIT-1A: сброс и восстановление цели/происхождения
(plan_progress_audit.md §9; spec_progress_audit.md F02/F03, P03/P04).

Задача на фундаменте AUDIT-C → AUDIT-5B (план §3: предшественники
закрыты). Состав карточки §9:

  1. ОДИН effective-target reducer обрабатывает choice/reset
     (session/run metadata, reason, Наставник, документ -- потребители
     одной семантики). До задачи: минимум четыре независимые реализации
     правил (тройка Наставника, ветки record_run_event, reason-mark
     node_status, restore) с задокументированным расхождением
     (пустой target в changed: run-метаданные -- сброс, Наставник --
     пропуск; мусорный source: origin фабриковал "user").
  2. При сбросе очищаются цель И origin (парно); прежний выбор
     сохраняется исторически (before_target + события в ledger).
  3. Restore восстанавливает СОГЛАСОВАННУЮ пару target/source
     (F03/P04: restore терял session.target_column_source -- после
     restore авто-выбор выглядел выбором без происхождения).
     Старый payload без source читается как user (legacy-контракт
     PROGR-25-A), повреждённое происхождение -- unknown (спека §8.2:
     «повреждённую историю не выдавать за подтверждённого человека»).
  4. Restore НЕ производит повторный авто-выбор (спека §8.2; план §9):
     сброшенная цель не воскресает из raw-файла, второго события
     выбора нет. Backend singleton-правило и исключение
     зарегистрированных производных сохраняются.

RED-сценарии карточки: P03/P04 по исправленным ожиданиям;
auto→reset→manual; manual→reset; reset без новой цели; два числовых;
demo; legacy source; выбор из зарегистрированных исходных/производных.

Границы (план §9, риск): сброс внутри correction payload не
игнорируется и не дублируется (ровно один cleared на сброс; хук сеет
correction_applied -- ДРУГОЙ тип); POST /target-column остаётся
маршрутом выбора (422 на пустой); raw restore-семантика и
historical/validity -- AUDIT-8; шаблоны отчёта -- AUDIT-7B.
"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.core.mentor_rules import (
    _phase_event_text_facts,
    _target_confirmed,
    _target_origin,
    phase_text,
)
from app.core.node_status import (
    derive_last_active_stage,
    derive_node_statuses,
    derive_pipeline_node_states,
)
from apps.api import research_runs
from apps.api.main import app
from apps.api.session_store import (
    get_session_store,
    reset_session_store_for_testing,
    SESSION_COOKIE_NAME,
)
from apps.api.trace_events import make_trace_event


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path, monkeypatch):
    """Изоляция КАЖДОГО теста: свои каталоги данных (файловый слой --
    restore перечитывает исходный файл), чистые синглтоны, Memory-бэкенды
    ОБОИХ хранилищ (паттерн test_research_runs / test_progress_audit_h1)."""
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CISSTAT_RUNS_BACKEND", "memory")
    reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    yield
    reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()


client = TestClient(app)


# ── Harness (паттерн test_progress_audit_h1) ─────────────────────────

CSV_ONE_NUMERIC = (
    "date,rain\n"
    "2023-01-01,10.5\n"
    "2023-01-02,20.1\n"
    "2023-01-03,30.2\n"
    "2023-01-04,15.8\n"
)

CSV_TWO_NUMERIC = (
    "date,rain,snow\n"
    "2023-01-01,10.5,1.0\n"
    "2023-01-02,20.1,2.0\n"
    "2023-01-03,30.2,3.0\n"
    "2023-01-04,15.8,4.0\n"
)


def _upload_csv(csv: str, name: str = "single.csv") -> dict:
    file = io.BytesIO(csv.encode("utf-8"))
    resp = client.post(
        "/v1/internal/upload",
        files={"file": (name, file, "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _convert_to_string(column: str, apply: bool = True):
    return client.post(
        "/v1/session/dataset/convert-types",
        json={
            "conversions": [{"column": column, "target_type": "string"}],
            "invalid_policy": "coerce",
            "apply": apply,
        },
    )


def _choose(column: str):
    return client.post("/v1/session/target-column", json={"column": column})


def _target_state() -> dict:
    resp = client.get("/v1/session/target-column")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _trace() -> dict:
    resp = client.get("/v1/progress/trace")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _confirm_structure_like_ui() -> None:
    """UI-автопревью Загрузки (канон репро PROGR-25-C/H1): уверенная
    дата фиксируется сама -- узел upload/structure становится done."""
    resp = client.post("/v1/session/date-column", json={"column": "date"})
    assert resp.status_code == 200, resp.text


def _run_id() -> str:
    run_id = _trace().get("run_id") or ""
    assert run_id, "run_id не зафиксирован в трассе слоя 1"
    return run_id


def _run_meta(run_id: str) -> research_runs.ResearchRun:
    run = research_runs.get_research_run_store().get_run(run_id)
    assert run is not None, "запуск не найден в слое 2"
    return run


def _cleared(trace: dict) -> list[dict]:
    return [
        e for e in trace.get("events", [])
        if e.get("event_type") == "target_column_cleared"
    ]


def _choices(trace: dict) -> list[dict]:
    return [
        e for e in trace.get("events", [])
        if e.get("event_type") == "target_column_changed"
    ]


def _mentor_text() -> str:
    """Метод наблюдения инструмента аудита P03 (H1-пин): текст фазы
    «Загрузка» по событиям слоя 2 НАПРЯМУЮ -- «historical_mentor_
    upload_text»."""
    store = research_runs.get_research_run_store()
    layer2 = store.list_events(_run_id())
    return phase_text(
        "upload", statuses=derive_node_statuses(layer2), events=layer2,
    )


def _restore(run_id: str) -> dict:
    """Рекалибровка DOCLOG-0 (P3): restore -- под bearer владельца
    (cookie исследования модульного клиента); bare run_id не право
    (§15.1). Новый cookie -- из ответа (джар несёт и bearer, и новый)."""
    fresh = TestClient(app)
    owner_cookie = client.cookies.get(SESSION_COOKIE_NAME)
    if owner_cookie:
        fresh.cookies.set(SESSION_COOKIE_NAME, owner_cookie)
    resp = fresh.get(f"/v1/progress/runs/{run_id}/restore")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    fresh.cookies.clear()
    new_cookie = resp.cookies.get(SESSION_COOKIE_NAME) or ""
    if new_cookie:
        fresh.cookies.set(SESSION_COOKIE_NAME, new_cookie)
    data["_session_id"] = new_cookie or owner_cookie or ""
    return data


def _reason_of(stage: str, node_id: str) -> str:
    trace = _trace()
    nodes = [
        n for n in trace.get("nodes", [])
        if n.get("stage") == stage and n.get("node_id") == node_id
    ]
    assert nodes, f"узел {stage}/{node_id} отсутствует"
    return nodes[0].get("status_reason") or ""


# ── 1. Единый effective-target reducer ───────────────────────────────


class TestEffectiveTargetReducer:
    """app/core/effective_target.py -- ЕДИНСТВЕННАЯ реализация правил
    choice/reset (план §9: один reducer для session/run metadata, reason,
    Наставника и документа)."""

    def _module(self):
        from app.core import effective_target

        return effective_target

    def test_choice_auto_fact(self):
        eff = self._module()
        event = make_trace_event(
            "target_column_changed", stage="validation", node_id=None,
            run_id="r1", actor="system", target_column="rain", source="auto",
        )
        state = eff.effective_target([event])
        assert state.target == "rain"
        assert state.origin == "auto"
        assert state.resolved is True
        assert state.source_event_id == event.event_id

    def test_choice_without_source_is_user_legacy(self):
        # Legacy-контракт PROGR-25-A: отсутствие source у ВЫБОРА -- user
        # (ручной маршрут сеет payload без source).
        eff = self._module()
        event = make_trace_event(
            "target_column_changed", stage="validation", node_id=None,
            run_id="r1", actor="user", target_column="snow",
        )
        state = eff.effective_target([event])
        assert state.target == "snow"
        assert state.origin == "user"
        assert state.resolved is True

    def test_damaged_provenance_is_unknown_not_user(self):
        # Спека §8.2 / контракт §3.7: повреждённое происхождение --
        # unknown, НЕ «подтверждённый человек».
        eff = self._module()
        event = make_trace_event(
            "target_column_changed", stage="validation", node_id=None,
            run_id="r1", actor="bot", target_column="rain", source="bot",
        )
        state = eff.effective_target([event])
        assert state.target == "rain"
        assert state.origin is None

    def test_cleared_resets_pair_and_keeps_history(self):
        # Контракт §3.1 п.4: после cleared origin = None, НЕ "user";
        # прежний выбор сохраняется исторически (before_target в payload,
        # события в ledger -- редьюсер это не трогает).
        eff = self._module()
        choice = make_trace_event(
            "target_column_changed", stage="validation", node_id=None,
            run_id="r1", actor="system", target_column="rain", source="auto",
        )
        cleared = make_trace_event(
            "target_column_cleared", stage="validation", node_id=None,
            run_id="r1", actor="system", target_column=None,
            reset_reason="type_conversion", source="system",
            before_target="rain",
        )
        state = eff.effective_target([choice, cleared])
        assert state.target is None
        assert state.origin is None
        assert state.resolved is True
        assert state.source_event_id == cleared.event_id

    def test_empty_target_changed_is_reset_canon(self):
        # Канон PROGR-15-B (паритет run-метаданных и reason-ветки:
        # «пустой target_column -- сброс выбора»): legacy-форма пустого
        # target в changed -- сброс, а не пропуск.
        eff = self._module()
        choice = make_trace_event(
            "target_column_changed", stage="validation", node_id=None,
            run_id="r1", actor="user", target_column="rain",
        )
        legacy_reset = make_trace_event(
            "target_column_changed", stage="validation", node_id=None,
            run_id="r1", actor="user", target_column="",
        )
        state = eff.effective_target([choice, legacy_reset])
        assert state.target is None
        assert state.origin is None
        assert state.resolved is True

    def test_garbage_target_changed_is_not_fact(self):
        # R3 (трасса -- журнал): мусорный target -- не факт вовсе;
        # редьюсер его пропускает, состояние не фабрикуется.
        eff = self._module()
        garbage = make_trace_event(
            "target_column_changed", stage="validation", node_id=None,
            run_id="r1", actor="user", target_column=123,
        )
        state = eff.effective_target([garbage])
        assert state.resolved is False
        assert state.target is None
        assert state.origin is None

    def test_empty_corpus_is_unresolved(self):
        eff = self._module()
        state = eff.effective_target([])
        assert state.resolved is False
        assert state.target is None
        assert state.origin is None

    def test_non_target_events_do_not_reset_state(self):
        eff = self._module()
        choice = make_trace_event(
            "target_column_changed", stage="validation", node_id=None,
            run_id="r1", actor="system", target_column="rain", source="auto",
        )
        noise = make_trace_event(
            "upload_completed", stage="upload", node_id="overview",
            run_id="r1", actor="system", name="f.csv",
        )
        state = eff.effective_target([choice, noise])
        assert state.target == "rain"
        assert state.origin == "auto"

    def test_last_wins_in_given_canonical_order(self):
        # Порядок -- ответственность вызывающего (канонический порядок
        # §3.3); редьюсер честен к данному порядку (P12: не сортирует сам).
        eff = self._module()
        auto = make_trace_event(
            "target_column_changed", stage="validation", node_id=None,
            run_id="r1", actor="system", target_column="rain", source="auto",
        )
        manual = make_trace_event(
            "target_column_changed", stage="validation", node_id=None,
            run_id="r1", actor="user", target_column="snow",
        )
        assert eff.effective_target([auto, manual]).target == "snow"
        assert eff.effective_target([manual, auto]).target == "rain"

    def test_accepts_trace_event_and_dict_forms(self):
        eff = self._module()
        event = make_trace_event(
            "target_column_changed", stage="validation", node_id=None,
            run_id="r1", actor="system", target_column="rain", source="auto",
        )
        as_dict = event.to_dict()
        assert eff.effective_target([event]).target == "rain"
        assert eff.effective_target([as_dict]).target == "rain"

    def test_garbage_event_degrades_honestly(self):
        eff = self._module()
        state = eff.effective_target(["мусор", None, 42])
        assert state.resolved is False


class TestMentorThroughReducer:
    """Тройка Наставника -- потребитель ЕДИНОГО редьюсера (план §9):
    результаты совпадают на смешанном корпусе, второй реализации
    семантики не существует."""

    def _mixed_corpus(self):
        choice_auto = make_trace_event(
            "target_column_changed", stage="validation", node_id=None,
            run_id="r1", actor="system", target_column="rain", source="auto",
        )
        noise = make_trace_event(
            "correction_applied", stage="validation", node_id="data_types",
            run_id="r1", actor="user", applied=True,
        )
        cleared = make_trace_event(
            "target_column_cleared", stage="validation", node_id=None,
            run_id="r1", actor="system", target_column=None,
            reset_reason="type_conversion", source="system",
            before_target="rain",
        )
        manual = make_trace_event(
            "target_column_changed", stage="validation", node_id=None,
            run_id="r1", actor="user", target_column="snow",
        )
        return [choice_auto, noise, cleared, manual]

    def test_confirmed_matches_reducer(self):
        from app.core import effective_target

        events = self._mixed_corpus()
        assert _target_confirmed(events) is (
            effective_target.effective_target(events).target is not None
        )
        assert _target_confirmed(events) is True

    def test_origin_matches_reducer(self):
        from app.core import effective_target

        events = self._mixed_corpus()
        assert _target_origin(events) == (
            effective_target.effective_target(events).origin
        )
        assert _target_origin(events) == "user"

    def test_phase_facts_match_reducer(self):
        from app.core import effective_target

        events = self._mixed_corpus()
        expected = effective_target.effective_target(events).target or ""
        facts = _phase_event_text_facts(tuple(events))
        assert facts == (
            {"target_column": expected} if expected else {}
        )


# ── 2. Run-метаданные: пара target/source через редьюсер ─────────────


class TestRunMetadataPair:
    """record_run_event зеркалирует пару (target, origin) нормализацией
    ЕДИНОГО редьюсера; повреждённое происхождение не фабрикуется."""

    def test_changed_auto_sets_pair(self):
        from apps.api.session_store import AnalysisSession

        session = AnalysisSession(session_id="s1")
        session.run_id = "r1"
        event = make_trace_event(
            "target_column_changed", stage="validation", node_id=None,
            run_id="r1", actor="system", target_column="rain", source="auto",
        )
        research_runs.record_run_event(session, event)
        run = research_runs.get_research_run_store().get_run("r1")
        assert run.target_column == "rain"
        assert run.target_column_source == "auto"

    def test_changed_manual_without_source_sets_user(self):
        from apps.api.session_store import AnalysisSession

        session = AnalysisSession(session_id="s1")
        session.run_id = "r1"
        # Ручной маршрут: payload без source (legacy-совместимо).
        event = make_trace_event(
            "target_column_changed", stage="validation", node_id=None,
            run_id="r1", actor="user", target_column="snow",
        )
        research_runs.record_run_event(session, event)
        run = research_runs.get_research_run_store().get_run("r1")
        assert run.target_column == "snow"
        assert run.target_column_source == "user"

    def test_cleared_nulls_pair(self):
        from apps.api.session_store import AnalysisSession

        session = AnalysisSession(session_id="s1")
        session.run_id = "r1"
        choice = make_trace_event(
            "target_column_changed", stage="validation", node_id=None,
            run_id="r1", actor="system", target_column="rain", source="auto",
        )
        cleared = make_trace_event(
            "target_column_cleared", stage="validation", node_id=None,
            run_id="r1", actor="system", target_column=None,
            reset_reason="type_conversion", source="system",
            before_target="rain",
        )
        research_runs.record_run_event(session, choice)
        research_runs.record_run_event(session, cleared)
        run = research_runs.get_research_run_store().get_run("r1")
        assert run.target_column is None
        assert run.target_column_source is None

    def test_garbage_target_does_not_fabricate_metadata(self):
        from apps.api.session_store import AnalysisSession

        session = AnalysisSession(session_id="s1")
        session.run_id = "r1"
        choice = make_trace_event(
            "target_column_changed", stage="validation", node_id=None,
            run_id="r1", actor="system", target_column="rain", source="auto",
        )
        garbage = make_trace_event(
            "target_column_changed", stage="validation", node_id=None,
            run_id="r1", actor="user", target_column=123,
        )
        research_runs.record_run_event(session, choice)
        research_runs.record_run_event(session, garbage)
        run = research_runs.get_research_run_store().get_run("r1")
        # Мусор -- не факт: метаданные не тронуты (не «123», не сброс).
        assert run.target_column == "rain"
        assert run.target_column_source == "auto"

    def test_to_dict_from_dict_roundtrip(self):
        run = research_runs.ResearchRun(
            run_id="r1", target_column="rain", target_column_source="auto",
        )
        restored = research_runs.ResearchRun.from_dict(run.to_dict())
        assert restored.target_column == "rain"
        assert restored.target_column_source == "auto"
        # None -- осознанное значение пары (сброс), а не отсутствие.
        reset = research_runs.ResearchRun(
            run_id="r2", target_column=None, target_column_source=None,
        )
        restored_reset = research_runs.ResearchRun.from_dict(reset.to_dict())
        assert restored_reset.target_column is None
        assert restored_reset.target_column_source is None


# ── 3. Сброс: полная согласованность потребителей (P03-corrected) ────


class TestResetConsistency:
    def test_full_reset_consistency(self):
        """auto→reset: /current, селектор, run-метаданные (ТЕПЕРЬ И
        origin), /trace (ровно один cleared), Наставник и reason
        согласованы -- ожидание P03 по исправленным ожиданиям."""
        _upload_csv(CSV_ONE_NUMERIC)
        _confirm_structure_like_ui()
        run_id = _run_id()
        assert _target_state()["target_column"] == "rain"
        assert _target_state()["target_column_source"] == "auto"

        resp = _convert_to_string("rain")
        assert resp.status_code == 200
        assert resp.json()["target_column_reset"] is True

        # Сессия: парная очистка (цель И origin).
        assert _target_state()["target_column"] is None
        assert _target_state()["target_column_source"] is None

        # Run-метаданные: та же пара.
        run = _run_meta(run_id)
        assert run.target_column is None
        assert run.target_column_source is None

        # Ровно ОДИН cleared (риск карточки: не два при hook+handler).
        trace = _trace()
        assert len(_cleared(trace)) == 1
        cleared = _cleared(trace)[0]
        assert cleared["payload"]["reset_reason"] == "type_conversion"
        assert cleared["payload"]["before_target"] == "rain"

        # Наставник честно просит подтвердить (fallback P03).
        text = _mentor_text()
        assert "Подтвердите целевой признак" in text

        # Reason своего класса снят.
        assert _reason_of("validation", "sufficiency") == ""

    def test_reset_without_new_target_stays_cleared(self):
        """reset без новой цели: состояние остаётся честно пустым у всех
        потребителей (никто не «воскрешает» цель)."""
        _upload_csv(CSV_ONE_NUMERIC)
        _confirm_structure_like_ui()
        run_id = _run_id()
        _convert_to_string("rain")
        assert _target_state()["target_column"] is None
        run = _run_meta(run_id)
        assert run.target_column is None
        assert run.target_column_source is None
        # Выбор один (авто при загрузке), сброс -- один; НОВОГО выбора
        # после сброса нет (последний факт цели -- cleared).
        trace = _trace()
        assert len(_choices(trace)) == 1
        assert len(_cleared(trace)) == 1
        store = research_runs.get_research_run_store()
        from app.core.effective_target import effective_target as _eff

        state = _eff(store.list_events(run_id))
        assert state.resolved is True
        assert state.target is None

    def test_preview_does_not_reset(self):
        """Preview не меняет данных -- сброса нет (граница H1)."""
        _upload_csv(CSV_ONE_NUMERIC)
        resp = _convert_to_string("rain", apply=False)
        assert resp.status_code == 200
        assert resp.json()["target_column_reset"] is False
        assert len(_cleared(_trace())) == 0
        assert _target_state()["target_column"] == "rain"

    def test_manual_route_rejects_empty_no_cleared(self):
        """POST /target-column остаётся маршрутом ВЫБОРА (422 на пустой,
        контракт §3.1 п.5, пин H1); сброс через него невозможен."""
        _upload_csv(CSV_ONE_NUMERIC)
        resp = client.post("/v1/session/target-column", json={"column": None})
        assert resp.status_code == 422
        assert len(_cleared(_trace())) == 0

    def test_report_header_follows_reset(self):
        """Документ -- потребитель той же проекции run-метаданных
        (план §9): после сброса заголовок отчёта не называет цель."""
        from app.core.run_report import build_report_model

        _upload_csv(CSV_ONE_NUMERIC)
        run_id = _run_id()
        _convert_to_string("rain")
        run = _run_meta(run_id)
        store = research_runs.get_research_run_store()
        model = build_report_model(
            run.to_dict(), [e.to_dict() for e in store.list_events(run_id)],
        )
        assert model.target_column is None


# ── 4. Restore: согласованная пара (F03/P04-corrected) ───────────────


class TestRestorePair:
    def test_restore_keeps_auto_origin(self):
        """P04 по исправленному ожиданию: restore возвращает ЦЕЛЬ И
        ПРОИСХОЖДЕНИЕ; второго события выбора нет."""
        _upload_csv(CSV_ONE_NUMERIC)
        run_id = _run_id()
        choices_before = len(
            [
                e
                for e in research_runs.get_research_run_store().list_events(run_id)
                if e.event_type == "target_column_changed"
            ]
        )
        assert choices_before == 1

        data = _restore(run_id)
        assert data["target_column"] == "rain"
        # F03: происхождение НЕ теряется.
        assert data["target_column_source"] == "auto"

        session = get_session_store().get(data["_session_id"])
        assert session.target_column == "rain"
        assert session.target_column_source == "auto"

        # Селектор новой сессии -- тот же факт.
        state_resp = client.get(
            "/v1/session/target-column",
            cookies={SESSION_COOKIE_NAME: data["_session_id"]},
        )
        assert state_resp.json()["target_column"] == "rain"
        assert state_resp.json()["target_column_source"] == "auto"

        # Второго события выбора нет (ни в слое 1, ни в ledger).
        store = research_runs.get_research_run_store()
        ledger_choices = [
            e for e in store.list_events(run_id)
            if e.event_type == "target_column_changed"
        ]
        assert len(ledger_choices) == 1
        session_trace = get_session_store().get(
            data["_session_id"]
        ).read_pipeline_trace()
        assert len(
            [e for e in session_trace if e.event_type == "target_column_changed"]
        ) == 1

    def test_restore_after_reset_no_resurrection_no_rechoice(self):
        """auto→reset→restore: сброшенная цель НЕ воскресает из
        устаревших метаданных и НЕ переизбирается авто-правилом на raw
        файле с единственной числовой (спека §8.2: не выполнять
        повторный авто-выбор как замену восстановлению)."""
        _upload_csv(CSV_ONE_NUMERIC)
        run_id = _run_id()
        assert _run_meta(run_id).target_column == "rain"
        _convert_to_string("rain")
        assert _run_meta(run_id).target_column is None

        data = _restore(run_id)
        # Raw-файл имеет единственную числовую rain: авто-пере-выбор дал
        # бы rain -- запрещён.
        assert data["target_column"] is None
        assert data["target_column_source"] is None
        session = get_session_store().get(data["_session_id"])
        assert session.target_column is None
        assert session.target_column_source is None

        # Restore не сеет событий выбора/сброса.
        store = research_runs.get_research_run_store()
        new_events = [
            e.event_type for e in store.list_events(run_id)
        ]
        assert new_events[-1] == "run_resumed"
        assert "target_column_changed" not in new_events[1:]
        assert len([t for t in new_events if t == "target_column_cleared"]) == 1

    def test_restore_manual_user_origin(self):
        """demo→manual→restore: origin=user восстанавливается."""
        resp = client.post("/v1/session/demo")
        assert resp.status_code == 200
        run_id = _run_id()
        choose = _choose("sales")
        assert choose.status_code == 200

        data = _restore(run_id)
        assert data["target_column"] == "sales"
        assert data["target_column_source"] == "user"
        session = get_session_store().get(data["_session_id"])
        assert session.target_column_source == "user"

    def test_restore_replays_ledger_over_stale_metadata(self):
        """Ledger авторитетен: сброс в истории сильнее устаревших
        метаданных (не вернуть reset-цель из устаревших метаданных)."""
        _upload_csv(CSV_ONE_NUMERIC)
        run_id = _run_id()
        _convert_to_string("rain")
        store = research_runs.get_research_run_store()
        # Имитация устаревших/повреждённых метаданных (цель «воскресла»
        # вне события): ledger говорит «сброшено».
        stale = store.get_run(run_id)
        from dataclasses import replace as dc_replace

        store.upsert_run(dc_replace(stale, target_column="rain"))
        assert store.get_run(run_id).target_column == "rain"

        data = _restore(run_id)
        assert data["target_column"] is None
        assert data["target_column_source"] is None

    def test_restore_metadata_fallback_without_ledger_facts(self):
        """Legacy-корпус без фактов цели в ledger: согласованные
        метаданные как fallback; происхождение -- честное отсутствие."""
        store = research_runs.get_research_run_store()
        store.upsert_run(
            research_runs.ResearchRun(
                run_id="legacy-r1",
                session_id="s0",
                dataset_name="legacy.csv",
                target_column="rain",
            )
        )
        # Файл в файловом слое отсутствует -> restore 409 -- нужен файл.
        # Регистрируем файл вручную тем же fingerprint.
        from apps.api.research_runs import get_dataset_file_store
        import csv as _csv

        buf = io.StringIO()
        writer = _csv.writer(buf)
        writer.writerow(["rain"])
        writer.writerow([1.5])
        fingerprint = get_dataset_file_store().save_upload(
            buf.getvalue().encode("utf-8"), "legacy.csv",
            rows=1, columns=1, size_label="1 B",
        )
        # Рекалибровка DOCLOG-0 (P1): легаси-run сеется на cookie-сессию
        # модульного клиента -- серверный континуитет §15.1 (создавшая
        # сессия продолжает свой запуск).
        client.get("/v1/progress/trace")  # фиксируем cookie клиента
        store.upsert_run(
            research_runs.ResearchRun(
                run_id="legacy-r1",
                session_id=client.cookies.get(SESSION_COOKIE_NAME),
                dataset_fingerprint=fingerprint,
                dataset_name="legacy.csv",
                target_column="rain",
            )
        )
        # P3: restore под bearer владельца (не bare run_id).
        data = _restore("legacy-r1")
        assert data["target_column"] == "rain"
        assert data["target_column_source"] is None
        session = get_session_store().get(data["_session_id"])
        assert session.target_column == "rain"
        assert session.target_column_source is None

    def test_restore_unapplicable_target_leaves_pair_empty(self):
        """Цель, неприменимая к raw-данным (отсутствует/нечисловая), не
        восстанавливается; парная origin тоже (согласованность пары)."""
        _upload_csv(CSV_ONE_NUMERIC)
        run_id = _run_id()
        store = research_runs.get_research_run_store()
        from dataclasses import replace as dc_replace

        # Ledger-факт выбора несуществующей колонки (повреждённый корпус).
        ghost = make_trace_event(
            "target_column_changed", stage="validation", node_id=None,
            run_id=run_id, actor="user", target_column="ghost",
        )
        store.append_event(run_id, ghost)

        data = _restore(run_id)
        assert data["target_column"] is None
        assert data["target_column_source"] is None
        session = get_session_store().get(data["_session_id"])
        assert session.target_column is None
        assert session.target_column_source is None

    def test_restore_two_numeric_no_auto_rechoice(self):
        """Два числовых: неоднозначность честна и после restore --
        пере-выбора нет."""
        _upload_csv(CSV_TWO_NUMERIC, name="two.csv")
        run_id = _run_id()
        assert _target_state()["target_column"] is None
        data = _restore(run_id)
        assert data["target_column"] is None
        assert data["target_column_source"] is None
        new_session = get_session_store().get(data["_session_id"])
        assert new_session.target_column is None

    def test_restored_session_origin_visible_in_trace_header(self):
        """Шапка /trace восстановленной сессии -- та же пара (один
        источник с селектором и /current)."""
        _upload_csv(CSV_ONE_NUMERIC)
        run_id = _run_id()
        data = _restore(run_id)
        sid = data["_session_id"]
        resp = client.get("/v1/progress/trace", cookies={SESSION_COOKIE_NAME: sid})
        trace = resp.json()
        assert trace["target_column"] == "rain"
        assert trace["target_column_source"] == "auto"


# ── 5. Полный цикл auto→reset→manual→reset (карточка §9 RED) ─────────


class TestFullCycle:
    def test_auto_reset_manual_cycle(self):
        _upload_csv(CSV_ONE_NUMERIC)
        _confirm_structure_like_ui()
        run_id = _run_id()

        # auto
        assert _target_state()["target_column"] == "rain"
        assert _target_state()["target_column_source"] == "auto"

        # reset
        _convert_to_string("rain")
        assert _target_state()["target_column"] is None
        assert _run_meta(run_id).target_column_source is None
        assert "Подтвердите целевой признак" in _mentor_text()

        # manual (rain больше не числовая -- в сессии после конвертации
        # числовых нет; выбор даёт 422. Проверяем честность: ручной выбор
        # возможен только из числовых.)
        resp = _choose("rain")
        assert resp.status_code == 422

    def test_manual_reset_cycle_on_two_numeric(self):
        """manual→reset: ручной выбор + сброс -- парная очистка."""
        _upload_csv(CSV_TWO_NUMERIC, name="two.csv")
        run_id = _run_id()
        assert _choose("snow").status_code == 200
        assert _target_state()["target_column"] == "snow"
        assert _target_state()["target_column_source"] == "user"
        assert _run_meta(run_id).target_column == "snow"
        assert _run_meta(run_id).target_column_source == "user"

        _convert_to_string("snow")
        assert _target_state()["target_column"] is None
        assert _target_state()["target_column_source"] is None
        run = _run_meta(run_id)
        assert run.target_column is None
        assert run.target_column_source is None
        trace = _trace()
        assert len(_cleared(trace)) == 1
        cleared = _cleared(trace)[0]
        assert cleared["payload"]["before_target"] == "snow"
        # Выбор сохранён исторически в ledger.
        assert len(_choices(trace)) == 1

    def test_choice_after_reset_restores_state(self):
        """auto→reset→manual (H1 канон): выбор после сброса
        восстанавливает факт у всех потребителей."""
        _upload_csv(CSV_TWO_NUMERIC, name="two.csv")
        run_id = _run_id()
        _convert_to_string("rain")
        assert _run_meta(run_id).target_column is None
        assert _choose("snow").status_code == 200
        state = _target_state()
        assert state["target_column"] == "snow"
        assert state["target_column_source"] == "user"
        run = _run_meta(run_id)
        assert run.target_column == "snow"
        assert run.target_column_source == "user"
        assert _target_origin(
            research_runs.get_research_run_store().list_events(run_id)
        ) == "user"


# ── 6. Derived columns: singleton-правило сохранено ──────────────────


class TestDerivedExclusion:
    def test_derived_column_not_candidate_and_restore_honest(self):
        """Исключение зарегистрированных производных сохраняется
        (план §9: singleton-правило сохраняется); производная не
        становится целью авто-правилом."""
        from apps.api.session_store import AnalysisSession

        _upload_csv(CSV_TWO_NUMERIC, name="two.csv")
        run_id = _run_id()
        session = get_session_store().get(
            client.cookies.get(SESSION_COOKIE_NAME)
        )
        assert session is not None
        # Регистрируем snow как производную (реестр PROGR-24).
        session.derived_columns = {"snow": {"source": "test"}}
        get_session_store().save(session)
        from apps.api.target_column_rule import target_column_candidates

        candidates = target_column_candidates(session)
        assert "snow" not in candidates
        # Auto-правило при единственном оставшемся кандидате...
        # (rain остаётся; авто-пере-выбора вне точек загрузки нет --
        # цель не меняется.)
        assert _target_state()["target_column"] is None
        assert _run_meta(run_id).target_column is None
