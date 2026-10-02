# app/core/run_report.py
"""Отчёт для пользователя (spec_progress.md §5.4, Task PROGR-7).

GET /v1/progress/runs/{run_id}/report?format=md|html рендерит trace_events
долговременного слоя (§5 слой 2) в читаемый ЛИНЕЙНЫЙ отчёт: по каждому
пройденному узлу -- что нашли, что исправили, чем кончилось.

Контракты, зафиксированные реализацией:

  * Терминология НЕ изобретается заново (§5.4 дословно): методология
    остановок -- тексты «Метрики и алгоритм» ВЕРБАТИМ из единого
    промотированного реестра знаний (apps/api/knowledge -- артефакт
    EDU-API-1, паритет байт-в-байт с TS-источником застрахован jest-тестом
    при каждом прогоне). Метки узлов -- заголовки тех же текстов
    (механический вывод, паттерн title реестра), метки стадий --
    stage_labels_ru реестра. Локальный fallback -- только для узлов без
    статей справки (Загрузка; 4 типа событий Прогнозирования), значения
    синхронны packages/ui/lib/progress.ts::NODE_LABELS.
  * Прогнозирование -- ПО ССЫЛКЕ (§5.4): полные данные прогноза отдаются
    ссылкой на GET /v1/session/modeling/forecast/{id}/export.json
    (spec_forecasting2.md §5.5 -- самодостаточный файл); сериализация не
    дублируется.
  * Факты -- из payload событий (§4.1: тот же уровень детализации, что
    уже возвращают эндпоинты). Отсутствующие факты не выдумываются
    (демо-загрузка без payload_keys -- честная строка без чисел);
    неизвестный тип события -- строка аудита (R3 PROGR-1-CERT: такие
    события хранятся).
  * N-2 (находка PROGR-4): stage-level события (node_id=None) не
    превращаются в узловые блоки -- им отдельный блок «Решения уровня
    этапа». Исключение -- контракт PROGR-1: forecasting-события слоя 2
    хранят node_id=None, узел выводится из типа события (4 канонических
    типа == узлы графа §2) -- публичным resolve_node_id единого движка
    app/core/node_status.py (Расхождение №1, PROGR-10: своего зеркала
    в модуле больше нет).
  * Хронология -- стабильная сортировка по ts, нечитаемые -- в конец
    (зеркало sortEventsChronologically packages/ui/lib/progress.ts).
  * HTML -- самодостаточный документ: ВСЕ динамические значения
    экранируются (payload несёт пользовательские данные -- имя файла);
    методология -- white-space:pre-line (вербатим-текст реестра).
"""
from __future__ import annotations

import html as _html
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.node_status import resolve_node_id
from app.core.pipeline_graph import STAGES
from apps.api.knowledge.registry import KnowledgeRegistry, load_registry

# ── Терминология из реестра знаний (единый источник, §5.4) ───────────

_REGISTRY: Optional[KnowledgeRegistry] = None


