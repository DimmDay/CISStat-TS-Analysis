# tests/api/test_run_report.py
"""Тесты Task PROGR-7 (plan_progress.md): отчёт для пользователя
(spec_progress.md §5.4) -- GET /v1/progress/runs/{run_id}/report?format=md|html.

Контракты §5.4:

  1. Линейный отчёт из trace_events долговременного слоя (слой 2, §5):
     по каждому пройденному узлу -- что нашли, что исправили, чем
     кончилось (факты из payload событий -- тот же уровень детализации,
     что уже возвращают эндпоинты, §4.1).
  2. Терминология НЕ изобретается заново: тексты «Метрики и алгоритм»
     остановок переиспользуются ВЕРБАТИМ из единого промотированного
     реестра знаний (apps/api/knowledge -- артефакт EDU-API-1, паритет
     байт-в-байт с TS-источником застрахован jest-тестом); метки стадий --
     stage_labels_ru того же реестра.
  3. Прогнозирование: отчёт ССЫЛАЕТСЯ на
     GET /v1/session/modeling/forecast/{id}/export.json и не дублирует
     сериализацию (§5.4 дословно; прецедент -- прогноз уже самодостаточен
     в export.json, spec_forecasting2.md §5.5).
  4. Форматы md|html (plan_progress.md): md -- канонический линейный
     текст, html -- самодостаточный документ; все динамические значения
     экранируются (payload несёт пользовательские данные -- имя файла).
  5. Ридер трассы сам не трассируется (паттерн PROGR-4/PROGR-5);
     долговременный слой недоступен -- честный 503 (паттерн PROGR-5:
     отчёт по неполной истории выдавал бы неполные факты за полные);
     N-2 -- stage-level события не создают узловых блоков.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from html import escape as html_escape
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.knowledge.registry import load_registry
from apps.api.trace_events import make_trace_event


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Изоляция КАЖДОГО теста: свои каталоги данных, чистые синглтоны."""
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CISSTAT_RUNS_BACKEND", raising=False)
    from apps.api import research_runs

    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    yield
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()


@pytest.fixture()
def client():
    from apps.api.main import app

    with TestClient(app) as test_client:
        yield test_client


def _ts(minute: int) -> str:
    """Детерминированный UTC-timestamp: 2026-09-26 12:{minute:02d} UTC."""
    return (
        datetime(2026, 9, 26, 12, minute, 0, tzinfo=timezone.utc).isoformat()
    )


def _seed_run(run_id: str = "RUN-REP00001", **meta):
    from apps.api import research_runs

    base = dict(
        session_id="seed-session",
        dataset_fingerprint="f" * 64,
        dataset_name="prices.csv",
        target_column=None,
        created_at=_ts(0),
        last_active_at=_ts(30),
        status="active",
    )
    base.update(meta)
    run = research_runs.ResearchRun(run_id=run_id, **base)
    research_runs.get_research_run_store().upsert_run(run)
    return run


def _append(run_id: str, event):
    from apps.api import research_runs

    research_runs.get_research_run_store().append_event(run_id, event)
    return event


def _ev(event_type: str, stage: str, node_id, run_id: str, ts: str, **payload):
    """make_trace_event + детерминированный ts через replace (фабрика
    ставит _now_iso(); коллизия payload-ключей с параметрами -- тем же
    паттерном replace(), что documented в PROGR-3/trace_hook)."""
    event = make_trace_event(
        event_type, stage=stage, node_id=node_id, run_id=run_id, **payload
    )
    return replace(event, ts=ts)


def _as_dict(event) -> dict:
    return event.to_dict()


# ── Контур 1: публичная метка стадии в реестре знаний ────────────────


