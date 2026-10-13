# -*- coding: utf-8 -*-
"""Независимая сертификация PROGR-AUDIT-7B (документ исследования) --
СВОИ оракулы на СВОИХ данных.

Дизъюнктность от корпуса исполнителя (tests/api/test_progress_audit_7b.py):
  * данные: kotel_electric_hourly.csv, колонки load_kw/temp_c/humidity
    (vs week.csv, demand/rain/snow);
  * запуски: RUN-CERT7B-* (vs RUN-7B*), контексты ctxcert-* (vs ctx-*);
  * ts: 2026-10-12 08:xx UTC (vs 2026-10-13 10:xx);
  * значения: job-cert-114, F-CERT-55, cmp-cert-9, bt-cert-31,
    cohort-cert-A, модели theta/tbats_lite/naive_seasonal
    (vs job-77, F-77, sa-1, cmp-1, bt-9, arima/ets);
  * наблюдательные методы: proof-сверка с ledger store.list_events
    (ids отчёта == ids долговременного слоя), собственный экстрактор
    ids/`событие <id>` (шире паттерна исполнителя), свои
    acceptance-группы G-*.

Запуск: cwd=корень репозитория (или worktree базы), PYTHONPATH туда же:
  PYTHONPATH=. python scripts/prograudit7bcert_oracles.py
Exit 0 -- все оракулы PASS (на HEAD после реализации); на базе b43e2eb
часть оракулов обязана падать (RED-протокол сертификации).
"""
from __future__ import annotations

import re
import sys
import tempfile
import traceback
from dataclasses import replace
from datetime import datetime, timezone

RESULTS: list[tuple[str, bool, str]] = []


def oracle(name: str):
    """Декоратор-регистратор оракула (свои наблюдательные методы)."""

    def _wrap(fn):
        def _run():
            try:
                detail = fn()
                RESULTS.append((name, True, detail or "OK"))
            except AssertionError as exc:
                RESULTS.append((name, False, f"ASSERT: {exc}"))
            except Exception as exc:  # noqa: BLE001 -- протоколируем класс
                RESULTS.append(
                    (name, False, f"ERROR {type(exc).__name__}: {exc}")
                )
                traceback.print_exc()
        _run.__name__ = fn.__name__
        ORACLES.append((name, _run))
        return _run
    return _wrap


ORACLES: list[tuple[str, object]] = []

# ── СВОИ данные (дизъюнктный корпус) ─────────────────────────────────

TS0 = datetime(2026, 10, 12, 8, 0, 0, tzinfo=timezone.utc)


def _ts(minute: int) -> str:
    return datetime(2026, 10, 12, 8, minute, 0, tzinfo=timezone.utc).isoformat()


def _ev(event_type: str, stage: str, node_id, run_id: str, ts: str, **payload):
    from apps.api.trace_events import make_trace_event

    return replace(
        make_trace_event(
            event_type, stage=stage, node_id=node_id, run_id=run_id, **payload
        ),
        ts=ts,
    )


def _dict(event) -> dict:
    return event.to_dict()


def _line(event: dict) -> str:
    from app.core.run_report import fact_line

    text, _links = fact_line(event)
    return text


def _norm(text: str) -> str:
    """Нормализация пробелов/переносов -- сверка докстрингов без
    привязки к переносу строк (паттерн сверки подписей)."""
    return re.sub(r"\s+", " ", text).strip().lower()


def _fact_texts(model) -> list[str]:
    texts = [
        f.text
        for stage in model.stages
        for node in stage.nodes
        for f in node.facts
    ]
    texts += [
        f.text for stage in model.stages for f in stage.stage_level_facts
    ]
    return texts


def _fact_ids(model) -> list[str]:
    ids = [
        f.event_id
        for stage in model.stages
        for node in stage.nodes
        for f in node.facts
    ]
    ids += [
        f.event_id for stage in model.stages for f in stage.stage_level_facts
    ]
    return ids


def _meta(**over) -> dict:
    base = {
        "run_id": "RUN-CERT7B-M",
        "dataset_name": "kotel_electric_hourly.csv",
        "target_column": "load_kw",
        "target_column_source": "auto",
        "status": "active",
        "created_at": _ts(0),
        "last_active_at": _ts(9),
    }
    base.update(over)
    return base


