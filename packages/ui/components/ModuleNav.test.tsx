// packages/ui/components/ModuleNav.test.tsx
//
// Тесты для ModuleNav — проверка навигации и выравнивания

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { ModuleNav } from "./ModuleNav";

// Мокаем usePathname
jest.mock("next/navigation", () => ({
  usePathname: () => "/validation",
}));

// ModuleNav теперь показывает "Логи событий" (перенесено из удалённого
// DatasetContextBar.tsx, см. комментарий в ModuleNav.tsx) -- нужен log.
jest.mock("../context/AppShellContext", () => ({
  useAppShell: () => ({ log: [] }),
}));

describe("ModuleNav", () => {
  it("renders all module tabs", () => {
    render(<ModuleNav />);
    const tabs = [
      "Навигатор", "Загрузка", "Валидация", "Предобработка", "Разведочный EDA",
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
    // Внутренний div — центрированный контейнер
    const innerDiv = nav.querySelector("[class*='max-w-\\[1600px\\]']");
    expect(innerDiv).toBeInTheDocument();
  });

  it("content container has px-6 matching main content padding", () => {
    render(<ModuleNav />);
    const nav = screen.getByRole("navigation", { name: /Навигация по модулям анализа/i });
    const innerDiv = nav.querySelector("[class*='max-w-\\[1600px\\]']");
    expect(innerDiv?.className).toMatch(/px-6/);
  });
});
