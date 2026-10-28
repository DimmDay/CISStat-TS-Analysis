# scripts/pgv01cert/mutations.py
#
# PGV-01-CERT — каталог мутационной кампании «мутанты на своих мутантах».
#
# Каждый мутант: уникальный якорь (count==1 в целевом файле), замена,
# прегистрированный исход по каналам:
#   REPO   — jest printSchema.test.ts + pytest test_pgv01_print_schema.py
#            + guard scripts/pgv01/check_documents.py + guard pgv00;
#   ORACLE — Класс A корпуса сертификатора (static + parity, без Класса B).
#
# Классы: DUAL (ловят оба канала) / ORACLE-ONLY (добавленная ценность
# канала сертификатора: repo-каналы слепы) / CONTROL (заведомый no-op,
# обязан оставаться ALIVE в обоих каналах).
#
# MV-уроки PGV-00-CERT учтены: якоря уникальны, замена не no-op (проверяет
# MV1), восстановление байт-честно (MV3), контроли не убиваются остаточными
# артефактами (MV4/MV5).

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Mutant:
    mid: str
    file: str
    anchor: str
    replacement: str
    expected: dict = field(default_factory=dict)  # {"REPO": "KILL"|"ALIVE", "ORACLE": ...}
    klass: str = "DUAL"
    note: str = ""


TS = "packages/ui/print/printSchema.ts"
PY = "apps/api/print_schema.py"
TWIN = "config/print_schema.json"
REGISTRY = "config/visual_registry.json"

