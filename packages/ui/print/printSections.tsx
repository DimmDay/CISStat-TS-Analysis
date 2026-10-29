// packages/ui/print/printSections.tsx
//
// PGV-07 — Shared pure print layout: секции печатной страницы по
// renderer_kind реестра PGV-00/схем PGV-01 (PrintSectionSpec):
//   recharts_svg — фиксированная поверхность + переданная научная
//                  геометрия экранного графика (переиспользование, §4.1:
//                  «screen и print переиспользуют научную геометрию без
//                  второй реализации»);
//   html_table   — полная таблица с повтором заголовков по частям
//                  (база пагинации PGV-AC15; оркестрация page-set — PGV-14);
//   html_heatmap — CSS-шкала с domain+units и color legend (§6);
//   html_cards   — карточки метрик с единицами.
//
// Чистота: без fetch/state/animation; стили — инлайн hex (printTheme,
// AC04). Hover-интерактив экрана в печать не переносится.

import React from "react";
import type { AxisSpec, PrintSectionSpec } from "./printSchema";
import {
  PRINT_PALETTE,
  PRINT_TYPE_SCALE,
} from "./printTheme";
import {
  formatUnit,
  PrintLegendStrip,
  PrintSectionTitle,
} from "./printLayout";

// ── Общие атомы ──────────────────────────────────────────────────

/** Строка оси: имя + единица (значение XOR причина, §6). */
export function describeAxis(axis: AxisSpec): string {
  const units = formatUnit(axis.units);
  return `${axis.name} (${units})`;
}

// ── recharts_svg: фиксированная поверхность + легенда ────────────

export interface PrintChartSectionProps {
  spec: PrintSectionSpec;
  /** Научная геометрия экранного графика (Recharts-элемент и т.п.). */
  children?: React.ReactNode;
  /** Высота поверхности рисунка (px при scale=1). */
  heightPx?: number;
}

/**
 * Печатная секция графика: заголовок, оси с единицами, ПОЛНАЯ легенда
 * (§7: «SamplingBadge/легенда не теряются при раскрытии») и переданная
 * геометрия на фиксированной поверхности.
 */
export function PrintChartSection({ spec, children, heightPx = 900 }: PrintChartSectionProps) {
  return (
    <section data-testid="print-chart-section" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {spec.title && <PrintSectionTitle>{spec.title}</PrintSectionTitle>}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "2px 18px",
          fontSize: PRINT_TYPE_SCALE.small,
          color: PRINT_PALETTE.ink_muted,
        }}
      >
        {spec.axes.map((axis) => (
          <span key={`${spec.section_id}-${axis.name}`}>{describeAxis(axis)}</span>
        ))}
      </div>
      <div
        style={{
          flex: "1 1 auto",
          minHeight: 0,
          height: `${heightPx}px`,
          border: `1px solid ${PRINT_PALETTE.border}`,
          backgroundColor: PRINT_PALETTE.page_background,
        }}
      >
        {children}
      </div>
      <PrintLegendStrip ordering={spec.legend_ordering} />
    </section>
  );
}

/** Полная легенда печати: все записи в заданном порядке (не теряется). */
export { PrintLegendStrip };

// ── html_table: целые строки + повтор заголовков ─────────────────

/**
 * Чанкование ТОЛЬКО целыми строками (§7: «не разрезать строки/оси/
 * legend»). rowsPerPage < 1 трактуется как 1 (защита от нулевой страницы);
 * пустой вход — пустой список частей.
 */
export function chunkTableRows<T>(rows: readonly T[], rowsPerPage: number): T[][] {
  if (rows.length === 0) return [];
  const size = Math.max(1, Math.floor(rowsPerPage));
  const chunks: T[][] = [];
  for (let start = 0; start < rows.length; start += size) {
    chunks.push(rows.slice(start, start + size));
  }
  return chunks;
}

export interface TableHeadings {
  row: string[];
  column: string[];
}

export interface PrintTableSectionProps {
  spec: PrintSectionSpec;
  headings: TableHeadings;
  /** Уже отформатированные строки: первая ячейка — заголовок строки. */
  rows: readonly (readonly string[])[];
  /** Строк на часть печатной страницы (база пагинации PGV-AC15/PGV-14). */
  rowsPerPage?: number;
  caption?: string | null;
}

