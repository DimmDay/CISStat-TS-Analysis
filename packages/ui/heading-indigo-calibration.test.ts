// packages/ui/heading-indigo-calibration.test.ts
//
// Task DKT-2R — калибровка индиго-заголовков (решение тимлида 2026-09-18,
// spec_dark_theme.md §10 фиксация).
//
// ТРЕБОВАНИЕ ТИМЛИДА: «все Заголовки и Подзаголовки цвета индиго должны
// быть в тёмной теме такого же цвета, как цвет логотипа — CISStat TS
// Analysis».
//
// Факты (отчёт DKT-2 §7, docs/task_dkt2_logo_audit.json):
//  - логотип = индиго-поле #2E3192 (hue 237°) + белое содержимое;
//  - literal #2E3192 на тёмной поверхности = 1.68:1 — ниже AA, поэтому
//    тёмная калибровка бренда = токен brand-bright #8F94F5 (тот же hue
//    237°, ≥ 4.5:1 на всех тёмных поверхностях; прецедент text-brand
//    DKT-2 §3).
//
// Инвентарь (программный скан, произвольные hex-классы текста): ровно
// 11 инстансов text-[#1e3a8a] в 5 файлах — hero-заголовки (h1/h2) и
// подзаголовки (p) home / navigator / tasks / platform-introduction /
// tasks-causes (TasksCauses добавлен срезом TSKV2-1, тот же hero-паттерн,
// тёмная ревизия общая — класс-уровневая).
// Это единственные произвольные цветовые классы платформы — тест
// инвентаря запрещает появление новых без тёмной ревизии.
//
// Механизм — utility-ревизия §6.2 (прецеденты text-brand/text-white):
// компоненты не правятся (ноль правок, §3.3), светлая тема —
// байт-инвариант.

import { readFileSync, readdirSync, statSync } from "node:fs";
import { resolve, join } from "node:path";

const UI_ROOT = resolve(__dirname, "..");
const GLOBALS = readFileSync(resolve(__dirname, "globals.css"), "utf8");

/** Произвольные цветовые классы, разрешённые без отдельной ревизии. */
const ARBITRARY_COLOR_WHITELIST = new Set<string>([]);

const HERO_FILES = [
  "packages/ui/components/HomeHero.tsx",
  "packages/ui/components/NavigatorHero.tsx",
  "packages/ui/components/TasksHub.tsx",
  "packages/ui/components/PlatformIntroduction.tsx",
  "packages/ui/components/TasksCauses.tsx",
] as const;

const HERO_CLASS = "text-[#1e3a8a]";
const HERO_INSTANCES_TOTAL = 11; // 2 + 4 + 2 + 1 + 2 (TasksCauses — TSKV2-1,
// hero-паттерн TasksHub: h1 + p-подзаголовок; тёмная ревизия класс-уровневая,
// та же utility-ревизия §6.2 — отдельных правок не требует)

// ── инфраструктура (те же примитивы, что в dark-catalog-contrast.test.ts) ──

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

const LIGHT_VARS = extractBlock(GLOBALS, ":root");
const DARK_VARS = extractBlock(GLOBALS, "\\.dark");

function walkTsx(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) {
      if (name === "node_modules" || name === "__tests__") continue;
      walkTsx(full, out);
    } else if ((name.endsWith(".tsx") || name.endsWith(".ts")) && !name.includes(".test.")) {
      out.push(full);
    }
  }
  return out;
}

