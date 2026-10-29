// packages/ui/print/printLayout.tsx
//
// PGV-07 — Shared pure print layout: каркас печатной страницы
// (spec_passport_graphics_visual.md §7 «PNG и печатная композиция»):
//   Верх  — заголовок/номер, источник/target/entity, даты;
//   Центр — рисунок/таблица (секции, printSections/printIh);
//   Низ   — методы/параметры/пояснения/ограничения, версия данных,
//           короткие IDs, page number; полные refs остаются в metadata.
//
// Чистота (§4.1): компоненты — pure function of props, без fetch/state/
// animation/текущего времени. Все стили — инлайн hex-константы печатной
// темы (printTheme), поэтому рендер не зависит от экранной темы (AC04).
// Геометрия страницы — фиксированные пиксели профиля (не резиновый
// viewport): Playwright (PGV-08) снимает специально
// построенную print page.
//
// «use client» сознательно нет: компоненты без хуков/обработчиков
// рендерятся и в server-контексте (урок DOCLOG-8-UI-FIX), print bundle
// подключается напрямую (packages/ui/print), barrel packages/ui/index.ts
// не затрагивается.

import React from "react";
import type {
  PrintProfileId,
  UnitDeclaration,
  VisualPrintSnapshotV1,
} from "./printSchema";
import { PRINT_PROFILE_CATALOG, resolvePrintProfile } from "./printSchema";
import {
  PRINT_FONT_STACK,
  PRINT_PALETTE,
  PRINT_TYPE_SCALE,
} from "./printTheme";

// ── Форматтеры (детерминированные, без ICU/локали машины) ────────

/**
 * Число в ru-формате с фиксированными разделителями (пробел — тысячи,
 * запятая — дробная часть; хвостовые нули дроби срезаются — digits задаёт
 * ТОЧНОСТЬ, не ширину). Детерминизм печати важнее ICU: формат не зависит
 * от машины рендера (byte-determinism, §12).
 */
export function formatNumberRu(
  value: number | null | undefined,
  digits = 1,
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const fixed = Math.abs(value).toFixed(digits);
  const [intPart, fracPart] = fixed.split(".");
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  const sign = value < 0 ? "-" : "";
  const trimmedFrac = fracPart ? fracPart.replace(/0+$/, "") : "";
  const frac = trimmedFrac.length > 0 ? `,${trimmedFrac}` : "";
  return `${sign}${grouped}${frac}`;
}

/**
 * Время печати — из ISO-строки напрямую («YYYY-MM-DD HH:MM UTC»), без
 * конструирования времени рантайма и без локали/зоны машины: детерминизм
 * печати. Отсутствие — явная причина (XOR-честность §6: не выдумывать
 * timestamps), null без причины — «—».
 */
export function formatPrintTime(
  iso: string | null | undefined,
  reason: string | null | undefined,
  timezoneFallback = "UTC",
): string {
  if (typeof iso === "string" && iso.length >= 16) {
    const date = iso.slice(0, 10);
    const time = iso.slice(11, 16);
    return `${date} ${time} ${timezoneFallback}`;
  }
  if (reason) return `неизвестно (${reason})`;
  return "—";
}

/** Единица измерения: значение XOR явная причина отсутствия (§6). */
export function formatUnit(unit: UnitDeclaration | undefined): string {
  if (!unit) return "—";
  if (unit.value) return unit.value;
  if (unit.reason) return `без единицы (${unit.reason})`;
  return "—";
}

/** Короткий ID для подвала страницы (полные refs — в metadata, §7). */
export function shortRef(ref: string | null | undefined, keep = 10): string {
  if (!ref) return "—";
  return ref.length <= keep ? ref : `${ref.slice(0, Math.max(1, keep))}…`;
}

export interface SamplingTextParts {
  applicable: boolean;
  mode: "full" | "downsampled" | "windowed" | "aggregated" | "truncated" | null;
  point_cap: number | null;
  reason: string | null;
}

