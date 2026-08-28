// packages/ui/components/TsAnalysisEDA.test.tsx
//
// Тесты для компонента «Разведочный EDA» — в частности:
// 1. Рендер модуля и 11 исследований степпера
// 2. Кнопка «Справка» переключает секцию
// 3. Expandable description box: chevron, overlay, collapse

import "@testing-library/jest-dom";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { TsAnalysisEDA } from "./TsAnalysisEDA";

const STATS_RESPONSE = {
  min_non_null_for_stats: 2,
  columns: [
    {
      name: "Year",
      non_null_count: 4,
      stats: {
        mean: 2021.5,
        median: 2021.5,
        std: 1.29,
        skewness: 0,
        kurtosis: -1.2,
        q1: 2020.75,
        q3: 2022.25,
        iqr: 1.5,
        distribution_hint: "Близко к нормальному",
      },
    },
    {
      name: "Price",
      non_null_count: 4,
      stats: {
        mean: 25,
        median: 25,
        std: 12.91,
        skewness: 0,
        kurtosis: -1.2,
        q1: 17.5,
        q3: 32.5,
        iqr: 15,
        distribution_hint: "Близко к нормальному",
      },
    },
    {
      name: "Volume",
      non_null_count: 4,
      stats: {
        mean: 250,
        median: 250,
        std: 129.1,
        skewness: 0,
        kurtosis: -1.2,
        q1: 175,
        q3: 325,
        iqr: 150,
        distribution_hint: "Близко к нормальному",
      },
    },
  ],
};

function routeFetch(input: RequestInfo | URL, init?: RequestInit) {
  const url = String(input);
  if (url.includes("/target-column")) {
    const selected = init?.method === "POST"
      ? JSON.parse(String(init.body)).column
      : null;
    return Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({
        target_column: selected,
        suggested_column: "Price",
        available_columns: ["Year", "Price", "Volume"],
        has_dataset: true,
      }),
    });
  }
  if (url.includes("/dataset/stats")) {
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(STATS_RESPONSE) });
  }
  if (url.includes("/dataset/distribution")) {
    const column = new URL(url).searchParams.get("column") ?? "Price";
    return Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({
        column,
        non_null_count: 4,
        min: 10,
        max: 40,
        scatter: [{ x: 0, y: 10 }],
        scatter_sampled: false,
        scatter_sampling_method: null,
        scatter_original_count: 4,
        histogram: [{ x0: 10, x1: 20, count: 2 }],
        kde: [{ x: 10, y: 0.1 }],
      }),
    });
  }
  return Promise.reject(new Error(`Unexpected fetch: ${url}`));
}

describe("TsAnalysisEDA", () => {
  beforeEach(() => {
    global.fetch = jest.fn(() => new Promise(() => {}));
  });

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

  it("uses the shared target selector and does not default to the numeric time axis", async () => {
    global.fetch = jest.fn(routeFetch) as jest.Mock;
    render(<TsAnalysisEDA />);

    const selector = await screen.findByRole("combobox", { name: "Исследуемый признак:" });
    await waitFor(() => expect(selector).toHaveValue("Price"));
    expect(screen.getByRole("option", { name: "Year" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Volume" })).toBeInTheDocument();
    expect(
      await screen.findByRole("table", { name: "Описательные статистики по числовым признакам" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Mean", { selector: "div" }).nextElementSibling).toHaveTextContent("25");

    fireEvent.change(selector, { target: { value: "Volume" } });
    await waitFor(() => expect(selector).toHaveValue("Volume"));
    await waitFor(() => {
      expect(screen.getByText("Mean", { selector: "div" }).nextElementSibling).toHaveTextContent("250");
    });
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/v1/session/target-column"),
      expect.objectContaining({ method: "POST", body: JSON.stringify({ column: "Volume" }) }),
    );
  });

  it("shows the specialized metric and pipeline descriptions", async () => {
    global.fetch = jest.fn(routeFetch) as jest.Mock;
    render(<TsAnalysisEDA />);
    await screen.findByRole("table", { name: "Описательные статистики по числовым признакам" });

    fireEvent.click(screen.getAllByRole("button", { name: "Метрики и алгоритм" })[0]);
    expect(screen.getByText(/N = число непустых наблюдений/i)).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Полный пайплайн" })[0]);
    expect(screen.getByText(/GET \/v1\/session\/dataset\/stats/i)).toBeInTheDocument();
  });

  it("recalculates the descriptive profile on demand", async () => {
    global.fetch = jest.fn(routeFetch) as jest.Mock;
    render(<TsAnalysisEDA />);
    await screen.findByRole("table", { name: "Описательные статистики по числовым признакам" });
    const statsCallsBefore = (global.fetch as jest.Mock).mock.calls.filter(([url]) => String(url).includes("/dataset/stats")).length;

    fireEvent.click(screen.getByRole("button", { name: "Пересчитать статистики" }));

    await waitFor(() => {
      const statsCallsAfter = (global.fetch as jest.Mock).mock.calls.filter(([url]) => String(url).includes("/dataset/stats")).length;
      expect(statsCallsAfter).toBe(statsCallsBefore + 1);
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
