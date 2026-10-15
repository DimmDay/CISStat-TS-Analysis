// apps/standalone/components/brand-rename.test.tsx
//
// Task UI-HOME-BRAND-1 (2026-10-15) — главное меню ProductHeader + title
// вкладки браузера:
//
//   1. Название бренда «CISStat TS Analysis» заменено на «CISStat
//      DataTime Lab»: текст <strong> в шапке, alt логотипа и доступное
//      имя ссылки бренда («CISStat DataTime Lab — на главная») — все три
//      поверхности бренда меняются СИНХРОННО (паттерн BRND-2: доступное
//      имя ссылки обязано совпадать с видимым текстом бренда, alt —
//      текстовая альтернатива той же сущности).
//   2. Title вкладки браузера рядом с фавиконом: metadata.title
//      apps/standalone/app/layout.tsx = «CISStat DataTime Lab» (favicon
//      /logo_TS.png правкой НЕ затронут).
//
// Корпус дизъюнктен существующим сюитам: проверяется точный новый текст
// «CISStat DataTime Lab» и отрицательный инвариант «старое название
// отсутствует» — легаси-пины ProductHeader.test.tsx /
// product-header-nav-slogan.test.tsx / layout.test.tsx переписаны на
// новый контракт синхронно (практика UI-VALIDATION-HDR-1 / UI-EDA-HDR-1).
//
// Вид бренда НЕ менялся (изменена только строка-название): typography-
// инварианты BRND-1/BRND-2 (text-[20px] leading-none font-normal
// tracking-tight text-brand) пинятся как «как было», чтобы переименование
// не притащило за собой случайную смену вида.

jest.mock("next/font/google", () => ({
  Inter: () => ({ variable: "--font-sans-mock", style: { fontFamily: "mock" } }),
}));

import { render, screen } from "@testing-library/react";
import { ProductHeader } from "./ProductHeader";
import { metadata } from "../app/layout";

const NEW_BRAND = "CISStat DataTime Lab";
const OLD_BRAND = "CISStat TS Analysis";

function renderHeader() {
  return render(<ProductHeader />);
}

describe("UI-HOME-BRAND-1: переименование бренда в ProductHeader", () => {
  it("текст бренда в шапке — «CISStat DataTime Lab» (strong); старое название отсутствует", () => {
    renderHeader();

    const brand = screen.getByText(NEW_BRAND, { selector: "strong" });
    expect(brand).toBeInTheDocument();

    // Старое название бренда нигде в шапке не осталось.
    expect(screen.queryByText(OLD_BRAND, { selector: "strong" })).toBeNull();
  });

  it("alt логотипа — «CISStat DataTime Lab» (синхронно с видимым названием)", () => {
    renderHeader();

    const logo = screen.getByAltText(NEW_BRAND);
    expect(logo).toBeInTheDocument();
    expect(screen.queryByAltText(OLD_BRAND)).toBeNull();
  });

  it("доступное имя ссылки бренда — «CISStat DataTime Lab — на главная» (паттерн BRND-2)", () => {
    renderHeader();

    const link = screen.getByRole("link", { name: `${NEW_BRAND} — на главную` });
    expect(link).toHaveAttribute("href", "https://ts-standalone.vercel.app/");

    // Логотип и текст бренда внутри той же ссылки (BRND-2 не тронут).
    const logo = screen.getByAltText(NEW_BRAND);
    const brand = screen.getByText(NEW_BRAND, { selector: "strong" });
    expect(logo.closest("a")).toBe(link);
    expect(brand.closest("a")).toBe(link);
  });

  it("вид бренда НЕ менялся: typography-инварианты BRND-1/BRND-2 сохранены", () => {
    renderHeader();

    const brand = screen.getByText(NEW_BRAND, { selector: "strong" });

    for (const cls of ["text-[20px]", "leading-none", "font-normal", "tracking-tight", "text-brand"]) {
      expect(brand).toHaveClass(cls);
    }
    expect(brand).not.toHaveClass("font-bold");
    expect(brand).not.toHaveClass("font-semibold");
  });

  it("остальные элементы шапки не затронуты: слоган, меню, РУС / ENG, кабинет", () => {
    renderHeader();

    // Слоган с прежним точным текстом (UI-HOME-HEADER-1).
    expect(
      screen.getByText("Цифровая научно-исследовательская лаборатория анализа данных")
    ).toBeInTheDocument();

    // Пункты меню и «РУС / ENG» — без изменений.
    expect(screen.getByRole("link", { name: "Обучение" })).toHaveAttribute("href", "/education");
    expect(screen.getByRole("link", { name: "Документация API" })).toHaveAttribute("href", "/docs");
    expect(screen.getByRole("link", { name: "Тарифы" })).toHaveAttribute("href", "/pricing");
    expect(screen.getByRole("link", { name: "Личный кабинет" })).toHaveAttribute("href", "/dashboard");
    expect(screen.getByText("РУС / ENG")).toBeInTheDocument();
  });
});

describe("UI-HOME-BRAND-1: title вкладки браузера (metadata standalone)", () => {
  it("metadata.title = «CISStat DataTime Lab» — название рядом с фавиконом", () => {
    expect(metadata.title).toBe(NEW_BRAND);
  });

  it("favicon НЕ затронут: icons остался логотипом продукта /logo_TS.png", () => {
    expect(metadata.icons).toEqual({ icon: "/logo_TS.png" });
  });
});
