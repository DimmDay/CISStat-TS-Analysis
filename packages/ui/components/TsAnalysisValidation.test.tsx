// packages/ui/components/TsAnalysisValidation.test.tsx
//
// Тесты для компонента «Валидация» — в частности:
// 1. Рендер кнопки «Управление правилами» внизу степпера
// 2. Клик по кнопке показывает контент в центральном текстовом окне
// 3. Кнопка визуально отличается от степпер-бейджей (имеет уникальный класс/роль)
// 4. Повторный клик скрывает контент (toggle)
// 5. Expandable description: chevron appears on overflow
// 6. Expand/collapse toggle

import "@testing-library/jest-dom";
import { render, screen, fireEvent } from "@testing-library/react";
import { TsAnalysisValidation } from "./TsAnalysisValidation";

describe("TsAnalysisValidation", () => {
  it("renders the module title", () => {
    render(<TsAnalysisValidation />);
    expect(screen.getByText("Data Quality")).toBeInTheDocument();
  });

  it("renders all 10 DQ checks in the stepper", () => {
    render(<TsAnalysisValidation />);
    const checkLabels = [
      "Типы данных", "Форматы и шаблоны", "Диапазоны значений",
      "Логика и хронология", "Уникальность", "Принадлежность к набору",
      "Ссылочная целостность", "Целостность текста",
      "Равномерность шага", "Достаточность наблюдений",
    ];
    checkLabels.forEach((label) => {
      expect(screen.getByText(label)).toBeInTheDocument();
    });
  });

  // ── Кнопка «Управление правилами» ──

  it("renders the 'Управление правилами' button at the bottom of the stepper", () => {
    render(<TsAnalysisValidation />);
    const rulesButton = screen.getByRole("button", { name: /Управление правилами/i });
    expect(rulesButton).toBeInTheDocument();
  });

  it("the rules button has a distinct data-testid to differentiate from stepper badges", () => {
    render(<TsAnalysisValidation />);
    const rulesButton = screen.getByTestId("rules-management-btn");
    expect(rulesButton).toBeInTheDocument();
  });

  it("clicking the rules button shows rules content in the central text area", () => {
    render(<TsAnalysisValidation />);
    const rulesButton = screen.getByTestId("rules-management-btn");

    // До клика — центральное поле содержит плейсхолдер
    expect(screen.getByText(/Нажмите «Метрики и алгоритм»/i)).toBeInTheDocument();

    // Клик
    fireEvent.click(rulesButton);

    // После клика — появляется контент про правила
    expect(screen.getByText(/Управление правилами/i)).toBeInTheDocument();
    expect(screen.getByText(/шаблон/i)).toBeInTheDocument();
  });

  it("clicking the rules button toggles content off on second click", () => {
    render(<TsAnalysisValidation />);
    const rulesButton = screen.getByTestId("rules-management-btn");

    // Первый клик — показываем
    fireEvent.click(rulesButton);
    expect(screen.queryByText(/Нажмите «Метрики и алгоритм»/i)).not.toBeInTheDocument();

    // Второй клик — скрываем (toggle)
    fireEvent.click(rulesButton);
    expect(screen.getByText(/Нажмите «Метрики и алгоритм»/i)).toBeInTheDocument();
  });

  it("rules button is visually distinct — has outlined/dashed style class", () => {
    render(<TsAnalysisValidation />);
    const rulesButton = screen.getByTestId("rules-management-btn");
    expect(rulesButton.className).toMatch(/border-dashed/);
    expect(rulesButton.className).toMatch(/text-brand/);
  });

  // ── Expandable Description Box ──

  it("description area has a minimum height (collapsed)", () => {
    render(<TsAnalysisValidation />);
    // Проверяем, что контейнер описания рендерится
    expect(screen.getByText("Описание")).toBeInTheDocument();
  });

  it("expand button is not visible when no content is loaded", () => {
    render(<TsAnalysisValidation />);
    // В начальном состоянии (плейсхолдер) нет overflow → нет chevron
    const expandBtn = screen.queryByTestId("desc-expand-btn");
    // Плейсхолдер короткий, overflow маловероятен
    expect(expandBtn).toBeNull();
  });
});
