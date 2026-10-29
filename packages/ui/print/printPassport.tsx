// packages/ui/print/printPassport.tsx
//
// PGV-07 — Shared pure print layout: печатная страница паспорта свойств
// ряда (spec_passport_graphics_visual.md §8 «Печатный паспорт выводит все
// группы существующей схемы, units, unavailable reasons/warnings/schema/
// calculation version и provenance. Не сокращается до rows/columns/claim
// counts. Неизвестная schema — unsupported_schema/missing fields, не
// пустая «готовая» картинка»).
//
// Вход — frozen запись истории паспортов (зеркало item'а
// PassportHistoryReader PGV-05: schema pgv.passport_history/1, XOR-поля
// «ключ»+«ключ_reason», content_status/content_gap_reason). Компонент
// НЕ пересчитывает паспорт и НЕ фетчит: pure presentation.
//
// Честность (AC12/§8): отсутствие факта печатается причиной
// (legacy_unknown/integrity_failure), не выдуманным значением; content-гэп
// — баннер без паспортных таблиц; неизвестная схема — баннер
// unsupported_schema; неизвестные print'у группы НЕ выбрасываются —
// печатаются по ключу словаря.

import React from "react";
import {
  formatNumberRu,
  formatPrintTime,
  shortRef,
} from "./printLayout";
import { PRINT_PALETTE, PRINT_TYPE_SCALE } from "./printTheme";

/**
 * Версии схемы паспорта, известные печатному слою (§8: «Неизвестная
 * schema — unsupported_schema»). Источник — документация движка сравнения
 * app/core/passport.py («v1.0 vs v1.1 / v1.1 vs v1.2»); будущие версии
 * добавляются в этот allowlist вместе с их печатной поддержкой.
 */
export const KNOWN_PASSPORT_SCHEMA_VERSIONS: readonly string[] = [
  "passport/1.0",
  "passport/1.1",
  "passport/1.2",
];

/** Известные группы паспорта с человекочитаемыми подписями (§8 «все группы»). */
export const KNOWN_PASSPORT_GROUPS: readonly { key: string; label: string }[] = [
  { key: "basic_stats", label: "Базовые статистики" },
  { key: "freq", label: "Частота ряда" },
  { key: "stationarity", label: "Стационарность (ADF)" },
  { key: "determinism", label: "Детерминированность (R² тренда)" },
  { key: "autocorrelation", label: "Автокорреляция (Ljung–Box)" },
  { key: "normality", label: "Нормальность (Jarque–Bera)" },
  { key: "trend", label: "Тренд" },
  { key: "seasonality", label: "Сезонность" },
  { key: "hurst", label: "Показатель Хёрста" },
  { key: "correlations", label: "Автокорреляции (топ)" },
  { key: "fft", label: "FFT-периоды" },
  { key: "wavelet", label: "Вейвлет-анализ" },
];

export type PrintPassportContentStatus = "present" | "missing_artifact" | "corrupt";

/**
 * Frozen запись паспорта (зеркало item'а PGV-05). XOR-конвенция полей:
 * значение присутствует → reason null; отсутствует → null + явная причина.
 */
export interface PrintPassportRecord {
  schema_version: string;
  snapshot_ref: string | null;
  session_snapshot_id?: string | null;
  artifact_id: string | null;
  stage: string | null;
  universe: string | null;
  passport: Record<string, unknown> | null;
  content_status: PrintPassportContentStatus;
  content_gap_reason: string | null;
  target_column: string | null;
  date_column: string | null;
  context_id: string | null;
  data_revision: string | null;
  captured_at: string | null;
  created_at: string | null;
  fingerprint: string | null;
  fingerprint_reason: string | null;
  source_hash: string | null;
  source_hash_reason: string | null;
  passport_schema_version: string | null;
  passport_schema_version_reason: string | null;
  calculation_version: string | null;
  calculation_version_reason: string | null;
}

// ── Универсальный рендер значений групп ──────────────────────────

const TREND_DIRECTIONS: Record<string, string> = {
  up: "восходящий",
  down: "нисходящий",
  flat: "горизонтальный",
};

function renderScalar(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return formatNumberRu(value, 4);
  if (typeof value === "boolean") return value ? "Да" : "Нет";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    return value.length === 0 ? "—" : value.map((item) => renderScalar(item)).join("; ");
  }
  return String(value);
}

export interface PassportFieldRow {
  /** Метка поля (вложенные dict'ы — через точку). */
  label: string;
  value: string;
  /** Приглушение для служебных/неаппликабельных значений. */
  muted?: boolean;
}

