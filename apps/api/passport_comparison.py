"""Pure comparison resolver паспортов (PGV-06; spec_passport_graphics_visual.md
§9, строка PGV-13-зависимый контракт ``pgv.passport_comparison/1``).

ПОСТАНОВКА (§13, строка PGV-06): «Pure comparison resolver; точки
изменения -- app/core/passport/session adapter; критерий -- Прежняя
семантика refs, cutoff/reuse/incompatible contexts проверены».

§9: «Общий pure comparison engine выделяется из session orchestration:
существующая ``_compare_ts_props`` через versioned adapter, без
дублирования формул в TypeScript. Вход -- immutable refs. Frozen
PassportComparisonSnapshot/1: ordered refs/path, checkpoint metadata,
numeric deltas/category/list/qualitative changes, method/schema
versions, gaps/context. Default resolver использует trajectory
checkpoint. При произвольном выборе UI показывает IDs. Несовместимые
target/entity/units/schema -> 409 comparison_incompatible. Cross-context
historical comparison -- только явный режим с проверкой сопоставимости
и маркировкой. Panel entities не смешиваются. Unchanged modeling_entry
не добавляет нулевую дублирующую колонку; отдельная строка
подтверждения содержит confirmed_at и reused ref. Missing validation --
gap, не ноль. Complete требует всех применимых сохранённых точек;
partial явно перечисляет пропуски».

Границы модуля (pure resolver):
  - НЕТ SessionStore/pandas/numpy/redis (AST-гейт в тестах поставки);
    вход -- immutable snapshot-записи PGV-05 (pgv.passport_history/1)
    и passport-dict'ы; выход -- frozen-структуры без собственного
    времени (детерминизм: те же refs -- тот же snapshot).
  - Формулы сравнения НЕ дублируются и НЕ переписываются: единственный
    движок -- существующий ``app.core.passport._compare_ts_props``,
    доступный ТОЛЬКО через versioned adapter
    (``compare_passports_via_engine``); session orchestration
    (routers/session.py) переведён на тот же adapter.
  - Чтение durable-refs -- через PassportHistoryReader (PGV-05):
    access-контур, XOR-честность gaps/legacy_unknown, изоляция вселенных
    наследуются; резолюция read-only (AC06-дух: сравнение не пишет в
    durable state и не пересчитывает науку).

Семантика путей (прежняя, проверяется тестами поставки):
  - trajectory-режим (default): путь -- ЗАМОРОЖЕННЫЕ stage_refs
    чекпоинта на момент подтверждения (cutoff; не latest каждого stage);
    отсутствующая точка -- явный gap, пары строятся по доказанным
    соседним точкам (семантика session-пропуска missing validation);
    unchanged-подтверждение (reused ref == previous ref) НЕ добавляет
    дублирующую колонку -- отдельная строка confirmation несёт
    confirmed_at и reused ref (§9/AC11);
  - explicit-refs режим (произвольный выбор UI): ordered refs КАК
    ЗАДАНО; пары -- только СОСЕДНИЕ разрешённые позиции (молчаливый
    «мост» через дыру запрещён); повтор ref -- алиас без нулевой пары;
    cross-context разрешён самим явным выбором и МАРКИРУЕТСЯ
    (cross_context=true на паре и в snapshot).

Несовместимость (§9/AC13/AC14): target/universe/entity/schema --
проверяются только по ДОКАЗУЕМЫМ значениям (XOR-честность: отсутствие
-- не значение, отказ на неизвестном не фабкуется; units в durable
passport-записях сегодня не записаны -- ось не проверяема без
фабкации, зафиксировано в docs поставки). Cross-context (известные
разные context_id) -- отказ вне явного режима, маркировка внутри него.
Отказ -- PassportComparisonIncompatible с машиночитаемыми reasons
(API-слой отображает как 409 comparison_incompatible, §11).
"""
from __future__ import annotations

from typing import Any, Optional

from app.core.passport import _compare_ts_props

# Frozen-контракт поставки (прецедент pgv.passport_history/1).
PASSPORT_COMPARISON_SCHEMA_VERSION = "pgv.passport_comparison/1"

# Versioned adapter (§9: «существующая _compare_ts_props через
# versioned adapter»): единственный способ вызвать движок из
# orchestration и durable-резолвера; смена формул -- новая версия.
COMPARISON_ENGINE = {
    "id": "app.core.passport._compare_ts_props",
    "version": "v1.0",
}

