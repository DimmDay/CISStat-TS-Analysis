# apps/api/visual_artifacts.py
"""
Task PGV-02 (spec_passport_graphics_visual.md §6/§8/§10.2/§13, строка
PGV-02): durable inputs научных визуализаций и паспортов -- валидаторы
payload'ов, freeze-оркестрация и durable-чтение.

ПОСТАНОВКА (§13): «Durable inputs/V01/P01/P02; точки изменения --
artifact_store/report_snapshot/SQL/validators; критерий -- versioned
migrations и legacy D01-D12/readers работают».

СОСТОЯНИЕ ИСХОДНИКОВ: PGV-01 зафиксировал версионированные контракты
VisualResult/1 + VisualPrintSnapshot/1 (printSchema.ts -- источник
истины, config/print_schema.json -- твин, apps/api/print_schema.py --
Python-зеркало правил preflight). Эта поставка замыкает контракты на
durable-слой: артефакты kind=visual_result / visual_print_snapshot /
passport_checkpoint регистрируются через ЕДИНУЮ точку producer→artifact
(PromotionService._persist, паттерн DOCLOG-1) с обязательной валидацией
payload (честный отказ вместо «готовой» картинки, §8).

КЛЮЧЕВЫЕ РЕШЕНИЯ:

1. ВАЛИДАЦИОННЫЙ ГЕЙТ. Registry не видит bytes (metadata-only), поэтому
   валидация -- в persist_visual_artifact (artifact_promotion) до
   staging: невалидный payload НЕ регистрируется вовсе (AC12-дух: gap,
   не ноль). visual_result/visual_print_snapshot проверяются зеркалом
   PGV-01; checkpoint -- собственным валидатором pgv.passport_checkpoint/1.

2. ИДЕМПОТЕНТНОСТЬ по producer_key (§11: «Idempotency scoped по
   subject/tenant/run/action+payload digest; иной payload с прежним
   key -- 409»):
     visual_result          -> pgv.visual_result:{view_id}:{result_ref}
     visual_print_snapshot  -> pgv.print_snapshot:{view_id}:{digest|reason}
     passport_checkpoint    -> pgv.checkpoint:{checkpoint_id}   (§8)
   Тот же ключ + тот же контент -- существующий артефакт; тот же ключ +
   другой контент -- ArtifactConflictError (409-семантика, честная).

3. CAS freeze (PGV-AC07): freeze сверяет expected_context снапшота
   (или явные expected_* аргументы) с текущим durable-состоянием запуска;
   расхождение -- PrintContextConflict (маппится роутерами в 409
   context_changed), НИЧЕГО не регистрируется. Демо-скоуп без контекста
   CAS не проходит (нет чего сверять -- честно).

4. ЧЕСТНЫЕ NULL-ПРИЧИНЫ (§6/§8): confirmed_at -- значение XOR причина
   (legacy_unknown); reused/unchanged чекпоинт обязан нести ссылку на
   исходный снимок и подтверждение (AC11); unchanged не совмещается с
   created (никакой четвёртой физической копии паспорта); panel_entry
   требует entity-контекст (AC14: панели не смешиваются).

5. DURABLE READ (субстрат AC09): list_visual_results /
   get_passport_checkpoint читают registry+ObjectStore БЕЗ
   SessionStore/Redis; полный PassportHistoryReader -- PGV-05.

ИНВАРИАНТ: экспорт/freeze НЕ запускает научный расчёт и не меняет
scientific ledger (§3.1) -- модуль только переносит УЖЕ вычисленный
результат в durable слой (§6: «результат переносится из фактического
response в durable слой идемпотентно»).
"""
from __future__ import annotations

import re
from typing import Any, Optional

from apps.api.print_schema import (
    PRINT_RESULT_SCHEMA_VERSION,
    PRINT_SNAPSHOT_SCHEMA_VERSION,
    PrintSchemaViolation,
    _violation,
    load_visual_registry,
    resolve_scope,
    validate_print_snapshot,
    validate_visual_result,
)

