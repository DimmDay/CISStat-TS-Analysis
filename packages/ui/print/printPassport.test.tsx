// packages/ui/print/printPassport.test.tsx
//
// PGV-07 — Shared pure print layout: печатные паспорта и сравнения
// (spec_passport_graphics_visual.md §8 «Durable паспорта и точная история»,
// §9 «Сравнение паспортов», §13 строка PGV-07 «полные паспорта»).
//
// Оракулы:
//   1) Печатный паспорт выводит ВСЕ группы существующей схемы (не
//      сокращается до rows/columns/claim counts), включая неизвестные
//      print'у группы — по ключу, не молча (§8).
//   2) Честность §8/AC12: отсутствие факта — причина (legacy_unknown/
//      integrity_failure), не выдуманное значение; content-гэп — баннер,
//      не пустая «готовая» картинка; unsupported schema — unsupported_schema.
//   3) Провенанс: stage/snapshot/captured_at/context/data_revision/
//      fingerprint/source_hash/schema/calculation version.
//   4) Сравнение §9/AC13: значения по этапам, absolute/relative с
//      определением и zero-denominator reason; отдельная строка
//      подтверждения reused checkpoint (AC11, без нулевой дублирующей
//      колонки); gaps честны (missing validation — gap, не ноль);
//      цвет delta не означает значимость (определения печатаются);
//      cross_context маркируется.

import React from "react";
import { render } from "@testing-library/react";

import {
  KNOWN_PASSPORT_GROUPS,
  PrintPassportPage,
  type PrintPassportRecord,
} from "./printPassport";
import {
  PrintPassportComparisonPage,
  PASSPORT_COMPARISON_SCHEMA_VERSION,
  type PrintComparisonSnapshot,
} from "./printComparison";

// ── Фикстуры (данные-оракулы, не научные расчёты) ────────────────

function fullRecord(overrides: Partial<PrintPassportRecord> = {}): PrintPassportRecord {
  return {
    schema_version: "pgv.passport_history/1",
    snapshot_ref: "artifact:passport:snap-123",
    session_snapshot_id: "snap-123",
    artifact_id: "artifact:passport:snap-123",
    stage: "validation",
    universe: "single",
    content_status: "present",
    content_gap_reason: null,
    passport: {
      basic_stats: { n: 512, mean: 42.5, std: 3.25, min: 30.1, max: 58.9 },
      freq: { value: "D" },
      stationarity: { value: 0.031, is_stationary: true },
      determinism: { value: 0.72 },
      autocorrelation: { value: 0.11 },
      normality: { value: 0.44 },
      trend: { direction: "up", slope: 0.12 },
      seasonality: { strength: 0.35, period: 7 },
      hurst: { value: 0.61 },
      correlations: { top3: { lag_1: 0.4, lag_2: 0.2 } },
      fft: { dominant_periods: [7, 30] },
      wavelet: { applicable: false, reason: "не применимо: короткий ряд" },
      self_test_unknown_group: { custom_metric: 5 },
    },
    target_column: "sales",
    date_column: "dt",
    context_id: "ctx-777",
    data_revision: "rev-9",
    captured_at: "2026-10-28T10:00:00Z",
    created_at: "2026-10-28T10:00:05Z",
    fingerprint: "f".repeat(64),
    fingerprint_reason: null,
    source_hash: "a".repeat(64),
    source_hash_reason: null,
    passport_schema_version: "passport/1.1",
    passport_schema_version_reason: null,
    calculation_version: "calc-v2",
    calculation_version_reason: null,
    ...overrides,
  };
}

// ── 1. Полный паспорт (§8) ───────────────────────────────────────