/** Экранирование класса для CSS-селектора: text-[#1e3a8a] → text-\[\#1e3a8a\]. */
function cssEscape(cls: string): string {
  return cls.replace(/[[\]#]/g, (m) => "\\" + m);
}

const ARBITRARY_COLOR_RE =
  /\b(?:text|bg|border|fill|stroke|from|to|via|ring)-\[#[0-9A-Fa-f]{3,8}\]/g;

// ── 1. Инвентарь произвольных цветовых классов ──

describe("DKT-2R: инвентарь произвольных цветовых классов", () => {
  const roots = [
    resolve(__dirname, "components"),
    resolve(__dirname, "..", "..", "apps", "standalone"),
    resolve(__dirname, "..", "..", "apps", "embedded"),
  ];

  const found = new Map<string, string[]>();
  for (const root of roots) {
    for (const file of walkTsx(root)) {
      const src = readFileSync(file, "utf8");
      for (const m of src.matchAll(ARBITRARY_COLOR_RE)) {
        const cls = m[0];
        // Платформо-независимый rel: нормализация разделителей win32 →
        // POSIX (на Windows slice оставлял backslash, endsWith с
        // POSIX-путями HERO_FILES не срабатывал — ложный отказ инвентаря).
        const posix = file.replace(/\\/g, "/");
        const rel = posix.slice(posix.indexOf("packages") !== -1 ? posix.indexOf("packages") : posix.indexOf("apps"));
        if (!found.has(cls)) found.set(cls, []);
        found.get(cls)!.push(rel);
      }
    }
  }

  it("каждый произвольный цветовой класс имеет тёмную ревизию .dark в globals.css", () => {
    const missing: string[] = [];
    for (const cls of found.keys()) {
      if (ARBITRARY_COLOR_WHITELIST.has(cls)) continue;
      const selector = `.dark .${cssEscape(cls)}`;
      if (!GLOBALS.includes(selector)) missing.push(`${cls} (селектор ${selector})`);
    }
    expect(missing).toEqual([]);
  });

  it("инвентарь hero-заголовков зафиксирован: 11 инстансов text-[#1e3a8a] в 5 файлах", () => {
    const perFile = found.get(HERO_CLASS) ?? [];
    expect(perFile).toHaveLength(HERO_INSTANCES_TOTAL);
    for (const rel of HERO_FILES) {
      expect(perFile.some((f) => f.endsWith(rel))).toBe(true);
    }
  });
});

// ── 2. Тёмная ревизия: hero-индиго → brand-bright (цвет логотипа) ──

describe("DKT-2R: тёмная ревизия индиго-заголовков", () => {
  it("utility-ревизия .dark .text-[#1e3a8a] → brand-bright присутствует", () => {
    const selector = `.dark .${cssEscape(HERO_CLASS)}`;
    const idx = GLOBALS.indexOf(selector);
    expect(idx).toBeGreaterThan(-1);
    const rule = GLOBALS.slice(idx, GLOBALS.indexOf("}", idx) + 1);
    expect(rule).toContain("rgb(var(--c-brand-bright))");
  });

  it("brand-bright в тёмной теме проходит AA 4.5:1 против страницы и карточки", () => {
    const bright = DARK_VARS["brand-bright"];
    expect(bright).toBe("143 148 245"); // #8F94F5 — калибровка бренда
    const pageDark = hexToChannels("0B0C10"); // фон страницы (каталог §6.1; body-токен — DKT-4)
    const cardDark = DARK_VARS["white"]; // карточки #16171C
    expect(contrastRatio(bright, pageDark)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(bright, cardDark)).toBeGreaterThanOrEqual(4.5);
  });

  it("hue тёмной калибровки совпадает с hue логотипа (237°) — «цвет логотипа», а не другой тон", () => {
    const [r, g, b] = channelsToRgb(DARK_VARS["brand-bright"]);
    const [lr, lg, lb] = channelsToRgb(LIGHT_VARS["brand"]); // #2E3192 логотипа
    const hue = (r: number, g: number, b: number): number => {
      const max = Math.max(r, g, b) / 255, min = Math.min(r, g, b) / 255;
      const d = max - min;
      if (d === 0) return 0;
      const rn = r / 255, gn = g / 255, bn = b / 255;
      let h: number;
      if (max === rn) h = ((gn - bn) / d) % 6;
      else if (max === gn) h = (bn - rn) / d + 2;
      else h = (rn - gn) / d + 4;
      return (h * 60 + 360) % 360;
    };
    // Допуск ±2°: квантование 8-битных каналов даёт ~±1.2° на этом диапазоне
    expect(Math.abs(hue(r, g, b) - hue(lr, lg, lb))).toBeLessThanOrEqual(2);
  });
});

// ── 3. Светлая тема — байт-инвариант ──

describe("DKT-2R: светлая тема не тронута", () => {
  it("ревизия существует только в области .dark — без нескопированного правила", () => {
    // Селектор без префикса .dark запрещён (иначе изменились бы светлые пиксели).
    const unscoped = new RegExp(`(?<!\\.dark )\\.${cssEscape(HERO_CLASS)}\\s*\\{`, "g");
    // убираем все .dark-вхождения, ищем оставшиеся
    const withoutDark = GLOBALS.replace(/\.dark \.[^{]+\{/g, "");
    expect(withoutDark.includes(`.${cssEscape(HERO_CLASS)}`)).toBe(false);
    expect(unscoped.test(GLOBALS)).toBe(false);
  });

  it("светлый brand-bright == бренд логотипа #2E3192 (инвариант DKT-2)", () => {
    expect(LIGHT_VARS["brand-bright"]).toBe("46 49 146");
  });
});
