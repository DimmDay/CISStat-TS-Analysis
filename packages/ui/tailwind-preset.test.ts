// packages/ui/tailwind-preset.test.ts
//
// Task DKT-1/DKT-2 — каталог-тест токенов тёмной темы (spec_dark_theme.md §8.1).
//
// Единственный источник перечня занятых шагов палитры — программный
// инвентарь rg (метод §2, тот же, что дал цифры инвентаризации).
// Тест утверждает:
//   (а) darkMode: "class" в пресете;
//   (б) каждый занятый шаг отображён на CSS-переменную в формате
//       rgb(var(--c-*) / <alpha-value>) — сохраняет ~150 слэш-модификаторов;
//   (в) :root-значения в globals.css равны текущим фактам светлой темы
//       (байт-инвариант светлой, §4.2);
//   (г) .dark-значения равны каталогу калибровки DKT-2 (фиксация вердикта);
//   (д) служебные правила: color-scheme, тёмный скроллбар feed-scroll,
//       приглушённые тени, бренд-текст (R-3) — присутствуют в globals.css.
//
// Значения — каналы RGB ("229 229 229"), формат var-троек (§4.1).

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import preset from "./tailwind-preset";

const GLOBALS_PATH = resolve(__dirname, "globals.css");
const globalsCss = readFileSync(GLOBALS_PATH, "utf8");

// ── Инвентарь занятых шагов (программный замер rg по main@3c034c5, DKT-2) ──

// Нейтральная рампа: заняты ВСЕ шаги 50..950 + white + black.
// black НЕ инвертируется (роль: текст/оверлеи на нетокенизированных
// поверхностях — подложка EventsLogDrawer; с DKT-5 футер HomeFooter
// токенизирован --c-footer-bg и выведен из роли black).
const NEUTRAL_STEPS = [
  "50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950",
] as const;

const LIGHT_FACTS: Record<string, string> = {
  white: "255 255 255",
  black: "0 0 0",
  "neutral-50": "250 250 250",   // #FAFAFA
  "neutral-100": "245 245 245",  // #F5F5F5
  "neutral-200": "229 229 229",  // #E5E5E5
  "neutral-300": "212 212 212",  // #D4D4D4
  "neutral-400": "163 163 163",  // #A3A3A3
  "neutral-500": "115 115 115",  // #737373
  "neutral-600": "82 82 82",     // #525252
  "neutral-700": "64 64 64",     // #404040
  "neutral-800": "38 38 38",     // #262626
  "neutral-900": "23 23 23",     // #171717
  "neutral-950": "10 10 10",     // #0A0A0A
  brand: "46 49 146",            // #2E3192
  "brand-light": "232 234 246",  // #E8EAF6
  "brand-bright": "46 49 146",   // НОВЫЙ (R-3): светлое == brand (байт-инвариант)
  footer: "91 91 91",            // #5B5B5B
  "footer-legal": "228 228 228", // #E4E4E4
  "green-50": "240 253 244",     // #F0FDF4
  "green-100": "220 252 231",    // #DCFCE7
  "green-200": "187 247 208",    // #BBF7D0
  "green-400": "74 222 128",     // #4ADE80
  "green-500": "34 197 94",      // #22C55E
  "green-600": "22 163 74",      // #16A34A
  "green-700": "21 128 61",      // #15803D
  "green-800": "22 101 52",      // #166534
  "amber-50": "255 251 235",     // #FFFBEB
  "amber-100": "254 243 199",    // #FEF3C7
  "amber-200": "253 230 138",    // #FDE68A
  "amber-300": "252 211 77",     // #FCD34D
  "amber-400": "251 191 36",     // #FBBF24
  "amber-600": "217 119 6",      // #D97706
  "amber-700": "180 83 9",       // #B45309
  "amber-800": "146 64 14",      // #92400E
  "amber-900": "120 53 15",      // #78350F
  "red-50": "254 242 242",       // #FEF2F2
  "red-100": "254 226 226",      // #FEE2E2
  "red-200": "254 202 202",      // #FECACA
  "red-300": "252 165 165",      // #FCA5A5
  "red-600": "220 38 38",        // #DC2626
  "red-700": "185 28 28",        // #B91C1C
  "red-800": "153 27 27",        // #991B1B
  "blue-50": "239 246 255",      // #EFF6FF
  "blue-200": "191 219 254",     // #BFDBFE
  "blue-300": "147 197 253",     // #93C5FD
  "blue-400": "96 165 250",      // #60A5FA
  "blue-600": "37 99 235",       // #2563EB
  "blue-700": "29 78 216",       // #1D4ED8
  "blue-800": "30 64 175",       // #1E40AF
  "blue-900": "30 58 138",       // #1E3A8A
  "emerald-50": "236 253 245",   // #ECFDF5
  "emerald-200": "167 243 208",  // #A7F3D0
  "emerald-600": "5 150 105",    // #059669
  "emerald-800": "6 95 70",      // #065F46
  "violet-50": "245 243 255",    // #F5F3FF
  "violet-200": "221 214 254",   // #DDD6FE
  "violet-950": "46 16 101",     // #2E1065
  "cyan-500": "6 182 212",       // #06B6D4
  "sky-50": "240 249 255",       // #F0F9FF
  "sky-100": "224 242 254",      // #E0F2FE
  "sky-200": "186 230 253",      // #BAE6FD
  "sky-800": "7 89 133",         // #075985
  "sky-950": "8 47 73",          // #082F49
  // Служебный токен text-white ревизии (§6.2): текст на заливках — белый
  // в ОБОИХ темах (классом не потребляется, только utility-ревизией ниже)
  "white-fg": "255 255 255",
};

