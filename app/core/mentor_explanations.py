# app/core/mentor_explanations.py
"""Реестр «объяснимости жёлтого статуса» Наставника (MNS-REG-2) --
данные/конфиг с fail-closed валидацией на импорте.

Контракт: spec_mentor_next_step.md §4/§5/§8 (задача MNS-REG-2 плана
docs/mentor_next_step_review_2026-10-19.md §6; решения Q1--Q7 приняты
тимлидом в 051b5fc). Для каждой из 25 warning-способных остановок
(upload 5 + validation 10 + preprocessing 10 -- РОВНО узлы STAGE_NODES
трёх стадий, порядок == канон сканирования §3.1) реестр
rules/mentor_stop_explanations.json несёт:

  * sources -- семантика источника warning классами C1--C4 спеки §4:
    C1 -- живой расчёт модуля «Загрузка» (upload_stop_status);
    C2 -- результат проверки/диагностики модуля (validation_check_status /
    preprocessing_check_status / профиль-факт outliers_profile_status /
    payload-override correction_applied «нарушения остались» -- G345
    PROGR-23, только у «Выбросов»);
    C3 -- предпросмотр коррекции correction_previewed без применения;
    C4 -- включённая вручную проверка без настроенного правила
    (needs_rule, VALFIX-1) -- только Валидация: «needs_rule»-аналога
    в Предобработке нет (routers/session.py);
  * explanation_template -- шаблон объяснения «почему жёлтый» с
    подстановкой {status_reason} и {summary_count} (контракт §5.2:
    ноль нового I/O -- пересказ уже посчитанной проекции; оба
    плейсхолдера обязательны, чужие запрещены -- контракты подстановки
    в placeholder_contract реестра);
  * deep_link -- цель «куда идти» (§5.3), формат "stage.node_id" --
    тот же формат recommended_action правил §7.1; UI-мэппинг на якорь
    степпера -- задача MNS-LINK-3, фолбэк -- вкладка стадии;
  * help_entry_id -- статья help_entries реестра знаний (Q7:
    методология -- ссылкой, вербатим остаётся отчёту
    run_report.py::node_methodology); для validation/preprocessing --
    статья facet=metrics «Метрики и алгоритм: <label>», для upload --
    существующая статья модуля upload.module.module_help.

Направление зависимостей (спека §6, риск-таблица plan_progress.md):
загрузчик читает СВОЙ файл и валидируется реестрами графа
(STAGE_NODES) и событий (node_status); хранилища и роутеры сюда не
импортируются. Терминология (label) == реестрам модулей и заголовкам
статей -- совпадение страхует сюит
tests/unit/test_mentor_stop_explanations.py (знание реестра знаний
живёт в ТЕСТЕ, не в загрузчике: загрузчик структурен, знание --
контракт).

Fail-closed (паттерн _load_pipeline_node_defs / load_mentor_config):
отсутствие файла, битый JSON, неполное покрытие, дубликат, фантомный
узел, дрейф deep_link, чужой плейсхолдер, неизвестный класс/событие
источника -- ImportError НА ИМПОРТЕ, а не тихий деградировавший
реестр: fallback-скан Наставника (MNS-FALLBACK-4) не должен стартовать
с частичной картиной объяснимости.

Потребители: MNS-FALLBACK-4 (сборка рекомендации Слоя B),
MNS-TEXT-5 (аддитивное explanation ответа next-step). Правила --
чистые функции (mentor_rules.py): этот модуль -- данные, правила/роутер
приносят факты, рендер -- чистая функция render_stop_explanation.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from app.core.node_status import EVENT_NODE_STATUS, PAYLOAD_STATUS_EVENT_TYPES
from app.core.pipeline_graph import STAGE_NODES

# ── Контракты реестра (проверяются загрузчиком, fail-closed) ──────────

MENTOR_STOP_EXPLANATIONS_PATH = (
    Path(__file__).resolve().parents[2]
    / "rules" / "mentor_stop_explanations.json"
)

# Warning-способные стадии (решения Q3/Q4: eda/modeling/forecasting
# вне скана; канон сканирования §3.1 -- порядок == порядок STAGES).
SCAN_STAGES: tuple[str, ...] = ("upload", "validation", "preprocessing")

# Классы источников warning (спека §4 -- проверенная классификация).
SOURCE_CLASSES: tuple[str, ...] = ("C1", "C2", "C3", "C4")

# Плейсхолдеры шаблона объяснения (оба обязательны, чужие запрещены).
TEMPLATE_PLACEHOLDERS: tuple[str, ...] = ("status_reason", "summary_count")

# События-носители статусов узлов: единый источник -- node_status.py
# (payload-статусы карт AUDIT-2A + карта семян статусов, включая
# correction_previewed). Список НЕ копируется -- импортируется;
# равенство страхует сюит реестра (KNOWN_SOURCE_EVENTS).
KNOWN_SOURCE_EVENTS: frozenset[str] = (
    frozenset(PAYLOAD_STATUS_EVENT_TYPES) | frozenset(EVENT_NODE_STATUS)
)

# Пары «класс -> допустимое событие-носитель» (проверенные пути
# появления warning/error: TRACE_ROUTES trace_hook.py, PAYLOAD_STATUS_*).
_CLASS_ALLOWED_EVENTS: dict[str, frozenset[str]] = {
    "C1": frozenset({"upload_stop_status"}),
    "C2": frozenset(
        {
            "validation_check_status",
            "preprocessing_check_status",
            "outliers_profile_status",
            "correction_applied",
        }
    ),
    "C3": frozenset({"correction_previewed"}),
    "C4": frozenset({"validation_check_status"}),
}

# Обязательные и допустимые классы по стадиям (спека §4): upload --
# только C1; validation -- C2 (отчёт) + C3 (preview) + C4 (needs_rule
# применим к любой из 10 проверок); preprocessing -- C2 + C3 (C4 нет).
_STAGE_ALLOWED_CLASSES: dict[str, frozenset[str]] = {
    "upload": frozenset({"C1"}),
    "validation": frozenset({"C2", "C3", "C4"}),
    "preprocessing": frozenset({"C2", "C3"}),
}
_STAGE_REQUIRED_CLASSES: dict[str, frozenset[str]] = {
    "upload": frozenset({"C1"}),
    "validation": frozenset({"C2", "C3", "C4"}),
    "preprocessing": frozenset({"C2", "C3"}),
}

# Формат ссылки на статью реестра знаний (структурная проверка
# загрузчика; содержательная -- «заголовок == метка остановки» --
# сюит реестра против registry_data.json).
_HELP_ENTRY_ID_RE = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")

# Честные константы подстановки (советы -- не факты, §3.2: недостающий
# факт не выдумывается, а честно называется недостающим).
_STATUS_REASON_MISSING = "причина не отчитана"
_SUMMARY_COUNT_MISSING = "не отчитано"


# ── Модель записи реестра ─────────────────────────────────────────────


@dataclass(frozen=True)
class MentorStopExplanationSource:
    """Источник warning одной остановки: класс спеки §4 + событие-носитель
    + проверенная семантика условия (текст реестра -- факт, не совет)."""

    source_class: str
    event: str
    semantics: str


@dataclass(frozen=True)
class MentorStopExplanation:
    """Запись реестра по одной остановке (спека §8, DoD MNS-REG-2)."""

    stage: str
    node_id: str
    label: str
    deep_link: str
    help_entry_id: str
    explanation_template: str
    sources: tuple[MentorStopExplanationSource, ...]


# ── Валидация и чтение (fail-closed, паттерн _load_pipeline_node_defs) ─


def _fail(path: Path, message: str) -> "ImportError":
    return ImportError(f"Реестр объяснимости {path}: {message}")


def _validate_stop_raw(path: Path, raw: Mapping[str, Any], index: int) -> None:
    """Структурная валидация ОДНОЙ записи до построения dataclass."""
    stage = str(raw.get("stage") or "").strip()
    node_id = str(raw.get("node_id") or "").strip()
    label = str(raw.get("label") or "").strip()
    where = f"stops[{index}] ({stage}/{node_id or '?'})"
    if stage not in SCAN_STAGES:
        raise _fail(
            path,
            f"{where}: стадия {stage!r} вне warning-способных {list(SCAN_STAGES)}",
        )
    if node_id not in STAGE_NODES[stage]:
        raise _fail(
            path,
            f"{where}: узел {node_id!r} неизвестен стадии {stage!r}; "
            f"известные: {list(STAGE_NODES[stage])}",
        )
    if not label:
        raise _fail(path, f"{where}: пустая label (терминология модуля)")
    deep_link = str(raw.get("deep_link") or "").strip()
    if deep_link != f"{stage}.{node_id}":
        raise _fail(
            path,
            f"{where}: deep_link {deep_link!r} != цели остановки "
            f"{stage}.{node_id} (спека §5.3)",
        )
    help_entry_id = str(raw.get("help_entry_id") or "").strip()
    if not _HELP_ENTRY_ID_RE.match(help_entry_id):
        raise _fail(
            path,
            f"{where}: help_entry_id {help_entry_id!r} не ссылка формата "
            "entry_id реестра знаний",
        )
    template = str(raw.get("explanation_template") or "")
    if not template.strip():
        raise _fail(path, f"{where}: пустой explanation_template")
    for placeholder in TEMPLATE_PLACEHOLDERS:
        if "{" + placeholder + "}" not in template:
            raise _fail(
                path,
                f"{where}: шаблон без обязательного "
                f"{{{placeholder}}} (контракт §5.2)",
            )
    # Чужие плейсхолдеры запрещены: .format() с двумя каноническими
    # ключами ловит любые "{...}", кроме разрешённых (KeyError/IndexError),
    # битые скобки -- ValueError; мусорная пара скобок "{}" без имени
    # не несёт контракта и тоже запрещена (честный шаблон -- только
    # документированные подстановки).
    try:
        probe = template.format(
            status_reason="_r", summary_count="_c"
        )
    except (KeyError, IndexError, ValueError) as exc:
        raise _fail(
            path,
            f"{where}: шаблон не подставляется каноническими "
            f"плейсхолдерами {TEMPLATE_PLACEHOLDERS}: {exc}",
        ) from exc
    if "{" in probe or "}" in probe:
        raise _fail(
            path,
            f"{where}: в шаблоне остались неразрешённые скобки -- "
            "чужой плейсхолдер запрещён",
        )
    sources_raw = raw.get("sources")
    if not isinstance(sources_raw, list) or not sources_raw:
        raise _fail(path, f"{where}: sources -- непустой список источников")
    seen_pairs: set[tuple[str, str]] = set()
    classes: set[str] = set()
    for source_raw in sources_raw:
        if not isinstance(source_raw, Mapping):
            raise _fail(path, f"{where}: источник не объект: {source_raw!r}")
        source_class = str(source_raw.get("source_class") or "").strip()
        event = str(source_raw.get("event") or "").strip()
        semantics = str(source_raw.get("semantics") or "").strip()
        if source_class not in SOURCE_CLASSES:
            raise _fail(
                path,
                f"{where}: класс источника {source_class!r} вне "
                f"{list(SOURCE_CLASSES)} (спека §4)",
            )
        if event not in KNOWN_SOURCE_EVENTS:
            raise _fail(
                path,
                f"{where}: событие {event!r} не носитель узловых статусов "
                "(node_status.py)",
            )
        if event not in _CLASS_ALLOWED_EVENTS[source_class]:
            raise _fail(
                path,
                f"{where}: класс {source_class} не носится событием "
                f"{event!r} (допустимые: "
                f"{sorted(_CLASS_ALLOWED_EVENTS[source_class])})",
            )
        if len(semantics) < 10:
            raise _fail(path, f"{where}: пустая семантика источника {source_class}")
        pair = (source_class, event)
        if pair in seen_pairs:
            raise _fail(
                path,
                f"{where}: дубликат источника (класс, событие) {pair}",
            )
        seen_pairs.add(pair)
        classes.add(source_class)
    allowed = _STAGE_ALLOWED_CLASSES[stage]
    required = _STAGE_REQUIRED_CLASSES[stage]
    unknown = classes - allowed
    if unknown:
        raise _fail(
            path,
            f"{where}: классы {sorted(unknown)} не применимы к стадии "
            f"{stage!r} (допустимые: {sorted(allowed)})",
        )
    missing = required - classes
    if missing:
        raise _fail(
            path,
            f"{where}: нет обязательных классов источника "
            f"{sorted(missing)} для стадии {stage!r} (спека §4)",
        )


def load_mentor_stop_explanations(
    path: Path | None = None,
) -> tuple[MentorStopExplanation, ...]:
    """Чтение реестра объяснимости (fail-closed на ВЫЗОВЕ; модульный
    singleton читает тот же файл на импорте).

    Отсутствие файла, битый JSON, пропуск обязательного поля, неполное
    покрытие, дубликат остановки/источника, фантомный узел, дрейф
    deep_link, чужой плейсхолдер, неизвестный класс/событие источника,
    нарушение порядка канона -- ImportError, а не тихая деградация.
    path -- переопределение для тестов; по умолчанию
    MENTOR_STOP_EXPLANATIONS_PATH.
    """
    path = path or MENTOR_STOP_EXPLANATIONS_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ImportError(
            f"Реестр объяснимости не найден: {path} (спека §8, DoD "
            "MNS-REG-2); файл обязателен для старта fallback-скана"
        ) from exc
    except json.JSONDecodeError as exc:
        raise _fail(path, f"не парсится: {exc}") from exc
    if not isinstance(raw, dict):
        raise _fail(path, f"корень не JSON-объект: {type(raw).__name__}")
    if raw.get("version") != 1:
        raise _fail(path, f"version {raw.get('version')!r} != 1")
    if raw.get("canon_version") != "mns_canon_v2":
        raise _fail(
            path,
            "canon_version не привязан к канону спеки v2 (mns_canon_v2)",
        )
    stops_raw = raw.get("stops")
    if not isinstance(stops_raw, list) or not stops_raw:
        raise _fail(path, "нет непустого списка stops")
    # Канон сканирования §3.1: РОВНО узлы STAGE_NODES трёх стадий,
    # в порядке STAGE_NODES -- детерминизм Слоя B (два вызова на одном
    # снапшоте дают один и тот же узел).
    expected: list[tuple[str, str]] = [
        (stage, node_id)
        for stage in SCAN_STAGES
        for node_id in STAGE_NODES[stage]
    ]
    actual: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    entries: list[MentorStopExplanation] = []
    for index, stop_raw in enumerate(stops_raw):
        if not isinstance(stop_raw, Mapping):
            raise _fail(path, f"stops[{index}] не объект: {stop_raw!r}")
        _validate_stop_raw(path, stop_raw, index)
        stage = str(stop_raw["stage"])
        node_id = str(stop_raw["node_id"])
        key = (stage, node_id)
        if key in seen:
            raise _fail(path, f"дубликат остановки {stage}/{node_id}")
        seen.add(key)
        actual.append(key)
        sources = tuple(
            MentorStopExplanationSource(
                source_class=str(source["source_class"]),
                event=str(source["event"]),
                semantics=str(source["semantics"]),
            )
            for source in stop_raw["sources"]
        )
        entries.append(
            MentorStopExplanation(
                stage=stage,
                node_id=node_id,
                label=str(stop_raw["label"]),
                deep_link=str(stop_raw["deep_link"]),
                help_entry_id=str(stop_raw["help_entry_id"]),
                explanation_template=str(stop_raw["explanation_template"]),
                sources=sources,
            )
        )
    if actual != expected:
        missing = [k for k in expected if k not in seen]
        extra = [k for k in actual if k not in expected]
        raise _fail(
            path,
            "реестр расходится с каноном сканирования §3.1 "
            f"(STAGE_NODES трёх стадий): нет {missing[:5]}, лишние "
            f"{extra[:5]}, порядок {actual[:5]}... != {expected[:5]}...",
        )
    return tuple(entries)


# Единый снимок реестра на процесс (паттерн MENTOR_CONFIG): тесты/ops
# могут подменить singleton без перезагрузки модуля; данные -- не логика.
MENTOR_STOP_EXPLANATIONS: tuple[MentorStopExplanation, ...] = (
    load_mentor_stop_explanations()
)

# Индекс по составному ключу (stage, node_id) -- идентичность узла
# составной ключ (pipeline_graph.is_known_node: regularity/stationarity
# существуют в двух стадиях).
MENTOR_STOP_EXPLANATIONS_BY_KEY: dict[tuple[str, str], MentorStopExplanation] = {
    (entry.stage, entry.node_id): entry for entry in MENTOR_STOP_EXPLANATIONS
}


def stop_explanation(stage: str, node_id: str) -> MentorStopExplanation:
    """Доступ к записи реестра (fail-closed, паттерн
    node_dependency_scopes): неизвестная пара -- ValueError, опечатка
    не должна молча вернуть чужое объяснение."""
    entry = MENTOR_STOP_EXPLANATIONS_BY_KEY.get((stage, node_id))
    if entry is None:
        raise ValueError(
            f"Нет записи реестра объяснимости для {stage!r}/{node_id!r}; "
            f"известные стадии: {list(SCAN_STAGES)}"
        )
    return entry


# ── Подстановка фактов в шаблон (контракт §5.2, чистая функция) ───────


def render_stop_explanation(
    entry: MentorStopExplanation,
    *,
    status_reason: str | None,
    summary_count: int | None,
) -> str:
    """Подстановка уже посчитанных фактов узла в шаблон реестра.

    Контракт placeholder_contract реестра (спека §5.2 -- ноль нового
    I/O, пересказ посчитанного; советы -- не факты §3.2: недостающий
    факт ЧЕСТНО называется недостающим, не выдумывается):

      * status_reason -- человекочитаемая причина статуса узла
        (EVENT_NODE_REASON / correction_reason с числами / причина
        отчёта модуля); None/пустая -- «причина не отчитана»;
      * summary_count -- число правого бейджа узла (то же, что
        показывает степпер); None/bool/дробное/отрицательное -- не
        факт (щит _clean_summary_count) -- «не отчитано».

    Функция чистая и детерминированная: рендер не мутирует реестр и не
    обращается к I/O; LLM-точка расширения -- MentorTextRenderer §8
    (переформулировка уже вычисленного текста, не вычисление факта).
    """
    reason = (status_reason or "").strip() or _STATUS_REASON_MISSING
    is_count = (
        isinstance(summary_count, int)
        and not isinstance(summary_count, bool)
        and summary_count >= 0
    )
    count_text = str(summary_count) if is_count else _SUMMARY_COUNT_MISSING
    return entry.explanation_template.format(
        status_reason=reason, summary_count=count_text
    )
