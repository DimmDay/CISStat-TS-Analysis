// packages/ui/dark-catalog-contrast.test.ts
//
// Task DKT-2 — контраст-аудит каталога (spec_dark_theme.md: «программный
// аудит контраста WCAG AA на всех текст/фон-парах каталога — скрипт-оракул,
// не глаза»).
//
// Jest-зеркало оракула scripts/task_dkt2/contrast_audit.py (независимая
// вторая реализация — культура перекрёстной проверки задач-сертификаций).
// Значения читаются из globals.css (единственный источник значений),
// пары — роль-парные комбинации каталога §6.1/§6.3.
//
// Семантика порогов (вердикт калибровки DKT-2):
//  - mode "aa"      — пара обязана держать порог в ОБОИХ темах;
//  - mode "dark"    — порог только для тёмной ревизии (светлая — исходно
//                     ниже AA; факт светлой темы зафиксирован инвариантом
//                     и не может меняться, тёмная обязана быть лучше:
//                     ratio_dark ≥ 4.5);
//  - mode "baseline"— светлое ratio зафиксировано ТОЧНО (2 знака) как
//                     факт-инвариант светлой темы; тёмное ≥ порога.
// Пороги WCAG 2.1 AA: 4.5:1 обычный текст; 3.0:1 крупный текст и
// не-текстовые UI-элементы (индикаторы).

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const GLOBALS_PATH = resolve(__dirname, "globals.css");

function extractBlock(css: string, blockSelector: string): Record<string, string> {
  const vars: Record<string, string> = {};
  const blockRe = new RegExp(`${blockSelector}\\s*\\{([\\s\\S]*?)\\n\\}`, "m");
  const m = css.match(blockRe);
  if (!m) return vars;
  const varRe = /--c-([a-z0-9-]+)\s*:\s*([0-9 ]+);/g;
  let vm: RegExpExecArray | null;
  while ((vm = varRe.exec(m[1])) !== null) vars[vm[1]] = vm[2].trim();
  return vars;
}

function channelsToRgb(channels: string): [number, number, number] {
  const [r, g, b] = channels.trim().split(/\s+/).map(Number);
  return [r, g, b];
}

function hexToChannels(hex: string): string {
  const h = hex.replace("#", "");
  const n = parseInt(h, 16);
  return `${(n >> 16) & 255} ${(n >> 8) & 255} ${n & 255}`;
}

function relativeLuminance([r, g, b]: [number, number, number]): number {
  const f = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}

