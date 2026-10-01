# app/core/mentor_rules.py
"""«Наставник v1» -- правило-движок без LLM (spec_progress.md §7,
Task PROGR-6). Наставник решает ДВЕ разных по природе задачи, разведённые
на независимые потоки правил с разными триггерами (§7 дословно):

  * §7.1 «Следующий шаг» -- проактивная навигация по графу: что делать
    дальше, куда идти. Триггер on_demand; вызывается кнопкой «Наставник»
    панели; Наставник даёт ОДНУ рекомендацию за раз (первое сработавшее
    правило по сортировке (priority, rule_id), не заваливает советами).
  * §7.2 «Обнаружение ошибок в Мастере» -- реактивная проверка результата
    ТОЛЬКО ЧТО совершённого действия. Триггер on_correction_result;
    проверка встраивается в шаг «Предпросмотр» ДО применения (frontend
    строит CorrectionOutcomeSummary из preview-ответа Мастера и вызывает
    POST /v1/progress/mentor/sanity-check); возвращается ВЕСЬ список
    сработавших -- разные проблемы независимы.
  * Третий вид триггера on_demand_with_history -- правило «мечется»
    (thrashing): требует истории trace_events, а не одного preview-ответа;
    вызывается при открытии Наставника (не на каждый preview -- дорого
    гонять историю на каждый клик), предупреждение показывается в панели,
    а не инлайн в Мастере.

Принципы, унаследованные от спецификации и precedent-задач:

  * LLM НЕ участвует: единственная точка расширения -- MentorTextRenderer,
    с PROGR-12 (Расхождение №3) зафиксированный В КОДЕ как Protocol (§8),
    а не только на бумаге: дефолтная реализация FormatMentorTextRenderer
    -- просто .format() шаблона, без сети/модели. Условия правил
    возвращают ФАКТ срабатывания (MentorRuleFact: параметры шаблона +
    severity/suggested_action), текст рендерится движком ЧЕРЕЗ renderer
    ПОСЛЕ факта; подключение LLM позже = добавление реализации Protocol
    (LLMMentorTextRenderer за фиче-флагом, §8), НЕ ввод интерфейса;
    renderer не вызывается, если правило не сработало (LLM никогда
    не решает, есть ли ошибка). Правила возвращают уже вычисленный
    факт; LLM когда-нибудь будет только ПЕРЕФОРМУЛИРОВЫВАТЬ его.
  * «Не новая аналитика, а пересказ уже посчитанного»: правила §7.2 читают
    stats_before/stats_after/changed_count/rows_removed -- те же числа,
    что Мастер уже показал в «Прогнозе влияния на статистики».
  * Пороги -- НЕ хардкод: читаются из rules/mentor.yaml на ВЫЗОВ правила
    (§12 п.7, паттерн калибруемых констант платформы). Файл обязателен:
    fail-closed ImportError на старте модуля -- паттерн общего EDA-JSON
    (§12 п.2, app/core/pipeline_graph.py), Наставник не работает с
    частичной картиной порогов.
  * Fail-closed валидация правил на импорте: неизвестный trigger, пустой
    шаблон, дубликат rule_id -- ImportError (паттерн TRACE_ROUTES хука
    PROGR-3), опечатка не доходит до рантайма.

Направление зависимостей (риск-таблица plan_progress.md): правила -- чистые
функции над переданными данными; модуль читает граф пайплайна
(app/core/pipeline_graph.py) и публичный API единого движка статусов
(app/core/node_status.py, Расхождение №1 PROGR-10 -- движок «тип события ->
статус узла» живёт ТАМ, не здесь), хранилища сессий/запусков сюда НЕ
импортируются -- данные приносит роутер.
"""
from __future__ import annotations

import json
import string
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

import yaml

from app.core.node_status import event_to_dict
from app.core.pipeline_graph import STAGE_NODES

# ── Конфигурация порогов (§12 п.7) ───────────────────────────────────

MENTOR_CONFIG_PATH = Path(__file__).resolve().parents[2] / "rules" / "mentor.yaml"

# Обязательные секции/ключи -- контрактом файла, проверка загрузчиком
# (fail-closed: опечатка в YAML не должна тихо уронить порог в None).
_REQUIRED_CONFIG_KEYS: tuple[tuple[str, ...], ...] = (
    ("sanity", "over_aggressive", "std_collapse_factor"),
    ("sanity", "excessive_data_loss", "max_removed_share"),
    ("history", "thrashing", "window_minutes"),
    ("history", "thrashing", "distinct_strategies"),
)


