# apps/api/passport_checkpoints.py
"""
Task PGV-04 (spec_passport_graphics_visual.md §8/§10.2/§13, строка
PGV-04): durable checkpoint/backfill -- каждый EDA handoff
(modeling_entry И panel_entry) фиксируется durable-артефактом
``pgv.passport_checkpoint/1``, включая reused snapshot.

ПОСТАНОВКА (§13): «Durable checkpoint/backfill; точки изменения --
promotion_integration/artifact_promotion/capture; критерий -- Reused
handoff хранит confirmed_at/trajectory отдельно, retry без capture».

ЧТО ДОБАВЛЯЕТ ПОСТАВКА (субстрат PGV-02: валидатор
pgv.passport_checkpoint/1 и register_passport_checkpoint уже
сертифицированы; здесь -- capture-сторона и backfill):

1. rs-ЗАПИСИ СНИМКОВ ПАСПОРТОВ. Чекпоинт ссылается на снимки через
   rs-* (контракт PGV-02), поэтому поставка обеспечивает СУЩЕСТВОВАНИЕ
   доказуемых durable-записей: одна rs-запись ReportSnapshot-реестра на
   session-снимок паспорта (идемпотентность по idempotency_key
   ``pgv-passport:{session_snapshot_id}`` -- §8 «старые snapshots не
   переписываются»). Запись -- АДРЕСУЕМЫЙ ФАКТ снимка (id/stage/
   fingerprint/target/date/время), НЕ документ: kinds=["D02"],
   sections=[], reproducibility=limited с причиной
   ``passport_snapshot_record``. Полное содержимое паспорта живёт в
   паспортном артефакте (kind="passport", промоушен notify_passport_
   captured -- C03); он прицепляется зависимостью, когда доступен.
   Зависимости нет -- честный content-гэп (legacy-сессии до C03),
   фабкация запрещена (R03).

2. СИНХРОННАЯ ЗАМОРОЗКА ЧЕКПОИНТА (producer_capture). Вызывается из
   точек capture (POST /dataset/passport/{stage}=modeling_entry,
   POST /panel/passport/confirm) ПОСЛЕ фиксации session-фактуры.
   Отсутствие обязательных точек траектории (validation/exit для
   modeling_entry) -- PromotionUnavailable: честный недобор, НЕ сбой
   (штатный поток «start -> modeling_entry» легитимен; receipt'ом
   security-audit не замусоривается). Прочие сбои -- durable-receipt
   в единой точке интеграции (прецедент C03).

3. BACKFILL (legacy_import). Sweep-точка моделирования
   (notify_modeling_artifacts_updated) добирает чекпоинты без durable
   представления ТОЛЬКО из доказуемых session-записей (single --
   passport_checkpoints, panel -- panel_entry_checkpoints) -- retry
   БЕЗ capture/пересчёта науки (§9.3; PGV-04-FIX F-P4C1: панельный
   список читается из РЕАЛЬНОГО поля session-контура). Уже
   замороженные (любой provenance) пропускаются по producer_key БЕЗ
   чтения payload -- конфликтов контента не возникает, provenance
   первого успеха сохраняется. Изоляция per-entry (PGV-04-FIX
   F-P4C2, паритет sweep-цикла): честный недобор
   (PromotionUnavailable) -- info-гэп без receipt; прочий сбой
   КОНКРЕТНОЙ записи -- durable-receipt + счётчик failed, добор
   остальных продолжается (восстановимая доставка).

КЛЮЧЕВЫЕ РЕШЕНИЯ ЧЕСТНОСТИ:

- confirmed_at -- из session-записи checkpoint'а; время промоушена НЕ
  подставляется (AC12). Чекпоинт с утраченным временем не фабкуется
  (валидатор PGV-02 требует confirmed_at XOR reason; session-запись
  время всегда несёт -- reason-ветка остаётся для будущих источников).
- trajectory refs «на момент подтверждения»: снимки этапов
  фильтруются по captured_at <= checkpoint.confirmed_at (история
  append-only -- фильтр доказуем); более поздние снимки в траекторию
  НЕ попадают (AC10-дух).
- context чекпоинта -- текущий (run, context_id, data_revision) сессии
  на момент заморозки: для синхронной заморозки это контекст
  подтверждения (один request); для backfill -- контекст импорта,
  что ЧЕСТНО маркируется provenance=legacy_import (контекст момента
  подтверждения legacy-чекпоинта из session-записей недоказуем).
- flags: created/reused -- по created_snapshot session-чекпоинта;
  unchanged НЕ заявляется (False): session-контур не производит
  доказуемо отличный от reused «unchanged»-случай (409 на повторное
  подтверждение того же fingerprint) -- поле остаётся контрактом
  валидатора для будущих источников.
- panel_entry: entity_id = entity_column панели (идентификатор
  entity-вселенной, AC14 «панели не смешиваются»);
  previous_snapshot_ref = None -- session-конвенция confirm ставит
  previous = сам снимок; отдельного «предыдущего» у панельного
  handoff нет, самоссылка не записывается (запрет F-P2C4).
- checkpoint_id durable = ``pck-`` + session checkpoint_id
  (детерминированная деривация: идемпотентность §8 сохраняется между
  capture/backfill; формат pck-* по валидатору PGV-02).
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from apps.api.visual_artifacts import CHECKPOINT_SCHEMA_VERSION

logger = logging.getLogger(__name__)

CHECKPOINT_ID_PREFIX = "pck-"
PASSPORT_RECORD_IDEMPOTENCY_PREFIX = "pgv-passport:"

# Универс чекпоинта -> скоуп чтения снимков сессии (R4: панельный
# контур не касается однорядного и наоборот).
_STAGE_UNIVERSES = {
    "modeling_entry": "single",
    "panel_entry": "panel",
}


def durable_checkpoint_id(session_checkpoint_id: str) -> str:
    """pck-{session_checkpoint_id}: детерминированная деривация
    durable-идентификатора из session-факта (идемпотентность §8)."""
    return f"{CHECKPOINT_ID_PREFIX}{session_checkpoint_id}"


def _parse_ts(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _authorized_service(run_id: str, subject: Any, session_id: str) -> Any:
    from apps.api.artifact_promotion import PromotionService

    service = PromotionService.create_default()
    service._authorized_run(run_id, subject, session_id, action="write")
    return service


# ── rs-записи снимков паспортов ──────────────────────────────────────


def _find_passport_artifact(service: Any, run_id: str, snapshot_id: str) -> Any:
    """Паспортный артефакт снимка (промоушен notify_passport_captured);
    None -- честное отсутствие (legacy-сессии до C03)."""
    try:
        return service.find_by_producer(run_id, f"passport:{snapshot_id}")
    except Exception:  # pragma: no cover -- честная деградация
        return None


def ensure_passport_snapshot_record(
    run_id: str,
    subject: Any,
    *,
    session_snapshot: Any,
    session_id: str = "",
    context_id: Optional[str] = None,
    data_revision: Optional[int] = None,
    created_by: Optional[str] = None,
) -> tuple[Any, bool]:
    """Гарантировать durable rs-запись ОДНОГО session-снимка паспорта.

    Идемпотентность: idempotency_key = pgv-passport:{snapshot_id};
    существующая запись возвращается без переписывания (§8). Запись --
    адресуемый факт (kinds=["D02"], sections=[]); полное содержимое
    паспорта -- в паспортном артефакте (зависимость, когда доступен).

    context_id/data_revision штампуются ТОЛЬКО когда доказуемы
    (снимок, созданный в этом же request'е подтверждения); для
    исторических снимков -- None (не догадка, AC12-дух).
    Возвращает (ReportSnapshot, created)."""
    service = _authorized_service(run_id, subject, session_id)

    from apps.api.report_snapshot import (
        ReportSnapshot,
        get_snapshot_registry,
        new_snapshot_id,
    )

    registry = get_snapshot_registry()
    idempotency_key = (
        f"{PASSPORT_RECORD_IDEMPOTENCY_PREFIX}{session_snapshot.snapshot_id}"
    )
    existing = registry.find_idempotent(run_id, idempotency_key)
    if existing is not None:
        return existing, False

    passport_artifact = _find_passport_artifact(
        service, run_id, session_snapshot.snapshot_id
    )
    fingerprint_body = {
        "purpose": "pgv-passport-record",
        "session_snapshot_id": session_snapshot.snapshot_id,
        "stage": session_snapshot.stage,
        "fingerprint": session_snapshot.fingerprint,
        "target_column": session_snapshot.target_column,
        "date_column": session_snapshot.date_column,
        "context_id": context_id,
        "data_revision": data_revision,
    }
    from apps.api.artifact_store import canonical_json_bytes

    request_fingerprint = hashlib.sha256(
        canonical_json_bytes(fingerprint_body)
    ).hexdigest()

    dependencies: list[str] = []
    deps_records: list[dict[str, Any]] = []
    if passport_artifact is not None:
        dependencies = [f"artifact:{passport_artifact.artifact_id}"]
        deps_records = [
            {
                "ref_kind": "artifact",
                "ref_id": passport_artifact.artifact_id,
                "reason": "passport_record",  # причина ставится после id
            }
        ]

    snapshot = ReportSnapshot(
        snapshot_id=new_snapshot_id(),
        research_run_id=run_id,
        # Контекст снимка штампуется только при доказуемости (см.
        # докстринг): исторические снимки контекста не несут.
        context_id=context_id,
        data_revision=data_revision,
        data_ref=None,
        data_digest=None,
        source_cutoff={},
        captured_at=session_snapshot.captured_at,
        knowledge_version=None,
        classification="private",
        redaction_profile="owner-v1",
        completeness={"status": "partial", "missing_refs": [], "missing_mandatory": []},
        reproducibility={
            "status": "limited",
            "reasons": ["passport_snapshot_record"],
        },
        sections=[],
        dependencies=dependencies,
        approval=None,
        kinds=["D02"],
        idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint,
        created_by=created_by or getattr(subject, "subject_id", None),
    )
    if deps_records:
        deps_records[0]["reason"] = f"passport_record:{snapshot.snapshot_id}"
    stored, created = registry.register_snapshot(snapshot, deps_records)
    if created and passport_artifact is not None:
        # §16: metadata graph хранит ПРИЧИНЫ ссылок -- pin зависимости.
        try:
            service.registry.pin_ref(
                run_id,
                "artifact",
                passport_artifact.artifact_id,
                reason=f"passport_record:{stored.snapshot_id}",
                created_by=created_by or getattr(subject, "subject_id", None),
            )
        except Exception as exc:  # pragma: no cover -- защитный контур
            logger.warning(
                "passport_record pin failed: run=%s artifact=%s -- %s",
                run_id,
                passport_artifact.artifact_id,
                exc,
            )
    return stored, created


# ── Заморозка чекпоинта ──────────────────────────────────────────────


def _stage_snapshot_at(
    session: Any, stage: str, confirmed_at: datetime
) -> Optional[Any]:
    """Последний снимок этапа, зафиксированный НЕ ПОЗЖЕ подтверждения
    (траектория «на момент подтверждения»; история append-only)."""
    if stage == "panel_entry":
        candidates = session.panel_passport_history
    else:
        candidates = session.passport_history
    best: Optional[Any] = None
    best_ts: Optional[datetime] = None
    for item in candidates:
        if item.stage != stage:
            continue
        captured = _parse_ts(item.captured_at)
        if captured is None or captured > confirmed_at:
            continue
        if best_ts is None or captured >= best_ts:
            best, best_ts = item, captured
    return best


def _resolve_universe(session: Any, checkpoint: Any) -> str:
    universe = _STAGE_UNIVERSES.get(checkpoint.stage)
    if universe is None:
        from apps.api.artifact_promotion import PromotionUnavailable

        raise PromotionUnavailable(
            f"Неизвестный этап чекпоинта: {checkpoint.stage!r} (R03)"
        )
    return universe


def _checkpoint_snapshot(session: Any, checkpoint: Any) -> Any:
    snapshot = (
        session.panel_passport_snapshot(checkpoint.snapshot_id)
        if checkpoint.stage == "panel_entry"
        else session.passport_snapshot(checkpoint.snapshot_id)
    )
    if snapshot is None:
        from apps.api.artifact_promotion import PromotionUnavailable

        raise PromotionUnavailable(
            f"Снимок {checkpoint.snapshot_id!r} чекпоинта отсутствует в "
            "session-записях -- ничего не фабкуется (R03)"
        )
    return snapshot


def build_passport_checkpoint_payload(
    session: Any,
    checkpoint: Any,
    *,
    created_snapshot: bool,
    provenance: str,
    snapshot_ref: str,
    previous_snapshot_ref: Optional[str],
    stage_refs: dict[str, str],
) -> dict[str, Any]:
    """pgv.passport_checkpoint/1 payload как ЧИСТАЯ функция session-
    фактов (детерминизм: те же записи -- тот же payload)."""
    context_id = None
    try:
        context_id = session.current_context_id()
    except Exception:  # pragma: no cover -- честная деградация
        context_id = None
    payload: dict[str, Any] = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,  # pgv.passport_checkpoint/1
        "checkpoint_id": durable_checkpoint_id(checkpoint.checkpoint_id),
        "stage": checkpoint.stage,
        "confirmed_at": checkpoint.confirmed_at,
        "confirmed_at_reason": None,
        "snapshot_ref": snapshot_ref,
        "previous_snapshot_ref": previous_snapshot_ref,
        "flags": {
            "created": bool(created_snapshot),
            "reused": not created_snapshot,
            # Не заявляется: session-контур не производит доказуемо
            # отличный от reused unchanged-случай (см. докстринг модуля).
            "unchanged": False,
        },
        "stage_refs": dict(stage_refs),
        "context": {
            "run_id": session.run_id,
            "context_id": context_id,
            "data_revision": getattr(session, "data_revision", None),
            "target_column": checkpoint.target_column,
            "entity_id": None,
        },
        "provenance": {"source": provenance},
    }
    if checkpoint.stage == "panel_entry":
        entity_column = _panel_entity_column(session, checkpoint)
        payload["context"]["entity_id"] = entity_column
    return payload


def _panel_entity_column(session: Any, checkpoint: Any) -> Optional[str]:
    """Идентификатор entity-вселенной панели (AC14): entity_column из
    panel_columns контура; недоказуемо -- None (валидатор честно
    отвергнет: panel_entry требует entity-контекст)."""
    columns = (getattr(session, "modeling_artifacts", None) or {}).get(
        "panel_columns"
    ) or {}
    entity_column = columns.get("entity_column")
    return str(entity_column) if entity_column else None


def freeze_passport_checkpoint(
    run_id: str,
    subject: Any,
    *,
    session: Any,
    session_id: str = "",
    checkpoint: Any,
    created_snapshot: bool,
    provenance: str = "producer_capture",
    created_by: Optional[str] = None,
) -> Any:
    """Заморозить ОДИН чекпоинт EDA handoff как durable-артефакт
    ``pgv.passport_checkpoint/1`` (валидационный гейт + идемпотентность
    по checkpoint_id -- PGV-02).

    Порядок: rs-записи вовлечённых снимков (идемпотентно) -> payload из
    session-фактов -> register_passport_checkpoint.

    Честная семантика частичной rs-записи (PGV-04-FIX F-P4C3):
    rs-записи вовлечённых снимков создаются ДО проверки полноты
    траектории и при честном недоборе (PromotionUnavailable --
    отсутствие обязательной точки) ОСТАЮТСЯ в реестре: это адресуемые
    факты СУЩЕСТВУЮЩИХ session-снимков (не фабкация; идемпотентность
    pgv-passport:{snapshot_id} §8 не нарушена -- повторный вызов и
    добор переиспользуют их без переписывания). Сам durable-чекпоинт
    при недоборе НЕ регистрируется. Существующий producer_key
    возвращается без переписывания (§8)."""
    from apps.api.artifact_promotion import PromotionUnavailable
    from apps.api.visual_artifacts import register_passport_checkpoint

    if not run_id:
        return None  # честный пропуск: трассы/запуска ещё нет
    service = _authorized_service(run_id, subject, session_id)
    _resolve_universe(session, checkpoint)
    confirmed_at = _parse_ts(checkpoint.confirmed_at)
    if confirmed_at is None:
        raise PromotionUnavailable(
            "Время подтверждения чекпоинта недоказуемо -- ничего не "
            "фабкуется (AC12: не догадка)"
        )

    confirmed_snapshot = _checkpoint_snapshot(session, checkpoint)
    confirmed_record, _ = ensure_passport_snapshot_record(
        run_id,
        subject,
        session_snapshot=confirmed_snapshot,
        session_id=session_id,
        # Контекст штампуется на rs-записи только для снимка, созданного
        # этим же подтверждением (доказуемо); reused -- исторический.
        context_id=(
            _current_context_or_none(session) if created_snapshot else None
        ),
        data_revision=(
            getattr(session, "data_revision", None) if created_snapshot else None
        ),
        created_by=created_by,
    )

    previous_ref: Optional[str] = None
    if (
        checkpoint.previous_snapshot_id
        and checkpoint.previous_snapshot_id != checkpoint.snapshot_id
    ):
        previous_snapshot = (
            session.panel_passport_snapshot(checkpoint.previous_snapshot_id)
            if checkpoint.stage == "panel_entry"
            else session.passport_snapshot(checkpoint.previous_snapshot_id)
        )
        if previous_snapshot is not None:
            previous_record, _ = ensure_passport_snapshot_record(
                run_id,
                subject,
                session_snapshot=previous_snapshot,
                session_id=session_id,
                created_by=created_by,
            )
            previous_ref = previous_record.snapshot_id

    stage_refs: dict[str, str] = {}
    if checkpoint.stage == "modeling_entry":
        for stage in ("start", "validation", "exit"):
            stage_snapshot = _stage_snapshot_at(session, stage, confirmed_at)
            if stage_snapshot is None:
                raise PromotionUnavailable(
                    f"Снимок этапа {stage!r} на момент подтверждения "
                    "отсутствует -- честный недобор, ничего не фабкуется "
                    "(AC12/R03; retry после фиксации точки доберёт)"
                )
            record, _ = ensure_passport_snapshot_record(
                run_id,
                subject,
                session_snapshot=stage_snapshot,
                session_id=session_id,
                created_by=created_by,
            )
            stage_refs[stage] = record.snapshot_id
    else:  # panel_entry
        stage_refs["panel"] = confirmed_record.snapshot_id

    payload = build_passport_checkpoint_payload(
        session,
        checkpoint,
        created_snapshot=created_snapshot,
        provenance=provenance,
        snapshot_ref=confirmed_record.snapshot_id,
        previous_snapshot_ref=previous_ref,
        stage_refs=stage_refs,
    )
    return register_passport_checkpoint(
        run_id,
        subject,
        payload=payload,
        session_id=session_id,
        created_by=created_by,
    )


def _current_context_or_none(session: Any) -> Optional[str]:
    try:
        return session.current_context_id()
    except Exception:  # pragma: no cover -- честная деградация
        return None


# ── Backfill (retry без capture) ─────────────────────────────────────


def _record_backfill_entry_failure(
    run_id: str,
    subject: Any,
    session_id: str,
    checkpoint: Any,
    error: BaseException,
) -> None:
    """Durable-receipt сбоя добора КОНКРЕТНОЙ записи (PGV-04-FIX
    F-P4C2). Receipt-семантика -- ЕДИНАЯ точка promotion_integration
    (инвариант 3 «одна точка интеграции»); никогда не бросает."""
    try:
        from apps.api.promotion_integration import _record_failure

        _record_failure(
            run_id=run_id,
            operation="backfill_passport_checkpoint",
            producer_key=(
                "pgv.checkpoint:"
                f"{durable_checkpoint_id(checkpoint.checkpoint_id)}"
            ),
            error=error,
            subject=subject,
            session_id=session_id,
        )
    except Exception:  # pragma: no cover -- receipt не ломает добор
        logger.warning(
            "Passport checkpoint backfill failure receipt could not be "
            "recorded: checkpoint=%s -- %s",
            getattr(checkpoint, "checkpoint_id", ""),
            error,
        )


def backfill_passport_checkpoints(
    run_id: str,
    subject: Any,
    *,
    session: Any,
    session_id: str = "",
) -> dict[str, int]:
    """Добрать durable-чекпоинты для ВСЕХ session-чекпоинтов без
    durable представления (single + panel вселенные, R4-изоляция
    сохраняется: каждая заморозка читает свой скоуп). ТОЛЬКО доказуемые
    session-записи; provenance=legacy_import; существующие (любой
    provenance) пропускаются по producer_key без чтения payload.

    Изоляция per-entry (PGV-04-FIX F-P4C2, паритет sweep-цикла
    notify_modeling_artifacts_updated): честный недобор
    (PromotionUnavailable) -- info-гэп БЕЗ receipt (штатное состояние
    конвейера, retry следующего sweep'а доберёт); прочий сбой ОДНОЙ
    записи (битая легаси-фактура -> ArtifactPayloadInvalid, конфликт,
    KeyError) -- durable-receipt класса сбоя промоушена + счётчик
    failed, добор остальных записей ПРОДОЛЖАЕТСЯ (восстановимая
    доставка: следующий sweep не упирается в блокирующий сбой партии;
    rs-записи, созданные до отказа сбойной записи, -- честные
    адресуемые факты существующих снимков, см. freeze).

    Возвращает счётчики: frozen / skipped_missing_stage_refs / failed
    (ключ failed присутствует только когда сбои доставки были --
    отсутствие ключа означает, что сбоев не было)."""
    counts = {"frozen": 0, "skipped_missing_stage_refs": 0}
    if not run_id:
        return counts
    from apps.api.artifact_promotion import PromotionUnavailable

    service = _authorized_service(run_id, subject, session_id)
    # F-P4C1: панельные чекпоинты -- РЕАЛЬНОЕ поле session-контура
    # panel_entry_checkpoints (ранее читалось несуществующее
    # panel_passport_checkpoints: панель молчаливо не добиралась --
    # «retry без capture» §13 для panel_entry не enforced).
    session_checkpoints = list(
        getattr(session, "passport_checkpoints", None) or []
    ) + list(getattr(session, "panel_entry_checkpoints", None) or [])
    for checkpoint in session_checkpoints:
        producer_key = f"pgv.checkpoint:{durable_checkpoint_id(checkpoint.checkpoint_id)}"
        try:
            if service.find_by_producer(run_id, producer_key) is not None:
                continue  # уже заморожен (любой provenance) -- не трогаем
            freeze_passport_checkpoint(
                run_id,
                subject,
                session=session,
                session_id=session_id,
                checkpoint=checkpoint,
                created_snapshot=bool(checkpoint.created_snapshot),
                provenance="legacy_import",
            )
            counts["frozen"] += 1
        except PromotionUnavailable as exc:
            # Честный недобор (нет точек траектории/снимка): не сбой,
            # retry следующего sweep'а доберёт. Не receipt.
            logger.info(
                "Passport checkpoint backfill skipped (honest gap): "
                "run=%s checkpoint=%s -- %s",
                run_id,
                checkpoint.checkpoint_id,
                exc,
            )
            counts["skipped_missing_stage_refs"] += 1
        except Exception as exc:
            # F-P4C2: сбой доставки КОНКРЕТНОЙ записи не прерывает добор
            # остальных (per-entry изоляция -- паритет sweep-цикла);
            # сбойная запись получает durable-receipt (класс сбоя
            # промоушена), добор продолжается.
            _record_backfill_entry_failure(
                run_id, subject, session_id, checkpoint, exc
            )
            counts["failed"] = counts.get("failed", 0) + 1
    return counts
