# apps/api/progress_projection.py
"""Единая полная проекция «Прогресса» и watermark (задача AUDIT-5B,
plan_progress_audit.md §8; контракт docs/progress_audit_contract.md,
инварианты I9/I10 -- аддендум v0.6-5B).

ПРОБЛЕМА (F06/F08/F11, P11/P12/P17): панель выводила состояние из
внутрисессионного хвоста (слой 1, кап 1000), Наставник и отчёт -- из
полного ledger слоя 2: один и тот же корпус давал разные состояния
(P11: длинное исследование теряло ранний прогресс и честное начало);
порядок корпуса у потребителей различался (отчёт -- ts-сортировка,
панель -- канонический порядок, P12); проекция не несла ни позиции
истории (watermark), ни происхождения своих полей.

РЕШЕНИЕ -- один читатель истории для всех потребителей:

  * канонический корпус: canonical_corpus(*sources) -- слияние
    источников (ledger слоя 2 приоритетен, затем слой 1, затем
    артефакты Прогнозирования) с дедупликацией строго по event_id
    (AUDIT-S) и ЕДИНЫМ каноническим порядком (§3.3: sequence, иначе
    стабильный ts-порядок);
  * ProjectionSnapshot -- снимок проекции: node/stage состояния
    (ЕДИНЫЙ редьюсер NodeStateFold из app/core/node_status.py --
    вторая реализации семантики запрещена), доказательства полей
    (source-ссылки/validity/evidence_level -- I10), watermark
    (позиция корпуса = число фактов канонического порядка),
    last_sequence, started_at запуска (run.created_at, НЕ первое
    событие уцелевшего хвоста -- P11), контекст запуска, счётчик
    диагностических аномалий, флаг полноты (PR-8: хвост без слоя 2
    честно помечен session_tail, не выдаётся за полную историю);
  * checkpoint + tail: snapshot сериализуем (to_dict/from_dict --
    checkpoint-состояние fold внутри); advance_projection достраивает
    состояние ХВОСТОМ за позицию base без повторного прогона
    префикса; эквивалентность «replay полного ledger ==
    snapshot + tail» страхуют оракулы (нагрузочный корпус 1500
    событий > 2 капов, расщепления в нескольких позициях, restart);
  * read-after-watermark (план §8 п.7): build/advance с
    min_watermark поднимают ProjectionPendingError, если корпус не
    дошёл до заданной позиции -- consumer видит snapshot не раньше
    позиции либо честное projection_pending; HTTP-форма -- 409
    (routers/progress.py::get_progress_trace).

Границы (осознанные, по плану §8 «Риск»): полное чтение ledger на
каждый GET -- контрольный эталон и текущее поведение читающих
эндпоинтов; checkpoint/watermark-механика (сериализуемый снапшот +
advance + min_watermark) поставлена и доказана тестами как носитель
контракта, подключение персистентного кэша снапшотов к эндпоинтам --
с AUDIT-6B (доставка/recovery); валидность -- уровень context_id
(грубее scope-сверки node_context_validity: у события есть только
идентификатор контекста, компоненты -- уровень AUDIT-8).
"""
from __future__ import annotations

from typing import Any, Mapping

from app.core.node_status import (
    NodeStateFold,
    derive_stage_states,
    event_to_dict,
)
from app.core.pipeline_graph import (
    VALIDITY_CURRENT,
    VALIDITY_STALE,
    VALIDITY_UNKNOWN,
)
from app.core.pipeline_graph import (
    event_context_validity as _event_context_validity,
)
from apps.api.trace_events import merge_canonical_events

# Вердикты применимости -- канон pipeline_graph (VALIDITY_*).

__all__ = [
    "ProjectionPendingError",
    "ProjectionSnapshot",
    "build_projection",
    "advance_projection",
    "canonical_corpus",
    "event_context_validity",
    "VALIDITY_CURRENT",
    "VALIDITY_STALE",
    "VALIDITY_UNKNOWN",
]


