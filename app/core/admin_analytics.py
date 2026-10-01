# app/core/admin_analytics.py
"""Движок агрегатов Admin-панели и офлайн-потребителей (Task PROGR-8,
spec_progress.md §10 + §9, категория D). ЧИСТЫЙ модуль без HTTP --
паттерн run_report.py (PROGR-7): на входе словари канонических форм
(ResearchRun.to_dict / TraceEvent.to_dict / MentorObservation.to_dict),
на выходе иммутабельные модели; сериализация в HTTP -- ответственность
роутера (pydantic-схемы progress.py).

СОСТАВ ПАНЕЛИ (§10 дословно, агрегаты по research_runs/trace_events,
БЕЗ раскрытия содержимого конкретных датасетов пользователей):

  * активные/приостановленные/завершённые/брошенные запуски за период
    (period_days по created_at; all-time -- отдельный честный счётчик);
  * распределение времени по стадиям («где аналитики чаще всего
    застревают»): span first->last читаемого ts событий стадии внутри
    запуска; стадия измерима при >= 2 читаемых событиях (интервал
    между двумя точками); нечитаемые ts пропускаются (деградация,
    паттерн mentor_rules._parse_event_ts), не распределяются;
  * топ узлов с финальным статусом warning/error -- статусы выводятся
    derive_node_statuses из ЕДИНОГО движка app/core/node_status.py
    (Расхождение №1, PROGR-10: один движок для панели/Наставника/admin;
    фантомных узлов нет: is_known_node гейт);
  * частота срабатывания правил «Следующий шаг» (§7.1) -- по журналу
    наблюдений (obs_kind="next_step": ВЫДАННЫЕ рекомендации);
  * частота sanity-предупреждений (§7.2) ПО ПРАВИЛУ И ПО УЗЛУ --
    по журналу наблюдений (obs_kind="sanity_warning"; наблюдение без
    node_id учитывается по правилу, но не атрибутируется узлу);
  * Прогнозирование (§9: spec_forecasting2 §9.3 п.5): частоты
    model_id/horizon/alpha из payload forecast_generated.

Период (days) применяется ТОЛЬКО к счётчикам запусков (§10: «запуски
за период»); остальные агрегаты -- по накопленному корпусу (категория
D: ось времени/данных, «старт -- по накоплении данных, не гейтится
кодом»: пустой корпус даёт честные нули, а не заглушку).

БАНК КЕЙСОВ (§9, алгоритмическая эвристика отбора кандидатов):
run.status == "completed" + финальный бэктест-скор (последний
backtest_run; MAPE НИЖЕ порога -- лучше: честная инверсия формулировки
«скор выше порога» для lower-is-better метрики) + малое число
warning-узлов + малое число sanity-предупреждений («чистые» прохождения
без метаний). Отобранные run_id идут в ОФЛАЙН-процесс суммаризации
(LLM-джоба вне этого сервиса -- §9 дословно); без доказательства скора
кандидат не отбирается (no fabricated results).

Корпус одной платформы (§12 п.1) невелик: полное чтение журналов
приемлемо (тот же паттерн «журнал целиком», что R-1 PROGR-7);
SQL-агрегации Postgres -- зрелая оптимизация при росте корпуса.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from app.core.node_status import derive_node_statuses, event_to_dict

# Канонические статусы запусков (§5) -- ключи runs_by_status всегда
# присутствуют (ноль -- честное отсутствие, стабильный контракт ответа).
_RUN_STATUSES = ("active", "paused", "completed", "abandoned")

_PROBLEM_STATUSES = ("warning", "error")

_OBS_SANITY = "sanity_warning"
_OBS_NEXT_STEP = "next_step"


def _parse_ts(raw: Any) -> Optional[datetime]:
    """ISO-ts -> datetime (naive -- UTC). Нечитаемое -- None: деградация
    «элемент пропущен», не падение (паттерн mentor_rules._parse_event_ts)."""
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@dataclass(frozen=True)
class StageSpanStat:
    """Время по стадии (агрегат по запускам, минуты)."""

    stage: str
    runs_with_stage: int
    mean_minutes: float
    median_minutes: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "runs_with_stage": self.runs_with_stage,
            "mean_minutes": self.mean_minutes,
            "median_minutes": self.median_minutes,
        }


@dataclass(frozen=True)
class NodeProblemCount:
    """Узел с финальным статусом warning/error, посчитанный по запускам."""

    stage: str
    node_id: str
    status: str
    count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "node_id": self.node_id,
            "status": self.status,
            "count": self.count,
        }


@dataclass(frozen=True)
class RuleFrequency:
    """Частота правила: §7.1 (next_step) или §7.2 по правилу (sanity)."""

    rule_id: str
    stage: str
    count: int

    def to_dict(self) -> dict[str, Any]:
        return {"rule_id": self.rule_id, "stage": self.stage, "count": self.count}


@dataclass(frozen=True)
class SanityNodeFrequency:
    """Частота sanity-предупреждений §7.2 по узлу («по правилу и по узлу»)."""

    stage: str
    node_id: str
    count: int

    def to_dict(self) -> dict[str, Any]:
        return {"stage": self.stage, "node_id": self.node_id, "count": self.count}


@dataclass(frozen=True)
class ValueFrequency:
    """Частота значения (model_id / horizon / alpha Прогнозирования, §9)."""

    value: str
    count: int

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "count": self.count}


@dataclass(frozen=True)
class AdminOverviewModel:
    """Модель агрегатов §10 (сборка ответа -- pydantic-схема роутера)."""

    generated_at: str
    period_days: int
    runs_total_all_time: int
    runs_total_in_period: int
    runs_by_status: dict[str, int] = field(default_factory=dict)
    stage_time: list[StageSpanStat] = field(default_factory=list)
    top_problem_nodes: list[NodeProblemCount] = field(default_factory=list)
    next_step_frequency: list[RuleFrequency] = field(default_factory=list)
    sanity_by_rule: list[RuleFrequency] = field(default_factory=list)
    sanity_by_node: list[SanityNodeFrequency] = field(default_factory=list)
    forecasting_model_frequency: list[ValueFrequency] = field(default_factory=list)
    forecasting_horizon_frequency: list[ValueFrequency] = field(default_factory=list)
    forecasting_alpha_frequency: list[ValueFrequency] = field(default_factory=list)


@dataclass(frozen=True)
class CaseBankCandidate:
    """Кандидат банка кейсов (§9): run_id + доказательства отбора
    (evidence) для офлайн-суммаризации трассы."""

    run_id: str
    status: str
    dataset_name: str
    created_at: str
    backtest_mape: float
    warning_nodes: int
    sanity_warnings: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "dataset_name": self.dataset_name,
            "created_at": self.created_at,
            "backtest_mape": self.backtest_mape,
            "warning_nodes": self.warning_nodes,
            "sanity_warnings": self.sanity_warnings,
        }


# ── Внутренние сборщики ──────────────────────────────────────────────


def _runs_by_status(
    runs: list[dict[str, Any]], *, now: datetime, period_days: int
) -> tuple[int, int, dict[str, int]]:
    """(all_time, in_period, by_status). Запуск в периоде -- по ЧИТАЕМОМУ
    created_at в окне [now - period_days, now]; будущий created_at --
    тоже вне периода (период -- накопленное прошлое). Нечитаемый
    created_at -- в all-time, вне периода (нельзя атрибутировать окну --
    честно, не угадываем)."""
    window_start = now - timedelta(days=period_days)
    counts: dict[str, int] = {status: 0 for status in _RUN_STATUSES}
    in_period = 0
    for run in runs:
        created = _parse_ts(run.get("created_at"))
        if created is not None and window_start <= created <= now:
            in_period += 1
            status = str(run.get("status") or "")
            counts[status] = counts.get(status, 0) + 1
    return len(runs), in_period, counts


def _stage_time(
    runs: list[dict[str, Any]], events_by_run: Mapping[str, list[dict[str, Any]]]
) -> list[StageSpanStat]:
    """Span стадии внутри запуска: last_ts - first_ts по ЧИТАЕМЫМ ts;
    измеримо при >= 2 читаемых событиях. minutes -- float."""
    spans: dict[str, list[float]] = {}
    for run in runs:
        run_id = str(run.get("run_id") or "")
        by_stage: dict[str, list[datetime]] = {}
        for event in events_by_run.get(run_id, ()):
            data = event_to_dict(event)
            if data is None:
                continue
            ts = _parse_ts(data.get("ts"))
            if ts is None:
                continue
            by_stage.setdefault(str(data.get("stage") or ""), []).append(ts)
        for stage, moments in by_stage.items():
            if len(moments) < 2:
                continue  # интервал между двумя точками не измерим
            span = (max(moments) - min(moments)).total_seconds() / 60.0
            spans.setdefault(stage, []).append(span)
    result = [
        StageSpanStat(
            stage=stage,
            runs_with_stage=len(values),
            mean_minutes=statistics.fmean(values),
            median_minutes=float(statistics.median(values)),
        )
        for stage, values in spans.items()
    ]
    result.sort(key=lambda item: (-item.mean_minutes, item.stage))
    return result


def _top_problem_nodes(
    runs: list[dict[str, Any]],
    events_by_run: Mapping[str, list[dict[str, Any]]],
    *,
    top_limit: int,
) -> list[NodeProblemCount]:
    """Финальные статусы узлов по запускам (derive_node_statuses --
    последнее событие узла решает); warning/error считаются ПО ЗАПУСКАМ:
    узел, дважды warning в одном запуске, -- один запуск с проблемой."""
    counts: dict[tuple[str, str, str], int] = {}
    for run in runs:
        run_id = str(run.get("run_id") or "")
        statuses = derive_node_statuses(events_by_run.get(run_id, ()))
        for key, status in statuses.items():
            if status not in _PROBLEM_STATUSES:
                continue
            stage, _, node_id = key.partition("/")
            counts[(stage, node_id, status)] = counts.get((stage, node_id, status), 0) + 1
    ranked = sorted(
        counts.items(), key=lambda item: (-item[1], item[0][0], item[0][1], item[0][2])
    )
    return [
        NodeProblemCount(stage=stage, node_id=node_id, status=status, count=count)
        for (stage, node_id, status), count in ranked[:top_limit]
    ]


def _next_step_frequency(
    observations: list[dict[str, Any]], *, top_limit: int
) -> list[RuleFrequency]:
    counts: dict[tuple[str, str], int] = {}
    for obs in observations:
        if str(obs.get("obs_kind") or "") != _OBS_NEXT_STEP:
            continue
        key = (str(obs.get("rule_id") or ""), str(obs.get("stage") or ""))
        counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0][0]))
    return [
        RuleFrequency(rule_id=rule_id, stage=stage, count=count)
        for (rule_id, stage), count in ranked[:top_limit]
    ]


def _sanity_frequencies(
    observations: list[dict[str, Any]], *, top_limit: int
) -> tuple[list[RuleFrequency], list[SanityNodeFrequency]]:
    """§10 «по правилу и по узлу»: две проекции одного журнала.
    Наблюдение без node_id -- по правилу учитывается, по узлу нет
    (нельзя атрибутировать узлу не угадывая)."""
    by_rule: dict[tuple[str, str], int] = {}
    by_node: dict[tuple[str, str], int] = {}
    for obs in observations:
        if str(obs.get("obs_kind") or "") != _OBS_SANITY:
            continue
        rule_id = str(obs.get("rule_id") or "")
        stage = str(obs.get("stage") or "")
        rule_key = (rule_id, stage)
        by_rule[rule_key] = by_rule.get(rule_key, 0) + 1
        node_id = obs.get("node_id")
        if node_id:
            key = (stage, str(node_id))
            by_node[key] = by_node.get(key, 0) + 1
    rule_ranked = sorted(by_rule.items(), key=lambda item: (-item[1], item[0]))
    node_ranked = sorted(by_node.items(), key=lambda item: (-item[1], item[0]))
    return (
        [
            RuleFrequency(rule_id=rule_id, stage=stage, count=count)
            for (rule_id, stage), count in rule_ranked[:top_limit]
        ],
        [
            SanityNodeFrequency(stage=stage, node_id=node_id, count=count)
            for (stage, node_id), count in node_ranked[:top_limit]
        ],
    )


def _forecast_frequencies(
    runs: list[dict[str, Any]],
    events_by_run: Mapping[str, list[dict[str, Any]]],
    *,
    top_limit: int,
) -> tuple[list[ValueFrequency], list[ValueFrequency], list[ValueFrequency]]:
    """Частоты model_id/horizon/alpha по payload forecast_generated (§9:
    «какие модели/горизонты/alpha выбираются чаще»). Пустые значения
    payload честно пропускаются."""

    def _frequency(events: list[dict[str, Any]], key: str) -> list[ValueFrequency]:
        counts: dict[str, int] = {}
        for event in events:
            data = event_to_dict(event)
            if data is None or data.get("event_type") != "forecast_generated":
                continue
            raw = (data.get("payload") or {}).get(key)
            if raw is None or str(raw) == "":
                continue
            value = str(raw)
            counts[value] = counts.get(value, 0) + 1
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        return [ValueFrequency(value=value, count=count) for value, count in ranked[:top_limit]]

    corpus: list[dict[str, Any]] = []
    for run in runs:
        corpus.extend(events_by_run.get(str(run.get("run_id") or ""), ()))
    return (
        _frequency(corpus, "model_id"),
        _frequency(corpus, "horizon"),
        _frequency(corpus, "alpha"),
    )


# ── Публичный контракт ───────────────────────────────────────────────


def build_admin_overview(
    runs: list[dict[str, Any]],
    events_by_run: Mapping[str, list[dict[str, Any]]],
    observations: list[dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    period_days: int = 30,
    top_limit: int = 10,
) -> AdminOverviewModel:
    """Агрегаты §10 по корпусу (запуски/события/наблюдения -- словари
    канонических форм). Пустой корпус -- честные нули (не гейтится
    кодом, приёмка плана PROGR-8). now -- инъекция для детерминизма
    тестов (дефолт -- текущий момент UTC)."""
    moment = now or datetime.now(timezone.utc)
    total_all, total_period, by_status = _runs_by_status(
        runs, now=moment, period_days=period_days
    )
    sanity_by_rule, sanity_by_node = _sanity_frequencies(
        observations, top_limit=top_limit
    )
    models, horizons, alphas = _forecast_frequencies(
        runs, events_by_run, top_limit=top_limit
    )
    return AdminOverviewModel(
        generated_at=moment.isoformat(),
        period_days=period_days,
        runs_total_all_time=total_all,
        runs_total_in_period=total_period,
        runs_by_status=by_status,
        stage_time=_stage_time(runs, events_by_run),
        top_problem_nodes=_top_problem_nodes(
            runs, events_by_run, top_limit=top_limit
        ),
        next_step_frequency=_next_step_frequency(
            observations, top_limit=top_limit
        ),
        sanity_by_rule=sanity_by_rule,
        sanity_by_node=sanity_by_node,
        forecasting_model_frequency=models,
        forecasting_horizon_frequency=horizons,
        forecasting_alpha_frequency=alphas,
    )


def select_case_bank_candidates(
    runs: list[dict[str, Any]],
    events_by_run: Mapping[str, list[dict[str, Any]]],
    observations: list[dict[str, Any]],
    *,
    max_backtest_mape: float = 30.0,
    max_warning_nodes: int = 2,
    max_sanity_warnings: int = 2,
) -> list[CaseBankCandidate]:
    """Отбор кандидатов банка кейсов (§9, алгоритмическая эвристика):
    «чистые» прохождения -- completed + финальный бэктест-скор + малое
    число warning-узлов + малое число sanity-предупреждений.

    Финальный бэктест -- ПОСЛЕДНИЙ backtest_run запуска; его payload
    mape (аддитивное дополнение хука PROGR-8, dotted "metrics.mape")
    и есть доказательство скора. MAPE lower-is-better: кандидат --
    mape <= max_backtest_mape (честная инверсия формулировки §9
    «скор выше порога» для метрики, где меньше -- лучше). Без mape
    у финального бэктеста доказательства нет -- кандидат не отбирается
    (no fabricated results). Сортировка -- mape по возрастанию (лучшие
    первыми), тай-брейк run_id."""
    sanity_counts: dict[str, int] = {}
    for obs in observations:
        if str(obs.get("obs_kind") or "") == _OBS_SANITY:
            run_id = str(obs.get("run_id") or "")
            sanity_counts[run_id] = sanity_counts.get(run_id, 0) + 1

    candidates: list[CaseBankCandidate] = []
    for run in runs:
        if str(run.get("status") or "") != "completed":
            continue
        run_id = str(run.get("run_id") or "")
        events = events_by_run.get(run_id, ())
        final_backtest = next(
            (
                data
                for data in reversed(
                    [item for item in (  # хронология дописывания
                        event_to_dict(event) for event in events
                    ) if item is not None]
                )
                if data.get("event_type") == "backtest_run"
            ),
            None,
        )
        if final_backtest is None:
            continue
        raw_mape = (final_backtest.get("payload") or {}).get("mape")
        try:
            mape = float(raw_mape)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue  # скор не записан/нечитаем -- доказательства нет
        statuses = derive_node_statuses(events)
        warning_nodes = sum(
            1 for status in statuses.values() if status in _PROBLEM_STATUSES
        )
        sanity_warnings = sanity_counts.get(run_id, 0)
        if mape > max_backtest_mape:
            continue
        if warning_nodes > max_warning_nodes:
            continue
        if sanity_warnings > max_sanity_warnings:
            continue
        candidates.append(
            CaseBankCandidate(
                run_id=run_id,
                status="completed",
                dataset_name=str(run.get("dataset_name") or ""),
                created_at=str(run.get("created_at") or ""),
                backtest_mape=mape,
                warning_nodes=warning_nodes,
                sanity_warnings=sanity_warnings,
            )
        )
    candidates.sort(key=lambda item: (item.backtest_mape, item.run_id))
    return candidates
