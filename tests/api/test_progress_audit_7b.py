# tests/api/test_progress_audit_7b.py
"""Оракулы задачи AUDIT-7B -- документ исследования (plan_progress_audit.md
§16, spec_progress_audit.md F12/P18, §4.2.6, §9 «Наставник/отчёт»).

Состав карточки §16 и классы отказов (RED на базе b43e2eb):

  R1 (P18/F12): факт выбора цели теряет происхождение -- «Установлен
     исследуемый признак: rain» без auto/user; спека §9: текст отчёта
     обязан различать «автоматически выбрано» / «выбрано аналитиком».
  R2: сброс цели (target_column_cleared, контракт v0.7-1A) не имеет
     собственного шаблона -- падает в общий fallback «Событие трассы».
  R3: семь Modeling-типов AUDIT-7A отображаются общим fallback -- нет
     human-шаблонов с параметрами/исходами (spec §9: «Новые Modeling-
     типы получают шаблоны и сохраняют параметры/исходы»).
  R4: общий fallback неизвестного типа не сохраняет ids и не сообщает
     «интерпретация неизвестна» (план §16: fallback сохраняет исходный
     тип/ids).
  R5: отчёт не несёт watermark/версии формата -- проекции панели,
     Наставника и отчёта должны быть читателями ОДНОЙ версии истории
     (spec §9; план §16: «при экспорте сохранять report format/version
     и watermark»).
  R6: историческая применимость не маркируется -- после raw restore
     факты другого контекста неотличимы от текущих (спека §9: «истори-
     чески выполнено»; AUDIT-8: «старые результаты маркируются
     историческими»).
  R7: методология реестра не помечена как справочный текст ТЕКУЩЕЙ
     версии (§4.2.6: «пояснения следует помечать как справочный текст
     текущей версии»).
  R8 (подписи admin): StageSpanStat «Время по стадии» называет
     календарный span активным временем (план §16: «календарный span
     стадии не называть активным временем»); частоты наблюдений
     Наставника не помечены как вызовы (не уникальные решения).

Контроли (GREEN на базе -- пины прежних контрактов): полнота строк
фактов без утечки посторонних payload-ключей, честный None цели,
неизвестная стадия в хвостовой секции, экранирование HTML.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Изоляция КАЖДОГО теста: свои каталоги данных, чистые синглтоны
    (тот же паттерн, что test_run_report.py)."""
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
    return (
        datetime(2026, 10, 13, 10, minute, 0, tzinfo=timezone.utc).isoformat()
    )


def _ev(event_type: str, stage: str, node_id, run_id: str, ts: str, **payload):
    from dataclasses import replace

    from apps.api.trace_events import make_trace_event

    event = make_trace_event(
        event_type, stage=stage, node_id=node_id, run_id=run_id, **payload
    )
    return replace(event, ts=ts)


def _dict(event) -> dict:
    return event.to_dict()


def _line(event: dict) -> str:
    from app.core.run_report import fact_line

    text, _links = fact_line(event)
    return text


# ── R1: происхождение выбора цели в строке факта (P18/F12) ───────────


class TestTargetOriginLine:
    def test_auto_origin_visible(self):
        """P18: source=auto -- строка обязана различать «автоматически»
        (спека §9: «автоматически выбрано» ≠ «выбрано аналитиком»)."""
        event = _ev(
            "target_column_changed", "validation", None, "RUN-7B", _ts(1),
            target_column="rain", source="auto",
        )
        line = _line(_dict(event))
        assert "авто" in line.lower()
        assert "rain" in line

    def test_user_origin_visible(self):
        event = _ev(
            "target_column_changed", "validation", None, "RUN-7B", _ts(1),
            target_column="snow", source="user",
        )
        line = _line(_dict(event))
        assert "вручную" in line.lower() or "аналитик" in line.lower()
        assert "snow" in line

    def test_legacy_absent_source_reads_as_user(self):
        """Контракт PROGR-25-A: отсутствующий source у legacy-ВЫБОРА --
        user; строка честно называет происхождение, а не умалчивает."""
        event = _ev(
            "target_column_changed", "validation", None, "RUN-7B", _ts(1),
            target_column="snow",
        )
        line = _line(_dict(event))
        assert "вручную" in line.lower() or "аналитик" in line.lower()

    def test_unknown_source_is_honest(self):
        """Мусорный source -- не «user» (спека §8.2/§3.7: повреждённое
        происхождение не выдаётся за подтверждённого человека)."""
        event = _ev(
            "target_column_changed", "validation", None, "RUN-7B", _ts(1),
            target_column="snow", source="corrupted",
        )
        line = _line(_dict(event))
        assert "неизвест" in line.lower()


