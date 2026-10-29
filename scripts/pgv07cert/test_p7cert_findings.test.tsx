/**
 * PGV-07-CERT — Class B: RED-свидетельства находок сертификации.
 *
 * НАМЕРЕННО RED на цели сертификации (HEAD с поставкой PGV-07). Требования
 * закодированы без xfail/skip; после PGV-07-FIX обязаны стать GREEN БЕЗ
 * правки смысла (прецедент PGV-00/02/04-FIX §7.4).
 *
 * Находки:
 *   F-P7C1 (низкая, документная): worklog-запись PGV-07 заявляет doc-contract
 *     гвард «62/62», фактический корпус гварда — 41 проверка (класс F-P0C1/
 *     F-P1C3/F-P5C1 — арифметика счётчиков в документации).
 *   F-P7C2 (низкая/средняя, print): свотчи PrintLegendStrip — синтетическое
 *     чередование 2 цветов (index % 2), не факты снапшота: при ≥3 сериях
 *     записи легенды неразличимы цветом; свотч выглядит фактическим цветом
 *     серии, которым не является (§7 «полная legend», §6 series styles).
 *   F-P7C3 (средняя, print): flattenPassportGroup — ветка «не применимо: …»
 *     недостижима (dead code): первый if перехватывает ВСЕ объекты с
 *     !applicable (включая applicable:false) и разворачивает их рекурсивно,
 *     а объект С applicable:true печатается «[object Object]». Док поставки
 *     (docs/pgv07_print_layout.md §3.6) заявляет семантику «applicable:false
 *     + reason — „не применимо: …"», которая кодом не реализована; форма
 *     данных реального паспорта (applicable только на уровне групп) не
 *     ломается, но контрактно возможная форма ломается фабкацией-ломкой.
 */
import { readFileSync } from "node:fs";
import { execSync } from "node:child_process";
import path from "node:path";
import React from "react";
import { render } from "@testing-library/react";

import { flattenPassportGroup } from "../../packages/ui/print/printPassport";
import { PrintLegendStrip } from "../../packages/ui/print/printSections";
import { PrintPassportPage, type PrintPassportRecord } from "../../packages/ui/print/printPassport";

// ── B1: заявление «62/62» vs фактический корпус гварда ───────────

describe("p7cert Class B: F-P7C1 счётчик doc-contract гварда в журнале", () => {
  test("B1 worklog-заявление о числе проверок гварда совпадает с фактическим корпусом", () => {
    const repoRoot = path.resolve(__dirname, "../..");
    const worklog = readFileSync(path.join(repoRoot, "worklog/worklog11.md"), "utf8");
    const pgv07Record = worklog.slice(worklog.indexOf("## Task ID: PGV-07"));
    const declared = pgv07Record.match(/check_documents\.py[^\n]*?(\d+)\/\d+/);
    expect(declared).not.toBeNull(); // заявление присутствует
    const declaredCount = Number(declared![1]);
    const guard = execSync("python3 scripts/pgv07/check_documents.py", {
      cwd: repoRoot,
      encoding: "utf8",
    });
    const actual = guard.match(/гвард: (\d+)\/(\d+)/);
    expect(actual).not.toBeNull();
    const actualCount = Number(actual![2]);
    // Требование (RED сейчас): заявление в журнале == фактическому корпусу.
    expect(actualCount).toBe(declaredCount);
  });
});

// ── B2: свотчи легенды — синтетика, ≥3 серий неразличимы ─────────

describe("p7cert Class B: F-P7C2 свотчи легенды не факты снапшота", () => {
  test("B2 3 записи легенды различимы цветом ИЛИ явно маркированы как иллюстративные", () => {
    const { container } = render(<PrintLegendStrip ordering={["Серия А", "Серия Б", "Серия В"]} />);
    const swatches = Array.from(container.querySelectorAll('[data-testid="print-legend"] [aria-hidden="true"]')) as HTMLElement[];
    expect(swatches.length).toBe(3);
    const colors = new Set(swatches.map((el) => el.style.backgroundColor));
    const text = container.querySelector('[data-testid="print-legend"]')?.textContent ?? "";
    // Требование: различимость (≥3 уникальных цвета) ИЛИ явная маркировка
    // «цвета легенды иллюстративные» (честная маркировка вместо фабкации).
    const marked = text.includes("иллюстративн") || text.includes("не фактические цвета");
    expect(colors.size >= 3 || marked).toBe(true);
  });
});

// ── B3: мёртвая ветка «не применимо» + [object Object] ───────────

describe("p7cert Class B: F-P7C3 flattenPassportGroup dead-branch", () => {
  test("B3a вложенный applicable:false печатает заявленную семантику «не применимо: <reason>»", () => {
    const rows = flattenPassportGroup({
      p7b3: { applicable: false, reason: "p7cert-причина-вложенной-группы", value: null },
    });
    const values = rows.map((r) => `${r.label}=${r.value}`);
    // Требование док поставки §3.6: «applicable:false + reason — „не применимо: …"».
    expect(values).toContain("p7b3=не применимо: p7cert-причина-вложенной-группы");
  });

  test("B3b вложенный applicable:true не печатается «[object Object]» (контрактно возможная форма данных)", () => {
    const rows = flattenPassportGroup({ p7b3b: { value: 1.5, applicable: true } });
    const rendered = rows.map((r) => `${r.label}=${r.value}`).join(" | ");
    expect(rendered).not.toContain("[object Object]");
    // Значение доступно (не потеряно).
    expect(rendered).toContain("1,5");
  });

  test("B3c печатная страница паспорта не производит «[object Object]» на смешанной форме", () => {
    const record: PrintPassportRecord = {
      schema_version: "pgv.passport_history/1",
      snapshot_ref: "artifact:passport:b3",
      session_snapshot_id: "b3",
      artifact_id: "artifact:passport:b3",
      stage: "validation",
      universe: "single",
      content_status: "present",
      content_gap_reason: null,
      passport: {
        freq: { value: "D" },
        mixed: { plain: 1, nested_applicable_true: { value: 2, applicable: true } },
      },
      target_column: "v",
      date_column: "d",
      context_id: "ctx",
      data_revision: "1",
      captured_at: "2026-10-29T00:00:00Z",
      created_at: null,
      fingerprint: null,
      fingerprint_reason: "legacy_unknown",
      source_hash: null,
      source_hash_reason: "legacy_unknown",
      passport_schema_version: "passport/1.1",
      passport_schema_version_reason: null,
      calculation_version: null,
      calculation_version_reason: "legacy_unknown",
    };
    const { getByTestId } = render(<PrintPassportPage record={record} pageIndex={1} pageCount={1} />);
    expect(getByTestId("print-passport-page").textContent ?? "").not.toContain("[object Object]");
  });
});