describe("PGV-07 PrintPassportPage: полный паспорт без сокращений (§8)", () => {
  test("все известные группы печатаются со значениями", () => {
    const { getByTestId } = render(<PrintPassportPage record={fullRecord()} pageIndex={1} pageCount={1} />);
    const page = getByTestId("print-passport-page");
    for (const group of KNOWN_PASSPORT_GROUPS) {
      expect(page.textContent).toContain(group.label);
    }
    expect(page.textContent).toContain("42,5");
    expect(page.textContent).toContain("стационарен");
    expect(page.textContent).toContain("восходящий");
    expect(page.textContent).toContain("не применимо: короткий ряд");
  });

  test("неизвестная print'у группа не выбрасывается — печатается по ключу", () => {
    const { getByTestId } = render(<PrintPassportPage record={fullRecord()} pageIndex={1} pageCount={1} />);
    const page = getByTestId("print-passport-page");
    expect(page.textContent).toContain("self_test_unknown_group");
    expect(page.textContent).toContain("custom_metric");
  });

  test("провенанс: этап, снимок, capture, context/data_revision, схема и версия расчёта", () => {
    const { getByTestId } = render(<PrintPassportPage record={fullRecord()} pageIndex={1} pageCount={1} />);
    const page = getByTestId("print-passport-page");
    expect(page.textContent).toContain("validation");
    expect(page.textContent).toContain("snap-123");
    expect(page.textContent).toContain("2026-10-28 10:00");
    expect(page.textContent).toContain("ctx-777");
    expect(page.textContent).toContain("rev-9");
    expect(page.textContent).toContain("passport/1.1");
    expect(page.textContent).toContain("calc-v2");
    expect(page.textContent).toContain("sales");
  });

  test("XOR-честность: отсутствующий fingerprint — причина legacy_unknown, не выдуманный хэш (AC12)", () => {
    const { getByTestId } = render(
      <PrintPassportPage
        record={fullRecord({
          fingerprint: null,
          fingerprint_reason: "legacy_unknown",
          passport_schema_version: null,
          passport_schema_version_reason: "legacy_unknown",
        })}
        pageIndex={1}
        pageCount={1}
      />,
    );
    const page = getByTestId("print-passport-page");
    expect(page.textContent).toContain("legacy_unknown");
    expect(page.textContent).not.toContain("ffffffff");
    expect(page.textContent).not.toContain("passport/1.1");
  });

  test("неизвестная схема паспорта — баннер unsupported_schema, не пустая картинка (§8)", () => {
    const { getByTestId } = render(
      <PrintPassportPage record={fullRecord({ passport_schema_version: "passport/9.9" })} pageIndex={1} pageCount={1} />,
    );
    expect(getByTestId("print-passport-unsupported-schema").textContent).toContain("passport/9.9");
  });

  test("content-гэп — честный баннер без паспортных таблиц (фабкация запрещена)", () => {
    const { getByTestId, queryByTestId } = render(
      <PrintPassportPage
        record={fullRecord({
          content_status: "missing_artifact",
          content_gap_reason: "passport_artifact_absent",
          passport: null,
        })}
        pageIndex={1}
        pageCount={1}
      />,
    );
    const gap = getByTestId("print-passport-content-gap");
    expect(gap.textContent).toContain("passport_artifact_absent");
    expect(queryByTestId("print-passport-groups")).toBeNull();
  });

  test("corrupt-контент — баннер integrity-проблемы с причиной", () => {
    const { getByTestId } = render(
      <PrintPassportPage
        record={fullRecord({ content_status: "corrupt", content_gap_reason: "snapshot_id_mismatch", passport: null })}
        pageIndex={1}
        pageCount={1}
      />,
    );
    expect(getByTestId("print-passport-content-gap").textContent).toContain("snapshot_id_mismatch");
  });

  test("номер страницы в подвале печатной страницы", () => {
    const { getByTestId } = render(<PrintPassportPage record={fullRecord()} pageIndex={2} pageCount={3} />);
    expect(getByTestId("print-passport-page").textContent).toContain("Стр. 2 из 3");
  });
});

// ── 2. Сравнение паспортов (§9/AC13) ─────────────────────────────

function comparisonSnapshot(overrides: Partial<PrintComparisonSnapshot> = {}): PrintComparisonSnapshot {
  const metric = { v_old: 100, v_new: 150, delta: 50, delta_pct: 50 };
  const zeroMetric = { v_old: 0, v_new: 12, delta: 12, delta_pct: 100 };
  return {
    schema_version: PASSPORT_COMPARISON_SCHEMA_VERSION,
    mode: "trajectory_checkpoint",
    run_id: "run-1",
    ordered_refs: ["artifact:passport:s1", "artifact:passport:s2"],
    path: ["start", "validation"],
    comparisons: [
      {
        from_stage: "start",
        to_stage: "validation",
        from_snapshot_id: "s1",
        to_snapshot_id: "s2",
        comparison: {
          metrics: { "Число наблюдений": metric, "Среднее": zeroMetric },
          qualitative_changes: ["ряд стал короче"],
          categorical_changes: { "freq.value": { v_old: "D", v_new: "W", changed: true } },
          list_changes: { "fft.dominant_periods": { added: [30], removed: [14], changed: true } },
          boolean_changes: { "stationarity.is_stationary": { v_old: true, v_new: false, changed: true } },
          summary: "изменилось 4 свойства",
        },
        cross_context: false,
      },
    ],
    confirmation: null,
    checkpoint: null,
    context: { context_id: "ctx-1", data_revision: "rev-2" },
    cross_context: false,
    aliases: [],
    method_versions: { engine: { id: "app.core.passport._compare_ts_props", version: "v1.0" }, records: [] },
    definitions: {
      absolute: "delta = v_new - v_old",
      relative: "delta_pct = (delta / abs(v_old)) * 100",
      zero_denominator_reason: "при |v_old| <= 1e-10 относительное изменение не определено",
      delta_color: "цвет delta не означает статистическую значимость",
    },
    gaps: [],
    completeness: "complete",
    ...overrides,
  };
}

