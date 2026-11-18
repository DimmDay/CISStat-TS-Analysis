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

import logging
import re
from typing import Any, Optional

# Компенсация AC08 (F-P2C5) логируется без дисклоужения контента.
logger = logging.getLogger(__name__)

from apps.api.print_schema import (
    PRINT_RESULT_SCHEMA_VERSION,
    PRINT_SNAPSHOT_SCHEMA_VERSION,
    PrintSchemaViolation,
    _violation,
    load_visual_registry,
    resolve_print_profile,
    resolve_scope,
    validate_print_snapshot,
    validate_visual_result,
)

# ── Контракты версий схем durable inputs ─────────────────────────────

CHECKPOINT_SCHEMA_VERSION = "pgv.passport_checkpoint/1"

# PGV-13 (§10.2/§13): frozen печатные входы документов P01/P02.
PASSPORT_PRINT_SNAPSHOT_SCHEMA_VERSION = "pgv.passport_print_snapshot/1"
PASSPORT_COMPARISON_SNAPSHOT_SCHEMA_VERSION = (
    "pgv.passport_comparison_print_snapshot/1"
)

VISUAL_ARTIFACT_SCHEMA_VERSIONS: dict[str, str] = {
    "visual_result": PRINT_RESULT_SCHEMA_VERSION,
    "visual_print_snapshot": PRINT_SNAPSHOT_SCHEMA_VERSION,
    "passport_checkpoint": CHECKPOINT_SCHEMA_VERSION,
    "passport_print_snapshot": PASSPORT_PRINT_SNAPSHOT_SCHEMA_VERSION,
    "passport_comparison_snapshot": (
        PASSPORT_COMPARISON_SNAPSHOT_SCHEMA_VERSION
    ),
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
    # PGV-02-FIX (F-P2C4): самоссылка -- история «предыдущий снимок =
    # сам снимок» не имеет смысла (§8: previous_snapshot_ref -- ссылка
    # на ПРЕДЫДУЩИЙ снимок цепочки подтверждений).
    if (
        snapshot_ref is not None
        and previous_ref is not None
        and previous_ref == snapshot_ref
    ):
        out.append(
            _violation(
                "invalid_value",
                "previous_snapshot_ref",
                "самоссылка: previous_snapshot_ref обязан отличаться от "
                "snapshot_ref (§8: ссылка на ПРЕДЫДУЩИЙ снимок)",
            )
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
    # PGV-02-FIX (N-P2C1, класс F-D7C2): пустая строка -- «обязательная
    # ревизия» без значения (missing_required_ref); 0 остаётся значением.
    raw_context_revision = context.get("data_revision")
    if raw_context_revision is None or (
        isinstance(raw_context_revision, str) and not raw_context_revision.strip()
    ):
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


def validate_passport_print_snapshot(
    payload: Any,
) -> list[PrintSchemaViolation]:
    """Валидация pgv.passport_print_snapshot/1 (PGV-13, P01; §8/§10.2):
    самодостаточный печатный вход из записей pgv.passport_history/1.
    Правила честности: content_status=corrupt/missing не несёт контента
    (AC12: контент не выдаётся под порчей); completeness согласован с
    фактическими content_status; identity (mode/refs/digest) обязательна
    для идемпотентности §11."""
    out: list[PrintSchemaViolation] = []
    if not isinstance(payload, dict):
        return [_violation("missing_field", "(root)", "print snapshot must be an object")]

    if payload.get("schema_version") != PASSPORT_PRINT_SNAPSHOT_SCHEMA_VERSION:
        out.append(
            _violation(
                "schema_version_mismatch",
                "schema_version",
                f"ожидается {PASSPORT_PRINT_SNAPSHOT_SCHEMA_VERSION}",
            )
        )
    documents = _rec(payload.get("documents"))
    if documents.get("print_kind") != "P01":
        out.append(
            _violation(
                "invalid_value",
                "documents.print_kind",
                "print_kind обязан быть P01",
            )
        )
    if documents.get("mode") not in ("single", "set"):
        out.append(
            _violation("invalid_value", "documents.mode", "mode: single|set")
        )
    if payload.get("scope") != "passport":
        out.append(_violation("invalid_value", "scope", "scope обязан быть passport"))

    print_rec = _rec(payload.get("print"))
    if resolve_print_profile(str(print_rec.get("profile_id") or "")) is None:
        out.append(
            _violation(
                "invalid_profile",
                "print.profile_id",
                "профиль обязан быть из каталога PGV-01",
            )
        )
    if print_rec.get("theme") != "light-print":
        out.append(
            _violation(
                "theme_not_light_print",
                "print.theme",
                "печать -- только light-print (§3.4)",
            )
        )

    times = _rec(payload.get("times"))
    if not str(times.get("render_requested_at") or ""):
        out.append(
            _violation(
                "missing_date",
                "times.render_requested_at",
                "время запроса рендера фиксируется отдельно (§6)",
            )
        )

    identity = _rec(payload.get("identity"))
    refs_list = identity.get("snapshot_refs")
    if not isinstance(refs_list, list) or not refs_list or not all(
        isinstance(ref, str) and _SNAPSHOT_REF_PATTERN.match(ref) for ref in refs_list
    ):
        out.append(
            _violation(
                "missing_required_ref",
                "identity.snapshot_refs",
                "упорядоченные rs-refs обязательны (§11: refs/checkpoint)",
            )
        )
    if not str(identity.get("digest") or ""):
        out.append(
            _violation(
                "missing_field",
                "identity.digest",
                "digest identity обязателен (идемпотентность §11)",
            )
        )

    display = _rec(payload.get("display"))
    sections = display.get("sections")
    if not isinstance(sections, list) or not sections:
        return out + [
            _violation(
                "empty_sections", "display.sections", "секции паспортов обязательны"
            )
        ]
    statuses: list[str] = []
    for index, section in enumerate(sections):
        path = f"display.sections[{index}]"
        section_rec = _rec(section)
        if section_rec.get("renderer_kind") != "passport_record":
            out.append(
                _violation(
                    "invalid_section_kind",
                    f"{path}.renderer_kind",
                    "секция P01 -- только passport_record",
                )
            )
            continue
        record = _rec(section_rec.get("record"))
        if record.get("schema_version") != "pgv.passport_history/1":
            out.append(
                _violation(
                    "invalid_value",
                    f"{path}.record.schema_version",
                    "запись обязана быть pgv.passport_history/1 (PGV-05)",
                )
            )
        status = record.get("content_status")
        statuses.append(str(status))
        if status not in ("present", "missing_artifact", "corrupt"):
            out.append(
                _violation(
                    "invalid_value",
                    f"{path}.record.content_status",
                    "content_status: present|missing_artifact|corrupt",
                )
            )
        ref = record.get("snapshot_ref")
        if not (isinstance(ref, str) and _SNAPSHOT_REF_PATTERN.match(ref)):
            out.append(
                _violation(
                    "invalid_value",
                    f"{path}.record.snapshot_ref",
                    "формат rs-*",
                )
            )
        passport = record.get("passport")
        if status == "present" and not isinstance(passport, dict):
            out.append(
                _violation(
                    "missing_field",
                    f"{path}.record.passport",
                    "present-запись несёт полный паспорт (AC09)",
                )
            )
        if status in ("missing_artifact", "corrupt") and passport is not None:
            out.append(
                _violation(
                    "conflicting_flags",
                    f"{path}.record.passport",
                    "corrupt/missing запись НЕ выдаёт контент (AC12)",
                )
            )
    completeness = display.get("completeness")
    if completeness not in ("complete", "partial"):
        out.append(
            _violation(
                "invalid_value",
                "display.completeness",
                "completeness: complete|partial",
            )
        )
    elif completeness == "complete" and any(s != "present" for s in statuses):
        out.append(
            _violation(
                "conflicting_flags",
                "display.completeness",
                "complete при не-present записи -- фабкация полноты (§9)",
            )
        )
    if not isinstance(display.get("gaps"), list):
        out.append(
            _violation("invalid_value", "display.gaps", "gaps -- список")
        )
    return out


def validate_passport_comparison_print_snapshot(
    payload: Any,
) -> list[PrintSchemaViolation]:
    """Валидация pgv.passport_comparison_print_snapshot/1 (PGV-13, P02;
    §9): frozen сравнение pgv.passport_comparison/1 встроено в секцию;
    completeness снапшота -- честное эхо completeness сравнения."""
    # Ленивый импорт константы PGV-06 (модуль движка тянет scipy/statsmodels
    # -- не утяжеляем импорт durable-слоя).
    from apps.api.passport_comparison import PASSPORT_COMPARISON_SCHEMA_VERSION

    out: list[PrintSchemaViolation] = []
    if not isinstance(payload, dict):
        return [_violation("missing_field", "(root)", "print snapshot must be an object")]

    if payload.get("schema_version") != (
        PASSPORT_COMPARISON_SNAPSHOT_SCHEMA_VERSION
    ):
        out.append(
            _violation(
                "schema_version_mismatch",
                "schema_version",
                f"ожидается {PASSPORT_COMPARISON_SNAPSHOT_SCHEMA_VERSION}",
            )
        )
    documents = _rec(payload.get("documents"))
    if documents.get("print_kind") != "P02":
        out.append(
            _violation(
                "invalid_value",
                "documents.print_kind",
                "print_kind обязан быть P02",
            )
        )
    if payload.get("scope") != "comparison":
        out.append(
            _violation("invalid_value", "scope", "scope обязан быть comparison")
        )

    print_rec = _rec(payload.get("print"))
    if resolve_print_profile(str(print_rec.get("profile_id") or "")) is None:
        out.append(
            _violation(
                "invalid_profile",
                "print.profile_id",
                "профиль обязан быть из каталога PGV-01",
            )
        )
    if print_rec.get("theme") != "light-print":
        out.append(
            _violation(
                "theme_not_light_print",
                "print.theme",
                "печать -- только light-print (§3.4)",
            )
        )

    times = _rec(payload.get("times"))
    if not str(times.get("render_requested_at") or ""):
        out.append(
            _violation(
                "missing_date",
                "times.render_requested_at",
                "время запроса рендера фиксируется отдельно (§6)",
            )
        )

    identity = _rec(payload.get("identity"))
    if not str(identity.get("digest") or ""):
        out.append(
            _violation(
                "missing_field",
                "identity.digest",
                "digest identity обязателен (идемпотентность §11)",
            )
        )

    display = _rec(payload.get("display"))
    sections = display.get("sections")
    if not isinstance(sections, list) or len(sections) != 1:
        return out + [
            _violation(
                "empty_sections",
                "display.sections",
                "P02 -- ровно одна секция сравнения",
            )
        ]
    section_rec = _rec(sections[0])
    if section_rec.get("renderer_kind") != "passport_comparison":
        out.append(
            _violation(
                "invalid_section_kind",
                "display.sections[0].renderer_kind",
                "секция P02 -- только passport_comparison",
            )
        )
    comparison = _rec(section_rec.get("comparison"))
    if comparison.get("schema_version") != PASSPORT_COMPARISON_SCHEMA_VERSION:
        out.append(
            _violation(
                "invalid_value",
                "display.sections[0].comparison.schema_version",
                f"сравнение обязано быть {PASSPORT_COMPARISON_SCHEMA_VERSION} (PGV-06)",
            )
        )
    if comparison.get("mode") not in ("trajectory_checkpoint", "explicit_refs"):
        out.append(
            _violation(
                "invalid_value",
                "display.sections[0].comparison.mode",
                "mode: trajectory_checkpoint|explicit_refs",
            )
        )
    ordered_refs = comparison.get("ordered_refs")
    if not isinstance(ordered_refs, list) or not ordered_refs or not all(
        isinstance(ref, str) and _SNAPSHOT_REF_PATTERN.match(ref)
        for ref in ordered_refs
    ):
        out.append(
            _violation(
                "missing_required_ref",
                "display.sections[0].comparison.ordered_refs",
                "ordered_refs -- непустой список rs-*",
            )
        )
    if comparison.get("completeness") != display.get("completeness"):
        out.append(
            _violation(
                "conflicting_flags",
                "display.completeness",
                "completeness снапшота -- эхо completeness сравнения (§9)",
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
    if kind == "passport_print_snapshot":
        return validate_passport_print_snapshot(payload)
    if kind == "passport_comparison_snapshot":
        return validate_passport_comparison_print_snapshot(payload)
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
    конфликт (честная 409-семантика).

    PGV-10 (аддитивно): снапшот с frozen экранным SVG несёт его sha256
    в identity (pgv.print_snapshot:{view_id}:{digest}:{svg16}) -- иной
    frozen print input (другая геометрия того же результата) является
    ДРУГИМ immutable снапшотом (§8 «старые snapshots не переписываются»;
    AC08: скрытой подмены отображения нет), а не конфликтом ключа."""
    view_id = _str(payload.get("view_id")) or "unknown"
    result = _rec(payload.get("result"))
    identity = _str(result.get("result_digest")) or _str(
        result.get("result_digest_reason")
    ) or "unknown"
    svg_digest = _str(result.get("screen_svg_sha256"))
    if svg_digest:
        return f"pgv.print_snapshot:{view_id}:{identity}:{svg_digest[:16]}"
    return f"pgv.print_snapshot:{view_id}:{identity}"


def checkpoint_producer_key(payload: dict[str, Any]) -> str:
    """pgv.checkpoint:{checkpoint_id} -- идемпотентность по checkpoint_id
    (§8)."""
    return f"pgv.checkpoint:{_str(payload.get('checkpoint_id')) or 'unknown'}"


def _passport_document_identity_core(payload: dict[str, Any]) -> str:
    """Референс identity печатного входа P01/P02: mode + упорядоченные
    refs + digest (§11 идемпотентность по телу; digest строит builder
    из identity-ядер записей/сравнения)."""
    identity = _rec(payload.get("identity"))
    mode = _str(identity.get("mode")) or "unknown"
    refs = ",".join(str(ref) for ref in identity.get("snapshot_refs") or [])
    digest = (_str(identity.get("digest")) or "unknown")[:16]
    return f"{mode}:{refs}:{digest}"


def passport_print_producer_key(payload: dict[str, Any]) -> str:
    """pgv.passport_print:{mode}:{refs}:{digest16} (PGV-13, P01) --
    тот же комплект из тех же refs идемпотентен; иная траектория --
    другой immutable снапшот (§8 «старые snapshots не переписываются»)."""
    return f"pgv.passport_print:{_passport_document_identity_core(payload)}"


def passport_comparison_producer_key(payload: dict[str, Any]) -> str:
    """pgv.passport_comparison_print:{mode}:{refs}:{digest16}
    (PGV-13, P02)."""
    return f"pgv.passport_comparison_print:{_passport_document_identity_core(payload)}"


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
    elif isinstance(raw_revision, str) and raw_revision.strip():
        # PGV-02-FIX (F-P2C2): клиент декларировал ожидаемую ревизию,
        # которую невозможно сверить с числовой ревизией запуска --
        # fail-closed CAS (409 context_changed), НЕ тихий пропуск сверки
        # (PGV-AC07-дух: смешанный print под чужую ревизию недопустим).
        raise PrintContextConflict(
            "freeze_visual_print_snapshot: expected_context.data_revision "
            f"{raw_revision!r} нечислова -- сверка с durable-состоянием "
            "запуска невозможна -- 409 context_changed: обновите "
            "представление или выберите сохранённую версию"
        )
    else:
        # Пустая/whitespace-строка -- отсутствие значения (конвенция _str);
        # research-снапшот отвергается валидационным гейтом persist.
        expected_data_revision = None
    if expected_context_id is not None or expected_data_revision is not None:
        _check_context_cas(
            run,
            expected_context_id=expected_context_id,
            expected_data_revision=expected_data_revision,
            source="freeze_visual_print_snapshot",
        )
    producer_key = print_snapshot_producer_key(payload)
    # F-P2C5: артефакт, существовавший ДО операции (идемпотентный
    # повтор), компенсации не подлежит -- удаляется только созданный.
    pre_existing = service.find_by_producer(run_id, producer_key)
    dependencies = [result_artifact_id] if result_artifact_id else []
    artifact = service.persist_visual_artifact(
        run_id,
        subject,
        kind="visual_print_snapshot",
        payload=payload,
        producer_key=producer_key,
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
    # F-P2C5 (AC08-дух): отказ пина не оставляет зарегистрированный
    # артефакт -- компенсация (unpin поставленных ЭТОЙ операцией пинов +
    # unregister созданного артефакта) и честный повторный raise.
    pre_pinned = {
        pin.ref_id
        for pin in service.registry.list_pins(run_id, ref_kind="artifact")
    }
    pinned_now: list[str] = []
    try:
        for dependency_id in dependencies:
            service.registry.pin_ref(
                run_id,
                "artifact",
                dependency_id,
                reason=f"print_snapshot:{artifact.artifact_id}",
                created_by=created_by or getattr(subject, "subject_id", None),
            )
            pinned_now.append(dependency_id)
    except Exception:
        for dependency_id in pinned_now:
            if dependency_id in pre_pinned:
                continue  # пин существовал до операции -- не наш
            try:
                service.registry.unpin_ref(run_id, "artifact", dependency_id)
            except Exception as unpin_exc:  # pragma: no cover
                logger.warning(
                    "freeze_visual_print_snapshot: unpin-компенсация не "
                    "удалась для %s: %s",
                    dependency_id,
                    unpin_exc,
                )
        if pre_existing is None:
            try:
                service.registry.unregister_artifact(artifact.artifact_id)
            except Exception as unregister_exc:  # pragma: no cover
                logger.warning(
                    "freeze_visual_print_snapshot: AC08-компенсация не "
                    "удалась для %s: %s",
                    artifact.artifact_id,
                    unregister_exc,
                )
        raise
    return artifact


def _freeze_passport_document_snapshot(
    run_id: str,
    subject: Any,
    *,
    kind: str,
    payload: dict[str, Any],
    producer_key: str,
    dependency_artifact_ids: list[str],
    pin_reason_prefix: str,
    session_id: str = "",
    created_by: Optional[str] = None,
) -> Any:
    """Общий freeze печатного входа P01/P02 (PGV-13). БЕЗ CAS
    current-context: POST /passport-documents восстанавливает
    ИСТОРИЧЕСКИЕ refs -- ожидание контекста клиента к ним не применимо
    (§3.3 «stale относительно текущих данных не уничтожает историческую
    действительность»; контракт §11 несёт refs/checkpoint, не
    expected_context). Целостность -- content-addressed хранение +
    payload_sha256 (T8) и producer_key-конфликт (§11). Пины
    passport-артефактов present-записей с причиной (§16); AC08-компенсация
    -- паритет freeze_visual_print_snapshot (F-P2C5)."""
    service, _run = _authorized_run(run_id, subject, session_id)
    pre_existing = service.find_by_producer(run_id, producer_key)
    artifact = service.persist_visual_artifact(
        run_id,
        subject,
        kind=kind,
        payload=payload,
        producer_key=producer_key,
        session_id=session_id,
        dependencies=list(dependency_artifact_ids),
        refs={
            "print_kind": _rec(payload.get("documents")).get("print_kind"),
            "mode": _rec(payload.get("documents")).get("mode"),
            "scope": payload.get("scope"),
            "profile_id": _rec(payload.get("print")).get("profile_id"),
        },
        created_by=created_by,
    )
    pre_pinned = {
        pin.ref_id
        for pin in service.registry.list_pins(run_id, ref_kind="artifact")
    }
    pinned_now: list[str] = []
    try:
        for dependency_id in dependency_artifact_ids:
            service.registry.pin_ref(
                run_id,
                "artifact",
                dependency_id,
                reason=f"{pin_reason_prefix}:{artifact.artifact_id}",
                created_by=created_by or getattr(subject, "subject_id", None),
            )
            pinned_now.append(dependency_id)
    except Exception:
        for dependency_id in pinned_now:
            if dependency_id in pre_pinned:
                continue  # пин существовал до операции -- не наш
            try:
                service.registry.unpin_ref(run_id, "artifact", dependency_id)
            except Exception as unpin_exc:  # pragma: no cover
                logger.warning(
                    "_freeze_passport_document_snapshot: unpin-компенсация "
                    "не удалась для %s: %s",
                    dependency_id,
                    unpin_exc,
                )
        if pre_existing is None:
            try:
                service.registry.unregister_artifact(artifact.artifact_id)
            except Exception as unregister_exc:  # pragma: no cover
                logger.warning(
                    "_freeze_passport_document_snapshot: AC08-компенсация "
                    "не удалась для %s: %s",
                    artifact.artifact_id,
                    unregister_exc,
                )
        raise
    return artifact


def freeze_passport_print_snapshot(
    run_id: str,
    subject: Any,
    *,
    payload: dict[str, Any],
    session_id: str = "",
    dependency_artifact_ids: Optional[list[str]] = None,
    created_by: Optional[str] = None,
) -> Any:
    """Freeze pgv.passport_print_snapshot/1 -- печатный вход P01
    (PGV-13); зависимости -- passport-артефакты present-записей."""
    return _freeze_passport_document_snapshot(
        run_id,
        subject,
        kind="passport_print_snapshot",
        payload=payload,
        producer_key=passport_print_producer_key(payload),
        dependency_artifact_ids=list(dependency_artifact_ids or []),
        pin_reason_prefix="passport_print",
        session_id=session_id,
        created_by=created_by,
    )


def freeze_passport_comparison_snapshot(
    run_id: str,
    subject: Any,
    *,
    payload: dict[str, Any],
    session_id: str = "",
    dependency_artifact_ids: Optional[list[str]] = None,
    created_by: Optional[str] = None,
) -> Any:
    """Freeze pgv.passport_comparison_print_snapshot/1 -- печатный вход
    P02 (PGV-13); зависимости -- passport-артефакты записей пути."""
    return _freeze_passport_document_snapshot(
        run_id,
        subject,
        kind="passport_comparison_snapshot",
        payload=payload,
        producer_key=passport_comparison_producer_key(payload),
        dependency_artifact_ids=list(dependency_artifact_ids or []),
        pin_reason_prefix="passport_comparison",
        session_id=session_id,
        created_by=created_by,
    )


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
