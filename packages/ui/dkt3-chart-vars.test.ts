// packages/ui/dkt3-chart-vars.test.ts
//
// Task DKT-3 — фиксированные hex → переменные: графики, волновые фоны,
// флоучарты (spec_dark_theme.md §7 DKT-3, §6.3).
//
// Инварианты:
//  1. Все графовые/статусные/волновые переменные определены в globals.css
//     в ОБОИХ блоках (:root/.dark); светлые значения — байт-инвариант
//     прежних литералов (пин-таблица ниже = карта миграции).
//  2. В коде графовых компонентов не остаётся цитированных hex-литералов
//     (белый список: canvas-заливка экспорта #FFFFFF — «всегда светлый
//     артефакт» §10.1; интерполяционная шкала heatmap — JS-числа).
//  3. Тёмные ревизии серий — не-текстовые ≥ 3.0:1 против карточки;
//     текстовые роли ≥ 4.5:1 (spec §6.3, пороги WCAG 2.1 AA).
//  4. Волновые тёмные значения — тёмные (яркость ≤ 0.25), декоративные
//     слои не всплывают на тёмной странице.

import { readFileSync, readdirSync, statSync } from "node:fs";
import { resolve, join } from "node:path";

const GLOBALS = readFileSync(resolve(__dirname, "globals.css"), "utf8");

function hexToChannels(hex: string): string {
  const h = hex.replace("#", "");
  const n = parseInt(h, 16);
  return `${(n >> 16) & 255} ${(n >> 8) & 255} ${n & 255}`;
}

function channelsToRgb(channels: string): [number, number, number] {
  const [r, g, b] = channels.trim().split(/\s+/).map(Number);
  return [r, g, b];
}

function relativeLuminance([r, g, b]: [number, number, number]): number {
  const f = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}

function contrastRatio(a: string, b: string): number {
  const la = relativeLuminance(channelsToRgb(a));
  const lb = relativeLuminance(channelsToRgb(b));
  const [hi, lo] = la > lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

// ── пин-таблица: var → [светлое (байт-инвариант), тёмное] ──
// Источник карты миграции: скан всех цитированных hex-литералов
// графовых компонентов (отчёт DKT-3 §2). Спековские --chart-grid/
// -axis/-surface/-brand/-reference и --status-* — из §6.3; остальные —
// документированные расширения по фактическим ролям кода.
export const CHART_VARS: Record<string, [string, string]> = {
  "chart-grid": ["#F0F0F0", "#262830"],
  "chart-border": ["#E5E5E5", "#2E3038"],
  "chart-axis": ["#171717", "#CACCD4"],
  "chart-axis-text": ["#737373", "#9A9DA9"],
  "chart-axis-muted": ["#A3A3A3", "#71747F"],
  "chart-reference": ["#D4D4D4", "#3B3E47"],
  "chart-surface": ["#FFFFFF", "#1C1D23"],
  "chart-brand": ["#2E3192", "#8F94F5"],
  "chart-brand-soft": ["#E8EAF6", "#1E2034"],
  "chart-blue": ["#2563EB", "#60A5FA"],
  "chart-blue-soft": ["#60A5FA", "#93C5FD"],
  "chart-blue-pale": ["#93C5FD", "#93C5FD"],
  "chart-violet": ["#7C3AED", "#A78BFA"],
  "chart-cyan": ["#0891B2", "#22D3EE"],
  "chart-slate": ["#94A3B8", "#94A3B8"],
  "chart-neutral": ["#9CA3AF", "#9CA3AF"],
  "status-error": ["#DC2626", "#F87171"],
  "status-success": ["#16A34A", "#4ADE80"],
  "status-warning": ["#D97706", "#FBBF24"],
  "status-warning-mid": ["#F59E0B", "#FBBF24"],
  "status-error-bright": ["#F87171", "#F87171"],
  "status-success-bright": ["#4ADE80", "#4ADE80"],
  "status-warning-bright": ["#FBBF24", "#FBBF24"],
  "status-error-strong": ["#EF4444", "#F87171"],
};

function extractVarBlock(blockSelector: string): Record<string, string> {
  const vars: Record<string, string> = {};
  const blockRe = new RegExp(`${blockSelector}\\s*\\{([\\s\\S]*?)\\n\\}`, "m");
  const m = GLOBALS.match(blockRe);
  if (!m) return vars;
  const varRe = /--([a-z0-9-]+)\s*:\s*(#[0-9A-Fa-f]{6})\s*;/g;
  let vm: RegExpExecArray | null;
  while ((vm = varRe.exec(m[1])) !== null) vars[vm[1]] = vm[2];
  return vars;
}

const LIGHT_BLOCK = extractVarBlock(":root");
const DARK_BLOCK = extractVarBlock("\\.dark");

// ── 1. Переменные определены в обоих блоках; светлые — байт-инвариант ──

describe("DKT-3: графовые переменные в globals.css", () => {
  it("каждая переменная присутствует в :root и .dark со значениями пин-таблицы", () => {
    const problems: string[] = [];
    for (const [name, [light, dark]] of Object.entries(CHART_VARS)) {
      if (LIGHT_BLOCK[name] !== light) {
        problems.push(`:root --${name} = ${LIGHT_BLOCK[name] ?? "ОТСУТСТВУЕТ"}, ожидалось ${light}`);
      }
      if (DARK_BLOCK[name] !== dark) {
        problems.push(`.dark --${name} = ${DARK_BLOCK[name] ?? "ОТСУТСТВУЕТ"}, ожидалось ${dark}`);
      }
    }
    expect(problems).toEqual([]);
  });

  it("волновые переменные определены в обоих блоках и согласованы по числу", () => {
    const lightWaves = Object.keys(LIGHT_BLOCK).filter((k) => k.startsWith("wave-"));
    const darkWaves = Object.keys(DARK_BLOCK).filter((k) => k.startsWith("wave-"));
    expect(lightWaves.length).toBeGreaterThan(0);
    expect(lightWaves.sort()).toEqual(darkWaves.sort());
  });

  it("тёмные волновые значения декоративно тёмные (яркость ≤ 0.25)", () => {
    for (const [name, value] of Object.entries(DARK_BLOCK)) {
      if (!name.startsWith("wave-")) continue;
      const lum = relativeLuminance(channelsToRgb(hexToChannels(value)));
      expect(lum).toBeLessThanOrEqual(0.25);
    }
  });
});

// ── 2. В коде графовых компонентов нет цитированных hex-литералов ──

function walkTsx(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) {
      if (name === "node_modules" || name === "__tests__") continue;
      walkTsx(full, out);
    } else if (name.endsWith(".tsx") && !name.includes(".test.")) {
      out.push(full);
    }
  }
  return out;
}