# Порядок этапов траектории (паритет session orchestration:
# start -> validation -> exit -> modeling_entry; панель -- своя
# вселенная). Неизвестный этап -- в конец, стабильно по captured_at.
_STAGE_RANK = {
    "start": 0,
    "validation": 1,
    "exit": 2,
    "modeling_entry": 3,
    "panel": 4,
    "panel_entry": 4,
}

# Определения метрик (AC13/§9): описывают ФАКТИЧЕСКИЕ конвенции
# движка (проверяются parity-оракулами), не переписывают формулы.
_COMPARISON_DEFINITIONS = {
    "absolute": "delta = v_new - v_old",
    "relative": "delta_pct = (delta / abs(v_old)) * 100",
    "zero_denominator_reason": (
        "при |v_old| <= 1e-10 относительное изменение не определено; "
        "движок подставляет 0.0 при |delta| < 1e-10, иначе 100.0 -- "
        "относительное изменение на нулевом базисе не является процентом"
    ),
    "delta_color": (
        "цвет delta не означает статистическую значимость -- только "
        "направление и величину изменения"
    ),
}


class PassportComparisonIncompatible(ValueError):
    """Несовместимые паспорта (§9: target/entity/units/schema;
    cross-context вне явного режима). ``reasons`` -- машиночитаемые
    причины; сообщение -- человекочитаемое (API-слой отображает как
    409 comparison_incompatible)."""

    def __init__(self, reasons: list[str], message: Optional[str] = None):
        self.reasons = [str(reason) for reason in reasons]
        if message is None:
            message = (
                "Сравнение паспортов несовместимо: " + "; ".join(self.reasons)
            )
        super().__init__(message)


# ── Versioned adapter над существующим движком ───────────────────────


def compare_passports_via_engine(
    props_old: dict[str, Any], props_new: dict[str, Any]
) -> dict[str, Any]:
    """Versioned adapter (§9): ТОЧНО вывод существующего pure engine
    ``app.core.passport._compare_ts_props`` -- формулы не дублируются и
    не меняются (parity-оракулы поставки убивают любой дрейф). Чистая
    функция двух passport-dict'ов: без сторов, сессий и времени."""
    return _compare_ts_props(props_old, props_new)


# ── Попарное сравнение snapshot-записей (immutable inputs) ───────────


def _incompatibility_reasons(
    old_record: dict[str, Any], new_record: dict[str, Any]
) -> list[str]:
    """ДОКАЗУЕМЫЕ несовместимости (XOR-честность: None -- неизвестно,
    не значение; отказ на неизвестном не фабкуется)."""
    reasons: list[str] = []
    old_target = old_record.get("target_column")
    new_target = new_record.get("target_column")
    if old_target is not None and new_target is not None and old_target != new_target:
        reasons.append(f"target_mismatch: {old_target!r} != {new_target!r}")
    old_universe = old_record.get("universe")
    new_universe = new_record.get("universe")
    if old_universe is not None and new_universe is not None and old_universe != new_universe:
        reasons.append(
            f"universe_mixing: {old_universe!r} != {new_universe!r} "
            "(panel и single-series не смешиваются, AC14)"
        )
    old_entity = old_record.get("entity_id")
    new_entity = new_record.get("entity_id")
    if old_entity is not None and new_entity is not None and old_entity != new_entity:
        reasons.append(f"entity_mismatch: {old_entity!r} != {new_entity!r} (AC14)")
    old_schema = old_record.get("passport_schema_version")
    new_schema = new_record.get("passport_schema_version")
    if old_schema is not None and new_schema is not None and old_schema != new_schema:
        reasons.append(f"schema_mismatch: {old_schema!r} != {new_schema!r}")
    return reasons


def _is_cross_context(old_record: dict[str, Any], new_record: dict[str, Any]) -> bool:
    """Cross-context ТОЛЬКО по доказуемым (известным обеим сторонам)
    context_id; неизвестное -- не значение (не догадка)."""
    old_context = old_record.get("context_id")
    new_context = new_record.get("context_id")
    return bool(
        old_context is not None
        and new_context is not None
        and old_context != new_context
    )