/** Честный текст сэмплинга (AC08: режимы различимы, без скрытого upgrade). */
export function describeSampling(sampling: SamplingTextParts): string {
  if (!sampling.applicable) {
    return sampling.reason
      ? `сэмплинг не применим: ${sampling.reason}`
      : "сэмплинг не применим";
  }
  const mode = sampling.mode ?? "—";
  // Потолок точек печатается без группировки разрядов: это служебное
  // число frozen-результата (паритет экранному SamplingBadge).
  const cap = sampling.point_cap !== null ? `, потолок ${String(sampling.point_cap)} точек` : "";
  const reason = sampling.reason ? `, причина: ${sampling.reason}` : "";
  return `сэмплинг: ${mode}${cap}${reason}`;
}

// ── Геометрия профиля (PGV-AC16) ─────────────────────────────────

export interface PageGeometry {
  profile_id: PrintProfileId;
  width_px: number;
  height_px: number;
  /** px на дюйм печати (300 ppi A4 / figure-landscape из каталога PGV-01). */
  ppi: number;
  /** Пропорция w/h (сохраняется при масштабировании). */
  aspect: number;
}

/** Геометрия печатной страницы из каталога профилей PGV-01 (§7). */
export function pageGeometry(profileId: PrintProfileId): PageGeometry {
  const profile = resolvePrintProfile(profileId);
  if (!profile) throw new Error(`Неизвестный print-профиль: ${profileId}`);
  const width_px = profile.width_px;
  const height_px = profile.height_px;
  return {
    profile_id: profile.id,
    width_px,
    height_px,
    ppi: profile.ppi,
    aspect: width_px / height_px,
  };
}

/** Каталог профилей PGV-01 (реэкспорт для print-потребителей). */
export { PRINT_PROFILE_CATALOG };

// ── Поверхность страницы ─────────────────────────────────────────

export interface PrintPageSurfaceProps {
  profileId: PrintProfileId;
  /** Масштаб к физическим пикселям профиля (превью/подгонка лимита 12 MP). */
  scale?: number;
  children?: React.ReactNode;
  testId?: string;
}

/**
 * Фиксированная печатная поверхность: пиксели профиля × scale, непрозрачный
 * белый фон, шрифтовой стек печати. Не viewport и не резиновый контейнер —
 * детерминированная геометрия для растеризации (PGV-08).
 */
export function PrintPageSurface({
  profileId,
  scale = 1,
  children,
  testId = "print-page-surface",
}: PrintPageSurfaceProps) {
  const geometry = pageGeometry(profileId);
  return (
    <div
      data-testid={testId}
      style={{
        width: `${Math.round(geometry.width_px * scale)}px`,
        height: `${Math.round(geometry.height_px * scale)}px`,
        backgroundColor: PRINT_PALETTE.page_background,
        color: PRINT_PALETTE.ink,
        fontFamily: PRINT_FONT_STACK,
        overflow: "hidden",
        position: "relative",
        boxSizing: "border-box",
      }}
    >
      {children}
    </div>
  );
}

// ── Атомы текста ─────────────────────────────────────────────────

function labelValue(label: string, value: string): React.ReactNode {
  return (
    <div key={label} style={{ display: "flex", gap: 6, alignItems: "baseline" }}>
      <span
        style={{
          fontSize: PRINT_TYPE_SCALE.small,
          color: PRINT_PALETTE.ink_faint,
          whiteSpace: "nowrap",
        }}
      >
        {label}:
      </span>
      <span
        style={{
          fontSize: PRINT_TYPE_SCALE.small,
          color: PRINT_PALETTE.ink_muted,
          fontFamily: "monospace",
        }}
      >
        {value}
      </span>
    </div>
  );
}

export function PrintSectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3
      style={{
        fontSize: PRINT_TYPE_SCALE.section,
        fontWeight: 600,
        color: PRINT_PALETTE.ink,
        margin: "0 0 6px 0",
      }}
    >
      {children}
    </h3>
  );
}