# ── R2: сброс цели -- собственный честный шаблон ─────────────────────


class TestTargetClearedLine:
    def test_cleared_line_with_reason_and_before(self):
        """Контракт v0.7-1A/§3.1: payload cleared --
        {reset_reason, before_target}; строка отражает факт сброса."""
        event = _ev(
            "target_column_cleared", "validation", None, "RUN-7B", _ts(2),
            reset_reason="convert_types", before_target="rain",
        )
        line = _line(_dict(event))
        assert "сброшен" in line.lower()
        assert "rain" in line
        assert "convert_types" in line

    def test_cleared_minimal_payload_no_fabrication(self):
        """Payload не требуется (§3.1): без before_target строка не
        выдумывает прежнюю колонку."""
        event = _ev(
            "target_column_cleared", "validation", None, "RUN-7B", _ts(2),
        )
        line = _line(_dict(event))
        assert "сброшен" in line.lower()

    def test_auto_clear_user_sequence(self):
        """Спека §9: auto → сброс → ручной выбор -- отчёт различает все
        три состояния; run-мета несёт origin текущего выбора."""
        from app.core.run_report import build_report_model

        events = [
            _ev("target_column_changed", "validation", None, "RUN-7BSEQ",
                _ts(1), target_column="rain", source="auto"),
            _ev("target_column_cleared", "validation", None, "RUN-7BSEQ",
                _ts(2), reset_reason="convert_types", before_target="rain"),
            _ev("target_column_changed", "validation", None, "RUN-7BSEQ",
                _ts(3), target_column="snow", source="user"),
        ]
        run_meta = {
            "run_id": "RUN-7BSEQ",
            "dataset_name": "seq.csv",
            "target_column": "snow",
            "target_column_source": "user",
            "status": "active",
            "created_at": _ts(0),
            "last_active_at": _ts(3),
        }
        model = build_report_model(run_meta, [_dict(e) for e in events])
        texts = [f.text for stage in model.stages
                 for node in stage.nodes for f in node.facts]
        texts += [f.text for stage in model.stages
                  for f in stage.stage_level_facts]
        assert any("сброшен" in t.lower() for t in texts)
        auto_line = next(t for t in texts if "rain" in t)
        assert "авто" in auto_line.lower()
        user_line = next(t for t in texts if "snow" in t)
        assert "вручную" in user_line.lower() or "аналитик" in user_line.lower()
        assert model.target_column_source == "user"


# ── R3: семь Modeling-типов AUDIT-7A -- human-шаблоны ────────────────