def _get_registry() -> KnowledgeRegistry:
    """Реестр знаний (один экземпляр на процесс; module-глобал вместо
    lru_cache -- точка патча для тестов, паттерн MENTOR_CONFIG PROGR-6)."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_registry()
    return _REGISTRY


_METRICS_LABEL_PREFIX = "Метрики и алгоритм: "

# Узлы без статей справки в реестре: Загрузка (справка не писалась --
# события несут факты) и 4 типа событий Прогнозирования (справка этапа --
# модульная). Значения синхронны NODE_LABELS packages/ui/lib/progress.ts.
FALLBACK_NODE_LABELS: dict[tuple[str, str], str] = {
    # PROGR-13-B: канонический id узла Загрузки -- "structure" (выровнен
    # с остановкой модуля); legacy "structure_confirmed" нормализуется
    # на границе resolve_node_id -- отчёт старых запусков получает ту же
    # метку, история не теряется.
    ("upload", "structure"): "Структура данных",
    ("forecasting", "forecast_generated"): "Прогноз построен",
    ("forecasting", "forecast_compared"): "Сравнение прогнозов",
    ("forecasting", "forecast_sensitivity_computed"): "Анализ чувствительности",
    ("forecasting", "forecast_exported"): "Экспорт прогноза",
}


def stage_label(stage: str) -> str:
    """RU-метка этапа -- stage_labels_ru реестра знаний."""
    return _get_registry().stage_label(stage)


def node_label(stage: str, node_id: str) -> str:
    """Метка узла из заголовка статьи справки: «Метрики и алгоритм: X»
    -> X (механический вывод, без перенабора -- терминология остановки).
    Для узлов без статей -- fallback-словарь, на последнем месте -- id."""
    registry = _get_registry()
    for facet in ("metrics", "stage_overview"):
        article = registry.find_article(stage, node_id, facet)
        if article is None:
            continue
        title = article.title.strip()
        if title.startswith(_METRICS_LABEL_PREFIX):
            return title[len(_METRICS_LABEL_PREFIX):].strip()
        return title
    return FALLBACK_NODE_LABELS.get((stage, node_id), node_id)


def node_methodology(stage: str, node_id: str) -> Optional[str]:
    """Текст «Метрики и алгоритм» остановки ВЕРБАТИМ (validation/
    preprocessing/eda -- facet metrics; modeling -- stage_overview узла).
    Промах -- None (no fabricated results, паттерн реестра)."""
    registry = _get_registry()
    for facet in ("metrics", "stage_overview"):
        article = registry.find_article(stage, node_id, facet)
        if article is not None:
            return article.body_md
    return None


def stage_methodology(stage: str) -> Optional[str]:
    """Методология УРОВНЯ ЭТАПА: пока только Прогнозирование (модульный
    stage_overview) -- рендерится один раз в шапке секции."""
    if stage != "forecasting":
        return None
    article = _get_registry().find_article("forecasting", None, "stage_overview")
    return article.body_md if article is not None else None


# ── Хронология (зеркало sortEventsChronologically фронтенда) ─────────


def _parse_event_ts(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def format_ts(raw: Any) -> str:
    """ISO 8601 UTC -> «YYYY-MM-DD HH:MM:SS UTC»; нечитаемое -- как есть
    (аудит честен, не «чистим» чужие данные)."""
    parsed = _parse_event_ts(raw)
    if parsed is None:
        return str(raw or "")
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def sort_events_chronologically(events: list[dict[str, Any]]) -> list[dict]:
    """Стабильная сортировка по ts; нечитаемые -- в конец с сохранением
    взаимного порядка (та же семантика, что на фронтенде)."""
    def _key(event: dict) -> float:
        parsed = _parse_event_ts(event.get("ts"))
        if parsed is None:
            return float("inf")
        return parsed.astimezone(timezone.utc).timestamp()

    return sorted(events, key=_key)


# ── Строки фактов: что нашли, что исправили, чем кончилось ───────────

_FORECAST_EXPORT_LINK_LABEL = "Полные данные прогноза (export.json)"

_CORRECTION_COUNTER_LABELS: tuple[tuple[str, str], ...] = (
    ("total_changed", "изменено значений"),
    ("rows_removed", "удалено строк"),
    ("total_missing", "пропусков"),
    ("total_outliers", "выбросов"),
    ("total_violations", "нарушений"),
    ("total_invalid", "некорректных значений"),
)


def _forecast_export_link(forecast_id: Any) -> tuple[tuple[str, str], ...]:
    """§5.4: полные данные прогноза -- ссылкой на export.json, сериализация
    не дублируется. Без forecast_id -- ссылки нет (не выдумываем)."""
    fid = str(forecast_id or "").strip()
    if not fid:
        return ()
    href = f"/v1/session/modeling/forecast/{fid}/export.json"
    return ((href, _FORECAST_EXPORT_LINK_LABEL),)


def _correction_parts(payload: dict) -> list[str]:
    """Части строки correction-факта: стратегия/метод, затем счётчики
    ИЗ PAYLOAD (отсутствующие опускаются -- §4.1: факты, не сырой ответ)."""
    parts: list[str] = []
    strategy = payload.get("strategy")
    if strategy:
        parts.append(f"стратегия «{strategy}»")
    method = payload.get("method")
    if method:
        parts.append(f"метод «{method}»")
    for key, label in _CORRECTION_COUNTER_LABELS:
        value = payload.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            parts.append(f"{label}: {value}")
    policy = payload.get("invalid_policy")
    if policy:
        parts.append(f"политика некорректных: {policy}")
    if payload.get("target_column_reset"):
        parts.append("исследуемый признак сброшен")
    return parts


def _correction_line(event_type: str, payload: dict) -> str:
    parts = _correction_parts(payload)
    head = "Применено исправление" if event_type == "correction_applied" else (
        "Предпросмотр исправления"
    )
    detail = f" ({', '.join(parts)})" if parts else ""
    if event_type == "correction_previewed":
        return f"{head}{detail}. Изменения не применены."
    return f"{head}{detail}."


def _upload_line(payload: dict) -> str:
    parts: list[str] = []
    if payload.get("rows") is not None:
        parts.append(f"строк: {payload['rows']}")
    if payload.get("columns") is not None:
        parts.append(f"колонок: {payload['columns']}")
    if payload.get("size_label"):
        parts.append(f"размер: {payload['size_label']}")
    name = payload.get("name")
    if not parts and not name:
        return "Загружен датасет."
    name_part = f" «{name}»" if name else ""
    detail = f": {', '.join(parts)}" if parts else ""
    return f"Загружен датасет{name_part}{detail}."


def fact_line(event: dict) -> tuple[str, tuple[tuple[str, str], ...]]:
    """Факт события -- человекочитаемая строка (+ ссылки, если есть).
    Шаблоны пишут терминологию платформы (стратегия/метод/счётчики --
    те же имена, что уже показывают Мастера); неизвестный тип -- честная
    строка аудита без выдуманных фактов."""
    event_type = str(event.get("event_type") or "")
    payload = event.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    links: tuple[tuple[str, str], ...] = ()

    if event_type == "upload_completed":
        return _upload_line(payload), links

    if event_type in ("correction_applied", "correction_previewed"):
        return _correction_line(event_type, payload), links

    if event_type == "mode_changed":
        modes = payload.get("modes")
        if isinstance(modes, dict) and modes:
            items = ", ".join(
                f"{key} → {modes[key]}" for key in sorted(modes)
            )
            return f"Изменены режимы проверок: {items}.", links
        if modes:
            return f"Изменены режимы проверок: {modes}.", links
        return "Изменены режимы проверок.", links

    if event_type == "target_column_changed":
        target = payload.get("target_column")
        if target:
            return f"Установлен исследуемый признак: {target}.", links
        return "Исследуемый признак изменён.", links

    if event_type == "profile_viewed":
        return "Профиль остановки открыт (диагностика просмотрена).", links

    if event_type == "passport_captured":
        parts: list[str] = []
        if payload.get("stage"):
            parts.append(f"этап {payload['stage']}")
        if payload.get("snapshot_id"):
            parts.append(f"снимок {payload['snapshot_id']}")
        if payload.get("fingerprint"):
            parts.append(f"отпечаток {payload['fingerprint']}")
        detail = f" ({', '.join(parts)})" if parts else ""
        return f"Паспорт данных захвачен{detail}.", links

    if event_type == "backtest_run":
        name = payload.get("model_name") or payload.get("model_id")
        parts = []
        if payload.get("family_id"):
            parts.append(f"семейство {payload['family_id']}")
        if payload.get("n_train") is not None and payload.get("n_test") is not None:
            parts.append(f"train {payload['n_train']} / test {payload['n_test']}")
        name_part = f" модели «{name}»" if name else ""
        detail = f" ({', '.join(parts)})" if parts else ""
        return f"Бэктест{name_part}{detail} запущен.", links

    if event_type == "tuning_trial_completed":
        parts = []
        if payload.get("n_trials") is not None:
            parts.append(f"испытаний: {payload['n_trials']}")
        if payload.get("best_trial") is not None:
            parts.append(f"лучший trial #{payload['best_trial']}")
        if payload.get("grid_size") is not None:
            parts.append(f"размер сетки: {payload['grid_size']}")
        detail = f": {', '.join(parts)}" if parts else ""
        return f"Тюнинг завершён{detail}.", links

    if event_type == "model_selected":
        name = payload.get("model_name")
        model_id = payload.get("selected_model_id") or payload.get("model_id")
        parts = []
        if name:
            parts.append(f"«{name}»")
        if model_id:
            parts.append(f"({model_id})")
        detail = " ".join(parts) if parts else ""
        tail = f" {detail}" if detail else ""
        return f"Выбрана модель{tail}.", links

    if event_type == "model_card_generated":
        card_id = payload.get("card_id") or payload.get("model_card_id")
        parts = []
        if card_id:
            parts.append(str(card_id))
        if payload.get("model_id"):
            parts.append(f"модель {payload['model_id']}")
        detail = f" ({', '.join(parts)})" if parts else ""
        return f"Сгенерирована Model Card{detail}.", links

    if event_type == "forecast_generated":
        parts = []
        if payload.get("model_id"):
            parts.append(f"модель {payload['model_id']}")
        if payload.get("horizon") is not None:
            parts.append(f"горизонт {payload['horizon']}")
        if payload.get("alpha") is not None:
            parts.append(f"интервал alpha={payload['alpha']}")
        if payload.get("ci_method"):
            parts.append(f"метод {payload['ci_method']}")
        detail = f" ({', '.join(parts)})" if parts else ""
        fid = payload.get("forecast_id")
        head = f"Построен прогноз {fid}" if fid else "Построен прогноз"
        return f"{head}{detail}.", _forecast_export_link(fid)

    if event_type == "forecast_compared":
        ids = payload.get("forecast_ids")
        if isinstance(ids, (list, tuple)) and ids:
            return f"Сравнение прогнозов: {', '.join(str(i) for i in ids)}.", links
        return "Сравнение прогнозов выполнено.", links

    if event_type == "forecast_sensitivity_computed":
        parts = []
        if payload.get("n_combos") is not None:
            parts.append(f"комбинаций: {payload['n_combos']}")
        axes = payload.get("varied_axes")
        if isinstance(axes, (list, tuple)) and axes:
            parts.append(f"варьируемые оси: {', '.join(str(a) for a in axes)}")
        detail = f": {', '.join(parts)}" if parts else ""
        fid = payload.get("forecast_id")
        head = (
            f"Анализ чувствительности прогноза {fid}"
            if fid
            else "Анализ чувствительности"
        )
        return f"{head}{detail}.", links

    if event_type == "forecast_exported":
        fmt = payload.get("format")
        fid = payload.get("forecast_id")
        head = f"Экспорт прогноза {fid}" if fid else "Экспорт прогноза"
        detail = f" (формат {fmt})" if fmt else ""
        return f"{head}{detail}.", _forecast_export_link(fid)

    if event_type == "run_paused":
        return "Исследование поставлено на паузу.", links

    if event_type == "run_resumed":
        if payload.get("restored"):
            return "Исследование возобновлено (восстановлено из трассы запуска).", links
        return "Исследование возобновлено.", links

    if event_type == "checkpoint_saved":
        label = payload.get("label")
        event_ref = payload.get("event_id")
        parts = []
        if label:
            parts.append(f"«{label}»")
        if event_ref:
            parts.append(f"ссылка на событие {event_ref}")
        detail = f": {', '.join(parts)}" if parts else ""
        return f"Контрольная точка сохранена{detail}.", links

    # R3 (PROGR-1-CERT): событие с неизвестным типом хранится -- отчёт
    # не падает и не выдумывает фактов, честная строка аудита.
    return f"Событие трассы: {event_type}.", links


# ── Модель отчёта (структура, независимая от рендеров) ───────────────


RUN_STATUS_LABELS: dict[str, str] = {
    "active": "в работе",
    "paused": "на паузе",
    "completed": "завершён",
    "abandoned": "покинут",
}

_STAGE_LEVEL_BLOCK_TITLE = "Решения уровня этапа"


@dataclass(frozen=True)
class ReportFact:
    """Одна строка факта: время + текст (+ ссылки §5.4)."""

    ts: str
    text: str
    links: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ReportNode:
    """Блок пройденного узла: метка + методология «Метрики и алгоритм»
    + хронологические факты (что нашли, что исправили, чем кончилось)."""

    stage: str
    node_id: str
    label: str
    methodology: Optional[str]
    facts: tuple[ReportFact, ...] = ()


@dataclass(frozen=True)
class ReportStage:
    """Секция этапа: узлы в порядке первого касания + блок решений
    уровня этапа (N-2: node_id=None не создаёт узлов)."""

    stage: str
    label: str
    stage_methodology: Optional[str]
    nodes: tuple[ReportNode, ...] = ()
    stage_level_facts: tuple[ReportFact, ...] = ()


@dataclass(frozen=True)
class RunReportModel:
    """Мета запуска (§5) + секции в каноническом порядке пайплайна."""

    run_id: str
    dataset_name: str
    target_column: Optional[str]
    status: str
    status_label: str
    created_at: str
    last_active_at: str
    events_total: int
    stages: tuple[ReportStage, ...]


def build_report_model(
    run_meta: dict[str, Any], events: list[dict[str, Any]]
) -> RunReportModel:
    """Сборка модели отчёта из меты запуска (ResearchRun.to_dict) и
    stored-событий (TraceEvent.to_dict). Секции -- в каноническом порядке
    STAGES (этапы без событий опускаются); узлы -- в порядке первого
    касания; события неизвестной стадии -- в защитную хвостовую секцию
    (прямой TraceEvent в хранилище не проходит гейт make_trace_event,
    но и не должен обваливать отчёт)."""
    ordered = sort_events_chronologically(events)

    stage_order: list[str] = []
    node_order: dict[str, list[str]] = {}
    node_facts: dict[str, list[ReportFact]] = {}
    stage_level_facts: dict[str, list[ReportFact]] = {}

    for event in ordered:
        stage = str(event.get("stage") or "")
        if stage not in stage_order:
            stage_order.append(stage)
        # Вывод узла -- единый движок (контракт PROGR-1 внутри resolve_node_id:
        # forecasting node_id=None -> event_type; явный node_id приоритетен).
        node_id = resolve_node_id(event)
        text, links = fact_line(event)
        fact = ReportFact(ts=format_ts(event.get("ts")), text=text, links=links)
        if node_id:
            nodes = node_order.setdefault(stage, [])
            if node_id not in nodes:
                nodes.append(node_id)
            node_facts.setdefault(f"{stage}/{node_id}", []).append(fact)
        else:
            stage_level_facts.setdefault(stage, []).append(fact)

    known = [s for s in STAGES if s in stage_order]
    tail = [s for s in stage_order if s not in STAGES]

    sections: list[ReportStage] = []
    for stage in [*known, *tail]:
        nodes = tuple(
            ReportNode(
                stage=stage,
                node_id=node_id,
                label=node_label(stage, node_id),
                methodology=node_methodology(stage, node_id),
                facts=tuple(node_facts.get(f"{stage}/{node_id}", ())),
            )
            for node_id in node_order.get(stage, ())
        )
        sections.append(
            ReportStage(
                stage=stage,
                label=stage_label(stage) if stage in STAGES else stage,
                stage_methodology=stage_methodology(stage) if stage in STAGES else None,
                nodes=nodes,
                stage_level_facts=tuple(stage_level_facts.get(stage, ())),
            )
        )

    status = str(run_meta.get("status") or "active")
    target = run_meta.get("target_column")
    return RunReportModel(
        run_id=str(run_meta.get("run_id") or ""),
        dataset_name=str(run_meta.get("dataset_name") or ""),
        target_column=str(target) if target else None,
        status=status,
        status_label=RUN_STATUS_LABELS.get(status, status),
        created_at=format_ts(run_meta.get("created_at")),
        last_active_at=format_ts(run_meta.get("last_active_at")),
        events_total=len(ordered),
        stages=tuple(sections),
    )


# ── Рендеры: markdown (канон) и html (самодостаточный документ) ──────

_REPORT_NOTE = (
    "Линейная хронология по этапам пайплайна; методология остановок — "
    "тексты «Метрики и алгоритм» интерфейса платформы. Полные данные "
    "прогноза отдаются по ссылке на export.json (сериализация не дублируется)."
)

_MD_DASH = "—"


def _markdown_fact(fact: ReportFact) -> str:
    line = f"- {fact.ts} {_MD_DASH} {fact.text}"
    for href, label in fact.links:
        line += f" [{label}]({href})"
    return line


def render_markdown(model: RunReportModel) -> str:
    """Канонический линейный отчёт (plan_progress.md: format=md первый)."""
    lines: list[str] = [f"# Отчёт об исследовании {model.run_id}", ""]
    lines.append(f"- Датасет: {model.dataset_name or _MD_DASH}")
    lines.append(f"- Исследуемый признак: {model.target_column or _MD_DASH}")
    lines.append(f"- Статус запуска: {model.status_label}")
    lines.append(f"- Начат: {model.created_at or _MD_DASH}")
    lines.append(f"- Последняя активность: {model.last_active_at or _MD_DASH}")
    lines.append(f"- Событий в трассе: {model.events_total}")
    lines.append("")
    lines.append(_REPORT_NOTE)

    for stage in model.stages:
        lines.append("")
        lines.append(f"## {stage.label}")
        if stage.stage_methodology:
            lines.append("")
            lines.append(stage.stage_methodology)
        for node in stage.nodes:
            lines.append("")
            lines.append(f"### {node.label}")
            if node.methodology:
                lines.append("")
                lines.append(node.methodology)
            if node.facts:
                lines.append("")
                lines.extend(_markdown_fact(fact) for fact in node.facts)
        if stage.stage_level_facts:
            lines.append("")
            lines.append(f"### {_STAGE_LEVEL_BLOCK_TITLE}")
            lines.append("")
            lines.extend(_markdown_fact(fact) for fact in stage.stage_level_facts)

    return "\n".join(lines).rstrip() + "\n"


_HTML_CSS = (
    "body{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;"
    "max-width:56rem;margin:2rem auto;padding:0 1.5rem;color:#17202a;"
    "line-height:1.55}"
    "h1{font-size:1.45rem}"
    "h2{font-size:1.2rem;margin-top:2rem;border-bottom:1px solid #d6dbe1;"
    "padding-bottom:.3rem}"
    "h3{font-size:1.02rem;margin-top:1.4rem}"
    ".meta{color:#4a5560}.meta ul{list-style:none;padding-left:0}"
    ".note{color:#5a6572;font-size:.92rem}"
    ".methodology{white-space:pre-line;background:#f5f7fa;"
    "border:1px solid #dfe5ec;border-radius:8px;padding:.8rem 1rem;"
    "font-size:.9rem;margin:.6rem 0}"
    ".facts{padding-left:1.2rem}.facts li{margin:.3rem 0}"
    ".ts{color:#5a6572;font-family:ui-monospace,SFMono-Regular,monospace;"
    "font-size:.86em}"
    ".stage-level{color:#4a5560}"
    "a{color:#0b5fff}"
)


def _html_facts(facts: tuple[ReportFact, ...]) -> str:
    escape = _html.escape
    items: list[str] = []
    for fact in facts:
        links = "".join(
            f' <a href="{escape(href)}">{escape(label)}</a>'
            for href, label in fact.links
        )
        items.append(
            f'<li><span class="ts">{escape(fact.ts)}</span>'
            f" {_MD_DASH} {escape(fact.text)}{links}</li>"
        )
    return f'<ul class="facts">{"".join(items)}</ul>'


def render_html(model: RunReportModel) -> str:
    """Самодостаточный HTML-документ (без внешних ресурсов): все
    динамические значения экранируются -- payload несёт пользовательские
    данные (имя файла и т.п.), отчёт открывается браузером."""
    escape = _html.escape
    dash = _MD_DASH
    parts: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="ru">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>Отчёт об исследовании {escape(model.run_id)}</title>",
        f"<style>{_HTML_CSS}</style>",
        "</head>",
        "<body>",
        f"<h1>Отчёт об исследовании {escape(model.run_id)}</h1>",
        '<div class="meta"><ul>',
        f"<li><strong>Датасет:</strong> {escape(model.dataset_name or dash)}</li>",
        f"<li><strong>Исследуемый признак:</strong> "
        f"{escape(model.target_column or dash)}</li>",
        f"<li><strong>Статус запуска:</strong> {escape(model.status_label)}</li>",
        f"<li><strong>Начат:</strong> {escape(model.created_at or dash)}</li>",
        f"<li><strong>Последняя активность:</strong> "
        f"{escape(model.last_active_at or dash)}</li>",
        f"<li><strong>Событий в трассе:</strong> {model.events_total}</li>",
        "</ul></div>",
        f'<p class="note">{escape(_REPORT_NOTE)}</p>',
    ]
    for stage in model.stages:
        parts.append(f"<h2>{escape(stage.label)}</h2>")
        if stage.stage_methodology:
            parts.append(
                f'<div class="methodology">{escape(stage.stage_methodology)}</div>'
            )
        for node in stage.nodes:
            parts.append(f"<h3>{escape(node.label)}</h3>")
            if node.methodology:
                parts.append(
                    f'<div class="methodology">{escape(node.methodology)}</div>'
                )
            if node.facts:
                parts.append(_html_facts(node.facts))
        if stage.stage_level_facts:
            parts.append(
                f'<h3 class="stage-level">{escape(_STAGE_LEVEL_BLOCK_TITLE)}</h3>'
            )
            parts.append(_html_facts(stage.stage_level_facts))
    parts.append("</body>")
    parts.append("</html>")
    return "\n".join(parts) + "\n"