/** Пояснения/ограничения в подвале (§7: низ страницы). */
export function PrintNotes({ items }: { items: readonly string[] }) {
  if (!items.length) return null;
  return (
    <ul
      data-testid="print-warnings"
      style={{
        margin: 0,
        paddingLeft: 16,
        fontSize: PRINT_TYPE_SCALE.small,
        color: PRINT_PALETTE.ink_muted,
      }}
    >
      {items.map((item, index) => (
        <li key={`${index}-${item.slice(0, 24)}`}>{item}</li>
      ))}
    </ul>
  );
}

/**
 * Полная легенда печати: ВСЕ записи series/категорий в заданном порядке
 * (§7: «полная legend», «легенда не теряется при раскрытии»). Свотч —
 * жёсткий светлый цвет; записи без пропусков.
 */
export function PrintLegendStrip({
  ordering,
  note,
}: {
  ordering: readonly string[];
  note?: string | null;
}) {
  return (
    <div
      data-testid="print-legend"
      style={{
        display: "flex",
        flexWrap: "wrap",
        alignItems: "center",
        gap: "4px 14px",
        fontSize: PRINT_TYPE_SCALE.small,
        color: PRINT_PALETTE.ink_muted,
      }}
    >
      <span style={{ color: PRINT_PALETTE.ink_faint }}>легенда:</span>
      {ordering.map((entry, index) => (
        <span key={`${index}-${entry}`} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
          <span
            aria-hidden="true"
            style={{
              width: 9,
              height: 9,
              borderRadius: 2,
              backgroundColor: index % 2 === 0 ? PRINT_PALETTE.series_blue : PRINT_PALETTE.series_blue_soft,
              border: `1px solid ${PRINT_PALETTE.border}`,
            }}
          />
          {entry}
        </span>
      ))}
      {note ? <span style={{ color: PRINT_PALETTE.ink_faint }}>({note})</span> : null}
    </div>
  );
}

// ── Каркас страницы §7 ───────────────────────────────────────────

const ORIGIN_LABELS: Record<string, string> = {
  producer_freeze: "фиксация producer'а",
  producer_first_export: "первый экспорт producer'а",
};

export interface PrintPageFrameProps {
  /** Frozen VisualPrintSnapshot/1 (PGV-01) — единственный источник фактов. */
  snapshot: VisualPrintSnapshotV1;
  /** Человекочитаемый источник: «модуль / остановка» (по умолчанию из view_id). */
  source?: string;
  children?: React.ReactNode;
  /** Номер страницы (1-based) и общее число — печатаются в подвале (§7). */
  pageIndex: number;
  pageCount: number;
  profileId?: PrintProfileId;
  scale?: number;
}

/**
 * Каркас печатной страницы из frozen снапшота: header (title/вид/источник/
 * размерности/даты) + тело (секции) + footer (метод/параметры/пояснения/
 * версия данных/короткие IDs/номер страницы). Анимации выключаются
 * глобальным kill-switch'ом страницы (детерминизм растеризации).
 */
