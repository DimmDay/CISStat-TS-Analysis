# tests/integration/test_progress_target_column_e2e.py
"""PROGR-25-D: сквозной тест сценария «исследуемый признак» (spec_progress_target_column.md
§4-D, план plan_progress_target_column.md §4).

Первый файл tests/integration/ (до задачи D директория была пуста).
Отличие от адресных сюит tests/api (test_progress_progr25a/c): здесь
ПРОХОЖДЕНИЕ ВСЕГО СЦЕНАРИЯ одним непрерывным потоком через штатные
эндпоинты -- как его видит аналитик, без прямых вызовов внутренних
модулей правила: загрузка файла → /current → /trace → Наставник, с
проверкой СОГЛАСОВАННОСТИ всех носителей факта (шапка-носитель /trace,
контекст /current, селектор /target-column, текст Наставника).

Датасет первого сценария -- демо forecast_monitor_synthetic_n150.csv
из §1 спеки. CSV-артефакт в репозитории НЕ закоммичен: файл
восстанавливается ДЕТЕРМИНИРОВАННЫМ генератором
scripts/dataset_forecast_monitor.py (generate_series, seed 20260916,
150 строк, колонки date/value, 3 пропуска @ {45,87,122}, 4 выброса @
{25,70,105,130}) -- та же функция, что породила эталонный артефакт.

Контракты (§4-D плана):
  D1 (позитивный сквозной): upload n150 → /current (value, auto) →
     /trace (шапка-носитель value/auto + ровно одно событие
     target_column_changed{target_column, source:"auto"}, stage="validation",
     node_id=None, run_id общий с upload_completed, хронология «фиксация →
     upload_completed» -- канон R3) → Наставник: «выбран автоматически:
     value» БЕЗ просьбы выбрать; все три источника согласованы.
  D2 (негативный сквозной): файл с ДВУМЯ числовыми → честное «не выбран»
     (фиксации/события нет) → Наставник ПРОСИТ выбрать → ручной выбор →
     source="user" во всех носителях, текст Наставника -- прежний BOTH
     (без «автоматически» и без просьбы); согласованность трёх источников.
"""
from __future__ import annotations

