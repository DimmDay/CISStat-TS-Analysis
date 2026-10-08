# tests/api/test_progress_progr25c.py
"""
PROGR-25-C: Наставник и reason узла учитывают происхождение выбора
(spec_progress_target_column.md §4-C; план plan_progress_target_column.md §3).

Баг тимлида (постановка 2026-10-08): датасет с единственной числовой
колонкой -- панель «Прогресс» показывает «value (авто)» (задачи A/B/F1),
а Наставник пишет «Исследование на этапе «Загрузка»: структура данных
подтверждена. Подтвердите целевой признак, чтобы пошли проверки
качества.» Второе предложение ошибочно: просьба при уже
авто-зафиксированном признаке.

Корень (репро scripts/progr25c_repro_bug.py, гипотеза H-A): событие
авто-фиксации задачи A живёт ТОЛЬКО в слое 1 (session.pipeline_trace),
а get_mentor_next_step читает слой 2 (store.list_events(run_id)) --
факта выбора в событиях запуска нет, правило _upload_structure_done
даёт текст-просьбу.

Контракты задачи:
  - зеркало сеемого события в слой 2 (record_run_event -- тот же
    двухслойный механизм, что у хука trace_hook.py:789 и отчётов
    фактов progress.py:461-465); run.target_column заполняется
    (research_runs.py:869-871) -- restore авто-сессий честен;
  - phase_text «Загрузки» при source=auto -- «Исследуемый признак
    выбран автоматически: value» (без просьбы выбрать);
  - status_reason (validation, sufficiency) -- «Целевой признак:
    value (авто)» при source=auto (через /trace, слой 1);
  - ручной выбор после авто -- last-wins, прежний текст без пометки;
  - demo (встроенный sales_demo.csv, две числовые) -- честная
    просьба, фиксации/события нет (guard R2/O4).
"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from apps.api import research_runs
from apps.api.main import app
from apps.api.session_store import reset_session_store_for_testing


@pytest.fixture(autouse=True)
def _reset_stores(monkeypatch):
    """Изоляция: Memory-бэкенды ОБОИХ хранилищ (паттерн
    test_progress_progr16: Наставник читает слой 2 -- run-store)."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CISSTAT_RUNS_BACKEND", "memory")
    reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()
    yield
    reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()


client = TestClient(app)

CSV_ONE_NUMERIC = (
    "date,value\n"
    "2023-01-01,10.5\n"
    "2023-01-02,20.1\n"
    "2023-01-03,30.2\n"
)


def _upload_one_numeric() -> None:
    file = io.BytesIO(CSV_ONE_NUMERIC.encode("utf-8"))
    resp = client.post(
        "/v1/internal/upload",
        files={"file": ("single.csv", file, "text/csv")},
    )
    assert resp.status_code == 200, resp.text


def _confirm_structure_like_ui() -> None:
    """UI-автопревью Загрузки (UploadAutoPreviewPipeline): уверенная дата
    фиксируется сама -- POST /date-column сеет structure_confirmed в
    слой 2, узел upload/structure становится done (сценарий тимлида)."""
    resp = client.post("/v1/session/date-column", json={"column": "date"})
    assert resp.status_code == 200, resp.text


def _run_id() -> str:
    trace = client.get("/v1/progress/trace").json()
    run_id = trace.get("run_id") or ""
    assert run_id, "run_id не зафиксирован в трассе слоя 1"
    return run_id


def _sufficiency_reason() -> str | None:
    data = client.get("/v1/progress/trace").json()
    nodes = [
        n for n in data.get("nodes", [])
        if n.get("stage") == "validation" and n.get("node_id") == "sufficiency"
    ]
    assert nodes, "узел validation/sufficiency отсутствует в /trace"
    return nodes[0].get("status_reason")


# ── Главный оракул: баг-сценарий тимлида end-to-end ──────────────────