def _model_events(run_id: str = "RUN-CERT7B-M"):
    return [
        _ev(
            "upload_completed", "upload", "structure_confirmed", run_id,
            _ts(1), name="kotel_electric_hourly.csv", rows=48, columns=3,
        ),
        _ev(
            "target_column_changed", "validation", None, run_id, _ts(2),
            target_column="load_kw", source="auto",
        ),
        _ev(
            "candidates_generated", "modeling", "candidate_generation",
            run_id, _ts(4), spec_version="2.5", runnable_candidates=12,
            catalog_only_candidates=3, blocked_candidates=4,
        ),
        _ev(
            "backtest_run", "modeling", "backtest", run_id, _ts(5),
            model_id="tbats_lite", model_name="TBATS-lite",
        ),
        _ev(
            "forecast_generated", "forecasting", None, run_id, _ts(7),
            forecast_id="F-CERT-55", model_id="theta", horizon=24,
        ),
    ]


# ── G-ORG: происхождение выбора цели в строке факта (F12/P18) ────────


@oracle("G-ORG-1 auto-origin-fact-line")
def _():
    line = _line(_dict(_ev(
        "target_column_changed", "validation", None, "RUN-CERT7B-A",
        _ts(1), target_column="load_kw", source="auto",
    )))
    assert "автоматически" in line.lower(), line
    assert "load_kw" in line, line
    assert "вручную" not in line.lower(), line
    return f"line={line!r}"


@oracle("G-ORG-2 user-origin-fact-line")
def _():
    line = _line(_dict(_ev(
        "target_column_changed", "validation", None, "RUN-CERT7B-A",
        _ts(1), target_column="temp_c", source="user",
    )))
    assert "вручную" in line.lower(), line
    assert "temp_c" in line, line
    assert "автоматически" not in line.lower(), line
    return f"line={line!r}"


@oracle("G-ORG-3 legacy-absent-source-reads-user")
def _():
    line = _line(_dict(_ev(
        "target_column_changed", "validation", None, "RUN-CERT7B-A",
        _ts(1), target_column="temp_c",
    )))
    assert "вручную" in line.lower(), line
    return f"line={line!r}"


@oracle("G-ORG-4 corrupted-source-honest-unknown")
def _():
    line = _line(_dict(_ev(
        "target_column_changed", "validation", None, "RUN-CERT7B-A",
        _ts(1), target_column="temp_c", source="sistema_sboj",
    )))
    assert "неизвест" in line.lower(), line
    assert "вручную" not in line.lower(), line
    assert "автоматически" not in line.lower(), line
    return f"line={line!r}"


@oracle("G-ORG-5 meta-origin-labels-md-html")
def _():
    from app.core.run_report import build_report_model, render_html
    from app.core.run_report import render_markdown

    model = build_report_model(
        _meta(), [_dict(e) for e in _model_events()]
    )
    md = render_markdown(model)
    html = render_html(model)
    assert "Происхождение цели: автоматически (auto)" in md, md[:600]
    # html-мета: метка и значение разделены </strong> -- сверка по паре
    assert "Происхождение цели:</strong> автоматически (auto)" in html, (
        html[:1200]
    )
    return "meta origin auto in md+html"


@oracle("G-ORG-6 meta-legacy-source-honest")
def _():
    from app.core.run_report import build_report_model, render_markdown

    model = build_report_model(
        _meta(target_column_source=None),
        [_dict(e) for e in _model_events()],
    )
    md = render_markdown(model)
    assert "не зафиксировано (легаси-запуск)" in md, "мета легаси отсутствует"
    assert "Происхождение цели: вручную (user)" not in md, "легаси маскируется под user"
    return "legacy origin honest"


@oracle("G-ORG-7 auto-clear-user-sequence")
def _():
    from app.core.run_report import build_report_model

    events = [
        _ev("target_column_changed", "validation", None, "RUN-CERT7B-SEQ",
            _ts(1), target_column="load_kw", source="auto"),
        _ev("target_column_cleared", "validation", None, "RUN-CERT7B-SEQ",
            _ts(2), reset_reason="target_type_converted",
            before_target="load_kw"),
        _ev("target_column_changed", "validation", None, "RUN-CERT7B-SEQ",
            _ts(3), target_column="temp_c", source="user"),
    ]
    model = build_report_model(
        _meta(run_id="RUN-CERT7B-SEQ", target_column="temp_c",
              target_column_source="user"),
        [_dict(e) for e in events],
    )
    texts = _fact_texts(model)
    auto_line = next(t for t in texts if "load_kw" in t)
    assert "автоматически" in auto_line.lower(), auto_line
    clear_line = next(t for t in texts if "сброшен" in t.lower())
    assert "target_type_converted" in clear_line, clear_line
    user_line = next(t for t in texts if "temp_c" in t)
    assert "вручную" in user_line.lower(), user_line
    assert model.target_column_source == "user"
    return "auto/cleared/user distinguishable"


# ── G-CLR: собственный шаблон сброса ─────────────────────────────────


