// packages/ui/print/printComparison.tsx
//
// PGV-07 — Shared pure print layout: печатная страница сравнения
// паспортов (spec_passport_graphics_visual.md §9: «Печатаются значения
// по этапам, absolute/relative changes с определением и zero-denominator
// reason, categories/lists/qualitative explanations. Цвет delta не
// означает статистическую значимость. … source refs и номера страниц»).
//
// Вход — frozen сравнение (зеркало вывода durable-резолвера PGV-06
// passport_comparison.py, schema pgv.passport_comparison/1). Компонент
// не пересчитывает сравнение и не дублирует формулы: печатает значения
// как зафиксированы. Reused checkpoint печатается ОТДЕЛЬНОЙ строкой
// подтверждения (AC11: без нулевой дублирующей колонки этапа) — path
// уже не содержит дубликата (семантика резолвера PGV-06).
//
// Чистота: без fetch/state/animation; инлайн-стили printTheme (AC04).

import React from "react";
import { formatNumberRu, formatPrintTime, shortRef } from "./printLayout";
import { PRINT_PALETTE, PRINT_TYPE_SCALE } from "./printTheme";

/** Версия frozen-контракта сравнения (паритет PGV-06). */
export const PASSPORT_COMPARISON_SCHEMA_VERSION = "pgv.passport_comparison/1";

export interface PrintComparisonMetricChange {
  v_old: number;
  v_new: number;
  delta: number;
  delta_pct: number;
}

export interface PrintComparisonNamedChange {
  v_old?: unknown;
  v_new?: unknown;
  changed?: boolean;
  added?: unknown[];
  removed?: unknown[];
}

export interface PrintComparisonPair {
  from_stage: string;
  to_stage: string;
  from_snapshot_id?: string | null;
  to_snapshot_id?: string | null;
  comparison: {
    metrics: Record<string, PrintComparisonMetricChange>;
    qualitative_changes: string[];
    categorical_changes: Record<string, PrintComparisonNamedChange>;
    list_changes: Record<string, PrintComparisonNamedChange>;
    boolean_changes: Record<string, PrintComparisonNamedChange>;
    summary: string;
  };
  cross_context?: boolean;
}

export interface PrintComparisonConfirmation {
  checkpoint_ref: string | null;
  confirmed_at: string | null;
  confirmed_at_reason: string | null;
  reused: boolean;
  unchanged: boolean;
  reused_ref: string | null;
  previous_ref: string | null;
}

export interface PrintComparisonCheckpointMeta {
  checkpoint_ref: string | null;
  checkpoint_artifact_id: string | null;
  stage: string | null;
  universe: string | null;
  confirmed_at: string | null;
  confirmed_at_reason: string | null;
  flags: Record<string, unknown> | null;
  provenance: Record<string, unknown> | null;
}

export interface PrintComparisonGap {
  at: string;
  snapshot_ref?: string | null;
  reason: string;
  detail: string;
}

export interface PrintComparisonContext {
  context_id?: string | null;
  data_revision?: string | null;
}

/**
 * Frozen сравнение паспортов (зеркало вывода PGV-06; поля без
 * печатного смысла — aliases/provenance — печатаются только счётчиком,
 * полный payload остаётся в metadata).
 */
export interface PrintComparisonSnapshot {
  schema_version: string;
  mode: string;
  run_id: string;
  ordered_refs: readonly (string | null)[];
  path: readonly string[];
  comparisons: readonly PrintComparisonPair[];
  confirmation: PrintComparisonConfirmation | null;
  checkpoint: PrintComparisonCheckpointMeta | null;
  context: PrintComparisonContext | null;
  cross_context: boolean;
  aliases: readonly unknown[];
  method_versions: { engine: { id: string; version: string }; records: readonly unknown[] };
  definitions: Readonly<Record<string, string>>;
  gaps: readonly PrintComparisonGap[];
  completeness: "complete" | "partial";
}

// ── Атомы ────────────────────────────────────────────────────────

