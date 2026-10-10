# app/core/pipeline_graph.py
"""Единый граф узлов пайплайна исследования -- источник истины для
сервиса «Прогресс» (spec_progress.md §2-§3, Task PROGR-2).

НЕ дублирует список остановок каждой вкладки (§2 «не дублирует,
а ссылается»):

  * Python-реестры (Валидация, Предобработка, Моделирование) импортируются
    напрямую -- STAGE_NODES держит ТЕ ЖЕ объекты-кортежи, что и исходные
    модули (идентичность застрахована тестом `is`, не только ==);
  * чисто-frontend реестр EDA (§12 п.2) вынесен в общий JSON
    shared/pipeline_nodes/eda_checks.json -- его читают и
    packages/ui/components/TsAnalysisEDA.tsx, и этот модуль; вшитой
    копии id в Python больше нет;
  * реестр остановок «Загрузки» -- ТОТ ЖЕ паттерн (§12 п.2, PROGR-13-A1):
    общий JSON shared/pipeline_nodes/upload_stops.json читают и
    packages/ui/components/TsAnalysisUpload.tsx (STOPS), и этот модуль.
    Дефект 1а PROGR-13: спека §2 «Загрузка -- нет CHECKS-массива»
    устарела -- степпер с реальными статусами существует (5 остановок),
    и панель «Прогресс» обязана агрегировать ТОТ ЖЕ реестр. Канонический
    id узла structure (PROGR-13-B: выровнен с остановкой «Структура»);
    историческое имя structure_confirmed нормализуется на границе чтения
    движка -- LEGACY_NODE_IDS в node_status.py, корпус слоя 2 историю
    сохраняет (A2);
  * Прогнозирование -- артефакт-ориентированный этап: узлы графа = 4
    типа события ForecastRun (spec_forecasting2.md §5.9, §2 таблица);
  * STAGES -- локальная константа, обязанная совпадать с
    apps/api/session_store.py::STAGES. Направленный импорт хранилища
    отсюда создал бы обратную зависимость контракта от хранилища и цикл
    при подключении хука трассы (PROGR-3), поэтому равенство страхует
    import-инвариант теста (tests/api/test_pipeline_graph.py, паттерн
    CERTIFIED_IDS), не взаимный импорт. Тот же инвариант связывает
    STAGES с apps/api/trace_events.py::KNOWN_STAGES (отложен PROGR-1).

Модель узла и статуса (§3): PipelineNodeState хранит статус из словаря
СВОЕГО класса стадии -- CheckStatus (StatusIcon.tsx) для проверочных
стадий, StageStatus (stages.ts, зеркало session_store.StageStatus) для
процессных. Приведение к одному словарю на уровне узла запрещено;
свёртка в 3 визуальных состояния карточки стадии -- отдельная чистая
функция fold_status_values/fold_stage_status (§12 п.10: любой единичный
warning/error делает карточку жёлтой -- заметность проблемы дороже
чистоты общей картины; skipped агрегатно не мешает пройденности).

Паспорт сознательно не входит в граф ни одним узлом (§2): он сквозная
панель, не остановка степпера с pass/fail-статусом.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

# Python-реестры узлов -- импорт напрямую (§2). Порядок импортов:
# платформенные реестры, не наоборот (риск-таблица plan_progress.md:
# циклические импорты исключены направлением зависимости
# pipeline_graph -> реестры; инвариант STAGES -- тестом).
from apps.api.model_readiness import MODELING_STAGE_IDS
from apps.api.routers.session import PREPROCESSING_CHECK_IDS
from validation.rule_resolver import CHECK_IDS as VALIDATION_STAGE_IDS

# ── §2: стадии и узлы ─────────────────────────────────────────────

STAGES: tuple[str, ...] = (
    "upload", "validation", "preprocessing", "eda", "modeling", "forecasting",
)

# Узлы Прогнозирования -- 4 типа события ForecastRun (§2 таблица,
# дословно spec_forecasting2.md §5.9).
FORECASTING_STAGE_IDS: tuple[str, ...] = (
    "forecast_generated", "forecast_compared",
    "forecast_sensitivity_computed", "forecast_exported",
)

# ── §12 п.2: общие JSON реестров (EDA + Загрузка, PROGR-13-A1) ─────

_EDA_JSON_PATH = (
    Path(__file__).resolve().parents[2]
    / "shared" / "pipeline_nodes" / "eda_checks.json"
)
_UPLOAD_JSON_PATH = (
    Path(__file__).resolve().parents[2]
    / "shared" / "pipeline_nodes" / "upload_stops.json"
)


def _load_pipeline_node_defs(
    path: Path, *, expected_stage: str, registry_name: str
) -> tuple[dict[str, str], ...]:
    """Общее ядро чтения общего JSON реестра узлов (§12 п.2;
    PROGR-13-A1 -- тот же паттерн для Загрузки).

    Отсутствие файла, битый JSON, пропуск обязательного ключа или
    дубликат id -- ошибка импорта, а не тихий деградировавший реестр:
    граф «Прогресса» не должен стартовать с частичной картиной стадий.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:  # pragma: no cover - защитная ветка
        raise ImportError(
            f"Общий реестр {registry_name} не найден: {path} (§12 п.2); "
            "файл обязателен для старта графа пайплайна"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ImportError(
            f"Общий реестр {registry_name} не парсится: {path}: {exc}"
        ) from exc
    declared_stage = str(raw.get("stage") or "")
    if declared_stage != expected_stage:
        raise ImportError(
            f"Реестр {path} объявляет stage={declared_stage!r}, "
            f"ожидалось {expected_stage!r}"
        )
    nodes_raw = raw.get("nodes")
    if not isinstance(nodes_raw, list) or not nodes_raw:
        raise ImportError(
            f"Реестр {path} не содержит непустого списка nodes"
        )
    defs: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in nodes_raw:
        node_id = str(entry.get("id") or "").strip()
        label = str(entry.get("label") or "").strip()
        description = str(entry.get("description") or "").strip()
        if not node_id or not label or not description:
            raise ImportError(
                f"Запись реестра {registry_name} без id/label/description: "
                f"{entry!r}"
            )
        if node_id in seen:
            raise ImportError(
                f"Дубликат id узла {registry_name} в реестре: {node_id!r}"
            )
        seen.add(node_id)
        defs.append({"id": node_id, "label": label, "description": description})
    return tuple(defs)


def _load_eda_check_defs(path: Path | None = None) -> tuple[dict[str, str], ...]:
    """Чтение общего JSON реестра EDA (fail-closed на старте модуля).

    path -- переопределение для тестов загрузчика; по умолчанию модульный
    путь _EDA_JSON_PATH. Контракт ошибок -- у общего ядра
    _load_pipeline_node_defs (PROGR-13-A1: тот же паттерн у Загрузки).
    """
    return _load_pipeline_node_defs(
        path or _EDA_JSON_PATH, expected_stage="eda", registry_name="EDA"
    )


def _load_upload_stop_defs(path: Path | None = None) -> tuple[dict[str, str], ...]:
    """Чтение общего JSON реестра остановок «Загрузки» (PROGR-13-A1,
    §12 п.2 -- тот же паттерн, что у EDA): fail-closed на старте модуля,
    path -- переопределение для тестов загрузчика."""
    return _load_pipeline_node_defs(
        path or _UPLOAD_JSON_PATH,
        expected_stage="upload",
        registry_name="Загрузки",
    )


EDA_CHECK_DEFS: tuple[dict[str, str], ...] = _load_eda_check_defs()

# Id остановок EDA -- из общего JSON (§12 п.2); синхронизация с .tsx
# застрахована тестами (test_eda_tsx_imports_shared_json и др.).
EDA_STAGE_IDS: tuple[str, ...] = tuple(d["id"] for d in EDA_CHECK_DEFS)

# Остановки «Загрузки» -- из общего JSON (PROGR-13-A1, §12 п.2);
# синхронизация с TsAnalysisUpload.tsx::STOPS застрахована тестами
# (test_upload_tsx_imports_shared_json и др.).
UPLOAD_STOP_DEFS: tuple[dict[str, str], ...] = _load_upload_stop_defs()

UPLOAD_STAGE_IDS: tuple[str, ...] = tuple(d["id"] for d in UPLOAD_STOP_DEFS)

STAGE_NODES: dict[str, tuple[str, ...]] = {
    # Общий JSON §12 п.2 (PROGR-13-A1) -- единственный источник id EDA
    # и остановок Загрузки (см. докстринг модуля).
    "upload": UPLOAD_STAGE_IDS,
    "validation": VALIDATION_STAGE_IDS,
    "preprocessing": PREPROCESSING_CHECK_IDS,
    "eda": EDA_STAGE_IDS,
    "modeling": MODELING_STAGE_IDS,
    "forecasting": FORECASTING_STAGE_IDS,
}

# Fail-closed самопроверка графа на импорте: структура реестра не может
# частично рассинхронизироваться незаметно.
if tuple(STAGE_NODES.keys()) != STAGES:  # pragma: no cover - защитная ветка
    raise ImportError(
        f"STAGE_NODES {list(STAGE_NODES)} расходится со STAGES {list(STAGES)}"
    )

TOTAL_NODE_COUNT: int = sum(len(nodes) for nodes in STAGE_NODES.values())


def iter_all_nodes() -> Iterator[tuple[str, str]]:
    """Итерация всех узлов графа парами (stage, node_id) в порядке §2."""
    for stage, nodes in STAGE_NODES.items():
        for node_id in nodes:
            yield stage, node_id


def is_known_node(stage: str, node_id: str) -> bool:
    """Валидность пары (stage, node_id): идентичность узла -- составной
    ключ, т.к. id вроде stationarity/regularity сознательно существуют
    в двух стадиях (свои проверки Предобработки и EDA)."""
    return node_id in STAGE_NODES.get(stage, ())


# ── §3: модель узла -- два словаря статусов, не один ──────────────

# CheckStatus (packages/ui/components/StatusIcon.tsx).
CHECK_STATUS_VALUES: tuple[str, ...] = (
    "done", "warning", "pending", "skipped", "running", "error",
)
# StageStatus (packages/ui/lib/stages.ts, зеркало session_store.StageStatus).
PROCESS_STATUS_VALUES: tuple[str, ...] = ("pending", "in_progress", "done")

# Проверочные стадии: каждый узел содержательно про отдельную
# проверку/коррекцию данных с исходом pass/fail/needs-attention (§3).
# Загрузка отнесена сюда по факту UI (UPLOAD-1): узел structure
# использует done/warning/pending -- подмножество CheckStatus; словарь
# StageStatus не выразил бы warning-состояние.
CHECK_STATUS_STAGES: tuple[str, ...] = (
    "upload", "validation", "preprocessing", "eda",
)
# Процессные стадии: узел про этап процесса, а не про диагностическую
# проверку (§3: Моделирование -- session.modeling_pipeline[stage],
# Прогнозирование -- по факту ForecastRun/trace_events).
PROCESS_STATUS_STAGES: tuple[str, ...] = ("modeling", "forecasting")

# mode -- auto/enabled/disabled, где применимо (§3: Валидация/Предобработка).
NODE_MODE_VALUES: tuple[str, ...] = ("auto", "enabled", "disabled")

# Стадии, узлам которых применим mode (§3): публичное имя -- канонический
# владелец классификации стадий этот модуль; потребители (node_status,
# PROGR-11) импортируют его, не держат свою копию пары.
MODE_STAGES: frozenset[str] = frozenset({"validation", "preprocessing"})
_STATUS_BY_STAGE: dict[str, frozenset[str]] = {
    stage: frozenset(CHECK_STATUS_VALUES) for stage in CHECK_STATUS_STAGES
} | {
    stage: frozenset(PROCESS_STATUS_VALUES) for stage in PROCESS_STATUS_STAGES
}


@dataclass(frozen=True)
class PipelineNodeState:
    """Состояние узла графа (spec_progress.md §3).

    status -- значение ИЗ словаря своего класса стадии
    (CheckStatus для проверочных, StageStatus для процессных);
    насильное приведение к одному словарю на уровне узла запрещено §3.
    Инварианты проверяются в __post_init__ -- в том числе при прямом
    конструировании, не только через фабрику (fail-closed).
    """

    stage: str
    node_id: str
    status: str = "pending"
    status_reason: str | None = None
    mode: str | None = None
    last_touched_at: str | None = None
    summary_count: int | None = None

    def __post_init__(self) -> None:
        if self.stage not in STAGES:
            raise ValueError(
                f"Неизвестная стадия узла: {self.stage!r}; "
                f"известные: {list(STAGES)}"
            )
        if self.node_id not in STAGE_NODES[self.stage]:
            raise ValueError(
                f"Неизвестный узел {self.node_id!r} стадии {self.stage!r}; "
                f"известные: {list(STAGE_NODES[self.stage])}"
            )
        allowed = _STATUS_BY_STAGE[self.stage]
        if self.status not in allowed:
            raise ValueError(
                f"Недопустимый статус {self.status!r} для стадии "
                f"{self.stage!r}; допустимые: {sorted(allowed)}"
            )
        if self.mode is not None:
            if self.stage not in MODE_STAGES:
                raise ValueError(
                    f"mode применим только к стадиям "
                    f"{list(MODE_STAGES)}, не к {self.stage!r}"
                )
            if self.mode not in NODE_MODE_VALUES:
                raise ValueError(
                    f"Недопустимый mode {self.mode!r}; "
                    f"допустимые: {list(NODE_MODE_VALUES)}"
                )
        if self.summary_count is not None and self.summary_count < 0:
            raise ValueError(
                f"summary_count -- число в правом бейдже узла, "
                f"не может быть отрицательным: {self.summary_count!r}"
            )


def make_node_state(
    stage: str,
    node_id: str,
    *,
    status: str = "pending",
    status_reason: str | None = None,
    mode: str | None = None,
    last_touched_at: str | None = None,
    summary_count: int | None = None,
) -> PipelineNodeState:
    """Фабрика узла с fail-closed гейтом (паттерн make_trace_event,
    PROGR-1): опечатка в stage/node_id/status не должна молча создать
    фантомный узел панели «Прогресс»."""
    return PipelineNodeState(
        stage=stage,
        node_id=node_id,
        status=status,
        status_reason=status_reason,
        mode=mode,
        last_touched_at=last_touched_at,
        summary_count=summary_count,
    )


# ── §3 + §12 п.10: свёртка в три визуальных состояния ─────────────

# Три визуальных состояния карточки стадии (§3): «пройдено» (зелёный
# лёгкий фон), «в работе / есть замечания» (жёлтый), «не начато»
# (нейтральный). Конкретика warning/error видна при разворачивании
# узла, на агрегате стадии она сознательно не различается (§3).
NODE_FOLD_PASSED = "passed"
NODE_FOLD_ATTENTION = "attention"
NODE_FOLD_NOT_STARTED = "not_started"

_VISUAL_STATES: frozenset[str] = frozenset(
    {NODE_FOLD_PASSED, NODE_FOLD_ATTENTION, NODE_FOLD_NOT_STARTED}
)

_KNOWN_NODE_STATUSES: frozenset[str] = frozenset(
    CHECK_STATUS_VALUES
) | frozenset(PROCESS_STATUS_VALUES)

_STARTED_BEYOND_DONE: frozenset[str] = frozenset(
    {"running", "in_progress"}
)


# ── AUDIT-C: реестр dependency scopes узлов (один реестр) ─────────

# Канонические scope-компоненты контекста расчёта (контракт
# docs/progress_audit_contract.md §3.4 -- УТВЕРЖДЕНО-AUDIT-0 (форма)):
#   data     -- контент данных (fingerprint файла + ревизия данных);
#   target   -- исследуемый признак;
#   temporal -- временная колонка/структура ряда.
# Имена совпадают с apps/api/data_context.py::SCOPE_* (единственный
# производитель компонентов); направленный импорт невозможен
# (data_context -> session_store, а этот модуль импортирует
# routers.session -- цикл), равенство страхует import-инвариант теста
# (паттерн STAGES).
CONTEXT_SCOPES: tuple[str, ...] = ("data", "target", "temporal")

# База стадии -- что инвалидирует ЛЮБОЙ узел стадии. Матрица на реальной
# семантике узлов (риск карточки AUDIT-C: «нельзя инвалидировать все узлы
# на любую настройку ЛИБО сохранять target-dependent done при смене
# цели»):
#   upload -- остановки чтения файла/картинки данных: data; узлы
#             render'а исследуемого признака -- +target; структура
#             (подтверждение даты) -- +temporal; график ведёт ряд по
#             временной оси -- все три;
#   validation -- проверки колонок/формы данных: data; регулярность
#             ряда -- +temporal; достаточность -- про ряд цели (+target).
#             Смена цели НЕ инвалидирует проверки типов/форматов/диапазонов:
#             данные не менялись (честная применимость сохраняется);
#   preprocessing -- преобразования ряда/фрейма: base все три; фреймовые
#             коррекции (пропуски/выбросы) и конфигурация масштабирования --
#             data-only (от цели не зависят), регулярность -- +temporal;
#   eda/modeling/forecasting -- исследования/решения/артефакты вычисляются
#             для ряда цели на временной оси текущих данных: все три
#             (совпадает с существующим централизованным инвалидированием:
#             set_target_column/set_date_column -> reset_passports ->
#             reset_modeling).
_STAGE_SCOPE_BASE: dict[str, frozenset[str]] = {
    "upload": frozenset({"data"}),
    "validation": frozenset({"data"}),
    "preprocessing": frozenset({"data", "target", "temporal"}),
    "eda": frozenset({"data", "target", "temporal"}),
    "modeling": frozenset({"data", "target", "temporal"}),
    "forecasting": frozenset({"data", "target", "temporal"}),
}

# Исключения узлов от базы стадии (создание fail-closed: исключение должно
# ссылаться на существующий узел своей стадии -- страхуется сборкой
# реестра ниже + тестом полноты).
_NODE_SCOPE_OVERRIDES: dict[str, dict[str, frozenset[str]]] = {
    "upload": {
        # График ведёт исследуемый признак по реальной временной оси.
        "chart": frozenset({"data", "target", "temporal"}),
        # Распределение выбранного числового признака (без временной оси).
        "distribution": frozenset({"data", "target"}),
        # Структура -- подтверждение даты/частоты: от цели не зависит.
        "structure": frozenset({"data", "temporal"}),
    },
    "validation": {
        # Регулярность -- про временной индекс ряда.
        "regularity": frozenset({"data", "temporal"}),
        # Достаточность -- про ряд цели (длина/частота для прогноза).
        "sufficiency": frozenset({"data", "target", "temporal"}),
    },
    "preprocessing": {
        # Фреймовые коррекции: контент колонок, от цели/даты не зависят.
        "missing": frozenset({"data"}),
        "outliers": frozenset({"data"}),
        # Регулярность -- про временной индекс.
        "regularity": frozenset({"data", "temporal"}),
        # Рецепт масштабирования -- конфигурация фрейма (fold-local fit
        # по X-колонкам), от цели не зависит.
        "scaling": frozenset({"data"}),
    },
}

# ПОЛНЫЙ реестр (stage -> node -> scopes): материализуется ОДИН раз,
# полнота страхуется тестом (каждая пара (stage, node) из STAGE_NODES
# имеет запись, сирот нет).
NODE_DEPENDENCY_SCOPES: dict[str, dict[str, frozenset[str]]] = {
    stage: {
        node_id: _NODE_SCOPE_OVERRIDES.get(stage, {}).get(node_id, base)
        for node_id in STAGE_NODES[stage]
    }
    for stage, base in _STAGE_SCOPE_BASE.items()
}


def node_dependency_scopes(stage: str, node_id: str) -> frozenset[str]:
    """Зависимости узла от компонент контекста (AUDIT-C, контракт §3.4:
    «dependency scopes узлов -- ОДИН реестр»; спека §8.2: «список
    зависимостей выводить из реестра узлов, а не разбрасывать reset по
    компонентам»).

    Fail-closed: неизвестная пара -- ValueError (опечатка не должна
    молча вернуть «нет зависимостей» = ложную вечную current)."""
    if stage not in STAGE_NODES:
        raise ValueError(
            f"Неизвестная стадия узла: {stage!r}; известные: {list(STAGES)}"
        )
    if node_id not in STAGE_NODES[stage]:
        raise ValueError(
            f"Неизвестный узел {node_id!r} стадии {stage!r}; "
            f"известные: {list(STAGE_NODES[stage])}"
        )
    return NODE_DEPENDENCY_SCOPES[stage][node_id]


# Вердикты применимости захваченного контекста к текущим данным
# (контракт §3.5: historical vs validity; план §8: «историческое
# достижение отдельно от validity»).
VALIDITY_CURRENT = "current"
VALIDITY_STALE = "stale"
VALIDITY_UNKNOWN = "unknown"


def node_context_validity(
    stage: str,
    node_id: str,
    captured: Mapping[str, Any] | None,
    current: Mapping[str, Any],
) -> str:
    """Применимость результата, захваченного в captured-контексте, к
    текущим данным узла (централизованная функция инвалидирования,
    план §6 п.6; фундамент I6 для AUDIT-3/5B/8).

    Правила:
      * captured отсутствует/нечитаем -- «unknown» (честная неполнота:
        старый факт без известного контекста НЕ выдаётся за current,
        план §8 AUDIT-5B);
      * у captured нет значения хотя бы одного нужного узлу scope --
        «unknown» (частичный контекст не может удостоверить current);
      * все нужные scope совпали -- «current»;
      * иначе -- «stale».

    Смена ТОЛЬКО цели оставляет data-only узел current (риск карточки:
    «нельзя инвалидировать все узлы на любую настройку»), а
    target-dependent узел -- stale («не сохранять target-dependent done
    при смене цели»). Исторические события при этом не стираются --
    verdict применимости, не удаление фактов.
    """
    scopes = node_dependency_scopes(stage, node_id)
    if not isinstance(captured, Mapping):
        return VALIDITY_UNKNOWN
    for scope in scopes:
        if scope not in captured:
            return VALIDITY_UNKNOWN
        if scope not in current:
            return VALIDITY_UNKNOWN
        if captured[scope] != current[scope]:
            return VALIDITY_STALE
    return VALIDITY_CURRENT


def fold_status_values(statuses: Iterable[str]) -> str:
    """Свёртка статусов узлов стадии в одно из трёх визуальных состояний
    (§3, точная таблица -- §12 п.10).

    Правила (в порядке приоритета):
      1. пусто -> «не начато»;
      2. ЛЮБОЙ warning/error -> «в работе / есть замечания» (жёлтый):
         для инструмента контроля качества данных пропущенная проблема
         (ложноотрицательное «всё зелёное») дороже лишнего жёлтого
         бейджа (§12 п.10);
      3. все done -> «пройдено»;
      4. done+skipped (есть хотя бы один done) -> «пройдено»: skipped --
         «не применимо/отключено аналитиком», агрегатно не является
         ни замечанием, ни незавершённой работой;
      5. есть started-признак (running/in_progress/done при наличии
         незавершённых) -> «в работе» (жёлтый);
      6. иначе (все pending либо смесь pending/skipped) -> «не начато».

    Неизвестное значение статуса -- ValueError (fail-closed), а не тихий
    нейтральный узел: опечатка источника данных не должна выглядеть
    как «чистая» стадия.
    """
    values = list(statuses)
    if not values:
        return NODE_FOLD_NOT_STARTED
    for status in values:
        if status not in _KNOWN_NODE_STATUSES:
            raise ValueError(
                f"Неизвестный статус узла: {status!r}; "
                f"известные: {sorted(_KNOWN_NODE_STATUSES)}"
            )
    if any(s in ("warning", "error") for s in values):
        return NODE_FOLD_ATTENTION
    if all(s == "done" for s in values):
        return NODE_FOLD_PASSED
    if any(s == "done" for s in values) and all(
        s in ("done", "skipped") for s in values
    ):
        # skipped агрегатно не мешает пройденности, но не заменяет её:
        # без хотя бы одного done стадия остаётся «не начатой».
        return NODE_FOLD_PASSED
    if any(s == "done" or s in _STARTED_BEYOND_DONE for s in values):
        return NODE_FOLD_ATTENTION
    return NODE_FOLD_NOT_STARTED


def fold_stage_status(nodes: Iterable[PipelineNodeState]) -> str:
    """Свёртка состояний узлов стадии (удобство поверх
    fold_status_values): метаданные узлов (reason/mode/count) на
    агрегат не влияют -- свёртка определена только статусами (§3:
    нормализация происходит на уровне рендера блок-схемы)."""
    return fold_status_values(node.status for node in nodes)