// ── Каталог тёмной ревизии (вердикт калибровки DKT-2, аудит WCAG AA) ──
// Принцип §6.1: зеркальная смена ролей по уровням светлоты. Значения
// откалиброваны скриптом-оракулом scripts/task_dkt2/contrast_audit.py
// (отчёт: docs/task_dkt2_dark_catalog_calibration.md).
const DARK_CATALOG: Record<string, string> = {
  white: "22 23 28",          // #16171C карточки/шапки
  black: "0 0 0",             // НЕ инвертируется (оверлеи/проп-поверхности)
  "neutral-50": "28 29 35",       // #1C1D23 лёгкие поверхности
  "neutral-100": "36 37 44",      // #24252C бейджи/muted
  "neutral-200": "46 48 56",      // #2E3038 границы (основные)
  "neutral-300": "59 62 71",      // #3B3E47 границы (сильные)
  "neutral-400": "113 116 127",   // #71747F placeholder/disabled
  "neutral-500": "154 157 169",   // #9A9DA9 вторичный текст
  "neutral-600": "181 184 193",   // #B5B8C1 текст-2
  "neutral-700": "202 204 212",   // #CACCD4 текст-1
  "neutral-800": "227 229 234",   // #E3E5EA текст основной
  "neutral-900": "241 242 245",   // #F1F2F5 заголовки
  "neutral-950": "10 10 10",      // НЕ инвертируется — код-блок (§6.2)
  brand: "74 78 217",         // #4A4ED9 заливки (bg-brand + text-white ~5.5:1)
  "brand-light": "30 32 52",  // #1E2034 шапки карточек
  "brand-bright": "143 148 245", // #8F94F5 текст/линии бренда (~7:1)
  footer: "59 62 71",         // #3B3E47 (dormant-токен)
  "footer-legal": "46 48 56", // #2E3038 (dormant-токен)
  "green-50": "18 37 26",     // #12251A поверхность PASS
  "green-100": "23 48 31",    // #17301F
  "green-200": "42 82 64",    // #2A5240 границы
  "green-400": "74 222 128",  // индикаторы — без ревизии
  "green-500": "34 197 94",   // индикаторы — без ревизии
  "green-600": "52 211 153",  // #34D399 текст статуса
  "green-700": "74 222 128",  // #4ADE80 текст PASS (§6.3)
  "green-800": "134 239 172", // #86EFAC текст PASS усиленный
  "amber-50": "42 33 19",     // #2A2113 поверхность WARNING (§6.3)
  "amber-100": "56 46 24",    // #382E18
  "amber-200": "85 70 31",    // #55461F границы
  "amber-300": "252 211 77",  // индикаторы — без ревизии
  "amber-400": "251 191 36",  // индикаторы — без ревизии
  "amber-600": "252 211 77",  // #FCD34D текст статуса
  "amber-700": "251 191 36",  // #FBBF24 текст WARNING (§6.3)
  "amber-800": "253 230 138", // #FDE68A
  "amber-900": "254 243 199", // #FEF3C7
  "red-50": "42 20 20",       // #2A1414 поверхность FAIL (§6.3)
  "red-100": "51 26 26",      // #331A1A
  "red-200": "92 46 46",      // #5C2E2E границы
  "red-300": "127 67 67",     // #7F4343 границы
  "red-600": "248 113 113",   // #F87171 текст статуса (§6.3)
  "red-700": "252 165 165",   // #FCA5A5 текст FAIL усиленный
  "red-800": "254 202 202",   // #FECACA
  "blue-50": "19 28 43",      // #131C2B поверхность
  "blue-200": "44 61 87",     // #2C3D57 границы
  "blue-300": "147 197 253",  // индикаторы — без ревизии
  "blue-400": "96 165 250",   // индикаторы — без ревизии
  "blue-600": "96 165 250",   // #60A5FA текст; заливка bg-blue-600 не ревизируется
  "blue-700": "147 197 253",  // #93C5FD
  "blue-800": "191 219 254",  // #BFDBFE
  "blue-900": "219 234 254",  // #DBEAFE
  "emerald-50": "14 35 24",   // #0E2318 поверхность
  "emerald-200": "40 85 64",  // #285540 границы
  "emerald-600": "52 211 153",  // #34D399
  "emerald-800": "110 231 183", // #6EE7B7
  "violet-50": "29 23 48",    // #1D1730 поверхность
  "violet-200": "63 52 102",  // #3F3466 границы
  "violet-950": "196 181 253",  // #C4B5FD текст
  "cyan-500": "6 182 212",    // индикаторы — без ревизии
  "sky-50": "18 32 46",       // #12202E поверхность
  "sky-100": "23 40 54",      // #172836
  "sky-200": "39 69 92",      // #27455C границы
  "sky-800": "125 211 252",   // #7DD3FC текст
  "sky-950": "186 230 253",   // #BAE6FD текст
  // text-white ревизия: значение то же (находка аудита DKT-2, §6.2)
  "white-fg": "255 255 255",
};

