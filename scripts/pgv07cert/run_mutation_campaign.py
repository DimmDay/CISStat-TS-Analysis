#!/usr/bin/env python3
"""
PGV-07-CERT — мутационная кампания «на своих мутантах».

Метод серии CERT (прецеденты pgv00cert/pgv02cert/pgv03cert/pgv05cert/pgv06cert):
  - боевые мутанты: по ОДНОМУ поведенческому изменению на функцию поставки;
  - каналы: REPO = repo-корпус поставки (printLayout.test + printPassport.test,
    48 тестов), ORACLE = Class A корпуса сертификатора (test_p7cert_oracles, 73);
  - контроли K01–K03 (no-op) — обязаны остаться ALIVE (каналы не убивают тривиально);
  - MV1: уникальность каждого якоря (count==1 в мутируемом файле);
  - MV2: восстановление после каждого мутанта с md5-сверкой (== HEAD);
  - MV5: чистота дерева после кампании (md5 всех мутируемых файлов == HEAD).

Запуск: python3 scripts/pgv07cert/run_mutation_campaign.py [--only M01,K01]
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "protocols"

# (id, файл, якорь, замена, ожидание)
MUTANTS: list[tuple[str, str, str, str, str]] = [
    # ── printTheme.ts ────────────────────────────────────────────────
    ("M01", "packages/ui/print/printTheme.ts",
     'page_background: "#FFFFFF"', 'page_background: "#FEFEFE"',
     "KILL: AC04 байт-диф фона (repo U10-класс + oracle A2.2)"),
    ("M02", "packages/ui/print/printTheme.ts",
     '{ key: "positive", color: PRINT_PALETTE.status_success, mark: "+", label: "рост/улучшение" }',
     '{ key: "positive", color: PRINT_PALETTE.status_success, mark: "", label: "рост/улучшение" }',
     "KILL: цвет перестаёт дублироваться знаком (§7); repo 121-133 + oracle A10.3"),
    ("M03", "packages/ui/print/printTheme.ts",
     "const direct = CHART_VARS_LIGHT[name];\n  if (direct !== undefined) return direct;",
     "const direct = CHART_VARS_LIGHT[name];\n  if (direct !== undefined) return null;",
     "KILL: паритет с картой потерян; repo 103-110 + oracle A10.6"),
    ("M04", "packages/ui/print/printTheme.ts",
     'return /^#[0-9A-Fa-f]{6}$/.test(value);',
     'return /^#[0-9A-Fa-f]{3,6}$/.test(value);',
     "KILL: 3-значные hex проходят; repo 92-101 + oracle A10.7"),
    # ── printLayout.tsx ──────────────────────────────────────────────
    ("M05", "packages/ui/print/printLayout.tsx",
     'const trimmedFrac = fracPart ? fracPart.replace(/0+$/, "") : "";',
     'const trimmedFrac = fracPart ? fracPart : "";',
     "KILL: хвостовые нули не срезаются (»,250»); repo 285-289 + oracle A1.1"),
    ("M06", "packages/ui/print/printLayout.tsx",
     "const time = iso.slice(11, 16);",
     "const time = iso.slice(11, 13);",
     "KILL: минуты теряются; repo 269-272 + oracle A1.3"),
    ("M07", "packages/ui/print/printLayout.tsx",
     "if (reason) return `неизвестно (${reason})`;\n  return \"—\";",
     'return "—";',
     "KILL: причина времени теряется (XOR); repo 274-277 + oracle A1.4"),
    ("M08", "packages/ui/print/printLayout.tsx",
     'if (unit.reason) return `без единицы (${unit.reason})`;',
     'if (unit.reason) return "—";',
     "KILL: причина единицы теряется; repo 279-283 + oracle A1.5"),
    ("M09", "packages/ui/print/printLayout.tsx",
     'return ref.length <= keep ? ref : `${ref.slice(0, Math.max(1, keep))}…`;',
     "return ref.length <= keep ? ref : ref.slice(0, Math.max(1, keep));",
     "KILL: молчаливое укорачивание без маркера; repo 291-298 + oracle A1.6"),
    ("M10", "packages/ui/print/printLayout.tsx",
     "const cap = sampling.point_cap !== null ? `, потолок ${String(sampling.point_cap)} точек` : \"\";",
     'const cap = "";',
     "KILL: потолок точек теряется (AC08); repo 240-252 + oracle A1.7"),
    ("M11", "packages/ui/print/printLayout.tsx",
     "backgroundColor: PRINT_PALETTE.page_background,\n        color: PRINT_PALETTE.ink,\n        fontFamily: PRINT_FONT_STACK,",
     "backgroundColor: PRINT_PALETTE.band_fill,\n        color: PRINT_PALETTE.ink,\n        fontFamily: PRINT_FONT_STACK,",
     "KILL: фон поверхности не белый; repo 329-340 + oracle A2.2"),
    ("M12", "packages/ui/print/printLayout.tsx",
     '            {labelValue(\n              "рассчитано",\n              formatPrintTime(\n                snapshot.times.computed_at,\n                snapshot.times.computed_at_reason,\n                snapshot.times.timezone,\n              ),\n            )}',
     "            {null}",
     "KILL: computed_at теряется из meta (AC05); repo 189-204/225-238 + oracle A3.1"),
    ("M13", "packages/ui/print/printLayout.tsx",
     '{labelValue("страница", `Стр. ${pageIndex} из ${pageCount}`)}',
     '{labelValue("страница", "Стр. 1 из 1")}',
     "KILL: номер страницы фабкуется; repo 221-222 + oracle A3.2"),
    ("M14", "packages/ui/print/printLayout.tsx",
     "            {snapshot.checkpoint?.reused &&\n              labelValue(\n                \"checkpoint\",",
     "            {false &&\n              labelValue(\n                \"checkpoint\",",
     "KILL: reused-checkpoint строка теряется; oracle A3.4 (repo-слепой)"),
    ("M15", "packages/ui/print/printLayout.tsx",
     "      {ordering.map((entry, index) => (",
     "      {[] .map((entry, index) => (",
     "KILL: легенда пустая (§7); repo 392-398 + oracle A10.1"),
    # ── printSections.tsx ────────────────────────────────────────────
    ("M16", "packages/ui/print/printSections.tsx",
     "const size = Math.max(1, Math.floor(rowsPerPage));",
     "const size = Math.max(2, Math.floor(rowsPerPage));",
     "KILL: минимальный размер 2 (1 строка/часть сломана); repo 400-407 + oracle A4.2"),
    ("M17", "packages/ui/print/printSections.tsx",
     "          {chunkIndex > 0 && (\n            <caption",
     "          {false && (\n            <caption",
     "KILL: метка «Продолжение» теряется; repo 409-428 + oracle A4.3"),
    ("M18", "packages/ui/print/printSections.tsx",
     "          <thead>\n            <tr style={{ backgroundColor: PRINT_PALETTE.band_fill }}>\n              {headings.row.map((heading) => (",
     "          {chunkIndex > 0 ? null : (\n          <thead>\n            <tr style={{ backgroundColor: PRINT_PALETTE.band_fill }}>\n              {headings.row.map((heading) => (",
     "KILL: повтор заголовков на частях 2+ (AC15); repo 423-424 + oracle A4.3"),
    ("M19", "packages/ui/print/printSections.tsx",
     "  const t = span <= 0 ? 0 : Math.min(1, Math.max(0, (value - min) / span));",
     "  const t = (value - min) / span;",
     "KILL: clamp домена снят; oracle A4.5/пробы P5 (repo-слепой)"),
    ("M20", "packages/ui/print/printSections.tsx",
     '                    {value === null ? missingText : cellText(rowIndex, columnIndex)}',
     '                    {value === null ? "0" : cellText(rowIndex, columnIndex)}',
     "KILL: пропуск подменяется нулём (фабкация!); repo 430-461 + oracle A4.6"),
    ("M21", "packages/ui/print/printSections.tsx",
     "export function describeAxis(axis: AxisSpec): string {\n  const units = formatUnit(axis.units);\n  return `${axis.name} (${units})`;\n}",
     "export function describeAxis(axis: AxisSpec): string {\n  return axis.name;\n}",
     "KILL: оси без единиц/причин; repo 371-390 + oracle A1.8/A4.1"),
    # ── printIh.tsx ──────────────────────────────────────────────────
    ("M22", "packages/ui/print/printIh.tsx",
     "function percentText(value: number): string {\n  return `${formatNumberRu(value, 1)} %`;\n}",
     "function percentText(value: number): string {\n  return formatNumberRu(value, 1);\n}",
     "KILL: проценты без единицы; repo 499-508 + oracle A5.1"),
    ("M23", "packages/ui/print/printIh.tsx",
     "                {hasRowTotals\n                  ? formatNumberRu(input.row_totals?.[rowIndex] ?? null, 0)\n                  : \"—\"}",
     '                : "—"}',
     "KILL: знаменатели строк теряются (AC02); repo 510-517 + oracle A5.1/A5.2"),
    ("M24", "packages/ui/print/printIh.tsx",
     "        Строки — интервалы «{input.feature_label}», столбцы — интервалы «{input.target_label}»; каждая строка\n        суммируется до 100 %. Наблюдений: {formatNumberRu(input.n_observations, 0)}.",
     "        Наблюдений: {formatNumberRu(input.n_observations, 0)}.",
     "KILL: правило 100 % теряется; repo 510-517 + oracle A5.1"),
    # ── printPassport.tsx ────────────────────────────────────────────
    ("M25", "packages/ui/print/printPassport.tsx",
     "            {KNOWN_PASSPORT_GROUPS.filter((group) => {\n              const value = (record.passport ?? {})[group.key];\n              return value !== undefined && value !== null;\n            }).map((group) => {",
     "            {KNOWN_PASSPORT_GROUPS.map((group) => {",
     "KILL: фабкация пустых секций отсутствующих групп; repo 85-95 (косв.) + oracle A6.1"),
    ("M26", "packages/ui/print/printPassport.tsx",
     "          {!isKnownSchema && (\n            <div\n              data-testid=\"print-passport-unsupported-schema\"",
     "          {false && (\n            <div\n              data-testid=\"print-passport-unsupported-schema\"",
     "KILL: unsupported_schema баннер теряется (§8); repo 136-141 + oracle A6.7/A6.8"),
    ("M27", "packages/ui/print/printPassport.tsx",
     "function xorText(value: string | null, reason: string | null | undefined): string {\n  if (value) return value;\n  if (reason) return `неизвестно (${reason})`;\n  return \"—\";\n}",
     'function xorText(value: string | null, reason: string | null | undefined): string {\n  return "—";\n}',
     "KILL: причины XOR-полей теряются (AC12); repo 117-134 + oracle A6.4"),
    ("M28", "packages/ui/print/printPassport.tsx",
     '«{record.content_gap_reason ?? "не указана"}». Содержимое не фабрикуется и не заменяется',
     '«не указана». Содержимое не фабрикуется и не заменяется',
     "KILL: причина content-гэпа теряется; repo 143-158/160-169 + oracle A6.6"),
    ("M29", "packages/ui/print/printPassport.tsx",
     "  const unknownGroupKeys = record.passport\n    ? Object.keys(record.passport).filter((key) => !knownKeys.has(key))\n    : [];",
     "  const unknownGroupKeys: string[] = [];",
     "KILL: неизвестные группы выбрасываются (§8); repo 97-102 + oracle A6.1"),
    # ── printComparison.tsx ──────────────────────────────────────────
    ("M30", "packages/ui/print/printComparison.tsx",
     "function signedNumber(value: number, digits = 1): string {\n  const sign = value > 0 ? \"+\" : value < 0 ? \"−\" : \"\";\n  return `${sign}${formatNumberRu(Math.abs(value), digits)}`;\n}",
     "function signedNumber(value: number, digits = 1): string {\n  return formatNumberRu(Math.abs(value), digits);\n}",
     "KILL: знак дельты теряется (AC13); repo 224-233 + oracle A7.1"),
    ("M31", "packages/ui/print/printComparison.tsx",
     "          reused ref: {snapshot.confirmation.reused_ref ?? \"—\"}.{\" \"}",
     "          {\" \"}",
     "KILL: reused ref подтверждения теряется (AC11); repo 252-282 + oracle A7.6"),
    ("M32", "packages/ui/print/printComparison.tsx",
     "      {snapshot.gaps.length > 0 && (",
     "      {false && (",
     "KILL: gaps не печатаются (partial тихий, §9); repo 284-304 + oracle A7.4"),
    ("M33", "packages/ui/print/printComparison.tsx",
     "      <section\n        data-testid=\"print-comparison-definitions\"",
     "      <section\n        style={{ display: \"none\" }}\n        data-testid=\"print-comparison-definitions\"",
     "KILL: definitions скрыты (zero-denominator reason теряется); repo 235-241 + oracle A7.3"),
    ("M34", "packages/ui/print/printComparison.tsx",
     "          {snapshot.cross_context && <Badge tone=\"warning\">cross_context: явный режим сравнения исторических контекстов</Badge>}",
     "          {null}",
     "KILL: cross_context не маркируется (§9); repo 306-311 + oracle A7.5"),
    # ── Контроли (обязаны остаться ALIVE) ────────────────────────────
    ("K01", "packages/ui/print/printTheme.ts",
     "/** 6-значный непрозрачный hex-цвет (#RRGGBB). */",
     "/** 6-значный непрозрачный hex-цвет (#RRGGBB). Комментарий контроля K01. */",
     "CONTROL: docstring-комментарий — ALIVE"),
    ("K02", "packages/ui/print/printLayout.tsx",
     "// ── Форматтеры (детерминированные, без ICU/локали машины) ────────",
     "// ── Форматтеры (детерминированные, без ICU/локали машины) ────────\n// Нейтральный комментарий контроля (без namespace-токенов).",
     "CONTROL: нейтральный комментарий — ALIVE"),
    ("K03", "packages/ui/print/printPassport.tsx",
     "/** Известные группы паспорта с человекочитаемыми подписями (§8 «все группы»). */",
     "/** Известные группы паспорта с человекочитаемыми подписями (§8 «все группы»). К3. */",
     "CONTROL: docstring-комментарий — ALIVE"),
]

PRINT_FILES = sorted({m[1] for m in MUTANTS})


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def head_md5() -> dict[str, str]:
    return {f: md5(REPO / f) for f in PRINT_FILES}


def apply_mutant(file: str, anchor: str, replacement: str) -> bool:
    p = REPO / file
    src = p.read_text(encoding="utf-8")
    if src.count(anchor) != 1:
        return False
    p.write_text(src.replace(anchor, replacement), encoding="utf-8")
    return True


def restore(file: str, expected_md5: str) -> bool:
    p = REPO / file
    subprocess.run(["git", "checkout", "--", file], cwd=REPO, check=True,
                   capture_output=True)
    return md5(p) == expected_md5


def run_channel(paths: list[str]) -> tuple[bool, str]:
    """Возвращает (all_passed, вывод)."""
    cmd = ["npx", "jest", "--silent", *paths]
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=600)
    out = r.stdout + r.stderr
    return ("Tests:" in out and " failed" not in out.split("Tests:")[-1].split(",")[0]
            and "passed" in out), out


def main() -> int:
    only = None
    if len(sys.argv) > 2 and sys.argv[1] == "--only":
        only = set(sys.argv[2].split(","))

    OUT.mkdir(parents=True, exist_ok=True)
    base = head_md5()
    journal: list[dict] = []

    # MV1: уникальность якорей
    mv1_failures = []
    for mid, file, anchor, replacement, expect in MUTANTS:
        if only and mid not in only:
            continue
        src = (REPO / file).read_text(encoding="utf-8")
        if src.count(anchor) != 1:
            mv1_failures.append((mid, file, src.count(anchor)))
    print(f"MV1 уникальность якорей: {'OK' if not mv1_failures else mv1_failures}")
    if mv1_failures:
        return 2

    for mid, file, anchor, replacement, expect in MUTANTS:
        if only and mid not in only:
            continue
        ok = apply_mutant(file, anchor, replacement)
        if not ok:
            journal.append({"id": mid, "status": "APPLY-FAIL"})
            print(f"{mid}: APPLY-FAIL")
            continue
        repo_ok, repo_out = run_channel([
            "packages/ui/print/printLayout.test.tsx",
            "packages/ui/print/printPassport.test.tsx",
        ])
        oracle_ok, oracle_out = run_channel([
            "scripts/pgv07cert/test_p7cert_oracles.test.tsx",
        ])
        repo_pass = repo_ok
        oracle_pass = oracle_ok
        if mid.startswith("K"):
            status = "ALIVE" if (repo_pass and oracle_pass) else "KILLED"
        else:
            if not repo_pass and not oracle_pass:
                status = "DUAL-KILLED"
            elif not repo_pass and oracle_pass:
                status = "REPO-ONLY-KILLED"
            elif repo_pass and not oracle_pass:
                status = "ORACLE-ONLY-KILLED"
            else:
                status = "SURVIVED"
        restored = restore(file, base[file])
        if not restored:
            print(f"{mid}: RESTORE-FAIL — аварийный останов")
            return 3
        journal.append({
            "id": mid, "file": file, "expect": expect,
            "repo_pass": repo_pass, "oracle_pass": oracle_pass,
            "status": status, "restored": restored,
        })
        print(f"{mid}: {status} (repo={'PASS' if repo_pass else 'FAIL'}, oracle={'PASS' if oracle_pass else 'FAIL'})")

    final = head_md5()
    clean = final == base
    print(f"MV5 чистота дерева: {'OK (md5==HEAD)' if clean else 'DIRTY'}")
    (OUT / "mutation_journal.json").write_text(
        json.dumps({"journal": journal, "tree_clean": clean, "head_md5": base},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