@oracle("G-CLR-1 cleared-with-payload")
def _():
    line = _line(_dict(_ev(
        "target_column_cleared", "validation", None, "RUN-CERT7B-C",
        _ts(2), reset_reason="target_type_converted",
        before_target="load_kw",
    )))
    assert "сброшен" in line.lower(), line
    assert "load_kw" in line, line
    assert "target_type_converted" in line, line
    return f"line={line!r}"


@oracle("G-CLR-2 cleared-empty-payload-no-fabrication")
def _():
    line = _line(_dict(_ev(
        "target_column_cleared", "validation", None, "RUN-CERT7B-C",
        _ts(2),
    )))
    assert "сброшен" in line.lower(), line
    assert "«" not in line, f"выдуманные детали: {line!r}"
    return f"line={line!r}"


# ── G-TPL: семь Modeling-шаблонов AUDIT-7A ───────────────────────────


@oracle("G-TPL-1 candidates-generated")
def _():
    line = _line(_dict(_ev(
        "candidates_generated", "modeling", "candidate_generation",
        "RUN-CERT7B-T", _ts(4), spec_version="2.5", runnable_candidates=12,
        catalog_only_candidates=3, blocked_candidates=4,
    )))
    assert "Событие трассы" not in line, line
    assert "кандидат" in line.lower(), line
    for token in ("12", "3", "4", "2.5"):
        assert token in line, f"{token} отсутствует: {line}"
    return f"line={line!r}"


@oracle("G-TPL-2 selection-evaluated-no-choice-fabrication")
def _():
    line = _line(_dict(_ev(
        "selection_evaluated", "modeling", "selection", "RUN-CERT7B-T",
        _ts(4), selection_analysis_id="sa-cert-3", cohort_id="cohort-cert-A",
        model_id="theta", status="not_eligible",
    )))
    assert "Событие трассы" not in line, line
    assert "theta" in line, line
    assert "not_eligible" in line, line
    assert "cohort-cert-A" in line, line
    # оценка ≠ выбор: «выбрана» не фабрикуется (AUDIT-7A)
    assert "выбрана" not in line.lower(), line
    return f"line={line!r}"


@oracle("G-TPL-3 models-compared")
def _():
    line = _line(_dict(_ev(
        "models_compared", "modeling", "comparison", "RUN-CERT7B-T",
        _ts(4), comparison_id="cmp-cert-9", cohort_id="cohort-cert-A",
        objective="smape_min",
    )))
    assert "Событие трассы" not in line, line
    assert "Сравнение" in line, line
    assert "smape_min" in line, line
    assert "cmp-cert-9" in line, line
    return f"line={line!r}"


@oracle("G-TPL-4 diagnostics-direct")
def _():
    line = _line(_dict(_ev(
        "diagnostics_run", "modeling", "diagnostics", "RUN-CERT7B-T",
        _ts(4), model_id="tbats_lite", params_source="defaults",
        backtest_run_id="bt-cert-31",
    )))
    assert "Событие трассы" not in line, line
    assert "Диагностика" in line, line
    assert "tbats_lite" in line, line
    assert "defaults" in line, line
    assert "bt-cert-31" in line, line
    return f"line={line!r}"


@oracle("G-TPL-5 diagnostics-ensure-reuse-visible")
def _():
    line = _line(_dict(_ev(
        "diagnostics_run", "modeling", "diagnostics", "RUN-CERT7B-T",
        _ts(4), calculated_model_ids=["m1", "m2", "m3"],
        reused_model_ids=["m4", "m5"],
    )))
    assert "Событие трассы" not in line, line
    assert "рассчитана для 3" in line, line
    assert "переиспользована для 2" in line, line
    return f"line={line!r}"


@oracle("G-TPL-6 tuning-skipped-reason-and-models-list")
def _():
    line = _line(_dict(_ev(
        "tuning_skipped", "modeling", "tuning", "RUN-CERT7B-T", _ts(4),
        model_ids=["theta", "naive_seasonal"],
        reason="окно истории ниже мягкого порога",
    )))
    assert "Событие трассы" not in line, line
    assert "пропущен" in line.lower(), line
    assert "theta" in line and "naive_seasonal" in line, line
    assert "окно истории ниже мягкого порога" in line, line
    return f"line={line!r}"


@oracle("G-TPL-7 tuning-job-started")
def _():
    line = _line(_dict(_ev(
        "tuning_job_started", "modeling", "tuning", "RUN-CERT7B-T", _ts(4),
        operation="tune", model_id="theta", job_id="job-cert-114",
        status="running", total_steps=64,
    )))
    assert "Событие трассы" not in line, line
    assert "Запущен job тюнинга" in line, line
    assert "job-cert-114" in line, line
    assert "64" in line, line
    return f"line={line!r}"