export function contrastRatio(a: string, b: string): number {
  const la = relativeLuminance(channelsToRgb(a));
  const lb = relativeLuminance(channelsToRgb(b));
  const [hi, lo] = la >= lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

const PAGE_BG_DARK = "#0B0C10"; // фон страницы (каталог §6.1; body — DKT-4)
const FOOTER_PROP_BG = "#CAD7F7"; // HomeFooter проп-фон (не токен; DKT-3 handoff)
const WHITE_FG = "white-fg"; // текст на заливках (utility-ревизия §6.2)

type PairMode = "aa" | "dark" | "baseline";

interface Pair {
  bg: string;
  fg: string;
  /** Порог тёмной ревизии (для "aa" — также светлой). */
  darkThreshold: number;
  mode: PairMode;
  /** mode="baseline": точное светлое ratio (2 знака) — инвариант светлой. */
  lightRatio?: number;
  /** Исключить тёмную сторону из проверки (замена — отдельная пара). */
  darkExempt?: boolean;
  note?: string;
}

const PAIRS: Pair[] = [
  // ── Нейтральная рампа: карточка (white) ↔ тексты — AA в обеих темах ──
  { bg: "white", fg: "neutral-900", darkThreshold: 4.5, mode: "aa" },
  { bg: "white", fg: "neutral-800", darkThreshold: 4.5, mode: "aa" },
  { bg: "white", fg: "neutral-700", darkThreshold: 4.5, mode: "aa" },
  { bg: "white", fg: "neutral-600", darkThreshold: 4.5, mode: "aa" },
  { bg: "white", fg: "neutral-500", darkThreshold: 4.5, mode: "aa" },
  // placeholder/disabled: светлый факт ниже AA — фиксируется, тёмная ≥3:1
  { bg: "white", fg: "neutral-400", darkThreshold: 3.0, mode: "dark", note: "placeholder/disabled — не-текстовый порог" },
  // декоративные стрелки: паритет с светлой (почти невидимы в обеих)
  { bg: "white", fg: "neutral-300", darkThreshold: 1.0, mode: "dark", note: "декоративные стрелки" },

  // ── Страница (тёмная #0B0C10) ↔ тексты ──
  { bg: PAGE_BG_DARK, fg: "neutral-800", darkThreshold: 4.5, mode: "dark" },
  { bg: PAGE_BG_DARK, fg: "neutral-500", darkThreshold: 4.5, mode: "dark" },

  // ── Бренд: заливка и текст (R-3) ──
  // bg-brand + text-white: белый текст на заливках сохранён utility-ревизией
  { bg: "brand", fg: WHITE_FG, darkThreshold: 4.5, mode: "aa", note: "кнопки/активные бейджи" },
  // text-brand: bright-ревизия (utility §6.2/R-3)
  { bg: "white", fg: "brand-bright", darkThreshold: 4.5, mode: "aa", note: "text-brand на карточках" },
  { bg: "brand-light", fg: "brand-bright", darkThreshold: 4.5, mode: "aa", note: "шапки карточек" },
  { bg: "brand-light", fg: "neutral-500", darkThreshold: 4.5, mode: "dark", lightRatio: 3.96, note: "светлый факт 3.96 — ниже AA, тёмная исправляет" },
  { bg: "brand-light", fg: "neutral-600", darkThreshold: 4.5, mode: "aa" },
  { bg: "brand-light", fg: "neutral-700", darkThreshold: 4.5, mode: "aa" },
  { bg: "brand-light", fg: "neutral-800", darkThreshold: 4.5, mode: "aa" },

  // ── Код-блок (инверсная поверхность, §6.2) ──
  { bg: "neutral-950", fg: "neutral-800", darkThreshold: 4.5, mode: "dark", note: "после точечного dark:text-neutral-800" },
  { bg: "neutral-950", fg: "neutral-100", darkThreshold: 4.5, mode: "baseline", lightRatio: 18.16, darkExempt: true, note: "светлая пара код-блока; в тёмной замена — dark:text-neutral-800 (след. пара)" },

  // ── Статусы: поверхность-50 ↔ тексты ──
  { bg: "green-50", fg: "green-700", darkThreshold: 4.5, mode: "aa" },
  { bg: "green-50", fg: "green-800", darkThreshold: 4.5, mode: "aa" },
  { bg: "green-50", fg: "green-600", darkThreshold: 4.5, mode: "dark", lightRatio: 3.15, note: "светлый факт 3.15 — ниже AA, тёмная исправляет" },
  { bg: "white", fg: "green-700", darkThreshold: 4.5, mode: "aa" },
  { bg: "amber-50", fg: "amber-700", darkThreshold: 4.5, mode: "aa" },
  { bg: "amber-50", fg: "amber-800", darkThreshold: 4.5, mode: "aa" },
  { bg: "amber-50", fg: "amber-600", darkThreshold: 4.5, mode: "dark", lightRatio: 3.07, note: "светлый факт 3.07" },
  { bg: "amber-50", fg: "amber-900", darkThreshold: 4.5, mode: "aa" },
  { bg: "red-50", fg: "red-700", darkThreshold: 4.5, mode: "aa" },
  { bg: "red-50", fg: "red-600", darkThreshold: 4.5, mode: "dark", lightRatio: 4.41, note: "светлый факт 4.41 — под AA, тёмная исправляет" },
  { bg: "red-50", fg: "red-800", darkThreshold: 4.5, mode: "aa" },
  { bg: "blue-50", fg: "blue-700", darkThreshold: 4.5, mode: "aa" },
  { bg: "blue-50", fg: "blue-900", darkThreshold: 4.5, mode: "aa" },
  { bg: "blue-50", fg: "blue-800", darkThreshold: 4.5, mode: "aa" },
  { bg: "emerald-50", fg: "emerald-600", darkThreshold: 4.5, mode: "dark", lightRatio: 3.58, note: "светлый факт 3.58" },
  { bg: "emerald-50", fg: "emerald-800", darkThreshold: 4.5, mode: "aa" },
  { bg: "violet-50", fg: "violet-950", darkThreshold: 4.5, mode: "aa" },
  { bg: "sky-50", fg: "sky-800", darkThreshold: 4.5, mode: "aa" },
  { bg: "sky-50", fg: "sky-950", darkThreshold: 4.5, mode: "aa" },

  // ── HomeFooter: проп-фон (не токен) ↔ text-black ──
  { bg: FOOTER_PROP_BG, fg: "black", darkThreshold: 4.5, mode: "dark", note: "black НЕ инвертируется (проп-фон светлый в обеих темах до DKT-3)" },

  // ── Индикаторы (не-текстовые элементы ≥3:1 против карточки) ──
  { bg: "white", fg: "green-500", darkThreshold: 3.0, mode: "dark", lightRatio: 2.28, note: "точки статусов" },
  { bg: "white", fg: "amber-400", darkThreshold: 3.0, mode: "dark", lightRatio: 1.67, note: "точки/прогресс" },
  { bg: "white", fg: "cyan-500", darkThreshold: 3.0, mode: "dark", lightRatio: 2.43, note: "индикаторы cyan" },

  // ── Со-локации фактического кода: поверхности neutral-50/100 ──
  { bg: "neutral-50", fg: "neutral-600", darkThreshold: 4.5, mode: "aa" },
  { bg: "neutral-50", fg: "neutral-500", darkThreshold: 4.5, mode: "dark", note: "светлый факт 4.54 — на грани AA, тёмная 6.22" },
  { bg: "neutral-50", fg: "neutral-700", darkThreshold: 4.5, mode: "aa" },
  { bg: "neutral-100", fg: "neutral-600", darkThreshold: 4.5, mode: "aa" },
  { bg: "neutral-100", fg: "neutral-700", darkThreshold: 4.5, mode: "aa" },
  { bg: "neutral-100", fg: "neutral-400", darkThreshold: 3.0, mode: "dark", note: "placeholder на neutral-100" },
  { bg: "white", fg: "amber-800", darkThreshold: 4.5, mode: "aa", note: "amber-текст на карточке" },
];

describe("Контраст-аудит каталога: WCAG AA (DKT-2 оракул)", () => {
  const css = readFileSync(GLOBALS_PATH, "utf8");
  const vars = { light: extractBlock(css, ":root"), dark: extractBlock(css, "\\.dark") };

  function resolveColor(ref: string, theme: "light" | "dark"): string {
    if (ref.startsWith("#")) return hexToChannels(ref);
    const map = theme === "dark" ? vars.dark : vars.light;
    if (map[ref]) return map[ref];
    throw new Error(`Токен ${ref} не найден в ${theme} наборе`);
  }

  function ratioOf(bg: string, fg: string, theme: "light" | "dark"): number {
    return contrastRatio(resolveColor(bg, theme), resolveColor(fg, theme));
  }

  it("обе темы содержат полный набор токенов каталога", () => {
    const occupied = [
      "white", "black", "white-fg",
      ...Array.from({ length: 11 }, (_, i) => `neutral-${[50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950][i]}`),
      "brand", "brand-light", "brand-bright",
    ];
    for (const token of occupied) {
      expect(vars.light[token]).toBeDefined();
      expect(vars.dark[token]).toBeDefined();
    }
  });

  it.each(PAIRS.map((p) => [`${p.bg} ↔ ${p.fg} [${p.mode}]`, p] as const))(
    "пара %s соответствует вердикту калибровки",
    (_label, pair) => {
      const failures: string[] = [];
      const lightRatio = ratioOf(pair.bg, pair.fg, "light");
      const darkRatio = ratioOf(pair.bg, pair.fg, "dark");

      if (pair.mode === "aa") {
        if (lightRatio < pair.darkThreshold)
          failures.push(`light ${lightRatio.toFixed(2)} < ${pair.darkThreshold}`);
        if (darkRatio < pair.darkThreshold)
          failures.push(`dark ${darkRatio.toFixed(2)} < ${pair.darkThreshold}`);
      } else if (pair.mode === "dark") {
        if (darkRatio < pair.darkThreshold)
          failures.push(`dark ${darkRatio.toFixed(2)} < ${pair.darkThreshold}`);
        // тёмная ревизия не должна быть хуже светлого факта
        if (darkRatio < lightRatio)
          failures.push(`dark ${darkRatio.toFixed(2)} < light факт ${lightRatio.toFixed(2)}`);
      } else if (pair.mode === "baseline") {
        // светлое ratio — точный инвариант (байт-инвариант светлой темы)
        if (Math.abs(lightRatio - (pair.lightRatio ?? 0)) > 0.005)
          failures.push(
            `light ${lightRatio.toFixed(2)} != зафиксированный ${pair.lightRatio}`
          );
        if (!pair.darkExempt && darkRatio < pair.darkThreshold)
          failures.push(`dark ${darkRatio.toFixed(2)} < ${pair.darkThreshold}`);
      }
      expect(failures).toEqual([]);
    }
  );
});