class ProjectionPendingError(Exception):
    """Read-after-watermark (план §8 п.7): корпус не дошёл до заданной
    позиции -- snapshot не отдаётся, consumer получает честное
    projection_pending (HTTP 409). Возникает при смене/сбросе
    хранилища, утере корпуса или ошибке consumer'а: append-only ledger
    монотонен, позиция уменьшаться не может."""


def canonical_corpus(*sources: list[Any]) -> list[dict[str, Any]]:
    """Единая канонизация корпуса для проекции: нормализация канона
    §4.1 (TraceEvent/dict -- event_to_dict, мусор честно пропускается;
    прецедент смешанных представлений легальны: слой 1 -- TraceEvent,
    слой 2 -- stored-словари), затем merge_canonical_events (AUDIT-S) --
    дедуп строго по event_id (первый источник приоритетен;
    независимые события сохраняются) + канонический порядок §3.3.

    Порядок источников = приоритет идентичности: ledger слоя 2 --
    авторитетная durable-запись (его envelope/sequence выигрывают),
    слой 1 -- свежие события, ещё не зеркалированные (P15-гонка),
    артефакты Прогнозирования -- последними."""
    normalized: list[list[dict[str, Any]]] = []
    for source in sources:
        entries: list[dict[str, Any]] = []
        for event in source or ():
            data = event_to_dict(event)
            if data is not None:
                entries.append(data)
        normalized.append(entries)
    return merge_canonical_events(*normalized)


def event_context_validity(
    event_context_id: str | None,
    current_context_id: str | None,
) -> str:
    """Реэкспорт централизованной функции применимости (pipeline_graph):
    уровень context_id; исторический факт без контекста -- unknown,
    не current (план §8 AUDIT-5B)."""
    return _event_context_validity(event_context_id, current_context_id)


def _max_sequence(events: list[dict[str, Any]]) -> int | None:
    """Максимальная позиция ledger в корпусе; None -- ни у одного
    события нет sequence (чистый legacy-корпус)."""
    values = [
        event["sequence"]
        for event in events
        if isinstance(event.get("sequence"), int)
        and not isinstance(event["sequence"], bool)
    ]
    return max(values) if values else None


def _event_id_of(event: Mapping[str, Any]) -> str | None:
    event_id = event.get("event_id")
    if isinstance(event_id, str) and event_id:
        return event_id
    return None


