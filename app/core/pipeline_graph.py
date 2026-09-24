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
  * Загрузка -- линейный флоу без CHECKS-массива: единственный узел
    structure_confirmed (§2);
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
from typing import Iterable, Iterator

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

# Единственный узел линейного флоу Загрузки (§2: структура ->
# target_column/date_column -> декомпозиция-бейджи; CHECKS-массива нет).
UPLOAD_STAGE_IDS: tuple[str, ...] = ("structure_confirmed",)

# Узлы Прогнозирования -- 4 типа события ForecastRun (§2 таблица,
# дословно spec_forecasting2.md §5.9).
FORECASTING_STAGE_IDS: tuple[str, ...] = (
    "forecast_generated", "forecast_compared",
    "forecast_sensitivity_computed", "forecast_exported",
)

# ── §12 п.2: общий JSON реестра EDA ───────────────────────────────

_EDA_JSON_PATH = (
    Path(__file__).resolve().parents[2]
    / "shared" / "pipeline_nodes" / "eda_checks.json"
)


def _load_eda_check_defs(path: Path | None = None) -> tuple[dict[str, str], ...]:
    """Чтение общего JSON реестра EDA (fail-closed на старте модуля).

    path -- переопределение для тестов загрузчика; по умолчанию модульный
    путь _EDA_JSON_PATH. Отсутствие файла, битый JSON, пропуск
    обязательного ключа или дубликат id -- ошибка импорта, а не тихий
    деградировавший реестр: граф «Прогресса» не должен стартовать с
    частичной картиной стадий.
    """
    path = path or _EDA_JSON_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:  # pragma: no cover - защитная ветка
        raise ImportError(
            f"Общий реестр EDA не найден: {path} (§12 п.2); "
            "файл обязателен для старта графа пайплайна"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ImportError(
            f"Общий реестр EDA не парсится: {path}: {exc}"
        ) from exc
    declared_stage = str(raw.get("stage") or "")
    if declared_stage != "eda":
        raise ImportError(
            f"Реестр {path} объявляет stage={declared_stage!r}, "
            "ожидалось 'eda'"
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
                f"Запись реестра EDA без id/label/description: {entry!r}"
            )
        if node_id in seen:
            raise ImportError(f"Дубликат id узла EDA в реестре: {node_id!r}")
        seen.add(node_id)
        defs.append({"id": node_id, "label": label, "description": description})
    return tuple(defs)


EDA_CHECK_DEFS: tuple[dict[str, str], ...] = _load_eda_check_defs()

# Id остановок EDA -- из общего JSON (§12 п.2); синхронизация с .tsx
# застрахована тестами (test_eda_tsx_imports_shared_json и др.).
EDA_STAGE_IDS: tuple[str, ...] = tuple(d["id"] for d in EDA_CHECK_DEFS)

STAGE_NODES: dict[str, tuple[str, ...]] = {
    "upload": UPLOAD_STAGE_IDS,
    "validation": VALIDATION_STAGE_IDS,
    "preprocessing": PREPROCESSING_CHECK_IDS,
    # Общий JSON §12 п.2 -- единственный источник id EDA (см. докстринг).
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
# Загрузка отнесена сюда по факту UI (UPLOAD-1): узел structure_confirmed
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

_MODE_STAGES: frozenset[str] = frozenset({"validation", "preprocessing"})
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
            if self.stage not in _MODE_STAGES:
                raise ValueError(
                    f"mode применим только к стадиям "
                    f"{list(_MODE_STAGES)}, не к {self.stage!r}"
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