@oracle("G-TPL-8 tuning-job-cancelled")
def _():
    line = _line(_dict(_ev(
        "tuning_job_cancelled", "modeling", "tuning", "RUN-CERT7B-T",
        _ts(4), model_id="theta", job_id="job-cert-114",
        status="cancelled", reason="решение аналитика",
    )))
    assert "Событие трассы" not in line, line
    assert "отмен" in line.lower(), line
    assert "job-cert-114" in line, line
    assert "решение аналитика" in line, line
    return f"line={line!r}"


# ── G-FB: fallback неизвестного типа ─────────────────────────────────


@oracle("G-FB-1 fallback-keeps-type-id-and-unknown")
def _():
    from app.core.run_report import fact_line

    event = {
        "event_id": "evt-cert-u1",
        "run_id": "RUN-CERT7B-T",
        "ts": _ts(1),
        "stage": "eda",
        "node_id": None,
        "event_type": "future_audit_probe",
        "payload": {"x": 1},
        "actor": "user",
    }
    text, links = fact_line(event)
    assert "future_audit_probe" in text, text
    assert "evt-cert-u1" in text, text
    assert "интерпрет" in text.lower(), text
    assert links == (), links
    return f"line={text!r}"


# ── G-META: версия формата / watermark / контекст ────────────────────


@oracle("G-META-1 model-carries-watermark-version-context")
def _():
    from app.core.run_report import build_report_model

    events = _model_events()
    model = build_report_model(
        _meta(context_id="ctxcert-NEW-7B"), [_dict(e) for e in events]
    )
    assert model.watermark == len(events), model.watermark
    assert str(model.report_version) == "2", model.report_version
    assert model.context_id == "ctxcert-NEW-7B"
    assert model.target_column_source == "auto"
    return f"watermark={model.watermark} version={model.report_version}"


@oracle("G-META-2 md-meta-lines")
def _():
    from app.core.run_report import build_report_model, render_markdown

    model = build_report_model(
        _meta(context_id="ctxcert-NEW-7B"),
        [_dict(e) for e in _model_events()],
    )
    md = render_markdown(model)
    assert "Формат отчёта: markdown (md)" in md, "формат отсутствует"
    assert "Версия формата отчёта: 2" in md, "версия отсутствует"
    assert "Позиция истории (watermark): 5" in md, "watermark отсутствует"
    assert "Контекст расчёта: ctxcert-NEW-7B" in md, "контекст отсутствует"
    return "md meta complete"


@oracle("G-META-3 html-meta-lines")
def _():
    from app.core.run_report import build_report_model, render_html

    model = build_report_model(
        _meta(context_id="ctxcert-NEW-7B"),
        [_dict(e) for e in _model_events()],
    )
    html = render_html(model)
    assert "Формат отчёта:</strong> html" in html, "формат (html)"
    assert "Версия формата отчёта:</strong> 2" in html, "версия (html)"
    assert "Позиция истории (watermark):</strong> 5" in html, (
        "watermark (html)"
    )
    assert "Контекст расчёта:</strong> ctxcert-NEW-7B" in html, (
        "контекст (html)"
    )
    return "html meta complete"


# ── G-PROOF: доказательные ссылки event_id ───────────────────────────


@oracle("G-PROOF-1 model-facts-carry-disjoint-ids")
def _():
    from app.core.run_report import build_report_model

    events = _model_events()
    model = build_report_model(
        _meta(), [_dict(e) for e in events]
    )
    ids = _fact_ids(model)
    assert len(ids) == len(events), (len(ids), len(events))
    assert set(ids) == {e.event_id for e in events}, set(ids)
    assert all(ids), "пустые event_id в фактах"
    return f"ids={sorted(ids)}"


@oracle("G-PROOF-2 renders-contain-all-proof-links")
def _():
    from app.core.run_report import (
        build_report_model,
        render_html,
        render_markdown,
    )

    model = build_report_model(
        _meta(), [_dict(e) for e in _model_events()]
    )
    md = render_markdown(model)
    html = render_html(model)
    ids = _fact_ids(model)
    for eid in ids:
        assert f"(событие {eid})" in md, f"{eid} нет в md"
        assert f"(событие {eid})" in html, f"{eid} нет в html"
    assert md.count("(событие ") == len(ids), "лишние/недостающие ссылки md"
    return f"{len(ids)} proof-links in md+html"


