// packages/ui/components/EducationPageBackground.test.tsx
//
// Контракт фоновой коробки страницы «Обучение и база знаний» /education
// (постановка тимлида 2026-09-21): сплошной фон #EFF6FD по паттерну
// главной страницы — отрицательная верхняя граница и скругление углов
// живут на обёртке страницы (apps/standalone/app/education/page.tsx),
// здесь проверяется сама коробка: absolute inset-0 -z-10, rounded-2xl,
// aria-hidden, pointer-events-none (паттерн HomeWavesBackground /
// NavigatorWavesBackground).
//
// Цвет — НЕ литерал, а токен --wave-home-2 палитры волн главной:
//   :root = #EFF6FD — байт-точно значение постановки;
//   .dark = #17212C — сертифицированная тёмная ревизия (DKT-CERT),
//           коробка не всплывает ярким пятном на тёмной странице
//           (практика DKT-5 «футер тоже конвертируем» — без заведения
//           нового токена).
// Governance: quoted-hex в компонентах запрещён (DKT-3), произвольные
// цветовые классы требуют .dark-ревизии (DKT-2R) — var() соблюдает
// оба инварианта и переиспользует сертифицированную пару значений.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render } from "@testing-library/react";
import "@testing-library/jest-dom";
import { EducationPageBackground } from "./EducationPageBackground";

const GLOBALS = readFileSync(resolve(__dirname, "..", "globals.css"), "utf8");

describe("EducationPageBackground", () => {
  it("является чисто декоративным слоем: aria-hidden и не перехватывает клики", () => {
    const { container } = render(<EducationPageBackground />);
    const root = container.firstElementChild;

    expect(root).toHaveAttribute("aria-hidden", "true");
    expect(root?.className).toContain("pointer-events-none");
  });

  it("спозиционирован абсолютно позади контента (absolute inset-0 -z-10), не fixed к вьюпорту", () => {
    const { container } = render(<EducationPageBackground />);
    const root = container.firstElementChild;

    expect(root?.className).toContain("absolute");
    expect(root?.className).toContain("inset-0");
    expect(root?.className).toContain("-z-10");
    expect(root?.className).not.toMatch(/\bfixed\b/);
  });

  it("углы скруглены по паттерну фоновой коробки главной (rounded-2xl)", () => {
    const { container } = render(<EducationPageBackground />);
    const root = container.firstElementChild;

    expect(root?.className).toContain("rounded-2xl");
  });

  it("фон — токен var(--wave-home-2), без hex-литерала в инлайн-стиле", () => {
    const { container } = render(<EducationPageBackground />);
    const root = container.firstElementChild as HTMLElement;
    const style = root.getAttribute("style") ?? "";

    expect(style).toContain("var(--wave-home-2)");
    expect(style).not.toMatch(/#[0-9A-Fa-f]{6}/);
  });

  it("пин постановки: :root --wave-home-2 == #EFF6FD; .dark-ревизия == #17212C (DKT-CERT)", () => {
    const lightPin = GLOBALS.match(/--wave-home-2:\s*(#[0-9A-Fa-f]{6})\s*;/);
    const darkIdx = GLOBALS.indexOf("\n.dark");
    const darkPin = GLOBALS
      .slice(darkIdx)
      .match(/--wave-home-2:\s*(#[0-9A-Fa-f]{6})\s*;/);

    expect(lightPin?.[1]?.toUpperCase()).toBe("#EFF6FD");
    expect(darkPin?.[1]?.toUpperCase()).toBe("#17212C");
  });
});