class TestRegistryStageLabel:
    def test_stage_labels_canonical(self):
        """stage_label -- RU-метки из stage_labels_ru артефакта промоушена
        (единый источник терминологии с фронтовым knowledge.ts)."""
        registry = load_registry()
        assert registry.stage_label("upload") == "Загрузка"
        assert registry.stage_label("validation") == "Валидация"
        assert registry.stage_label("preprocessing") == "Предобработка"
        assert registry.stage_label("eda") == "Разведочный EDA"
        assert registry.stage_label("modeling") == "Моделирование"
        assert registry.stage_label("forecasting") == "Прогнозирование"

    def test_stage_label_unknown_is_honest_id(self):
        registry = load_registry()
        assert registry.stage_label("no_such_stage") == "no_such_stage"


# ── Контур 2: терминология отчёта из реестра знаний (§5.4) ───────────


class TestNodeTerminology:
    def test_label_from_metrics_header(self):
        """Метка узла -- заголовок текста «Метрики и алгоритм» без
        префикса: терминология отчёта = терминология остановки."""
        from app.core import run_report

        assert run_report.node_label("validation", "data_types") == "Типы данных"
        assert run_report.node_label("preprocessing", "missing") == "Пропуски"
        assert (
            run_report.node_label("eda", "correlation")
            == "Корреляция (ACF/PACF)"
        )

    def test_label_from_stage_overview_modeling(self):
        from app.core import run_report

        assert run_report.node_label("modeling", "backtest") == "Бэктест"
        assert (
            run_report.node_label("modeling", "baseline_estimation")
            == "Baseline"
        )

    def test_label_fallback_upload_forecasting(self):
        """Узлы без статей справки (Загрузка; 4 типа событий
        Прогнозирования) -- локальные метки. PROGR-13-A5: метки
        Загрузки -- из ОБЩЕГО реестра остановок (upload_stops.json §12 п.2
        через UPLOAD_STOP_DEFS, единый источник с модулем TsAnalysisUpload
        и зеркалом progress.ts; метка остановки -- «Структура»);
        PROGR-13-B: legacy "structure_confirmed" нормализуется в
        resolve_node_id, поэтому отчёт старых запусков получает ту же
        метку."""
        from app.core import run_report

        assert run_report.node_label("upload", "structure") == "Структура"
        assert run_report.node_label("upload", "overview") == "Превью датасета"
        assert run_report.node_label("upload", "quality") == "Качество"
        # legacy id корпуса слоя 2 нормализуется ДО метки (в
        # resolve_node_id модели отчёта): прямая метка по legacy id --
        # честный сырой фоллбек, не выдуманная метка
        assert (
            run_report.node_label("upload", "structure_confirmed")
            == "structure_confirmed"
        )
        assert (
            run_report.node_label("forecasting", "forecast_generated")
            == "Прогноз построен"
        )
        assert (
            run_report.node_label("forecasting", "forecast_compared")
            == "Сравнение прогнозов"
        )
        assert (
            run_report.node_label(
                "forecasting", "forecast_sensitivity_computed"
            )
            == "Анализ чувствительности"
        )
        assert (
            run_report.node_label("forecasting", "forecast_exported")
            == "Экспорт прогноза"
        )

    def test_label_unknown_node_is_honest_id(self):
        from app.core import run_report

        assert run_report.node_label("validation", "nonexistent") == "nonexistent"

    def test_methodology_metrics_verbatim(self):
        """Текст «Метрики и алгоритм» входит в отчёт ВЕРБАТИМ из
        реестра знаний (терминология не изобретается заново, §5.4)."""
        from app.core import run_report

        article = load_registry().find_article(
            "validation", "data_types", "metrics"
        )
        assert article is not None
        assert run_report.node_methodology("validation", "data_types") == (
            article.body_md
        )

    def test_methodology_modeling_stage_overview(self):
        from app.core import run_report

        article = load_registry().find_article(
            "modeling", "backtest", "stage_overview"
        )
        assert article is not None
        assert run_report.node_methodology("modeling", "backtest") == (
            article.body_md
        )

    def test_methodology_honest_missing(self):
        """У узла без статьи (upload) и на промахе -- None (no fabricated
        results, паттерн реестра знаний)."""
        from app.core import run_report

        assert run_report.node_methodology("upload", "structure") is None
        assert run_report.node_methodology("validation", "nonexistent") is None

    def test_stage_methodology_forecasting_module_overview(self):
        """Прогнозирование -- модульный текст этапа (stage_overview
        stage-уровня), рендерится один раз в шапке секции."""
        from app.core import run_report

        overview = run_report.stage_methodology("forecasting")
        assert overview is not None
        assert overview == load_registry().find_article(
            "forecasting", None, "stage_overview"
        ).body_md

    def test_stage_methodology_other_stages_none(self):
        from app.core import run_report

        assert run_report.stage_methodology("validation") is None
        assert run_report.stage_methodology("upload") is None


