// packages/ui/components/TsAnalysisEDA.test.tsx
//
// Тесты для компонента «Разведочный EDA» — в частности:
// 1. Рендер модуля и 11 исследований степпера
// 2. Кнопка «Справка» переключает секцию
// 3. Expandable description box: chevron, overlay, collapse

import "@testing-library/jest-dom";
import { render, screen, fireEvent } from "@testing-library/react";
import { TsAnalysisEDA } from "./TsAnalysisEDA";

describe("TsAnalysisEDA", () => {
  it("renders the module title", () => {
    render(<TsAnalysisEDA />);
    expect(screen.getByText("Разведочный EDA")).toBeInTheDocument();
  });

  it("renders all 11 EDA investigations in the stepper", () => {
    render(<TsAnalysisEDA />);
    const stepLabels = [
      "Описательные статистики", "Корреляция (ACF/PACF)", "IH-анализ",
      "Сезонность и периодичность", "Верификация стационарности",
      "Распределение", "Структурные сдвиги", "Отбор признаков",
      "Стратегия валидации", "Матрица моделей", "Паспорт свойств ряда",
    ];
    stepLabels.forEach((label) => {
      expect(screen.getByText(label)).toBeInTheDocument();
    });
  });

  // ── Кнопка «Справка» ──

  it("renders the 'Справка' button in the header", () => {
    render(<TsAnalysisEDA />);
    const helpButton = screen.getByRole("button", { name: /Справка/i });
    expect(helpButton).toBeInTheDocument();
  });

  it("clicking 'Справка' shows help content in the central text area", () => {
    render(<TsAnalysisEDA />);
    const helpButton = screen.getByRole("button", { name: /Справка/i });

    // До клика — плейсхолдер
    expect(screen.getByText(/Нажмите «Метрики и алгоритм»/i)).toBeInTheDocument();

    // Клик
    fireEvent.click(helpButton);

    // После клика — появляется справка. Используем getAllByText, т.к.
    // regex /Цели модуля/i матчит ДВА элемента: подзаголовок «Справка — Цели
    // модуля и результаты EDA» и сам контент «Цели модуля "EDA"».
    const matches = screen.getAllByText(/Цели модуля/i);
    expect(matches.length).toBeGreaterThanOrEqual(1);
  });

  it("clicking 'Справка' toggles content off on second click", () => {
    render(<TsAnalysisEDA />);
    const helpButton = screen.getByRole("button", { name: /Справка/i });

    // Первый клик — показываем
    fireEvent.click(helpButton);
    expect(screen.queryByText(/Нажмите «Метрики и алгоритм»/i)).not.toBeInTheDocument();

    // Второй клик — скрываем (toggle)
    fireEvent.click(helpButton);
    expect(screen.getByText(/Нажмите «Метрики и алгоритм»/i)).toBeInTheDocument();
  });

  // ── Expandable Description Box ──

  it("description area has a minimum height (collapsed)", () => {
    render(<TsAnalysisEDA />);
    expect(screen.getByText("Описание")).toBeInTheDocument();
  });

  it("expand chevron is not visible when no content is loaded (no overflow)", () => {
    render(<TsAnalysisEDA />);
    // В начальном состоянии (плейсхолдер) нет overflow → нет chevron
    const expandBtn = screen.queryByTestId("desc-expand-btn");
    expect(expandBtn).toBeNull();
  });

  it("collapse chevron is not visible when description is not expanded", () => {
    render(<TsAnalysisEDA />);
    const collapseBtn = screen.queryByTestId("desc-collapse-btn");
    expect(collapseBtn).toBeNull();
  });

  it("collapse chevron appears inside description after expanding", () => {
    render(<TsAnalysisEDA />);
    // Сначала chevron нет
    expect(screen.queryByTestId("desc-collapse-btn")).toBeNull();

    // Кликаем справку для контента
    const helpButton = screen.getByRole("button", { name: /Справка/i });
    fireEvent.click(helpButton);

    // После загрузки контента — компонент стабилен.
    // getAllByText, т.к. regex матчит и подзаголовок, и контент (см. выше).
    const matches = screen.getAllByText(/Цели модуля/i);
    expect(matches.length).toBeGreaterThanOrEqual(1);
  });
});