@oracle("G-PROOF-3 e2e-proof-links-match-ledger")
def _e2e_proof():
    from apps.api import research_runs
    from apps.api.session_store import (
        SESSION_COOKIE_NAME,
        get_session_store,
    )

    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    from fastapi.testclient import TestClient

    from apps.api.main import app
    from apps.api.progress_projection import canonical_corpus

    with tempfile.TemporaryDirectory() as tmp:
        import os

        os.environ["CISSTAT_DATA_DIR"] = tmp
        research_runs.reset_research_run_store_for_testing()
        research_runs.reset_dataset_file_store_for_testing()
        with TestClient(app) as client:
            client.get("/v1/progress/trace")
            session_id = client.cookies.get(SESSION_COOKIE_NAME) or ""
            session = get_session_store().get_or_create(session_id)
            session.run_id = "RUN-CERT7B-E2E"
            get_session_store().save(session)

            run = research_runs.ResearchRun(
                run_id="RUN-CERT7B-E2E",
                session_id=session_id,
                dataset_fingerprint="c" * 64,
                dataset_name="kotel_electric_hourly.csv",
                target_column="load_kw",
                target_column_source="auto",
                context_id="ctxcert-E2E-7B",
                created_at=_ts(0),
                last_active_at=_ts(8),
                status="active",
            )
            research_runs.get_research_run_store().upsert_run(run)
            events = _model_events("RUN-CERT7B-E2E")
            for event in events:
                research_runs.get_research_run_store().append_event(
                    "RUN-CERT7B-E2E", event
                )

            ledger_ids = {
                e.event_id
                for e in research_runs.get_research_run_store().list_events(
                    "RUN-CERT7B-E2E"
                )
            }
            md = client.get(
                "/v1/progress/runs/RUN-CERT7B-E2E/report"
            ).text
            report_ids = set(
                re.findall(r"событие\s+([A-Za-z0-9\-_\.]+)", md)
            )
            assert report_ids == ledger_ids, (
                report_ids ^ ledger_ids
            )
    return f"ledger==report: {len(ledger_ids)} ids"


# ── G-VAL: применимость фактов ───────────────────────────────────────


def _events_with_context(events, context):
    dicts = [_dict(e) for e in events]
    for d in dicts:
        d["context_id"] = context
    return dicts


@oracle("G-VAL-1 stale-marked-md-html")
def _():
    from app.core.run_report import (
        build_report_model,
        render_html,
        render_markdown,
    )

    dicts = _events_with_context(
        [_ev("backtest_run", "modeling", "backtest", "RUN-CERT7B-S",
             _ts(1), model_id="tbats_lite")],
        "ctxcert-OLD-7B",
    )
    model = build_report_model(
        _meta(run_id="RUN-CERT7B-S", context_id="ctxcert-NEW-7B"), dicts
    )
    fact = model.stages[0].nodes[0].facts[0]
    assert fact.validity == "stale", fact.validity
    md = render_markdown(model)
    html = render_html(model)
    assert "(исторический факт: другой контекст расчёта)" in md, "нет в md"
    assert "(исторический факт: другой контекст расчёта)" in html, "нет в html"
    return "stale marker in md+html"


@oracle("G-VAL-2 unknown-legacy-fact-marked")
def _():
    from app.core.run_report import build_report_model, render_markdown

    dicts = _events_with_context(
        [_ev("backtest_run", "modeling", "backtest", "RUN-CERT7B-U",
             _ts(1), model_id="tbats_lite")],
        None,
    )
    model = build_report_model(
        _meta(run_id="RUN-CERT7B-U", context_id="ctxcert-X-7B"), dicts
    )
    fact = model.stages[0].nodes[0].facts[0]
    assert fact.validity == "unknown", fact.validity
    md = render_markdown(model)
    assert "(применимость к текущим данным неизвестна)" in md, md[-400:]
    return "unknown marker in md"


@oracle("G-VAL-3 current-fact-no-noise")
def _():
    from app.core.run_report import build_report_model, render_markdown

    dicts = _events_with_context(
        [_ev("backtest_run", "modeling", "backtest", "RUN-CERT7B-CR",
             _ts(1), model_id="tbats_lite")],
        "ctxcert-CUR-7B",
    )
    model = build_report_model(
        _meta(run_id="RUN-CERT7B-CR", context_id="ctxcert-CUR-7B"), dicts
    )
    assert model.stages[0].nodes[0].facts[0].validity == "current"
    md = render_markdown(model)
    assert "(исторический факт" not in md, "шум stale на своём контексте"
    assert "(применимость к текущим данным неизвестна" not in md
    assert "(событие " in md, "proof-ссылка потеряна"
    return "current clean, proof kept"