# ── Контур 3: строки фактов из payload (что нашли/исправили/чем кончилось)


class TestFactLines:
    def _line(self, event) -> str:
        from app.core.run_report import fact_line

        text, _links = fact_line(_as_dict(event))
        return text

    def _links(self, event):
        from app.core.run_report import fact_line

        return fact_line(_as_dict(event))[1]

    def test_upload_completed_full_payload(self):
        event = _ev(
            "upload_completed", "upload", "structure_confirmed", "RUN-X", _ts(1),
            name="prices.csv", rows=120, columns=5, size_label="12.3 КБ",
        )
        line = self._line(event)
        assert "Загружен датасет" in line
        assert "«prices.csv»" in line
        assert "строк: 120" in line
        assert "колонок: 5" in line
        assert "размер: 12.3 КБ" in line

    def test_upload_completed_empty_payload_demo(self):
        """Демо-загрузка пишется хуком без payload_keys -- факт загрузки
        честен и без чисел (не выдумываем отсутствующие данные)."""
        event = _ev(
            "upload_completed", "upload", "structure_confirmed", "RUN-X", _ts(1),
        )
        assert "Загружен датасет" in self._line(event)

    def test_correction_applied_with_strategy_and_counters(self):
        event = _ev(
            "correction_applied", "validation", "data_types", "RUN-X", _ts(2),
            applied=True, strategy="drop_rows", total_missing=10,
            total_changed=8, rows_removed=2,
        )
        line = self._line(event)
        assert "Применено исправление" in line
        assert "стратегия «drop_rows»" in line
        assert "изменено значений: 8" in line
        assert "удалено строк: 2" in line
        assert "пропусков: 10" in line

    def test_correction_previewed_is_not_applied(self):
        event = _ev(
            "correction_previewed", "preprocessing", "missing", "RUN-X", _ts(2),
            applied=False, strategy="median_mode", total_missing=10,
            total_changed=8,
        )
        line = self._line(event)
        assert "Предпросмотр исправления" in line
        assert "не применены" in line

    def test_correction_with_method_and_policy(self):
        event = _ev(
            "correction_applied", "validation", "data_types", "RUN-X", _ts(2),
            applied=True, method="to_numeric", invalid_policy="coerce",
            total_invalid=3, total_changed=3,
        )
        line = self._line(event)
        assert "метод «to_numeric»" in line
        assert "некорректных значений: 3" in line
        assert "coerce" in line

    def test_correction_target_column_reset(self):
        event = _ev(
            "correction_applied", "validation", "data_types", "RUN-X", _ts(2),
            applied=True, target_column_reset=True, total_changed=1,
        )
        assert "исследуемый признак сброшен" in self._line(event)

    def test_mode_changed(self):
        event = _ev(
            "mode_changed", "validation", None, "RUN-X", _ts(3),
            modes={"data_types": "enabled", "formats": "disabled"},
        )
        line = self._line(event)
        assert "Изменены режимы проверок" in line
        assert "data_types → enabled" in line
        assert "formats → disabled" in line

    def test_target_column_changed(self):
        event = _ev(
            "target_column_changed", "validation", None, "RUN-X", _ts(3),
            target_column="Price",
        )
        line = self._line(event)
        assert "исследуемый признак" in line.lower()
        assert "Price" in line

    def test_profile_viewed(self):
        event = _ev(
            "profile_viewed", "eda", "correlation", "RUN-X", _ts(4),
        )
        line = self._line(event)
        assert "Профиль остановки" in line

    def test_passport_captured(self):
        # payload-ключ "stage" коллизирует с параметром фабрики -- паттерн
        # PROGR-3: payload через replace().
        base = make_trace_event(
            "passport_captured", stage="eda", node_id=None, run_id="RUN-X"
        )
        event = replace(
            base,
            payload={
                "stage": "preprocessing",
                "snapshot_id": "SNAP-1234",
                "fingerprint": "ab" * 32,
            },
        )
        line = self._line(event)
        assert "Паспорт данных" in line
        assert "SNAP-1234" in line

    def test_backtest_run(self):
        event = _ev(
            "backtest_run", "modeling", "backtest", "RUN-X", _ts(5),
            model_id="arima", model_name="ARIMA", family_id="classical",
            n_train=80, n_test=40,
        )
        line = self._line(event)
        assert "Бэктест модели «ARIMA»" in line
        assert "train 80" in line
        assert "test 40" in line

    def test_tuning_trial_completed(self):
        event = _ev(
            "tuning_trial_completed", "modeling", "tuning", "RUN-X", _ts(5),
            n_trials=12, best_trial=3, grid_size=16,
        )
        line = self._line(event)
        assert "Тюнинг завершён" in line
        assert "испытаний: 12" in line
        assert "лучший trial #3" in line

    def test_model_selected(self):
        event = _ev(
            "model_selected", "modeling", "selection", "RUN-X", _ts(6),
            selected_model_id="arima", model_id="arima", model_name="ARIMA",
        )
        line = self._line(event)
        assert "Выбрана модель" in line
        assert "«ARIMA»" in line

    def test_model_card_generated(self):
        event = _ev(
            "model_card_generated", "modeling", "model_card", "RUN-X", _ts(6),
            model_card_id="MC-1", card_id="card-99", model_id="arima",
        )
        line = self._line(event)
        assert "Model Card" in line
        assert "card-99" in line

    def test_forecast_generated_with_export_link(self):
        event = _ev(
            "forecast_generated", "forecasting", None, "RUN-X", _ts(7),
            model_card_id="MC-1", forecast_id="F-abc123", model_id="arima",
            horizon=12, alpha=0.05, ci_method="conformal",
        )
        line, links = self._line(event), self._links(event)
        assert "Построен прогноз" in line
        assert "горизонт 12" in line
        assert any(
            href == "/v1/session/modeling/forecast/F-abc123/export.json"
            and label == "Полные данные прогноза (export.json)"
            for href, label in links
        )

    def test_forecast_compared(self):
        event = _ev(
            "forecast_compared", "forecasting", None, "RUN-X", _ts(7),
            forecast_ids=["F-1", "F-2"], model_card_ids=["MC-1", "MC-2"],
        )
        line = self._line(event)
        assert "Сравнение прогнозов" in line
        assert "F-1" in line and "F-2" in line

    def test_forecast_sensitivity(self):
        event = _ev(
            "forecast_sensitivity_computed", "forecasting", None, "RUN-X",
            _ts(8), forecast_id="F-abc123", varied_axes=["alpha", "horizon"],
            n_combos=9,
        )
        line = self._line(event)
        assert "Анализ чувствительности" in line
        assert "комбинаций: 9" in line
        assert "alpha" in line and "horizon" in line

    def test_forecast_exported_with_link(self):
        event = _ev(
            "forecast_exported", "forecasting", None, "RUN-X", _ts(8),
            forecast_id="F-abc123", format="csv",
        )
        line, links = self._line(event), self._links(event)
        assert "Экспорт прогноза" in line
        assert "csv" in line
        assert any(
            href == "/v1/session/modeling/forecast/F-abc123/export.json"
            for href, _ in links
        )

    def test_run_level_pause_resume_checkpoint(self):
        paused = _ev("run_paused", "validation", None, "RUN-X", _ts(9))
        assert "паузу" in self._line(paused)

        resumed = _ev("run_resumed", "validation", None, "RUN-X", _ts(10))
        assert "возобновлено" in self._line(resumed)

        restored = _ev(
            "run_resumed", "validation", None, "RUN-X", _ts(10), restored=True,
        )
        assert "восстановлен" in self._line(restored)

        checkpoint = _ev(
            "checkpoint_saved", "preprocessing", None, "RUN-X", _ts(10),
            checkpoint_id="CP-1", event_id="e-42", label="перед сглаживанием",
        )
        line = self._line(checkpoint)
        assert "Контрольная точка" in line
        assert "«перед сглаживанием»" in line

    def test_unknown_event_type_is_audit_line(self):
        """R3 (PROGR-1-CERT): событие с неизвестным типом хранится --
        отчёт не падает и не выдумывает фактов, честная строка аудита."""
        from app.core.run_report import fact_line

        text, links = fact_line(
            {
                "event_id": "e-1",
                "run_id": "RUN-X",
                "ts": _ts(1),
                "stage": "eda",
                "node_id": None,
                "event_type": "future_event_kind",
                "payload": {"x": 1},
                "actor": "user",
            }
        )
        assert "future_event_kind" in text
        assert links == ()


