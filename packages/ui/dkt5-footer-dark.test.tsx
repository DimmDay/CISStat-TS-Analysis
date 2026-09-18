// packages/ui/dkt5-footer-dark.test.tsx
//
// Task DKT-5 — футер в тёмной теме (отложенный пункт DKT-4; команда
// тимлида 2026-09-18: «Футер тоже конвертируем в тёмную тему»).
//
// Контракт конверсии (Вариант C §3.3 + прецеденты §6.2):
//  - фон футера токенизируется: --c-footer-bg (светлый == литерал
//    #CAD7F7 — байт-инвариант светлой темы; тёмная ревизия #171D2C —
//    hue 223° волновой семьи футера, --wave-home-9 #C7D5F7 / --wave-nav-15
//    #C8D7F8 ↔ тёмные #171D2C по тому же hue-сохранному преобразованию,
//    что DKT-3);
//  - классы компонентов НЕ меняются: black-семейство футера (text-black,
//    text-black/50, text-black/40, border-black/20, decoration-black/30)
//    ревизируется scoped-правилами .dark .home-footer (§6.2 — тот же
//    механизм, что .dark .text-brand / .dark .text-[#1e3a8a]); значения —
//    ссылки на токен neutral-900 (заголовки, #F1F2F5 в тёмной), альфы —
//    с теми же коэффициентами;
//  - форма поиска bg-white/40: в светлой теме поверхность ВОЗВЫШЕНА над
//    футером (белое поверх #CAD7F7) — зеркало сохраняется литералом
//    rgb(255 255 255 / 0.07) (токен white в тёмной инвертируется в
//    поверхность #16171C и elevation перевернул бы роль);
//  - явный проп backgroundColor сохраняет контракт «фон — свой для
//    каждой страницы»: точный цвет в обеих темах (ответственность
//    вызывающего); без пропа — тематический var();
//  - оракул контраста: тёмные пары blended-альф ≥ AA/декоративные
//    пороги (независимая реализация формул WCAG 2.1 — культура
//    перекрёстной проверки dark-catalog-contrast.test.ts).

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render } from "@testing-library/react";
import { HomeFooter } from "./components/HomeFooter";
import { FOOTER_HOME_BACKGROUND_COLOR } from "./lib/homeFooter";

const GLOBALS = readFileSync(resolve(__dirname, "globals.css"), "utf8");
const ROOT_BLOCK = GLOBALS.match(/:root\s*\{([\s\S]*?)\n\}/)![1];
const DARK_BLOCK = GLOBALS.match(/\.dark\s*\{([\s\S]*?)\n\}/)![1];

describe("DKT-5: футер — токен --c-footer-bg", () => {
  it("токен объявлен симметрично в :root и .dark (паритет каталога)", () => {
    expect(ROOT_BLOCK).toMatch(/--c-footer-bg:\s*[0-9 ]+;/);
    expect(DARK_BLOCK).toMatch(/--c-footer-bg:\s*[0-9 ]+;/);
  });

  it("светлое значение — байт-инвариант #CAD7F7 (== FOOTER_HOME_BACKGROUND_COLOR)", () => {
    const light = ROOT_BLOCK.match(/--c-footer-bg:\s*([0-9 ]+);/)![1].trim();
    // #CAD7F7 === rgb(202, 215, 247)
    expect(light).toBe("202 215 247");
    expect(FOOTER_HOME_BACKGROUND_COLOR).toBe("#CAD7F7");
  });

  it("тёмная ревизия зафиксирована: #171D2C (hue 223° — семья волн футера)", () => {
    const dark = DARK_BLOCK.match(/--c-footer-bg:\s*([0-9 ]+);/)![1].trim();
    // #171D2C === rgb(23, 29, 44)
    expect(dark).toBe("23 29 44");
  });
});