class TestModelingTemplates:
    def test_candidates_generated(self):
        event = _ev(
            "candidates_generated", "modeling", "candidate_generation",
            "RUN-7B", _ts(4), spec_version="1.0", runnable_candidates=7,
            catalog_only_candidates=2, blocked_candidates=1,
        )
        line = _line(_dict(event))
        assert "Событие трассы" not in line
        assert "кандидат" in line.lower()
        assert "7" in line

    def test_selection_evaluated(self):
        event = _ev(
            "selection_evaluated", "modeling", "selection", "RUN-7B",
            _ts(4), selection_analysis_id="sa-1", cohort_id="co-1",
            model_id="arima", status="not_eligible",
        )
        line = _line(_dict(event))
        assert "Событие трассы" not in line
        assert "arima" in line
        assert "not_eligible" in line

    def test_models_compared(self):
        event = _ev(
            "models_compared", "modeling", "comparison", "RUN-7B",
            _ts(4), comparison_id="cmp-1", cohort_id="co-1",
            objective="forecast_accuracy",
        )
        line = _line(_dict(event))
        assert "Событие трассы" not in line
        assert "Сравнение" in line
        assert "forecast_accuracy" in line

    def test_diagnostics_direct(self):
        event = _ev(
            "diagnostics_run", "modeling", "diagnostics", "RUN-7B",
            _ts(4), model_id="ets", params_source="defaults",
            backtest_run_id="bt-9",
        )
        line = _line(_dict(event))
        assert "Событие трассы" not in line
        assert "Диагностика" in line
        assert "ets" in line
        assert "defaults" in line

    def test_diagnostics_ensure_reuse_is_visible(self):
        """Переиспользование диагностики -- честный факт (payload
        /diagnostics/ensure: calculated_model_ids/reused_model_ids)."""
        event = _ev(
            "diagnostics_run", "modeling", "diagnostics", "RUN-7B",
            _ts(4), calculated_model_ids=["a", "b"], reused_model_ids=["c"],
        )
        line = _line(_dict(event))
        assert "Событие трассы" not in line
        assert "2" in line
        assert "1" in line

    def test_tuning_skipped_with_reason(self):
        """AUDIT-7A: reason -- эхо ответа в payload; шаблон обязан
        показывать обоснование (§15: «skipped имеет обоснование»)."""
        event = _ev(
            "tuning_skipped", "modeling", "tuning", "RUN-7B", _ts(4),
            model_id="arima", reason="ряд короткий, оставлены defaults",
        )
        line = _line(_dict(event))
        assert "Событие трассы" not in line
        assert "пропущен" in line.lower()
        assert "ряд короткий" in line

    def test_tuning_job_started(self):
        event = _ev(
            "tuning_job_started", "modeling", "tuning", "RUN-7B", _ts(4),
            operation="tune", model_id="arima", job_id="job-77",
            status="running", total_steps=40,
        )
        line = _line(_dict(event))
        assert "Событие трассы" not in line
        assert "job-77" in line

    def test_tuning_job_cancelled(self):
        event = _ev(
            "tuning_job_cancelled", "modeling", "tuning", "RUN-7B", _ts(4),
            model_id="arima", job_id="job-77", status="cancelled",
            reason="по запросу аналитика",
        )
        line = _line(_dict(event))
        assert "Событие трассы" not in line
        assert "отмен" in line.lower()
        assert "job-77" in line
        assert "по запросу аналитика" in line


# ── R4: fallback неизвестного типа сохраняет тип/ids ─────────────────


class TestFallbackKeepsIdentity:
    def test_fallback_keeps_type_and_id_and_reports_unknown(self):
        from app.core.run_report import fact_line

        event = {
            "event_id": "evt-unknown-42",
            "run_id": "RUN-7B",
            "ts": _ts(1),
            "stage": "eda",
            "node_id": None,
            "event_type": "future_event_kind",
            "payload": {"x": 1},
            "actor": "user",
        }
        text, links = fact_line(event)
        assert "future_event_kind" in text
        assert "evt-unknown-42" in text
        assert "интерпрет" in text.lower()
        assert links == ()


# ── R5/R6/R7: watermark, версия формата, применимость, методология ───


def _meta(**over):
    base = {
        "run_id": "RUN-7BMODEL",
        "dataset_name": "week.csv",
        "target_column": "demand",
        "target_column_source": "auto",
        "status": "active",
        "created_at": _ts(0),
        "last_active_at": _ts(9),
    }
    base.update(over)
    return base


def _model_events():
    return [
        _ev("upload_completed", "upload", "structure_confirmed",
            "RUN-7BMODEL", _ts(1), name="week.csv", rows=30, columns=2),
        _ev("target_column_changed", "validation", None, "RUN-7BMODEL",
            _ts(2), target_column="demand", source="auto"),
        _ev("candidates_generated", "modeling", "candidate_generation",
            "RUN-7BMODEL", _ts(4), runnable_candidates=5),
        _ev("backtest_run", "modeling", "backtest", "RUN-7BMODEL",
            _ts(5), model_id="arima", model_name="ARIMA"),
        _ev("forecast_generated", "forecasting", None, "RUN-7BMODEL",
            _ts(7), forecast_id="F-77", model_id="arima", horizon=12),
    ]