class ProjectionSnapshot:
    """Снимок полной проекции «Прогресса» (контракт AUDIT-5B PR-2).

    Поля -- замороженные по смыслу; events -- ПОЛНЫЙ канонический
    корпус (позиция истории; отображаемый список ограничивает
    потребитель -- cap=1000 ограничивает список, не состояния, I9).

    Сериализация (to_dict/from_dict) -- checkpoint проекции: внутри
    ехает состояние fold (statuses + книжки деталей + аномалии), что
    делает advance_projection чистым достраиванием хвостом. Формат
    версии 1 -- наш внутренний носитель; мусор при чтении -- честные
    дефолты (снапшот восстанавливаем, не переписываем корпус).
    """

    __slots__ = (
        "run_id",
        "watermark",
        "last_sequence",
        "started_at",
        "context_id",
        "node_statuses",
        "node_states",
        "stage_states",
        "events",
        "anomalies",
        "complete",
        "last_event_id",
        "fold_state",
    )

    def __init__(
        self,
        *,
        run_id: str | None,
        watermark: int,
        last_sequence: int | None,
        started_at: str | None,
        context_id: str | None,
        node_statuses: dict[str, str],
        node_states: list[dict[str, Any]],
        stage_states: list[dict[str, Any]],
        events: tuple[dict[str, Any], ...],
        anomalies: int,
        complete: bool,
        last_event_id: str | None,
        fold_state: dict[str, Any],
    ) -> None:
        self.run_id = run_id
        self.watermark = watermark
        self.last_sequence = last_sequence
        self.started_at = started_at
        self.context_id = context_id
        self.node_statuses = node_statuses
        self.node_states = node_states
        self.stage_states = stage_states
        self.events = events
        self.anomalies = anomalies
        self.complete = complete
        self.last_event_id = last_event_id
        self.fold_state = fold_state

    # -- удобные представления --

    @property
    def events_total(self) -> int:
        """Полный размер корпуса (синоним watermark -- позиция истории)."""
        return self.watermark

    def display_events(self, cap: int) -> list[dict[str, Any]]:
        """Отображаемый список: ПОСЛЕДНИЕ cap событий канонического
        порядка (I9: cap ограничивает список, не накопленные
        состояния)."""
        if cap <= 0:
            return []
        return list(self.events[-cap:])

    def to_dict(self) -> dict[str, Any]:
        """Checkpoint-сериализация (JSON-безопасна)."""
        return {
            "version": 1,
            "run_id": self.run_id,
            "watermark": self.watermark,
            "last_sequence": self.last_sequence,
            "started_at": self.started_at,
            "context_id": self.context_id,
            "node_statuses": dict(self.node_statuses),
            "node_states": [dict(state) for state in self.node_states],
            "stage_states": [dict(state) for state in self.stage_states],
            "events": list(self.events),
            "anomalies": self.anomalies,
            "complete": self.complete,
            "last_event_id": self.last_event_id,
            "fold_state": self.fold_state,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProjectionSnapshot":
        """Восстановление checkpoint (restart проекции не теряет ранние
        статусы -- RED-критерий плана §8)."""
        return cls(
            run_id=data.get("run_id") if isinstance(data.get("run_id"), str) else None,
            watermark=int(data.get("watermark") or 0),
            last_sequence=(
                int(data["last_sequence"])
                if isinstance(data.get("last_sequence"), int)
                and not isinstance(data.get("last_sequence"), bool)
                else None
            ),
            started_at=(
                data.get("started_at")
                if isinstance(data.get("started_at"), str)
                else None
            ),
            context_id=(
                data.get("context_id")
                if isinstance(data.get("context_id"), str)
                else None
            ),
            node_statuses={
                str(k): str(v)
                for k, v in (data.get("node_statuses") or {}).items()
            },
            node_states=list(data.get("node_states") or []),
            stage_states=list(data.get("stage_states") or []),
            events=tuple(data.get("events") or []),
            anomalies=max(0, int(data.get("anomalies") or 0)),
            complete=bool(data.get("complete", True)),
            last_event_id=(
                data.get("last_event_id")
                if isinstance(data.get("last_event_id"), str)
                else None
            ),
            fold_state=dict(data.get("fold_state") or {}),
        )


def _check_min_watermark(watermark: int, min_watermark: int | None) -> None:
    if min_watermark is not None and watermark < min_watermark:
        raise ProjectionPendingError(
            f"projection_pending: позиция корпуса {watermark} не достигла "
            f"запрошенной {min_watermark}"
        )


def _run_meta_fields(
    run_meta: Mapping[str, Any] | None,
) -> tuple[str | None, str | None, str | None]:
    if not isinstance(run_meta, Mapping):
        return None, None, None
    run_id = run_meta.get("run_id")
    created_at = run_meta.get("created_at")
    context_id = run_meta.get("context_id")
    return (
        str(run_id) if isinstance(run_id, str) and run_id else None,
        str(created_at) if isinstance(created_at, str) and created_at else None,
        (
            str(context_id)
            if isinstance(context_id, str) and context_id
            else None
        ),
    )


def _build_from_fold(
    fold: NodeStateFold,
    corpus: list[dict[str, Any]],
    *,
    run_meta: Mapping[str, Any] | None,
    check_modes: Mapping[str, Mapping[str, Any]] | None,
    corpus_complete: bool,
) -> ProjectionSnapshot:
    run_id, created_at, context_id = _run_meta_fields(run_meta)
    return ProjectionSnapshot(
        run_id=run_id,
        watermark=len(corpus),
        last_sequence=_max_sequence(corpus),
        # P11/PR-3: started_at -- run.created_at, НЕ ts первого события
        # уцелевшего хвоста (run_meta нет -- честное отсутствие, хвост
        # начало не выдумывает).
        started_at=created_at,
        context_id=context_id,
        node_statuses=dict(fold.statuses),
        # I10: узлы несут происхождение полей + validity против
        # контекста запуска (уровень context_id).
        node_states=fold.node_states_with_evidence(
            check_modes=check_modes, run_context_id=context_id
        ),
        stage_states=derive_stage_states(fold.statuses),
        events=tuple(corpus),
        anomalies=fold.anomaly_count,
        complete=bool(corpus_complete),
        last_event_id=_event_id_of(corpus[-1]) if corpus else None,
        fold_state=fold.export_state(),
    )


def build_projection(
    *sources: list[dict[str, Any]],
    run_meta: Mapping[str, Any] | None = None,
    check_modes: Mapping[str, Mapping[str, Any]] | None = None,
    corpus_complete: bool = True,
    min_watermark: int | None = None,
) -> ProjectionSnapshot:
    """Полный replay -- контрольный эталон проекции (план §8 «Риск»).

    Источники канонизируются здесь (canonical_corpus: дедуп по
    event_id + единый порядок), состояние собирается ЕДИНЫМ
    редьюсером NodeStateFold. min_watermark -- read-after-watermark:
    корпус меньше позиции -- ProjectionPendingError (честное
    projection_pending).
    """
    corpus = canonical_corpus(*sources)
    _check_min_watermark(len(corpus), min_watermark)
    fold = NodeStateFold()
    for event in corpus:
        fold.apply(event)
    return _build_from_fold(
        fold,
        corpus,
        run_meta=run_meta,
        check_modes=check_modes,
        corpus_complete=corpus_complete,
    )


def advance_projection(
    base: ProjectionSnapshot,
    tail_events: list[dict[str, Any]],
    *,
    run_meta: Mapping[str, Any] | None = None,
    check_modes: Mapping[str, Mapping[str, Any]] | None = None,
    corpus_complete: bool = True,
    min_watermark: int | None = None,
) -> ProjectionSnapshot:
    """Checkpoint + tail (план §8: «Источник -- полный ledger либо
    проверенный checkpoint проекции + tail»).

    base -- сериализованный или живой снапшот позиции W; tail_events --
    события Канонического порядка ПОСЛЕ позиции W (хвост среза
    canonical_corpus; контракты: append-only ledger, хвост не содержит
    событий префикса). Состояние fold восстанавливается из base и
    достраивается хвостом -- префикс повторно НЕ прогоняется.

    Эквивалентность «replay == snapshot + tail» -- инвариант задачи
    (оракулы: расщепления корпуса, restart через from_dict,
    нагрузочный корпус); выравнивание run-метаданных -- свежими
    run_meta/check_modes (контекст может сместиться с префикса).
    Хвост нормализуется к канону §4.1 (TraceEvent/dict -- event_to_dict;
    срез канонического корпуса идемпотентен, повторный порядок не
    переупорядочивает)."""
    fold = NodeStateFold()
    fold.restore_state(base.fold_state)
    tail: list[dict[str, Any]] = []
    for event in tail_events:
        data = event_to_dict(event)
        if data is not None:
            tail.append(data)
    watermark = base.watermark + len(tail)
    _check_min_watermark(watermark, min_watermark)
    for event in tail:
        fold.apply(event)
    corpus = tuple(base.events) + tuple(tail)
    snapshot = _build_from_fold(
        fold,
        list(corpus),
        run_meta=run_meta,
        check_modes=check_modes,
        corpus_complete=corpus_complete,
    )
    # позиция истории -- от base, не от длины слияния (tail --
    # канонический хвост после W; дедуп против префикса -- ошибка
    # вызывающего, что видно по watermark).
    return snapshot
