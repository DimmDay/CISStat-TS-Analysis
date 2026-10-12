# apps/api/progress_maps.py
"""ЕДИНЫЙ механизм API-карт статусов «Прогресса»: v2-конверт, контекстные
гейты и идемпотентность доставки (задача AUDIT-2A, план
plan_progress_audit.md §11; контракт docs/progress_audit_contract.md
аддендум v0.9-2A §19).

Потребители -- ЧЕТЫРЕ эндпоинта отчёта карт (apps/api/routers/progress.py):
POST /upload-stops, /validation-checks, /preprocessing-checks,
/eda-checks. До AUDIT-2A их контур записи был скопирован четыре раза и
обладал классом дефектов F04/F07 (спека spec_progress_audit.md §5):

  * P24/F04 -- карта не привязана к контексту расчёта: старое тело
    принимается новым запуском, отчёт прошлого контекста того же
    запуска принимается после смены цели/ревизии;
  * P07/F07 -- повтор отчёта не идемпотентен: каждый POST рождает
    новые event_id, содержательный дедуп store'а (AUDIT-6A) не
    активируется, Memory и Postgres расходятся;
  * карты писались v1-событиями -- «клиентское наблюдение» не было
    выражено в доказательности факта (I10);
  * у доставки не было receipt -- клиент не различал «принято» и
    «записано в долговременный слой».

Механизм (контракт §19):

  * V-1 v2-конверт тела: schema_version=2 + run_id + context_id +
    report_id (+ result_refs там, где результаты имеются). Форма --
    422 ДО первой записи;
  * V-2 контекстные гейты ДО записи: совпадение запуска (409
    stale_run) и контекста (409 stale_context -- против durable
    run.context_id, ТОГО ЖЕ источника, что клиент видит в
    GET /v1/progress/trace). Любой 409/422 -- НОЛЬ изменений в слоях
    1 и 2 (план §11 GREEN);
  * V-3 идемпотентность по report_id: ключ report:{run_id}:{report_id}
    + отпечаток ТЕЛА (без event_id/ts). Повтор того же тела -- прежний
    receipt и ноль новых событий (включая слой 1); тот же ключ с
    другим телом -- 409; НОВЫЙ ключ с тем же телом -- новое клиентское
    наблюдение (явное основание -- новый отчёт, план §11 п.4);
  * V-4 события штампуются envelope'ом (stamp_envelope): schema_version=2,
    evidence_level=client_observation, operation_id=report_id,
    context_id; result_ref -- только узлам со ссылками;
  * V-5 легаси-режим (тело БЕЗ schema_version) -- прежнее поведение
    байт-в-байт; ответ помечен mode="legacy". P24/H26 для old-write
    пути НЕ закрыты -- compatibility mode до отключения (план §20.2
    п.4, контракт §19.5);
  * V-6 транзакционность v2: строгий commit слоя 2 (CAS контекста)
    ПЕРЕД слоем 1 -- отказы до/на commit оставляют ноль частичных
    узлов; сбой сохранения слоя 1 ПОСЛЕ durable-фиксации -- честный
    500 с существующим receipt (retry дедуплицируется).

Сервер НЕ пересчитывает профили/проверки по пришедшей карте (план §11
п.2): карта -- client observation о состоянии модуля, а не факт
серверного расчёта; сервер удостоверяет КОНТЕКСТ и ФОРМУ, доказатель-
ность события -- client_observation, не server_result.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from fastapi import HTTPException, Request, Response

from apps.api.research_runs import (
    commit_map_report,
    record_run_event_batch,
)
from apps.api.session_store import (
    get_or_create_session_id,
    get_session_store,
)
from apps.api.trace_events import TraceEvent, make_trace_event, stamp_envelope

logger = logging.getLogger("apps.api.progress_maps")

# Редакция конверта карт (контракт §19.1): поддерживается ТОЛЬКО 2.
# Явное чужое значение (1/3/...) -- 422: legacy-писатели шлют тело БЕЗ
# поля (отсутствие поля -- честный признак легаси-режима), а не нулём/1.
MAP_REPORT_SCHEMA_VERSION = 2

# Ссылка на результат: непрозрачная строка клиента. Если ссылка несёт
# ВСТРОЕННЫЙ контекст (префикс ctx-<16 hex>@), он обязан совпадать с
# контекстом отчёта -- «результат чужого контекста не прикладывается к
# текущей карте» (I3; RED плана §11 «result принадлежит чужому
# контексту»). Форма префикса -- канон context_id (data_context.py:
# CONTEXT_ID_PREFIX + 16 hex). Ссылка без префикса -- клиентская метка
# без серверной проверки владения (серверный реестр результатов --
# граница AUDIT-6B/7A, честно задокументирована).
_RESULT_REF_MAX_LEN = 512
_REPORT_ID_MAX_LEN = 200
_CONTEXT_REF_PREFIX = re.compile(r"^ctx-[0-9a-f]{16}@")


@dataclass(frozen=True)
class MapSpec:
    """Параметры ЭНДПОИНТА карты для единого механизма записи.

    Формовая валидация карты (реестр узлов/словарь статусов/полнота)
    остаётся в handler'е (тексты и гейты legacy-поведения не меняются);
    в механизм передаётся уже провалидированная полная карта.
    """

    stage: str                       # "upload" | "validation" | "preprocessing" | "eda"
    event_type: str                  # тип события трассы (реестр §4.1)
    registry: Tuple[str, ...]        # полный реестр узлов карты (порядок записи)
    no_dataset_subject: str          # подлежащее текста 400 («остановки «Загрузки»»...)


@dataclass(frozen=True)
class MapReportV2:
    """Разобранный v2-конверт отчёта карты (контракт §19.1)."""

    run_id: str
    context_id: str
    report_id: str
    result_refs: Tuple[Tuple[str, str], ...] = ()


@dataclass(frozen=True)
class MapReportOutcome:
    """Итог приёмки отчёта -- поля ответа эндпоинта (контракт §19.4).

    mode="legacy" -- прежний контракт (receipt/report_id/context_id
    не выдаются); mode="v2" -- приёмка с receipt: deduplicated=true
    означает повтор той же поставки (события не записывались).
    """

    run_id: str
    reported: int
    mode: str
    report_id: Optional[str] = None
    context_id: Optional[str] = None
    deduplicated: bool = False
    receipt: Optional[Dict[str, Any]] = None

    def response_fields(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "reported": self.reported,
            "mode": self.mode,
            "report_id": self.report_id,
            "context_id": self.context_id,
            "deduplicated": self.deduplicated,
            "receipt": self.receipt,
        }


def parse_map_envelope(
    body: Any, *, registry: Tuple[str, ...]
) -> Optional[MapReportV2]:
    """Разбор v2-конверта тела отчёта (контракт §19.1).

    None -- легаси-режим (schema_version отсутствует: старые писатели
    шлют только карту). Формовые нарушения конверта -- HTTPException
    422 (вызывается ДО первой записи; отчёт не касается хранилищ).

    result_refs -- Optional-словарь {узел реестра -> непрозрачная
    ссылка}: фантомный узел/пустая ссылка -- 422; ссылка со встроенным
    чужим контекстом -- 409 (принадлежность результата другому расчёту).
    """
    schema_version = getattr(body, "schema_version", None)
    if schema_version is None:
        return None
    if schema_version != MAP_REPORT_SCHEMA_VERSION:
        raise HTTPException(
            status_code=422,
            detail=(
                f"schema_version={schema_version!r}: поддерживается "
                f"{MAP_REPORT_SCHEMA_VERSION}; legacy-писатели шлют тело "
                "БЕЗ поля schema_version (контракт §19.5)"
            ),
        )
    run_id = str(getattr(body, "run_id", None) or "").strip()
    if not run_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "v2-конверт требует run_id: отчёт обязан ссылаться на "
                "запуск исследования (непустая строка)"
            ),
        )
    context_id = str(getattr(body, "context_id", None) or "").strip()
    if not context_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "v2-конверт требует context_id: карта связывается с "
                "контекстом расчёта (I3/P24); серверный context_id "
                "клиент получает из GET /v1/progress/trace"
            ),
        )
    report_id = str(getattr(body, "report_id", None) or "").strip()
    if not report_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "v2-конверт требует report_id: стабильный ключ поставки "
                "-- идемпотентность (повтор того же тела возвращает "
                "прежний receipt, P07)"
            ),
        )
    if len(report_id) > _REPORT_ID_MAX_LEN:
        raise HTTPException(
            status_code=422,
            detail=(
                f"report_id длиннее {_REPORT_ID_MAX_LEN} символов -- "
                "ключ поставки обязан быть компактным"
            ),
        )
    raw_refs = getattr(body, "result_refs", None) or {}
    refs: list[tuple[str, str]] = []
    for node_id, ref in dict(raw_refs).items():
        if node_id not in registry:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"result_refs: неизвестный узел {node_id!r}; реестр "
                    f"карты: {list(registry)} (фантомных ссылок нет)"
                ),
            )
        if not isinstance(ref, str) or not ref.strip():
            raise HTTPException(
                status_code=422,
                detail=(
                    f"result_refs[{node_id!r}]: ссылка обязана быть "
                    "непустой строкой"
                ),
            )
        ref = ref.strip()
        if len(ref) > _RESULT_REF_MAX_LEN:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"result_refs[{node_id!r}]: ссылка длиннее "
                    f"{_RESULT_REF_MAX_LEN} символов"
                ),
            )
        match = _CONTEXT_REF_PREFIX.match(ref)
        if match:
            ref_context = ref[: match.end() - 1]  # без '@'
            if ref_context != context_id:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"result_refs[{node_id!r}]: ссылка принадлежит "
                        f"чужому контексту {ref_context!r} (отчёт -- "
                        f"{context_id!r}); результат чужого расчёта не "
                        "прикладывается к текущей карте (I3)"
                    ),
                )
        refs.append((node_id, ref))
    refs.sort()
    return MapReportV2(
        run_id=run_id,
        context_id=context_id,
        report_id=report_id,
        result_refs=tuple(refs),
    )


def report_body_fingerprint(
    *,
    run_id: str,
    context_id: str,
    report_id: str,
    payload_map: Mapping[str, str],
    result_refs: Optional[Mapping[str, str]] = None,
) -> str:
    """Детерминированный отпечаток ТЕЛА v2-отчёта (контракт §19.3).

    Материал -- КЛИЕНТСКОЕ тело (карта + конверт), НЕ сгенерированные
    события: повтор того же тела даёт тот же отпечаток независимо от
    event_id/ts записей. База решений store'а (AUDIT-6A): тот же ключ
    идемпотентности + тот же отпечаток -- прежний receipt без записи;
    тот же ключ с другим отпечатком -- конфликт без записи (план §7
    п.4). Порядок ключей карты/ссылок не влияет (canonical json).
    """
    refs = sorted(
        (str(node_id), str(ref))
        for node_id, ref in dict(result_refs or {}).items()
    )
    material = json.dumps(
        {
            "v": 1,
            "kind": "progress-map-report",
            "run_id": str(run_id),
            "context_id": str(context_id),
            "report_id": str(report_id),
            "map": {
                str(node_id): str(status)
                for node_id, status in dict(payload_map).items()
            },
            "result_refs": [list(pair) for pair in refs],
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def _build_map_events(
    spec: MapSpec,
    *,
    run_id: str,
    map_values: Mapping[str, str],
    envelope: Optional[MapReportV2] = None,
) -> list[TraceEvent]:
    """События карты в ПОРЯДКЕ РЕЕСТРА (прецедент §7.2/PROGR-13-A4).

    Легаси -- v1-форма (envelope не сеется, прежний корпус совместим).
    v2 -- штамп client_observation (schema_version=2, operation_id,
    context_id) + result_ref узлам со ссылками (контракт §19.2/§19.3).
    """
    events: list[TraceEvent] = []
    refs_by_node = dict(envelope.result_refs) if envelope else {}
    for node_id in spec.registry:
        event = make_trace_event(
            spec.event_type,
            stage=spec.stage,
            node_id=node_id,
            run_id=run_id,
            status=map_values[node_id],
        )
        if envelope is not None:
            stamp_kwargs: Dict[str, Any] = {
                "schema_version": MAP_REPORT_SCHEMA_VERSION,
                "evidence_level": "client_observation",
                "operation_id": envelope.report_id,
                "context_id": envelope.context_id,
            }
            ref = refs_by_node.get(node_id)
            if ref is not None:
                stamp_kwargs["result_ref"] = {"report_ref": ref}
            event = stamp_envelope(event, **stamp_kwargs)
        events.append(event)
    return events


def accept_map_report(
    *,
    request: Request,
    response: Response,
    spec: MapSpec,
    map_values: Mapping[str, str],
    body: Any,
) -> MapReportOutcome:
    """ЕДИНЫЙ контур записи отчёта карты (легаси + строгий v2).

    Гейты по порядку (контракт §19.6):
      1. 400 -- датасет отсутствует (факты без исследования не
         существуют; гейт общий для обоих режимов, порядок прежний);
      2. разбор конверта -- None (легаси) либо MapReportV2; форма
         конверта -- 422 до записи;
      3. ЛЕГАСИ: прежний контур байт-в-байт (ensure_run_id -> события
         v1 -> слой 1 -> best-effort зеркало слоя 2 с map:-отпечатком);
         P24 для old-write пути НЕ закрыт (compatibility mode);
      4. V2 strict: 409 stale_run (отчёт чужого/неизвестного запуска);
         409 stale_context (контекст отчёта != durable run.context_id);
      5. V2: строгий commit слоя 2 (ключ report:{run}:{report_id},
         отпечаток тела, CAS expected_context) -- дедуп возвращает
         прежний receipt БЕЗ записи; конфликт тела/сдвиг контекста --
         409; всё ДО слоя 1 (ноль частичных узлов);
      6. V2: слой 1 (append+save) ПОСЛЕ durable-фиксации; сбой -- 500
         с существующим receipt (повтор той же поставки вернёт receipt,
         дедуплицировавшись; граница -- контракт §19.6).

    Возвращает поля ответа; reported -- размер реестра при приёмке,
    0 при дедупе (новых фактов не записано).
    """
    session_id = get_or_create_session_id(request, response)
    store = get_session_store()
    session = store.get_or_create(session_id)
    if session.dataset is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Сначала загрузите датасет -- {spec.no_dataset_subject} "
                "без данных не существуют"
            ),
        )

    envelope = parse_map_envelope(body, registry=spec.registry)

    if envelope is None:
        # ── V-5: легаси-режим -- прежнее поведение байт-в-байт ──
        session.ensure_run_id()
        events = _build_map_events(spec, run_id=session.run_id, map_values=map_values)
        for event in events:
            session.append_trace_event(event)
        store.save(session)
        # Слой 2 -- тот же best-effort батч AUDIT-6A (сбой не ломает
        # ответ; частичных фактов в слое 2 нет -- P08).
        record_run_event_batch(session, events)
        return MapReportOutcome(
            run_id=session.run_id,
            reported=len(spec.registry),
            mode="legacy",
        )

    # ── V-2: строгий v2 -- контекстные гейты ДО записи ──
    run_id = session.run_id or ""
    if not run_id or envelope.run_id != run_id:
        raise HTTPException(
            status_code=409,
            detail=(
                f"stale_run: отчёт относится к запуску "
                f"{envelope.run_id!r}, сессия ведёт запуск "
                f"{run_id or None!r} -- устаревший отчёт не записывается "
                "(P24/F04); обновите контекст GET /v1/progress/trace"
            ),
        )
    from apps.api.research_runs import get_research_run_store

    run = get_research_run_store().get_run(run_id)
    if run is None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"stale_run: запуск {run_id!r} не зафиксирован в "
                "долговременном слое -- привязывать карту не к чему (I3)"
            ),
        )
    server_context = run.context_id
    if not server_context:
        raise HTTPException(
            status_code=409,
            detail=(
                f"stale_context: контекст запуска {run_id!r} не "
                "зафиксирован -- строгий v2 отклоняет отчёт без "
                "контекста (план §11 п.5)"
            ),
        )
    if envelope.context_id != server_context:
        raise HTTPException(
            status_code=409,
            detail=(
                f"stale_context: отчёт относится к контексту "
                f"{envelope.context_id!r}, текущий контекст запуска -- "
                f"{server_context!r} (смена цели/данных/ревизии); старый "
                "снапшот не записывается и не повышает текущий прогресс "
                "(P24/F04)"
            ),
        )

    events = _build_map_events(
        spec, run_id=run_id, map_values=map_values, envelope=envelope
    )
    fingerprint = report_body_fingerprint(
        run_id=run_id,
        context_id=envelope.context_id,
        report_id=envelope.report_id,
        payload_map=map_values,
        result_refs=dict(envelope.result_refs),
    )
    idempotency_key = f"report:{run_id}:{envelope.report_id}"

    # ── V-3/V-6: строгий commit слоя 2 ПЕРЕД слоем 1 ──
    # Дедуп (тот же ключ + то же тело) возвращает ПРЕЖНИЙ receipt --
    # события, построенные выше, не записываются ни в один слой.
    # Конфликты store'а (AUDIT-6A) -- честные 409 ДО слоя 1 (ноль
    # изменений): тот же ключ с другим телом -- IdempotencyConflictError;
    # сдвиг контекста между гейтом и commit (гонка) -- CommitConflictError.
    from apps.api.research_runs import (
        CommitConflictError,
        IdempotencyConflictError,
    )

    try:
        receipt = commit_map_report(
            session,
            events=tuple(events),
            run_id=run_id,
            expected_context_id=server_context,
            idempotency_key=idempotency_key,
            body_fingerprint=fingerprint,
        )
    except IdempotencyConflictError:
        raise HTTPException(
            status_code=409,
            detail=(
                f"report_id_conflict: ключ поставки {idempotency_key!r} "
                "уже использован с ДРУГИМ телом -- прежний ключ не "
                "переиспользуется (P07); сформируйте новый report_id "
                "для новой поставки"
            ),
        )
    except CommitConflictError:
        raise HTTPException(
            status_code=409,
            detail=(
                f"stale_context: контекст запуска {run_id!r} сдвинулся "
                "между проверкой и фиксацией (конкурентная операция) -- "
                "отчёт не записан (I3); обновите контекст GET "
                "/v1/progress/trace и повторите"
            ),
        )
    deduplicated = set(receipt.accepted_event_ids) != {
        event.event_id for event in events
    }

    if not deduplicated:
        for event in events:
            session.append_trace_event(event)
        try:
            store.save(session)
        except Exception:
            logger.warning(
                "Progress maps: слой 1 не сохранён после durable-"
                "фиксации %s -- receipt существует, повтор той же "
                "поставки вернёт его дедуплицированно",
                idempotency_key,
                exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail=(
                    "Долговременный слой зафиксировал отчёт (receipt "
                    "выдан), локальная копия сессии не сохранена -- "
                    "повторите доставку с тем же report_id (повтор "
                    "вернёт receipt без новых фактов)"
                ),
            )

    return MapReportOutcome(
        run_id=run_id,
        reported=0 if deduplicated else len(spec.registry),
        mode="v2",
        report_id=envelope.report_id,
        context_id=envelope.context_id,
        deduplicated=deduplicated,
        receipt=receipt.to_dict(),
    )