export function PrintPageFrame({
  snapshot,
  source,
  children,
  pageIndex,
  pageCount,
  profileId,
  scale = 1,
}: PrintPageFrameProps) {
  const profile = profileId ?? snapshot.print.profile_id;
  const dims = snapshot.dimensions;
  const modulePart = snapshot.view_id.split(".").slice(0, 2).join(" / ");
  const dataSource =
    snapshot.refs.data_revision ??
    snapshot.expected_context.data_revision ??
    snapshot.data_artifact.artifact_version ??
    snapshot.refs.demo_dataset_id ??
    "—";
  const parameterText =
    Object.keys(snapshot.method.parameters ?? {}).length > 0
      ? Object.entries(snapshot.method.parameters)
          .map(([key, value]) => `${key}=${String(value)}`)
          .join("; ")
      : null;

  return (
    <PrintPageSurface profileId={profile} scale={scale} testId="print-page-surface">
      {/* Kill-switch анимаций/переходов: печатная страница детерминирована. */}
      <style>{"*, *::before, *::after { animation: none !important; transition: none !important; }"}</style>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          height: "100%",
          padding: 24,
          boxSizing: "border-box",
          gap: 12,
        }}
      >
        {/* ── Верх §7 ─────────────────────────────────────────── */}
        <header
          data-testid="print-header"
          style={{
            borderBottom: `1px solid ${PRINT_PALETTE.border}`,
            paddingBottom: 8,
          }}
        >
          <h1
            style={{
              fontSize: PRINT_TYPE_SCALE.title,
              fontWeight: 700,
              color: PRINT_PALETTE.ink,
              margin: 0,
            }}
          >
            {snapshot.display.title}
          </h1>
          {snapshot.display.subtitle && (
            <p
              style={{
                fontSize: PRINT_TYPE_SCALE.subtitle,
                color: PRINT_PALETTE.ink_muted,
                margin: "4px 0 0 0",
              }}
            >
              {snapshot.display.subtitle}
            </p>
          )}
          <div
            data-testid="print-meta"
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: "2px 16px",
              marginTop: 8,
            }}
          >
            {labelValue("вид", `${snapshot.view_id} (${snapshot.scope})`)}
            {labelValue("источник", source ?? modulePart)}
            {dims.target_column && labelValue("target", dims.target_column)}
            {dims.date_column && labelValue("даты", dims.date_column)}
            {dims.entity_column && labelValue("entity", dims.entity_column)}
            {dims.entity_id && labelValue("entity_id", dims.entity_id)}
            {labelValue("режим", dims.mode)}
            {snapshot.expected_context.context_id &&
              labelValue("context", snapshot.expected_context.context_id)}
            {snapshot.expected_context.data_revision &&
              labelValue("data_revision", snapshot.expected_context.data_revision)}
            {labelValue(
              "рассчитано",
              formatPrintTime(
                snapshot.times.computed_at,
                snapshot.times.computed_at_reason,
                snapshot.times.timezone,
              ),
            )}
            {labelValue(
              "зафиксировано",
              formatPrintTime(
                snapshot.times.captured_at,
                snapshot.times.captured_at_reason,
                snapshot.times.timezone,
              ),
            )}
            {snapshot.checkpoint?.reused &&
              labelValue(
                "checkpoint",
                `reused, подтверждён ${formatPrintTime(snapshot.times.checkpoint_confirmed_at, null, snapshot.times.timezone)}`,
              )}
          </div>
          {snapshot.sampling.applicable && (
            <p
              data-testid="print-sampling"
              style={{
                fontSize: PRINT_TYPE_SCALE.small,
                color: PRINT_PALETTE.status_warning,
                margin: "6px 0 0 0",
              }}
            >
              {describeSampling(snapshot.sampling)}
            </p>
          )}
        </header>

        {/* ── Центр §7: секции тела ───────────────────────────── */}
        <div style={{ flex: "1 1 auto", minHeight: 0 }}>{children}</div>

        {/* ── Низ §7 ──────────────────────────────────────────── */}
        <footer
          data-testid="print-footer"
          style={{
            borderTop: `1px solid ${PRINT_PALETTE.border}`,
            paddingTop: 8,
            display: "flex",
            flexDirection: "column",
            gap: 4,
          }}
        >
          <div style={{ display: "flex", flexWrap: "wrap", gap: "2px 16px" }}>
            {labelValue(
              "метод",
              `${snapshot.method.method} (${snapshot.method.origin} — ${ORIGIN_LABELS[snapshot.method.origin] ?? "происхождение не зафиксировано"})`,
            )}
            {parameterText && labelValue("параметры", parameterText)}
            {labelValue("версия данных", dataSource)}
            {labelValue("результат", shortRef(snapshot.result.result_ref))}
            {labelValue(
              "рендер",
              `${snapshot.print.theme}, профиль ${snapshot.print.profile_id}`,
            )}
            <div style={{ marginLeft: "auto" }}>
              {labelValue("страница", `Стр. ${pageIndex} из ${pageCount}`)}
            </div>
          </div>
          <PrintNotes items={snapshot.warnings} />
        </footer>
      </div>
    </PrintPageSurface>
  );
}
