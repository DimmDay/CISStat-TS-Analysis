// packages/ui/components/RulesManagementPanel.test.tsx
//
// Тесты для панели «Управление правилами»:
// 1. Рендер заголовка панели
// 2. Рендер селектора шаблона
// 3. Загрузка шаблона при выборе
// 4. Редактор диапазонов отображает min/max для каждого правила
// 5. Кнопки «Применить» и «Сбросить» присутствуют
// 6. Нажатие «Применить» вызывает PATCH /rules/update
// 7. Нажатие «Сбросить» возвращает исходные значения

import "@testing-library/jest-dom";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { RulesManagementPanel } from "./RulesManagementPanel";

// Мокаем fetch для API-вызовов
const mockFetch = jest.fn();
global.fetch = mockFetch;

describe("RulesManagementPanel", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    // Дефолтный мок: GET /rules/templates
    mockFetch.mockImplementation((url: string) => {
      if (url.includes("/rules/templates")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            templates: [
              { id: "custom", label: "Custom (автогенерация)" },
              { id: "default", label: "Default (общий)" },
              { id: "fao_prices", label: "FAO Prices (CIS)" },
              { id: "macro", label: "Macro indicators" },
            ],
          }),
        });
      }
      if (url.includes("/rules/load/")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            template_id: "fao_prices",
            rules: {
              ranges: [
                { name: "Цена должна быть положительной", keywords: ["price"], min: 0, max: 5000 },
                { name: "Год в разумных пределах", keywords: ["year"], min: 1990, max: 2030 },
              ],
            },
          }),
        });
      }
      if (url.includes("/rules/update")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            template_id: "fao_prices",
            updated_ranges_count: 2,
            message: "Правила обновлены in-memory.",
          }),
        });
      }
      return Promise.resolve({ ok: false, json: () => Promise.resolve({ detail: "Not found" }) });
    });
  });

  it("renders the panel header", () => {
    render(<RulesManagementPanel />);
    expect(screen.getByText(/Управление правилами/i)).toBeInTheDocument();
  });

  it("renders template selector with 4 options", async () => {
    render(<RulesManagementPanel />);
    const selector = screen.getByLabelText(/Выберите шаблон/i);
    expect(selector).toBeInTheDocument();

    await waitFor(() => {
      const options = selector.querySelectorAll("option");
      expect(options.length).toBe(4);
    });
  });

  it("renders Apply and Reset buttons after rules are loaded", async () => {
    render(<RulesManagementPanel />);
    const selector = screen.getByLabelText(/Выберите шаблон/i);

    // Выбираем fao_prices — загрузятся правила
    fireEvent.change(selector, { target: { value: "fao_prices" } });

    await waitFor(() => {
      expect(screen.getByTestId("apply-rules-btn")).toBeInTheDocument();
      expect(screen.getByTestId("reset-rules-btn")).toBeInTheDocument();
    });
  });

  it("loads rules when template is selected", async () => {
    render(<RulesManagementPanel />);
    const selector = screen.getByLabelText(/Выберите шаблон/i);

    fireEvent.change(selector, { target: { value: "fao_prices" } });

    await waitFor(() => {
      expect(screen.getByText(/Цена должна быть положительной/i)).toBeInTheDocument();
      expect(screen.getByText(/Год в разумных пределах/i)).toBeInTheDocument();
    });
  });

  it("shows range editor with min/max inputs for each rule", async () => {
    render(<RulesManagementPanel />);
    const selector = screen.getByLabelText(/Выберите шаблон/i);

    fireEvent.change(selector, { target: { value: "fao_prices" } });

    await waitFor(() => {
      // Два правила = два min input + два max input
      const minInputs = screen.getAllByLabelText(/^Минимум/i);
      const maxInputs = screen.getAllByLabelText(/^Максимум/i);
      expect(minInputs.length).toBe(2);
      expect(maxInputs.length).toBe(2);
    });
  });

  it("calls PATCH /rules/update on Apply click", async () => {
    render(<RulesManagementPanel />);
    const selector = screen.getByLabelText(/Выберите шаблон/i);

    fireEvent.change(selector, { target: { value: "fao_prices" } });

    await waitFor(() => {
      expect(screen.getByTestId("apply-rules-btn")).toBeInTheDocument();
    });

    const applyBtn = screen.getByTestId("apply-rules-btn");
    fireEvent.click(applyBtn);

    await waitFor(() => {
      // Проверяем, что fetch был вызван с PATCH
      const patchCalls = mockFetch.mock.calls.filter(
        (call: [string, unknown]) => call[0]?.includes?.("/rules/update")
      );
      expect(patchCalls.length).toBeGreaterThan(0);
      const lastCall = mockFetch.mock.calls[mockFetch.mock.calls.length - 1];
      const options = lastCall[1] as Record<string, unknown>;
      expect(options.method).toBe("PATCH");
    });
  });

  it("resets rules to original values on Reset click", async () => {
    render(<RulesManagementPanel />);
    const selector = screen.getByLabelText(/Выберите шаблон/i);

    fireEvent.change(selector, { target: { value: "fao_prices" } });

    // Ждём загрузки правил
    await waitFor(() => {
      expect(screen.getByText(/Цена должна быть положительной/i)).toBeInTheDocument();
    });

    // Изменим min первого правила
    const minInputs = screen.getAllByLabelText(/^Минимум/i);
    fireEvent.change(minInputs[0], { target: { value: "10" } });

    // Нажмём «Сбросить»
    const resetBtn = screen.getByTestId("reset-rules-btn");
    fireEvent.click(resetBtn);

    // После сброса значения должны вернуться к исходным
    await waitFor(() => {
      const resetInputs = screen.getAllByLabelText(/^Минимум/i);
      expect((resetInputs[0] as HTMLInputElement).value).toBe("0");
    });
  });
});