@oracle("G-VAL-4 run-without-context-single-meta-line")
def _():
    from app.core.run_report import (
        build_report_model,
        render_html,
        render_markdown,
    )

    dicts = _events_with_context(
        [_ev("backtest_run", "modeling", "backtest", "RUN-CERT7B-NC",
             _ts(1), model_id="tbats_lite")],
        None,
    )
    model = build_report_model(
        _meta(run_id="RUN-CERT7B-NC", target_column=None,
              target_column_source=None, context_id=None),
        dicts,
    )
    md = render_markdown(model)
    html = render_html(model)
    assert "не удостоверяется" in md, "честная строка меты отсутствует"
    assert "не удостоверяется" in html, "честная строка меты (html)"
    assert "(исторический факт" not in md, "суффиксный шум без контекста"
    assert (
        "(применимость к текущим данным неизвестна" not in md
    ), "F-7BC1: per-fact unknown-суффикс при запуске без контекста (§24.2: шум не фабрикуется)"
    assert md.count("не удостоверяется") == 1, "больше одной строки меты"
    return "single honest meta statement"


# ── G-METH: методология -- справочный текст текущей версии ───────────


@oracle("G-METH-1 node-methodology-labeled-current")
def _():
    from app.core.run_report import build_report_model, render_markdown
    from apps.api.knowledge.registry import load_registry

    events = [
        _ev("profile_viewed", "eda", "seasonality", "RUN-CERT7B-ME",
            _ts(1)),
    ]
    model = build_report_model(
        _meta(run_id="RUN-CERT7B-ME", target_column=None,
              target_column_source=None),
        [_dict(e) for e in events],
    )
    md = render_markdown(model)
    label = "Справочная методология (текущая версия реестра знаний):"
    assert label in md, "метка справочной методологии отсутствует"
    body = load_registry().find_article(
        "eda", "seasonality", "metrics"
    ).body_md
    assert body in md, "вербатим-текст реестра потерян"
    return "label + verbatim registry text"


@oracle("G-METH-2 stage-methodology-and-note-separation")
def _():
    from app.core.run_report import build_report_model, render_markdown

    model = build_report_model(
        _meta(), [_dict(e) for e in _model_events()]
    )
    md = render_markdown(model)
    label = "Справочная методология (текущая версия реестра знаний):"
    assert label in md, "метка справочной методологии отсутствует"
    # ЛИТЕРАЛЬНЫЙ stage-пин (урок волны 1: node-метки любого узла
    # удовлетворяли бы общий assert -- самореференция): в сегменте
    # секции «Прогнозирование» ДО первого узлового заголовка обязана
    # стоять курсивная метка stage-методологии.
    head = md.find("## Прогнозирование")
    assert head >= 0, "секция Прогнозирования отсутствует"
    node_h = md.find("\n### ", head)
    segment = md[head: node_h if node_h > 0 else len(md)]
    assert f"*{label}*" in segment, (
        "stage-метка отсутствует в шапке секции Прогнозирования: "
        f"{segment[:300]!r}"
    )
    assert "канонический порядок ledger" in md, (
        "заметка не разделяет хронологию и группировку"
    )
    assert "СПРАВОЧНЫЙ ТЕКСТ ТЕКУЩЕЙ" in md, (
        "разделение исторического результата и справки отсутствует"
    )
    return "stage literal pin + note separation"


# ── G-ADM: подписи admin-аналитики ───────────────────────────────────


@oracle("G-ADM-1 stage-span-out-label")
def _():
    from apps.api.routers.progress import StageSpanStatOut

    doc = _norm(StageSpanStatOut.__doc__ or "")
    assert "календарн" in doc, doc
    assert "не время активной работы" in doc, doc
    return "StageSpanStatOut honest label"


@oracle("G-ADM-2 rule-frequency-out-label")
def _():
    from apps.api.routers.progress import RuleFrequencyOut

    doc = _norm(RuleFrequencyOut.__doc__ or "")
    assert "наблюдени" in doc, doc
    assert "не число уникальных решений" in doc, doc
    return "RuleFrequencyOut honest label"


@oracle("G-ADM-3 sanity-node-frequency-out-label")
def _():
    from apps.api.routers.progress import SanityNodeFrequencyOut

    doc = _norm(SanityNodeFrequencyOut.__doc__ or "")
    assert "не уникальные решения" in doc, doc
    return "SanityNodeFrequencyOut honest label"


@oracle("G-ADM-4 engine-stage-span-docstring")
def _():
    from app.core.admin_analytics import StageSpanStat

    doc = _norm(StageSpanStat.__doc__ or "")
    assert "не время активной работы аналитика" in doc, doc
    return "engine docstring honest"


# ── G-ESC: экранирование и отсутствие утечек ─────────────────────────


