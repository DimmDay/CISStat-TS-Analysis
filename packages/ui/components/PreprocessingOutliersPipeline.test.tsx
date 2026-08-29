import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { PreprocessingOutliersPipeline } from "./PreprocessingOutliersPipeline";

const PROFILE = {
  rule_source: "system", mode: "auto", status: "warning", status_reason: null, method: "iqr",
  total_rows: 21, total_numeric_columns: 1, total_outliers: 1, outlier_rate_pct: 4.76,
  affected_columns: ["Price"],
  columns: [{
    column: "Price", sample_size: 21, outlier_count: 1, outlier_pct: 4.76,
    recommended_method: "iqr", bounds: { lower: -5, upper: 25 },
    outlier_examples: [20], insufficient_sample: false,
  }],
};

const ALL_COLUMNS = { columns: [{ column: "Price" }, { column: "Date" }] };

const PREVIEW = {
  applied: false, strategy: "cap", method: "iqr", used_residual: false,
  total_outliers: 1, total_changed: 1, total_still_outliers: 0,
  rows_removed: 0, added_columns: [],
  columns: [{
    column: "Price", outlier_count: 1, changed_count: 1, still_outliers: 0, outlier_examples: [20], flag_column: null,
    stats_before: { mean: 57, median: 10, std: 216.3 },
    stats_after: { mean: 11, median: 10, std: 3.4 },
  }],
  profile: [{ ...PROFILE.columns[0], outlier_count: 0, outlier_pct: 0, outlier_examples: [] }],
};

function mockFetchSequence(...responses: unknown[]) {
  const queue = [...responses];
  global.fetch = jest.fn(() => {
    const next = queue.shift() ?? responses[responses.length - 1];
    return Promise.resolve({ ok: true, json: () => Promise.resolve(next) });
  }) as unknown as typeof fetch;
}

describe("PreprocessingOutliersPipeline", () => {
  beforeEach(() => {
    mockFetchSequence(PROFILE, ALL_COLUMNS);
  });

  it("renders the five-step correction flow with columns pre-selected", async () => {
    render(<PreprocessingOutliersPipeline onApplied={jest.fn()} />);

    expect(screen.getByRole("region", { name: "Мастер исправления выбросов" })).toBeInTheDocument();
    expect(await screen.findByRole("checkbox", { name: "Выбрать колонку Price" })).toBeChecked();
    expect(screen.getByText("2. Метод обнаружения")).toBeInTheDocument();
    expect(screen.getByText("3. Стратегия исправления")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Modified Z-score (MAD)" })).toBeInTheDocument();
  });

  it("enables the residual toggle only when exactly one column is selected", async () => {
    render(<PreprocessingOutliersPipeline onApplied={jest.fn()} />);
    await screen.findByText("Price"); // дожидаемся, пока профиль и allColumns осядут (оба setState в одном тике)
    const toggle = screen.getByRole("checkbox", { name: "Обнаруживать на остатке после STL-декомпозиции" });
    await waitFor(() => expect(toggle).not.toBeDisabled());

    fireEvent.click(toggle);
    expect(await screen.findByRole("combobox", { name: "Колонка с датой для декомпозиции" })).toBeInTheDocument();
  });

  it("previews and applies only after confirmation", async () => {
    mockFetchSequence(PROFILE, ALL_COLUMNS, PREVIEW, { ...PREVIEW, applied: true });
    const onApplied = jest.fn();
    render(<PreprocessingOutliersPipeline onApplied={onApplied} />);

    await screen.findByText("Price");
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    expect(await screen.findByText("Найдено выбросов: 1")).toBeInTheDocument();

    const apply = screen.getByRole("button", { name: "Применить исправления" });
    expect(apply).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /Подтверждаю изменение активного датасета/i }));
    fireEvent.click(apply);
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
  });

  it("shows a positive terminal state when there are no outliers", async () => {
    mockFetchSequence({ ...PROFILE, total_outliers: 0, columns: [{ ...PROFILE.columns[0], outlier_count: 0 }] }, ALL_COLUMNS);
    render(<PreprocessingOutliersPipeline onApplied={jest.fn()} />);
    expect(await screen.findByText(/Выбросов в датасете не найдено/)).toBeInTheDocument();
  });

  it("shows the before/after impact forecast in the preview step", async () => {
    mockFetchSequence(PROFILE, ALL_COLUMNS, PREVIEW);
    render(<PreprocessingOutliersPipeline onApplied={jest.fn()} />);

    await screen.findByText("Price");
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));

    expect(await screen.findByText("Прогноз влияния на статистики")).toBeInTheDocument();
    expect(screen.getByText("10 → 10")).toBeInTheDocument(); // медиана не меняется
    expect(screen.getByText(/216,3 → 3,4/)).toBeInTheDocument(); // std резко падает
  });
});
