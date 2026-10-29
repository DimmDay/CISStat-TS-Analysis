# apps/api/passport_history.py
"""
Task PGV-05 (spec_passport_graphics_visual.md §8/§10/§13, строка
PGV-05): PassportHistoryReader -- чтение durable-истории паспортов
свойств ряда из registry/ObjectStore, НЕ из SessionStore.

ПОСТАНОВКА (§13): «PassportHistoryReader; точки изменения --
passport_documents/ObjectStore/refs; критерий -- Чтение без
Redis/DataFrame, schema gaps/legacy_unknown честны».

СУБСТРАТ (PGV-02/03/04): rs-записи снимков паспортов (ReportSnapshot,
kinds=["D02"], idempotency_key ``pgv-passport:{session_snapshot_id}``),
паспортные артефакты (kind="passport", producer_key
``passport:{session_snapshot_id}``, C03) и durable-чекпоинты
(kind="passport_checkpoint", ``pgv.passport_checkpoint/1``, PGV-04).
Reader -- ТОЛЬКО ЧТЕНИЕ: ни одного вызова capture/promotion, ни одной
записи; сессия (SessionStore/Redis/DataFrame) не затрагивается (AC09).

КОНТРАКТ pgv.passport_history/1 (§8 «Snapshot включает»):

* snapshot-запись: snapshot_ref (rs-*), session_snapshot_id, artifact_id,
  stage/universe, ПОЛНОЕ содержимое паспорта (groups/metrics/...)
  КАК ЕСТЬ (не сокращается до rows/columns/claim counts),
  schema/calculation version, target/date/entity, fingerprint,
  context_id/data_revision, data_ref, captured_at (время capture,
  rs-запись) и created_at (время промоушена, артефакт) -- ДВА разных
  доказуемых времени;
* trajectory-чтение: durable-чекпоинт -> замороженные stage_refs +
  подтверждённый снимок + previous; gaps перечисляются явно (§9
  «partial явно перечисляет пропуски»); траектория «на выбранное
  подтверждение EDA», не latest каждого stage (AC10); reused handoff
  резолвится в ИСХОДНЫЙ снимок (AC11);
* списки-пикеры (§10): run/context/target/entity/time, IDs, stage,
  fingerprint/actuality (provenance + created_at), изоляция вселенных
  по stage (AC14: panel_entry отдельно от single-series).

КЛЮЧЕВЫЕ РЕШЕНИЯ ЧЕСТНОСТИ (AC12):

* XOR-конвенция «значение либо явная причина» (прецедент print_schema:
  digest XOR reason): каждое недоказуемое поле -- None + машина-причина
  ``legacy_unknown`` (не существовало/не записано) или
  ``integrity_failure`` (существует, но не верифицируется). Значение
  НЕ выдумывается никогда.
* source_hash и fingerprint -- РАЗНЫЕ поля с определёнными алгоритмами
  (§8): source_hash = SHA-256 канонического JSON payload'а паспортного
  артефакта (identity КОНТЕНТА, == payload_sha256 реестра); fingerprint
  = series_fingerprint данных на capture (identity ДАННЫХ, алгоритм
  app.core.passport.series_fingerprint).
* Целостность: ObjectStore content-addressed ключ (T8) + сверка
  payload_sha256 реестра с прочитанными байтами; расхождение/порча ->
  content_status="corrupt" с деталью, контент не выдаётся; captured_at
  при этом остаётся доказуемым из rs-метаданных (не выдуманная дата).
* Связь rs-записи с артефактом: зависимость ``artifact:{id}`` (причина
  ``passport_record:*``), fallback -- producer-ключ по session
  snapshot_id (порядок промоушена C03/PGV-04); оба источника --
  доказуемые registry-факты. payload.snapshot_id сверяется с
  session_snapshot_id (подмена ассоциации -> corrupt).
* Доступ: authorize_run_access(action="read"), единый отказ
  PassportHistoryAccessDenied без дисклоужения существования (AC18-дух);
  глобальные lookup'ы (get_snapshot_record/get_artifact) проверяют
  принадлежность run'у.
* Старые snapshots не переписываются (§8): reader только читает;
  два confirmation'а дают две независимые траектории из замороженных
  refs.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

PASSPORT_HISTORY_SCHEMA_VERSION = "pgv.passport_history/1"

# Алгоритм source_hash (§8: «определение алгоритмов» -- явно).
SOURCE_HASH_ALGORITHM = "sha256(canonical_json)"

# Универс чекпоинта/снимка -> скоуп чтения (R4: панельный контур не
# касается однорядного и наоборот). Паритет passport_checkpoints
# (_STAGE_UNIVERSES) + stage-имена физических снимков однорядного
# контура; дублируется намеренно -- reader не зависит от capture-стороны.
_UNIVERSE_BY_STAGE = {
    "start": "single",
    "validation": "single",
    "exit": "single",
    "modeling_entry": "single",
    "panel_entry": "panel",
}


class PassportHistoryAccessDenied(RuntimeError):
    """Единый отказ доступа к паспортной истории (чужой/неизвестный
    run -- без дисклоужения существования, AC18-дух)."""


# ── Доступ (read-only; единый отказ) ─────────────────────────────────


def _authorized_run(run_id: str, subject: Any, session_id: str) -> None:
    from apps.api.artifact_promotion import ArtifactAccessDenied, PromotionService

    service = PromotionService.create_default()
    try:
        service._authorized_run(run_id, subject, session_id, action="read")
    except ArtifactAccessDenied as exc:
        raise PassportHistoryAccessDenied(
            "Паспортная история недоступна"
        ) from exc


# ── Целостное чтение payload'а артефакта ─────────────────────────────


def _read_artifact_payload(artifact: Any) -> tuple[Optional[dict], Optional[str]]:
    """(payload, integrity_detail): detail None -- байты верифицированы
    (content-key T8 + payload_sha256 реестра) и разобраны; строка --
    честная деталь отказа, контент НЕ выдаётся."""
    from apps.api.artifact_store import ArtifactIntegrityError, get_artifact_object_store

    try:
        data = get_artifact_object_store().read_bytes(artifact.storage_key)
    except ArtifactIntegrityError as exc:
        return None, f"content_key_mismatch: {exc}"
    except (FileNotFoundError, OSError) as exc:
        return None, f"content_unreadable: {exc}"
    if hashlib.sha256(data).hexdigest() != artifact.payload_sha256:
        return None, "payload_sha256_mismatch"
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"payload_not_json: {exc}"
    if not isinstance(payload, dict):
        return None, "payload_not_object"
    return payload, None


def _xor_set(record: dict[str, Any], key: str, value: Any, reason_absent: str) -> None:
    """XOR-конвенция (прецедент print_schema digest XOR reason):
    значение присутствует -> reason None; отсутствует -> None + явная
    причина; оба сразу / выдуманное значение запрещены."""
    record[key] = value
    record[f"{key}_reason"] = None if value is not None else reason_absent


# ── Резолвер snapshot-записи (§8) ────────────────────────────────────


def _passport_artifact_for(run_id: str, record: Any, session_snapshot_id: str) -> Optional[Any]:
    """Паспортный артефакт rs-записи: зависимость ``artifact:{id}``
    (причина ``passport_record:*``) или fallback по producer-ключу
    (порядок промоушена C03/PGV-04). Оба -- registry-факты; run-
    принадлежность проверяется на каждом шаге."""
    from apps.api.artifact_store import get_artifact_registry

    registry = get_artifact_registry()
    for dep in record.dependencies or []:
        if not isinstance(dep, str) or not dep.startswith("artifact:"):
            continue
        candidate = registry.get_artifact(dep.split(":", 1)[1])
        if (
            candidate is not None
            and candidate.run_id == run_id
            and candidate.kind == "passport"
        ):
            return candidate
    producer_key = f"passport:{session_snapshot_id}"
    for candidate in registry.list_artifacts(run_id, kind="passport"):
        if candidate.producer_key == producer_key:
            return candidate
    return None


def _snapshot_record(
    run_id: str, snapshot_ref: str, *, at: str
) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
    """(record, gap): snapshot-запись §8 из rs-факта + паспортный
    артефакт; (None, gap) -- разрешить не удалось (запись отсутствует,
    чужая или не паспортная). Content-проблемы -- НЕ gap резолюции, а
    честный content_status внутри записи."""
    from apps.api.passport_checkpoints import PASSPORT_RECORD_IDEMPOTENCY_PREFIX
    from apps.api.report_snapshot import get_snapshot_registry

    def _gap(reason: str, detail: str) -> tuple[None, dict[str, Any]]:
        return None, {
            "at": at,
            "snapshot_ref": snapshot_ref,
            "reason": reason,
            "detail": detail,
        }

    record = get_snapshot_registry().get_snapshot_record(snapshot_ref)
    if record is None:
        return _gap(
            "missing_snapshot_record",
            "rs-запись отсутствует в реестре -- факт не восстанавливается",
        )
    if record.research_run_id != run_id:
        # Чужой снимок: uniform-семантика отсутствия (без дисклоужения).
        return _gap(
            "missing_snapshot_record",
            "rs-запись не принадлежит запуску -- факт не восстанавливается",
        )
    idempotency_key = str(record.idempotency_key or "")
    if (
        not idempotency_key.startswith(PASSPORT_RECORD_IDEMPOTENCY_PREFIX)
        or "D02" not in (record.kinds or [])
    ):
        return _gap(
            "not_a_passport_record",
            "rs-запись не является паспортной (pgv-passport:*, D02)",
        )
    session_snapshot_id = idempotency_key[len(PASSPORT_RECORD_IDEMPOTENCY_PREFIX):]

    item: dict[str, Any] = {
        "schema_version": PASSPORT_HISTORY_SCHEMA_VERSION,
        "snapshot_ref": snapshot_ref,
        "session_snapshot_id": session_snapshot_id,
        "artifact_id": None,
        "stage": None,
        "universe": None,
        "passport": None,
        "content_status": "missing_artifact",
        "content_gap_reason": "passport_artifact_absent",
        "target_column": None,
        "date_column": None,
        "context_id": record.context_id,
        "data_revision": record.data_revision,
        "data_ref": record.data_ref,
        "captured_at": record.captured_at,
        "created_at": None,
        "source_hash_algorithm": SOURCE_HASH_ALGORITHM,
    }
    # XOR-поля: значение либо явная причина (AC12: не догадка).
    _xor_set(item, "fingerprint", None, "legacy_unknown")
    _xor_set(item, "source_hash", None, "legacy_unknown")
    _xor_set(item, "passport_schema_version", None, "legacy_unknown")
    _xor_set(item, "calculation_version", None, "legacy_unknown")

    artifact = _passport_artifact_for(run_id, record, session_snapshot_id)
    if artifact is None:
        # Legacy до C03: rs-факт есть, content-зависимости нет (§8:
        # честный content-гэп, фабкация запрещена).
        return item, None

    item["artifact_id"] = artifact.artifact_id
    item["created_at"] = artifact.created_at
    payload, detail = _read_artifact_payload(artifact)
    if detail is not None:
        item["content_status"] = "corrupt"
        item["content_gap_reason"] = detail
        # Метаданные реестра целы: recorded-хэш остаётся доказуемым
        # фактом ОЖИДАЕМОГО контента (сам контент не выдаётся).
        _xor_set(item, "source_hash", artifact.payload_sha256 or None, "legacy_unknown")
        _xor_set(item, "fingerprint", None, "integrity_failure")
        _xor_set(item, "passport_schema_version", None, "integrity_failure")
        _xor_set(item, "calculation_version", None, "integrity_failure")
        return item, None

    passport_content = payload.get("passport")
    if not isinstance(passport_content, dict):
        item["content_status"] = "corrupt"
        item["content_gap_reason"] = "payload_passport_not_object"
        _xor_set(item, "source_hash", artifact.payload_sha256 or None, "legacy_unknown")
        _xor_set(item, "fingerprint", None, "integrity_failure")
        return item, None
    if payload.get("snapshot_id") != session_snapshot_id:
        # Подмена ассоциации payload<->rs-запись -- integrity failure
        # (контент не выдаётся под чужой идентичностью).
        item["content_status"] = "corrupt"
        item["content_gap_reason"] = "snapshot_id_mismatch"
        _xor_set(item, "source_hash", artifact.payload_sha256 or None, "legacy_unknown")
        _xor_set(item, "fingerprint", None, "integrity_failure")
        return item, None

    stage = payload.get("stage") or artifact.refs.get("stage")
    item.update({
        "content_status": "present",
        "content_gap_reason": None,
        "passport": passport_content,
        "stage": stage,
        "universe": _UNIVERSE_BY_STAGE.get(str(stage)) if stage else None,
        "target_column": payload.get("target_column"),
        "date_column": payload.get("date_column"),
    })
    _xor_set(item, "fingerprint", payload.get("fingerprint"), "legacy_unknown")
    _xor_set(item, "source_hash", artifact.payload_sha256 or None, "legacy_unknown")
    # Самоназвание схемы/расчёта: будущие captures могут нести
    # passport_schema_version/calculation_version в payload; текущие --
    # честно legacy_unknown (§8: не догадка, не выдуманный 'v1').
    _xor_set(
        item,
        "passport_schema_version",
        payload.get("passport_schema_version"),
        "legacy_unknown",
    )
    _xor_set(
        item,
        "calculation_version",
        payload.get("calculation_version"),
        "legacy_unknown",
    )
    return item, None


# ── Чекпоинты: реестр + payload ──────────────────────────────────────


def _checkpoint_artifacts(run_id: str) -> list[Any]:
    from apps.api.artifact_store import get_artifact_registry

    return get_artifact_registry().list_artifacts(run_id, kind="passport_checkpoint")


def _find_checkpoint_artifact(run_id: str, checkpoint_id: str) -> Optional[Any]:
    for artifact in _checkpoint_artifacts(run_id):
        if artifact.refs.get("checkpoint_id") == checkpoint_id:
            return artifact
    return None


def _checkpoint_record(run_id: str, artifact: Any) -> dict[str, Any]:
    """Запись чекпоинта для version picker (§10): run/context/target/
    entity/time, IDs, stage, fingerprint/data version, актуальность
    (provenance + created_at). Битый payload -- честная деградация до
    registry-метаданных (refs), integrity_status=corrupt."""
    checkpoint_id = str(artifact.refs.get("checkpoint_id") or "")
    stage = artifact.refs.get("stage")
    record: dict[str, Any] = {
        "schema_version": PASSPORT_HISTORY_SCHEMA_VERSION,
        "checkpoint_id": checkpoint_id,
        "artifact_id": artifact.artifact_id,
        "stage": stage,
        "universe": _UNIVERSE_BY_STAGE.get(str(stage)) if stage else None,
        "confirmed_at": None,
        "confirmed_at_reason": "integrity_failure",
        "flags": None,
        "provenance": None,
        "context": None,
        "snapshot_ref": None,
        "previous_snapshot_ref": None,
        "stage_refs": None,
        "integrity_status": "corrupt",
        "integrity_reason": None,
        "created_at": artifact.created_at,
    }
    _xor_set(record, "fingerprint", None, "integrity_failure")
    payload, detail = _read_artifact_payload(artifact)
    if detail is not None:
        record["integrity_reason"] = detail
        return record
    confirmed, _gap = _snapshot_record(
        run_id, str(payload.get("snapshot_ref") or ""), at="snapshot_ref"
    )
    fingerprint = confirmed.get("fingerprint") if confirmed else None
    if fingerprint:
        fingerprint_reason = None
    elif confirmed is not None:
        fingerprint_reason = confirmed.get("fingerprint_reason") or "legacy_unknown"
    else:
        fingerprint_reason = "missing_snapshot_record"
    record.update({
        "confirmed_at": payload.get("confirmed_at"),
        "confirmed_at_reason": payload.get("confirmed_at_reason"),
        "flags": payload.get("flags"),
        "provenance": payload.get("provenance"),
        "context": payload.get("context"),
        "snapshot_ref": payload.get("snapshot_ref"),
        "previous_snapshot_ref": payload.get("previous_snapshot_ref"),
        "stage_refs": payload.get("stage_refs"),
        "integrity_status": "ok",
        "integrity_reason": None,
    })
    _xor_set(record, "fingerprint", fingerprint, fingerprint_reason or "legacy_unknown")
    return record


# ── Публичное чтение (PassportHistoryReader, pgv.passport_history/1) ─


def read_passport_snapshot(
    run_id: str,
    subject: Any,
    *,
    snapshot_ref: str,
    session_id: str = "",
) -> Optional[dict[str, Any]]:
    """Snapshot-запись §8 по rs-ref: полное содержимое паспорта (когда
    доказуемо), schema/calculation version, target/date, fingerprint,
    context/data_revision, captured/created time, data_ref. None --
    запись отсутствует/чужая/не паспортная (uniform, без фабкации)."""
    _authorized_run(run_id, subject, session_id)
    record, _gap = _snapshot_record(run_id, snapshot_ref, at="snapshot_ref")
    return record


def read_passport_trajectory(
    run_id: str,
    subject: Any,
    *,
    checkpoint_id: str,
    session_id: str = "",
) -> Optional[dict[str, Any]]:
    """Траектория «на выбранное подтверждение EDA» (AC10): замороженные
    stage_refs чекпоинта + подтверждённый снимок + previous. Reused
    handoff резолвится в ИСХОДНЫЙ снимок (AC11, физической копии нет:
    тот же rs-ref под ключом этапа подтверждения). Недостающие ссылки
    -- явные gaps (§9: partial перечисляет пропуски), НЕ фабкация
    (AC12). None -- чекпоинт отсутствует в run'е."""
    _authorized_run(run_id, subject, session_id)
    artifact = _find_checkpoint_artifact(run_id, checkpoint_id)
    if artifact is None:
        return None
    stage = artifact.refs.get("stage")
    trajectory: dict[str, Any] = {
        "schema_version": PASSPORT_HISTORY_SCHEMA_VERSION,
        "checkpoint_ref": checkpoint_id,
        "checkpoint_artifact_id": artifact.artifact_id,
        "stage": stage,
        "universe": _UNIVERSE_BY_STAGE.get(str(stage)) if stage else None,
        "confirmed_at": None,
        "confirmed_at_reason": "integrity_failure",
        "flags": None,
        "provenance": None,
        "context": None,
        "snapshots": {},
        "previous_snapshot": None,
        "gaps": [],
        "integrity_status": "corrupt",
        "integrity_reason": None,
        "created_at": artifact.created_at,
    }
    payload, detail = _read_artifact_payload(artifact)
    if detail is not None:
        trajectory["integrity_reason"] = detail
        trajectory["gaps"].append({
            "at": "checkpoint_payload",
            "snapshot_ref": None,
            "reason": "integrity_failure",
            "detail": detail,
        })
        return trajectory

    trajectory.update({
        "confirmed_at": payload.get("confirmed_at"),
        "confirmed_at_reason": payload.get("confirmed_at_reason"),
        "flags": payload.get("flags"),
        "provenance": payload.get("provenance"),
        "context": payload.get("context"),
        "integrity_status": "ok",
    })

    resolved_refs: set[str] = set()
    snapshots: dict[str, dict[str, Any]] = {}
    for stage_key in sorted(payload.get("stage_refs") or {}):
        ref = str(payload["stage_refs"][stage_key] or "")
        record, gap = _snapshot_record(run_id, ref, at=f"stage_refs.{stage_key}")
        if record is None:
            trajectory["gaps"].append(gap)
            continue
        snapshots[stage_key] = record
        resolved_refs.add(ref)

    confirmed_ref = str(payload.get("snapshot_ref") or "")
    if confirmed_ref:
        if confirmed_ref in resolved_refs:
            # reused/panel: ИСХОДНЫЙ снимок уже разрешён по stage-ключу
            # (AC11: физической копии нет) -- путь подтверждения получает
            # ТОТ ЖЕ факт под ключом этапа чекпоинта (единая rs-запись,
            # два адреса пути; новой записи/контента не создаётся).
            stage_key = str(payload.get("stage") or "confirmed")
            for existing in snapshots.values():
                if existing["snapshot_ref"] == confirmed_ref:
                    snapshots[stage_key] = existing
                    break
        else:
            record, gap = _snapshot_record(run_id, confirmed_ref, at="snapshot_ref")
            if record is None:
                trajectory["gaps"].append(gap)
            else:
                # Ключ этапа подтверждения; запись -- ФИЗИЧЕСКИ одна
                # (created-снимок modeling_entry/panel_entry).
                key = record.get("stage") or payload.get("stage") or "confirmed"
                snapshots[str(key)] = record
            resolved_refs.add(confirmed_ref)

    previous_ref = str(payload.get("previous_snapshot_ref") or "")
    if previous_ref:
        previous_record: Optional[dict[str, Any]] = None
        if previous_ref in resolved_refs:
            for existing in snapshots.values():
                if existing["snapshot_ref"] == previous_ref:
                    previous_record = existing
                    break
        else:
            record, gap = _snapshot_record(
                run_id, previous_ref, at="previous_snapshot_ref"
            )
            if record is None:
                trajectory["gaps"].append(gap)
            else:
                previous_record = record
        trajectory["previous_snapshot"] = previous_record
    trajectory["snapshots"] = snapshots
    return trajectory


