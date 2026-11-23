// packages/ui/print/printTheme.test.ts
//
// PGV13-VIS-01 — физическая типографика печати (задача VIS-01 независимого
// ревью, спека §7 «Нельзя уменьшать до нечитаемого шрифта»).
//
// Оракулы:
//   1) Перевод единиц честен: ptToPx/mmToPx при 300 ppi дают точные
//      производные (1 pt = ppi/72 px; 1 мм = ppi/25.4 px).
//   2) Целевая шкала задачи: основной текст 9–10 pt, служебный ~8 pt;
//      px-шкала — точное производное pt-шкалы (без расхождений).
//   3) Иерархия заголовков сохраняется; P02-заголовки документов больше
//      не захардкожены вне шкалы (printComparison DOCUMENT_HEADING_STYLE
//      построен на PRINT_TYPE_SCALE.section).
//   4) PRINT_PROFILE_PPI паритетен каталогу профилей PGV-01.
//   5) Отступы в мм: поля страницы ≥ 10 мм физики, производные px
//      согласованы с PRINT_SPACING_MM.

import {
  mmToPx,
  PRINT_PROFILE_PPI,
  PRINT_SPACING_MM,
  PRINT_SPACING_PX,
  PRINT_TYPE_SCALE,
  PRINT_TYPE_SCALE_PT,
  ptToPx,
} from "./printTheme";
import { PRINT_PROFILE_CATALOG } from "./printSchema";

describe("PGV13-VIS-01: перевод физических единиц печати", () => {
  test("ptToPx: 1 pt при 300 ppi = 300/72 px (точный перевод)", () => {
    expect(ptToPx(1, 300)).toBeCloseTo(300 / 72, 10);
    expect(ptToPx(9.5, 300)).toBeCloseTo(39.583333333333336, 10);
    expect(ptToPx(16, 300)).toBeCloseTo(66.66666666666667, 10);
    // Перевод параметричен по ppi (физика, не константа интерфейса).
    expect(ptToPx(12, 96)).toBeCloseTo(16, 10);
  });

  test("mmToPx: 1 мм при 300 ppi = 300/25.4 px (точный перевод)", () => {
    expect(mmToPx(1, 300)).toBeCloseTo(300 / 25.4, 10);
    expect(mmToPx(12, 300)).toBeCloseTo(141.73228346456693, 10);
    expect(mmToPx(210, 300)).toBeCloseTo(2480.3149606299213, 10);
  });

  test("PRINT_PROFILE_PPI паритетен каталогу профилей PGV-01 (все 300 ppi)", () => {
    expect(PRINT_PROFILE_PPI).toBe(300);
    for (const profile of PRINT_PROFILE_CATALOG) {
      expect(profile.ppi).toBe(PRINT_PROFILE_PPI);
    }
  });
});

describe("PGV13-VIS-01: целевая шкала типа (основной 9–10 pt, служебный ~8 pt)", () => {
  test("основной текст body в целевом коридоре 9–10 pt", () => {
    expect(PRINT_TYPE_SCALE_PT.body).toBeGreaterThanOrEqual(9);
    expect(PRINT_TYPE_SCALE_PT.body).toBeLessThanOrEqual(10);
  });

  test("служебный текст (small/micro) около 8 pt, не ниже 8 pt", () => {
    expect(PRINT_TYPE_SCALE_PT.small).toBeGreaterThanOrEqual(8);
    expect(PRINT_TYPE_SCALE_PT.small).toBeLessThanOrEqual(9);
    expect(PRINT_TYPE_SCALE_PT.micro).toBeGreaterThanOrEqual(8);
    expect(PRINT_TYPE_SCALE_PT.micro).toBeLessThanOrEqual(9);
  });

  test("иерархия заголовков: title > subtitle > section > body > small > micro", () => {
    const scale = PRINT_TYPE_SCALE_PT;
    expect(scale.title).toBeGreaterThan(scale.subtitle);
    expect(scale.subtitle).toBeGreaterThan(scale.section);
    expect(scale.section).toBeGreaterThan(scale.body);
    expect(scale.body).toBeGreaterThan(scale.small);
    expect(scale.small).toBeGreaterThanOrEqual(scale.micro);
  });

  test("px-шкала — точное производное pt-шкалы при ppi каталога (без расхождений)", () => {
    for (const key of Object.keys(PRINT_TYPE_SCALE_PT) as Array<keyof typeof PRINT_TYPE_SCALE_PT>) {
      const expectedPx = ptToPx(PRINT_TYPE_SCALE_PT[key], PRINT_PROFILE_PPI);
      expect(PRINT_TYPE_SCALE[key]).toBeCloseTo(expectedPx, 2);
      // Физический смысл px-значения: обратный перевод даёт целевой pt.
      expect((PRINT_TYPE_SCALE[key] * 72) / PRINT_PROFILE_PPI).toBeCloseTo(PRINT_TYPE_SCALE_PT[key], 2);
    }
  });

  test("физическая читаемость @300ppi: тело ≥ 9 pt (37.5 px), служебная ≥ 8 pt (33.33 px)", () => {
    expect(PRINT_TYPE_SCALE.body).toBeGreaterThanOrEqual(9 * (300 / 72));
    expect(PRINT_TYPE_SCALE.small).toBeGreaterThanOrEqual(8 * (300 / 72));
    expect(PRINT_TYPE_SCALE.micro).toBeGreaterThanOrEqual(8 * (300 / 72));
    expect(PRINT_TYPE_SCALE.title).toBeGreaterThan(PRINT_TYPE_SCALE.section);
  });
});

describe("PGV13-VIS-01: отступы в мм (физические поля страницы)", () => {
  test("поля страницы ≥ 10 мм (print margin), колонтитулы и ячейки согласованы", () => {
    expect(PRINT_SPACING_MM.page_margin).toBeGreaterThanOrEqual(10);
    expect(PRINT_SPACING_PX.page_margin).toBeCloseTo(mmToPx(PRINT_SPACING_MM.page_margin, PRINT_PROFILE_PPI), 2);
    expect(PRINT_SPACING_PX.band_pad).toBeCloseTo(mmToPx(PRINT_SPACING_MM.band_pad, PRINT_PROFILE_PPI), 2);
    expect(PRINT_SPACING_PX.cell_pad).toBeCloseTo(mmToPx(PRINT_SPACING_MM.cell_pad, PRINT_PROFILE_PPI), 2);
    expect(PRINT_SPACING_PX.cell_pad_y).toBeCloseTo(mmToPx(PRINT_SPACING_MM.cell_pad_y, PRINT_PROFILE_PPI), 2);
  });

  test("все ключи mm-шкалы имеют px-производные (без «сырых» px в каркасе)", () => {
    for (const key of Object.keys(PRINT_SPACING_MM) as Array<keyof typeof PRINT_SPACING_MM>) {
      expect(PRINT_SPACING_PX[key]).toBeDefined();
      expect(PRINT_SPACING_PX[key]).toBeCloseTo(mmToPx(PRINT_SPACING_MM[key], PRINT_PROFILE_PPI), 2);
    }
  });
});
