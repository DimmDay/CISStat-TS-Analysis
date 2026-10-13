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

from app.core.effective_target import normalize_target_origin
from app.core.node_status import resolve_node_id
from app.core.pipeline_graph import (
    STAGES,
    UPLOAD_STOP_DEFS,
    VALIDITY_CURRENT,
    VALIDITY_STALE,
    VALIDITY_UNKNOWN,
    event_context_validity,
)
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
# модульная). Метки Загрузки -- из ОБЩЕГО реестра остановок
# (upload_stops.json §12 п.2 через UPLOAD_STOP_DEFS, PROGR-13-A5 --
# единый источник с модулем и графиком; вшитой копии меток больше нет);
# значения синхронны NODE_LABELS packages/ui/lib/progress.ts (там метки
# тоже из общего JSON).
FALLBACK_NODE_LABELS: dict[tuple[str, str], str] = {
    # PROGR-13-B: канонический id узла Загрузки -- "structure" (выровнен
    # с остановкой модуля); legacy "structure_confirmed" нормализуется
    # на границе resolve_node_id -- отчёт старых запусков получает ту же
    # метку, история не теряется. Прямая метка по legacy id -- честный
    # сырой фоллбек (node_id как есть), зафиксировано тестом.
    **{( "upload", d["id"]): d["label"] for d in UPLOAD_STOP_DEFS},
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


_STOP_STATUS_LABELS: dict[str, str] = {
    "done": "выполнена",
    "warning": "есть замечания",
    "pending": "ожидает",
    "skipped": "пропущена",
    "running": "в работе",
    "error": "ошибка",
}


def _structure_confirmed_line(payload: dict) -> str:
    """PROGR-13-A3/A5: факт подтверждения структуры аналитиком
    (POST /date-column, остановка «Структура»): колонка -- ИЗ PAYLOAD
    (форма ответа DateColumnResponse), отсутствующая -- честная строка
    без выдуманных фактов."""
    column = payload.get("date_column")
    if column:
        return f"Подтверждена временная колонка «{column}»."
    return "Подтверждена структура данных (временная колонка)."


def _upload_stop_status_line(event: dict) -> str:
    """PROGR-13-A4/A5: факт отчёта остановки модулем «Загрузка»
    (upload_stop_status): метка остановки -- из общего реестра
    (node_label), статус -- человеческой формулировкой CheckStatus
    (неизвестное значение -- как есть, честный аудит)."""
    payload = event.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    status = str(payload.get("status") or "")
    status_label = _STOP_STATUS_LABELS.get(status, status or "неизвестен")
    node_id = str(event.get("node_id") or "")
    stop_label = node_label("upload", node_id) if node_id else node_id
    return f"Статус остановки «{stop_label}» отчитан модулем: {status_label}."


def _validation_check_status_line(event: dict) -> str:
    """PROGR-16-A: факт отчёта проверки модулем «Валидация»
    (validation_check_status, POST /v1/progress/validation-checks):
    та же гранулярность, что у панели (дефект PROGR-16-REPRO) -- метка
    проверки из реестра справки (node_label), статус -- человеческой
    формулировкой CheckStatus (неизвестное значение -- как есть,
    честный аудит)."""
    payload = event.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    status = str(payload.get("status") or "")
    status_label = _STOP_STATUS_LABELS.get(status, status or "неизвестен")
    node_id = str(event.get("node_id") or "")
    check_label = node_label("validation", node_id) if node_id else node_id
    return f"Статус проверки «{check_label}» отчитан модулем: {status_label}."


def _preprocessing_check_status_line(event: dict) -> str:
    """PROGR-17 (spec_progress_v1.1.md §2, категория B): факт отчёта
    этапа модулем «Предобработка» (preprocessing_check_status, POST
    /v1/progress/preprocessing-checks) -- зеркало _validation_check_
    status_line: та же гранулярность, что у панели -- метка остановки
    из реестра справки (node_label; все 10 остановок Предобработки
    имеют статьи «Метрики и алгоритм»), статус -- человеческой
    формулировкой CheckStatus (неизвестное значение -- как есть,
    честный аудит). Модуль назван ЯВНО: в журнале отчёта строка
    однозначно отличается от строки «Валидации» (существующий контракт
    которой не сужается -- метка модуля там опущена)."""
    payload = event.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    status = str(payload.get("status") or "")
    status_label = _STOP_STATUS_LABELS.get(status, status or "неизвестен")
    node_id = str(event.get("node_id") or "")
    check_label = node_label("preprocessing", node_id) if node_id else node_id
    return (
        f"Статус проверки «{check_label}» отчитан модулем "
        f"«Предобработка»: {status_label}."
    )


# Формулировки статуса отчёта EDA (PROGR-18): факт ПРОСМОТРА
# исследования, не исход проверки (EDA -- анализ, pass/fail-семантики
# нет; решение тимлида: done/pending по факту «аналитик открыл и
# просмотрел результат», warning не вводить). Неизвестное значение --
# как есть (честный аудит, тот же принцип, что у _STOP_STATUS_LABELS).
_EDA_STATUS_LABELS: dict[str, str] = {
    "done": "результат просмотрен аналитиком",
    "pending": "ещё не просмотрен аналитиком",
}


def _eda_check_status_line(event: dict) -> str:
    """PROGR-18 (spec_progress_v1.1.md §2, категория B): факт отчёта
    просмотра исследования модулем «EDA» (eda_check_status, POST
    /v1/progress/eda-checks) -- зеркало _preprocessing_check_status_
    line: та же гранулярность, что у панели -- метка исследования из
    реестра справки (node_label; все 10 исследований EDA имеют статьи
    «Метрики и алгоритм»). Терминология -- факта ПРОСМОТРА (решение
    тимлида: EDA -- анализ, не проверка качества), модуль назван ЯВНО:
    в журнале отчёта строка однозначно отличается от строк
    «Валидации»/«Предобработки»."""
    payload = event.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    status = str(payload.get("status") or "")
    status_label = _EDA_STATUS_LABELS.get(status, status or "неизвестен")
    node_id = str(event.get("node_id") or "")
    check_label = node_label("eda", node_id) if node_id else node_id
    return (
        f"Статус исследования «{check_label}» отчитан модулем "
        f"«EDA»: {status_label}."
    )


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

    # PROGR-13-A3/A5: факты остановок «Загрузки» -- та же гранулярность,
    # что у панели (дефект 1 PROGR-13: в отчёте была одна строка на
    # всю Загрузку).
    if event_type == "structure_confirmed":
        return _structure_confirmed_line(payload), links

    if event_type == "upload_stop_status":
        return _upload_stop_status_line(event), links

    # PROGR-16-A: факты проверок «Валидации» -- та же гранулярность,
    # что у панели (дефект PROGR-16-REPRO: «Валидация. Не начато» при
    # цветном модуле).
    if event_type == "validation_check_status":
        return _validation_check_status_line(event), links

    # PROGR-17: факты этапов «Предобработки» -- зеркало PROGR-16-A
    # (spec_progress_v1.1.md §2, категория B): та же гранулярность, что
    # у панели.
    if event_type == "preprocessing_check_status":
        return _preprocessing_check_status_line(event), links

    # PROGR-18: факты просмотров исследований «EDA» -- зеркало
    # PROGR-16-A/17 (spec_progress_v1.1.md §2, категория B): та же
    # гранулярность, что у панели.
    if event_type == "eda_check_status":
        return _eda_check_status_line(event), links

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
        # AUDIT-7B (P18/F12, spec §9: «автоматически выбрано» ≠ «выбрано
        # аналитиком»): происхождение ВЫБОРА -- из payload через
        # normalize_target_origin ЕДИНОГО редьюсера (v0.7-1A -- вторая
        # реализация семантики запрещена): auto -> «автоматически»;
        # user/legacy-отсутствие -> «вручную» (контракт PROGR-25-A);
        # мусор -- честное «неизвестно» (§8.2, не «user»).
        target = payload.get("target_column")
        origin = normalize_target_origin(payload.get("source"))
        if origin == "auto":
            head = "Установлен исследуемый признак автоматически"
        elif origin == "user":
            head = "Установлен исследуемый признак вручную"
        else:
            head = (
                "Установлен исследуемый признак "
                "(происхождение выбора неизвестно)"
            )
        if target:
            return f"{head}: {target}.", links
        return f"{head}.", links

    if event_type == "target_column_cleared":
        # AUDIT-7B (контракт v0.7-1A/§3.1): выделенный тип сброса получает
        # собственный шаблон (до задачи -- общий fallback, before_target/
        # reset_reason терялись). Части -- ИЗ PAYLOAD, отсутствующие не
        # выдумываются; пустой payload -- честный факт сброса без деталей.
        parts: list[str] = []
        before = payload.get("before_target")
        if before:
            parts.append(f"был «{before}»")
        reason = payload.get("reset_reason")
        if reason:
            parts.append(f"причина: {reason}")
        detail = f" ({', '.join(parts)})" if parts else ""
        return f"Исследуемый признак сброшен{detail}.", links

    if event_type == "profile_viewed":
        return "Профиль остановки открыт (диагностика просмотрена).", links

    # AUDIT-3: GET -- запрос/вычисление профиля, не просмотр; факт
    # показа результата -- от модуля (eda_check_status).
    if event_type == "profile_requested":
        return "Профиль запрошен (GET-запрос вычисления; показ результата фиксируется модулем).", links

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

    # ── AUDIT-7B (F09/P13, план §16): семь Modeling-типов AUDIT-7A
    # получают human-шаблоны (спека §9: «Новые Modeling-типы получают
    # шаблоны и сохраняют параметры/исходы»; до задачи -- общий fallback,
    # параметры payload терялись). Формулировки -- зеркала EVENT_NODE_
    # REASON (AUDIT-7A, факты процессной стадии, «операция ≠ результат»);
    # значения -- ИЗ PAYLOAD (payload_keys хука, §4.1), отсутствующие
    # опускаются, никаких выдуманных чисел.
    if event_type == "candidates_generated":
        parts = []
        runnable = payload.get("runnable_candidates")
        if isinstance(runnable, (int, float)) and not isinstance(runnable, bool):
            parts.append(f"годных к запуску: {runnable}")
        catalog_only = payload.get("catalog_only_candidates")
        if isinstance(catalog_only, (int, float)) and not isinstance(catalog_only, bool):
            parts.append(f"только каталог: {catalog_only}")
        blocked = payload.get("blocked_candidates")
        if isinstance(blocked, (int, float)) and not isinstance(blocked, bool):
            parts.append(f"заблокировано: {blocked}")
        spec_version = payload.get("spec_version")
        if spec_version:
            parts.append(f"спека {spec_version}")
        detail = f" ({', '.join(parts)})" if parts else ""
        return f"Сформирован пул кандидатов{detail}.", links

    if event_type == "selection_evaluated":
        # Оценка ≠ выбор (AUDIT-7A: done узла selection несёт только
        # model_selected): строка называет рекомендацию и вердикт
        # ансамбля, не фабрикует «модель выбрана».
        parts = []
        recommended = payload.get("model_id")
        if recommended:
            parts.append(f"рекомендация: «{recommended}»")
        ensemble = payload.get("status")
        if ensemble:
            parts.append(f"ансамбль: {ensemble}")
        cohort = payload.get("cohort_id")
        if cohort:
            parts.append(f"когорта {cohort}")
        detail = f" ({', '.join(parts)})" if parts else ""
        return f"Выполнена оценка выбора модели{detail}.", links

    if event_type == "models_compared":
        parts = []
        objective = payload.get("objective")
        if objective:
            parts.append(f"цель: {objective}")
        comparison = payload.get("comparison_id")
        if comparison:
            parts.append(f"сравнение {comparison}")
        detail = f" ({', '.join(parts)})" if parts else ""
        return f"Сравнение моделей выполнено{detail}.", links

    if event_type == "diagnostics_run":
        # Две формы payload (пара маршрутов /diagnostics и
        # /diagnostics/ensure, один класс факта): прямой запуск (модель +
        # источник параметров) и обеспечение скоупа (рассчитано/
        # переиспользовано -- переиспользование честно видно).
        parts = []
        model_id = payload.get("model_id")
        if model_id:
            parts.append(f"модель «{model_id}»")
        params_source = payload.get("params_source")
        if params_source:
            parts.append(f"источник параметров: {params_source}")
        calculated = payload.get("calculated_model_ids")
        if isinstance(calculated, (list, tuple)):
            parts.append(f"рассчитана для {len(calculated)}")
        reused = payload.get("reused_model_ids")
        if isinstance(reused, (list, tuple)):
            parts.append(f"переиспользована для {len(reused)}")
        backtest_ref = payload.get("backtest_run_id")
        if backtest_ref:
            parts.append(f"бэктест {backtest_ref}")
        detail = f" ({', '.join(parts)})" if parts else ""
        return f"Диагностика моделей выполнена{detail}.", links

    if event_type == "tuning_skipped":
        # AUDIT-7A: «skipped имеет обоснование» -- reason (эхо ответа)
        # попадает в строку факта.
        parts = []
        model_id = payload.get("model_id")
        model_ids = payload.get("model_ids")
        if model_id:
            parts.append(f"модель «{model_id}»")
        elif isinstance(model_ids, (list, tuple)) and model_ids:
            parts.append(
                f"модели: {', '.join(str(m) for m in model_ids)}"
            )
        reason = payload.get("reason")
        if reason:
            parts.append(f"причина: {reason}")
        detail = f" ({', '.join(parts)})" if parts else ""
        return (
            f"Тюнинг пропущен аналитиком: оставлены параметры "
            f"по умолчанию{detail}.",
            links,
        )

    if event_type == "tuning_job_started":
        parts = []
        job_id = payload.get("job_id")
        if job_id:
            parts.append(f"job {job_id}")
        model_id = payload.get("model_id")
        if model_id:
            parts.append(f"модель «{model_id}»")
        total_steps = payload.get("total_steps")
        if isinstance(total_steps, (int, float)) and not isinstance(total_steps, bool):
            parts.append(f"шагов: {total_steps}")
        detail = f" ({', '.join(parts)})" if parts else ""
        return f"Запущен job тюнинга{detail}.", links

    if event_type == "tuning_job_cancelled":
        parts = []
        job_id = payload.get("job_id")
        if job_id:
            parts.append(f"job {job_id}")
        reason = payload.get("reason")
        if reason:
            parts.append(f"причина: {reason}")
        detail = f" ({', '.join(parts)})" if parts else ""
        return f"Тюнинг отменён аналитиком до завершения{detail}.", links

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
    # AUDIT-7B (план §16: «Общий fallback сохраняет исходный тип/ids и
    # сообщает неизвестную интерпретацию»): к типу добавляются event_id
    # (proof-ссылка ledger) и явное сообщение, что интерпретация отчётом
    # не определена -- событие не маскируется под известный факт.
    audit_parts = [f"Событие трассы: {event_type}"]
    audit_parts.append("интерпретация отчётом не определена")
    event_ref = str(event.get("event_id") or "").strip()
    if event_ref:
        audit_parts.append(f"событие {event_ref}")
    return f"{audit_parts[0]} ({'; '.join(audit_parts[1:])}).", links


# ── Модель отчёта (структура, независимая от рендеров) ───────────────


RUN_STATUS_LABELS: dict[str, str] = {
    "active": "в работе",
    "paused": "на паузе",
    "completed": "завершён",
    "abandoned": "покинут",
}

_STAGE_LEVEL_BLOCK_TITLE = "Решения уровня этапа"

# AUDIT-7B (план §16: «при экспорте сохранять report format/version и
# watermark»): версия ФОРМАТА отчёта. v1 -- PROGR-7 (линейный отчёт из
# слоя 2); v2 -- AUDIT-7B: мета несёт watermark/происхождение цели/
# контекст расчёта, факты несут proof-ссылки event_id и маркировку
# применимости (current/stale/unknown), методология помечена как
# справочный текст текущей версии реестра, Modeling-типы AUDIT-7A и
# target_column_cleared получили human-шаблоны. Аддитивно: события v1
# читаются без миграции (корпус не переписывается).
REPORT_VERSION = "2"

_ORIGIN_META_LABELS: dict[str, str] = {
    "auto": "автоматически (auto)",
    "user": "вручную (user)",
}


@dataclass(frozen=True)
class ReportFact:
    """Одна строка факта: время + текст (+ ссылки §5.4).

    AUDIT-7B (аддитивно, v1-совместимо): event_id -- proof-ссылка на
    событие durable-ledger (spec §9: «Каждая цифра/причина ссылается на
    породивший её факт»; сравнение factual ids между MD/HTML/панелью/
    Наставником); validity -- применимость факта к ТЕКУЩИМ данным
    запуска (event_context_validity, уровень context_id: current/stale/
    unknown -- после raw restore факты прежнего контекста маркируются
    историческими, легаси-факты без context_id -- unknown, план §8
    AUDIT-5B)."""

    ts: str
    text: str
    links: tuple[tuple[str, str], ...] = ()
    event_id: str = ""
    validity: str = VALIDITY_CURRENT


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
    """Мета запуска (§5) + секции в каноническом порядке пайплайна.

    AUDIT-7B (аддитивно): watermark -- позиция истории (полный размер
    канонического корпуса; spec §9: панель/Наставник/отчёт -- читатели
    ОДНОЙ версии истории); report_version -- версия формата; 
    target_column_source/context_id -- происхождение текущей цели и
    текущий контекст расчёта запуска (из run-метаданных AUDIT-1A/C).
    """

    run_id: str
    dataset_name: str
    target_column: Optional[str]
    status: str
    status_label: str
    created_at: str
    last_active_at: str
    events_total: int
    stages: tuple[ReportStage, ...]
    watermark: int = 0
    report_version: str = REPORT_VERSION
    target_column_source: Optional[str] = None
    context_id: Optional[str] = None


def build_report_model(
    run_meta: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    canonical_order: bool = False,
) -> RunReportModel:
    """Сборка модели отчёта из меты запуска (ResearchRun.to_dict) и
    stored-событий (TraceEvent.to_dict). Секции -- в каноническом порядке
    STAGES (этапы без событий опускаются); узлы -- в порядке первого
    касания; события неизвестной стадии -- в защитную хвостовую секцию
    (прямой TraceEvent в хранилище не проходит гейт make_trace_event,
    но и не должен обваливать отчёт).

    AUDIT-5B (P12/F08, план §8 «Один canonical order для панели,
    Наставника и отчёта»): canonical_order=True -- вход уже в
    каноническом порядке корпуса (дедуп по event_id + позиция ledger;
    продиктован проекцией apps/api/progress_projection.py) и НЕ
    пересортировывается: ts-сортировка корпуса с sequence -- второй
    порядок того же корпуса (контрпример P12), запрещена. По умолчанию
    False -- прежнее поведение прямых вызовов (стабильная
    хронология ts).

    AUDIT-7B (план §16): каждый факт несёт proof-ссылку event_id и
    применимость к текущим данным (event_context_validity по context_id
    запуска: stale -- факт другого контекста после raw restore, unknown
    -- легаси-факт без context_id; при неизвестном контексте запуска
    применимость не удостоверяется -- глобальная строка меты, без шума
    суффиксов); watermark = полный размер корпуса (позиция истории);
    происхождение текущей цели и контекст расчёта -- из run-метаданных."""
    if canonical_order:
        ordered = list(events)
    else:
        ordered = sort_events_chronologically(events)

    run_context_id = run_meta.get("context_id")
    if not isinstance(run_context_id, str) or not run_context_id:
        run_context_id = None

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
        event_context = event.get("context_id")
        if not isinstance(event_context, str) or not event_context:
            event_context = None
        fact = ReportFact(
            ts=format_ts(event.get("ts")),
            text=text,
            links=links,
            event_id=str(event.get("event_id") or ""),
            validity=event_context_validity(event_context, run_context_id),
        )
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
    target_source = run_meta.get("target_column_source")
    if not isinstance(target_source, str) or not target_source:
        target_source = None
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
        # AUDIT-7B: полный размер канонического корпуса -- позиция истории
        # (projection.events_total == watermark, spec §9).
        watermark=len(ordered),
        report_version=REPORT_VERSION,
        target_column_source=target_source,
        context_id=run_context_id,
    )