def load_mentor_config(path: Path | None = None) -> dict[str, Any]:
    """Чтение порогов Наставника из rules/mentor.yaml (fail-closed).

    Отсутствие файла, битый YAML, пропущенная секция/ключ или
    нечисловой порог -- ImportError, а не тихая деградация: движение
    с порогом None вместо 0.2 предупреждало бы «всегда» либо «никогда».
    path -- переопределение для тестов; по умолчанию MENTOR_CONFIG_PATH.
    """
    path = path or MENTOR_CONFIG_PATH
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ImportError(
            f"Конфиг порогов Наставника не найден: {path} (§12 п.7); "
            "файл обязателен для старта правила-движка"
        ) from exc
    except yaml.YAMLError as exc:
        raise ImportError(
            f"Конфиг порогов Наставника не парсится: {path}: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise ImportError(f"Конфиг {path} не словарь YAML: {type(raw).__name__}")
    for keys in _REQUIRED_CONFIG_KEYS:
        node: Any = raw
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                raise ImportError(
                    f"Конфиг {path} не содержит {'.'.join(keys)!r} (§12 п.7)"
                )
            node = node[key]
        if isinstance(node, bool) or not isinstance(node, (int, float)):
            raise ImportError(
                f"Порог {'.'.join(keys)!r} должен быть числом, "
                f"получено {node!r}"
            )
    return raw


# Единый снимок конфига на процесс; правила читают его НА ВЫЗОВЕ
# (dict-lookup в теле функции), поэтому тесты/ops могут подменить
# singleton без перезагрузки модуля -- порог не захардкожен.
MENTOR_CONFIG: dict[str, Any] = load_mentor_config()


def _threshold(section: str, rule: str, key: str) -> float:
    value = MENTOR_CONFIG[section][rule][key]
    return float(value)  # загрузчик гарантирует число; bool исключён


# ── Модели данных (§7.1/§7.2) ────────────────────────────────────────

TRIGGER_ON_DEMAND = "on_demand"
TRIGGER_ON_CORRECTION_RESULT = "on_correction_result"
TRIGGER_ON_DEMAND_WITH_HISTORY = "on_demand_with_history"

KNOWN_TRIGGERS: frozenset[str] = frozenset(
    {TRIGGER_ON_DEMAND, TRIGGER_ON_CORRECTION_RESULT, TRIGGER_ON_DEMAND_WITH_HISTORY}
)

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"


@dataclass(frozen=True)
class MentorRule:
    """Правило Наставника (§7.1). condition -- чистая функция без
    побочных эффектов; сигнатура зависит от trigger:

      * on_demand: (statuses: Mapping[str, str]) -> bool --
        статусы узлов графа по ключу "stage/node_id";
      * on_correction_result: (outcome: CorrectionOutcomeSummary)
        -> MentorRuleFact | None -- факт срабатывания, БЕЗ текста
        (текст рендерится движком через MentorTextRenderer, §8);
      * on_demand_with_history: (events: list, *, now: datetime | None)
        -> MentorRuleFact | None -- недавние события трассы запуска
        (dict или TraceEvent).

    recommended_action -- deep-link «stage.node_id» (§7.1) или None
    (осознанно без deep-link -- «как решать», а не «куда идти»).
    explanation_template -- параметризованный текст (канон §7);
    с PROGR-12 обязателен для ВСЕХ триггеров: рендер §8 применим
    одинаково к §7.1 и §7.2, валидация fail-closed на импорте.
    """

    rule_id: str
    stage: str
    trigger: str
    priority: int
    explanation_template: str
    recommended_action: str | None = None
    condition: Callable[..., Any] | None = None


@dataclass(frozen=True)
class SanityWarning:
    """Предупреждение §7.2 (канон §7.2: severity -- info | warning)."""

    rule_id: str
    severity: str
    message: str
    suggested_action: str | None = None


@dataclass(frozen=True)
class CorrectionOutcomeSummary:
    """Нормализованная проекция preview-ответа ЛЮБОГО мастера (§7.2
    дословно) -- не новые вычисления, только переупаковка уже
    существующих полей ответа в общую форму, чтобы правила §7.2 не знали
    про специфику конкретного мастера. Строится клиентом
    (packages/ui/lib/mentor.ts) и валидируется роутером (fail-closed по
    паре (stage, node_id) -- паттерн make_node_state)."""

    stage: str
    node_id: str
    strategy: str = ""
    method: str | None = None
    affected_count_before: int = 0     # missing_count / outlier_count / total_violations
    changed_count: int = 0
    still_affected_count: int = 0      # still_missing / still_outliers / violations_after
    rows_before: int = 0
    rows_after: int = 0
    stats_before: Mapping[str, float | None] | None = None   # mean/std/median
    stats_after: Mapping[str, float | None] | None = None


@dataclass(frozen=True)
class MentorRecommendation:
    """Результат §7.1 -- одна рекомендация (первое сработавшее правило)."""

    rule_id: str
    stage: str
    message: str
    recommended_action: str | None = None


@dataclass(frozen=True)
class MentorRuleFact:
    """Вычисленный условием ФАКТ срабатывания правила -- без текста
    (§8: рендер -- отдельная ответственность Protocol). context --
    параметры шаблона + агрегированные факты, виденные условием (статусы
    узлов, исход коррекции, стратегии в окне; сырые данные ряда сюда
    НЕ попадают -- принцип §8 «LLM -- рендерер, не источник истины»);
    severity/suggested_action -- постоянные правила, движок переносит
    их в собираемое SanityWarning. §7.1-условия по-прежнему возвращают
    bool (канон §7: "(nodes) -> bool")."""

    context: dict[str, Any] = field(default_factory=dict)
    severity: str = SEVERITY_WARNING
    suggested_action: str | None = None


@runtime_checkable
class MentorTextRenderer(Protocol):
    """Единственная точка, где мог бы появиться LLM: ПЕРЕФОРМУЛИРОВКА
    уже вычисленного правило-движком факта (rule_id + параметры шаблона),
    НЕ вычисление самого факта/рекомендации/предупреждения. Дефолтная
    реализация -- просто .format() шаблона, без сети/модели. Применимо
    одинаково и к §7.1 (следующий шаг), и к §7.2 (sanity-предупреждения).
    (§8 spec_progress.md дословно; с PROGR-12 контракт зафиксирован
    в КОДЕ, а не только в докстринге -- Расхождение №3.)"""

    def render(self, rule: MentorRule, context: dict[str, Any]) -> str: ...


class FormatMentorTextRenderer:
    """Дефолтная реализация §8: просто .format() шаблона правила
    переданными параметрами, без сети/модели. Богатый контекст (лишние
    ключи -- агрегированные факты для будущего LLM) .format() игнорирует;
    пропущенный параметр шаблона -- KeyError (пары шаблон/контекст
    страхуют тесты движка и fail-closed валидация на импорте)."""

    def render(self, rule: MentorRule, context: dict[str, Any]) -> str:
        return rule.explanation_template.format(**context)


# Дефолтный рендерер процесса; evaluate_* принимают renderer параметром
# -- подключение LLM позже = передача LLMMentorTextRenderer(MentorTextRenderer)
# за фиче-флагом (§8), правка движка и точек вызова не требуется.
DEFAULT_TEXT_RENDERER: MentorTextRenderer = FormatMentorTextRenderer()


# ── Правила §7.2 (on_correction_result) ──────────────────────────────

_NO_EFFECT_TEXT = "Выбранная стратегия не изменила ни одного значения."
_NO_EFFECT_ACTION = (
    "Проверьте параметр/порог метода или попробуйте другой метод обнаружения."
)


def rule_no_effect(outcome: CorrectionOutcomeSummary) -> MentorRuleFact | None:
    """Стратегия выбрана, но по факту ничего не изменила -- типичный
    признак: порог/метод слишком мягкий, либо выборка слишком мала
    (§7.2 дословно). Возвращает ФАКТ срабатывания (§8): текст рендерится
    движком через MentorTextRenderer из шаблона правила."""
    if outcome.affected_count_before > 0 and outcome.changed_count == 0:
        return MentorRuleFact(
            context={
                "affected_count_before": outcome.affected_count_before,
                "changed_count": outcome.changed_count,
            },
            severity=SEVERITY_WARNING,
            suggested_action=_NO_EFFECT_ACTION,
        )
    return None


_OVER_AGGRESSIVE_ACTION = (
    "Рассмотрите менее жёсткую стратегию (например, флаг вместо замены) "
    "или уточните порог метода."
)


def rule_over_aggressive(outcome: CorrectionOutcomeSummary) -> MentorRuleFact | None:
    """Стандартное отклонение после исправления схлопнулось намного
    сильнее, чем можно объяснить долей затронутых значений -- признак
    переглаживания/слишком грубой стратегии (напр. замена медианой
    большой доли выборки) (§7.2 дословно). Порог -- из конфига
    (std_collapse_factor, стартово 0.2 == «более чем в 5 раз»). ФАКТ
    без текста (§8): шаблон правила с подстановкой {times} рендерится
    движком через MentorTextRenderer."""
    if not (outcome.stats_before and outcome.stats_after):
        return None
    std_before = outcome.stats_before.get("std")
    std_after = outcome.stats_after.get("std")
    if std_before and std_after is not None:
        factor = _threshold("sanity", "over_aggressive", "std_collapse_factor")
        if std_after < std_before * factor:
            times = max(round(1 / factor), 1) if factor > 0 else 0
            return MentorRuleFact(
                context={
                    "times": times,
                    "std_before": std_before,
                    "std_after": std_after,
                },
                severity=SEVERITY_WARNING,
                suggested_action=_OVER_AGGRESSIVE_ACTION,
            )
    return None


_EXCESSIVE_LOSS_ACTION = (
    "Проверьте, не завышен ли порог метода, и не задета ли колонка, "
    "которую вы не собирались исправлять."
)


def rule_excessive_data_loss(outcome: CorrectionOutcomeSummary) -> MentorRuleFact | None:
    """drop_rows/ресемплирование удалило значительную долю датасета --
    типичный признак слишком узкого порога или ошибочно выбранной
    колонки (§7.2 дословно). Порог -- из конфига (max_removed_share,
    стартово 0.3). ФАКТ без текста (§8): шаблон с подстановкой
    {removed_share} рендерится движком через MentorTextRenderer."""
    if outcome.rows_before == 0:
        return None
    max_share = _threshold("sanity", "excessive_data_loss", "max_removed_share")
    # Доля как (before-after)/before, а не 1 - after/before: разность
    # float-ов (1 - 0.7 == 0.30000000000000004) рвала границу «ровно
    # max_share -- тишина»; одно деление целых даёт точный boundary.
    removed_share = (outcome.rows_before - outcome.rows_after) / outcome.rows_before
    if outcome.strategy == "drop_rows" and removed_share > max_share:
        return MentorRuleFact(
            context={
                "removed_share": removed_share,
                "rows_before": outcome.rows_before,
                "rows_after": outcome.rows_after,
            },
            severity=SEVERITY_WARNING,
            suggested_action=_EXCESSIVE_LOSS_ACTION,
        )
    return None


# ── Правило «мечется» (on_demand_with_history) ───────────────────────

_THRASHING_TEXT = (
    "На этой остановке опробовано несколько разных стратегий подряд "
    "без применения ни одной. Если не уверены в выборе — посмотрите "
    "раздел «Оценка методологии» в «Метрики и алгоритм» этой остановки, "
    "или зафиксируйте промежуточный результат чекпоинтом и продолжите позже."
)


def _parse_event_ts(raw: Any) -> datetime | None:
    """ISO-ts события; naive -- UTC (паттерн trace_hook._throttled);
    нечитаемое -- None (деградация: событие вне окна, не 500)."""
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def rule_thrashing(
    events: list[Any], *, now: datetime | None = None
) -> MentorRuleFact | None:
    """«Мечется» (§7.2): один и тот же узел за короткое окно многократно
    исправляется чередующимися стратегиями без итогового применения --
    паттерн «аналитик пробует всё подряд». Требует истории trace_events
    (триггер on_demand_with_history), а не одного preview-ответа;
   recommended_action осознанно None -- это «как решать», а не «куда идти».

    Окно (window_minutes, стартово 10) и число разных стратегий
    (distinct_strategies, стартово 3) -- из конфига §12 п.7. Применённая
    коррекция (correction_applied в окне) снимает предупреждение:
    выбор сделан. События с нечитаемым ts в окно не попадают.
    ФАКТ без текста (§8): статичный шаблон правила рендерится движком
    через MentorTextRenderer; контекст несёт агрегированные факты окна
    (список стратегий -- для будущего LLM-рендера).
    """
    cfg = MENTOR_CONFIG["history"]["thrashing"]
    window_minutes = float(cfg["window_minutes"])
    distinct_needed = int(cfg["distinct_strategies"])
    current = now or datetime.now(timezone.utc)
    window_start = current - timedelta(minutes=window_minutes)
    strategies: list[str] = []
    has_apply = False
    for event in events:
        data = event_to_dict(event)
        if data is None:
            continue
        if data.get("event_type") == "correction_applied":
            ts = _parse_event_ts(data.get("ts"))
            if ts is not None and ts >= window_start:
                has_apply = True
            continue
        if data.get("event_type") != "correction_previewed":
            continue
        ts = _parse_event_ts(data.get("ts"))
        if ts is None or ts < window_start:
            continue
        strategy = (data.get("payload") or {}).get("strategy")
        if isinstance(strategy, str) and strategy and strategy not in strategies:
            strategies.append(strategy)
    if len(strategies) >= distinct_needed and not has_apply:
        return MentorRuleFact(
            context={
                "strategies": list(strategies),
                "window_minutes": window_minutes,
                "distinct_strategies": distinct_needed,
            },
            severity=SEVERITY_INFO,
            suggested_action=None,
        )
    return None


# ── Правила §7.1 (on_demand): «Следующий шаг» ────────────────────────

# Сортировка: МЕНЬШИЙ priority -- выше срочность (сначала сработавшее
# правило с min (priority, rule_id)); троттлинг-константы хука используют
# тот же стиль «число-приоритет», конфликтов направленности нет.


def _status(statuses: Mapping[str, str], stage: str, node_id: str) -> str:
    return statuses.get(f"{stage}/{node_id}", "pending")


def _regularity_before_decomposition(statuses: Mapping[str, str]) -> bool:
    return (
        _status(statuses, "preprocessing", "regularity") == "warning"
        and _status(statuses, "preprocessing", "decomposition") in ("pending", "skipped")
    )


def _stationarity_before_modeling(statuses: Mapping[str, str]) -> bool:
    return _status(statuses, "preprocessing", "stationarity") == "warning"


def _missing_attention(statuses: Mapping[str, str]) -> bool:
    return _status(statuses, "preprocessing", "missing") == "warning"


def _outliers_attention(statuses: Mapping[str, str]) -> bool:
    return _status(statuses, "preprocessing", "outliers") == "warning"


def _selected_without_backtest(statuses: Mapping[str, str]) -> bool:
    return _status(statuses, "modeling", "selection") == "done" and _status(
        statuses, "modeling", "backtest"
    ) in ("pending", "skipped")


def _candidates_without_selection(statuses: Mapping[str, str]) -> bool:
    return _status(statuses, "modeling", "backtest") == "done" and _status(
        statuses, "modeling", "selection"
    ) in ("pending", "skipped")


def _sufficiency_attention(statuses: Mapping[str, str]) -> bool:
    return _status(statuses, "validation", "sufficiency") == "warning"


def _forecast_not_compared(statuses: Mapping[str, str]) -> bool:
    return _status(
        statuses, "forecasting", "forecast_generated"
    ) == "done" and _status(statuses, "forecasting", "forecast_compared") in (
        "pending",
        "skipped",
    )


NEXT_STEP_RULES: tuple[MentorRule, ...] = (
    # Канонический пример §7.1: STL/спектр требуют равномерной сетки дат.
    MentorRule(
        rule_id="regularity_before_decomposition",
        stage="preprocessing",
        trigger=TRIGGER_ON_DEMAND,
        priority=10,
        explanation_template=(
            "В ряде остались нарушения регулярности временного шага. "
            "STL-декомпозиция и спектральный анализ требуют равномерной "
            "сетки дат — рекомендуем сначала исправить регулярность."
        ),
        recommended_action="preprocessing.regularity",
        condition=_regularity_before_decomposition,
    ),
    # Категория C §11: правило включено сразу; данные появляются по мере
    # работы Прогнозирования без изменений в коде Прогресса (§11 дословно).
    MentorRule(
        rule_id="forecast_not_compared_before_export",
        stage="forecasting",
        trigger=TRIGGER_ON_DEMAND,
        priority=10,
        explanation_template=(
            "Прогноз построен, но не сравнивался с альтернативными "
            "моделями — рассмотрите сравнение перед экспортом."
        ),
        recommended_action="forecasting.compare",
        condition=_forecast_not_compared,
    ),
    # Этап 2 §11: базовые правила Моделирования на 11 существующих узлах.
    MentorRule(
        rule_id="preprocessing_stationarity_before_modeling",
        stage="preprocessing",
        trigger=TRIGGER_ON_DEMAND,
        priority=15,
        explanation_template=(
            "Ряд нестационарен — большинство моделей требуют "
            "стационарности или явных преобразований. Рекомендуем пройти "
            "остановку «Стационарность ряда» до моделирования."
        ),
        recommended_action="preprocessing.stationarity",
        condition=_stationarity_before_modeling,
    ),
    MentorRule(
        rule_id="modeling_selected_without_backtest",
        stage="modeling",
        trigger=TRIGGER_ON_DEMAND,
        priority=20,
        explanation_template=(
            "Модель выбрана, но бэктест не запускался — качество выбора "
            "не подтверждено на скользящем бэктесте. Рекомендуем запустить "
            "бэктест до построения прогноза."
        ),
        recommended_action="modeling.backtest",
        condition=_selected_without_backtest,
    ),
    MentorRule(
        rule_id="modeling_candidates_without_selection",
        stage="modeling",
        trigger=TRIGGER_ON_DEMAND,
        priority=20,
        explanation_template=(
            "Кандидаты прошли бэктест, но модель ещё не выбрана — "
            "зафиксируйте выбор, чтобы прогноз строился по "
            "подтверждённой модели."
        ),
        recommended_action="modeling.selection",
        condition=_candidates_without_selection,
    ),
    MentorRule(
        rule_id="preprocessing_missing_attention",
        stage="preprocessing",
        trigger=TRIGGER_ON_DEMAND,
        priority=30,
        explanation_template=(
            "В данных остались пропуски — заполните или удалите их, "
            "чтобы не искажать статистики и качество моделей."
        ),
        recommended_action="preprocessing.missing",
        condition=_missing_attention,
    ),
    MentorRule(
        rule_id="preprocessing_outliers_attention",
        stage="preprocessing",
        trigger=TRIGGER_ON_DEMAND,
        priority=30,
        explanation_template=(
            "Обнаружены выбросы — рассмотрите обработку до моделирования: "
            "они смещают среднее, дисперсию и оценки качества."
        ),
        recommended_action="preprocessing.outliers",
        condition=_outliers_attention,
    ),
    MentorRule(
        rule_id="validation_sufficiency_attention",
        stage="validation",
        trigger=TRIGGER_ON_DEMAND,
        priority=40,
        explanation_template=(
            "Наблюдений недостаточно для устойчивного моделирования — "
            "рассмотрите сбор дополнительных данных или снижение "
            "горизонта выводов."
        ),
        recommended_action="validation.sufficiency",
        condition=_sufficiency_attention,
    ),
)


def evaluate_next_step(
    statuses: Mapping[str, str],
    *,
    renderer: MentorTextRenderer | None = None,
) -> MentorRecommendation | None:
    """§7.1: прогон состояния графа через отсортированный по (priority,
    rule_id) список on_demand-правил, первое сработавшее -- ОДНА
    рекомендация за раз (не весь список, §7.1 дословно). Текст --
    renderer.render ПОСЛЕ факта (§8); контекст несёт агрегированные
    факты (статусы узлов). renderer=None -- дефолтный
    FormatMentorTextRenderer; подключение LLM -- передачей реализации
    Protocol, без правки движка."""
    text_renderer = renderer or DEFAULT_TEXT_RENDERER
    for rule in sorted(NEXT_STEP_RULES, key=lambda item: (item.priority, item.rule_id)):
        condition = rule.condition
        if condition is not None and condition(statuses):
            return MentorRecommendation(
                rule_id=rule.rule_id,
                stage=rule.stage,
                message=text_renderer.render(rule, {"statuses": dict(statuses)}),
                recommended_action=rule.recommended_action,
            )
    return None


# ── §7.2: полный список sanity-предупреждений ────────────────────────

SANITY_RULES: tuple[MentorRule, ...] = (
    MentorRule(
        rule_id="no_effect",
        stage="preprocessing",
        trigger=TRIGGER_ON_CORRECTION_RESULT,
        priority=10,
        explanation_template=_NO_EFFECT_TEXT,
        recommended_action=None,
        condition=rule_no_effect,
    ),
    MentorRule(
        rule_id="over_aggressive",
        stage="preprocessing",
        trigger=TRIGGER_ON_CORRECTION_RESULT,
        priority=20,
        explanation_template=(
            "После исправления стандартное отклонение упало более чем "
            "в {times} раз — возможно, стратегия слишком агрессивна "
            "для этой доли данных."
        ),
        recommended_action=None,
        condition=rule_over_aggressive,
    ),
    MentorRule(
        rule_id="excessive_data_loss",
        stage="preprocessing",
        trigger=TRIGGER_ON_CORRECTION_RESULT,
        priority=30,
        explanation_template="Стратегия удалит {removed_share:.0%} строк датасета.",
        recommended_action=None,
        condition=rule_excessive_data_loss,
    ),
)

HISTORY_RULES: tuple[MentorRule, ...] = (
    MentorRule(
        rule_id="thrashing_detected",
        stage="preprocessing",  # или любая (§7.2)
        trigger=TRIGGER_ON_DEMAND_WITH_HISTORY,
        priority=5,
        explanation_template=_THRASHING_TEXT,
        recommended_action=None,  # осознанно без deep-link (§7.2)
        condition=rule_thrashing,
    ),
)


def evaluate_sanity(
    outcome: CorrectionOutcomeSummary,
    *,
    renderer: MentorTextRenderer | None = None,
) -> list[SanityWarning]:
    """§7.2: прогон через ВСЕ on_correction_result-правила (в отличие от
    §7.1 возвращается весь список -- разные проблемы независимы и не
    взаимоисключающи). Порядок -- реестр SANITY_RULES (стабилен для UI).
    Текст предупреждения -- renderer.render ПОСЛЕ факта (§8): условие
    возвращает MentorRuleFact (severity/suggested_action/параметры
    шаблона), message собирает движок ЧЕРЕЗ Protocol; renderer не
    вызывается для не сработавших правил."""
    text_renderer = renderer or DEFAULT_TEXT_RENDERER
    warnings: list[SanityWarning] = []
    for rule in SANITY_RULES:
        condition = rule.condition
        if condition is None:
            continue
        fact = condition(outcome)
        if fact is not None:
            warnings.append(
                SanityWarning(
                    rule_id=rule.rule_id,
                    severity=fact.severity,
                    message=text_renderer.render(rule, fact.context),
                    suggested_action=fact.suggested_action,
                )
            )
    return warnings


def evaluate_history_warnings(
    events: list[Any],
    *,
    now: datetime | None = None,
    renderer: MentorTextRenderer | None = None,
) -> list[SanityWarning]:
    """on_demand_with_history-правила: при открытии Наставника (не на
    каждый preview) по последним событиям запуска (§7.2 дословно).
    Текст -- renderer.render ПОСЛЕ факта (§8), как в evaluate_sanity."""
    text_renderer = renderer or DEFAULT_TEXT_RENDERER
    warnings: list[SanityWarning] = []
    for rule in HISTORY_RULES:
        condition = rule.condition
        if condition is None:
            continue
        fact = condition(events, now=now) if now else condition(events)
        if fact is not None:
            warnings.append(
                SanityWarning(
                    rule_id=rule.rule_id,
                    severity=fact.severity,
                    message=text_renderer.render(rule, fact.context),
                    suggested_action=fact.suggested_action,
                )
            )
    return warnings


# ── Краткая сводка стадии для ответа next-step (§7.1) ────────────────
# Движок статусов (derive_node_statuses) с PROGR-10 живёт в
# app/core/node_status.py (единый движок трёх потребителей); здесь
# осталась только агрегация готовых статусов по узлам стадии.


def stage_node_summary(stage: str, statuses: Mapping[str, str]) -> dict[str, Any]:
    """Краткая сводка стадии для ответа next-step (§7.1: «краткая сводка
    уже полученных выводов -- агрегация по узлам той же стадии»).
    Возвращает факты узлов (id + статус), done/warning-счётчики и total --
    человекочитаемые метки узлов остаются на фронте (NODE_LABELS)."""
    nodes = STAGE_NODES.get(stage, ())
    facts: list[dict[str, str]] = []
    done_count = 0
    warning_nodes = 0
    for node_id in nodes:
        status = statuses.get(f"{stage}/{node_id}", "pending")
        facts.append({"node_id": node_id, "status": status})
        if status == "done":
            done_count += 1
        if status in ("warning", "error"):
            warning_nodes += 1
    return {
        "stage": stage,
        "total_nodes": len(nodes),
        "done_count": done_count,
        "warning_nodes": warning_nodes,
        "nodes": facts,
    }


# ── Пояснение текущей фазы (§7.1: шаблон по последнему активному stage) ──

PHASE_TEXT_TEMPLATES: dict[str, str] = {
    "upload": (
        "Исследование на этапе «Загрузка»: подтвердите структуру данных "
        "и целевой признак, чтобы пошли проверки качества."
    ),
    "validation": (
        "Идёт этап «Валидация»: проверки качества данных ищут типовые "
        "проблемы -- типы, диапазоны, пропуски, регулярность шага."
    ),
    "preprocessing": (
        "Идёт этап «Предобработка»: мастера исправлений приводят ряд "
        "к виду, пригодному для моделирования и прогнозирования."
    ),
    "eda": (
        "Идёт этап «Разведочный EDA»: профиль и сезонность помогают "
        "понять структуру ряда до выбора моделей."
    ),
    "modeling": (
        "Идёт этап «Моделирование»: от выбора задачи к бэктесту "
        "кандидатов и фиксации итоговой модели."
    ),
    "forecasting": (
        "Идёт этап «Прогнозирование»: построение, сравнение и экспорт "
        "прогноза по выбранной модели."
    ),
}

_PHASE_TEXT_FALLBACK = (
    "Исследование идёт по графу пайплайна; откройте панель «Прогресс», "
    "чтобы увидеть блок-схему стадий и трассу решений."
)


def phase_text(stage: str) -> str:
    """Текст пояснения текущей фазы (§7.1). Неизвестная стадия -- честный
    нейтральный текст (fail-safe), не пустая строка."""
    return PHASE_TEXT_TEMPLATES.get(stage, _PHASE_TEXT_FALLBACK)


def validate_explanation_template(rule: MentorRule) -> None:
    """Fail-closed валидация шаблона объяснения (§8, PROGR-12): шаблон
    обязателен для ВСЕХ триггеров -- рендер применим одинаково к §7.1
    и §7.2; битая подстановка (незакрытая {) -- ImportError на импорте,
    паттерн TRACE_ROUTES PROGR-3: опечатка не доходит до рантайма."""
    if not rule.explanation_template:
        raise ImportError(f"Правило {rule.rule_id!r} без explanation_template")
    try:
        list(string.Formatter().parse(rule.explanation_template))
    except ValueError as exc:
        raise ImportError(
            f"Правило {rule.rule_id!r}: битый шаблон объяснения ({exc})"
        ) from exc


# ── Fail-closed самопроверка реестра на импорте ──────────────────────

# (паттерн TRACE_ROUTES PROGR-3: невалидное правило -- ImportError на
# импорте модуля, опечатка не доходит до рантайма).

_seen_rule_ids: set[str] = set()
for _rule in (*NEXT_STEP_RULES, *SANITY_RULES, *HISTORY_RULES):
    if _rule.rule_id in _seen_rule_ids:
        raise ImportError(f"Дубликат rule_id в реестре Наставника: {_rule.rule_id!r}")
    _seen_rule_ids.add(_rule.rule_id)
    if _rule.trigger not in KNOWN_TRIGGERS:
        raise ImportError(
            f"Правило {_rule.rule_id!r}: неизвестный trigger {_rule.trigger!r}"
        )
    if _rule.trigger == TRIGGER_ON_DEMAND and _rule.condition is None:
        raise ImportError(
            f"on_demand-правило {_rule.rule_id!r} без condition -- "
            "ошибка таблицы правил Наставника"
        )
    # §8 (PROGR-12): шаблон обязателен для ВСЕХ триггеров + битая
    # подстановка -- ImportError (раньше исключение делалось для
    # on_correction_result; рендер теперь един для §7.1/§7.2).
    validate_explanation_template(_rule)