function signedNumber(value: number, digits = 1): string {
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${formatNumberRu(Math.abs(value), digits)}`;
}

function Badge({ tone, children }: { tone: "neutral" | "warning"; children: React.ReactNode }) {
  return (
    <span
      style={{
        display: "inline-block",
        border: `1px solid ${tone === "warning" ? PRINT_PALETTE.status_warning : PRINT_PALETTE.border}`,
        color: tone === "warning" ? PRINT_PALETTE.status_warning : PRINT_PALETTE.ink_muted,
        borderRadius: 3,
        padding: "1px 6px",
        fontSize: PRINT_TYPE_SCALE.small,
      }}
    >
      {children}
    </span>
  );
}

function ProvLine({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", gap: 6, alignItems: "baseline" }}>
      <span style={{ fontSize: PRINT_TYPE_SCALE.small, color: PRINT_PALETTE.ink_faint, whiteSpace: "nowrap" }}>
        {label}:
      </span>
      <span style={{ fontSize: PRINT_TYPE_SCALE.small, color: PRINT_PALETTE.ink_muted, fontFamily: "monospace" }}>
        {value}
      </span>
    </div>
  );
}

// ── Страница сравнения ───────────────────────────────────────────

export interface PrintPassportComparisonPageProps {
  snapshot: PrintComparisonSnapshot;
  pageIndex?: number;
  pageCount?: number;
}

/**
 * Печатное сравнение паспортов: значения по этапам + absolute/relative
 * дельты, категории/списки/булевы/качественные изменения, определения
 * метрик (zero-denominator reason, «цвет delta не значимость»), строка
 * подтверждения reused checkpoint, честные gaps, маркировка cross_context
 * и полноты (§9/AC11/AC13).
 */
export function PrintPassportComparisonPage({ snapshot, pageIndex = 1, pageCount = 1 }: PrintPassportComparisonPageProps) {
  // Значения по этапам: v_old → from_stage, v_new → to_stage (паритет
  // экранной ComparisonView DatasetPassportPanel; без пересчёта).
  const stageValues = new Map<string, Map<string, number>>();
  for (const stage of snapshot.path) stageValues.set(stage, new Map());
  for (const pair of snapshot.comparisons) {
    for (const [name, metric] of Object.entries(pair.comparison.metrics)) {
      if (!stageValues.has(pair.from_stage)) stageValues.set(pair.from_stage, new Map());
      if (!stageValues.has(pair.to_stage)) stageValues.set(pair.to_stage, new Map());
      stageValues.get(pair.from_stage)!.set(name, metric.v_old);
      stageValues.get(pair.to_stage)!.set(name, metric.v_new);
    }
  }
  const metricNames = Array.from(
    new Set(snapshot.comparisons.flatMap((pair) => Object.keys(pair.comparison.metrics))),
  );

  const listChanges = snapshot.comparisons.flatMap((pair) =>
    Object.entries(pair.comparison.list_changes)
      .filter(([, change]) => change.changed)
      .map(([label, change]) => ({
        pair,
        label,
        added: change.added ?? [],
        removed: change.removed ?? [],
      })),
  );

  return (
    <article
      data-testid="print-comparison-page"
      style={{
        backgroundColor: PRINT_PALETTE.page_background,
        color: PRINT_PALETTE.ink,
        padding: 24,
        boxSizing: "border-box",
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      <header style={{ borderBottom: `1px solid ${PRINT_PALETTE.border}`, paddingBottom: 8 }}>
        <h1 style={{ fontSize: PRINT_TYPE_SCALE.title, fontWeight: 700, margin: 0 }}>
          Сравнение паспортов свойств ряда
        </h1>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "2px 16px", marginTop: 8 }}>
          <ProvLine label="run" value={snapshot.run_id} />
          <ProvLine label="режим" value={snapshot.mode} />
          <ProvLine label="этапы" value={snapshot.path.join(" → ")} />
          <ProvLine label="context" value={snapshot.context?.context_id ?? "—"} />
          <ProvLine label="data_revision" value={snapshot.context?.data_revision ?? "—"} />
          <ProvLine label="движок" value={`${shortRef(snapshot.method_versions.engine.id)} ${snapshot.method_versions.engine.version}`} />
          <ProvLine label="полнота" value={snapshot.completeness} />
          {snapshot.cross_context && <Badge tone="warning">cross_context: явный режим сравнения исторических контекстов</Badge>}
        </div>
      </header>

      {metricNames.length > 0 && (
        <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <h3 style={{ fontSize: PRINT_TYPE_SCALE.section, fontWeight: 600, margin: 0 }}>Числовые метрики по этапам</h3>
          <table style={{ borderCollapse: "collapse", width: "100%", fontSize: PRINT_TYPE_SCALE.body }}>
            <thead>
              <tr style={{ backgroundColor: PRINT_PALETTE.band_fill }}>
                <th scope="col" style={{ border: `1px solid ${PRINT_PALETTE.border}`, padding: "6px 8px", textAlign: "left" }}>
                  Метрика
                </th>
                {snapshot.path.map((stage) => (
                  <th key={stage} scope="col" style={{ border: `1px solid ${PRINT_PALETTE.border}`, padding: "6px 8px", textAlign: "right" }}>
                    {stage}
                  </th>
                ))}
                {snapshot.comparisons.map((pair) => (
                  <th
                    key={`${pair.from_stage}-${pair.to_stage}`}
                    scope="col"
                    style={{ border: `1px solid ${PRINT_PALETTE.border}`, padding: "6px 8px", textAlign: "right" }}
                  >
                    {`Δ ${pair.from_stage} → ${pair.to_stage}`}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {metricNames.map((name) => (
                <tr key={name}>
                  <td style={{ border: `1px solid ${PRINT_PALETTE.border}`, padding: "5px 8px", fontWeight: 600 }}>{name}</td>
                  {snapshot.path.map((stage) => (
                    <td
                      key={`${name}-${stage}`}
                      style={{ border: `1px solid ${PRINT_PALETTE.border}`, padding: "5px 8px", textAlign: "right", fontVariantNumeric: "tabular-nums" }}
                    >
                      {formatNumberRu(stageValues.get(stage)?.get(name) ?? null, 4)}
                    </td>
                  ))}
                  {snapshot.comparisons.map((pair) => {
                    const metric = pair.comparison.metrics[name];
                    return (
                      <td
                        key={`${name}-${pair.from_stage}-${pair.to_stage}`}
                        style={{ border: `1px solid ${PRINT_PALETTE.border}`, padding: "5px 8px", textAlign: "right", fontVariantNumeric: "tabular-nums" }}
                      >
                        {metric
                          ? `${signedNumber(metric.delta)} (${signedNumber(metric.delta_pct)} %)`
                          : "—"}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <p style={{ margin: 0, fontSize: PRINT_TYPE_SCALE.small, color: PRINT_PALETTE.ink_faint }}>
            Абсолютное и относительное изменения приведены как зафиксированы сравнением; цвет ячеек
            не применяется — знак печатается явно (см. определения ниже).
          </p>
        </section>
      )}

      <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <h3 style={{ fontSize: PRINT_TYPE_SCALE.section, fontWeight: 600, margin: 0 }}>Качественные и категориальные изменения</h3>
        {snapshot.comparisons.map((pair) => (
          <p key={`${pair.from_stage}-${pair.to_stage}`} style={{ margin: 0, fontSize: PRINT_TYPE_SCALE.body }}>
            <strong>
              {pair.from_stage} → {pair.to_stage}:
            </strong>{" "}
            {pair.comparison.summary}
          </p>
        ))}
        {snapshot.comparisons.flatMap((pair) => pair.comparison.qualitative_changes).map((text, index) => (
          <p key={`qual-${index}`} style={{ margin: 0, fontSize: PRINT_TYPE_SCALE.body }}>
            · {text}
          </p>
        ))}
        {snapshot.comparisons.flatMap((pair) =>
          Object.entries(pair.comparison.categorical_changes)
            .filter(([, change]) => change.changed)
            .map(([label, change]) => (
              <p key={`cat-${label}`} style={{ margin: 0, fontSize: PRINT_TYPE_SCALE.body }}>
                · {label}: {String(change.v_old ?? "—")} → {String(change.v_new ?? "—")}
              </p>
            )),
        )}
        {snapshot.comparisons.flatMap((pair) =>
          Object.entries(pair.comparison.boolean_changes)
            .filter(([, change]) => change.changed)
            .map(([label, change]) => (
              <p key={`bool-${label}`} style={{ margin: 0, fontSize: PRINT_TYPE_SCALE.body }}>
                · {label}: {change.v_old ? "Да" : "Нет"} → {change.v_new ? "Да" : "Нет"}
              </p>
            )),
        )}
        {listChanges.map(({ pair, label, added, removed }) => (
          <p key={`list-${pair.from_stage}-${label}`} style={{ margin: 0, fontSize: PRINT_TYPE_SCALE.body }}>
            · {label} ({pair.from_stage} → {pair.to_stage}): Добавлено {renderList(added)}; Удалено {renderList(removed)}.
          </p>
        ))}
      </section>

      {snapshot.confirmation && (
        <section
          data-testid="print-comparison-confirmation"
          style={{ border: `1px solid ${PRINT_PALETTE.border}`, padding: "8px 12px", fontSize: PRINT_TYPE_SCALE.body }}
        >
          <strong>Подтверждение чекпоинта</strong>{" "}
          {snapshot.checkpoint?.stage ? `(этап ${snapshot.checkpoint.stage})` : ""}: подтверждено{" "}
          {formatPrintTime(snapshot.confirmation.confirmed_at, snapshot.confirmation.confirmed_at_reason)}.
          {snapshot.confirmation.unchanged
            ? " Состояние совпало с предыдущим снимком — подтверждение без повторного расчёта и без четвёртой копии паспорта."
            : " Используется ранее рассчитанный снимок без повторного расчёта."}{" "}
          reused ref: {snapshot.confirmation.reused_ref ?? "—"}.{" "}
          previous ref: {snapshot.confirmation.previous_ref ?? "нет (unchanged)"}.
        </section>
      )}

      {snapshot.gaps.length > 0 && (
        <section
          data-testid="print-comparison-gaps"
          style={{ border: `1px solid ${PRINT_PALETTE.status_warning}`, padding: "8px 12px", fontSize: PRINT_TYPE_SCALE.body }}
        >
          <strong>Полнота: {snapshot.completeness}</strong> — отсутствующие точки перечислены явно, нулем
          не подменяются (§9):
          <ul style={{ margin: "4px 0 0 0", paddingLeft: 16 }}>
            {snapshot.gaps.map((gap) => (
              <li key={`${gap.at}-${gap.reason}`}>
                {gap.at}: {gap.reason} — {gap.detail}
                {gap.snapshot_ref ? ` (${shortRef(gap.snapshot_ref)})` : ""}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section
        data-testid="print-comparison-definitions"
        style={{ borderTop: `1px solid ${PRINT_PALETTE.border}`, paddingTop: 8, fontSize: PRINT_TYPE_SCALE.small, color: PRINT_PALETTE.ink_muted }}
      >
        <strong style={{ color: PRINT_PALETTE.ink }}>Определения:</strong>
        <ul style={{ margin: "4px 0 0 0", paddingLeft: 16 }}>
          {Object.entries(snapshot.definitions).map(([key, text]) => (
            <li key={key}>
              {key}: {text}
            </li>
          ))}
        </ul>
      </section>

      <footer
        style={{
          borderTop: `1px solid ${PRINT_PALETTE.border}`,
          paddingTop: 8,
          display: "flex",
          justifyContent: "space-between",
          fontSize: PRINT_TYPE_SCALE.small,
          color: PRINT_PALETTE.ink_faint,
        }}
      >
        <span>
          источник: {snapshot.schema_version}; aliases: {snapshot.aliases.length}; пар: {snapshot.comparisons.length}
        </span>
        <span>{`Стр. ${pageIndex} из ${pageCount}`}</span>
      </footer>
    </article>
  );
}

function renderList(items: unknown[]): string {
  if (!items || items.length === 0) return "нет";
  return items.map((item) => (typeof item === "number" ? formatNumberRu(item, 4) : String(item))).join("; ");
}
