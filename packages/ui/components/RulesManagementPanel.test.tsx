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
//
// ⚠️ 2026-08-17 (Task 20-D): исправлен race condition. Тесты падали с
// `Unable to find [data-testid="apply-rules-btn"]` после `fireEvent.change`.
// Причина: на момент клика по селектору компонент ещё не загрузил список
// шаблонов (асинхронный GET /v1/internal/rules/templates). Выбор
// "fao_prices" игнорировался, т.к. `templates` был пуст и в селекторе
// не было <option value="fao_prices">. Кроме того, native <select> не
// обновляет значение при несуществующем option — fireEvent.change был
// no-op. Решение: ждать загрузки шаблонов через waitFor перед change
// (детектим, что в селекторе появилось 4 <option>).
//
// Также исправлен label/input association: getAllByLabelText(/^Минимум/i)
// возвращал пустой массив, т.к. <label> без htmlFor не ассоциируется с
// <input>. Тест переписан на getAllByRole("spinbutton") + фильтрацию по
// label-тексту соседнего <label>. Альтернатива — добавить htmlRef/id в
// RulesManagementPanel.tsx (но это меняет прод-код), поэтому оставлен
// lookup по DOM-структуре.

import "@testing-library/jest-dom";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { RulesManagementPanel } from "./RulesManagementPanel";

// Мокаем fetch для API-вызовов
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Хелпер: ждём, пока селектор шаблонов загрузит все 4 <option>.
// До этого момента fireEvent.change(selector, { value: "fao_prices" })
// будет no-op (нативный <select> не меняет значение на несуществующую
// опцию), и последующие waitFor на apply-rules-btn / правила таймаутятся.
async function waitTemplatesLoaded(container: HTMLElement) {
  await waitFor(() => {
    const selector = screen.getByLabelText(/Выберите шаблон/i);
    const options = selector.querySelectorAll("option");
    expect(options.length).toBeGreaterThanOrEqual(4);
  });
  return screen.getByLabelText(/Выберите шаблон/i) as HTMLSelectElement;
}

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
    const { container } = render(<RulesManagementPanel />);
    const selector = await waitTemplatesLoaded(container);

    // Выбираем fao_prices — загрузятся правила
    fireEvent.change(selector, { target: { value: "fao_prices" } });

    await waitFor(() => {
      expect(screen.getByTestId("apply-rules-btn")).toBeInTheDocument();
      expect(screen.getByTestId("reset-rules-btn")).toBeInTheDocument();
    });
  });

  it("loads rules when template is selected", async () => {
    const { container } = render(<RulesManagementPanel />);
    const selector = await waitTemplatesLoaded(container);

    fireEvent.change(selector, { target: { value: "fao_prices" } });

    await waitFor(() => {
      expect(screen.getByText(/Цена должна быть положительной/i)).toBeInTheDocument();
      expect(screen.getByText(/Год в разумных пределах/i)).toBeInTheDocument();
    });
  });

  it("shows range editor with min/max inputs for each rule", async () => {
    const { container } = render(<RulesManagementPanel />);
    const selector = await waitTemplatesLoaded(container);

    fireEvent.change(selector, { target: { value: "fao_prices" } });

    await waitFor(() => {
      // Два правила = два min input + два max input.
      // <label> в RulesManagementPanel.tsx не имеют htmlFor (id-связи с
      // input), поэтому getAllByLabelText возвращает 0. Ищем через
      // текстовое содержимое соседних <label>.
      const allLabels = screen.getAllByText(/^Минимум$/i);
      const maxLabels = screen.getAllByText(/^Максимум$/i);
      expect(allLabels.length).toBe(2);
      expect(maxLabels.length).toBe(2);
      // 4 числовых input (type=number → role=spinbutton).
      const spinInputs = screen.getAllByRole("spinbutton");
      expect(spinInputs.length).toBe(4);
    });
  });

  it("calls PATCH /rules/update on Apply click", async () => {
    const { container } = render(<RulesManagementPanel />);
    const selector = await waitTemplatesLoaded(container);

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
    const { container } = render(<RulesManagementPanel />);
    const selector = await waitTemplatesLoaded(container);

    fireEvent.change(selector, { target: { value: "fao_prices" } });

    // Ждём загрузки правил
    await waitFor(() => {
      expect(screen.getByText(/Цена должна быть положительной/i)).toBeInTheDocument();
    });

    // Изменим min первого правила.
    // <label> не связан с input через htmlFor, поэтому ищем input через
    // DOM: первый <label>«Минимум»</label> → sibling <input type="number">.
    const minLabels = screen.getAllByText(/^Минимум$/i);
    const firstMinInput = minLabels[0].parentElement?.querySelector(
      'input[type="number"]'
    ) as HTMLInputElement;
    expect(firstMinInput).toBeTruthy();
    fireEvent.change(firstMinInput, { target: { value: "10" } });
    expect(firstMinInput.value).toBe("10");

    // Нажмём «Сбросить»
    const resetBtn = screen.getByTestId("reset-rules-btn");
    fireEvent.click(resetBtn);

    // После сброса значения должны вернуться к исходным (min=0).
    await waitFor(() => {
      expect(firstMinInput.value).toBe("0");
    });
  });
});
