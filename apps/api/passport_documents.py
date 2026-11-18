# apps/api/passport_documents.py
"""
Task PGV-13 (spec_passport_graphics_visual.md §9/§10.2/§11/§13, строка
PGV-13): P01/P02 builders -- полные паспорта и их сравнение из durable
refs, без DataFrame, reused checkpoint работает.

ПОСТАНОВКА (§13): «P01/P02 builders; точки изменения --
passport_documents/snapshot_builder/lifecycle; критерий -- Полные
паспорта/сравнение из refs, без DataFrame, reused checkpoint работает».

АРХИТЕКТУРА (§10.2/§11): «Восстановить паспорта» -> context/trajectory/
checkpoint -> сохранённые точки/gaps -> один/все -> «Создать печатное
представление». Создаётся печатная ревизия (P01/P02, каталог
pgv.document_catalog/2) с frozen basis из durable print inputs БЕЗ
capture и перерасчёта науки (§3.1, AC06); путь работает без активного
DataFrame и живой cookie-сессии, если сохранены durable-источники (§1,
AC09).

КЛЮЧЕВЫЕ РЕШЕНИЯ (§11/§12.2/§3.3):

1. FROZEN ПЕЧАТНЫЕ ВХОДЫ -- новые versioned artifact kinds
   (passport_print_snapshot -> P01; passport_comparison_snapshot ->
   P02). Контент (полные записи pgv.passport_history/1 / frozen
   сравнение pgv.passport_comparison/1) встраивается В МОМЕНТ сборки --
   рендер не пере-выводит историю и не может «додумать» утраченное
   (AC12); печатная композиция -- компоненты PGV-07 (единственная
   реализация, §4.1), Python не перерисовывает паспорта.
2. БЕЗ CAS current-context (сознательно): восстановление ИСТОРИЧЕСКИХ
   refs -- ожидание контекста клиента к ним не применимо (§3.3 «stale
   относительно текущих данных не уничтожает историческую
   действительность»; контракт §11 несёт refs/checkpoint, не
   expected_context). Целостность -- content-addressed ObjectStore +
   payload_sha256 (T8) и producer_key-конфликт (§11).
3. ИДЕМПОТЕНТНОСТЬ (§11/§12.2): identity -- mode + упорядоченные refs +
   digest (SHA-256 канонического JSON identity-ядер записей/сравнения);
   существующий frozen input переиспользуется -> та же ревизия
   (basis_fingerprint) -> тот же активный/ready job. Дубли не создаются.
4. ЧЕСТНЫЕ ГРАНИЦЫ: доступ через reader'ы PGV-05/06 (read) и
   PromotionService._authorized_run(write) -- чужой run -- единый
   PassportDocumentAccessDenied (AC18-дух); несовместимые паспорта --
   PassportDocumentIncompatible (409 comparison_incompatible, §9/AC13/
   AC14); отсутствующий checkpoint/ref -- PassportDocumentSource-
   Unavailable (409 source_unavailable; пересчёт запрещён); неверная
   форма запроса -- PassportDocumentInvalidSelection (422). Частичность
   честна: недостающие/битые точки -- gap-записи/гэпы, completeness=
   partial (§9 «partial явно перечисляет пропуски»; §3.6).
5. Reused checkpoint (AC11): trajectory-резолвер PGV-06 возвращает
   подтверждение отдельной строкой и путь без дубликата этапа; builder
   печатает как зафиксировано.

Инвариант §3.1: модуль ТОЛЬКО переносит уже зафиксированное (durable
refs) в печатный контур; никакой науки, никакого SessionStore/pandas/
redis (AST-гейт тестов поставки), никакого DOM.
"""
from __future__ import annotations

import hashlib
from typing import Any, Optional

from apps.api.print_schema import resolve_print_profile

# ── Контракты версий (паритет visual_artifacts) ───────────────────────

PASSPORT_PRINT_SNAPSHOT_SCHEMA_VERSION = "pgv.passport_print_snapshot/1"
PASSPORT_COMPARISON_SNAPSHOT_SCHEMA_VERSION = (
    "pgv.passport_comparison_print_snapshot/1"
)
IDENTITY_DIGEST_ALGORITHM = "sha256(canonical_json)"

