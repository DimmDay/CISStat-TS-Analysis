# scripts/pgv16/coverage_gate.py
"""
Task PGV-16 (spec_passport_graphics_visual.md §5/§13, строка PGV-16,
точка изменения «registry»): COV-1 -- fail-closed CERT-гейт покрытия
реестра render-sites.

Spec §5: «PGV-00 создаёт machine-readable registry ... Unknown/unmapped
scientific site блокирует CERT и остаётся в denominator coverage».
До PGV-16 «блокирует CERT» существовало только на TS-стороне
(jest-оракул visualExportRegistry.coverage.test.ts -- AST-скан
исходников) и doc-guard'е scripts/pgv00/check_documents.py. Этот гейт
добавляет Python-сторону (запускается в local_gates/CI без node):

  1. схема pgv.visual_registry/1 + self-consistency registry_version
     (пересчёт FNV-1a/64 UTF-8 хэша канонической сериализации сайтов --
     ТОТ ЖЕ алгоритм, что visualRegistryVersion() в
     packages/ui/lib/visualExportRegistry.ts --
     дрейф TS⇄JSON ловится здесь);
  2. каждый сайт: обязательные поля, уникальность view_id, известные
     module_id/renderer_kind/applicability/export_status, файл
     render_site существует;
  3. exclusions: известный reason_class, непустая причина, существование
     target-файлов;
  4. каждый научный модуль непуст; total_sites == len(sites) ==
     sum(modules);
  5. паритет print-схемы: PRINT_RENDER_BASIS_KINDS ⊇ {V01, P01, P02}
     (печатные семейства PGV-15), профили figure-landscape/a4-*
     присутствуют, лимиты §7 совпадают со штатным print_limits().

Разделение труда честно зафиксировано (docs/pgv16_security_retention_ops_
coverage.md §2 COV-1): Python-гейт -- структура/ссылки/паритет;
TS-оракул -- AST-скан исходников JSX (denominator coverage).

Запуск: python scripts/pgv16/coverage_gate.py [path/to/visual_registry.json]
Exit 0 -- нарушений нет; exit 1 -- перечень нарушений (fail-closed).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_PATH = REPO_ROOT / "config" / "visual_registry.json"

SCHEMA_VERSION = "pgv.visual_registry/1"

KNOWN_MODULE_IDS = frozenset(
    {"navigator", "upload", "validation", "preprocessing",
     "eda", "modeling", "forecasting", "tasks"}
)
KNOWN_RENDERER_KINDS = frozenset(
    {"recharts_svg", "html_table", "html_cards", "html_heatmap",
     "html_matrix", "mixed", "svg_static", "canvas"}
)
KNOWN_APPLICABILITY = frozenset(
    {"univariate", "univariate+panel", "panel", "static_demo"}
)
KNOWN_EXPORT_STATUS = frozenset({"planned", "wired", "legacy_client", "not_mounted"})
KNOWN_REASON_CLASSES = frozenset(
    {"decorative", "ops_admin", "controls", "interactive_editor",
     "operational_list", "placeholder_soon", "legacy_client"}
)

REQUIRED_SITE_FIELDS = (
    "view_id", "module_id", "stop_id", "render_site", "renderer_kind",
    "applicability", "export_status",
)

# Лимиты §7 (spec: 12 MP/page, 20 страниц, 50 MiB, timeout 60 s,
# concurrency tenant=1/global=2) -- гейт сверяет со штатным твином.
EXPECTED_PRINT_LIMITS: dict[str, int] = {
    "max_megapixels_per_page": 12,
    "max_pages_per_set": 20,
    "max_output_bytes": 50 * 1024 * 1024,
    "render_timeout_s": 60,
    "concurrency_per_tenant": 1,
    "concurrency_global": 2,
}

EXPECTED_BASIS_KINDS = frozenset(
    {"visual_print_snapshot", "passport_print_snapshot",
     "passport_comparison_snapshot"}
)
EXPECTED_PRINT_FAMILIES = frozenset({"V01", "P01", "P02"})
REQUIRED_PRINT_PROFILES = ("figure-landscape", "a4-portrait", "a4-landscape")


def fnv1a64_utf8(data: bytes) -> int:
    """FNV-1a/64 по байтам UTF-8 -- паритет fnv1a64Utf8() TS-стороны."""
    h = 0xCBF29CE484222325
    prime = 0x100000001B3
    mask = 0xFFFFFFFFFFFFFFFF
    for b in data:
        h ^= b
        h = (h * prime) & mask
    return h


def canonical_sites_bytes(sites: list[dict]) -> bytes:
    """Каноническая сериализация сайтов -- ТОТ ЖЕ канон, что
    JSON.stringify(VISUAL_SITE_REGISTRY) в TS (без пробелов, порядок
    ключей файла, не-ASCII не экранируются)."""
    return json.dumps(
        sites, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def _registry_violations(payload: dict[str, Any], registry_path: Path) -> list[str]:
    violations: list[str] = []

    if payload.get("schema_version") != SCHEMA_VERSION:
        violations.append(
            f"schema_version: ожидалось {SCHEMA_VERSION!r}, "
            f"факт {payload.get('schema_version')!r}"
        )
    sites = payload.get("sites")
    exclusions = payload.get("exclusions")
    modules = payload.get("modules")
    if not isinstance(sites, list) or not sites:
        violations.append("sites: непустой список обязателен")
        return violations
    if not isinstance(exclusions, list):
        violations.append("exclusions: список обязателен")
        exclusions = []
    if not isinstance(modules, dict):
        violations.append("modules: словарь обязателен")
        modules = {}

    # 1. registry_version -- self-consistency (дрейф TS⇄JSON ловится).
    expected_version = (
        f"pgv16-{fnv1a64_utf8(canonical_sites_bytes(sites)):016x}"
    )
    declared = payload.get("registry_version")
    if not declared:
        violations.append(
            "registry_version: отсутствует -- твин перегенерирован "
            "штатным scripts/pgv00/export_registry.ts?"
        )
    elif declared != expected_version:
        violations.append(
            "registry_version: несогласован с содержимым sites "
            f"(объявлен {declared!r}, вычислен {expected_version!r}) -- "
            "дрейф TS⇄JSON: перегенерируй твин штатным экспортером"
        )

    # 2. Сайты.
    seen_view_ids: set[str] = set()
    module_site_counts: dict[str, int] = {}
    for index, site in enumerate(sites):
        if not isinstance(site, dict):
            violations.append(f"sites[{index}]: запись не объект")
            continue
        view_id = str(site.get("view_id", ""))
        if not view_id:
            violations.append(f"sites[{index}]: view_id отсутствует")
        elif view_id in seen_view_ids:
            violations.append(f"view_id {view_id!r}: дубликат (уникальность §5)")
        seen_view_ids.add(view_id)
        for field in REQUIRED_SITE_FIELDS:
            if not str(site.get(field, "")).strip():
                violations.append(f"sites[{view_id or index}]: поле {field} пусто")
        module_id = str(site.get("module_id", ""))
        if module_id not in KNOWN_MODULE_IDS:
            violations.append(
                f"sites[{view_id}]: неизвестный module_id {module_id!r}"
            )
        module_site_counts[module_id] = module_site_counts.get(module_id, 0) + 1
        renderer_kind = str(site.get("renderer_kind", ""))
        if renderer_kind not in KNOWN_RENDERER_KINDS:
            violations.append(
                f"sites[{view_id}]: неизвестный renderer_kind {renderer_kind!r}"
            )
        applicability = str(site.get("applicability", ""))
        if applicability not in KNOWN_APPLICABILITY:
            violations.append(
                f"sites[{view_id}]: неизвестный applicability {applicability!r}"
            )
        export_status = str(site.get("export_status", ""))
        if export_status not in KNOWN_EXPORT_STATUS:
            violations.append(
                f"sites[{view_id}]: неизвестный export_status {export_status!r}"
            )
        render_site = str(site.get("render_site", ""))
        render_file = render_site.split("#", 1)[0]
        if render_file and not (REPO_ROOT / render_file).exists():
            violations.append(
                f"sites[{view_id}]: render_site-файл {render_file!r} не существует"
            )

    # 3. Exclusions: известный класс, непустая причина, цель существует.
    for index, exclusion in enumerate(exclusions):
        if not isinstance(exclusion, dict):
            violations.append(f"exclusions[{index}]: запись не объект")
            continue
        reason_class = str(exclusion.get("reason_class", ""))
        if reason_class not in KNOWN_REASON_CLASSES:
            violations.append(
                f"exclusions[{index}]: неизвестный reason_class {reason_class!r}"
            )
        if not str(exclusion.get("reason", "")).strip():
            violations.append(f"exclusions[{index}]: причина пуста (честность §3.6)")
        targets = exclusion.get("targets") or []
        if not isinstance(targets, list) or not targets:
            violations.append(f"exclusions[{index}]: targets пуст")
        for target in targets:
            if not _target_exists(target):
                violations.append(
                    f"exclusions[{index}]: target {target!r} не существует"
                )

    # 4. Модули непусты; счётчики согласованы (denominator coverage).
    total_sites = payload.get("total_sites")
    if total_sites != len(sites):
        violations.append(
            f"total_sites: {total_sites!r} != len(sites) {len(sites)}"
        )
    for module_id, count in modules.items():
        if module_id not in KNOWN_MODULE_IDS:
            violations.append(f"modules: неизвестный module_id {module_id!r}")
        actual = module_site_counts.get(module_id, 0)
        if count != actual:
            violations.append(
                f"modules[{module_id}]: объявлено {count}, фактически {actual}"
            )
        if actual == 0:
            violations.append(
                f"модуль {module_id!r} пуст -- научный раздел без coverage "
                "блокирует CERT (§5)"
            )
    for module_id in module_site_counts:
        if module_id not in modules:
            violations.append(
                f"modules: сайт модуля {module_id!r} не отражён в счётчиках"
            )
    return violations


def _target_exists(target: str) -> bool:
    """Существование target-файла exclusion'а (шаблоны с '*' -- glob)."""
    from fnmatch import fnmatch

    target_file = str(target).split("#", 1)[0]
    if not target_file:
        return True
    path = REPO_ROOT / target_file
    if path.exists():
        return True
    if "*" in target_file or "?" in target_file:
        matches = list(REPO_ROOT.glob(target_file))
        return bool(matches)
    return False


