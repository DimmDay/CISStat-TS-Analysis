// apps/standalone/components/ProductHeader.test.tsx
//
// Тесты для ProductHeader — проверка выравнивания контента
// по контейнеру max-w-[1600px] mx-auto px-6

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { ProductHeader } from "./ProductHeader";

describe("ProductHeader", () => {
  it("renders the product name", () => {
    render(<ProductHeader />);
    expect(screen.getByText("CISStat TS Analysis")).toBeInTheDocument();
  });

  it("renders all nav items", () => {
    render(<ProductHeader />);
    expect(screen.getByText("Продукт")).toBeInTheDocument();
    expect(screen.getByText("Документация API")).toBeInTheDocument();
    expect(screen.getByText("Тарифы")).toBeInTheDocument();
    expect(screen.getByText("Личный кабинет")).toBeInTheDocument();
  });

  it("has a max-w-[1600px] container for content alignment", () => {
    render(<ProductHeader />);
    // Внешний div — полноширинная граница
    const outerDiv = screen.getByText("CISStat TS Analysis").closest("[class*='border-b']");
    expect(outerDiv).toBeInTheDocument();
    // Внутренний div — центрированный контейнер
    const innerDiv = outerDiv?.querySelector("[class*='max-w-\\[1600px\\]']");
    expect(innerDiv).toBeInTheDocument();
  });

  it("content container has px-6 matching main content padding", () => {
    render(<ProductHeader />);
    const outerDiv = screen.getByText("CISStat TS Analysis").closest("[class*='border-b']");
    const innerDiv = outerDiv?.querySelector("[class*='max-w-\\[1600px\\]']");
    expect(innerDiv?.className).toMatch(/px-6/);
  });
});