@oracle("G-ESC-1 cleared-reason-escaped-in-html")
def _():
    from app.core.run_report import (
        build_report_model,
        render_html,
        render_markdown,
    )

    events = [
        _ev("target_column_cleared", "validation", None, "RUN-CERT7B-ESC",
            _ts(2), reset_reason="<script>alert(1)</script>",
            before_target="load<b>kw"),
    ]
    model = build_report_model(
        _meta(run_id="RUN-CERT7B-ESC"), [_dict(e) for e in events]
    )
    html = render_html(model)
    md = render_markdown(model)
    assert "<script>alert(1)</script>" not in html, "XSS в html"
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html, "нет экранирования"
    assert "load&lt;b&gt;kw" in html, "before_target не экранирован"
    # md -- текстовый формат, сырые угловые скобки payload не проходят
    # как HTML-инъекция, но и не теряются: факт содержит причину
    assert "alert(1)" in md, "причина потеряна в md"
    return "html escape of new template payload"


@oracle("G-ESC-2 templates-read-only-own-keys")
def _():
    from app.core.run_report import fact_line

    event = {
        "event_id": "e-cert-sec",
        "run_id": "RUN-CERT7B-SEC",
        "ts": _ts(1),
        "stage": "upload",
        "node_id": "structure_confirmed",
        "event_type": "upload_completed",
        "payload": {
            "rows": 48,
            "api_key": "sk-CERT-SECRET-VALUE",
            "raw_series": "1,2,3,4,5",
        },
        "actor": "user",
    }
    text, _ = fact_line(event)
    assert "48" in text, text
    assert "sk-CERT-SECRET-VALUE" not in text, "утечка ключа"
    assert "raw_series" not in text, "утечка сырого ряда"
    return "no secret/raw leak"


# ── G-XRED: сквозное сравнение читателей (панель/Наставник/отчёт) ────


def _seed_e2e_run(client, run_id: str):
    from apps.api import research_runs
    from apps.api.session_store import (
        SESSION_COOKIE_NAME,
        get_session_store,
    )

    client.get("/v1/progress/trace")
    session_id = client.cookies.get(SESSION_COOKIE_NAME) or ""
    session = get_session_store().get_or_create(session_id)
    session.run_id = run_id
    get_session_store().save(session)

    run = research_runs.ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint="d" * 64,
        dataset_name="kotel_electric_hourly.csv",
        target_column="temp_c",
        target_column_source="user",
        context_id="ctxcert-XRED-7B",
        created_at=_ts(0),
        last_active_at=_ts(8),
        status="active",
    )
    research_runs.get_research_run_store().upsert_run(run)
    events = [
        _ev("upload_completed", "upload", "structure_confirmed", run_id,
            _ts(1), name="kotel_electric_hourly.csv", rows=48, columns=3),
        _ev("target_column_changed", "validation", None, run_id, _ts(2),
            target_column="temp_c", source="user"),
        _ev("candidates_generated", "modeling", "candidate_generation",
            run_id, _ts(4), runnable_candidates=12),
        _ev("tuning_skipped", "modeling", "tuning", run_id, _ts(5),
            model_id="theta", reason="окно истории ниже мягкого порога"),
        _ev("backtest_run", "modeling", "backtest", run_id, _ts(6),
            model_id="tbats_lite", model_name="TBATS-lite"),
        _ev("forecast_generated", "forecasting", None, run_id, _ts(7),
            forecast_id="F-CERT-55", model_id="theta", horizon=24),
    ]
    for event in events:
        research_runs.get_research_run_store().append_event(run_id, event)
    return events


@oracle("G-XRED-1 four-readers-one-history")
def _():
    from fastapi.testclient import TestClient

    from apps.api.main import app
    from apps.api.progress_projection import canonical_corpus

    with tempfile.TemporaryDirectory() as tmp:
        import os

        os.environ["CISSTAT_DATA_DIR"] = tmp
        from apps.api import research_runs

        research_runs.reset_research_run_store_for_testing()
        research_runs.reset_dataset_file_store_for_testing()
        with TestClient(app) as client:
            events = _seed_e2e_run(client, "RUN-CERT7B-XR")
            corpus = canonical_corpus([_dict(e) for e in events])
            corpus_ids = {e["event_id"] for e in corpus}

            md = client.get(
                "/v1/progress/runs/RUN-CERT7B-XR/report"
            )
            assert md.status_code == 200, md.status_code
            html = client.get(
                "/v1/progress/runs/RUN-CERT7B-XR/report",
                params={"format": "html"},
            )
            assert html.status_code == 200, html.status_code

            def _ids(text: str) -> set:
                return set(
                    re.findall(r"событие\s+([A-Za-z0-9\-_\.]+)", text)
                )

            md_ids, html_ids = _ids(md.text), _ids(html.text)
            assert md_ids == corpus_ids, md_ids ^ corpus_ids
            assert html_ids == corpus_ids, html_ids ^ corpus_ids

            md_wm = int(
                re.search(r"watermark[^0-9]*(\d+)", md.text, re.I).group(1)
            )
            html_wm = int(
                re.search(r"watermark[^0-9]*(\d+)", html.text, re.I).group(1)
            )
            trace = client.get("/v1/progress/trace")
            assert trace.status_code == 200
            trace_wm = trace.json()["watermark"]
            mentor = client.get(
                "/v1/progress/runs/RUN-CERT7B-XR/mentor/next-step"
            )
            assert mentor.status_code == 200, mentor.status_code
            mentor_wm = mentor.json()["watermark"]
            assert (
                md_wm == html_wm == trace_wm == mentor_wm == len(corpus)
            ), (md_wm, html_wm, trace_wm, mentor_wm, len(corpus))
    return f"4 readers == watermark {md_wm}"


