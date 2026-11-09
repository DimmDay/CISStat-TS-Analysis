// apps/standalone/components/product-header-beta-chip.test.tsx
//
// Task UI-DEVNOTICE-1 (2026-11-09): чип «β» у бренда (дополнение к
// варианту A постановки тимлида) — постоянный статус-маркер рядом с
// «CISStat DataTime Lab» внутри ссылки бренда.
//
// Гвардейлы постановки: чип не меняет доступное имя ссылки бренда
// (aria-label остаётся «CISStat DataTime Lab — на главную», паттерн
// BRND-2), не сдвигает геометрию шапки (ряд items-center сохранён,
// высота чипа меньше h-7 строки), tooltip объясняет статус, для
// скринридеров даётся текстовое «бета-версия». Токены DKT: bg-brand-light/40
// + text-brand (тёмные значения подставляются платформенным контрактом
// «имена классов не меняются — меняются значения»), произвольных цветов нет.
//
// Корпус дизъюнктен ProductHeader.test.tsx / brand-rename.test.tsx /
// product-header-nav-slogan.test.tsx.

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { ProductHeader } from "./ProductHeader";

const BRAND_LINK_NAME = "CISStat DataTime Lab — на главную";

describe("UI-DEVNOTICE-1: чип β у бренда", () => {
  it("чип β находится внутри ссылки бренда, рядом с названием", () => {
    render(<ProductHeader />);
    const chip = screen.getByTestId("product-beta-chip");
    const brandLink = screen.getByRole("link", { name: BRAND_LINK_NAME });
    expect(chip.closest("a")).toBe(brandLink);
  });

  it("чип виден сразу (не dismissible): статус присутствует при каждом рендере", () => {
    render(<ProductHeader />);
    expect(screen.getByTestId("product-beta-chip")).toHaveTextContent("β");
  });

  it("тултип объясняет статус: «Платформа в активной разработке»", () => {
    render(<ProductHeader />);
    expect(screen.getByTestId("product-beta-chip")).toHaveAttribute(
      "title",
      "Платформа в активной разработке"
    );
  });

  it("для скринридеров чип читается как «бета-версия» (sr-only внутри)", () => {
    render(<ProductHeader />);
    const chip = screen.getByTestId("product-beta-chip");
    expect(chip.querySelector(".sr-only")).toHaveTextContent("бета-версия");
  });

  it("доступное имя ссылки бренда НЕ загрязнено чипом (паттерн BRND-2)", () => {
    render(<ProductHeader />);
    const link = screen.getByRole("link", { name: BRAND_LINK_NAME });
    expect(link).toHaveAttribute("href", "https://ts-standalone.vercel.app/");
  });

  it("чип на токенах DKT: bg-brand-light/40 + text-brand, без произвольных цветов", () => {
    render(<ProductHeader />);
    const chip = screen.getByTestId("product-beta-chip");
    expect(chip).toHaveClass("bg-brand-light/40");
    expect(chip).toHaveClass("text-brand");
    expect(chip.className).not.toContain("#");
  });

  it("чип не меняет геометрию строки шапки: меньше высоты h-7 (28px)", () => {
    render(<ProductHeader />);
    const chip = screen.getByTestId("product-beta-chip");
    // text-[11px] + py-[3px] ≈ 17px — меньше 28px строки, ряд items-center
    // остаётся обусловленным логотипом/брендом/кнопками.
    expect(chip).toHaveClass("text-[11px]");
    expect(chip).toHaveClass("leading-none");
  });
});