# ── Контур 4: сборка модели отчёта (линейность, группировка) ─────────


class TestBuildReportModel:
    def _model(self, events, **meta):
        from app.core.run_report import build_report_model

        run = _seed_run("RUN-MODEL01", **meta)
        return build_report_model(
            run.to_dict(), [_as_dict(event) for event in events]
        )

    def test_stages_in_canonical_pipeline_order(self):
        """Секции -- в каноническом порядке STAGES независимо от порядка
        событий (линейный отчёт читается по пайплайну)."""
        events = [
            _ev("forecast_generated", "forecasting", None, "RUN-MODEL01", _ts(9), forecast_id="F-1"),
            _ev("backtest_run", "modeling", "backtest", "RUN-MODEL01", _ts(5), model_name="ARIMA"),
            _ev("profile_viewed", "eda", "correlation", "RUN-MODEL01", _ts(4)),
            _ev("upload_completed", "upload", "structure_confirmed", "RUN-MODEL01", _ts(1), name="a.csv"),
        ]
        model = self._model(events)
        assert [s.stage for s in model.stages] == [
            "upload", "eda", "modeling", "forecasting",
        ]

    def test_nodes_in_first_touch_order(self):
        events = [
            _ev("profile_viewed", "eda", "correlation", "RUN-MODEL01", _ts(4)),
            _ev("profile_viewed", "eda", "seasonality", "RUN-MODEL01", _ts(5)),
            _ev("profile_viewed", "eda", "distribution", "RUN-MODEL01", _ts(6)),
            _ev("profile_viewed", "eda", "correlation", "RUN-MODEL01", _ts(7)),
        ]
        model = self._model(events)
        stage = model.stages[0]
        assert [n.node_id for n in stage.nodes] == [
            "correlation", "seasonality", "distribution",
        ]
        # Повторное касание -- в факты того же узла, новые узлы не плодятся
        assert len(stage.nodes[0].facts) == 2

    def test_stage_level_events_do_not_create_nodes(self):
        """N-2 (находка PROGR-4): stage-level события (node_id=None) --
        в блок «Решения уровня этапа», фантомных узлов нет."""
        events = [
            _ev("mode_changed", "validation", None, "RUN-MODEL01", _ts(2), modes={"data_types": "enabled"}),
            _ev("target_column_changed", "validation", None, "RUN-MODEL01", _ts(3), target_column="Price"),
            _ev("correction_applied", "validation", "data_types", "RUN-MODEL01", _ts(4), applied=True, total_changed=1),
        ]
        model = self._model(events)
        stage = model.stages[0]
        assert [n.node_id for n in stage.nodes] == ["data_types"]
        assert len(stage.stage_level_facts) == 2

    def test_forecasting_node_derived_from_event_type(self):
        """Контракт PROGR-1: forecasting-события слоя 2 хранят
        node_id=None -- узел выводится из типа события (4 типа == узлы
        графа §2, зеркало derive_node_statuses)."""
        events = [
            _ev("forecast_generated", "forecasting", None, "RUN-MODEL01", _ts(7), forecast_id="F-1"),
            _ev("forecast_exported", "forecasting", None, "RUN-MODEL01", _ts(8), forecast_id="F-1", format="csv"),
        ]
        model = self._model(events)
        stage = model.stages[0]
        assert [n.node_id for n in stage.nodes] == [
            "forecast_generated", "forecast_exported",
        ]

    def test_chronological_sort_unparseable_ts_last(self):
        """Хронология: нечитаемый ts -- в конец (зеркало
        sortEventsChronologically фронтенда); порядок взаимный сохранён."""
        from app.core.run_report import sort_events_chronologically

        raw = [
            {"event_id": "e1", "ts": "не дата"},
            {"event_id": "e2", "ts": _ts(3)},
            {"event_id": "e3", "ts": "тоже не дата"},
            {"event_id": "e4", "ts": _ts(1)},
        ]
        ordered = sort_events_chronologically(raw)
        assert [e["event_id"] for e in ordered] == ["e4", "e2", "e1", "e3"]

    def test_run_metadata_and_status_labels(self):
        from app.core.run_report import build_report_model

        for status, label in (
            ("active", "в работе"),
            ("paused", "на паузе"),
            ("completed", "завершён"),
            ("abandoned", "покинут"),
        ):
            run = _seed_run("RUN-MODEL01", status=status)
            model = build_report_model(run.to_dict(), [])
            assert model.status_label == label
            assert model.run_id == "RUN-MODEL01"
            assert model.dataset_name == "prices.csv"

    def test_target_column_honest_none(self):
        """Без признака -- честный None (без выдуманных прочерков в
        модели; прочерк -- решение рендера)."""
        model = self._model([])
        assert model.target_column is None
        assert model.events_total == 0
        assert model.stages == ()

    def test_target_column_from_run_meta(self):
        model = self._model([], target_column="Price")
        assert model.target_column == "Price"

    def test_unknown_stage_goes_to_defensive_tail_section(self):
        """Защитный контур: событие неизвестной стадии (прямой
        TraceEvent в хранилище) -- в хвостовую секцию, отчёт не падает."""
        from apps.api.trace_events import TraceEvent

        raw = TraceEvent(
            event_type="custom", payload={}, run_id="RUN-MODEL01",
            ts=_ts(2), stage="mystage", node_id=None,
        )
        model = self._model([raw])
        assert [s.stage for s in model.stages] == ["mystage"]
        assert model.stages[0].label == "mystage"

    def test_stage_methodology_and_node_methodology_attached(self):
        events = [
            _ev("profile_viewed", "eda", "correlation", "RUN-MODEL01", _ts(4)),
            _ev("forecast_generated", "forecasting", None, "RUN-MODEL01", _ts(7), forecast_id="F-1"),
        ]
        model = self._model(events)
        eda_stage = model.stages[0]
        assert eda_stage.stage_methodology is None
        assert eda_stage.nodes[0].methodology is not None
        assert eda_stage.nodes[0].methodology.startswith("Метрики и алгоритм: Корреляция")

        fc_stage = model.stages[1]
        assert fc_stage.stage_methodology is not None
        assert fc_stage.stage_methodology.startswith("Цель: построить реальный прогноз")