# ── Рендеры: markdown (канон) и html (самодостаточный документ) ──────

# AUDIT-7B (§4.2.6, план §16): заметка разделяет хронологию и группировку
# и явно помечает методологию справочным текстом ТЕКУЩЕЙ версии реестра
# (исторический результат удостоверяют параметры/версии в событиях).
_REPORT_NOTE = (
    "Факты сгруппированы по этапам и узлам; исходный порядок истории — "
    "канонический порядок ledger (позиция — watermark в мете), группировка "
    "— производное представление того же корпуса. Методология остановок — "
    "тексты «Метрики и алгоритм» интерфейса платформы: это СПРАВОЧНЫЙ "
    "ТЕКСТ ТЕКУЩЕЙ версии реестра знаний, а не методика исторического "
    "расчёта — расчёт удостоверяют параметры и версии в событиях. Полные "
    "данные прогноза отдаются по ссылке на export.json (сериализация не "
    "дублируется). Каждая строка факта несёт ссылку на событие журнала."
)

_MD_DASH = "—"

# AUDIT-7B: метка применимости факта (план §16: «текущую и историческую
# применимость» отображать; spec §9: «исторически выполнено»). Присоединяется
# ТОЛЬКО при non-current validity и известном контексте запуска (запуск без
# контекста -- одна глобальная строка меты, а не суффикс на каждом факте).
_VALIDITY_MARKERS: dict[str, str] = {
    VALIDITY_STALE: "исторический факт: другой контекст расчёта",
    VALIDITY_UNKNOWN: "применимость к текущим данным неизвестна",
}