def _print_schema_violations() -> list[str]:
    """Паритет print-схемы (PGV-01/14) и печатных семейств (PGV-15):
    документные семейства V01/P01/P02 (PRINT_DOCUMENT_KIND_CODES),
    каталог basis-kinds рендера, профили, лимиты §7."""
    violations: list[str] = []
    repo_str = str(REPO_ROOT)
    if repo_str not in sys.path:
        sys.path.insert(0, repo_str)
    try:
        from apps.api.print_schema import print_limits
    except Exception as exc:  # noqa: BLE001 -- fail-closed
        return [f"print_schema: импорт print_limits не удался ({type(exc).__name__})"]
    try:
        from apps.api.document_jobs import PRINT_RENDER_BASIS_KINDS
        from apps.api.report_snapshot import PRINT_DOCUMENT_KIND_CODES
    except Exception as exc:  # noqa: BLE001 -- fail-closed
        return [
            f"print_schema: импорт каталогов не удался ({type(exc).__name__})"
        ]
    missing_families = EXPECTED_PRINT_FAMILIES - set(PRINT_DOCUMENT_KIND_CODES)
    if missing_families:
        violations.append(
            f"print_families: печатные семейства {sorted(missing_families)} "
            "отсутствуют в PRINT_DOCUMENT_KIND_CODES -- PGV-15 перечисление "
            "печатных семейств нарушено"
        )
    missing = EXPECTED_BASIS_KINDS - set(PRINT_RENDER_BASIS_KINDS)
    if missing:
        violations.append(
            f"print_basis: basis-kinds {sorted(missing)} отсутствуют в "
            "PRINT_RENDER_BASIS_KINDS -- самодостаточные входы печати "
            "(PGV-13) нарушены"
        )
    limits = print_limits()
    for key, expected in EXPECTED_PRINT_LIMITS.items():
        if limits.get(key) != expected:
            violations.append(
                f"print_limits[{key}]: ожидалось {expected}, факт "
                f"{limits.get(key)!r} (§7 потолки)"
            )
    try:
        from apps.api.print_schema import load_print_schema

        profile_ids = {
            str(profile.get("id"))
            for profile in load_print_schema().get("profiles", [])
        }
        for required in REQUIRED_PRINT_PROFILES:
            if required not in profile_ids:
                violations.append(
                    f"print_profiles: профиль {required!r} отсутствует (§7)"
                )
    except Exception as exc:  # noqa: BLE001 -- fail-closed
        violations.append(
            f"print_profiles: каталог профилей недоступен ({type(exc).__name__})"
        )
    return violations


