// packages/ui/components/DatasetContextBar.test.tsx
//
// Тесты для DatasetContextBar — проверка выравнивания контента

import { render, screen } from "@testing-library/react";
import { DatasetContextBar } from "./DatasetContextBar";

// Мокаем AppShellContext
jest.mock("../context/AppShellContext", () => ({
  useAppShell: () => ({
    activeDataset: null,
    log: [],
  }),
}));

describe("DatasetContextBar", () => {
  it("renders 'Загрузить датасет' link when no dataset active", () => {
    render(<DatasetContextBar />);
    expect(screen.getByText(/Загрузить датасет/i)).toBeInTheDocument();
  });

  it("renders 'Логи событий' button", () => {
    render(<DatasetContextBar />);
    expect(screen.getByRole("button", { name: /Логи событий/i })).toBeInTheDocument();
  });

  it("has a max-w-[1600px] container for content alignment", () => {
    render(<DatasetContextBar />);
    // Ищем внешний div с border
    const outerDiv = screen.getByText(/Загрузить датасет/i).closest("[class*='border-b']");
    expect(outerDiv).toBeInTheDocument();
    // Внутренний div — центрированный контейнер
    const innerDiv = outerDiv?.querySelector("[class*='max-w-\\[1600px\\]']");
    expect(innerDiv).toBeInTheDocument();
  });

  it("content container has px-6 matching main content padding", () => {
    render(<DatasetContextBar />);
    const outerDiv = screen.getByText(/Загрузить датасет/i).closest("[class*='border-b']");
    const innerDiv = outerDiv?.querySelector("[class*='max-w-\\[1600px\\]']");
    expect(innerDiv?.className).toMatch(/px-6/);
  });
});