/**
 * Печатная таблица: части по rowsPerPage целых строк, на КАЖДОЙ части
 * повторяется thead (§7: «повторять headers/footers»), продолжение
 * помечено явно.
 */
export function PrintTableSection({ spec, headings, rows, rowsPerPage, caption }: PrintTableSectionProps) {
  const chunks = chunkTableRows(rows, rowsPerPage ?? Number.MAX_SAFE_INTEGER);
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {spec.title && <PrintSectionTitle>{spec.title}</PrintSectionTitle>}
      {(caption || spec.units.length > 0) && (
        <p style={{ margin: 0, fontSize: PRINT_TYPE_SCALE.small, color: PRINT_PALETTE.ink_faint }}>
          {caption ?? ""}
          {spec.units.length > 0
            ? `${caption ? ". " : ""}Единицы: ${spec.units.map(formatUnit).join(", ")}`
            : ""}
        </p>
      )}
      {chunks.map((chunk, chunkIndex) => (
        <table
          key={`${spec.section_id}-page-${chunkIndex}`}
          data-testid="print-table"
          style={{
            borderCollapse: "collapse",
            width: "100%",
            fontSize: PRINT_TYPE_SCALE.body,
            color: PRINT_PALETTE.ink,
          }}
        >
          {chunkIndex > 0 && (
            <caption
              style={{
                captionSide: "top",
                textAlign: "left",
                fontSize: PRINT_TYPE_SCALE.small,
                color: PRINT_PALETTE.ink_faint,
                paddingBottom: 4,
              }}
            >
              Продолжение{spec.title ? `: ${spec.title}` : ""}
            </caption>
          )}
          <thead>
            <tr style={{ backgroundColor: PRINT_PALETTE.band_fill }}>
              {headings.row.map((heading) => (
                <th
                  key={`row-${heading}`}
                  style={{
                    border: `1px solid ${PRINT_PALETTE.border}`,
                    padding: "6px 8px",
                    textAlign: "left",
                    fontWeight: 600,
                  }}
                >
                  {heading}
                </th>
              ))}
              {headings.column.map((heading) => (
                <th
                  key={`col-${heading}`}
                  style={{
                    border: `1px solid ${PRINT_PALETTE.border}`,
                    padding: "6px 8px",
                    textAlign: "right",
                    fontWeight: 600,
                  }}
                >
                  {heading}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {chunk.map((cells, rowIndex) => (
              <tr key={`${spec.section_id}-${chunkIndex}-${rowIndex}`}>
                {cells.map((cell, cellIndex) => (
                  <td
                    key={`${spec.section_id}-${chunkIndex}-${rowIndex}-${cellIndex}`}
                    style={{
                      border: `1px solid ${PRINT_PALETTE.border}`,
                      padding: "5px 8px",
                      textAlign: cellIndex === 0 ? "left" : "right",
                      fontVariantNumeric: "tabular-nums",
                    }}
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      ))}
    </section>
  );
}

// ── html_heatmap: CSS-шкала + color legend ────────────────────────

/**
 * Цвет тепловой карты: линейная интерполяция белый → series_blue по
 * домену шкалы (clamped). Значение вне домена зажимается — шкала устойчива
 * (§7: «Цвета/штриховки/линии устойчивы»).
 */
export function heatColor(value: number, domain: [number, number]): string {
  const [min, max] = domain;
  const span = max - min;
  const t = span <= 0 ? 0 : Math.min(1, Math.max(0, (value - min) / span));
  const from = { r: 255, g: 255, b: 255 };
  const to = { r: 37, g: 99, b: 235 }; // PRINT_PALETTE.series_blue
  const r = Math.round(from.r + (to.r - from.r) * t);
  const g = Math.round(from.g + (to.g - from.g) * t);
  const b = Math.round(from.b + (to.b - from.b) * t);
  return `rgb(${r}, ${g}, ${b})`;
}

export interface PrintHeatmapSectionProps {
  spec: PrintSectionSpec;
  rowHeadings: readonly string[];
  columnHeadings: readonly string[];
  /** Значение ячейки для шкалы; null — честный пропуск (не ноль). */
  cellValue: (row: number, column: number) => number | null;
  /** Текст ячейки для непустого значения (уже отформатирован). */
  cellText: (row: number, column: number) => string;
  missingText?: string;
}

/**
 * Тепловая карта печати: заголовки строк/колонок, все ячейки, шкала с
 * domain+units и color legend (§6: heatmap_scale обязателен для
 * html_heatmap). Пропуск — явная метка, не нулевая заливка.
 */
export function PrintHeatmapSection({
  spec,
  rowHeadings,
  columnHeadings,
  cellValue,
  cellText,
  missingText = "нет данных",
}: PrintHeatmapSectionProps) {
  const scale = spec.heatmap_scale;
  const domain: [number, number] = scale?.domain ?? [0, 1];
  const cellStyle = (value: number | null): React.CSSProperties => ({
    border: `1px solid ${PRINT_PALETTE.border}`,
    padding: "5px 8px",
    textAlign: "right",
    fontVariantNumeric: "tabular-nums",
    backgroundColor:
      value === null ? PRINT_PALETTE.band_fill : heatColor(value, domain),
    color: value === null ? PRINT_PALETTE.ink_faint : PRINT_PALETTE.ink,
  });
  return (
    <section data-testid="print-heatmap-section" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {spec.title && <PrintSectionTitle>{spec.title}</PrintSectionTitle>}
      <table style={{ borderCollapse: "collapse", width: "100%", fontSize: PRINT_TYPE_SCALE.body }}>
        <thead>
          <tr style={{ backgroundColor: PRINT_PALETTE.band_fill }}>
            {rowHeadings.length > 0 && <th aria-label="строки" style={{ border: `1px solid ${PRINT_PALETTE.border}`, padding: "6px 8px" }} />}
            {columnHeadings.map((heading) => (
              <th
                key={heading}
                style={{
                  border: `1px solid ${PRINT_PALETTE.border}`,
                  padding: "6px 8px",
                  textAlign: "right",
                  fontWeight: 600,
                }}
              >
                {heading}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rowHeadings.map((rowHeading, rowIndex) => (
            <tr key={rowHeading}>
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
                {rowHeading}
              </th>
              {columnHeadings.map((_column, columnIndex) => {
                const value = cellValue(rowIndex, columnIndex);
                return (
                  <td key={`${rowHeading}-${columnIndex}`} data-testid="print-heatmap-cell" style={cellStyle(value)}>
                    {value === null ? missingText : cellText(rowIndex, columnIndex)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div
        data-testid="print-heatmap-scale"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          fontSize: PRINT_TYPE_SCALE.small,
          color: PRINT_PALETTE.ink_muted,
        }}
      >
        <span>шкала:</span>
        <span>{formatNumber(domain[0])}</span>
        <span
          aria-hidden="true"
          style={{
            width: 120,
            height: 10,
            background: `linear-gradient(to right, ${heatColor(domain[0], domain)}, ${heatColor(domain[1], domain)})`,
            border: `1px solid ${PRINT_PALETTE.border}`,
          }}
        />
        <span>{formatNumber(domain[1])}</span>
        <span>{scale ? formatUnit(scale.units) : ""}</span>
      </div>
    </section>
  );
}

function formatNumber(value: number): string {
  return Number.isInteger(value) ? String(value) : String(Math.round(value * 100) / 100);
}

// ── html_cards: карточки метрик ──────────────────────────────────

export interface PrintCard {
  label: string;
  /** Уже отформатированное значение (форматтеры printLayout). */
  value: string;
  unit?: { value: string | null; reason: string | null };
}

export interface PrintCardsSectionProps {
  spec: PrintSectionSpec;
  cards: readonly PrintCard[];
}

/** Карточки метрик печати: подпись + значение + единица (XOR-честность). */
export function PrintCardsSection({ spec, cards }: PrintCardsSectionProps) {
  return (
    <section data-testid="print-cards-section" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {spec.title && <PrintSectionTitle>{spec.title}</PrintSectionTitle>}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {cards.map((card) => (
          <div
            key={card.label}
            style={{
              border: `1px solid ${PRINT_PALETTE.border}`,
              padding: "6px 10px",
              minWidth: 120,
            }}
          >
            <div style={{ fontSize: PRINT_TYPE_SCALE.small, color: PRINT_PALETTE.ink_faint }}>{card.label}</div>
            <div style={{ fontSize: PRINT_TYPE_SCALE.section, fontWeight: 600, color: PRINT_PALETTE.ink }}>
              {card.value}
              {card.unit ? <span style={{ fontWeight: 400, fontSize: PRINT_TYPE_SCALE.small }}> {formatUnit(card.unit)}</span> : null}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