def compare_passport_records(
    old_record: dict[str, Any],
    new_record: dict[str, Any],
    *,
    allow_cross_context: bool = False,
) -> dict[str, Any]:
    """Попарное сравнение ДВУХ snapshot-записей PGV-05 (immutable,
    content_status=present): несовместимость -- отказ с reasons;
    cross-context -- отказ вне явного режима, маркировка внутри него.
    Блок comparison -- вывод движка AS-IS через versioned adapter."""
    for record in (old_record, new_record):
        if record.get("content_status") != "present" or not isinstance(
            record.get("passport"), dict
        ):
            raise ValueError(
                "compare_passport_records требует present-записи; "
                "content-проблемы резолвер обязан оформить как gaps "
                "(§9: missing -- gap, не ноль)"
            )
    reasons = _incompatibility_reasons(old_record, new_record)
    cross = _is_cross_context(old_record, new_record)
    if cross and not allow_cross_context:
        reasons = reasons + [
            "context_mismatch_requires_explicit_mode: "
            f"{old_record.get('context_id')!r} != {new_record.get('context_id')!r} "
            "(cross-context -- только явный режим, §9)"
        ]
    if reasons:
        raise PassportComparisonIncompatible(reasons)
    return {
        "from_stage": old_record.get("stage"),
        "to_stage": new_record.get("stage"),
        "from_ref": old_record.get("snapshot_ref"),
        "to_ref": new_record.get("snapshot_ref"),
        "from_snapshot_id": old_record.get("session_snapshot_id"),
        "to_snapshot_id": new_record.get("session_snapshot_id"),
        "from_captured_at": old_record.get("captured_at"),
        "to_captured_at": new_record.get("captured_at"),
        "comparison": compare_passports_via_engine(
            old_record["passport"], new_record["passport"]
        ),
        "cross_context": cross,
    }


# ── Резолвер: frozen PassportComparisonSnapshot/1 ────────────────────


def _content_gap(record: dict[str, Any], *, at: str) -> Optional[dict[str, Any]]:
    """Content-проблема записи -- честный gap (§9: missing -- gap, не
    ноль); present-запись -- None."""
    status = record.get("content_status")
    if status == "present" and isinstance(record.get("passport"), dict):
        return None
    reason = "content_corrupt" if status == "corrupt" else "content_missing"
    return {
        "at": at,
        "snapshot_ref": record.get("snapshot_ref"),
        "reason": reason,
        "detail": record.get("content_gap_reason") or str(status),
    }


