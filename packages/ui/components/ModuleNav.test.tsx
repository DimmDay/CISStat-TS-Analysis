// packages/ui/components/ModuleNav.test.tsx
//
// Тесты для ModuleNav — проверка навигации, выравнивания и
// аккордеона «О платформе» (Task 25).

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { ModuleNav } from "./ModuleNav";

// Мокаем usePathname — по умолчанию на /validation, чтобы не было
// ложных срабатываний isActive на корневом пути.
jest.mock("next/navigation", () => ({
  usePathname: () => "/validation",
}));

// ModuleNav показывает "Логи событий" — нужен log.
jest.mock("../context/AppShellContext", () => ({
  useAppShell: () => ({ log: [] }),
}));

describe("ModuleNav", () => {
  it("renders all module tabs including 'О платформе'", () => {
    render(<ModuleNav />);
    const tabs = [
      "О платформе", "Загрузка", "Валидация", "Предобработка", "Разведочный EDA",
      "Моделирование", "Прогнозирование", "Задачи",
    ];
    tabs.forEach((label) => {
      expect(screen.getByText(label)).toBeInTheDocument();
    });
  });

  it("has a max-w-[1600px] container for content alignment", () => {
    render(<ModuleNav />);
    const nav = screen.getByRole("navigation", { name: /Навигация по модулям анализа/i });
    expect(nav).toBeInTheDocument();
    const innerDiv = nav.querySelector("[class*='max-w-\\[1600px\\]']");
    expect(innerDiv).toBeInTheDocument();
  });

  it("content container has px-6 matching main content padding", () => {
    render(<ModuleNav />);
    const nav = screen.getByRole("navigation", { name: /Навигация по модулям анализа/i });
    const innerDiv = nav.querySelector("[class*='max-w-\\[1600px\\]']");
    expect(innerDiv?.className).toMatch(/px-6/);
  });

  // ── Аккордеон «О платформе» (Task 25) ──────────────────────────

  it("'О платформе' link points to /", () => {
    render(<ModuleNav />);
    const link = screen.getByText("О платформе").closest("a");
    expect(link).toHaveAttribute("href", "/");
  });

  it("renders 5 sub-links in the 'О платформе' accordion panel", () => {
    render(<ModuleNav />);
    const subLinks = [
      "Знакомство с платформой",
      "Обучение и база знаний",
      "Отраслевые исследования",
      "Доступ и тарифы",
      "Документация API",
    ];
    subLinks.forEach((label) => {
      expect(screen.getByText(label)).toBeInTheDocument();
    });
  });

  it("accordion sub-links have correct hrefs from HOME_ROUTES", () => {
    render(<ModuleNav />);
    // role="menuitem" переопределяет неявную роль link —
    // ищем по menuitem, а не по link.
    const menuItems = screen.getAllByRole("menuitem");
    const expectedHrefs = ["/navigator", "/docs", "/research", "/pricing", "/docs"];
    const actualHrefs = menuItems.map((mi) => mi.getAttribute("href"));
    expect(actualHrefs).toEqual(expectedHrefs);
  });

  it("accordion panel has role='menu' for accessibility", () => {
    render(<ModuleNav />);
    const menu = screen.getByRole("menu", { name: /О платформе/i });
    expect(menu).toBeInTheDocument();
  });

  it("'О платформе' trigger has aria-haspopup='menu'", () => {
    render(<ModuleNav />);
    const trigger = screen.getByText("О платформе").closest("a");
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
  });

  it("'О платформе' is NOT marked active when pathname is /validation", () => {
    // usePathname мокнут на /validation — «О платформе» не должна подсвечиваться
    render(<ModuleNav />);
    const trigger = screen.getByText("О платформе").closest("a");
    expect(trigger?.className).not.toContain("border-brand");
    expect(trigger?.className).not.toContain("text-brand");
  });

  it("does NOT render 'Навигатор' tab (renamed to 'О платформе' in Task 25)", () => {
    render(<ModuleNav />);
    expect(screen.queryByText("Навигатор")).toBeNull();
  });

  it("does NOT render 'Приступить к анализу данных' in accordion (already in main nav as 'Загрузка')", () => {
    render(<ModuleNav />);
    expect(screen.queryByText("Приступить к анализу данных")).toBeNull();
  });
});