MUTANTS: list[Mutant] = [
    # ── TS-источник истины ──────────────────────────────────────────
    Mutant(
        "M01", TS,
        'research: ["context_id", "data_revision"],',
        'research: ["context_id"],',
        {"REPO": "KILL", "ORACLE": "KILL"}, "DUAL",
        "ослабление мандата research-refs (критерий version)",
    ),
    Mutant(
        "M02", TS,
        'export const PARAMETER_ORIGINS: readonly ParameterOrigin[] = [\n  "producer_freeze",\n  "producer_first_export",\n];',
        'export const PARAMETER_ORIGINS: readonly ParameterOrigin[] = [\n  "producer_freeze",\n  "producer_first_export",\n  "client_request",\n];',
        {"REPO": "KILL", "ORACLE": "KILL"}, "DUAL",
        "доверие клиентскому origin (параметры trusted)",
    ),
    Mutant(
        "M03", TS,
        'export function samplingRequiredForSite(site: VisualSiteRecord): boolean {\n  return site.renderer_kind !== "html_cards";\n}',
        'export function samplingRequiredForSite(site: VisualSiteRecord): boolean {\n  return site.renderer_kind !== "html_cards" && site.renderer_kind !== "html_heatmap";\n}',
        {"REPO": "KILL", "ORACLE": "KILL"}, "DUAL",
        "тихое исключение heatmap из sampling (переатрибутировано: repo убивают jest-пин samplingRequiredForSite(matrix) и pytest test_sampling_rules_match_registry_kinds)",
    ),
    Mutant(
        "M04", TS,
        "  return hasValue !== hasReason;\n}",
        "  return hasValue || hasReason;\n}",
        {"REPO": "KILL", "ORACLE": "KILL"}, "DUAL",
        "XOR→OR в isUnitDeclared (принимает value+reason)",
    ),
    Mutant(
        "M05", TS,
        "  if ((SAMPLING_MODES_REQUIRING_POINT_CAP as readonly string[]).includes(mode)) {",
        "  if (false) {\n    void (SAMPLING_MODES_REQUIRING_POINT_CAP as readonly string[]);",
        {"REPO": "KILL", "ORACLE": "KILL"}, "DUAL",
        "снятие требования point_cap (скрытый detail upgrade)",
    ),
    Mutant(
        "M06", TS,
        '  if (print.theme !== "light-print") {',
        "  if (false) {\n    void print;",
        {"REPO": "ALIVE", "ORACLE": "KILL"}, "ORACLE-ONLY",
        "снятие мандата light-print (repo-канал не тестирует theme)",
    ),
    Mutant(
        "M07", TS,
        "  if (sensitive.raw_data_included !== false) {",
        "  if (false) {\n    void sensitive;",
        {"REPO": "KILL", "ORACLE": "KILL"}, "DUAL",
        "разрешение raw данных в metadata",
    ),
    Mutant(
        "M08", TS,
        "  indexes.forEach((index, i) => {\n    if (index !== i + 1) {",
        "  indexes.forEach((index, i) => {\n    if (false && index !== i + 1) {",
        {"REPO": "KILL", "ORACLE": "KILL"}, "DUAL",
        "снятие проверки непрерывности порядка страниц",
    ),
    Mutant(
        "M09", TS,
        "    width_px: 2480,\n    height_px: 3508,",
        "    width_px: 2481,\n    height_px: 3508,",
        {"REPO": "KILL", "ORACLE": "KILL"}, "DUAL",
        "дрейф закреплённых пикселей A4 (PGV-AC16)",
    ),
    Mutant(
        "M10", TS,
        "    if (str(expected.context_id) === null || str(expected.data_revision) === null) {",
        "    if (false) {",
        {"REPO": "ALIVE", "ORACLE": "KILL"}, "ORACLE-ONLY",
        "снятие мандата expected_context (PGV-AC07): типобезопасная правка ВНУТРЕННЕГО условия — repo-канал поведенчески слеп (обёртка if (false) снаружи отбрасывала narrowing value и убивалась ts-диагностикой TS2339 — честно зафиксировано и перепроектировано)",
    ),
    Mutant(
        "M11", TS,
        "    if (sections.length < 2) {",
        "    if (false) {",
        {"REPO": "ALIVE", "ORACLE": "KILL"}, "ORACLE-ONLY",
        "mixed-сайт с одной секцией допустим; типобезопасный вариант — repo-канал поведенчески слеп (первая редакция убивалась ts-диагностикой TS2339 — честно зафиксировано и перепроектировано)",
    ),
    Mutant(
        "M12", TS,
        '    if (site.applicability === "univariate" && str(dimensions.entity_id) !== null) {',
        "    if (false) {\n      void dimensions;",
        {"REPO": "KILL", "ORACLE": "KILL"}, "DUAL",
        "разрешение entity на univariate (panel mixing)",
    ),
    Mutant(
        "M13", TS,
        "  if (value.data_included !== false) {",
        "  if (true) {\n    void value;",
        {"REPO": "KILL", "ORACLE": "KILL"}, "DUAL",
        "инверсия data_included (валидный манифест отбивается)",
    ),
    Mutant(
        "M14", TS,
        "    } else if (seenFilenames.has(filename)) {",
        "    } else if (false && seenFilenames.has(filename)) {",
        {"REPO": "KILL", "ORACLE": "KILL"}, "DUAL",
        "снятие запрета дубликатов имён страниц",
    ),
    # ── Python-зеркало (preflight PGV-02/09) ────────────────────────
    Mutant(
        "M15", PY,
        '    "research": ["context_id", "data_revision"],',
        '    "research": ["context_id"],',
        {"REPO": "KILL", "ORACLE": "KILL"}, "DUAL",
        "ослабление мандата research-refs в зеркале",
    ),
    Mutant(
        "M16", PY,
        '    return value if isinstance(value, str) and value.strip() else None',
        '    return value if isinstance(value, str) and value else None',
        {"REPO": "ALIVE", "ORACLE": "KILL"}, "ORACLE-ONLY",
        "принятие whitespace-строк (кейс O01; repo-канал без такого фиксатора)",
    ),
    Mutant(
        "M17", PY,
        '    allowed = set("0123456789abcdef")',
        '    allowed = set("0123456789abcdefABCDEF")',
        {"REPO": "ALIVE", "ORACLE": "KILL"}, "ORACLE-ONLY",
        "принятие UPPERCASE hex-hash (кейс O02; repo-канал слеп)",
    ),
    Mutant(
        "M18", PY,
        "        if cap is None or cap <= 0:",
        "        if False:\n            pass",
        {"REPO": "KILL", "ORACLE": "KILL"}, "DUAL",
        "снятие point_cap в зеркале",
    ),
    Mutant(
        "M19", PY,
        '    if print_block.get("theme") != "light-print":',
        "    if False:\n        pass",
        {"REPO": "ALIVE", "ORACLE": "KILL"}, "ORACLE-ONLY",
        "снятие light-print в зеркале (repo-канал не тестирует theme)",
    ),
    Mutant(
        "M20", PY,
        '    if sensitive.get("raw_data_included") is not False:',
        "    if False:\n        pass",
        {"REPO": "KILL", "ORACLE": "KILL"}, "DUAL",
        "разрешение raw данных в зеркале",
    ),
    # ── JSON-твины ──────────────────────────────────────────────────
    Mutant(
        "M21", TWIN,
        '    "render_timeout_s": 60,',
        '    "render_timeout_s": 61,',
        {"REPO": "KILL", "ORACLE": "KILL"}, "DUAL",
        "дрейф лимита §7 в твине",
    ),
    Mutant(
        "M22", TWIN,
        '    "missing_title",\n',
        "",
        {"REPO": "KILL", "ORACLE": "KILL"}, "DUAL",
        "потеря кода нарушения в контракте твина",
    ),
    Mutant(
        "M23", REGISTRY,
        '      "view_id": "upload.structure.schema",\n      "module_id": "upload",\n      "stop_id": "structure",\n      "render_site": "packages/ui/components/StructuralClassSchema.tsx",\n      "mounted_at": "packages/ui/components/TsAnalysisUpload.tsx#structure",\n      "renderer_kind": "html_table",\n      "source_adapter": "pgv-03/upload_structure",\n      "required_refs": [\n        "context_id",\n        "data_revision",\n        "date_column",',
        '      "view_id": "upload.structure.schema",\n      "module_id": "upload",\n      "stop_id": "structure",\n      "render_site": "packages/ui/components/StructuralClassSchema.tsx",\n      "mounted_at": "packages/ui/components/TsAnalysisUpload.tsx#structure",\n      "renderer_kind": "html_table",\n      "source_adapter": "pgv-03/upload_structure",\n      "required_refs": [\n        "context_id",\n        "date_column",',
        {"REPO": "KILL", "ORACLE": "KILL"}, "DUAL",
        "снятие уточнения PGV-01 у upload.structure.schema",
    ),
    # ── Контроли (заведомый no-op, ALIVE) ───────────────────────────
    Mutant(
        "K01", TS,
        "// ── Версии схем ──────────────────────────────────────────────────",
        "// ── Версии схем ──────────────────────────────────────────────────\n// p1cert control: no-op comment (K01)",
        {"REPO": "ALIVE", "ORACLE": "ALIVE"}, "CONTROL",
        "no-op комментарий в TS",
    ),
    Mutant(
        "K02", PY,
        "# ── Загрузка твинов ──────────────────────────────────────────────",
        "# ── Загрузка твинов ──────────────────────────────────────────────\n# p1cert control: no-op comment (K02)",
        {"REPO": "ALIVE", "ORACLE": "ALIVE"}, "CONTROL",
        "no-op комментарий в Python",
    ),
    Mutant(
        "K03", TWIN,
        '      "ppi": 300,\n      "width_in": 8,\n      "height_in": 5,',
        '      "width_in": 8,\n      "ppi": 300,\n      "height_in": 5,',
        {"REPO": "ALIVE", "ORACLE": "ALIVE"}, "CONTROL",
        "перестановка ключей (структурное равенство сохраняется)",
    ),
]

TARGET_FILES = sorted({mutant.file for mutant in MUTANTS})