describe("DKT-3: инвариант отсутствия фиксированных hex в графовом коде", () => {
  // Белый список (отчёт DKT-3 §5 «Границы»):
  //  - ForecastExportMenu.tsx — canvas-заливка #FFFFFF («всегда светлый
  //    печатный артефакт», §10.1, рекомендация спеки);
  //  - PreprocessingMissingVisualizations.tsx — интерполяционная шкала
  //    heatmap строится из JS-чисел каналов [r,g,b]; var() не
  //    интерполируется — фиксированные каналы оставлены, тёмная ревизия
  //    шкалы — отдельное решение (визуально шкала читаема на тёмном).
  const WHITELIST_FILES = new Set([
    "ForecastExportMenu.tsx",
    "PreprocessingMissingVisualizations.tsx",
  ]);

  it("цитированные hex-литералы в компонентах отсутствуют (вне белого списка)", () => {
    const files = walkTsx(resolve(__dirname, "components"));
    const offenders: string[] = [];
    const hexRe = /["']#[0-9A-Fa-f]{6}["']/g;
    for (const file of files) {
      // Платформо-независимый basename: нормализация разделителей win32 →
      // POSIX (на Windows walkTsx/join дают backslash, split("/") возвращал
      // полный путь, белый список не срабатывал — ложный offender).
      const base = file.replace(/\\/g, "/").split("/").pop()!;
      if (WHITELIST_FILES.has(base)) continue;
      const src = readFileSync(file, "utf8");
      // строки кода без // -комментариев: hex в комментариях не считается
      for (const line of src.split("\n")) {
        const code = line.includes("//") ? line.slice(0, line.indexOf("//")) : line;
        if (hexRe.test(code)) offenders.push(`${base}: ${code.trim().slice(0, 80)}`);
        hexRe.lastIndex = 0;
      }
    }
    expect(offenders).toEqual([]);
  });
});

// ── 3. Контраст тёмных ревизий ──

describe("DKT-3: контраст тёмных ревизий серий (WCAG 2.1 AA)", () => {
  const CARD = "#16171C";
  it("серийные/статусные роли ≥ 3.0:1 против карточки (не-текст)", () => {
    const series = [
      "chart-brand", "chart-blue", "chart-blue-soft", "chart-blue-pale",
      "chart-violet", "chart-cyan", "chart-slate", "chart-neutral",
      "status-error", "status-success", "status-warning", "status-warning-mid",
      "status-error-bright", "status-success-bright", "status-warning-bright",
      "status-error-strong", "chart-axis", "chart-axis-text",
    ];
    const fails: string[] = [];
    for (const name of series) {
      const dark = CHART_VARS[name][1];
      const ratio = contrastRatio(hexToChannels(dark), hexToChannels(CARD));
      const isTextRole = name === "chart-axis-text" || name === "chart-axis";
      const threshold = isTextRole ? 4.5 : 3.0;
      if (ratio < threshold) fails.push(`--${name} (${dark}): ${ratio.toFixed(2)} < ${threshold}`);
    }
    expect(fails).toEqual([]);
  });

  it("осевые текстовые роли ≥ 4.5:1 против карточки", () => {
    expect(contrastRatio(hexToChannels("#9A9DA9"), hexToChannels(CARD))).toBeGreaterThanOrEqual(4.5);
  });
});
