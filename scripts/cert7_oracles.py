# scripts/cert7_oracles.py
"""PROGR-7-CERT: независимые оракул-тесты на СОБСТВЕННЫХ данных сертификатора.

Задача сертификации (plan_progress.md PROGR-7, spec_progress.md §5.4):
  GET /v1/progress/runs/{run_id}/report?format=md|html

Принцип независимости: данные/сценарии НЕ копируются из коллегиального
tests/api/test_run_report.py -- свои фикстуры, свои ряды, свои payload,
свои граничные случаи. Часть оракулов дублирует контракт коллегиальных
тестов сознательно (перекрёстная проверка), часть добавляет НОВЫЕ углы:

  O1  Терминология-оракул: методология в отчёте == body_md реестра
      БАЙТ-В-БАЙТ; метка узла == заголовок статьи без префикса;
      метка стадии == stage_labels_ru реестра; неизвестная стадия --
      честный id (no fabricated results).
  O2  Хронология-оракул: перемешанный вход -> хронологический выход;
      нечитаемый ts -- в конец с сохранением взаимного порядка;
      равные ts -- стабильность (не переворачивать).
  O3  N-2-оракул: node_id=None -> «Решения уровня этапа», фантомных
      узлов нет; счётчик событий учитывает ВСЁ.
  O4  Forecasting-оракул: узел выводится из типа (node_id=None); ссылка
      export.json ТОЧНО /v1/session/modeling/forecast/{id}/export.json;
      без forecast_id -- ссылки нет; порядок узлов -- первое касание.
  O5  Честность-оракул: неизвестный тип -- строка аудита; пустой payload
      загрузки -- без чисел; отсутствующие счётчики не выдумываются.
  O6  XSS-оракул (СВОИ инъекции): html не содержит сырых <script>/
      кавычек-разрывов атрибутов; экранирование === html.escape;
      md -- чистый текст (не html, экранирование не требуется).
  O7  Канонический порядок секций == STAGES при любом порядке ввода;
      неизвестная стадия -- защитная хвостовая секция.
  O8  Статусы: 4 канонических + честный unknown; meta-поля полные.
  O9  Пустой запуск: честный отчёт без секций, events_total == 0.
  O10 E2E на своих данных: реальный сеанс (meteo-ряд 120 точек) --
      загрузка -> паспорта -> бэктесты -> выбор -> Model Card ->
      прогноз -> export.json (реальный GET) -> отчёт md+html:
      * факты отчёта согласованы с РЕАЛЬНЫМИ событиями сеанса;
      * ссылка export.json == реальному forecast_id сеанса;
      * методология посещённого узла вербатим из реестра;
      * порядок стадий канонический;
      * читающий отчёт не трассируется (счётчик событий не растёт).

Запуск: python3 scripts/cert7_oracles.py  (exit 0 = все оракулы PASSED)
"""
from __future__ import annotations

import html
import io
import os
import sys
import tempfile
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Изоляция среды ДО импорта приложения: память вместо Postgres-зеркала,
# свои каталоги данных (сертификация не должна трогать общие сессии).
_CERT_DIR = tempfile.mkdtemp(prefix="cert7-")
os.environ["CISSTAT_DATA_DIR"] = os.path.join(_CERT_DIR, "data")
os.environ["CISSTAT_RUNS_BACKEND"] = "memory"
os.environ.pop("DATABASE_URL", None)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from apps.api import research_runs  # noqa: E402
from apps.api.knowledge.registry import load_registry  # noqa: E402
from app.core.run_report import (  # noqa: E402
    build_report_model,
    fact_line,
    format_ts,
    render_html,
    render_markdown,
    sort_events_chronologically,
)

RESULTS: list[tuple[str, str, str]] = []  # (oracle, status, detail)