class TestReportVersioningAndValidity:
    def test_model_carries_watermark_and_version(self):
        from app.core.run_report import build_report_model

        events = _model_events()
        model = build_report_model(_meta(), [_dict(e) for e in events])
        assert model.watermark == len(events)
        assert str(model.report_version) == "2"

    def test_md_carries_format_version_watermark(self):
        from app.core.run_report import build_report_model, render_markdown

        model = build_report_model(
            _meta(), [_dict(e) for e in _model_events()]
        )
        md = render_markdown(model)
        assert "Версия формата отчёта" in md
        assert "watermark" in md.lower()
        assert "Формат отчёта" in md

    def test_html_carries_format_version_watermark(self):
        from app.core.run_report import build_report_model, render_html

        model = build_report_model(
            _meta(), [_dict(e) for e in _model_events()]
        )
        html = render_html(model)
        assert "Версия формата отчёта" in html
        assert "watermark" in html.lower()
        assert "Формат отчёта" in html

    def test_facts_carry_event_id(self):
        from app.core.run_report import build_report_model

        events = _model_events()
        model = build_report_model(_meta(), [_dict(e) for e in events])
        fact_ids = [
            f.event_id for stage in model.stages
            for node in stage.nodes for f in node.facts
        ]
        fact_ids += [
            f.event_id for stage in model.stages
            for f in stage.stage_level_facts
        ]
        assert len(fact_ids) == len(events)
        assert set(fact_ids) == {e.event_id for e in events}

    def test_stale_fact_marked_after_restore(self):
        """AUDIT-8: после raw restore факты прежнего контекста --
        исторические, отчёт обязан их маркировать (спека §9: «истори-
        чески выполнено»)."""
        from app.core.run_report import build_report_model

        events = [
            _ev("backtest_run", "modeling", "backtest", "RUN-7BSTALE",
                _ts(1), model_id="arima"),
        ]
        dicts = [_dict(e) for e in events]
        for d in dicts:
            d["context_id"] = "ctx-OLD"
        model = build_report_model(
            _meta(run_id="RUN-7BSTALE", context_id="ctx-NEW"), dicts
        )
        fact = model.stages[0].nodes[0].facts[0]
        assert fact.validity == "stale"

    def test_stale_marker_visible_in_md_and_html(self):
        from app.core.run_report import (
            build_report_model,
            render_html,
            render_markdown,
        )

        events = [
            _ev("backtest_run", "modeling", "backtest", "RUN-7BSTALE",
                _ts(1), model_id="arima"),
        ]
        dicts = [_dict(e) for e in events]
        for d in dicts:
            d["context_id"] = "ctx-OLD"
        model = build_report_model(
            _meta(run_id="RUN-7BSTALE", context_id="ctx-NEW"), dicts
        )
        md = render_markdown(model)
        html = render_html(model)
        assert "(исторический факт" in md
        assert "(исторический факт" in html

    def test_unknown_validity_fact_marked(self):
        """Легаси-факт без context_id при известном текущем контексте --
        unknown, не current (план §8 AUDIT-5B)."""
        from app.core.run_report import build_report_model

        events = [
            _ev("backtest_run", "modeling", "backtest", "RUN-7BUNK",
                _ts(1), model_id="arima"),
        ]
        dicts = [_dict(e) for e in events]
        for d in dicts:
            d["context_id"] = None
        model = build_report_model(
            _meta(run_id="RUN-7BUNK", context_id="ctx-X"), dicts
        )
        fact = model.stages[0].nodes[0].facts[0]
        assert fact.validity == "unknown"

    def test_current_fact_not_marked(self):
        """Факт СВОЕГО контекста -- без суффикса (шум не фабрикуется)."""
        from app.core.run_report import (
            build_report_model,
            render_markdown,
        )

        events = [
            _ev("backtest_run", "modeling", "backtest", "RUN-7BCUR",
                _ts(1), model_id="arima"),
        ]
        dicts = [_dict(e) for e in events]
        for d in dicts:
            d["context_id"] = "ctx-CUR"
        model = build_report_model(
            _meta(run_id="RUN-7BCUR", context_id="ctx-CUR"), dicts
        )
        assert model.stages[0].nodes[0].facts[0].validity == "current"
        md = render_markdown(model)
        assert "(исторический факт" not in md
        assert "(событие" in md  # proof-ссылка остаётся

    def test_run_without_context_meta_statement_no_fact_noise(self):
        """Запуск без текущего context_id: применимость не удостоверяется
        -- ОДНА честная строка в мете, а не суффикс на каждом факте."""
        from app.core.run_report import (
            build_report_model,
            render_markdown,
        )

        events = [
            _ev("backtest_run", "modeling", "backtest", "RUN-7BNOCTX",
                _ts(1), model_id="arima"),
        ]
        model = build_report_model(
            _meta(run_id="RUN-7BNOCTX", target_column=None,
                  target_column_source=None, context_id=None),
            [_dict(e) for e in events],
        )
        md = render_markdown(model)
        assert "(исторический факт" not in md
        assert "Контекст расчёта" in md

    def test_meta_carries_target_origin_and_context(self):
        from app.core.run_report import build_report_model, render_markdown

        model = build_report_model(
            _meta(context_id="ctx-M1"),
            [_dict(e) for e in _model_events()],
        )
        assert model.context_id == "ctx-M1"
        md = render_markdown(model)
        assert "Происхождение цели" in md
        assert "авто" in md.lower()
        assert "Контекст расчёта" in md
        assert "ctx-M1" in md

    def test_methodology_labeled_current_version(self):
        """§4.2.6: пояснения -- справочный текст ТЕКУЩЕЙ версии реестра;
        исторический результат отделяён от справки."""
        from app.core.run_report import build_report_model, render_markdown

        events = [
            _ev("profile_viewed", "eda", "correlation", "RUN-7BMETH",
                _ts(1)),
        ]
        model = build_report_model(
            _meta(run_id="RUN-7BMETH", target_column=None,
                  target_column_source=None),
            [_dict(e) for e in events],
        )
        md = render_markdown(model)
        assert "текущ" in md.lower() and "реестр" in md.lower()
        # текст методологии сам по себе остаётся вербатимом
        from apps.api.knowledge.registry import load_registry

        text = load_registry().find_article(
            "eda", "correlation", "metrics"
        ).body_md
        assert text in md


