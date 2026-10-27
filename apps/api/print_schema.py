# apps/api/print_schema.py
"""
PGV-01 (2026-10-27): print schema/metadata/profile -- Python-зеркало
print-схем научных визуализаций (spec_passport_graphics_visual.md §6/§7;
строка PGV-01: точки изменения «shared schemas, registry», критерий
готовности «Result/version/date/units/sampling обязательны по
applicability, параметры trusted»).

Источник истины -- packages/ui/print/printSchema.ts (TypeScript);
config/print_schema.json -- JSON-твин, генерируемый
scripts/pgv01/export_print_schema.ts; паритет TS⇄JSON гвардится
jest-оракулом packages/ui/print/printSchema.test.ts. Этот модуль --
Python-зеркало ПРАВИЛ (не новый источник истины): он читает твин и
реализует те же проверки, чтобы PGV-02 (durable inputs) и PGV-09
(jobs/renderer integration) делали preflight frozen payload до постановки
рендер-задания теми же правилами, что и фронтенд-валидация.

Обязательность metadata «по applicability»: scope сайта реестра PGV-00
(demo/research/passport/comparison), его required_refs и renderer_kind
определяют обязательный набор полей снапшота. Единицы/даты/хэши не
выдумываются: отсутствие -- только с явной null-причиной (legacy_unknown,
demo_dataset), паритет parquet-эталона §7 родительской спеки. Параметры
trusted: origin -- producer_freeze/producer_first_export; клиент передаёт
ref и allowlisted display selection (ключи -- view_params реестра).

Границы PGV-01: схемы/валидация -- НЕ runtime. Durable store (PGV-02),
producer-адаптеры (PGV-03/04), jobs/renderer (PGV-09) потребляют эти
правила позже; существующие пути скачивания не меняются.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
PRINT_SCHEMA_PATH = REPO_ROOT / "config" / "print_schema.json"
VISUAL_REGISTRY_PATH = REPO_ROOT / "config" / "visual_registry.json"

PRINT_SCHEMA_DOCUMENT_VERSION = "pgv.print_schema/1"
PRINT_RESULT_SCHEMA_VERSION = "pgv.visual_result/1"
PRINT_SNAPSHOT_SCHEMA_VERSION = "pgv.visual_print_snapshot/1"
PRINT_MANIFEST_SCHEMA_VERSION = "pgv.print_manifest/1"

SNAPSHOT_SCOPES = ("demo", "research", "passport", "comparison")

MANDATORY_REFS_BY_SCOPE: dict[str, list[str]] = {
    "demo": ["demo_dataset_id"],
    "research": ["context_id", "data_revision"],
    "passport": ["context_id", "snapshot_id", "data_revision", "schema_version"],
    "comparison": ["research_run_id", "comparison_id"],
}

SECTION_RENDERER_KINDS = ("recharts_svg", "html_table", "html_heatmap", "html_cards")

TRUSTED_PARAMETER_ORIGINS = ("producer_freeze", "producer_first_export")

SAMPLING_MODES = ("full", "downsampled", "windowed", "aggregated", "truncated")
SAMPLING_MODES_REQUIRING_POINT_CAP = ("downsampled", "windowed", "truncated")

DETAIL_LEVELS = ("compact", "expanded", "sampling")
DEPENDENCY_STATUSES = ("available", "unavailable", "unknown")

UNIT_REASON_DIMENSIONLESS = "dimensionless"
UNIT_REASON_LEGACY_UNKNOWN = "legacy_unknown"


class PrintSchemaViolation:
    """Нарушение print-схемы: стабильный код + путь + причина (контракт PGV-02/09)."""

    __slots__ = ("code", "path", "message")

    def __init__(self, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PrintSchemaViolation):
            return NotImplemented
        return (self.code, self.path, self.message) == (other.code, other.path, other.message)

    def __repr__(self) -> str:  # pragma: no cover - диагностика
        return f"PrintSchemaViolation({self.code!r}, {self.path!r})"


class SamplingError(Exception):
    """Программная ошибка правил sampling (не нарушение payload'а)."""


def _violation(code: str, path: str, message: str) -> PrintSchemaViolation:
    return PrintSchemaViolation(code, path, message)


# ── Загрузка твинов ──────────────────────────────────────────────


@lru_cache(maxsize=1)
def load_print_schema() -> dict[str, Any]:
    """JSON-твин print-схем (генерат scripts/pgv01/export_print_schema.ts)."""
    with PRINT_SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def load_visual_registry() -> dict[str, Any]:
    """JSON-твин реестра render-sites PGV-00 (config/visual_registry.json)."""
    with VISUAL_REGISTRY_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def reset_caches() -> None:
    """Сброс кэшей твинов (для тестов)."""
    load_print_schema.cache_clear()
    load_visual_registry.cache_clear()


# ── Профили и лимиты (spec §7) ───────────────────────────────────


def resolve_print_profile(profile_id: str) -> dict[str, Any] | None:
    """Профиль из каталога; неизвестный -- None (API-слой PGV-09 -> 422 invalid_profile)."""
    for profile in load_print_schema()["profiles"]:
        if profile["id"] == profile_id:
            return profile
    return None


def profile_pixel_consistency(profile: dict[str, Any]) -> bool:
    """Согласованность px<->мм<->ppi с допуском округления <=1px (PGV-AC16)."""
    width_from_mm = profile["width_mm"] / 25.4 * profile["ppi"]
    height_from_mm = profile["height_mm"] / 25.4 * profile["ppi"]
    return (
        abs(profile["width_px"] - width_from_mm) <= 1
        and abs(profile["height_px"] - height_from_mm) <= 1
    )


def print_limits() -> dict[str, int]:
    """Лимиты §7: 12 MP/стр, 20 стр, 50 MiB, 60 s, tenant=1/global=2."""
    return dict(load_print_schema()["limits"])


# ── Scope и обязательные refs ────────────────────────────────────


def resolve_scope(site: dict[str, Any]) -> str:
    """Scope сайта реестра: demo/comparison/passport/research (см. printSchema.ts)."""
    refs = set(site.get("required_refs", []))
    if "demo_dataset_id" in refs:
        return "demo"
    if "comparison_id" in refs:
        return "comparison"
    if "snapshot_id" in refs or site.get("stop_id") == "passport":
        return "passport"
    return "research"


def mandatory_ref_keys(site: dict[str, Any]) -> list[str]:
    """Обязательные refs снапшота: мандат scope + все заявленные сайтом."""
    scope = resolve_scope(site)
    merged = set(MANDATORY_REFS_BY_SCOPE[scope]) | set(site.get("required_refs", []))
    return sorted(merged)


def sampling_required(site: dict[str, Any]) -> bool:
    """Sampling обязателен по applicability: html_cards освобождены (см. printSchema.ts)."""
    return site.get("renderer_kind") != "html_cards"


# ── Робастные акцессоры (валидаторы не бросают на malformed) ─────


def _rec(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _num(value: Any) -> float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _is_hex64(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    allowed = set("0123456789abcdef")
    return len(value) == 64 and set(value) <= allowed


# ── Units: значение XOR причина ──────────────────────────────────


def _validate_unit(unit: Any, path: str, out: list[PrintSchemaViolation]) -> None:
    if not isinstance(unit, dict):
        out.append(_violation("missing_units", path, "unit declaration must be an object"))
        return
    has_value = _str(unit.get("value")) is not None
    has_reason = _str(unit.get("reason")) is not None
    if has_value and has_reason:
        out.append(
            _violation(
                "ambiguous_unit",
                path,
                "unit value и reason взаимоисключающи (spec §6: не выдумывать единицы)",
            )
        )
    elif not has_value and not has_reason:
        out.append(_violation("missing_units", path, "unit требует value XOR явную null-причину"))


def _validate_units_list(units: Any, path: str, out: list[PrintSchemaViolation]) -> None:
    if not isinstance(units, list) or not units:
        out.append(
            _violation(
                "missing_units",
                path,
                "секция обязана декларировать units (пусть и с null-причиной)",
            )
        )
        return
    for index, unit in enumerate(units):
        _validate_unit(unit, f"{path}[{index}]", out)


# ── Trusted-параметры / selection ────────────────────────────────


def _validate_trusted_parameters(
    method: Any,
    selection: Any,
    site: dict[str, Any] | None,
    out: list[PrintSchemaViolation],
) -> None:
    origin = _str(_rec(method).get("origin"))
    if origin is None or origin not in TRUSTED_PARAMETER_ORIGINS:
        out.append(
            _violation(
                "untrusted_parameter_origin",
                "method.origin",
                "origin должен быть producer_freeze/producer_first_export -- параметры trusted",
            )
        )
    allowlist = [k for k in _rec(selection).get("allowlist", []) if isinstance(k, str)]
    if site is not None:
        view_params = set(site.get("view_params", []))
        for key in allowlist:
            if key not in view_params:
                out.append(
                    _violation(
                        "selection_not_allowlisted",
                        f"selection.allowlist.{key}",
                        "client selection keys обязаны входить в view_params реестра",
                    )
                )
    values = _rec(_rec(selection).get("values"))
    for key in values:
        if key not in allowlist:
            out.append(
                _violation(
                    "selection_not_allowlisted",
                    f"selection.values.{key}",
                    "значение selection вне allowlist",
                )
            )


# ── Sampling ─────────────────────────────────────────────────────


def _validate_sampling(
    sampling: Any, required: bool, out: list[PrintSchemaViolation]
) -> None:
    rec = _rec(sampling)
    applicable = rec.get("applicable") is True
    if required and not applicable:
        out.append(
            _violation(
                "missing_sampling",
                "sampling",
                "sampling обязателен по applicability (серии/таблицы/матрицы)",
            )
        )
        return
    if not applicable:
        if _str(rec.get("reason")) is None:
            out.append(
                _violation(
                    "missing_sampling_reason",
                    "sampling.reason",
                    "not applicable требует явной причины (html_cards и пр.)",
                )
            )
        return
    mode = _str(rec.get("mode"))
    if mode is None or mode not in SAMPLING_MODES:
        out.append(_violation("missing_sampling_mode", "sampling.mode", "режим sampling обязателен"))
        return
    if mode in SAMPLING_MODES_REQUIRING_POINT_CAP:
        cap = _num(rec.get("point_cap"))
        if cap is None or cap <= 0:
            out.append(
                _violation(
                    "missing_point_cap",
                    "sampling.point_cap",
                    f"{mode} требует явный point_cap -- скрытого detail upgrade нет (PGV-AC08)",
                )
            )


# ── Секции ───────────────────────────────────────────────────────


def _validate_section(section: Any, path: str, out: list[PrintSchemaViolation]) -> None:
    rec = _rec(section)
    kind = _str(rec.get("renderer_kind"))
    if kind is None or kind not in SECTION_RENDERER_KINDS:
        out.append(
            _violation("invalid_section_kind", f"{path}.renderer_kind", "недопустимый renderer_kind секции")
        )
        return
    _validate_units_list(rec.get("units"), f"{path}.units", out)
    if kind == "recharts_svg":
        axes = rec.get("axes")
        axes = axes if isinstance(axes, list) else []
        if not axes:
            out.append(_violation("missing_axes", f"{path}.axes", "график обязан декларировать оси"))
        for index, axis in enumerate(axes):
            axis_rec = _rec(axis)
            if _str(axis_rec.get("name")) is None:
                out.append(
                    _violation("missing_axes", f"{path}.axes[{index}].name", "имя оси обязательно")
                )
            _validate_unit(axis_rec.get("units"), f"{path}.axes[{index}].units", out)
    if kind == "html_table":
        headings = _rec(rec.get("table_headings"))
        row = [c for c in headings.get("row", []) if isinstance(c, str)]
        column = [c for c in headings.get("column", []) if isinstance(c, str)]
        if not row or not column:
            out.append(
                _violation(
                    "missing_table_headings",
                    f"{path}.table_headings",
                    "таблица обязана нести заголовки строк/колонок (spec §6)",
                )
            )
    if kind == "html_heatmap":
        scale = _rec(rec.get("heatmap_scale"))
        domain = scale.get("domain")
        domain_ok = (
            isinstance(domain, list)
            and len(domain) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in domain)
        )
        if not domain_ok or not isinstance(scale.get("units"), dict):
            out.append(
                _violation(
                    "missing_heatmap_scale",
                    f"{path}.heatmap_scale",
                    "тепловая карта обязана декларировать цветовую шкалу с domain и units",
                )
            )
        else:
            _validate_unit(scale.get("units"), f"{path}.heatmap_scale.units", out)


def _validate_section_composition(
    sections: Any,
    site: dict[str, Any] | None,
    out: list[PrintSchemaViolation],
) -> None:
    if not isinstance(sections, list) or not sections:
        out.append(
            _violation("empty_sections", "display.sections", "снапшот обязан нести хотя бы одну секцию")
        )
        return
    for index, section in enumerate(sections):
        _validate_section(section, f"display.sections[{index}]", out)
    if site is None:
        return
    if site.get("renderer_kind") == "mixed":
        if len(sections) < 2:
            out.append(
                _violation(
                    "mixed_needs_multiple_sections",
                    "display.sections",
                    "mixed render-site обязан нести несколько секций разных kinds",
                )
            )
    elif len(sections) != 1 or _rec(sections[0]).get("renderer_kind") != site.get("renderer_kind"):
        out.append(
            _violation(
                "section_kind_mismatch",
                "display.sections",
                f"сайт {site.get('view_id')} рендерит {site.get('renderer_kind')} -- состав секций обязан соответствовать",
            )
        )


# ── Время: значение XOR причина ──────────────────────────────────


def _validate_time_xor(
    value: Any, reason: Any, path: str, code: str, out: list[PrintSchemaViolation]
) -> None:
    has_value = _str(value) is not None
    has_reason = _str(reason) is not None
    if has_value and has_reason:
        out.append(
            _violation("ambiguous_date", path, "время и причина отсутствия взаимоисключающи")
        )
    elif not has_value and not has_reason:
        out.append(
            _violation(
                code,
                path,
                "время обязательно либо явная null-причина (не выдумывать timestamps)",
            )
        )


# ── validate_print_snapshot ──────────────────────────────────────


def validate_print_snapshot(
    snapshot: Any, site: dict[str, Any] | None = None
) -> list[PrintSchemaViolation]:
    """Валидация VisualPrintSnapshot/1 (см. printSchema.ts -- те же правила)."""
    out: list[PrintSchemaViolation] = []
    if not isinstance(snapshot, dict):
        return [_violation("missing_field", "(root)", "print snapshot must be an object")]

    if snapshot.get("schema_version") != PRINT_SNAPSHOT_SCHEMA_VERSION:
        out.append(
            _violation(
                "schema_version_mismatch",
                "schema_version",
                f"ожидается {PRINT_SNAPSHOT_SCHEMA_VERSION}",
            )
        )

    view_id = _str(snapshot.get("view_id"))
    if view_id is None:
        out.append(_violation("missing_field", "view_id", "view_id обязателен"))
    elif site is not None and view_id != site.get("view_id"):
        out.append(
            _violation(
                "missing_field",
                "view_id",
                f"view_id не совпадает с реестром ({site.get('view_id')})",
            )
        )

    scope = resolve_scope(site) if site is not None else _str(snapshot.get("scope"))
    if scope is None or scope not in SNAPSHOT_SCOPES:
        out.append(
            _violation(
                "missing_field",
                "scope",
                "scope обязателен: demo/research/passport/comparison",
            )
        )
    elif snapshot.get("scope") != scope:
        out.append(
            _violation("missing_field", "scope", f"scope обязан быть {scope} (по applicability реестра)")
        )

    refs = _rec(snapshot.get("refs"))
    if scope in SNAPSHOT_SCOPES:
        mandatory = set(MANDATORY_REFS_BY_SCOPE[scope])
        if site is not None:
            mandatory |= set(site.get("required_refs", []))
        for ref_key in sorted(mandatory):
            if _str(refs.get(ref_key)) is None:
                out.append(
                    _violation(
                        "missing_required_ref",
                        f"refs.{ref_key}",
                        f"ref обязателен по applicability (scope={scope})",
                    )
                )

    result = _rec(snapshot.get("result"))
    if _str(result.get("result_ref")) is None or _str(result.get("result_schema_version")) is None:
        out.append(
            _violation(
                "missing_result_ref",
                "result",
                "result_ref/result_schema_version обязательны (frozen VisualResult)",
            )
        )
    result_digest = _str(result.get("result_digest"))
    result_digest_reason = _str(result.get("result_digest_reason"))
    if result_digest is None and result_digest_reason is None:
        out.append(
            _violation(
                "missing_source_hash",
                "result.result_digest",
                "digest XOR явная причина отсутствия",
            )
        )
    elif result_digest is not None and result_digest_reason is not None:
        out.append(
            _violation(
                "ambiguous_source_hash",
                "result.result_digest",
                "digest и reason взаимоисключающи",
            )
        )

    data_artifact = _rec(snapshot.get("data_artifact"))
    if _str(data_artifact.get("artifact_version")) is None:
        out.append(
            _violation(
                "missing_data_version",
                "data_artifact.artifact_version",
                "версия данных обязательна",
            )
        )
    source_hash = _str(data_artifact.get("source_hash"))
    hash_reason = _str(data_artifact.get("hash_reason"))
    if source_hash is None and hash_reason is None:
        out.append(
            _violation(
                "missing_source_hash",
                "data_artifact.source_hash",
                "source_hash XOR явная причина",
            )
        )
    elif source_hash is not None and hash_reason is not None:
        out.append(
            _violation(
                "ambiguous_source_hash",
                "data_artifact.source_hash",
                "hash и reason взаимоисключающи",
            )
        )

    if scope == "research":
        expected = _rec(snapshot.get("expected_context"))
        if _str(expected.get("context_id")) is None or _str(expected.get("data_revision")) is None:
            out.append(
                _violation(
                    "missing_expected_context",
                    "expected_context",
                    "research-снапшот обязан нести context_id+data_revision для проверки freeze (PGV-AC07)",
                )
            )

    times = _rec(snapshot.get("times"))
    _validate_time_xor(
        times.get("computed_at"), times.get("computed_at_reason"), "times.computed_at", "missing_date", out
    )
    _validate_time_xor(
        times.get("captured_at"), times.get("captured_at_reason"), "times.captured_at", "missing_date", out
    )
    if _str(times.get("render_requested_at")) is None:
        out.append(
            _violation(
                "missing_field",
                "times.render_requested_at",
                "render_requested_at фиксируется отдельно",
            )
        )
    if _str(times.get("timezone")) is None or _str(times.get("locale")) is None:
        out.append(
            _violation("missing_field", "times.timezone/locale", "timezone и locale обязательны")
        )

    checkpoint = _rec(snapshot.get("checkpoint"))
    if checkpoint.get("reused") is True:
        confirmed_at = _str(times.get("checkpoint_confirmed_at"))
        source_ref = _str(checkpoint.get("source_snapshot_ref"))
        if confirmed_at is None or source_ref is None:
            out.append(
                _violation(
                    "missing_checkpoint_confirmation",
                    "checkpoint",
                    "reused checkpoint обязан нести confirmed_at и source_snapshot_ref (PGV-AC11)",
                )
            )

    display = _rec(snapshot.get("display"))
    if _str(display.get("title")) is None:
        out.append(_violation("missing_title", "display.title", "заголовок печатного представления обязателен"))
    detail_level = _str(display.get("detail_level"))
    if detail_level is None or detail_level not in DETAIL_LEVELS:
        out.append(_violation("missing_field", "display.detail_level", "detail_level обязателен"))
    _validate_section_composition(display.get("sections"), site, out)

    _validate_trusted_parameters(snapshot.get("method"), snapshot.get("selection"), site, out)

    _validate_sampling(
        snapshot.get("sampling"),
        sampling_required(site) if site is not None else True,
        out,
    )

    dimensions = _rec(snapshot.get("dimensions"))
    mode = _str(dimensions.get("mode"))
    if site is not None:
        if site.get("applicability") == "panel":
            if mode != "panel":
                out.append(
                    _violation(
                        "panel_mixing",
                        "dimensions.mode",
                        "панельный сайт обязан печататься в mode=panel",
                    )
                )
            if _str(dimensions.get("entity_column")) is None and _str(refs.get("entity_column")) is None:
                out.append(
                    _violation(
                        "missing_required_ref",
                        "dimensions.entity_column",
                        "панельный вид обязан нести entity_column",
                    )
                )
        if site.get("applicability") == "univariate" and _str(dimensions.get("entity_id")) is not None:
            out.append(
                _violation(
                    "panel_mixing",
                    "dimensions.entity_id",
                    "entity на univariate виде -- смешивание panel/univariate запрещено (PGV-AC14)",
                )
            )
    elif mode == "panel" and _str(dimensions.get("entity_column")) is None:
        out.append(_violation("panel_mixing", "dimensions", "mode=panel требует entity_column"))

    print_block = _rec(snapshot.get("print"))
    profile_id = _str(print_block.get("profile_id"))
    if profile_id is None or resolve_print_profile(profile_id) is None:
        out.append(
            _violation(
                "invalid_profile",
                "print.profile_id",
                "профиль обязан быть из каталога (422 invalid_profile -- PGV-09)",
            )
        )
    page_count = _num(print_block.get("page_count"))
    if page_count is None or page_count < 1 or page_count != int(page_count):
        out.append(
            _violation("missing_field", "print.page_count", "page_count -- положительное целое")
        )
    if print_block.get("theme") != "light-print":
        out.append(
            _violation("theme_not_light_print", "print.theme", "всегда light-print (spec §3.4)")
        )

    renderer_env = _rec(snapshot.get("renderer_env"))
    dependency_status = _str(renderer_env.get("dependency_status"))
    if dependency_status is None or dependency_status not in DEPENDENCY_STATUSES:
        out.append(
            _violation(
                "missing_field",
                "renderer_env.dependency_status",
                "dependency_status обязателен",
            )
        )
    if dependency_status == "unavailable" and _str(renderer_env.get("unavailable_reason")) is None:
        out.append(
            _violation(
                "missing_renderer_reason",
                "renderer_env.unavailable_reason",
                "unavailable требует явной причины (PGV-AC17)",
            )
        )

    sensitive = _rec(snapshot.get("sensitive"))
    if sensitive.get("raw_data_included") is not False:
        out.append(
            _violation(
                "raw_data_included_forbidden",
                "sensitive.raw_data_included",
                "metadata не вкладывает raw данные (spec §11)",
            )
        )
    if _str(sensitive.get("sensitive_fields_policy")) is None:
        out.append(
            _violation(
                "missing_field",
                "sensitive.sensitive_fields_policy",
                "политика чувствительных полей обязательна",
            )
        )

    annotations = _rec(snapshot.get("annotations"))
    revision = _num(annotations.get("revision"))
    if revision is None or revision < 0 or revision != int(revision):
        out.append(
            _violation(
                "missing_field",
                "annotations.revision",
                "revision аннотаций -- неотрицательное целое",
            )
        )

    return out


# ── validate_visual_result ───────────────────────────────────────


def validate_visual_result(result: Any) -> list[PrintSchemaViolation]:
    """Валидация VisualResult/1 (frozen input producer'а, spec §6)."""
    out: list[PrintSchemaViolation] = []
    if not isinstance(result, dict):
        return [_violation("missing_field", "(root)", "visual result must be an object")]

    if result.get("schema_version") != PRINT_RESULT_SCHEMA_VERSION:
        out.append(
            _violation(
                "schema_version_mismatch",
                "schema_version",
                f"ожидается {PRINT_RESULT_SCHEMA_VERSION}",
            )
        )
    if _str(result.get("view_id")) is None:
        out.append(_violation("missing_field", "view_id", "view_id обязателен"))

    payload = _rec(result.get("payload"))
    kind = _str(payload.get("kind"))
    if kind is None or kind not in SECTION_RENDERER_KINDS:
        out.append(
            _violation("invalid_section_kind", "payload.kind", "payload.kind -- базовый renderer_kind")
        )
    digest = _str(payload.get("digest"))
    digest_reason = _str(payload.get("digest_reason"))
    if digest is None and digest_reason is None:
        out.append(
            _violation(
                "missing_digest",
                "payload.digest",
                "digest XOR явная причина (legacy_unknown честен)",
            )
        )
    elif digest is not None and digest_reason is not None:
        out.append(
            _violation("ambiguous_source_hash", "payload.digest", "digest и reason взаимоисключающи")
        )

    _validate_trusted_parameters(
        result.get("parameters"), {"allowlist": [], "values": {}}, None, out
    )
    _validate_units_list(result.get("units"), "units", out)
    _validate_sampling(result.get("sampling"), True, out)

    execution = _rec(result.get("execution"))
    if _str(execution.get("result_ref")) is None:
        out.append(
            _violation("missing_result_ref", "execution.result_ref", "result_ref обязателен")
        )
    _validate_time_xor(
        execution.get("computed_at"),
        execution.get("computed_at_reason"),
        "execution.computed_at",
        "missing_date",
        out,
    )

    return out


# ── validate_print_set_manifest ──────────────────────────────────


def validate_print_set_manifest(manifest: Any) -> list[PrintSchemaViolation]:
    """Валидация PrintSetManifest/1 (ZIP: PNG + manifest + metadata, spec §7)."""
    out: list[PrintSchemaViolation] = []
    if not isinstance(manifest, dict):
        return [_violation("missing_field", "(root)", "manifest must be an object")]

    if manifest.get("schema_version") != PRINT_MANIFEST_SCHEMA_VERSION:
        out.append(
            _violation(
                "schema_version_mismatch",
                "schema_version",
                f"ожидается {PRINT_MANIFEST_SCHEMA_VERSION}",
            )
        )
    if _str(manifest.get("set_id")) is None:
        out.append(_violation("missing_field", "set_id", "set_id обязателен"))
    if _str(manifest.get("render_version")) is None:
        out.append(_violation("missing_field", "render_version", "render_version обязательна"))
    profile_id = _str(manifest.get("profile_id"))
    if profile_id is None or resolve_print_profile(profile_id) is None:
        out.append(_violation("invalid_profile", "profile_id", "профиль обязан быть из каталога"))
    if _str(manifest.get("metadata_filename")) is None:
        out.append(
            _violation(
                "missing_field",
                "metadata_filename",
                "metadata_filename обязателен (hash вне PNG bytes)",
            )
        )

    pages = manifest.get("pages")
    pages = pages if isinstance(pages, list) else []
    seen: set[str] = set()
    indexes: list[float] = []
    for index, page in enumerate(pages):
        rec = _rec(page)
        path = f"pages[{index}]"
        filename = _str(rec.get("filename"))
        if filename is None:
            out.append(
                _violation("missing_field", f"{path}.filename", "имя файла страницы обязательно")
            )
        elif filename in seen:
            out.append(
                _violation(
                    "duplicate_filename", f"{path}.filename", f"дубликат имени страницы: {filename}"
                )
            )
        else:
            seen.add(filename)
        page_index = _num(rec.get("index"))
        if page_index is None or page_index < 1 or page_index != int(page_index):
            out.append(
                _violation("page_order_gap", f"{path}.index", "index страницы -- целое >= 1")
            )
        else:
            indexes.append(page_index)
        width = _num(rec.get("width_px"))
        height = _num(rec.get("height_px"))
        if width is None or width <= 0 or height is None or height <= 0:
            out.append(
                _violation(
                    "missing_field",
                    f"{path}.width_px/height_px",
                    "пиксели страницы обязательны",
                )
            )
        if not _is_hex64(rec.get("png_sha256")):
            out.append(
                _violation(
                    "missing_page_hash",
                    f"{path}.png_sha256",
                    "hash PNG хранится в manifest отдельным полем, не внутрь PNG bytes",
                )
            )
    indexes.sort()
    for position, page_index in enumerate(indexes):
        if page_index != position + 1:
            out.append(
                _violation(
                    "page_order_gap",
                    "pages.index",
                    "порядок страниц должен быть непрерывным 1..n",
                )
            )
            break

    if manifest.get("data_included") is not False:
        out.append(
            _violation(
                "data_included_forbidden",
                "data_included",
                "ZIP -- контейнер PNG и метаданных; raw DataFrame не вкладывается (PGV-AC21)",
            )
        )

    return out
