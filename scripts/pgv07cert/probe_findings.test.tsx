/**
 * PGV-07-CERT — динамические пробы находок (read-only, продукт не менялся).
 *
 * Пробы P1..P12 — независимая проверка кандидатов-находок сертификатора на
 * живом коде поставки. Ожидания прегистрированы; «CONFIRMED» = кандидат —
 * находка (Class B), «REJECTED» = гипотеза опровергнута.
 *
 * Namespace p7cert-* — дизъюнктен repo-корпусу (printLayout.test/printPassport.test).
 * Файл остаётся в корпусе сертификатора как протокол; в продуктовый граф не входит.
 */
import React from "react";
import { render } from "@testing-library/react";

import {
  flattenPassportGroup,
  KNOWN_PASSPORT_GROUPS,
} from "../../packages/ui/print/printPassport";
import { formatPrintTime, shortRef } from "../../packages/ui/print/printLayout";
import { chunkTableRows, heatColor } from "../../packages/ui/print/printSections";
import { buildMinimalValidSnapshot } from "../../packages/ui/print/printSchema";
import { VISUAL_SITE_REGISTRY } from "../../packages/ui/lib/visualExportRegistry";
import { PrintLegendStrip } from "../../packages/ui/print/printSections";
import { PrintPageFrame } from "../../packages/ui/print/printLayout";
import * as printBarrel from "../../packages/ui/print";

function site(viewId: string) {
  const s = VISUAL_SITE_REGISTRY.find((x) => x.view_id === viewId);
  if (!s) throw new Error(`site not found: ${viewId}`);
  return s;
}

