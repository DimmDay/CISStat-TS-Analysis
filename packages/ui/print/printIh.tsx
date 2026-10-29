// packages/ui/print/printIh.tsx
//
// PGV-07 — Shared pure print layout: печать HTML IH-анализа
// (spec_passport_graphics_visual.md §5 «EDA … IH, HTML-карты»;
// приёмочный PGV-AC02: «IH HTML matrix полностью печатается с bins/
// процентами/знаменателем/color legend»).
//
// Вход — frozen данные уже вычисленного IH-результата (зеркало
// EdaIhResponse-полей условной карты/метрик; перенесено producer-адаптером
// PGV-03 в VisualResult, НЕ пересчитывается). Знаменатели, которых нет
// в frozen результате, печатаются как честная причина, а не выдуманное
// число (§6: «counts/denominators», неполнота не подменяется нулями).
//
// Чистота: без fetch/state/animation; инлайн-стили printTheme (AC04).

import React from "react";
import {
  formatNumberRu,
  PrintSectionTitle,
} from "./printLayout";
import { heatColor } from "./printSections";
import { PRINT_PALETTE, PRINT_TYPE_SCALE } from "./printTheme";

const IH_SCALE_DOMAIN: [number, number] = [0, 100];

// ── Условная карта (AC02) ────────────────────────────────────────

export interface PrintIhConditionalRow {
  x_bin: string;
  /** Проценты строки (0..100), по ячейке на y_bin. */
  values: number[];
}

export interface PrintIhConditionalInput {
  /** Фактор (conditional_feature). */
  feature_label: string;
  /** Исследуемый признак (column). */
  target_label: string;
  /** Интервалы фактора — строки (conditional_x_bins). */
  x_bins: readonly string[];
  /** Интервалы цели — колонки (conditional_y_bins). */
  y_bins: readonly string[];
  rows: readonly PrintIhConditionalRow[];
  /** Общий знаменатель: число наблюдений IH-анализа. */
  n_observations: number;
  /**
   * Знаменатель каждой строки (n по интервалу фактора), если сохранился
   * в frozen результате; null — честная причина ниже, не выдуманные числа.
   */
  row_totals?: readonly (number | null)[] | null;
  /** Причина отсутствия построчных знаменателей (§6). */
  denominator_note?: string | null;
}

function percentText(value: number): string {
  return `${formatNumberRu(value, 1)} %`;
}

/**
 * Условное распределение цели по интервалам фактора: ВСЕ bins строк и
 * колонок, проценты ячеек, знаменатель строки, правило «строка суммируется
 * до 100 %» и color legend шкалы 0–100 % (PGV-AC02).
 */