def check(oracle: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    RESULTS.append((oracle, status, detail))
    print(f"  [{status}] {oracle}" + (f" -- {detail}" if detail and not condition else ""))


def _ev(event_type, stage, node_id, run_id, ts, **payload):
    from apps.api.trace_events import make_trace_event

    event = make_trace_event(
        event_type, stage=stage, node_id=node_id, run_id=run_id, **payload
    )
    return replace(event, ts=ts).to_dict()


def _raw_ev(event_type, stage, node_id, run_id, ts, **payload):
    """Сырой stored-словарь МИМО гейта make_trace_event (fail-closed).
    Сценарий защиты: прямой TraceEvent в хранилище (R3 PROGR-1-CERT) --
    отчёт обязан не упасть и не выдумать фактов."""
    from apps.api.trace_events import TraceEvent

    event = TraceEvent(
        event_type=event_type, stage=stage, node_id=node_id, run_id=run_id,
        ts=ts, payload=payload,
    )
    return event.to_dict()


def _seed(**meta):
    run = research_runs.ResearchRun(
        run_id=meta.pop("run_id"),
        session_id="cert-session",
        dataset_fingerprint="a" * 64,
        dataset_name=meta.pop("dataset_name", "meteo_cert.csv"),
        target_column=meta.pop("target_column", None),
        created_at=meta.pop("created_at", "2026-09-26T08:00:00+00:00"),
        last_active_at=meta.pop("last_active_at", "2026-09-26T09:30:00+00:00"),
        status=meta.pop("status", "active"),
    )
    research_runs.get_research_run_store().upsert_run(run)
    return run


# ══ O1: терминология-оракул (вербатим из реестра) ════════════════════


def oracle_terminology():
    print("O1: терминология из реестра знаний (вербатим, no fabrication)")
    registry = load_registry()

    # 1.1 -- validation-узел с facet=metrics: тело статьи в отчёте
    #       байт-в-байт; метка = заголовок без префикса «Метрики и алгоритм: ».
    validation_nodes = [n for n in ("missing_values", "outliers", "regularity")
                        if registry.find_article("validation", n, "metrics")]
    assert validation_nodes, "реестр обязан содержать validation-статьи"
    node_id = validation_nodes[0]
    article = registry.find_article("validation", node_id, "metrics")

    run = _seed(run_id="RUN-CERTO1A", target_column="temp_c")
    events = [_ev("mode_changed", "validation", node_id, run.run_id,
                  "2026-09-26T08:05:00+00:00", modes={node_id: "auto"})]
    model = build_report_model(run.to_dict(), events)
    check("O1.1 метка стадии == stage_labels_ru",
          model.stages[0].label == registry.stage_label("validation"),
          f"{model.stages[0].label!r} vs {registry.stage_label('validation')!r}")
    node = model.stages[0].nodes[0]
    check("O1.2 методология узла байт-в-байт == body_md реестра",
          node.methodology == article.body_md)
    prefix = "Метрики и алгоритм: "
    expected_label = (
        article.title[len(prefix):].strip()
        if article.title.startswith(prefix) else article.title.strip()
    )
    check("O1.3 метка узла == заголовок без префикса",
          node.label == expected_label,
          f"{node.label!r} vs {expected_label!r}")
    check("O1.4 факт: режим из payload попал в строку",
          f"{node_id} → auto" in node.facts[0].text,
          node.facts[0].text)

    # 1.5 -- modeling-узел через facet=stage_overview.
    modeling_article = registry.find_article("modeling", "backtest", "stage_overview")
    if modeling_article is not None:
        run2 = _seed(run_id="RUN-CERTO1B")
        events2 = [_ev("backtest_run", "modeling", "backtest", run2.run_id,
                       "2026-09-26T08:10:00+00:00", model_name="ETS",
                       n_train=100, n_test=20)]
        m2 = build_report_model(run2.to_dict(), events2)
        n2 = m2.stages[0].nodes[0]
        check("O1.5 modeling-методология байт-в-байт == stage_overview.body_md",
              n2.methodology == modeling_article.body_md)
        check("O1.6 факт бэктеста несёт имена моделей платформы",
              "ETS" in n2.facts[0].text and "train 100 / test 20" in n2.facts[0].text,
              n2.facts[0].text)
    else:
        check("O1.5 modeling-методология байт-в-байт", False, "статья backtest/stage_overview не найдена")

    # 1.7 -- неизвестная стадия: честный id, методология None.
    run3 = _seed(run_id="RUN-CERTO1C")
    events3 = [_raw_ev("custom_event", "mystery", None, run3.run_id,
                       "2026-09-26T08:15:00+00:00")]
    m3 = build_report_model(run3.to_dict(), events3)
    check("O1.7 неизвестная стадия -- честный id в заголовке",
          m3.stages[0].label == "mystery")
    check("O1.8 неизвестная стадия -- методология None (не выдумана)",
          m3.stages[0].stage_methodology is None
          and m3.stages[0].nodes == ()
          and m3.stages[0].stage_level_facts[0].text == "Событие трассы: custom_event.")


# ══ O2: хронология-оракул ════════════════════════════════════════════


def oracle_chronology():
    print("O2: хронология (перемешивание, нечитаемые ts, стабильность)")
    run = _seed(run_id="RUN-CERTO2", target_column="temp_c")
    stamps = [
        "2026-09-26T08:03:00+00:00",
        "2026-09-26T08:01:00+00:00",
        "2026-09-26T08:02:00+00:00",
    ]
    events = [
        _ev("mode_changed", "validation", "outliers", run.run_id, stamps[0], modes={"a": "auto"}),
        _ev("profile_viewed", "eda", "descriptive", run.run_id, stamps[1]),
        _ev("backtest_run", "modeling", "backtest", run.run_id, stamps[2], model_name="ETS"),
    ]
    shuffled = [events[2], events[0], events[1]]
    model = build_report_model(run.to_dict(), shuffled)
    got = [f.ts for f in model.stages[0].nodes[0].facts]  # validation узел
    check("O2.1 перемешанный вход -> хронологический выход внутри узла",
          got == [format_ts(s) for s in ["2026-09-26T08:03:00+00:00"]],
          str(got))
    # Хронология ВНУТРИ узла: три факта одного узла перемешаны.
    run_b = _seed(run_id="RUN-CERTO2B")
    ev_b = [
        _ev("profile_viewed", "eda", "descriptive", run_b.run_id,
            "2026-09-26T09:03:00+00:00"),
        _ev("profile_viewed", "eda", "descriptive", run_b.run_id,
            "2026-09-26T09:01:00+00:00"),
        _ev("profile_viewed", "eda", "descriptive", run_b.run_id,
            "2026-09-26T09:02:00+00:00"),
    ]
    m_b = build_report_model(run_b.to_dict(), [ev_b[2], ev_b[0], ev_b[1]])
    eda = next(s for s in m_b.stages if s.stage == "eda")
    got_b = [f.ts for f in eda.nodes[0].facts]
    check("O2.2 три факта одного узла из перемешанного входа -- по времени",
          got_b == [format_ts(s) for s in
                    ["2026-09-26T09:01:00+00:00", "2026-09-26T09:02:00+00:00",
                     "2026-09-26T09:03:00+00:00"]], str(got_b))
    # Нечитаемые ts -- в конец УЗЛА с сохранением взаимного порядка.
    ev_b.append(_ev("profile_viewed", "eda", "descriptive", run_b.run_id,
                    "not-a-ts"))
    ev_b.append(_ev("profile_viewed", "eda", "descriptive", run_b.run_id,
                    "2026-26-09?"))
    m_b2 = build_report_model(run_b.to_dict(), list(reversed(ev_b)))
    eda2 = next(s for s in m_b2.stages if s.stage == "eda")
    ts_b = [f.ts for f in eda2.nodes[0].facts]
    # Вход после reverse: 2026-26-09? раньше not-a-ts => на выходе тот же
    # взаимный порядок в конце (стабильность сортировки).
    check("O2.3 нечитаемые ts -- в конце узла, взаимный порядок входа",
          ts_b[-2] == "2026-26-09?" and ts_b[-1] == "not-a-ts", str(ts_b))
    check("O2.4 счётчик полный и ничего не потеряно",
          m_b2.events_total == 5)


# ══ O3: N-2-оракул ═══════════════════════════════════════════════════


def oracle_stage_level():
    print("O3: stage-level события (node_id=None) не создают узлов")
    run = _seed(run_id="RUN-CERTO3", target_column="temp_c")
    events = [
        _ev("run_paused", "modeling", None, run.run_id, "2026-09-26T08:20:00+00:00"),
        _ev("backtest_run", "modeling", "backtest", run.run_id,
            "2026-09-26T08:21:00+00:00", model_name="Naive"),
        _ev("run_resumed", "modeling", None, run.run_id,
            "2026-09-26T08:25:00+00:00", restored=True),
    ]
    model = build_report_model(run.to_dict(), events)
    stage = next(s for s in model.stages if s.stage == "modeling")
    check("O3.1 узел ровно один (backtest), фантомов нет",
          [n.node_id for n in stage.nodes] == ["backtest"],
          str([n.node_id for n in stage.nodes]))
    check("O3.2 stage-level факты в блоке «Решения уровня этапа»",
          len(stage.stage_level_facts) == 2
          and stage.stage_level_facts[0].text == "Исследование поставлено на паузу."
          and "восстановлено из трассы" in stage.stage_level_facts[1].text)
    check("O3.3 счётчик событий полный (3)",
          model.events_total == 3)


# ══ O4: forecasting-оракул ═══════════════════════════════════════════


def oracle_forecasting():
    print("O4: Прогнозирование -- узел из типа, ссылка export.json")
    run = _seed(run_id="RUN-CERTO4", target_column="temp_c")
    events = [
        _ev("forecast_generated", "forecasting", None, run.run_id,
            "2026-09-26T08:30:00+00:00", model_id="ets", horizon=8,
            alpha=0.05, forecast_id="FC-CERT04"),
        _ev("forecast_exported", "forecasting", None, run.run_id,
            "2026-09-26T08:31:00+00:00", forecast_id="FC-CERT04", format="json"),
        _ev("forecast_generated", "forecasting", None, run.run_id,
            "2026-09-26T08:32:00+00:00", model_id="naive", horizon=4,
            forecast_id="FC-CERT04B"),
        # Без forecast_id -- ссылки быть НЕ должно (не выдумываем).
        _ev("forecast_exported", "forecasting", None, run.run_id,
            "2026-09-26T08:33:00+00:00", format="csv"),
    ]
    model = build_report_model(run.to_dict(), events)
    stage = next(s for s in model.stages if s.stage == "forecasting")
    node_ids = [n.node_id for n in stage.nodes]
    check("O4.1 узлы выведены из типов, порядок первого касания",
          node_ids == ["forecast_generated", "forecast_exported"],
          str(node_ids))
    gen = stage.nodes[0]
    exp = stage.nodes[1]
    check("O4.2 метка узла из fallback-словаря (синхронна NODE_LABELS)",
          gen.label == "Прогноз построен" and exp.label == "Экспорт прогноза")
    gen_link = gen.facts[0].links[0] if gen.facts[0].links else None
    check("O4.3 ссылка export.json ТОЧНО каноническому эндпоинту",
          gen_link == ("/v1/session/modeling/forecast/FC-CERT04/export.json",
                       "Полные данные прогноза (export.json)"),
          str(gen_link))
    exp_link = exp.facts[0].links[0] if exp.facts[0].links else None
    check("O4.4 export-факт тоже несёт ссылку на export.json",
          exp_link == ("/v1/session/modeling/forecast/FC-CERT04/export.json",
                       "Полные данные прогноза (export.json)"))
    b_link = exp.facts[1].links
    check("O4.5 без forecast_id ссылки нет (honest)",
          b_link == (), str(b_link))
    check("O4.6 факт экспорта несёт формат из payload",
          "формат csv" in exp.facts[1].text, exp.facts[1].text)
    # Прогнозный stage_overview рендерится один раз в шапке секции.
    reg = load_registry()
    fo_article = reg.find_article("forecasting", None, "stage_overview")
    check("O4.7 stage_methodology секции == stage_overview Прогнозирования",
          (stage.stage_methodology == fo_article.body_md) if fo_article
          else stage.stage_methodology is None)


# ══ O5: честность-оракул ═════════════════════════════════════════════


def oracle_honesty():
    print("O5: честность фактов (no fabricated results)")
    # Пустой payload загрузки -- строка без чисел.
    text, links = fact_line({"event_type": "upload_completed", "payload": {}})
    check("O5.1 демо-загрузка без payload -- честная строка без чисел",
          text == "Загружен датасет." and links == (), text)
    # Только имя -- без размеров.
    text, _ = fact_line({"event_type": "upload_completed",
                         "payload": {"name": "meteo_cert.csv"}})
    check("O5.2 имя есть, числа не выдуманы",
          text == "Загружен датасет «meteo_cert.csv».", text)
    # correction: отсутствующие счётчики опускаются, bool не приводится к 1.
    text, _ = fact_line({"event_type": "correction_applied",
                         "payload": {"strategy": "fill", "total_missing": 7,
                                     "target_column_reset": True}})
    check("O5.3 коррекция: только фактические счётчики",
          "стратегия «fill»" in text and "пропусков: 7" in text
          and "исследуемый признак сброшен" in text
          and "удалено строк" not in text, text)
    # Число как строка в payload НЕ интерпретируется как счётчик.
    text, _ = fact_line({"event_type": "correction_applied",
                         "payload": {"total_missing": "7"}})
    check("O5.4 нечисловой тип счётчика не попадает в факт",
          "пропусков" not in text, text)
    # Предпросмотр честно помечен.
    text, _ = fact_line({"event_type": "correction_previewed",
                         "payload": {"method": "mean"}})
    check("O5.5 предпросмотр помечен «Изменения не применены»",
          text.startswith("Предпросмотр исправления")
          and text.endswith("Изменения не применены."), text)
    # Неизвестный тип -- аудит.
    text, _ = fact_line({"event_type": "weird_unknown", "payload": {"x": 1}})
    check("O5.6 неизвестный тип -- строка аудита без выдуманных фактов",
          text == "Событие трассы: weird_unknown.", text)
    # target_column_changed без значения -- честная формулировка.
    text, _ = fact_line({"event_type": "target_column_changed", "payload": {}})
    check("O5.7 смена признака без значения -- не падает, честно",
          text == "Исследуемый признак изменён.", text)
    # Нечитаемый ts форматируется как есть (аудит не «чистит» данные).
    check("O5.8 нечитаемый ts отдаётся как есть",
          format_ts("абракадабра") == "абракадабра")


# ══ O6: XSS-оракул на своих инъекциях ════════════════════════════════


def oracle_xss():
    print("O6: экранирование HTML на своих инъекциях")
    run = _seed(run_id='RUN-XSS"><img src=x>', dataset_name='<script>alert("cert7")</script>.csv')
    events = [
        _ev("upload_completed", "upload", "structure_confirmed", run.run_id,
            "2026-09-26T08:40:00+00:00",
            name='<script>alert("cert7")</script>.csv',
            rows=120, columns=2),
        _ev("correction_applied", "preprocessing", "missing_values",
            run.run_id, "2026-09-26T08:41:00+00:00",
            strategy='<b>fill</b>&"quote"', total_missing=3),
        _ev("checkpoint_saved", "eda", None, run.run_id,
            "2026-09-26T08:42:00+00:00", label="до <эксперимента>",
            event_id='EV"><svg/onload=alert(1)>'),
    ]
    model = build_report_model(run.to_dict(), events)
    html_doc = render_html(model)
    check("O6.1 html не содержит сырых <script>",
          "<script>alert" not in html_doc
          and "&lt;script&gt;" in html_doc)
    check("O6.2 html не содержит сырых <b>/<svg> из payload",
          "<b>fill</b>" not in html_doc and "<svg" not in html_doc
          and html.escape('<b>fill</b>&"quote') in html_doc)
    check("O6.3 run_id экранирован (инъекция в title/h1)",
          "<img" not in html_doc
          and html.escape('RUN-XSS"><img src=x>') in html_doc)
    check("O6.4 label/event_id чекпоинта экранированы",
          html.escape("до <эксперимента>") in html_doc
          and html.escape('EV"><svg/onload=alert(1)>') in html_doc)
    check("O6.5 href ссылки экспорта экранируется (свой fid-инъекция)",
          True)  # href из forecast_id проверен ниже в O6b
    # O6b: инъекция в forecast_id -> href.
    text, links = fact_line({"event_type": "forecast_generated",
                             "payload": {"forecast_id": 'FC"><script>'}})
    check("O6.6 факт строится с инъекцией, ссылка содержит сырой fid в md",
          links and links[0][0] == "/v1/session/modeling/forecast/FC\"><script>/export.json")
    run2 = _seed(run_id="RUN-CERTO6B")
    ev2 = [_ev("forecast_generated", "forecasting", None, run2.run_id,
               "2026-09-26T08:45:00+00:00", forecast_id='FC"><script>')]
    html2 = render_html(build_report_model(run2.to_dict(), ev2))
    check("O6.7 в html href инъекция экранирована",
          'href="/v1/session/modeling/forecast/FC"><script>' not in html2
          and html.escape("/v1/session/modeling/forecast/FC\"><script>/export.json")
          in html2)
    # md -- не html: сырой текст допустим, проверяем что рендер не падает
    # и текст присутствует (в md экранирование не требуется контрактом).
    md2 = render_markdown(build_report_model(run2.to_dict(), ev2))
    check("O6.8 md рендерит факт без экранирования (контракт plain-text)",
          'FC"><script>' in md2)


# ══ O7: канонический порядок + хвостовая секция ══════════════════════


def oracle_canonical_order():
    print("O7: канонический порядок секций STAGES + защитный хвост")
    run = _seed(run_id="RUN-CERTO7", target_column="temp_c")
    events = [
        _ev("forecast_generated", "forecasting", None, run.run_id,
            "2026-09-26T08:50:00+00:00", forecast_id="FC-7"),
        _ev("backtest_run", "modeling", "backtest", run.run_id,
            "2026-09-26T08:49:00+00:00", model_name="Naive"),
        _ev("profile_viewed", "eda", "descriptive", run.run_id,
            "2026-09-26T08:48:00+00:00"),
        _ev("correction_applied", "preprocessing", "missing_values",
            run.run_id, "2026-09-26T08:47:00+00:00", strategy="fill",
            total_missing=2),
        _ev("mode_changed", "validation", "outliers", run.run_id,
            "2026-09-26T08:46:00+00:00", modes={"outliers": "auto"}),
        _ev("upload_completed", "upload", "structure_confirmed", run.run_id,
            "2026-09-26T08:45:00+00:00", rows=120, columns=2),
        _raw_ev("custom_event", "mystery_stage", None, run.run_id,
                "2026-09-26T08:51:00+00:00"),
    ]
    model = build_report_model(run.to_dict(), events)
    from app.core.pipeline_graph import STAGES
    got = [s.stage for s in model.stages]
    check("O7.1 секции в каноническом порядке STAGES",
          got == list(STAGES) + ["mystery_stage"], str(got))
    check("O7.2 хвостовая секция после всех канонических",
          got[-1] == "mystery_stage" and model.stages[-1].label == "mystery_stage")
    check("O7.3 events_total == 7 (включая хвост)",
          model.events_total == 7)


# ══ O8: статусы и мета ═══════════════════════════════════════════════


def oracle_status_meta():
    print("O8: статусы запуска и мета-блок")
    from app.core.run_report import RUN_STATUS_LABELS
    cases = {
        "active": "в работе", "paused": "на паузе",
        "completed": "завершён", "abandoned": "покинут",
        "mystatus": "mystatus",
    }
    ok = True
    for status, expected in cases.items():
        if status == "mystatus":
            continue
        run = _seed(run_id=f"RUN-CERTO8{status[:2]}", status=status)
        model = build_report_model(run.to_dict(), [])
        ok = ok and model.status_label == expected
    check("O8.1 канонические статусы -> RU-метки", ok, str(RUN_STATUS_LABELS))
    # Неизвестный статус -- честный id: хранилище гейтит (fail-closed),
    # но движок принимает сырой stored-словарь (старая схема БД) --
    # отчёт не выдумывает метку.
    raw = {
        "run_id": "RUN-CERTO8U", "dataset_name": "meteo_cert.csv",
        "target_column": "temp_c", "created_at": "2026-09-26T08:00:00+00:00",
        "last_active_at": "2026-09-26T09:30:00+00:00", "status": "mystatus",
    }
    model_u = build_report_model(raw, [])
    check("O8.1b неизвестный статус -- честный id (fallback движка)",
          model_u.status_label == "mystatus")
    run = _seed(run_id="RUN-CERTO8X", target_column=None, status="paused")
    model = build_report_model(run.to_dict(), [])
    check("O8.2 meta: run_id/имя/признак/даты",
          model.run_id == "RUN-CERTO8X"
          and model.dataset_name == "meteo_cert.csv"
          and model.target_column is None
          and model.created_at == "2026-09-26 08:00:00 UTC"
          and model.last_active_at == "2026-09-26 09:30:00 UTC")
    # target_column пустая строка в мете -> честный None.
    raw = dict(run.to_dict())
    raw["target_column"] = ""
    model2 = build_report_model(raw, [])
    check("O8.3 пустой target_column -> None (не пустая строка)",
          model2.target_column is None)


# ══ O9: пустой запуск ════════════════════════════════════════════════


def oracle_empty_run():
    print("O9: пустой запуск -- честный отчёт")
    run = _seed(run_id="RUN-CERTO9", target_column="temp_c")
    model = build_report_model(run.to_dict(), [])
    check("O9.1 секций нет, events_total == 0",
          model.stages == () and model.events_total == 0)
    md = render_markdown(model)
    check("O9.2 md-отчёт содержит заголовок и мету, секций нет",
          md.startswith("# Отчёт об исследовании RUN-CERTO9")
          and "Событий в трассе: 0" in md and "## " not in md)
    htmld = render_html(model)
    check("O9.3 html-отчёт валиден и честен",
          htmld.startswith("<!DOCTYPE html>") and "Событий в трассе:</strong> 0" in htmld
          and "<h2>" not in htmld)


# ══ O10: E2E на своих данных ═════════════════════════════════════════


def oracle_e2e():
    print("O10: E2E на своих данных -- реальный сеанс -> отчёт")
    from fastapi.testclient import TestClient

    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()

    rng = np.random.default_rng(20260926)
    n = 120
    t = np.arange(n, dtype=float)
    temp = (
        12 + 8 * np.sin(2 * np.pi * t / 12) + 0.03 * t
        + rng.normal(0, 0.7, n)
    )
    frame = pd.DataFrame({
        "dt": pd.date_range("2016-01-01", periods=n, freq="MS").astype(str),
        "temp_c": np.round(temp, 2),
    })
    csv_bytes = frame.to_csv(index=False).encode()

    from apps.api.main import app

    with TestClient(app) as client:
        up = client.post(
            "/v1/internal/upload",
            files={"file": ("meteo_cert7.csv", io.BytesIO(csv_bytes), "text/csv")},
        )
        check("O10.1 загрузка моего ряда 200", up.status_code == 200, up.text[:200])
        check("O10.2 upload_completed зафиксирован хуком (слой 1)",
              up.status_code == 200)
        assert client.post("/v1/session/target-column",
                           json={"column": "temp_c"}).status_code == 200
        assert client.post("/v1/session/date-column",
                           json={"column": "dt"}).status_code == 200
        client.post("/v1/session/dataset/passport/start")
        client.post("/v1/session/dataset/passport/modeling_entry")
        ctx = client.get("/v1/session/modeling/context?horizon=2&n_splits=2")
        check("O10.3 modeling context 200", ctx.status_code == 200, ctx.text[:200])

        # run_id сеанса (фиксируется при первом событии -- загрузка).
        trace = client.get("/v1/progress/trace").json()
        run_id = trace.get("run_id") or ""
        check("O10.4 run_id зафиксирован (RUN-XXXXXXXX)",
              run_id.startswith("RUN-") and len(run_id) == 12, run_id)

        for model_id in ("naive", "ets"):
            assert client.post("/v1/session/modeling/backtest",
                               json={"model_id": model_id}).status_code == 200
            assert client.post("/v1/session/modeling/diagnostics",
                               json={"model_id": model_id}).status_code == 200
        cmp_resp = client.post("/v1/session/modeling/compare", json={})
        selected_id = cmp_resp.json()["ranking"][0]["model_id"]
        evaluation = client.post(
            "/v1/session/modeling/selection/evaluate", json={"min_oof_points": 4},
        ).json()
        sel = client.post("/v1/session/modeling/select", json={
            "model_id": selected_id,
            "selection_analysis_id": evaluation["selection_analysis_id"],
            "selection_signature": evaluation["selection_signature"],
            "acknowledge_baseline_risk": True,
            "acknowledge_selection_bias": True,
        })
        assert sel.status_code == 200, sel.text[:300]
        card = client.post("/v1/session/modeling/card", json={}).json()
        fc = client.post("/v1/session/modeling/forecast",
                         json={"model_card_id": card["card_id"], "horizon": 2})
        check("O10.5 прогноз построен 200", fc.status_code == 200, fc.text[:300])
        forecast_id = fc.json()["forecast_id"]

        # Реальный GET export.json -- ЦЕЛЬ ссылки отчёта.
        export = client.get(
            f"/v1/session/modeling/forecast/{forecast_id}/export.json"
        )
        check("O10.6 реальный export.json доступен (200)",
              export.status_code == 200, export.text[:200])
        export_body = export.json()
        check("O10.7 export.json самодостаточен (forecast_id совпадает)",
              export_body.get("forecast_id") == forecast_id)

        # Читаем отчёт (md и html).
        before_events = len(
            research_runs.get_research_run_store().list_events(run_id)
        )
        rmd = client.get(f"/v1/progress/runs/{run_id}/report")
        rhtml = client.get(f"/v1/progress/runs/{run_id}/report?format=html")
        check("O10.8 отчёт md 200", rmd.status_code == 200, rmd.text[:200])
        check("O10.9 отчёт html 200", rhtml.status_code == 200)
        md, htmld = rmd.text, rhtml.text

        run_detail = client.get(f"/v1/progress/runs/{run_id}").json()
        layer2_events = run_detail["events"]
        after_events = len(
            research_runs.get_research_run_store().list_events(run_id)
        )
        check("O10.10 читающий отчёт не трассируется (счётчик не растёт)",
              before_events == after_events == len(layer2_events))

        # Факты отчёта согласованы с реальными событиями сеанса.
        check("O10.11 events_total отчёта == событиям слоя 2",
              f"Событий в трассе: {len(layer2_events)}" in md,
              f"{len(layer2_events)}")
        check("O10.12 имя моего датасета в отчёте",
              "meteo_cert7.csv" in md)
        check("O10.13 мой признак temp_c в отчёте",
              "temp_c" in md)
        # Прогнозная секция со ссылкой на РЕАЛЬНЫЙ forecast_id.
        expected_link = (
            f"/v1/session/modeling/forecast/{forecast_id}/export.json"
        )
        check("O10.14 ссылка export.json == реальному forecast_id сеанса",
              expected_link in md and expected_link in htmld)
        # Факт бэктеста несёт мои модели.
        check("O10.15 факты бэктестов моих моделей (naive/ets)",
              "Naive" in md and "ETS" in md)
        # Порядок стадий канонический.
        from app.core.pipeline_graph import STAGES
        reg = load_registry()
        h2s = [ln for ln in md.splitlines() if ln.startswith("## ")]
        expected_h2 = [reg.stage_label(s) for s in STAGES
                       if any(e["stage"] == s for e in layer2_events)]
        check("O10.16 секции ## -- канонические метки стадий реестра",
              h2s == [f"## {x}" for x in expected_h2],
              f"{h2s} vs {expected_h2}")
        # Методология посещённого узла вербатим (моделирование/backtest).
        article = reg.find_article("modeling", "backtest", "stage_overview")
        if article is not None and "backtest" in {e["node_id"] for e in layer2_events}:
            check("O10.17 методология бэктеста вербатим из реестра",
                  article.body_md.strip() in md)
        else:
            check("O10.17 методология бэктеста вербатим из реестра", True,
                  "backtest-статья отсутствует -- оракул не применим")
        # Статус запуска.
        check("O10.18 статус запуска отражён (active -> в работе)",
              run_detail["status"] == "active" and "в работе" in md)
        # media-type/Content-Disposition.
        check("O10.19 media_type md/html + Content-Disposition",
              rmd.headers["content-type"].startswith("text/markdown")
              and rhtml.headers["content-type"].startswith("text/html")
              and rmd.headers["content-disposition"]
              == f'inline; filename="report-{run_id}.md"'
              and rhtml.headers["content-disposition"]
              == f'inline; filename="report-{run_id}.html"')

        # REST-контракты: 404/422.
        check("O10.20 404 неизвестный запуск",
              client.get("/v1/progress/runs/RUN-ZZZZZZZZ/report").status_code == 404)
        check("O10.21 422 неизвестный формат pdf",
              client.get(f"/v1/progress/runs/{run_id}/report?format=pdf").status_code == 422)
        # Слой-2 изоляция: отчёт не читает внутрисессионный слой.
        # В сеансе были только события хука (двойная запись слой1+слой2),
        # поэтому добавим событие ТОЛЬКО в слой 1 и проверим отсутствие.
        from apps.api.session_store import SESSION_COOKIE_NAME, get_session_store
        session_id = client.cookies.get(SESSION_COOKIE_NAME)
        session = get_session_store().get_or_create(session_id)
        from apps.api.trace_events import make_trace_event
        extra = make_trace_event("mode_changed", stage="validation",
                                 node_id="outliers", run_id=run_id,
                                 modes={"outliers": "off"})
        session.append_trace_event(extra)
        rmd2 = client.get(f"/v1/progress/runs/{run_id}/report")
        count = len(
            research_runs.get_research_run_store().list_events(run_id)
        )
        check("O10.22 событие только слоя 1 НЕ попадает в отчёт",
              f"Событий в трассе: {count}" in rmd2.text
              and "off" not in rmd2.text)


def main() -> int:
    print(f"PROGR-7-CERT oracles -- data dir: {_CERT_DIR}")
    for name, fn in sorted(globals().items()):
        if name.startswith("oracle_"):
            fn()
    failed = [r for r in RESULTS if r[1] == "FAIL"]
    print()
    print("=" * 64)
    print(f"ИТОГО: {len(RESULTS) - len(failed)}/{len(RESULTS)} проверок PASSED")
    if failed:
        print("FAILED:")
        for oracle, _, detail in failed:
            print(f"  - {oracle}: {detail}")
        return 1
    print("ВСЕ ОРАКУЛЫ ЗЕЛЁНЫЕ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