_METHODOLOGY_CURRENT_LABEL = (
    "Справочная методология (текущая версия реестра знаний):"
)


def _fact_suffixes(fact: ReportFact) -> tuple[str, str]:
    """(MD, HTML) суффиксы факта: маркер применимости + proof-ссылка
    event_id. Порядок стабилен: маркер валидности, ссылки §5.4, событие."""
    marker_md = marker_html = ""
    label = _VALIDITY_MARKERS.get(fact.validity)
    if label:
        marker_md = f" ({label})"
        marker_html = f" <em>({label})</em>"
    ref_md = ref_html = ""
    if fact.event_id:
        ref_md = f" (событие {fact.event_id})"
        ref_html = f" <span class=\"event-id\">(событие {fact.event_id})</span>"
    return f"{marker_md}{ref_md}", f"{marker_html}{ref_html}"


def _markdown_fact(fact: ReportFact) -> str:
    line = f"- {fact.ts} {_MD_DASH} {fact.text}"
    for href, label in fact.links:
        line += f" [{label}]({href})"
    suffix, _ = _fact_suffixes(fact)
    return line + suffix


def render_markdown(model: RunReportModel) -> str:
    """Канонический линейный отчёт (plan_progress.md: format=md первый).
    AUDIT-7B: мета несёт формат/версию/watermark/происхождение цели/
    контекст расчёта; методология помечена текущей версией реестра."""
    lines: list[str] = [f"# Отчёт об исследовании {model.run_id}", ""]
    lines.append("- Формат отчёта: markdown (md)")
    lines.append(f"- Версия формата отчёта: {model.report_version}")
    lines.append(f"- Датасет: {model.dataset_name or _MD_DASH}")
    lines.append(f"- Исследуемый признак: {model.target_column or _MD_DASH}")
    if model.target_column:
        # Происхождение ТЕКУЩЕЙ цели из run-метаданных (AUDIT-1A);
        # легаси-запуск без source -- честное отсутствие (не «user»).
        origin_label = _ORIGIN_META_LABELS.get(model.target_column_source)
        if origin_label:
            lines.append(f"- Происхождение цели: {origin_label}")
        else:
            lines.append(
                "- Происхождение цели: не зафиксировано (легаси-запуск)"
            )
    lines.append(f"- Статус запуска: {model.status_label}")
    lines.append(f"- Начат: {model.created_at or _MD_DASH}")
    lines.append(f"- Последняя активность: {model.last_active_at or _MD_DASH}")
    lines.append(f"- Событий в трассе: {model.events_total}")
    lines.append(f"- Позиция истории (watermark): {model.watermark}")
    lines.append(
        f"- Контекст расчёта: {model.context_id or _MD_DASH}"
    )
    if model.context_id is None:
        # AUDIT-7B: применимость фактов не удостоверяется -- одна честная
        # строка вместо суффикса на каждом факте (корпус легаси/без контекста).
        lines.append(
            "- Применимость фактов к текущим данным: не удостоверяется "
            "(у запуска не зафиксирован текущий контекст расчёта)"
        )
    lines.append("")
    lines.append(_REPORT_NOTE)

    for stage in model.stages:
        lines.append("")
        lines.append(f"## {stage.label}")
        if stage.stage_methodology:
            lines.append("")
            lines.append(f"*{_METHODOLOGY_CURRENT_LABEL}*")
            lines.append("")
            lines.append(stage.stage_methodology)
        for node in stage.nodes:
            lines.append("")
            lines.append(f"### {node.label}")
            if node.methodology:
                lines.append("")
                lines.append(f"*{_METHODOLOGY_CURRENT_LABEL}*")
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
    ".methodology-note{color:#5a6572;font-size:.85rem;font-style:italic;"
    "margin:.6rem 0 0}"
    ".methodology{white-space:pre-line;background:#f5f7fa;"
    "border:1px solid #dfe5ec;border-radius:8px;padding:.8rem 1rem;"
    "font-size:.9rem;margin:.6rem 0}"
    ".facts{padding-left:1.2rem}.facts li{margin:.3rem 0}"
    ".ts{color:#5a6572;font-family:ui-monospace,SFMono-Regular,monospace;"
    "font-size:.86em}"
    ".event-id{color:#5a6572;font-family:ui-monospace,SFMono-Regular,monospace;"
    "font-size:.82em}"
    ".stale{color:#8a5a00}"
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
        suffix, _ = _fact_suffixes(fact)
        items.append(
            f'<li><span class="ts">{escape(fact.ts)}</span>'
            f" {_MD_DASH} {escape(fact.text)}{links}{suffix}</li>"
        )
    return f'<ul class="facts">{"".join(items)}</ul>'