def run_gate(registry_path: Path | None = None) -> list[str]:
    """Полная проверка; возвращает список нарушений (пустой -- OK)."""
    path = Path(registry_path) if registry_path is not None else DEFAULT_REGISTRY_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 -- fail-closed
        return [f"registry: файл {path} не читается как JSON ({type(exc).__name__})"]
    if not isinstance(payload, dict):
        return [f"registry: {path} -- корень не объект"]
    return _registry_violations(payload, path) + _print_schema_violations()


def main(argv: list[str] | None = None) -> int:
    """CLI-вход: fail-closed -- violations -> SystemExit(1), чисто ->
    SystemExit(0) (гейт обязателен: тишина == зелёный, отсутствие
    файла/парса -- красный)."""
    args = list(sys.argv[1:] if argv is None else argv)
    registry_path = Path(args[0]) if args else None
    violations = run_gate(registry_path)
    path = registry_path or DEFAULT_REGISTRY_PATH
    if violations:
        print(f"PGV-16 coverage gate: FAIL ({len(violations)} нарушений)")
        for violation in violations:
            print(f"  - {violation}")
        raise SystemExit(1)
    print(f"PGV-16 coverage gate: PASS ({path})")
    raise SystemExit(0)


if __name__ == "__main__":  # pragma: no cover -- CLI
    main()