describe("PGV-07 PrintPassportComparisonPage: сравнение (§9/AC13)", () => {
  test("этапы-колонки, значения, absolute/relative дельты", () => {
    const { getByTestId } = render(<PrintPassportComparisonPage snapshot={comparisonSnapshot()} />);
    const page = getByTestId("print-comparison-page");
    expect(page.textContent).toContain("Число наблюдений");
    expect(page.textContent).toContain("100");
    expect(page.textContent).toContain("150");
    expect(page.textContent).toContain("+50");
    expect(page.textContent).toContain("+50 %");
    expect(page.textContent).toContain("validation");
  });

  test("определения с zero-denominator reason печатаются (цвет delta не значимость)", () => {
    const { getByTestId } = render(<PrintPassportComparisonPage snapshot={comparisonSnapshot()} />);
    const defs = getByTestId("print-comparison-definitions");
    expect(defs.textContent).toContain("не определено");
    expect(defs.textContent).toContain("не означает статистическую значимость");
    expect(defs.textContent).toContain("delta = v_new - v_old");
  });

  test("категории/списки/булевы/качественные изменения печатаются (AC13)", () => {
    const { getByTestId } = render(<PrintPassportComparisonPage snapshot={comparisonSnapshot()} />);
    const page = getByTestId("print-comparison-page");
    expect(page.textContent).toContain("ряд стал короче");
    expect(page.textContent).toContain("D → W");
    expect(page.textContent).toContain("Добавлено");
    expect(page.textContent).toContain("Да → Нет");
  });

  test("reused checkpoint: строка подтверждения с confirmed_at и reused ref (AC11)", () => {
    const { getByTestId } = render(
      <PrintPassportComparisonPage
        snapshot={comparisonSnapshot({
          confirmation: {
            checkpoint_ref: "artifact:passport_checkpoint:ck1",
            confirmed_at: "2026-10-28T12:00:00Z",
            confirmed_at_reason: null,
            reused: true,
            unchanged: true,
            reused_ref: "artifact:passport:s2",
            previous_ref: null,
          },
          checkpoint: {
            checkpoint_ref: "artifact:passport_checkpoint:ck1",
            checkpoint_artifact_id: "artifact:passport_checkpoint:ck1",
            stage: "modeling_entry",
            universe: "single",
            confirmed_at: "2026-10-28T12:00:00Z",
            confirmed_at_reason: null,
            flags: { reused: true },
            provenance: null,
          },
        })}
      />,
    );
    const confirmation = getByTestId("print-comparison-confirmation");
    expect(confirmation.textContent).toContain("2026-10-28 12:00");
    expect(confirmation.textContent).toContain("artifact:passport:s2");
    expect(confirmation.textContent).toContain("без повторного расчёта");
  });

  test("gaps честны: отсутствующая validation — gap, не ноль (AC13/§9)", () => {
    const { getByTestId } = render(
      <PrintPassportComparisonPage
        snapshot={comparisonSnapshot({
          completeness: "partial",
          gaps: [
            {
              at: "path.validation",
              snapshot_ref: "artifact:passport:s2",
              reason: "missing_snapshot_record",
              detail: "rs-запись отсутствует в реестре",
            },
          ],
        })}
      />,
    );
    const gaps = getByTestId("print-comparison-gaps");
    expect(gaps.textContent).toContain("path.validation");
    expect(gaps.textContent).toContain("missing_snapshot_record");
    expect(gaps.textContent).toContain("partial");
  });

  test("cross_context маркируется в явном режиме", () => {
    const { getByTestId } = render(
      <PrintPassportComparisonPage snapshot={comparisonSnapshot({ cross_context: true })} />,
    );
    expect(getByTestId("print-comparison-page").textContent).toContain("cross_context");
  });
});
