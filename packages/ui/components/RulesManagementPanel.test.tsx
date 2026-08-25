// packages/ui/components/RulesManagementPanel.test.tsx
//
// Тесты для панели «Управление правилами»:
// 1. Рендер заголовка панели
// 2. Рендер селектора шаблона
// 3. Загрузка шаблона при выборе
// 4. Редактор диапазонов отображает min/max для каждого правила
// 5. Кнопки «Применить» и «Сбросить» присутствуют
// 6. Нажатие «Применить» сохраняет шаблон и overrides в текущей сессии
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
let sessionRulesResponse: { template_id: string; overrides: Record<string, unknown> };

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
    sessionRulesResponse = { template_id: "system", overrides: {} };
    // Дефолтный мок: GET /rules/templates
    mockFetch.mockImplementation((url: string, options?: RequestInit) => {
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
              formats: {
                Country: { pattern: "^[А-Яа-яЁёA-Za-z\\s\\-]+$", threshold: 100 },
                Year: { pattern: "^\\d{4}$", threshold: 100 },
                "usd/tonne": { pattern: "^(usd|USD)$", threshold: 100 },
              },
            },
          }),
        });
      }
      if (url.includes("/session/dataset/validation-rules")) {
        if (!options?.method) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve(sessionRulesResponse),
          });
        }
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
    expect(screen.getByText(/Встроенная логика:/i)).toBeInTheDocument();
    expect(screen.getByText(/Правила предметной области:/i)).toBeInTheDocument();
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
      expect(screen.getByText("Форматы: 3 правила")).toBeInTheDocument();
    });
  });

  it("renders editable format rules and saves a changed regex as a session override", async () => {
    const { container } = render(<RulesManagementPanel />);
    const selector = await waitTemplatesLoaded(container);
    fireEvent.change(selector, { target: { value: "fao_prices" } });

    const countryPattern = await screen.findByRole("textbox", { name: "Regex для Country" });
    fireEvent.change(countryPattern, { target: { value: "^[A-Za-z]+$" } });
    fireEvent.click(screen.getByTestId("apply-rules-btn"));

    await waitFor(() => {
      const putCall = mockFetch.mock.calls.find(
        (call: [string, RequestInit?]) =>
          call[0].includes("/session/dataset/validation-rules") && call[1]?.method === "PUT"
      );
      const payload = JSON.parse((putCall?.[1]?.body ?? "{}") as string);
      expect(payload.overrides.formats.Country.pattern).toBe("^[A-Za-z]+$");
      expect(payload.overrides.ranges).toBeUndefined();
    });
  });

  it("lets a custom template add a format rule for an arbitrary column", async () => {
    render(<RulesManagementPanel />);
    await waitFor(() => expect(screen.getByTestId("apply-system-rules-btn")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Добавить правило формата" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Колонка правила 1" }), {
      target: { value: "Code" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Regex правила 1" }), {
      target: { value: "^[A-Z]{3}$" },
    });
    fireEvent.click(screen.getByTestId("apply-system-rules-btn"));

    await waitFor(() => {
      const putCall = mockFetch.mock.calls.find(
        (call: [string, RequestInit?]) =>
          call[0].includes("/session/dataset/validation-rules") && call[1]?.method === "PUT"
      );
      const payload = JSON.parse((putCall?.[1]?.body ?? "{}") as string);
      expect(payload).toEqual({
        template_id: "system",
        overrides: { formats: { Code: { pattern: "^[A-Z]{3}$", threshold: 100 } } },
      });
    });
  });

  it("restores saved custom format rules when the panel is reopened", async () => {
    sessionRulesResponse = {
      template_id: "system",
      overrides: {
        formats: { Code: { pattern: "^[A-Z]{3}$", threshold: 100 } },
      },
    };

    render(<RulesManagementPanel />);

    expect(await screen.findByRole("textbox", { name: "Regex для Code" })).toHaveValue("^[A-Z]{3}$");
    expect(screen.getByText("Форматы: 1 правило")).toBeInTheDocument();
  });

  it("lets a custom session add an exact range rule for an arbitrary numeric column", async () => {
    render(<RulesManagementPanel />);
    await waitFor(() => expect(screen.getByTestId("apply-system-rules-btn")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Добавить правило диапазона" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Колонка правила диапазона 1" }), {
      target: { value: "Score" },
    });
    fireEvent.change(screen.getByRole("spinbutton", { name: "Минимум правила диапазона 1" }), {
      target: { value: "0" },
    });
    fireEvent.change(screen.getByRole("spinbutton", { name: "Максимум правила диапазона 1" }), {
      target: { value: "100" },
    });
    fireEvent.click(screen.getByTestId("apply-system-rules-btn"));

    await waitFor(() => {
      const putCall = mockFetch.mock.calls.find(
        (call: [string, RequestInit?]) =>
          call[0].includes("/session/dataset/validation-rules") && call[1]?.method === "PUT"
      );
      const payload = JSON.parse((putCall?.[1]?.body ?? "{}") as string);
      expect(payload).toEqual({
        template_id: "system",
        overrides: {
          ranges: [{ name: "Score — пользовательский диапазон", keywords: ["Score"], min: 0, max: 100 }],
        },
      });
    });
  });

  it("restores saved custom range rules when the panel is reopened", async () => {
    sessionRulesResponse = {
      template_id: "system",
      overrides: {
        ranges: [{ name: "Score", keywords: ["Score"], min: 0, max: 100 }],
      },
    };

    render(<RulesManagementPanel />);

    expect(await screen.findByRole("textbox", { name: "Ключевые слова Score" })).toHaveValue("Score");
    expect(screen.getByRole("spinbutton", { name: "Минимум Score" })).toHaveValue(0);
    expect(screen.getByRole("spinbutton", { name: "Максимум Score" })).toHaveValue(100);
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
      const spinInputs = screen.getAllByRole("spinbutton", { name: /^(Минимум|Максимум)/i });
      expect(spinInputs.length).toBe(4);
    });
  });

  it("saves the selected template without duplicating unchanged ranges as overrides", async () => {
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
      const sessionCalls = mockFetch.mock.calls.filter(
        (call: [string, unknown]) => call[0]?.includes?.("/session/dataset/validation-rules")
      );
      expect(sessionCalls.length).toBeGreaterThan(0);
      const lastCall = mockFetch.mock.calls[mockFetch.mock.calls.length - 1];
      const options = lastCall[1] as Record<string, unknown>;
      expect(options.method).toBe("PUT");
      expect(JSON.parse(options.body as string)).toEqual({
        template_id: "fao_prices",
        overrides: {},
      });
    });
  });

  it("saves edited ranges as session overrides", async () => {
    const { container } = render(<RulesManagementPanel />);
    const selector = await waitTemplatesLoaded(container);
    fireEvent.change(selector, { target: { value: "fao_prices" } });
    await waitFor(() => expect(screen.getByTestId("apply-rules-btn")).toBeInTheDocument());

    const firstMinInput = screen.getAllByText(/^Минимум$/i)[0].parentElement?.querySelector(
      'input[type="number"]'
    ) as HTMLInputElement;
    fireEvent.change(firstMinInput, { target: { value: "10" } });
    fireEvent.click(screen.getByTestId("apply-rules-btn"));

    await waitFor(() => {
      const putCall = mockFetch.mock.calls.find(
        (call: [string, RequestInit?]) =>
          call[0].includes("/session/dataset/validation-rules") && call[1]?.method === "PUT"
      );
      expect(putCall).toBeDefined();
      const payload = JSON.parse((putCall?.[1]?.body ?? "{}") as string);
      expect(payload.template_id).toBe("fao_prices");
      expect(payload.overrides.ranges[0].min).toBe(10);
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