@oracle("G-XRED-2 export-self-sufficient-endpoint")
def _():
    from fastapi.testclient import TestClient

    from apps.api.main import app

    with tempfile.TemporaryDirectory() as tmp:
        import os

        os.environ["CISSTAT_DATA_DIR"] = tmp
        from apps.api import research_runs

        research_runs.reset_research_run_store_for_testing()
        research_runs.reset_dataset_file_store_for_testing()
        with TestClient(app) as client:
            _seed_e2e_run(client, "RUN-CERT7B-EXP")
            resp = client.get("/v1/progress/runs/RUN-CERT7B-EXP/report")
            assert resp.status_code == 200
            md = resp.text
            assert "Версия формата отчёта: 2" in md
            assert "Формат отчёта: markdown (md)" in md
            assert "Позиция истории (watermark): 6" in md
            assert "Контекст расчёта: ctxcert-XRED-7B" in md
            assert "inline" in resp.headers.get("Content-Disposition", "")
    return "endpoint export self-sufficient"


# ── Контроли (обязаны быть GREEN и на базе b43e2eb) ──────────────────


@oracle("C-1 upload-line-no-secret-leak (base control)")
def _():
    from app.core.run_report import fact_line

    text, _ = fact_line({
        "event_id": "e-c1",
        "run_id": "RUN-CERT7B-C1",
        "ts": _ts(1),
        "stage": "upload",
        "node_id": "structure_confirmed",
        "event_type": "upload_completed",
        "payload": {"rows": 7, "password": "hunter2"},
        "actor": "user",
    })
    assert "7" in text
    assert "hunter2" not in text
    return "control: old pin intact"


@oracle("C-2 html-escape-dataset-name (base control)")
def _():
    from app.core.run_report import build_report_model, render_html

    events = [
        _ev("upload_completed", "upload", "structure_confirmed",
            "RUN-CERT7B-C2", _ts(1), name="a<b>.csv"),
    ]
    model = build_report_model(
        _meta(run_id="RUN-CERT7B-C2", dataset_name="a<b>.csv",
              target_column=None, target_column_source=None),
        [_dict(e) for e in events],
    )
    html = render_html(model)
    assert "a&lt;b&gt;.csv" in html
    return "control: escape pin intact"


@oracle("C-3 none-target-honest-meta (base control)")
def _():
    from app.core.run_report import build_report_model, render_markdown

    model = build_report_model(
        _meta(target_column=None, target_column_source=None),
        [_dict(e) for e in _model_events()],
    )
    md = render_markdown(model)
    assert "Исследуемый признак: —" in md
    assert "Происхождение цели" not in md
    return "control: None target honest"


@oracle("C-4 unknown-stage-tail-section (base control)")
def _():
    from app.core.run_report import build_report_model

    events = [
        {
            "event_id": "e-cert-tail",
            "run_id": "RUN-CERT7B-C4",
            "ts": _ts(1),
            "stage": "mystery_stage",
            "node_id": "n1",
            "event_type": "backtest_run",
            "payload": {"model_id": "theta"},
            "actor": "user",
        }
    ]
    model = build_report_model(
        _meta(run_id="RUN-CERT7B-C4"), events
    )
    tail = [s for s in model.stages if s.stage == "mystery_stage"]
    assert tail, "хвостовая секция исчезла"
    assert tail[0].nodes, "узел хвостовой секции потерян"
    return "control: tail section intact"


def main() -> int:
    for _name, fn in ORACLES:
        fn()
    passed = sum(1 for _n, ok, _d in RESULTS if ok)
    print(f"{'=' * 72}")
    print(
        "PROGR-AUDIT-7B CERT: own oracles -- "
        f"{passed}/{len(RESULTS)} PASS"
    )
    print(f"{'=' * 72}")
    for name, ok, detail in RESULTS:
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {name} -- {detail}")
    print(f"{'=' * 72}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