// ── Извлечение var-троек из блока globals.css ──
function extractVarBlock(css: string, blockSelector: string): Record<string, string> {
  const vars: Record<string, string> = {};
  const blockRe = new RegExp(`${blockSelector}\\s*\\{([\\s\\S]*?)\\n\\}`, "m");
  const m = css.match(blockRe);
  if (!m) return vars;
  const varRe = /--c-([a-z0-9-]+)\s*:\s*([0-9 ]+);/g;
  let vm: RegExpExecArray | null;
  while ((vm = varRe.exec(m[1])) !== null) {
    vars[vm[1]] = vm[2].trim();
  }
  return vars;
}

// ── Обход палитры пресета: имя шага → ожидаемая var-тройка ──
interface PresetWalk {
  varMapped: Record<string, string>; // имя var (--c-*) → формат-строка
  unmapped: string[];                // занятые шаги, НЕ отображённые на var
}

function walkColors(colors: Record<string, unknown>, prefix = "", acc?: PresetWalk): PresetWalk {
  const walk = acc ?? { varMapped: {}, unmapped: [] };
  for (const [key, value] of Object.entries(colors)) {
    // Tailwind-конвенция: ключ DEFAULT внутри группы = цвет без суффикса
    // (brand.DEFAULT → "brand"), вложенные ключи — "brand-light" и т.п.
    const name = prefix ? (key === "DEFAULT" ? prefix : `${prefix}-${key}`) : key;
    if (typeof value === "string") {
      walk.varMapped[name] = value;
    } else if (value && typeof value === "object") {
      walkColors(value as Record<string, unknown>, name, walk);
    }
  }
  return walk;
}

describe("Tailwind preset: тёмная тема (DKT-1 фундамент)", () => {
  it("(а) переключает тёмную тему классом .dark на <html>", () => {
    expect((preset as { darkMode?: string }).darkMode).toBe("class");
  });
});

describe("Каталог-тест: занятые шаги отображены на var (§8.1а)", () => {
  const config = preset as {
    theme?: { extend?: { colors?: Record<string, unknown> } };
  };
  const colors = config.theme?.extend?.colors ?? {};
  const walk = walkColors(colors);

  it("каждый занятый шаг палитры имеет var-отображение формата rgb(var(--c-*) / <alpha-value>)", () => {
    // white-fg — служебный токен utility-ревизии text-white (§6.2):
    // классом не потребляется, в пресете не отображается
    const occupied = Object.keys(LIGHT_FACTS).filter((t) => t !== "white-fg");
    const missing: string[] = [];
    const badFormat: string[] = [];
    for (const step of occupied) {
      const value = walk.varMapped[step];
      if (value === undefined) {
        missing.push(step);
        continue;
      }
      const expected = `rgb(var(--c-${step}) / <alpha-value>)`;
      if (value !== expected) badFormat.push(`${step}: ${value}`);
    }
    expect(missing).toEqual([]);
    expect(badFormat).toEqual([]);
  });

  it("не-токенизированные служебные цвета отсутствуют (footer/legal — токены)", () => {
    // footer и footer-legal — токены пресета, обязаны остаться var-отображёнными
    expect(walk.varMapped.footer).toBe("rgb(var(--c-footer) / <alpha-value>)");
    expect(walk.varMapped["footer-legal"]).toBe(
      "rgb(var(--c-footer-legal) / <alpha-value>)"
    );
  });
});