# ── Контракты версий схем durable inputs ─────────────────────────────

CHECKPOINT_SCHEMA_VERSION = "pgv.passport_checkpoint/1"

VISUAL_ARTIFACT_SCHEMA_VERSIONS: dict[str, str] = {
    "visual_result": PRINT_RESULT_SCHEMA_VERSION,
    "visual_print_snapshot": PRINT_SNAPSHOT_SCHEMA_VERSION,
    "passport_checkpoint": CHECKPOINT_SCHEMA_VERSION,
}

VISUAL_ARTIFACT_KIND_NAMES = frozenset(VISUAL_ARTIFACT_SCHEMA_VERSIONS)

CHECKPOINT_STAGES = ("modeling_entry", "panel_entry")
PROVENANCE_SOURCES = ("producer_capture", "legacy_import", "session_replay")

_SNAPSHOT_REF_PATTERN = re.compile(r"^rs-[0-9a-f]{32}$")
_CHECKPOINT_ID_PATTERN = re.compile(r"^pck-[0-9a-zA-Z][0-9a-zA-Z_.:-]{0,127}$")

# ── Ошибки (роутеры PGV-13/15 маппят: 409/422) ───────────────────────


class ArtifactPayloadInvalid(ValueError):
    """Payload не соответствует контракту схемы (§6/§8): честный отказ,
    ничего не регистрируется. violations -- список PrintSchemaViolation
    (стабильные коды нарушений print-слоя)."""

    def __init__(self, violations: list[PrintSchemaViolation]) -> None:
        summary = "; ".join(
            f"{v.code}@{v.path}: {v.message}" for v in violations[:5]
        )
        super().__init__(f"visual artifact payload invalid: {summary}")
        self.violations = violations