describe("DKT-5: utility-ревизия .dark .home-footer (§6.2, классы не меняются)", () => {
  it("текст футера text-black → neutral-900 (каталог «заголовки»)", () => {
    expect(GLOBALS).toMatch(
      /\.dark \.home-footer \.text-black\s*\{[^}]*color:\s*rgb\(var\(--c-neutral-900\)\)/,
    );
  });

  it("альфы текста /50 и /40 ревизируются в neutral-900 с теми же коэффициентами", () => {
    expect(GLOBALS).toMatch(
      /\.dark \.home-footer \.text-black\\\/50\s*\{[^}]*rgb\(var\(--c-neutral-900\) \/ 0\.5\)/,
    );
    expect(GLOBALS).toMatch(
      /\.dark \.home-footer \.text-black\\\/40\s*\{[^}]*rgb\(var\(--c-neutral-900\) \/ 0\.4\)/,
    );
  });

  it("граница /20 и подчёркивание /30 ревизируются в neutral-900-альфы", () => {
    expect(GLOBALS).toMatch(
      /\.dark \.home-footer \.border-black\\\/20\s*\{[^}]*rgb\(var\(--c-neutral-900\) \/ 0\.2\)/,
    );
    expect(GLOBALS).toMatch(
      /\.dark \.home-footer \.decoration-black\\\/30\s*\{[^}]*text-decoration-color:\s*rgb\(var\(--c-neutral-900\) \/ 0\.3\)/,
    );
  });

  it("форма поиска bg-white/40: возвышение поверхности сохраняется (white 0.07)", () => {
    expect(GLOBALS).toMatch(
      /\.dark \.home-footer \.bg-white\\\/40\s*\{[^}]*rgb\(255 255 255 \/ 0\.07\)/,
    );
  });
});

describe("DKT-5: HomeFooter — тематический фон по умолчанию", () => {
  it("корень несёт маркер-класс home-footer (хук тёмной ревизии)", () => {
    const { container } = render(<HomeFooter />);
    const footer = container.querySelector("footer")!;
    expect(footer.className).toContain("home-footer");
  });

  it("без пропа фон = var(--c-footer-bg) (тема-зависимый)", () => {
    const { container } = render(<HomeFooter />);
    const footer = container.querySelector("footer")!;
    // cssstyle может не парсить var() в CSSOM-свойстве — проверяем атрибут style
    expect(footer.getAttribute("style") ?? "").toContain("var(--c-footer-bg)");
  });

  it("явный проп — точный цвет (контракт «свой фон на каждой странице» сохранён)", () => {
    const { container } = render(<HomeFooter backgroundColor="#FFEEDD" />);
    const footer = container.querySelector("footer")!;
    // jsdom нормализует hex к rgb(...); #FFEEDD === rgb(255, 238, 221)
    expect(footer.style.backgroundColor).toBe("rgb(255, 238, 221)");
  });
});

describe("DKT-5: контраст тёмной ревизии футера (оракул WCAG 2.1)", () => {
  function luminance([r, g, b]: [number, number, number]): number {
    const f = (c: number) => {
      const s = c / 255;
      return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  }

  function ratio(a: [number, number, number], b: [number, number, number]): number {
    const la = luminance(a);
    const lb = luminance(b);
    const [hi, lo] = la >= lb ? [la, lb] : [lb, la];
    return (hi + 0.05) / (lo + 0.05);
  }

  /** Альфа-композитинг fg поверх bg (для ревизий с /NN-коэффициентами). */
  function blend(
    fg: [number, number, number],
    alpha: number,
    bg: [number, number, number],
  ): [number, number, number] {
    return [
      alpha * fg[0] + (1 - alpha) * bg[0],
      alpha * fg[1] + (1 - alpha) * bg[1],
      alpha * fg[2] + (1 - alpha) * bg[2],
    ];
  }

  const BG: [number, number, number] = [23, 29, 44]; // #171D2C --c-footer-bg (.dark)
  const FG: [number, number, number] = [241, 242, 245]; // neutral-900 (.dark, #F1F2F5)

  it("текст футера на тёмной поверхности ≥ 4.5 (AA)", () => {
    expect(ratio(FG, BG)).toBeGreaterThanOrEqual(4.5);
  });

  it("blended-альфы ревизии держат свои пороги (текст/графика/декор)", () => {
    // placeholder:text-black/50 → текст input: AA 4.5
    expect(ratio(blend(FG, 0.5, BG), BG)).toBeGreaterThanOrEqual(4.5);
    // иконки поиска text-black/40 → не-текстовая графика: 3.0
    expect(ratio(blend(FG, 0.4, BG), BG)).toBeGreaterThanOrEqual(3.0);
    // подчёркивание legal decoration-black/30 → декоративный повтор
    // семантики (ссылка уже видна текстом): ≥ 2.0
    expect(ratio(blend(FG, 0.3, BG), BG)).toBeGreaterThanOrEqual(2.0);
    // разделитель border-black/20 → декоративная черта: ≥ 1.5
    expect(ratio(blend(FG, 0.2, BG), BG)).toBeGreaterThanOrEqual(1.5);
    // фон формы (elevation white 0.07): различимость поверхности ≥ 1.15
    expect(ratio(blend([255, 255, 255], 0.07, BG), BG)).toBeGreaterThanOrEqual(1.15);
  });
});