def _method_versions(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Method/schema versions (§9) -- из записей AS-IS; legacy_unknown
    остаётся честным отсутствием (None), не выдуманной версией."""
    return {
        "engine": dict(COMPARISON_ENGINE),
        "records": [
            {
                "snapshot_ref": record.get("snapshot_ref"),
                "passport_schema_version": record.get("passport_schema_version"),
                "calculation_version": record.get("calculation_version"),
            }
            for record in records
        ],
    }


def _snapshot_skeleton(
    mode: str, run_id: str, ordered_refs: list[str], path: list[Any]
) -> dict[str, Any]:
    return {
        "schema_version": PASSPORT_COMPARISON_SCHEMA_VERSION,
        "mode": mode,
        "run_id": run_id,
        "ordered_refs": ordered_refs,
        "path": path,
        "comparisons": [],
        "confirmation": None,
        "checkpoint": None,
        "context": None,
        "cross_context": False,
        "aliases": [],
        "method_versions": {"engine": dict(COMPARISON_ENGINE), "records": []},
        "definitions": dict(_COMPARISON_DEFINITIONS),
        "gaps": [],
        "completeness": "complete",
    }


def resolve_passport_comparison(
    run_id: str,
    subject: Any,
    *,
    checkpoint_id: Optional[str] = None,
    snapshot_refs: Optional[list[str]] = None,
    allow_cross_context: Optional[bool] = None,
    session_id: str = "",
) -> Optional[dict[str, Any]]:
    """Frozen PassportComparisonSnapshot/1 (§9) из immutable refs.

    Default (``checkpoint_id``): trajectory checkpoint -- замороженные
    stage_refs на момент подтверждения (cutoff), reuse/unchanged --
    без дублирующей колонки, отдельная строка confirmation. Произвольный
    выбор UI (``snapshot_refs``): ordered refs как задано, IDs в парах;
    cross-context разрешён явным выбором и маркируется. Режимы
    взаимоисключающие. None -- чекпоинт отсутствует в run'е (uniform,
    без фабкации). Доступ/честность gaps -- наследуются от
    PassportHistoryReader (PGV-05); резолюция read-only.
    """
    if checkpoint_id is None and not snapshot_refs:
        raise ValueError("Нужен checkpoint_id либо непустой snapshot_refs")
    if checkpoint_id is not None and snapshot_refs:
        raise ValueError(
            "Режимы взаимоисключающие: checkpoint_id либо snapshot_refs"
        )
    from apps.api import passport_history

    if checkpoint_id is not None:
        return _resolve_from_trajectory(
            run_id, subject, checkpoint_id=checkpoint_id, session_id=session_id
        )
    return _resolve_from_refs(
        run_id,
        subject,
        snapshot_refs=[str(ref) for ref in snapshot_refs or []],
        session_id=session_id,
    )


def _resolve_from_trajectory(
    run_id: str, subject: Any, *, checkpoint_id: str, session_id: str
) -> Optional[dict[str, Any]]:
    from apps.api import passport_history

    trajectory = passport_history.read_passport_trajectory(
        run_id, subject, checkpoint_id=checkpoint_id, session_id=session_id
    )
    if trajectory is None:
        return None

    flags = dict(trajectory.get("flags") or {})
    checkpoint_stage = trajectory.get("stage")
    snapshots: dict[str, dict[str, Any]] = dict(trajectory.get("snapshots") or {})
    previous = trajectory.get("previous_snapshot")
    confirmed_record = snapshots.get(checkpoint_stage) if checkpoint_stage else None

    # Reuse-семантика (§9/AC11): unchanged-подтверждение -- reused ref
    # совпадает с previous ref; дублирующая колонка НЕ добавляется,
    # подтверждение -- отдельной строкой. Durable-деривация: freeze
    # НЕ пишет previous_snapshot_ref, когда previous == подтверждённый
    # снимок (session-семантика previous_snapshot_id == snapshot_id),
    # поэтому reused + отсутствующий previous == unchanged; reused
    # с ДОКАЗАННЫМ отличным previous -- возврат к старому снимку (алиас).
    unchanged = bool(
        flags.get("reused")
        and confirmed_record is not None
        and (
            previous is None
            or previous.get("snapshot_ref") == confirmed_record.get("snapshot_ref")
        )
    )
    reused_ref = (
        confirmed_record.get("snapshot_ref")
        if (confirmed_record is not None and flags.get("reused"))
        else None
    )

    path_stages = sorted(
        snapshots.keys(),
        key=lambda s: (
            _STAGE_RANK.get(str(s), 90),
            str(snapshots[s].get("captured_at") or ""),
            str(s),
        ),
    )
    if unchanged and checkpoint_stage in path_stages:
        path_stages = [s for s in path_stages if s != checkpoint_stage]
    ordered_refs = [snapshots[s].get("snapshot_ref") for s in path_stages]

    # Content-проблемы -- честные gaps по записям пути (не нули).
    gaps: list[dict[str, Any]] = [
        dict(gap) for gap in (trajectory.get("gaps") or [])
    ]
    present: dict[str, bool] = {}
    for stage_key in path_stages:
        gap = _content_gap(snapshots[stage_key], at=f"path.{stage_key}")
        if gap is not None:
            gaps.append(gap)
        present[stage_key] = gap is None

    comparisons: list[dict[str, Any]] = []
    cross_any = False
    for old_stage, new_stage in zip(path_stages, path_stages[1:]):
        if not (present[old_stage] and present[new_stage]):
            continue  # затронутая дырой пара -- gap выше, не ноль
        pair = compare_passport_records(
            snapshots[old_stage], snapshots[new_stage]
        )
        # Ключи этапов ПУТИ (паритет session-семантики): алиасная
        # запись (reused-снимок, AC11) несёт stage исходного снимка,
        # но адресуется ключом этапа подтверждения -- одна запись,
        # два адреса пути.
        pair["from_stage"] = old_stage
        pair["to_stage"] = new_stage
        comparisons.append(pair)
        cross_any = cross_any or bool(pair["cross_context"])

    complete = not gaps
    confirmation = {
        "checkpoint_ref": trajectory.get("checkpoint_ref"),
        "confirmed_at": trajectory.get("confirmed_at"),
        "confirmed_at_reason": trajectory.get("confirmed_at_reason"),
        "reused": bool(flags.get("reused")),
        "unchanged": unchanged,
        "reused_ref": reused_ref,
        "previous_ref": (
            previous.get("snapshot_ref") if previous is not None else None
        ),
    }
    checkpoint_meta = {
        "checkpoint_ref": trajectory.get("checkpoint_ref"),
        "checkpoint_artifact_id": trajectory.get("checkpoint_artifact_id"),
        "stage": checkpoint_stage,
        "universe": trajectory.get("universe"),
        "confirmed_at": trajectory.get("confirmed_at"),
        "confirmed_at_reason": trajectory.get("confirmed_at_reason"),
        "flags": flags,
        "provenance": trajectory.get("provenance"),
    }
    snapshot = _snapshot_skeleton(
        "trajectory_checkpoint", run_id, ordered_refs, path_stages
    )
    snapshot.update({
        "comparisons": comparisons,
        "confirmation": confirmation,
        "checkpoint": checkpoint_meta,
        "context": trajectory.get("context"),
        "cross_context": cross_any,
        "method_versions": _method_versions(
            [snapshots[s] for s in path_stages]
        ),
        "gaps": gaps,
        "completeness": "complete" if complete else "partial",
    })
    return snapshot


def _resolve_from_refs(
    run_id: str,
    subject: Any,
    *,
    snapshot_refs: list[str],
    session_id: str,
) -> dict[str, Any]:
    """Explicit-refs режим (произвольный выбор UI, §9): ordered refs
    как задано; пары -- только соседние РАЗРЕШЁННЫЕ позиции (никаких
    молчаливых мостов через дыру); повтор ref -- алиас без нулевой
    пары; явный выбор = явный cross-context режим (маркируется)."""
    from apps.api import passport_history

    positions: list[Optional[dict[str, Any]]] = []
    gaps: list[dict[str, Any]] = []
    for idx, ref in enumerate(snapshot_refs):
        record = passport_history.read_passport_snapshot(
            run_id, subject, snapshot_ref=ref, session_id=session_id
        )
        if record is None:
            gaps.append({
                "at": f"refs.{idx}",
                "snapshot_ref": ref,
                "reason": "missing_snapshot_record",
                "detail": (
                    "rs-запись отсутствует/чужая/не паспортная -- "
                    "сравнение не фабкуется"
                ),
            })
            positions.append(None)
            continue
        positions.append(record)

    # Физический путь: первые вхождения refs; повторы -- алиасы (одна
    # запись, несколько адресов; без нулевых дублирующих пар).
    aliases: list[dict[str, Any]] = []
    seen_refs: set[str] = set()
    path_records: list[dict[str, Any]] = []
    path_stages: list[Any] = []
    for idx, record in enumerate(positions):
        if record is None:
            continue
        ref = str(record.get("snapshot_ref"))
        if ref in seen_refs:
            aliases.append({"path_position": idx, "snapshot_ref": ref})
            continue
        seen_refs.add(ref)
        path_records.append(record)
        path_stages.append(record.get("stage"))

    present_by_position: list[bool] = []
    for idx, record in enumerate(positions):
        if record is None:
            present_by_position.append(False)
            continue
        gap = _content_gap(record, at=f"refs.{idx}")
        if gap is not None:
            gaps.append(gap)
        present_by_position.append(gap is None)

    # Пары -- соседние РАЗРЕШЁННЫЕ позиции заданной
    # последовательности; bridge через дыру запрещён.
    comparisons: list[dict[str, Any]] = []
    cross_any = False
    for i in range(len(positions) - 1):
        old_record, new_record = positions[i], positions[i + 1]
        if old_record is None or new_record is None:
            continue
        if not (present_by_position[i] and present_by_position[i + 1]):
            continue
        if str(old_record.get("snapshot_ref")) == str(new_record.get("snapshot_ref")):
            continue  # алиас: та же запись, нулевая пара не фабкуется
        pair = compare_passport_records(old_record, new_record, allow_cross_context=True)
        comparisons.append(pair)
        cross_any = cross_any or bool(pair["cross_context"])

    snapshot = _snapshot_skeleton("explicit_refs", run_id, snapshot_refs, path_stages)
    snapshot.update({
        "comparisons": comparisons,
        "context": None,
        "cross_context": cross_any,
        "aliases": aliases,
        "method_versions": _method_versions(path_records),
        "gaps": gaps,
        "completeness": "partial" if gaps else "complete",
    })
    return snapshot