# ── Контур 5: рендеры md/html ─────────────────────────────────────────


def _sample_model():
    from app.core.run_report import build_report_model

    run = _seed_run(
        "RUN-RENDER01",
        dataset_name="prices <v2>.csv",
        target_column="Price",
    )
    events = [
        _ev("upload_completed", "upload", "structure_confirmed", "RUN-RENDER01", _ts(1),
            name="prices <v2>.csv", rows=120, columns=5, size_label="12.3 КБ"),
        _ev("correction_applied", "validation", "data_types", "RUN-RENDER01", _ts(2),
            applied=True, strategy="drop_rows", total_missing=10, total_changed=8,
            rows_removed=2),
        _ev("backtest_run", "modeling", "backtest", "RUN-RENDER01", _ts(5),
            model_id="arima", model_name="ARIMA", family_id="classical",
            n_train=80, n_test=40),
        _ev("forecast_generated", "forecasting", None, "RUN-RENDER01", _ts(7),
            model_card_id="MC-1", forecast_id="F-abc123", model_id="arima",
            horizon=12, alpha=0.05, ci_method="conformal"),
    ]
    return build_report_model(run.to_dict(), [_as_dict(e) for e in events])


class TestMarkdownRender:
    @pytest.fixture()
    def md(self) -> str:
        from app.core.run_report import render_markdown

        return render_markdown(_sample_model())

    def test_header_block(self, md: str):
        assert md.startswith("# Отчёт об исследовании RUN-RENDER01")
        assert "Датасет: prices <v2>.csv" in md
        assert "Исследуемый признак: Price" in md
        assert "Статус запуска: в работе" in md
        assert "Событий в трассе: 4" in md
        assert "2026-09-26 12:01:00 UTC" in md

    def test_stage_and_node_headings(self, md: str):
        assert "## Загрузка" in md
        assert "## Валидация" in md
        assert "## Моделирование" in md
        assert "## Прогнозирование" in md
        # PROGR-13-A5: метка остановки -- из общего реестра (модуль:
        # «Структура»), не старая «Структура данных»
        assert "### Структура" in md
        assert "### Типы данных" in md
        assert "### Бэктест" in md
        assert "### Прогноз построен" in md

    def test_methodology_verbatim_in_report(self, md: str):
        """Текст «Метрики и алгоритм» остановки -- в отчёте вербатим
        (§5.4: терминология не изобретается заново)."""
        registry = load_registry()
        text = registry.find_article("validation", "data_types", "metrics").body_md
        assert text in md

    def test_fact_lines_and_stage_level_block(self, md: str):
        assert "Загружен датасет" in md
        assert "Применено исправление" in md
        assert "Бэктест модели «ARIMA»" in md

    def test_forecast_export_link(self, md: str):
        assert (
            "[Полные данные прогноза (export.json)]"
            "(/v1/session/modeling/forecast/F-abc123/export.json)" in md
        )

    def test_empty_report_renders_honest_header(self):
        from app.core.run_report import build_report_model, render_markdown

        run = _seed_run("RUN-EMPTY001")
        md = render_markdown(build_report_model(run.to_dict(), []))
        assert "# Отчёт об исследовании RUN-EMPTY001" in md
        assert "Событий в трассе: 0" in md
        assert "### " not in md