import importlib.util
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.research_runs import reset_research_run_store_for_testing
from apps.api.session_store import reset_session_store_for_testing

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_generator():
    """Генератор scripts/dataset_forecast_monitor.py -- единственный
    источник демо-артефакта n150 (в репо CSV не закоммичен)."""
    script = REPO_ROOT / "scripts" / "dataset_forecast_monitor.py"
    spec = importlib.util.spec_from_file_location("dfm_generator_d", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def n150_csv_bytes() -> bytes:
    """Детерминированное восстановление демо-датасета n150 генератором."""
    df = _load_generator().generate_series()
    assert df.shape == (150, 2) and list(df.columns) == ["date", "value"]
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _reset_stores(monkeypatch):
    """Изоляция: Memory-бэкенды ОБОИХ хранилищ (паттерн
    test_progress_progr25c.py: Наставник читает слой 2 -- run-store;
    песочница может задавать DATABASE_URL -- снимаем)."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CISSTAT_RUNS_BACKEND", "memory")
    reset_session_store_for_testing()
    reset_research_run_store_for_testing()
    yield
    reset_session_store_for_testing()
    reset_research_run_store_for_testing()


client = TestClient(app)


def _upload(csv_bytes: bytes, filename: str) -> dict:
    resp = client.post(
        "/v1/internal/upload",
        files={"file": (filename, io.BytesIO(csv_bytes), "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _current() -> dict:
    resp = client.get("/v1/session/current")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _target_column_state() -> dict:
    resp = client.get("/v1/session/target-column")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _trace() -> dict:
    resp = client.get("/v1/progress/trace")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _mentor_phase_text(run_id: str) -> str:
    resp = client.get(f"/v1/progress/runs/{run_id}/mentor/next-step")
    assert resp.status_code == 200, resp.text
    return resp.json()["phase_text"]


def _confirm_structure() -> None:
    """Канон репро PROGR-25-C: уверенная дата фиксируется сама
    (UI-автопревью UploadAutoPreviewPipeline) -- в API-потоке это
    POST /date-column; без него структура pending и Наставник даёт
    статический шаблон, не различающий происхождение признака."""
    resp = client.post("/v1/session/date-column", json={"column": "date"})
    assert resp.status_code == 200, resp.text


# ══ D1: демо n150 → /current → /trace → Наставник согласованы ════════


class TestScenarioDemoN150EndToEnd:
    """Приёмка §7 спеки: «сразу после загрузки панель показывает
    "Признак: value (авто)"» -- в терминах носителей: /trace (шапка B),
    /current (контекст), /target-column (селектор) и Наставник."""

    def test_d1_full_scenario_consistency(self, n150_csv_bytes):
        # ── Шаг 1: загрузка демо-датасета (без захода на вкладки) ──
        upload = _upload(n150_csv_bytes, "forecast_monitor_synthetic_n150.csv")
        assert upload["name"] == "forecast_monitor_synthetic_n150.csv"
        assert upload["rows"] == 150

        # ── Шаг 2: /current -- признак зафиксирован АВТОМАТИЧЕСКИ ──
        current = _current()
        assert current["has_active_dataset"] is True
        assert current["target_column"] == "value"
        assert current["target_column_source"] == "auto"
        assert current["date_column"] is None  # регистрация даты -- отдельное действие

        # ── Шаг 3: селектор -- тот же факт, рекомендация совпадает ──
        state = _target_column_state()
        assert state["target_column"] == "value"
        assert state["target_column_source"] == "auto"
        assert state["suggested_column"] == "value"
        assert "value" in state["available_columns"]

        # ── Шаг 4: /trace -- шапка-носитель (задача B) и событие ──
        trace = _trace()
        assert trace["target_column"] == "value"
        assert trace["target_column_source"] == "auto"

        changed = [
            e for e in trace["events"]
            if e.get("event_type") == "target_column_changed"
        ]
        assert len(changed) == 1, "ровно одно событие фиксации"
        event = changed[0]
        assert event["payload"] == {"target_column": "value", "source": "auto"}
        assert event["stage"] == "validation"
        assert event["node_id"] is None
        assert event["actor"] == "system"

        upload_completed = [
            e for e in trace["events"] if e.get("event_type") == "upload_completed"
        ]
        assert upload_completed, "upload_completed отсутствует"
        # run_id общий: фиксация и upload_completed -- один запуск (§5)
        assert event["run_id"] == upload_completed[0]["run_id"]
        assert event["run_id"]
        # хронология канона R3: фиксация раньше upload_completed
        types = [e.get("event_type") for e in trace["events"]]
        assert types.index("target_column_changed") < types.index(
            "upload_completed"
        )

        # ── Шаг 5: структура подтверждена (канон репро PROGR-25-C) ──
        _confirm_structure()

        # ── Шаг 6: Наставник видит авто-фиксацию (слой 2) и НЕ просит ──
        phase_text = _mentor_phase_text(trace["run_id"])
        assert "выбран автоматически: value" in phase_text
        assert "Подтвердите целевой признак" not in phase_text

        # ── Шаг 7: согласованность трёх источников -- один факт ──
        assert (
            _current()["target_column"]
            == _trace()["target_column"]
            == _target_column_state()["target_column"]
            == "value"
        )
        assert (
            _current()["target_column_source"]
            == _trace()["target_column_source"]
            == _target_column_state()["target_column_source"]
            == "auto"
        )

    def test_d1b_trace_fields_absent_on_fresh_session(self):
        """Инверсия сценария: свежая сессия (датасета нет) -- носитель
        честно пуст (шапка B рендерит «—» только в этом состоянии)."""
        trace = _trace()
        assert trace["target_column"] is None
        assert trace["target_column_source"] is None
        assert _current()["target_column"] is None


# ══ D2: негативный сценарий -- две числовые → «не выбран» → user ═════


CSV_TWO_NUMERIC = (
    "date,value,price\n"
    "2023-01-01,10.5,100\n"
    "2023-01-02,20.1,200\n"
    "2023-01-03,30.2,300\n"
    "2023-01-04,15.0,150\n"
)


class TestScenarioTwoNumericNegative:
    """Приёмка §7 спеки: файл с несколькими числовыми -- «не выбран»,
    Наставник просит выбрать, ручной выбор без пометки «(авто)»."""

    def test_d2_ambiguity_then_manual_user(self):
        # ── Шаг 1: загрузка двухчислового файла -- тихой фиксации НЕТ ──
        _upload(CSV_TWO_NUMERIC.encode("utf-8"), "two_numeric.csv")
        current = _current()
        assert current["target_column"] is None
        assert current["target_column_source"] is None

        # /trace: ни носителя, ни события фиксации
        trace = _trace()
        assert trace["target_column"] is None
        assert trace["target_column_source"] is None
        assert [
            e for e in trace["events"]
            if e.get("event_type") == "target_column_changed"
        ] == []

        # ── Шаг 2: структура подтверждена -- Наставник ПРОСИТ выбрать ──
        _confirm_structure()
        plea_text = _mentor_phase_text(trace["run_id"])
        assert "Подтвердите целевой признак" in plea_text
        assert "выбран автоматически" not in plea_text

        # селектор при неоднозначности: рекомендация отображается,
        # но не фиксируется (первый кандидат по стабильному порядку)
        state = _target_column_state()
        assert state["target_column"] is None
        assert state["suggested_column"] == "value"

        # ── Шаг 3: ручной выбор price -- source=user, last-wins ──
        resp = client.post("/v1/session/target-column", json={"column": "price"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["target_column_source"] == "user"

        # ── Шаг 4: все носители отражают user-факт без «(авто)» ──
        assert _current()["target_column"] == "price"
        assert _current()["target_column_source"] == "user"
        assert _target_column_state()["target_column"] == "price"
        assert _target_column_state()["target_column_source"] == "user"

        trace_after = _trace()
        assert trace_after["target_column"] == "price"
        assert trace_after["target_column_source"] == "user"
        manual_events = [
            e for e in trace_after["events"]
            if e.get("event_type") == "target_column_changed"
        ]
        assert len(manual_events) == 1
        # событие ручного маршрута -- legacy-payload без source
        # (контракт A: отсутствие поля читается как user)
        assert manual_events[0]["payload"] == {"target_column": "price"}

        # ── Шаг 5: Наставник -- прежний BOTH-текст: без просьбы и
        # без «автоматически» (происхождение различает тексты) ──
        user_text = _mentor_phase_text(trace_after["run_id"])
        assert "Подтвердите целевой признак" not in user_text
        assert "выбран автоматически" not in user_text
        assert "целевой признак выбран" in user_text

        # ── Шаг 6: согласованность трёх источников на user-факте ──
        assert (
            _current()["target_column"]
            == _trace()["target_column"]
            == _target_column_state()["target_column"]
            == "price"
        )
        assert (
            _current()["target_column_source"]
            == _trace()["target_column_source"]
            == _target_column_state()["target_column_source"]
            == "user"
        )