class TestMentorSeesAutoFixation:
    def test_bug_scenario_mentor_does_not_request_target(self):
        """RED (баг тимлида дословно): upload одной числовой +
        автоподтверждение структуры UI -- Наставник НЕ просит
        выбрать/подтвердить признак: текст называет колонку и
        авто-факт. До закрытия гэпа Наставник читал слой 2 без события
        фиксации и давал «Подтвердите целевой признак...»."""
        _upload_one_numeric()
        _confirm_structure_like_ui()
        resp = client.get(f"/v1/progress/runs/{_run_id()}/mentor/next-step")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["last_active_stage"] == "upload"
        text = data["phase_text"]
        assert "выбран автоматически" in text, text
        assert "value" in text, text
        assert "подтвердите" not in text.lower(), text
        # сводка того же ответа согласована (самопротиворечие одного
        # JSON исключено -- канон PROGR-15-B/19)
        assert data["summary"]["done_count"] >= 2

    def test_seeded_event_reaches_layer2(self):
        """RED (зеркало): target_column_changed(source=auto) --
        в store.list_events слоя 2 (тот же двухслойный механизм, что у
        хука trace_hook.py:789 и отчётов фактов progress.py:461-465).
        Хронология слоя 2 -- канон R3: фиксация раньше upload_completed."""
        _upload_one_numeric()
        store = research_runs.get_research_run_store()
        events = [e.to_dict() for e in store.list_events(_run_id())]
        fixed = [e for e in events if e["event_type"] == "target_column_changed"]
        assert len(fixed) == 1, [e["event_type"] for e in events]
        assert fixed[0]["payload"] == {"target_column": "value", "source": "auto"}
        assert fixed[0]["stage"] == "validation"
        assert fixed[0]["node_id"] is None
        types = [e["event_type"] for e in events]
        assert types.index("target_column_changed") < types.index(
            "upload_completed"
        )

    def test_run_target_column_set_for_restore(self):
        """RED (restore-хилинг): record_run_event заполняет
        run.target_column из payload (research_runs.py:869-871) --
        restore авто-сессий честен БЕЗ повторной фиксации (контракт A:
        restore своим путём, сеющих вызовов нет)."""
        _upload_one_numeric()
        store = research_runs.get_research_run_store()
        run = store.get_run(_run_id())
        assert run is not None
        assert run.target_column == "value"

    def test_manual_repick_after_auto_last_wins(self):
        """Last-wins: ручной выбор после авто -- прежний текст BOTH без
        пометки авто (контракт §4-C «при user -- прежний текст»)."""
        _upload_one_numeric()
        _confirm_structure_like_ui()
        resp = client.post("/v1/session/target-column", json={"column": "value"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["target_column_source"] == "user"
        resp = client.get(f"/v1/progress/runs/{_run_id()}/mentor/next-step")
        assert resp.status_code == 200, resp.text
        text = resp.json()["phase_text"]
        assert "структура данных подтверждена, целевой признак выбран" in text
        assert "автоматически" not in text
        assert "подтвердите" not in text.lower()

    def test_two_numerics_mentor_still_requests_target(self):
        """Негативная ветка (§4-D негатив): две числовые -- фиксации
        нет; после автоподтверждения структуры Наставник честно просит
        выбрать признак (прежний текст-просьба)."""
        file = io.BytesIO(
            b"date,value,price\n2023-01-01,10.5,100\n2023-01-02,20.1,200\n"
        )
        resp = client.post(
            "/v1/internal/upload",
            files={"file": ("two.csv", file, "text/csv")},
        )
        assert resp.status_code == 200, resp.text
        _confirm_structure_like_ui()
        resp = client.get(f"/v1/progress/runs/{_run_id()}/mentor/next-step")
        assert resp.status_code == 200, resp.text
        text = resp.json()["phase_text"]
        assert "Подтвердите целевой признак" in text
        assert "автоматически" not in text


# ── reason узла (validation, sufficiency) через /trace ───────────────


class TestSufficiencyReasonOriginApi:
    def test_trace_nodes_show_auto_mark(self):
        """RED: reason носителя в /trace (слой 1): «Целевой признак:
        value (авто)» при source=auto (панель «Прогресс» -- производные
        узловых карточек)."""
        _upload_one_numeric()
        assert _sufficiency_reason() == "Целевой признак: value (авто)"

    def test_manual_choice_reason_without_mark(self):
        """Ручной выбор -- прежний текст без пометки (регресс PROGR-21)."""
        _upload_one_numeric()
        resp = client.post("/v1/session/target-column", json={"column": "value"})
        assert resp.status_code == 200, resp.text
        assert _sufficiency_reason() == "Целевой признак: value"


# ── Guard: demo-путь и legacy-совместимость ──────────────────────────


class TestDemoPathUnchanged:
    def test_builtin_demo_ambiguous_honest_request(self):
        """Guard (R2/O4): встроенный sales_demo.csv -- две числовые
        (sales, profit): фиксации/события нет НИ В ОДНОМ слое; Наставник
        честно просит подтвердить (без «автоматически»)."""
        resp = client.post("/v1/session/demo")
        assert resp.status_code == 200, resp.text
        assert client.get("/v1/session/current").json()["target_column"] is None
        store = research_runs.get_research_run_store()
        events = [e.to_dict() for e in store.list_events(_run_id())]
        assert not [e for e in events if e["event_type"] == "target_column_changed"]
        resp = client.get(f"/v1/progress/runs/{_run_id()}/mentor/next-step")
        assert resp.status_code == 200, resp.text
        text = resp.json()["phase_text"]
        assert "автоматически" not in text
        assert "подтвердите" in text.lower()