# Идентификаторы печатного контракта документа (§10.2: аддитивные типы
# P01/P02; НЕ сайты реестра PGV-00 -- реестр только о научных
# визуализациях, пикер «Документов» -- PGV-15).
P01_VIEW_ID = "passport.document.p01"
P02_VIEW_ID = "passport.document.p02"

P01_TITLE = "Паспорт свойств ряда"
P01_SET_TITLE = "Паспорта свойств ряда: комплект траектории"
P02_TITLE = "Сравнение паспортов свойств ряда"

# Порядок этапов траектории (паритет passport_comparison._STAGE_RANK).
_STAGE_RANK = {
    "start": 0,
    "validation": 1,
    "exit": 2,
    "modeling_entry": 3,
    "panel": 4,
    "panel_entry": 4,
}

DOCUMENT_MODES = ("single", "set", "compare")


# ── Ошибки (роутер маппит: 404/409/422) ───────────────────────────────


class PassportDocumentError(RuntimeError):
    """Базовая ошибка контура паспортных документов (честная, без
    дисклоужения)."""


class PassportDocumentAccessDenied(PassportDocumentError):
    """Чужой/несуществующий run -- uniform отказ (R09/AC18-дух)."""


class PassportDocumentSourceUnavailable(PassportDocumentError):
    """Чекпоинт/снимок не разрешается из durable-слоя (§11
    source_unavailable); пересчёт науки запрещён."""


class PassportDocumentInvalidSelection(PassportDocumentError):
    """Неверная форма запроса (§11 invalid_selection): mode/refs/чекпоинт."""


class PassportDocumentIncompatible(PassportDocumentError):
    """Несовместимые паспорта (§9/AC13/AC14): target/universe/schema/
    cross-context вне явного режима. reasons -- машиночитаемые причины."""

    def __init__(self, reasons: list[str]):
        self.reasons = [str(reason) for reason in reasons]
        super().__init__(
            "Сравнение паспортов несовместимо: " + "; ".join(self.reasons)
        )


# ── Утилиты честности ────────────────────────────────────────────────


def _canonical_digest(value: Any) -> str:
    """SHA-256 канонического JSON (§8: source_hash-алгоритм контура)."""
    from apps.api.artifact_store import canonical_json_bytes

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _record_identity_core(record: dict[str, Any]) -> dict[str, Any]:
    """Identity-ядро записи (§8): адрес + content-статус + доказуемые
    XOR-поля. Не включает полное содержимое паспорта: тот же снимок под
    той же целостностью -- тот же вход (идемпотентность §11)."""
    return {
        "snapshot_ref": record.get("snapshot_ref"),
        "content_status": record.get("content_status"),
        "content_gap_reason": record.get("content_gap_reason"),
        "source_hash": record.get("source_hash"),
        "source_hash_reason": record.get("source_hash_reason"),
        "fingerprint": record.get("fingerprint"),
        "fingerprint_reason": record.get("fingerprint_reason"),
        "stage": record.get("stage"),
    }


def _unique_or_none(values: list[Any]) -> Optional[str]:
    """Единственное доказуемое значение списка либо None (не фабрикация
    «общего» значения при расхождении)."""
    distinct = {str(v) for v in values if v is not None and str(v) != ""}
    return next(iter(distinct)) if len(distinct) == 1 else None