# ── R5: сравнение ids/watermark между MD, HTML, панелью, Наставником ─


class TestCrossReaderIdentity:
    def _seed_run_with_events(self, client: TestClient, run_id: str):
        """Сессия с cookie + run в слое 2 (привязка run_id к сессии --
        паттерн _seed_session_and_run AUDIT-5B)."""
        from apps.api import research_runs
        from apps.api.session_store import SESSION_COOKIE_NAME, get_session_store

        client.get("/v1/progress/trace")  # создаёт сессию и cookie
        session_id = client.cookies.get(SESSION_COOKIE_NAME) or ""
        session = get_session_store().get_or_create(session_id)
        session.run_id = run_id
        get_session_store().save(session)

        run = research_runs.ResearchRun(
            run_id=run_id,
            session_id=session_id,
            dataset_fingerprint="a" * 64,
            dataset_name="week.csv",
            target_column="demand",
            target_column_source="auto",
            created_at=_ts(0),
            last_active_at=_ts(8),
            status="active",
        )
        research_runs.get_research_run_store().upsert_run(run)
        events = [
            _ev("upload_completed", "upload", "structure_confirmed",
                run_id, _ts(1), name="week.csv", rows=30, columns=2),
            _ev("target_column_changed", "validation", None, run_id,
                _ts(2), target_column="demand", source="auto"),
            _ev("candidates_generated", "modeling", "candidate_generation",
                run_id, _ts(4), runnable_candidates=5),
            _ev("backtest_run", "modeling", "backtest", run_id, _ts(5),
                model_id="arima", model_name="ARIMA"),
            _ev("forecast_generated", "forecasting", None, run_id, _ts(7),
                forecast_id="F-77", model_id="arima", horizon=12),
        ]
        for event in events:
            research_runs.get_research_run_store().append_event(
                run_id, event
            )
        return run_id, events

    def test_md_html_panel_mentor_same_facts_and_watermark(
        self, client: TestClient
    ):
        """spec §9: панель, Наставник и отчёт -- читатели ОДНОЙ версии
        истории; factual ids и watermark совпадают у всех четырёх."""
        from apps.api.progress_projection import canonical_corpus

        run_id, events = self._seed_run_with_events(client, "RUN-7BXREAD")

        corpus = canonical_corpus([_dict(e) for e in events])
        corpus_ids = {e["event_id"] for e in corpus}

        md_resp = client.get(f"/v1/progress/runs/{run_id}/report")
        assert md_resp.status_code == 200
        md = md_resp.text
        html_resp = client.get(
            f"/v1/progress/runs/{run_id}/report", params={"format": "html"}
        )
        html = html_resp.text

        def _ids(text: str) -> set[str]:
            return set(re.findall(r"\(событие ([A-Za-z0-9\-]+)\)", text))

        md_ids, html_ids = _ids(md), _ids(html)
        assert md_ids == corpus_ids
        assert html_ids == corpus_ids

        # watermark: отчёт == панель == Наставник
        md_wm = int(re.search(r"watermark[^0-9]*(\d+)", md, re.I).group(1))
        html_wm = int(
            re.search(r"watermark[^0-9]*(\d+)", html, re.I).group(1)
        )
        trace = client.get("/v1/progress/trace")
        assert trace.status_code == 200
        trace_wm = trace.json()["watermark"]
        mentor = client.get(
            f"/v1/progress/runs/{run_id}/mentor/next-step"
        )
        assert mentor.status_code == 200
        mentor_wm = mentor.json()["watermark"]
        assert md_wm == html_wm == trace_wm == mentor_wm == len(corpus)

    def test_endpoint_document_contract_headers_honest(self, client: TestClient):
        """Формат отчёта -- контракт; в документе присутствуют
        формат/версия/watermark (экспорт самодостаточен)."""
        run_id, _events = self._seed_run_with_events(client, "RUN-7BEXPORT")
        md = client.get(f"/v1/progress/runs/{run_id}/report").text
        assert "Версия формата отчёта" in md
        assert "Формат отчёта" in md
        assert "watermark" in md.lower()