class TestHtmlRender:
    @pytest.fixture()
    def html(self) -> str:
        from app.core.run_report import render_html

        return render_html(_sample_model())

    def test_document_skeleton(self, html: str):
        assert html.startswith("<!DOCTYPE html>")
        assert '<html lang="ru">' in html
        assert "<title>Отчёт об исследовании RUN-RENDER01</title>" in html

    def test_payload_values_are_escaped(self, html: str):
        """Имя файла -- пользовательские данные: экранирование обязательно
        (отчёт открывается браузером)."""
        assert "prices &lt;v2&gt;.csv" in html
        assert "<v2>" not in html
        assert "<script>" not in html

    def test_structure_and_methodology(self, html: str):
        assert "<h2>Загрузка</h2>" in html
        assert "<h3>Типы данных</h3>" in html
        registry = load_registry()
        text = registry.find_article("validation", "data_types", "metrics").body_md
        # html-экранирование текстов реестра не меняет содержимого
        assert html_escape(text) in html
        assert "methodology" in html

    def test_export_link_escaped_and_present(self, html: str):
        assert '<a href="/v1/session/modeling/forecast/F-abc123/export.json">' in html
        assert "Полные данные прогноза (export.json)" in html


# ── Контур 6: REST GET /v1/progress/runs/{run_id}/report ──────────────