def list_passport_snapshots(
    run_id: str,
    subject: Any,
    *,
    universe: Optional[str] = None,
    session_id: str = "",
) -> list[dict[str, Any]]:
    """Все паспортные rs-записи run'а (pgv-passport:*, D02) с полными
    snapshot-записями §8; сортировка по captured_at. universe-фильтр
    (AC14): записи без доказуемого stage (content-гэп) под фильтр не
    попадают -- вселенная недоказуема, приписывать её нельзя."""
    _authorized_run(run_id, subject, session_id)
    from apps.api.passport_checkpoints import PASSPORT_RECORD_IDEMPOTENCY_PREFIX
    from apps.api.report_snapshot import get_snapshot_registry

    items: list[dict[str, Any]] = []
    for record in get_snapshot_registry().list_records(run_id):
        if "D02" not in (record.kinds or []):
            continue
        if not str(record.idempotency_key or "").startswith(
            PASSPORT_RECORD_IDEMPOTENCY_PREFIX
        ):
            continue
        item, _gap = _snapshot_record(run_id, record.snapshot_id, at="list")
        if item is None:  # pragma: no cover -- запись существует по определению
            continue
        if universe is not None and item["universe"] != universe:
            continue
        items.append(item)
    items.sort(key=lambda item: (item["captured_at"] or "", item["snapshot_ref"]))
    return items


def list_passport_checkpoints(
    run_id: str,
    subject: Any,
    *,
    universe: Optional[str] = None,
    session_id: str = "",
) -> list[dict[str, Any]]:
    """Все durable-чекпоинты run'а -- substrate version picker'а (§10):
    run/context/target/entity/time, IDs, stage, fingerprint/actuality
    (provenance + created_at); сортировка по confirmed_at. universe-
    фильтр изолирует вселенные (AC14)."""
    _authorized_run(run_id, subject, session_id)
    items = [_checkpoint_record(run_id, artifact) for artifact in _checkpoint_artifacts(run_id)]
    if universe is not None:
        items = [item for item in items if item["universe"] == universe]
    items.sort(key=lambda item: (item["confirmed_at"] or "", item["checkpoint_id"]))
    return items