def _record_gaps(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Content-проблемы записей -- честные gaps (§9: missing -- gap,
    не ноль)."""
    gaps: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        status = record.get("content_status")
        if status == "present" and isinstance(record.get("passport"), dict):
            continue
        reason = "content_corrupt" if status == "corrupt" else "content_missing"
        gaps.append({
            "at": f"records.{index}",
            "snapshot_ref": record.get("snapshot_ref"),
            "reason": reason,
            "detail": record.get("content_gap_reason") or str(status),
        })
    return gaps


def _present_artifact_ids(records: list[dict[str, Any]]) -> list[str]:
    """passport-артефакты present-записей (пины зависимостей, §16) --
    в порядке записей, без дублей."""
    out: list[str] = []
    for record in records:
        artifact_id = record.get("artifact_id")
        if (
            record.get("content_status") == "present"
            and isinstance(artifact_id, str)
            and artifact_id
            and artifact_id not in out
        ):
            out.append(artifact_id)
    return out


def _validate_profile(profile_id: str) -> None:
    if resolve_print_profile(profile_id) is None:
        raise PassportDocumentInvalidSelection(
            f"invalid_profile: профиль {profile_id!r} вне каталога PGV-01"
        )


def _snapshot_skeleton(
    *, view_id: str, scope: str, print_kind: str, mode: str,
    profile_id: str, render_requested_at: str, identity: dict[str, Any],
) -> dict[str, Any]:
    """Верхнеуровневая форма паритетна VisualPrintSnapshot/1 -- та же
    рамка печати PrintPageFrame (print/display/dimensions); исторические
    context/data_revision живут В ЗАПИСЯХ (§3.3), верхнеуровневые поля
    не фабрикуются."""
    return {
        "schema_version": (
            PASSPORT_PRINT_SNAPSHOT_SCHEMA_VERSION
            if print_kind == "P01"
            else PASSPORT_COMPARISON_SNAPSHOT_SCHEMA_VERSION
        ),
        "view_id": view_id,
        "scope": scope,
        "documents": {"print_kind": print_kind, "mode": mode},
        "identity": {**identity, "algorithm": IDENTITY_DIGEST_ALGORITHM},
        "refs": {"run_id": None, "target_column": None, "date_column": None},
        "expected_context": {"context_id": None, "data_revision": None},
        "data_artifact": {
            "artifact_id": None,
            "artifact_version": "",
            "source_hash": None,
            "hash_algorithm": None,
            "hash_reason": "not_applicable -- контент встроен в записи",
        },
        "dimensions": {
            "mode": "univariate",
            "target_column": None,
            "date_column": None,
            "entity_column": None,
            "entity_id": None,
        },
        "times": {
            "render_requested_at": render_requested_at,
            "timezone": "UTC",
            "locale": "ru-RU",
        },
        "checkpoint": None,
        "method": {
            "origin": "passport_documents_build",
            "method": "passport_history_read",
            "parameters": {},
        },
        "print": {
            "profile_id": profile_id,
            "page_count": 1,
            "theme": "light-print",
        },
        "renderer_env": {
            "dependency_status": "unknown",
            "unavailable_reason": None,
            "renderer_version": "print-renderer/1",
            "font_profile": "print-fonts-dejavu/1",
        },
        "sensitive": {
            "raw_data_included": False,
            "sensitive_fields_policy": (
                "metadata-only; raw данные не вкладываются (spec §11)"
            ),
        },
    }


# ── Builders (pure от durable-фактов) ────────────────────────────────


def build_passport_print_snapshot(
    run_id: str,
    records: list[dict[str, Any]],
    *,
    mode: str,
    profile_id: str,
    render_requested_at: str,
    title: Optional[str] = None,
    checkpoint_meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Сборка pgv.passport_print_snapshot/1 (P01) из записей истории
    паспортов (PGV-05). ЧИСТАЯ функция: записи встроены целиком
    (groups/metrics/provenance/content_status -- AC09); недостающие/
    битые записи -- секции с честным баннером (AC12), completeness --
    по фактическим content_status (§9). Порядок секций = порядок
    переданных записей (траектория -- путь резолвера)."""
    _validate_profile(profile_id)
    if mode not in ("single", "set"):
        raise PassportDocumentInvalidSelection(
            f"mode {mode!r} недопустим для P01 (single|set)"
        )
    if not records:
        raise PassportDocumentSourceUnavailable(
            "source_unavailable: ни одна запись паспорта не разрешена "
            "(пересчёт науки запрещён)"
        )
    identity_refs = [str(record.get("snapshot_ref") or "") for record in records]
    if not all(identity_refs):
        raise PassportDocumentSourceUnavailable(
            "source_unavailable: у записей отсутствуют доказуемые rs-refs"
        )
    digest = _canonical_digest([_record_identity_core(record) for record in records])
    completeness = (
        "complete"
        if all(
            record.get("content_status") == "present"
            and isinstance(record.get("passport"), dict)
            for record in records
        )
        else "partial"
    )
    sections: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        stage = record.get("stage")
        sections.append({
            "section_id": f"passport:{index}:{str(record.get('snapshot_ref'))[:16]}",
            "renderer_kind": "passport_record",
            "title": f"{P01_TITLE}: {stage}" if stage else P01_TITLE,
            "record": record,
        })
    payload = _snapshot_skeleton(
        view_id=P01_VIEW_ID,
        scope="passport",
        print_kind="P01",
        mode=mode,
        profile_id=profile_id,
        render_requested_at=render_requested_at,
        identity={"mode": mode, "snapshot_refs": identity_refs, "digest": digest},
    )
    payload.update({
        "refs": {
            "run_id": str(run_id),
            "target_column": _unique_or_none(
                [record.get("target_column") for record in records]
            ),
            "date_column": _unique_or_none(
                [record.get("date_column") for record in records]
            ),
        },
        "dimensions": {
            "mode": (
                "panel"
                if any(record.get("universe") == "panel" for record in records)
                else "univariate"
            ),
            "target_column": _unique_or_none(
                [record.get("target_column") for record in records]
            ),
            "date_column": _unique_or_none(
                [record.get("date_column") for record in records]
            ),
            "entity_column": None,
            "entity_id": None,
        },
        "checkpoint": dict(checkpoint_meta) if checkpoint_meta else None,
        "display": {
            "title": title or (P01_TITLE if mode == "single" else P01_SET_TITLE),
            "subtitle": None,
            "detail_level": "expanded",
            "completeness": completeness,
            "gaps": _record_gaps(records),
            "sections": sections,
        },
    })
    _assert_canonical(payload)
    return payload


def build_passport_comparison_print_snapshot(
    run_id: str,
    comparison: dict[str, Any],
    *,
    profile_id: str,
    render_requested_at: str,
) -> dict[str, Any]:
    """Сборка pgv.passport_comparison_print_snapshot/1 (P02) из frozen
    сравнения (PGV-06, pgv.passport_comparison/1). ЧИСТАЯ функция:
    сравнение встроено целиком -- metrics/categorical/list/qualitative,
    definitions (zero-denominator reason), confirmation reused-чекпоинта
    (AC11), gaps/completeness (AC13)."""
    _validate_profile(profile_id)
    if comparison.get("schema_version") != "pgv.passport_comparison/1":
        raise PassportDocumentInvalidSelection(
            "invalid_selection: вход должен быть pgv.passport_comparison/1"
        )
    ordered_refs = [str(ref) for ref in comparison.get("ordered_refs") or []]
    digest = _canonical_digest({
        "mode": comparison.get("mode"),
        "ordered_refs": ordered_refs,
        "engine": (comparison.get("method_versions") or {}).get("engine"),
        "confirmation": comparison.get("confirmation"),
        "checkpoint_ref": (comparison.get("checkpoint") or {}).get(
            "checkpoint_ref"
        ),
    })
    sections = [{
        "section_id": "comparison:main",
        "renderer_kind": "passport_comparison",
        "title": P02_TITLE,
        "comparison": comparison,
    }]
    payload = _snapshot_skeleton(
        view_id=P02_VIEW_ID,
        scope="comparison",
        print_kind="P02",
        mode="compare",
        profile_id=profile_id,
        render_requested_at=render_requested_at,
        identity={"mode": "compare", "snapshot_refs": ordered_refs, "digest": digest},
    )
    payload.update({
        "refs": {"run_id": str(run_id), "target_column": None, "date_column": None},
        "display": {
            "title": P02_TITLE,
            "subtitle": None,
            "detail_level": "expanded",
            "completeness": comparison.get("completeness"),
            "gaps": list(comparison.get("gaps") or []),
            "sections": sections,
        },
    })
    _assert_canonical(payload)
    return payload


def _assert_canonical(payload: dict[str, Any]) -> None:
    from apps.api.artifact_store import SerializationError, canonical_json_bytes

    try:
        canonical_json_bytes(payload)
    except SerializationError as exc:
        raise PassportDocumentInvalidSelection(
            f"invalid_selection: печатный вход неканоничен ({exc})"
        ) from exc


# ── Durable-резолюция (reader'ы PGV-05/06; read-only) ────────────────


def _authorized_run_or_denied(
    run_id: str, subject: Any, session_id: str, *, action: str
) -> None:
    from apps.api.artifact_promotion import (
        ArtifactAccessDenied,
        PromotionDenied,
        PromotionService,
    )

    service = PromotionService.create_default()
    try:
        service._authorized_run(run_id, subject, session_id, action=action)
    except (PromotionDenied, ArtifactAccessDenied) as exc:
        raise PassportDocumentAccessDenied(
            "Паспортные документы недоступны"
        ) from exc


def _resolve_set_records(
    run_id: str,
    subject: Any,
    *,
    checkpoint_id: Optional[str],
    snapshot_refs: list[str],
    session_id: str,
) -> tuple[list[dict[str, Any]], Optional[dict[str, Any]], list[dict[str, Any]]]:
    """Записи комплекта + checkpoint-метаданные + дополнительные гэпы.
    checkpoint_id -- траектория «на выбранное подтверждение EDA»
    (замороженные stage_refs, AC10; reused -- исходный снимок, AC11);
    refs -- записи КАК ЗАДАНЫ (missing ref -- gap-запись, AC12)."""
    from apps.api import passport_history

    if checkpoint_id:
        trajectory = passport_history.read_passport_trajectory(
            run_id, subject, checkpoint_id=checkpoint_id, session_id=session_id
        )
        if trajectory is None:
            raise PassportDocumentSourceUnavailable(
                "source_unavailable: чекпоинт не разрешается из durable-"
                "слоя (пересчёт запрещён)"
            )
        records: list[dict[str, Any]] = []
        for stage_key in sorted(
            (trajectory.get("snapshots") or {}).keys(),
            key=lambda s: (
                _STAGE_RANK.get(str(s), 90),
                str(s),
            ),
        ):
            records.append(trajectory["snapshots"][stage_key])
        extra_gaps: list[dict[str, Any]] = []
        for raw_gap in trajectory.get("gaps") or []:
            gap = dict(raw_gap)
            # Единая uniform-деталь недоступной rs-записи (паритет
            # PGV-06: существование чужой записи не дисклоужируется).
            if gap.get("reason") == "missing_snapshot_record":
                gap["detail"] = (
                    "rs-запись отсутствует/чужая/не паспортная -- "
                    "сравнение не фабкуется"
                )
            extra_gaps.append(gap)
            # Недостающая точка траектории -- gap-ЗАПИСЬ комплекта:
            # печатается баннером по адресу (AC12), не ноль.
            ref = str(gap.get("snapshot_ref") or "")
            if ref:
                records.append(_missing_record(ref, stage=gap.get("at")))
        checkpoint_meta = {
            "checkpoint_id": trajectory.get("checkpoint_ref"),
            "stage": trajectory.get("stage"),
            "confirmed_at": trajectory.get("confirmed_at"),
            "confirmed_at_reason": trajectory.get("confirmed_at_reason"),
            "flags": trajectory.get("flags"),
        }
        return records, checkpoint_meta, extra_gaps

    records = []
    for ref in snapshot_refs:
        record = passport_history.read_passport_snapshot(
            run_id, subject, snapshot_ref=ref, session_id=session_id
        )
        records.append(record if record is not None else _missing_record(ref))
    return records, None, []


def _missing_record(ref: str, *, stage: Any = None) -> dict[str, Any]:
    """Gap-запись отсутствующей/неразрешённой точки (паритет полей
    pgv.passport_history/1; контент не фабрикуется, AC12)."""
    return {
        "schema_version": "pgv.passport_history/1",
        "snapshot_ref": ref,
        "session_snapshot_id": None,
        "artifact_id": None,
        "stage": stage,
        "universe": None,
        "passport": None,
        "content_status": "missing_artifact",
        "content_gap_reason": "missing_snapshot_record",
        "target_column": None,
        "date_column": None,
        "context_id": None,
        "data_revision": None,
        "data_ref": None,
        "captured_at": None,
        "captured_at_reason": "legacy_unknown",
        "created_at": None,
        "source_hash_algorithm": "sha256(canonical_json)",
        "fingerprint": None,
        "fingerprint_reason": "legacy_unknown",
        "source_hash": None,
        "source_hash_reason": "legacy_unknown",
        "passport_schema_version": None,
        "passport_schema_version_reason": "legacy_unknown",
        "calculation_version": None,
        "calculation_version_reason": "legacy_unknown",
    }


def _resolve_comparison(
    run_id: str,
    subject: Any,
    *,
    checkpoint_id: Optional[str],
    snapshot_refs: list[str],
    session_id: str,
) -> dict[str, Any]:
    from apps.api.passport_comparison import (
        PassportComparisonIncompatible,
        resolve_passport_comparison,
    )

    try:
        comparison = resolve_passport_comparison(
            run_id,
            subject,
            checkpoint_id=checkpoint_id,
            snapshot_refs=snapshot_refs or None,
            session_id=session_id,
        )
    except PassportComparisonIncompatible as exc:
        # Несовместимость -- честный отказ с reasons (409, §9/AC13/AC14).
        raise PassportDocumentIncompatible(exc.reasons) from exc
    if comparison is None:
        raise PassportDocumentSourceUnavailable(
            "source_unavailable: чекпоинт не разрешается из durable-слоя "
            "(пересчёт запрещён)"
        )
    return comparison


def _records_for_refs(
    run_id: str, subject: Any, refs: list[str], *, session_id: str
) -> list[dict[str, Any]]:
    """Записи ordered_refs сравнения -- для пинов passport-артефактов
    (§16); недоступные записи пинов не получают (контента нет)."""
    from apps.api import passport_history

    records: list[dict[str, Any]] = []
    for ref in refs:
        record = passport_history.read_passport_snapshot(
            run_id, subject, snapshot_ref=ref, session_id=session_id
        )
        if record is not None:
            records.append(record)
    return records


# ── Lifecycle (§10.2/§11): freeze -> P01/P02 revision -> PNG job ─────


def request_passport_document(
    run_id: str,
    subject: Any,
    *,
    mode: str,
    checkpoint_id: Optional[str] = None,
    snapshot_refs: Optional[list[str]] = None,
    profile_id: str = "figure-landscape",
    redaction_profile: Optional[str] = None,
    session_id: str = "",
    render_requested_at: str,
) -> dict[str, Any]:
    """POST /passport-documents (§11): single/set/compare -> P01/P02
    печатная ревизия + PNG job (202). Наука не запускается (AC06);
    идемпотентность -- §11/§12.2 (тот же refs/checkpoint -- та же
    ревизия и тот же job). redaction_profile None -- каталог
    DEFAULT_REDACTION_PROFILE печатного конвейера (паритет
    request_print_rendition)."""
    from apps.api.document_jobs import DEFAULT_REDACTION_PROFILE

    if redaction_profile is None:
        redaction_profile = DEFAULT_REDACTION_PROFILE
    if mode not in DOCUMENT_MODES:
        raise PassportDocumentInvalidSelection(
            f"invalid_selection: mode {mode!r} -- допустимы {list(DOCUMENT_MODES)}"
        )
    refs = [
        str(ref).strip()
        for ref in (snapshot_refs or [])
        if str(ref).strip()
    ]
    if checkpoint_id and refs:
        raise PassportDocumentInvalidSelection(
            "invalid_selection: checkpoint_id и snapshot_refs "
            "взаимоисключающи"
        )
    if mode == "single" and len(refs) != 1:
        raise PassportDocumentInvalidSelection(
            "invalid_selection: single требует ровно один snapshot_ref"
        )
    if mode == "compare" and not checkpoint_id and len(refs) < 2:
        raise PassportDocumentInvalidSelection(
            "invalid_selection: compare требует checkpoint_id либо "
            "не менее двух snapshot_refs"
        )
    if not checkpoint_id and not refs:
        raise PassportDocumentInvalidSelection(
            "invalid_selection: требуется checkpoint_id либо snapshot_refs"
        )
    _validate_profile(profile_id)

    # Авторизация -- ПЕРВЫЙ шаг (R09/§11): чужой/несуществующий run --
    # uniform отказ ДО чтения durable-содержимого.
    _authorized_run_or_denied(run_id, subject, session_id, action="write")

    comparison: Optional[dict[str, Any]] = None
    checkpoint_meta: Optional[dict[str, Any]] = None
    extra_gaps: list[dict[str, Any]] = []
    if mode == "compare":
        comparison = _resolve_comparison(
            run_id,
            subject,
            checkpoint_id=checkpoint_id,
            snapshot_refs=refs,
            session_id=session_id,
        )
        ordered_refs = [str(ref) for ref in comparison.get("ordered_refs") or []]
        identity_refs = ordered_refs
        digest = _canonical_digest({
            "mode": comparison.get("mode"),
            "ordered_refs": ordered_refs,
            "engine": (comparison.get("method_versions") or {}).get("engine"),
            "confirmation": comparison.get("confirmation"),
            "checkpoint_ref": (comparison.get("checkpoint") or {}).get(
                "checkpoint_ref"
            ),
        })
        pin_records = _records_for_refs(
            run_id, subject, ordered_refs, session_id=session_id
        )
    else:
        records, checkpoint_meta, extra_gaps = _resolve_set_records(
            run_id,
            subject,
            checkpoint_id=checkpoint_id,
            snapshot_refs=refs,
            session_id=session_id,
        )
        if mode == "single" and records and (
            records[0].get("content_status") != "present"
            or not isinstance(records[0].get("passport"), dict)
        ):
            # single -- ОДИН паспорт: если он не разрешается (отсутствует/
            # чужой/не паспортный/битый), печатать нечего -- честный отказ
            # (§11 source_unavailable); пересчёт науки запрещён (AC06).
            raise PassportDocumentSourceUnavailable(
                "source_unavailable: паспорт по ref не разрешается из "
                "durable-слоя (пересчёт запрещён)"
            )
        identity_refs = [str(r.get("snapshot_ref") or "") for r in records]
        digest = _canonical_digest(
            [_record_identity_core(record) for record in records]
        )
        pin_records = records

    producer_key = (
        f"pgv.passport_comparison_print:compare:{','.join(identity_refs)}:"
        f"{digest[:16]}"
        if mode == "compare"
        else f"pgv.passport_print:{mode}:{','.join(identity_refs)}:{digest[:16]}"
    )

    from apps.api.artifact_promotion import PromotionService

    promotion = PromotionService.create_default()
    existing = promotion.find_by_producer(run_id, producer_key)
    if existing is not None:
        # Идемпотентный повтор: frozen input переиспользуется (его время
        # фиксации не переписывается, §8) -> та же ревизия -> тот же job.
        snapshot_artifact = existing
    else:
        if mode == "compare":
            assert comparison is not None
            payload = build_passport_comparison_print_snapshot(
                run_id,
                comparison,
                profile_id=profile_id,
                render_requested_at=render_requested_at,
            )
            freeze = _freeze_comparison
        else:
            payload = build_passport_print_snapshot(
                run_id,
                records,
                mode=mode,
                profile_id=profile_id,
                render_requested_at=render_requested_at,
                checkpoint_meta=checkpoint_meta,
            )
            freeze = _freeze_print
        snapshot_artifact = freeze(
            run_id,
            subject,
            payload=payload,
            dependency_artifact_ids=_present_artifact_ids(pin_records),
            session_id=session_id,
        )

    from apps.api.document_jobs import DocumentDeliveryService

    documents = DocumentDeliveryService.create_default()
    print_kind = "P02" if mode == "compare" else "P01"
    _document, revision, _created = documents.ensure_print_document_revision(
        run_id,
        subject,
        session_id=session_id,
        print_kind=print_kind,
        basis_kind=(
            "passport_comparison_snapshot"
            if mode == "compare"
            else "passport_print_snapshot"
        ),
        basis_artifact_ids=[snapshot_artifact.artifact_id],
        profile_id=profile_id,
    )
    job, _rendition = documents.request_print_rendition(
        revision.print_revision_id,
        format="png",
        subject=subject,
        session_id=session_id,
        redaction_profile=redaction_profile,
    )

    outcome: dict[str, Any] = {
        "run_id": run_id,
        "mode": mode,
        "print_kind": print_kind,
        "document_id": _document.document_id,
        "print_revision_id": revision.print_revision_id,
        "snapshot_artifact_id": snapshot_artifact.artifact_id,
        "job": _job_json(job),
        "status_url": f"/v1/documentation/jobs/{job.job_id}",
    }
    if checkpoint_id:
        outcome["checkpoint_id"] = checkpoint_id
    if refs:
        outcome["snapshot_refs"] = refs
    if mode == "compare" and comparison is not None:
        outcome["comparison"] = {
            "mode": comparison.get("mode"),
            "path": comparison.get("path"),
            "cross_context": comparison.get("cross_context"),
            "completeness": comparison.get("completeness"),
            "gaps": comparison.get("gaps"),
        }
        outcome["completeness"] = comparison.get("completeness")
    else:
        # Сводка комплекта -- из РАЗРЕШЁННЫХ записей (не из payload:
        # идемпотентный повтор использует существующий frozen input,
        # а записи одинаковы по identity -- §11).
        completeness = (
            "complete"
            if all(
                record.get("content_status") == "present"
                and isinstance(record.get("passport"), dict)
                for record in records
            )
            else "partial"
        )
        outcome["completeness"] = completeness
        outcome["display"] = {
            "title": P01_TITLE if mode == "single" else P01_SET_TITLE,
            "completeness": completeness,
            "gaps": extra_gaps + _record_gaps(records),
            "sections": [
                {
                    "snapshot_ref": record.get("snapshot_ref"),
                    "stage": record.get("stage"),
                    "content_status": record.get("content_status"),
                }
                for record in records
            ],
        }
    return outcome


def _freeze_print(
    run_id: str,
    subject: Any,
    *,
    payload: dict[str, Any],
    dependency_artifact_ids: list[str],
    session_id: str,
) -> Any:
    from apps.api.visual_artifacts import freeze_passport_print_snapshot

    return freeze_passport_print_snapshot(
        run_id,
        subject,
        payload=payload,
        session_id=session_id,
        dependency_artifact_ids=dependency_artifact_ids,
    )


def _freeze_comparison(
    run_id: str,
    subject: Any,
    *,
    payload: dict[str, Any],
    dependency_artifact_ids: list[str],
    session_id: str,
) -> Any:
    from apps.api.visual_artifacts import freeze_passport_comparison_snapshot

    return freeze_passport_comparison_snapshot(
        run_id,
        subject,
        payload=payload,
        session_id=session_id,
        dependency_artifact_ids=dependency_artifact_ids,
    )


def _job_json(job: Any) -> dict[str, Any]:
    """Плоская проекция job'а (паритет visual_exports._job_json)."""
    return {
        "job_id": job.job_id,
        "state": job.state,
        "format": job.format,
        "attempt": job.attempt,
        "print_revision_id": getattr(job, "print_revision_id", "") or None,
        "error_code": job.error_code,
        "created_at": job.created_at,
    }


# ── Пикер источников (GET passport-sources, §10/§11) ─────────────────


def list_passport_sources(
    run_id: str, subject: Any, *, session_id: str = ""
) -> dict[str, Any]:
    """GET passport-sources (§11): durable versions/checkpoints/gaps БЕЗ
    session DataFrame (PassportHistoryReader, read-only) -- substrate
    пикера «Документов» (PGV-15)."""
    _authorized_run_or_denied(run_id, subject, session_id, action="read")
    from apps.api import passport_history

    snapshots = passport_history.list_passport_snapshots(
        run_id, subject, session_id=session_id
    )
    checkpoints = passport_history.list_passport_checkpoints(
        run_id, subject, session_id=session_id
    )
    return {
        "run_id": run_id,
        "snapshots": snapshots,
        "checkpoints": checkpoints,
    }