class TestReportEndpoint:
    def _seed_full_run(self, run_id: str = "RUN-REST0001"):
        _seed_run(run_id)
        _append(run_id, _ev("upload_completed", "upload", "structure_confirmed",
                            run_id, _ts(1), name="prices.csv", rows=120,
                            columns=5, size_label="12.3 КБ"))
        _append(run_id, _ev("correction_applied", "validation", "data_types",
                            run_id, _ts(2), applied=True, strategy="drop_rows",
                            total_missing=10, total_changed=8, rows_removed=2))
        _append(run_id, _ev("forecast_generated", "forecasting", None,
                            run_id, _ts(7), model_card_id="MC-1",
                            forecast_id="F-abc123", model_id="arima",
                            horizon=12, alpha=0.05, ci_method="conformal"))
        return run_id

    def test_report_md_default(self, client: TestClient):
        run_id = self._seed_full_run()
        resp = client.get(f"/v1/progress/runs/{run_id}/report")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        assert "Отчёт об исследовании RUN-REST0001" in resp.text
        assert "Применено исправление" in resp.text

    def test_report_html_explicit(self, client: TestClient):
        run_id = self._seed_full_run()
        resp = client.get(
            f"/v1/progress/runs/{run_id}/report", params={"format": "html"}
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        assert resp.text.startswith("<!DOCTYPE html>")

    def test_report_unknown_run_404(self, client: TestClient):
        resp = client.get("/v1/progress/runs/RUN-NOPE/report")
        assert resp.status_code == 404

    def test_report_bad_format_422(self, client: TestClient):
        """Формат фиксируется контрактом plan_progress.md (md|html):
        pdf не поддерживается -- честный 422, а не тихий md."""
        run_id = self._seed_full_run()
        resp = client.get(
            f"/v1/progress/runs/{run_id}/report", params={"format": "pdf"}
        )
        assert resp.status_code == 422

    def test_report_durable_layer_outage_503(self, client: TestClient, monkeypatch):
        """Паттерн PROGR-5: сбой слоя 2 -- честный 503 (отчёт по
        неполной истории выдавал бы неполные факты за полные)."""
        from apps.api import research_runs

        run_id = self._seed_full_run()
        research_runs.reset_research_run_store_for_testing()
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
        research_runs.reset_research_run_store_for_testing()

        resp = client.get(f"/v1/progress/runs/{run_id}/report")
        assert resp.status_code == 503

    def test_report_contains_forecast_export_link(self, client: TestClient):
        run_id = self._seed_full_run()
        resp = client.get(f"/v1/progress/runs/{run_id}/report")
        assert "/v1/session/modeling/forecast/F-abc123/export.json" in resp.text

    def test_report_reflects_layer2_not_layer1(self, client: TestClient):
        """Отчёт строится из слоя 2 (кросс-сессионный §5): события
        ДРУГОЙ сессии, не тронувшей отчётный запуск, в отчёт не попадают."""
        run_id = self._seed_full_run()
        # Чужая браузерная сессия грузит свой датасет -- слой 2 другого запуска
        other = client.post("/v1/session/demo")
        assert other.status_code == 200
        resp = client.get(f"/v1/progress/runs/{run_id}/report")
        assert "demo_sales.csv" not in resp.text

    def test_report_endpoint_not_traced_by_hook(self):
        """Ридер трассы сам не трассируется (паттерн PROGR-4/PROGR-5)."""
        from apps.api.trace_hook import resolve_trace_route

        assert (
            resolve_trace_route("GET", "/v1/progress/runs/RUN-1/report") is None
        )

    def test_report_no_panel_control_semantics(self, client: TestClient):
        """N-4 (PROGR-4): документ отчёта не несёт семантики управления
        панелью -- рендер у клиента."""
        run_id = self._seed_full_run()
        resp = client.get(f"/v1/progress/runs/{run_id}/report")
        for forbidden in ("close_panel", "open_panel", "navigate", "redirect"):
            assert forbidden not in resp.text

    def test_report_of_empty_run_is_honest(self, client: TestClient):
        run_id = "RUN-REST0002"
        _seed_run(run_id)
        resp = client.get(f"/v1/progress/runs/{run_id}/report")
        assert resp.status_code == 200
        assert "Событий в трассе: 0" in resp.text