export function PrintIhConditionalMatrix({ input }: { input: PrintIhConditionalInput }) {
  const hasRowTotals = Array.isArray(input.row_totals) && input.row_totals.length > 0;
  const denominatorNote =
    input.denominator_note ??
    (hasRowTotals ? null : "знаменатель строки не сохранён в frozen результате");
  return (
    <section data-testid="print-ih-conditional" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <PrintSectionTitle>
        Условное распределение «{input.target_label}» по интервалам «{input.feature_label}»
      </PrintSectionTitle>
      <p style={{ margin: 0, fontSize: PRINT_TYPE_SCALE.small, color: PRINT_PALETTE.ink_faint }}>
        Строки — интервалы «{input.feature_label}», столбцы — интервалы «{input.target_label}»; каждая строка
        суммируется до 100 %. Наблюдений: {formatNumberRu(input.n_observations, 0)}.
      </p>
      <table style={{ borderCollapse: "collapse", width: "100%", fontSize: PRINT_TYPE_SCALE.body }}>
        <thead>
          <tr style={{ backgroundColor: PRINT_PALETTE.band_fill }}>
            <th
              scope="col"
              style={{
                border: `1px solid ${PRINT_PALETTE.border}`,
                padding: "6px 8px",
                textAlign: "left",
                fontWeight: 600,
              }}
            >
              {input.feature_label} \ {input.target_label}
            </th>
            {input.y_bins.map((bin) => (
              <th
                key={bin}
                scope="col"
                style={{
                  border: `1px solid ${PRINT_PALETTE.border}`,
                  padding: "6px 8px",
                  textAlign: "right",
                  fontWeight: 600,
                }}
              >
                {bin}
              </th>
            ))}
            <th
              scope="col"
              style={{
                border: `1px solid ${PRINT_PALETTE.border}`,
                padding: "6px 8px",
                textAlign: "right",
                fontWeight: 600,
              }}
            >
              Знаменатель строки (n)
            </th>
          </tr>
        </thead>
        <tbody>
          {input.rows.map((row, rowIndex) => (
            <tr key={row.x_bin}>
              <th
                scope="row"
                style={{
                  border: `1px solid ${PRINT_PALETTE.border}`,
                  padding: "5px 8px",
                  textAlign: "left",
                  fontWeight: 600,
                  backgroundColor: PRINT_PALETTE.band_fill,
                }}
              >
                {row.x_bin}
              </th>
              {row.values.map((value, columnIndex) => (
                <td
                  key={`${row.x_bin}-${input.y_bins[columnIndex]}`}
                  data-testid="print-ih-cell"
                  style={{
                    border: `1px solid ${PRINT_PALETTE.border}`,
                    padding: "5px 8px",
                    textAlign: "right",
                    fontVariantNumeric: "tabular-nums",
                    backgroundColor: heatColor(value, IH_SCALE_DOMAIN),
                  }}
                >
                  {percentText(value)}
                </td>
              ))}
              <td
                style={{
                  border: `1px solid ${PRINT_PALETTE.border}`,
                  padding: "5px 8px",
                  textAlign: "right",
                  fontVariantNumeric: "tabular-nums",
                  color: hasRowTotals ? PRINT_PALETTE.ink : PRINT_PALETTE.ink_faint,
                }}
              >
                {hasRowTotals
                  ? formatNumberRu(input.row_totals?.[rowIndex] ?? null, 0)
                  : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {denominatorNote && (
        <p style={{ margin: 0, fontSize: PRINT_TYPE_SCALE.small, color: PRINT_PALETTE.ink_faint }}>
          Знаменатель: {denominatorNote}.
        </p>
      )}
      <div
        data-testid="print-ih-scale"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          fontSize: PRINT_TYPE_SCALE.small,
          color: PRINT_PALETTE.ink_muted,
        }}
      >
        <span>шкала:</span>
        <span>0 %</span>
        <span
          aria-hidden="true"
          style={{
            width: 120,
            height: 10,
            background: `linear-gradient(to right, ${heatColor(0, IH_SCALE_DOMAIN)}, ${heatColor(100, IH_SCALE_DOMAIN)})`,
            border: `1px solid ${PRINT_PALETTE.border}`,
          }}
        />
        <span>100 %</span>
        <span>доля строки, % (dimensionless)</span>
      </div>
    </section>
  );
}

// ── Карта энтропийных метрик ─────────────────────────────────────

export interface PrintIhMetricsRow {
  feature: string;
  h_x: number;
  mi: number;
  r: number;
  r_adjusted: number;
}

/**
 * Карта метрик IH: H(X), I(X;Y), R(Y|X), R-скорректированный — те же
 * колонки, что и экранная карта, в светлой печати.
 */
export function PrintIhMetricsMap({ results }: { results: readonly PrintIhMetricsRow[] }) {
  return (
    <section data-testid="print-ih-metrics" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <PrintSectionTitle>Карта энтропийных метрик</PrintSectionTitle>
      <table style={{ borderCollapse: "collapse", width: "100%", fontSize: PRINT_TYPE_SCALE.body }}>
        <thead>
          <tr style={{ backgroundColor: PRINT_PALETTE.band_fill }}>
            {["Фактор", "H(X)", "I(X;Y)", "R(Y|X)", "R adj."].map((heading, index) => (
              <th
                key={heading}
                scope="col"
                style={{
                  border: `1px solid ${PRINT_PALETTE.border}`,
                  padding: "6px 8px",
                  textAlign: index === 0 ? "left" : "right",
                  fontWeight: 600,
                }}
              >
                {heading}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {results.map((row) => (
            <tr key={row.feature}>
              <td style={{ border: `1px solid ${PRINT_PALETTE.border}`, padding: "5px 8px", fontWeight: 600 }}>
                {row.feature}
              </td>
              {[row.h_x, row.mi, row.r, row.r_adjusted].map((value, index) => (
                <td
                  key={`${row.feature}-v${index}`}
                  style={{
                    border: `1px solid ${PRINT_PALETTE.border}`,
                    padding: "5px 8px",
                    textAlign: "right",
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {formatNumberRu(value, 4)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