def render_html(model: RunReportModel) -> str:
    """Самодостаточный HTML-документ (без внешних ресурсов): все
    динамические значения экранируются -- payload несёт пользовательские
    данные (имя файла и т.п.), отчёт открывается браузером. AUDIT-7B:
    мета несёт формат/версию/watermark/происхождение цели/контекст;
    методология помечена текущей версией реестра."""
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
        f"<li><strong>Формат отчёта:</strong> html</li>",
        f"<li><strong>Версия формата отчёта:</strong> {escape(model.report_version)}</li>",
        f"<li><strong>Датасет:</strong> {escape(model.dataset_name or dash)}</li>",
        f"<li><strong>Исследуемый признак:</strong> "
        f"{escape(model.target_column or dash)}</li>",
    ]
    if model.target_column:
        origin_label = _ORIGIN_META_LABELS.get(model.target_column_source)
        if origin_label:
            parts.append(
                f"<li><strong>Происхождение цели:</strong> {escape(origin_label)}</li>"
            )
        else:
            parts.append(
                "<li><strong>Происхождение цели:</strong> "
                "не зафиксировано (легаси-запуск)</li>"
            )
    parts.extend(
        [
            f"<li><strong>Статус запуска:</strong> {escape(model.status_label)}</li>",
            f"<li><strong>Начат:</strong> {escape(model.created_at or dash)}</li>",
            f"<li><strong>Последняя активность:</strong> "
            f"{escape(model.last_active_at or dash)}</li>",
            f"<li><strong>Событий в трассе:</strong> {model.events_total}</li>",
            f"<li><strong>Позиция истории (watermark):</strong> {model.watermark}</li>",
            f"<li><strong>Контекст расчёта:</strong> {escape(model.context_id or dash)}</li>",
        ]
    )
    if model.context_id is None:
        parts.append(
            "<li><strong>Применимость фактов к текущим данным:</strong> "
            "не удостоверяется (у запуска не зафиксирован текущий "
            "контекст расчёта)</li>"
        )
    parts.extend(
        [
            "</ul></div>",
            f'<p class="note">{escape(_REPORT_NOTE)}</p>',
        ]
    )
    for stage in model.stages:
        parts.append(f"<h2>{escape(stage.label)}</h2>")
        if stage.stage_methodology:
            parts.append(
                f'<p class="methodology-note">{escape(_METHODOLOGY_CURRENT_LABEL)}</p>'
            )
            parts.append(
                f'<div class="methodology">{escape(stage.stage_methodology)}</div>'
            )
        for node in stage.nodes:
            parts.append(f"<h3>{escape(node.label)}</h3>")
            if node.methodology:
                parts.append(
                    f'<p class="methodology-note">{escape(_METHODOLOGY_CURRENT_LABEL)}</p>'
                )
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