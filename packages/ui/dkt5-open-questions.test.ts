// packages/ui/dkt5-open-questions.test.ts
//
// Task DKT-5 — фиксация решений по открытым вопросам §10 спеки
// spec_dark_theme.md (команда тимлида 2026-09-18: «DKT-5 и открытые
// §10.1/§10.5/§10.6»). Реализации соответствуют рекомендациям спеки и
// действуют с DKT-1/DKT-3; сюита — ГВАРДЫ-ФИКСАЦИИ: пинят вердикты,
// детектируя регрессию (появление next-themes, глобального transition
// или темозависимого PNG-экспорта — RED).
//
//  - §10.1 PNG-экспорт — «всегда светлый» печатный артефакт: резолв
//    var() из светлой карты (--chart-*/--status-*/--wave-* :root) в клоне
//    SVG до сериализации + canvas-заливка #FFFFFF независимо от темы
//    (реализовано DKT-3, lib/chartVars.ts; юниты резолва —
//    ForecastExportMenu.vars.test.ts);
//  - §10.5 провайдер — hand-rolled ~50 строк ThemeContext (DKT-1,
//    прецедент NAVSTG-2), БЕЗ зависимости next-themes; контракт §5
//    (ключ localStorage, класс .dark, порядок init) от библиотеки не
//    зависит;
//  - §10.6 анимация перехода — БЕЗ глобального transition: смена темы
//    мгновенная (дешевле, без миганий при гидратации; R-4 no-FOUC не
//    соревнуется с анимацией). Точечные transition-классы компонентов
//    (интерактив) не запрещены — запрещена глобальная тема-анимация.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const UI_ROOT = __dirname;
const MONOREPO = resolve(UI_ROOT, "..", "..");

const GLOBALS = readFileSync(resolve(UI_ROOT, "globals.css"), "utf8");
const THEME_CONTEXT = readFileSync(
  resolve(UI_ROOT, "context", "ThemeContext.tsx"),
  "utf8",
);
const EXPORT_MENU = readFileSync(
  resolve(UI_ROOT, "components", "ForecastExportMenu.tsx"),
  "utf8",
);
const CHART_VARS = readFileSync(
  resolve(UI_ROOT, "lib", "chartVars.ts"),
  "utf8",
);

describe("DKT-5 §10.1 (решено): PNG-экспорт — «всегда светлый» артефакт", () => {
  it("экспорт резолвит var() светлой картой в клоне SVG до сериализации", () => {
    expect(EXPORT_MENU).toContain("resolveSvgVarsLight(clone)");
  });

  it("canvas-заливка — фиксированный белый (#FFFFFF), от темы не зависит", () => {
    expect(EXPORT_MENU).toMatch(/context\.fillStyle\s*=\s*"#FFFFFF"/);
  });

  it("светлая карта chartVars — зеркало :root globals.css (источник значений)", () => {
    const block = GLOBALS.match(/:root\s*\{([\s\S]*?)\n\}/)![1];
    const declared = new Map<string, string>();
    for (const m of block.matchAll(
      /--((?:chart|status|wave)-[a-z0-9-]+)\s*:\s*(#[0-9A-Fa-f]{6})/g,
    )) {
      declared.set(m[1], m[2]);
    }
    expect(declared.size).toBeGreaterThan(0);
    for (const [name, hex] of declared) {
      expect(CHART_VARS).toContain(`"${name}": "${hex.toUpperCase()}"`);
    }
  });
});

describe("DKT-5 §10.5 (решено): провайдер — hand-rolled, без next-themes", () => {
  const PACKAGE_JSONS = [
    resolve(MONOREPO, "package.json"),
    resolve(MONOREPO, "packages", "ui", "package.json"),
    resolve(MONOREPO, "apps", "standalone", "package.json"),
    resolve(MONOREPO, "apps", "embedded", "package.json"),
  ];

  it("hand-rolled провайдер существует (packages/ui/context/ThemeContext.tsx)", () => {
    expect(THEME_CONTEXT).toContain("ThemeProvider");
    expect(THEME_CONTEXT).toContain("resolveInitialTheme");
  });

  it.each(PACKAGE_JSONS)("next-themes отсутствует в %s", (pkgPath) => {
    const pkg = JSON.parse(readFileSync(pkgPath, "utf8"));
    const deps = {
      ...pkg.dependencies,
      ...pkg.devDependencies,
      ...pkg.peerDependencies,
    };
    expect(Object.keys(deps)).not.toContain("next-themes");
  });

  it("контракт темы §5 зафиксирован в провайдере (ключ cisstat-theme, точное значение)", () => {
    // DKT-CERT (мутация M4): substring "cisstat-theme" — слабый оракул,
    // проходит и на мутанте "cisstat-theme-mutated"; юнит-тесты тавтологичны
    // (пишут и читают через одну константу). Пиним присвоение точного
    // значения ключа контракта.
    expect(THEME_CONTEXT).toContain('THEME_STORAGE_KEY = "cisstat-theme"');
  });
});

describe("DKT-5 §10.6 (решено): смена темы — без глобального transition", () => {
  it("globals.css не содержит transition-деклараций (глобальной анимации темы нет)", () => {
    expect(GLOBALS).not.toMatch(/transition\s*:/);
  });

  it("провайдер не внедряет глобальную анимацию смены темы", () => {
    expect(THEME_CONTEXT).not.toMatch(/transition/i);
  });
});