# ── Контроль: без утечки посторонних payload-ключей и сырых рядов ────


class TestNoSecretLeakage:
    def test_fact_line_reads_only_template_keys(self):
        """Посторонние ключи payload (в т.ч. «похожие на секрет») не
        попадают в текст факта -- шаблоны читают только свои ключи."""
        from app.core.run_report import fact_line

        event = {
            "event_id": "e-sec",
            "run_id": "RUN-7B",
            "ts": _ts(1),
            "stage": "upload",
            "node_id": "structure_confirmed",
            "event_type": "upload_completed",
            "payload": {
                "rows": 10,
                "api_key": "sk-SUPER-SECRET",
                "raw_series": "1,2,3,4,5",
            },
            "actor": "user",
        }
        text, _ = fact_line(event)
        assert "строк: 10" in text
        assert "sk-SUPER-SECRET" not in text
        assert "raw_series" not in text

    def test_html_escape_of_user_data_preserved(self):
        """Пин §5.4 (PROGR-7): пользовательские данные экранируются."""
        from app.core.run_report import build_report_model, render_html

        events = [
            _ev("upload_completed", "upload", "structure_confirmed",
                "RUN-7BESC", _ts(1), name="a<b>.csv"),
        ]
        model = build_report_model(
            _meta(run_id="RUN-7BESC", dataset_name="a<b>.csv",
                  target_column=None, target_column_source=None),
            [_dict(e) for e in events],
        )
        html = render_html(model)
        assert "a&lt;b&gt;.csv" in html
        assert "<b>" not in html.replace("<h3>", "")


# ── R8: подписи admin-аналитики (план §16 п.6) ────────────────────────


class TestAdminLabels:
    def test_stage_span_label_is_calendar_span_not_active_time(self):
        from apps.api.routers.progress import StageSpanStatOut

        doc = StageSpanStatOut.__doc__ or ""
        assert "календарн" in doc.lower()
        assert "активн" in doc.lower()

    def test_observation_frequency_not_unique_decisions(self):
        from apps.api.routers.progress import RuleFrequencyOut

        doc = RuleFrequencyOut.__doc__ or ""
        assert "наблюдени" in doc.lower()