describe("PGV-07-CERT пробы находок (p7cert)", () => {
  // ── P1: flattenPassportGroup для группы с applicable: true ──────
  // Реальная форма данных паспорта (app/core/passport.py):
  //   autocorrelation: { value, is_white_noise, is_ok, tested_lag, applicable: True }
  //   seasonality: { strength, is_seasonal, period, applicable: True }
  // Ожидание находки: печатается «[object Object]» вместо значений.
  test("P1 (REJECTED-документация) flattenPassportGroup: группа с applicable:true разворачивается по полям", () => {
    const group = {
      value: 0.11,
      is_white_noise: false,
      is_ok: false,
      tested_lag: 1,
      applicable: true,
    };
    const rows = flattenPassportGroup(group);
    const rendered = rows.map((r) => `${r.label}=${r.value}`).join(" | ");
    const hasObjectObject = rendered.includes("[object Object]");
    // eslint-disable-next-line no-console
    console.log(`P1 RESULT: ${hasObjectObject ? "CONFIRMED" : "REJECTED"} :: ${rendered}`);
    // ИТОГ СЕРТИФИКАЦИИ: гипотеза ОПРОВЕРГНУТА — поля группы скалярны, разворачиваются.
    expect(hasObjectObject).toBe(false);
  });

  // ── P1b: seasonality (strength/period) — второй реальный кейс ───
  test("P1b (REJECTED-документация) flattenPassportGroup: seasonality applicable:true", () => {
    const rows = flattenPassportGroup({
      strength: 0.35,
      is_seasonal: true,
      period: 7,
      applicable: true,
    });
    const rendered = rows.map((r) => `${r.label}=${r.value}`).join(" | ");
    const hasObjectObject = rendered.includes("[object Object]");
    // eslint-disable-next-line no-console
    console.log(`P1b RESULT: ${hasObjectObject ? "CONFIRMED" : "REJECTED"} :: ${rendered}`);
    // ИТОГ СЕРТИФИКАЦИИ: гипотеза ОПРОВЕРГНУТА.
    expect(hasObjectObject).toBe(false);
  });

  // ── P1c: печатная страница паспорта с реальной формой групп ─────
  test("P1c (REJECTED-документация) PrintPassportPage: реальная форма паспорта без «[object Object]»", () => {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { PrintPassportPage } = require("../../packages/ui/print/printPassport");
    const record = {
      schema_version: "pgv.passport_history/1",
      snapshot_ref: "artifact:passport:s1",
      session_snapshot_id: "s1",
      artifact_id: "artifact:passport:s1",
      stage: "validation",
      universe: "single",
      content_status: "present" as const,
      content_gap_reason: null,
      passport: {
        autocorrelation: { value: 0.11, is_white_noise: false, is_ok: false, tested_lag: 1, applicable: true },
        seasonality: { strength: 0.35, is_seasonal: true, period: 7, applicable: true },
      },
      target_column: "value",
      date_column: "dt",
      context_id: "ctx-1",
      data_revision: "1",
      captured_at: "2026-10-28T10:00:00Z",
      created_at: null,
      fingerprint: "f".repeat(64),
      fingerprint_reason: null,
      source_hash: "a".repeat(64),
      source_hash_reason: null,
      passport_schema_version: "passport/1.1",
      passport_schema_version_reason: null,
      calculation_version: null,
      calculation_version_reason: "legacy_unknown",
    };
    const { getByTestId } = render(<PrintPassportPage record={record} pageIndex={1} pageCount={1} />);
    const text = getByTestId("print-passport-page").textContent ?? "";
    const hasObjectObject = text.includes("[object Object]");
    const lostValue = !text.includes("0,11"); // formatNumberRu(0.11, 4)
    const lostStrength = !text.includes("0,35");
    // eslint-disable-next-line no-console
    console.log(
      `P1c RESULT: ${hasObjectObject ? "CONFIRMED" : "REJECTED"} :: objectObject=${hasObjectObject} lostValue=${lostValue} lostStrength=${lostStrength}`,
    );
    // ИТОГ СЕРТИФИКАЦИИ: гипотеза ОПРОВЕРГНУТА — значения печатаются.
    expect(hasObjectObject).toBe(false);
    expect(lostValue).toBe(false);
  });

  // ── P2: barrel-конфликт PrintLegendStrip (export * дважды) ──────
  test("P2 barrel print/index.ts: PrintLegendStrip резолвится", () => {
    const keys = Object.keys(printBarrel as Record<string, unknown>);
    const hasStrip = keys.includes("PrintLegendStrip");
    // eslint-disable-next-line no-console
    console.log(`P2 RESULT: barrel exports=${keys.length} hasPrintLegendStrip=${hasStrip}`);
    // TS/jest молча резолвят звездный конфликт (не пустой): проверяем фактическую доступность.
    expect(hasStrip).toBe(true);
  });

  // ── P3: formatPrintTime — зона при ISO с offset ─────────────────
  test("P3 formatPrintTime: ISO +03:00 печатается с подписью UTC", () => {
    const out = formatPrintTime("2026-10-27T12:34:56+03:00", null, "UTC");
    // eslint-disable-next-line no-console
    console.log(`P3 RESULT: "${out}" :: ${out === "2026-10-27 12:34 UTC" ? "CONFIRMED (ложная зона)" : "REJECTED"}`);
    expect(out).toBe("2026-10-27 12:34 UTC");
  });

  // ── P3b: formatPrintTime с timezone снапшота ≠ UTC ──────────────
  test("P3b formatPrintTime: подпись зоны из снапшота без конверсии", () => {
    const out = formatPrintTime("2026-10-27T12:34:56+03:00", null, "Europe/Moscow");
    // eslint-disable-next-line no-console
    console.log(`P3b RESULT: "${out}"`);
    expect(out).toBe("2026-10-27 12:34 Europe/Moscow");
  });

  // ── P4: chunkTableRows NaN ──────────────────────────────────────
  test("P4 chunkTableRows: NaN как rowsPerPage", () => {
    const rows = [["a", "1"], ["b", "2"], ["c", "3"]];
    const chunks = chunkTableRows(rows, Number.NaN);
    // eslint-disable-next-line no-console
    console.log(`P4 RESULT: chunks=${JSON.stringify(chunks.map((c) => c.length))} :: ${chunks.length !== 3 ? "CONFIRMED (аномалия)" : "REJECTED (эквивалент full page)"}`);
    expect(chunks.length).toBeGreaterThanOrEqual(0);
  });

  // ── P5: heatColor вне домена (clamp) ────────────────────────────
  test("P5 heatColor: значения вне домена зажаты", () => {
    const below = heatColor(-10, [0, 100]);
    const above = heatColor(500, [0, 100]);
    // eslint-disable-next-line no-console
    console.log(`P5 RESULT: below="${below}" above="${above}"`);
    expect(below).toBe("rgb(255, 255, 255)");
    expect(above).toBe("rgb(37, 99, 235)");
  });

  // ── P6: PrintLegendStrip — свотчи при 3+ сериях (index % 2) ─────
  test("P6 PrintLegendStrip: 3 записи — записи 0 и 2 получают одинаковый свотч", () => {
    const { container } = render(<PrintLegendStrip ordering={["Серия 1", "Серия 2", "Серия 3"]} />);
    const swatches = Array.from(container.querySelectorAll("[aria-hidden=true]"));
    const colors = swatches.map((el) => (el as HTMLElement).style.backgroundColor);
    const unique = new Set(colors);
    // eslint-disable-next-line no-console
    console.log(`P6 RESULT: colors=${JSON.stringify(colors)} unique=${unique.size} :: ${unique.size < colors.length ? "CONFIRMED (коллизия свотчей)" : "REJECTED"}`);
    expect(colors.length).toBe(3);
    expect(unique.size).toBe(2); // 3 записи — 2 цвета
  });

  // ── P7: PrintPageFrame печатает «версия данных» из refs ─────────
  test("P7 PrintPageFrame: источник версии данных — refs.data_revision", () => {
    const snapshot = buildMinimalValidSnapshot(site("upload.distribution.scatter"));
    const { getByTestId } = render(
      <PrintPageFrame snapshot={snapshot} pageIndex={1} pageCount={1}>
        <p>тело</p>
      </PrintPageFrame>,
    );
    const footer = getByTestId("print-footer").textContent ?? "";
    const meta = getByTestId("print-meta").textContent ?? "";
    // eslint-disable-next-line no-console
    console.log(`P7 RESULT: footer-версия=${footer.includes("fixture:data_revision")} meta-revision=${meta.includes("data_revision")}`);
    expect(footer).toContain("fixture:data_revision");
  });

  // ── P8: shortRef кириллица и многоточие ─────────────────────────
  test("P8 shortRef: keep=10 на кириллическом ref", () => {
    const out = shortRef("снимок паспорта свойств ряда: validation");
    // eslint-disable-next-line no-console
    console.log(`P8 RESULT: "${out}"`);
    expect(out.startsWith("снимок пас")).toBe(true);
    expect(out.endsWith("…")).toBe(true);
  });

  // ── P9: неизвестная группа KNOWN_PASSPORT_GROUPS полнота ────────
  test("P9 KNOWN_PASSPORT_GROUPS: состав 12 групп", () => {
    // eslint-disable-next-line no-console
    console.log(`P9 RESULT: groups=${KNOWN_PASSPORT_GROUPS.map((g) => g.key).join(",")}`);
    expect(KNOWN_PASSPORT_GROUPS.length).toBe(12);
  });

  // ── P10: buildMinimalValidSnapshot compact/expanded sections ────
  test("P10 buildMinimalValidSnapshot: detailLevel меняет только display.detail_level", () => {
    const s = site("upload.distribution.scatter");
    const compact = buildMinimalValidSnapshot(s, { detailLevel: "compact" });
    const expanded = buildMinimalValidSnapshot(s, { detailLevel: "expanded" });
    const sectionsEqual = JSON.stringify(compact.display.sections) === JSON.stringify(expanded.display.sections);
    // eslint-disable-next-line no-console
    console.log(`P10 RESULT: sectionsEqual=${sectionsEqual}`);
    expect(sectionsEqual).toBe(true);
  });
});