/**
 * Плоское развёртывание группы паспорта в строки «метка — значение».
 * Особые случаи существующей схемы: trend.direction — словами;
 * is_stationary — «стационарен/нестационарен»; applicable=false + reason —
 * «не применимо: <причина>» (§8: unavailable reasons печатаются).
 * Неизвестные поля печатаются по ключу — ничего не выбрасывается.
 */
export function flattenPassportGroup(group: Record<string, unknown>, prefix = ""): PassportFieldRow[] {
  const rows: PassportFieldRow[] = [];
  for (const [key, value] of Object.entries(group)) {
    const label = prefix ? `${prefix}.${key}` : key;
    if (key === "applicable" && value === false) continue; // причина печатается рядом
    if (value !== null && typeof value === "object" && !Array.isArray(value)) {
      const nested = value as Record<string, unknown>;
      // §3.6: applicable:false + reason — «не применимо: <причина>». Ветка
      // достижима (PGV-07-FIX: ранее перехватывалась рекурсией по полям —
      // dead code, находка сертификации F-P7C3).
      if (nested.applicable === false) {
        rows.push({
          label,
          value: `не применимо: ${typeof nested.reason === "string" ? nested.reason : "причина не указана"}`,
          muted: true,
        });
        continue;
      }
      // Остальные plain-объекты — включая обёртки applicable:true —
      // разворачиваются по полям с префиксом (applicable печатается «Да»,
      // как на уровне группы); «[object Object]» невозможен (PGV-07-FIX).
      rows.push(...flattenPassportGroup(nested, label));
      continue;
    }
    if (key === "direction" && typeof value === "string" && TREND_DIRECTIONS[value]) {
      rows.push({ label, value: TREND_DIRECTIONS[value] });
      continue;
    }
    if (key === "is_stationary" && typeof value === "boolean") {
      rows.push({ label, value: value ? "стационарен" : "нестационарен" });
      continue;
    }
    rows.push({ label, value: renderScalar(value) });
  }
  return rows;
}

// ── Атомы ────────────────────────────────────────────────────────