describe("Каталог-тест: значения обеих тем в globals.css (§8.1б,в)", () => {
  const rootVars = extractVarBlock(globalsCss, ":root");
  const darkVars = extractVarBlock(globalsCss, "\\.dark");

  it(":root содержит var-тройки", () => {
    expect(Object.keys(rootVars).length).toBeGreaterThan(0);
  });

  it(":root-значения равны фактам светлой темы (байт-инвариант, §4.2)", () => {
    const diff: string[] = [];
    for (const [token, channels] of Object.entries(LIGHT_FACTS)) {
      if (rootVars[token] !== channels) {
        diff.push(`${token}: globals=${rootVars[token]} ожидается=${channels}`);
      }
    }
    expect(diff).toEqual([]);
  });

  it(".dark-блок присутствует и содержит var-тройки", () => {
    expect(globalsCss).toMatch(/(?:^|\n)\.dark\s*\{/);
    expect(Object.keys(darkVars).length).toBeGreaterThanOrEqual(
      Object.keys(LIGHT_FACTS).length
    );
  });

  it(".dark-значения равны каталогу калибровки DKT-2 (§8.1в)", () => {
    const diff: string[] = [];
    for (const [token, channels] of Object.entries(DARK_CATALOG)) {
      if (darkVars[token] !== channels) {
        diff.push(`${token}: globals=${darkVars[token]} ожидается=${channels}`);
      }
    }
    expect(diff).toEqual([]);
  });

  it(".dark инвертирует ровно занятые шаги и НЕ трогает исключения (§6.2)", () => {
    // neutral-950 (код-блок) и black (оверлеи/проп-поверхности) не инвертируются
    expect(darkVars["neutral-950"]).toBe(LIGHT_FACTS["neutral-950"]);
    expect(darkVars.black).toBe(LIGHT_FACTS.black);
  });
});

describe("Служебные правила globals.css (§4.2, §6.2)", () => {
  it("color-scheme переключается темой", () => {
    expect(globalsCss).toMatch(/:root\s*\{[^}]*color-scheme:\s*light/s);
    expect(globalsCss).toMatch(/\.dark\s*\{[^}]*color-scheme:\s*dark/s);
  });

  it("тёмная ревизия скроллбара feed-scroll присутствует", () => {
    expect(globalsCss).toMatch(/\.dark\s+\.feed-scroll\s*\{/);
  });

  it("тени приглушаются в тёмной теме без правки компонентов (§6.2)", () => {
    expect(globalsCss).toMatch(/\.dark\s+\.shadow-lg\s*\{/);
    expect(globalsCss).toMatch(/\.dark\s+\.shadow-xl\s*\{/);
    expect(globalsCss).toMatch(/\.dark\s+\.shadow-sm\s*\{/);
  });

  it("text-brand в тёмной теме получает бренд-bright (R-3, utility-ревизия)", () => {
    // 153 plain text-brand + 6 hover:text-brand: utility-ревизия на уровне
    // globals.css (механизм §6.2) вместо массового правки 48 файлов —
    // сохраняет аргумент «ноль правок в компонентах» (§3.3).
    expect(globalsCss).toMatch(/\.dark\s+\.text-brand\s*\{/);
    expect(globalsCss).toMatch(/\.dark\s+\.hover\\:text-brand:hover\s*\{/);
  });

  it("text-white остаётся белым на заливках (находка аудита DKT-2, §6.2)", () => {
    // 103 plain + 7 hover: + 2 group-hover: text-white — «текст на цветной
    // заливке», не поверхность: без ревизии инвертировался бы в #16171C
    // на bg-brand (2.88:1 — FAIL). Слэш-вариантов text-white/NN нет.
    expect(globalsCss).toMatch(/\.dark\s+\.text-white\s*\{[^}]*--c-white-fg/s);
    expect(globalsCss).toMatch(/\.dark\s+\.hover\\:text-white:hover\s*\{/);
    expect(globalsCss).toMatch(/\.dark\s+\.group:hover\s+\.group-hover\\:text-white\s*\{/);
  });
});