class PrintContextConflict(RuntimeError):
    """CAS freeze (PGV-AC07): ожидаемый контекст/ревизия данных не
    совпали с текущим durable-состоянием запуска -- 409 context_changed;
    клиент выбирает обновление или сохранённую версию."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.error_code = "context_changed"


# ── Валидаторы ───────────────────────────────────────────────────────


def _rec(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _site_for_view(view_id: str) -> dict[str, Any] | None:
    for site in load_visual_registry()["sites"]:
        if site.get("view_id") == view_id:
            return site
    return None


def validate_passport_checkpoint(
    checkpoint: Any,
) -> list[PrintSchemaViolation]:
    """Валидация pgv.passport_checkpoint/1 (spec §8): checkpoint_id,
    stage, confirmed_at, snapshot/previous refs, flags, точные stage-refs
    на момент подтверждения и context. Правила честности: missing
    confirmed_at -- gap с причиной, не выдуманная дата (AC12);
    reused/unchanged требуют ссылку на исходный снимок (AC11);
    panel_entry отдельно от single-series (AC14)."""
    out: list[PrintSchemaViolation] = []
    if not isinstance(checkpoint, dict):
        return [_violation("missing_field", "(root)", "checkpoint must be an object")]

    if checkpoint.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
        out.append(
            _violation(
                "schema_version_mismatch",
                "schema_version",
                f"ожидается {CHECKPOINT_SCHEMA_VERSION}",
            )
        )

    checkpoint_id = _str(checkpoint.get("checkpoint_id"))
    if checkpoint_id is None:
        out.append(_violation("missing_field", "checkpoint_id", "checkpoint_id обязателен"))
    elif not _CHECKPOINT_ID_PATTERN.match(checkpoint_id):
        out.append(
            _violation("invalid_value", "checkpoint_id", "формат pck-* (идемпотентность §8)")
        )

    stage = _str(checkpoint.get("stage"))
    if stage is None:
        out.append(_violation("missing_field", "stage", "stage обязателен"))
    elif stage not in CHECKPOINT_STAGES:
        out.append(
            _violation(
                "invalid_value",
                "stage",
                f"stage обязан быть одним из {list(CHECKPOINT_STAGES)}",
            )
        )

    # confirmed_at -- значение XOR честная причина (AC12: утраченная
    # дата легаси -- legacy_unknown, не догадка; время промоушена НЕ
    # подставляется вместо времени подтверждения).
    confirmed_at = _str(checkpoint.get("confirmed_at"))
    confirmed_at_reason = _str(checkpoint.get("confirmed_at_reason"))
    if confirmed_at is None and confirmed_at_reason is None:
        out.append(
            _violation(
                "missing_date",
                "confirmed_at",
                "confirmed_at XOR явная причина отсутствия (AC12)",
            )
        )
    elif confirmed_at is not None and confirmed_at_reason is not None:
        out.append(
            _violation(
                "ambiguous_source_hash",
                "confirmed_at",
                "confirmed_at и reason взаимоисключающи",
            )
        )

    # Ссылка на снимок подтверждения: created -- НОВЫЙ снимок,
    # reused/unchanged -- ИСХОДНЫЙ (AC11: подтверждение + ссылка на
    # источник, без ложной четвёртой копии).
    snapshot_ref = _str(checkpoint.get("snapshot_ref"))
    if snapshot_ref is None:
        out.append(
            _violation(
                "missing_required_ref",
                "snapshot_ref",
                "ссылка на снимок подтверждения обязательна (AC11)",
            )
        )
    elif not _SNAPSHOT_REF_PATTERN.match(snapshot_ref):
        out.append(
            _violation("invalid_value", "snapshot_ref", "формат rs-* (report snapshot)")
        )
    previous_ref = _str(checkpoint.get("previous_snapshot_ref"))
    if previous_ref is not None and not _SNAPSHOT_REF_PATTERN.match(previous_ref):
        out.append(
            _violation("invalid_value", "previous_snapshot_ref", "формат rs-*")
        )

    # Flags (§8): created/reused/unchanged. Ровно одно из created|reused;
    # unchanged -- частный случай reused (исходный снимок переиспользуется).
    flags = _rec(checkpoint.get("flags"))
    created = flags.get("created") is True
    reused = flags.get("reused") is True
    unchanged = flags.get("unchanged") is True
    if created == reused:
        out.append(
            _violation(
                "conflicting_flags",
                "flags",
                "ровно одно из created|reused истинно (AC11)",
            )
        )
    if unchanged and created:
        out.append(
            _violation(
                "conflicting_flags",
                "flags.unchanged",
                "unchanged не создаёт новую физическую копию паспорта (AC11)",
            )
        )
    if unchanged and not reused:
        out.append(
            _violation(
                "conflicting_flags",
                "flags.unchanged",
                "unchanged подразумевает reused исходного снимка",
            )
        )

    # Точные refs этапа на момент подтверждения (§8): modeling_entry --
    # start/validation/exit; panel_entry -- panel (AC14: панели отдельно).
    stage_refs = _rec(checkpoint.get("stage_refs"))
    if stage == "modeling_entry":
        for key in ("start", "validation", "exit"):
            ref = _str(stage_refs.get(key))
            if ref is None:
                out.append(
                    _violation(
                        "missing_required_ref",
                        f"stage_refs.{key}",
                        "точная ссылка этапа обязательна (§8)",
                    )
                )
            elif not _SNAPSHOT_REF_PATTERN.match(ref):
                out.append(
                    _violation("invalid_value", f"stage_refs.{key}", "формат rs-*")
                )
    elif stage == "panel_entry":
        ref = _str(stage_refs.get("panel"))
        if ref is None:
            out.append(
                _violation(
                    "missing_required_ref",
                    "stage_refs.panel",
                    "панельный снимок обязателен (AC14)",
                )
            )
        elif not _SNAPSHOT_REF_PATTERN.match(ref):
            out.append(
                _violation("invalid_value", "stage_refs.panel", "формат rs-*")
            )

    # Context подтверждения (§8): run/context/revision; entity_id
    # обязателен для panel_entry (панели не смешиваются с single-series).
    context = _rec(checkpoint.get("context"))
    if _str(context.get("run_id")) is None:
        out.append(
            _violation("missing_required_ref", "context.run_id", "run подтверждения обязателен")
        )
    if _str(context.get("context_id")) is None:
        out.append(
            _violation(
                "missing_required_ref", "context.context_id", "context подтверждения обязателен"
            )
        )
    if context.get("data_revision") is None:
        out.append(
            _violation(
                "missing_required_ref",
                "context.data_revision",
                "ревизия данных подтверждения обязательна",
            )
        )
    if stage == "panel_entry" and _str(context.get("entity_id")) is None:
        out.append(
            _violation(
                "panel_mixing",
                "context.entity_id",
                "panel_entry требует entity-контекст (AC14: не смешиваются)",
            )
        )

    provenance = _rec(checkpoint.get("provenance"))
    source = _str(provenance.get("source"))
    if source is not None and source not in PROVENANCE_SOURCES:
        out.append(
            _violation(
                "invalid_value",
                "provenance.source",
                f"источник должен быть одним из {list(PROVENANCE_SOURCES)}",
            )
        )
    return out


def validate_visual_artifact_payload(
    kind: str, payload: Any, *, site: dict[str, Any] | None = None
) -> list[PrintSchemaViolation]:
    """Диспетчер валидации durable payloads по kind. Для
    visual_print_snapshot сайт реестра PGV-00 резолвится по view_id
    (unknown site -- violation `unknown_view`, spec §5)."""
    if kind == "visual_result":
        violations = validate_visual_result(payload)
        view_id = _str(_rec(payload).get("view_id")) if isinstance(payload, dict) else None
        if view_id is not None and _site_for_view(view_id) is None:
            violations.append(
                _violation("unknown_view", "view_id", f"view {view_id!r} вне реестра PGV-00")
            )
        return violations
    if kind == "visual_print_snapshot":
        if not isinstance(payload, dict):
            return [_violation("missing_field", "(root)", "print snapshot must be an object")]
        view_id = _str(payload.get("view_id"))
        resolved = site if site is not None else (
            _site_for_view(view_id) if view_id else None
        )
        violations = validate_print_snapshot(payload, resolved)
        if view_id is not None and resolved is None:
            violations.append(
                _violation("unknown_view", "view_id", f"view {view_id!r} вне реестра PGV-00")
            )
        return violations
    if kind == "passport_checkpoint":
        return validate_passport_checkpoint(payload)
    return [_violation("invalid_value", "kind", f"kind {kind!r} не является visual artifact kind")]


# ── Producer key conventions (идемпотентность §11) ───────────────────


def visual_result_producer_key(payload: dict[str, Any]) -> str:
    """pgv.visual_result:{view_id}:{result_ref} -- тот же результат
    переносится идемпотентно; пересчитанный результат (другой result_ref)
    -- НОВЫЙ immutable артефакт (старые не переписываются, §8)."""
    view_id = _str(payload.get("view_id")) or "unknown"
    result_ref = (
        _str(_rec(payload.get("execution")).get("result_ref")) or "unknown"
    )
    return f"pgv.visual_result:{view_id}:{result_ref}"


def print_snapshot_producer_key(payload: dict[str, Any]) -> str:
    """pgv.print_snapshot:{view_id}:{digest|reason} -- снапшот
    идентичен frozen результату; подмена контента при том же ключе --
    конфликт (честная 409-семантика)."""
    view_id = _str(payload.get("view_id")) or "unknown"
    result = _rec(payload.get("result"))
    identity = _str(result.get("result_digest")) or _str(
        result.get("result_digest_reason")
    ) or "unknown"
    return f"pgv.print_snapshot:{view_id}:{identity}"


def checkpoint_producer_key(payload: dict[str, Any]) -> str:
    """pgv.checkpoint:{checkpoint_id} -- идемпотентность по checkpoint_id
    (§8)."""
    return f"pgv.checkpoint:{_str(payload.get('checkpoint_id')) or 'unknown'}"


# ── CAS freeze (PGV-AC07) ────────────────────────────────────────────


def _authorized_run(run_id: str, subject: Any, session_id: str) -> Any:
    """Единая авторизация write через PromotionService (R09/T7):
    uniform-отказ без дисклоужения существования."""
    from apps.api.artifact_promotion import PromotionDenied, PromotionService

    service = PromotionService.create_default()
    try:
        run = service._authorized_run(run_id, subject, session_id, action="write")
    except PromotionDenied:
        raise
    return service, run


def _check_context_cas(
    run: Any,
    *,
    expected_context_id: Optional[str],
    expected_data_revision: Optional[int],
    source: str,
) -> None:
    """Сверка ожиданий клиента с durable-состоянием запуска; расхождение
    -- PrintContextConflict (409 context_changed, PGV-AC07), НИЧЕГО не
    регистрируется."""
    if expected_context_id is not None and run.context_id != expected_context_id:
        raise PrintContextConflict(
            f"{source}: context изменился "
            f"(ожидалось {expected_context_id!r}, текущий {run.context_id!r}) -- "
            "409 context_changed: обновите представление или выберите "
            "сохранённую версию"
        )
    if expected_data_revision is not None and run.data_revision != expected_data_revision:
        raise PrintContextConflict(
            f"{source}: data_revision изменилась "
            f"(ожидалась {expected_data_revision!r}, текущая {run.data_revision!r}) -- "
            "409 context_changed"
        )


# ── Freeze-оркестрация (durable inputs) ──────────────────────────────


def freeze_visual_result(
    run_id: str,
    subject: Any,
    *,
    payload: dict[str, Any],
    session_id: str = "",
    expected_context_id: Optional[str] = None,
    expected_data_revision: Optional[int] = None,
    created_by: Optional[str] = None,
) -> Any:
    """Freeze VisualResult/1: нормализованные данные УЖЕ вычисленного
    результата переносятся в durable слой идемпотентно (§6). Валидация
    payload обязательна; CAS -- по явным expected_* (producer_freeze в
    момент фиксации результата; None = без CAS, первый explicit export)."""
    service, run = _authorized_run(run_id, subject, session_id)
    _check_context_cas(
        run,
        expected_context_id=expected_context_id,
        expected_data_revision=expected_data_revision,
        source="freeze_visual_result",
    )
    return service.persist_visual_artifact(
        run_id,
        subject,
        kind="visual_result",
        payload=payload,
        producer_key=visual_result_producer_key(payload),
        session_id=session_id,
        context_id=getattr(run, "context_id", None),
        data_revision=getattr(run, "data_revision", None),
        refs={
            "view_id": payload.get("view_id"),
            "result_ref": _rec(payload.get("execution")).get("result_ref"),
        },
        created_by=created_by,
    )


def freeze_visual_print_snapshot(
    run_id: str,
    subject: Any,
    *,
    payload: dict[str, Any],
    session_id: str = "",
    result_artifact_id: Optional[str] = None,
    created_by: Optional[str] = None,
) -> Any:
    """Freeze VisualPrintSnapshot/1: frozen печатный вход renderer'а.
    CAS -- по expected_context снапшота против текущего состояния запуска
    (PGV-AC07; demo-скоуп без контекста не сверяется). Зависимость
    visual_result пинится с причиной (§16)."""
    service, run = _authorized_run(run_id, subject, session_id)
    expected = _rec(payload.get("expected_context"))
    expected_context_id = _str(expected.get("context_id"))
    raw_revision = expected.get("data_revision")
    # Контракт PGV-01 хранит ревизию строкой; допуск int -- паритет твина.
    if isinstance(raw_revision, int):
        expected_data_revision: Optional[int] = raw_revision
    elif isinstance(raw_revision, str) and raw_revision.strip().isdigit():
        expected_data_revision = int(raw_revision)
    else:
        expected_data_revision = None
    if expected_context_id is not None or expected_data_revision is not None:
        _check_context_cas(
            run,
            expected_context_id=expected_context_id,
            expected_data_revision=expected_data_revision,
            source="freeze_visual_print_snapshot",
        )
    dependencies = [result_artifact_id] if result_artifact_id else []
    artifact = service.persist_visual_artifact(
        run_id,
        subject,
        kind="visual_print_snapshot",
        payload=payload,
        producer_key=print_snapshot_producer_key(payload),
        session_id=session_id,
        dependencies=dependencies,
        context_id=getattr(run, "context_id", None),
        data_revision=getattr(run, "data_revision", None),
        refs={
            "view_id": payload.get("view_id"),
            "scope": payload.get("scope"),
            "profile_id": _rec(payload.get("print")).get("profile_id"),
        },
        created_by=created_by,
    )
    # §16: metadata graph хранит ПРИЧИНЫ ссылок -- pin зависимости.
    for dependency_id in dependencies:
        service.registry.pin_ref(
            run_id,
            "artifact",
            dependency_id,
            reason=f"print_snapshot:{artifact.artifact_id}",
            created_by=created_by or getattr(subject, "subject_id", None),
        )
    return artifact


def register_passport_checkpoint(
    run_id: str,
    subject: Any,
    *,
    payload: dict[str, Any],
    session_id: str = "",
    created_by: Optional[str] = None,
) -> Any:
    """Регистрация passport_checkpoint (§8): факт подтверждения EDA
    handoff; идемпотентность по checkpoint_id. Ссылки (rs-*) --
    в report_snapshot реестре (защищён отдельно), artifact-pins не
    требуются."""
    service, _run = _authorized_run(run_id, subject, session_id)
    return service.persist_visual_artifact(
        run_id,
        subject,
        kind="passport_checkpoint",
        payload=payload,
        producer_key=checkpoint_producer_key(payload),
        session_id=session_id,
        dependencies=[],
        refs={
            "checkpoint_id": payload.get("checkpoint_id"),
            "stage": payload.get("stage"),
            "snapshot_ref": payload.get("snapshot_ref"),
        },
        created_by=created_by,
    )


# ── Durable read (субстрат AC09; полный reader -- PGV-05) ────────────


def list_visual_results(
    run_id: str, *, view_id: Optional[str] = None
) -> list[Any]:
    """Все visual_result запуска (опционально по view_id) -- чтение из
    реестра БЕЗ SessionStore/Redis; копии записей (R1)."""
    from apps.api.artifact_store import get_artifact_registry

    artifacts = get_artifact_registry().list_artifacts(run_id, kind="visual_result")
    if view_id is None:
        return artifacts
    return [a for a in artifacts if a.refs.get("view_id") == view_id]


def list_visual_print_snapshots(
    run_id: str, *, view_id: Optional[str] = None
) -> list[Any]:
    from apps.api.artifact_store import get_artifact_registry

    artifacts = get_artifact_registry().list_artifacts(run_id, kind="visual_print_snapshot")
    if view_id is None:
        return artifacts
    return [a for a in artifacts if a.refs.get("view_id") == view_id]


def get_passport_checkpoint(run_id: str, checkpoint_id: str) -> Any | None:
    """Чекпоинт по checkpoint_id (идемпотентный ключ §8) -- None без
    фабкации отсутствующего факта."""
    from apps.api.artifact_store import get_artifact_registry

    for artifact in get_artifact_registry().list_artifacts(run_id, kind="passport_checkpoint"):
        if artifact.refs.get("checkpoint_id") == checkpoint_id:
            return artifact
    return None