function ProvItem({ label, value }: { label: string; value: string }) {
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

function xorText(value: string | null, reason: string | null | undefined): string {
  if (value) return value;
  if (reason) return `неизвестно (${reason})`;
  return "—";
}

// ── Страница паспорта ────────────────────────────────────────────

export interface PrintPassportPageProps {
  record: PrintPassportRecord;
  pageIndex: number;
  pageCount: number;
}

/**
 * Печатный паспорт: провенанс (этап/снимок/время/context/data_revision/
 * fingerprint/source_hash/schema/версия расчёта) + ВСЕ группы существующей
 * схемы + неизвестные группы по ключу. Content-гэп — честный баннер без
 * фабкации таблиц; неизвестная схема — баннер unsupported_schema (§8).
 */
export function PrintPassportPage({ record, pageIndex, pageCount }: PrintPassportPageProps) {
  const isKnownSchema =
    typeof record.passport_schema_version === "string" &&
    KNOWN_PASSPORT_SCHEMA_VERSIONS.includes(record.passport_schema_version);
  const contentGap = record.content_status !== "present" || record.passport === null;

  const knownKeys = new Set(KNOWN_PASSPORT_GROUPS.map((g) => g.key));
  const unknownGroupKeys = record.passport
    ? Object.keys(record.passport).filter((key) => !knownKeys.has(key))
    : [];

  return (
    <article
      data-testid="print-passport-page"
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
          Паспорт свойств ряда
          {record.stage ? `: ${record.stage}` : ""}
        </h1>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "2px 16px", marginTop: 8 }}>
          <ProvItem label="снимок" value={record.session_snapshot_id ?? shortRef(record.snapshot_ref)} />
          <ProvItem label="этап" value={record.stage ?? "—"} />
          <ProvItem label="вселенная" value={record.universe ?? "—"} />
          <ProvItem label="target" value={record.target_column ?? "—"} />
          <ProvItem label="даты" value={record.date_column ?? "—"} />
          <ProvItem label="context" value={record.context_id ?? "—"} />
          <ProvItem label="data_revision" value={record.data_revision ?? "—"} />
          <ProvItem
            label="captured_at"
            value={formatPrintTime(record.captured_at, record.captured_at ? null : "legacy_unknown")}
          />
          <ProvItem label="fingerprint" value={xorText(record.fingerprint, record.fingerprint_reason)} />
          <ProvItem label="source_hash" value={xorText(record.source_hash, record.source_hash_reason)} />
          <ProvItem
            label="schema"
            value={xorText(record.passport_schema_version, record.passport_schema_version_reason)}
          />
          <ProvItem
            label="версия расчёта"
            value={xorText(record.calculation_version, record.calculation_version_reason)}
          />
        </div>
      </header>

      {contentGap ? (
        <div
          data-testid="print-passport-content-gap"
          style={{
            border: `1px solid ${PRINT_PALETTE.status_warning}`,
            color: PRINT_PALETTE.status_warning,
            padding: "10px 12px",
            fontSize: PRINT_TYPE_SCALE.body,
          }}
        >
          Паспорт недоступен из durable-источника: статус «{record.content_status}», причина
          «{record.content_gap_reason ?? "не указана"}». Содержимое не фабрикуется и не заменяется
          текущими данными (§8).
        </div>
      ) : (
        <>
          {!isKnownSchema && (
            <div
              data-testid="print-passport-unsupported-schema"
              style={{
                border: `1px solid ${PRINT_PALETTE.status_warning}`,
                color: PRINT_PALETTE.status_warning,
                padding: "10px 12px",
                fontSize: PRINT_TYPE_SCALE.body,
              }}
            >
              unsupported_schema: версия схемы паспорта «{record.passport_schema_version}» неизвестна
              печатному слою; группы печатаются как есть, интерпретация полей не гарантируется.
            </div>
          )}
          <div data-testid="print-passport-groups" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {KNOWN_PASSPORT_GROUPS.filter((group) => {
              const value = (record.passport ?? {})[group.key];
              return value !== undefined && value !== null;
            }).map((group) => {
              const raw = (record.passport ?? {})[group.key] as Record<string, unknown>;
              const rows = flattenPassportGroup(raw && typeof raw === "object" && !Array.isArray(raw) ? raw : { value: raw });
              return (
                <section key={group.key} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  <h3 style={{ fontSize: PRINT_TYPE_SCALE.section, fontWeight: 600, margin: 0 }}>{group.label}</h3>
                  <table style={{ borderCollapse: "collapse", width: "100%", fontSize: PRINT_TYPE_SCALE.body }}>
                    <tbody>
                      {rows.map((row) => (
                        <tr key={`${group.key}-${row.label}`}>
                          <td
                            style={{
                              border: `1px solid ${PRINT_PALETTE.border}`,
                              padding: "4px 8px",
                              width: "40%",
                              color: row.muted ? PRINT_PALETTE.ink_faint : PRINT_PALETTE.ink_muted,
                            }}
                          >
                            {row.label}
                          </td>
                          <td
                            style={{
                              border: `1px solid ${PRINT_PALETTE.border}`,
                              padding: "4px 8px",
                              fontVariantNumeric: "tabular-nums",
                              color: row.muted ? PRINT_PALETTE.ink_faint : PRINT_PALETTE.ink,
                            }}
                          >
                            {row.value}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </section>
              );
            })}
            {unknownGroupKeys.map((key) => {
              const raw = (record.passport ?? {})[key];
              const rows = flattenPassportGroup(
                raw && typeof raw === "object" && !Array.isArray(raw)
                  ? (raw as Record<string, unknown>)
                  : { value: raw },
              );
              return (
                <section key={key} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  <h3 style={{ fontSize: PRINT_TYPE_SCALE.section, fontWeight: 600, margin: 0 }}>{key}</h3>
                  <p style={{ margin: 0, fontSize: PRINT_TYPE_SCALE.small, color: PRINT_PALETTE.ink_faint }}>
                    группа вне известного print'у набора — печатается по ключу без интерпретации
                  </p>
                  <table style={{ borderCollapse: "collapse", width: "100%", fontSize: PRINT_TYPE_SCALE.body }}>
                    <tbody>
                      {rows.map((row) => (
                        <tr key={`${key}-${row.label}`}>
                          <td style={{ border: `1px solid ${PRINT_PALETTE.border}`, padding: "4px 8px", width: "40%", color: PRINT_PALETTE.ink_muted }}>
                            {row.label}
                          </td>
                          <td style={{ border: `1px solid ${PRINT_PALETTE.border}`, padding: "4px 8px", fontVariantNumeric: "tabular-nums" }}>
                            {row.value}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </section>
              );
            })}
          </div>
        </>
      )}

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
        <span>источник: pgv.passport_history/1 (PassportHistoryReader, durable refs без SessionStore)</span>
        <span>{`Стр. ${pageIndex} из ${pageCount}`}</span>
      </footer>
    </article>
  );
}
