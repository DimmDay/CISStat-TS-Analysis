import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";
import { PreprocessingScalingOverview, type ScalingProfile } from "./PreprocessingScalingOverview";


const profile: ScalingProfile = {
  target_column: "Price", applicable: true, reason: null, n_observations: 100,
  numeric_count: 3, eligible_count: 2, suggested_columns: ["Volume", "Temperature"],
  recommended_method: "standard", configured: false, saved_recipe: null,
  focus_column: "Volume", scale_ratio: 250, orders_of_magnitude: 2.398,
  columns: [
    { name: "Volume", role: "source", dtype: "float64", missing_count: 0, unique_count: 100, binary: false, constant: false, eligible: true, recommended: true, exclusion_reason: null, minimum: 10000, maximum: 34750, mean: 22375, std: 7253, median: 22375, q1: 16187.5, q3: 28562.5, iqr: 12375, outlier_pct: 0, scale: 7253 },
    { name: "Temperature", role: "source", dtype: "float64", missing_count: 0, unique_count: 100, binary: false, constant: false, eligible: true, recommended: true, exclusion_reason: null, minimum: 4, maximum: 6, mean: 5, std: 0.7, median: 5, q1: 4.5, q3: 5.5, iqr: 1, outlier_pct: 0, scale: 0.7 },
  ],
  preview_points: [{ x: "2018-01-01", original: 10000, scaled: -1.7 }],
  range_points: [{ column: "Volume", scale_before: 7253, scale_after: 1, log_scale_before: 3.86, log_scale_after: 0 }],
  distribution_points: [{ x_before: 10000, density_before: 0.1, x_after: -1.7, density_after: 0.1 }],
  box_points: [{ column: "Volume", stage: "before", minimum: 10000, q1: 16187.5, median: 22375, q3: 28562.5, maximum: 34750 }],
  correlation_points: [{ x: "Volume", y: "Temperature", before: 0.2, after: 0.2, delta: 0 }],
  methods: [
    { method: "standard", label: "StandardScaler", linear: true, centers: "mean", scales: "std", outlier_robust: false, bounded: false, preserves_zero: false, max_correlation_delta: 0, note: "Нулевая средняя и единичная дисперсия." },
    { method: "minmax", label: "MinMaxScaler", linear: true, centers: "minimum", scales: "range", outlier_robust: false, bounded: true, preserves_zero: false, max_correlation_delta: 0, note: "Диапазон." },
    { method: "robust", label: "RobustScaler", linear: true, centers: "median", scales: "IQR", outlier_robust: true, bounded: false, preserves_zero: false, max_correlation_delta: 0, note: "Устойчив к выбросам." },
    { method: "maxabs", label: "MaxAbsScaler", linear: true, centers: "none", scales: "max(abs)", outlier_robust: false, bounded: true, preserves_zero: true, max_correlation_delta: 0, note: "Сохраняет нули." },
    { method: "quantile", label: "QuantileTransformer", linear: false, centers: "rank", scales: "ECDF", outlier_robust: true, bounded: false, preserves_zero: false, max_correlation_delta: 0.1, note: "Искажает корреляции." },
  ],
  warnings: [], recommendation: "Для текущей матрицы начните со StandardScaler.",
  methodology_note: "Сохраняется рецепт; fit выполняется только на train-fold.",
};


describe("PreprocessingScalingOverview", () => {
  it("renders five overview visualizations", () => {
    render(<PreprocessingScalingOverview profile={profile} loading={false} error={null} noDataset={false} />);
    expect(screen.getByRole("img", { name: /Ряд до и после диагностического масштабирования/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Масштабы" }));
    expect(screen.getByRole("img", { name: /Сравнение масштабов числовых признаков/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Распределение" }));
    expect(screen.getByRole("img", { name: /Распределение до и после масштабирования/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Корреляции" }));
    expect(screen.getByRole("table", { name: /Изменение корреляций после преобразования/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Методы" }));
    expect(screen.getByRole("table", { name: /Сравнение методов масштабирования/i })).toBeInTheDocument();
  });

  it("supports loading, errors and not-applicable states", () => {
    const { rerender } = render(<PreprocessingScalingOverview profile={null} loading error={null} noDataset={false} />);
    expect(screen.getByRole("status")).toHaveTextContent("Сравниваем масштабы");
    rerender(<PreprocessingScalingOverview profile={null} loading={false} error="Ошибка" noDataset={false} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Ошибка");
    rerender(<PreprocessingScalingOverview profile={{ ...profile, applicable: false, reason: "Нет непрерывных признаков" }} loading={false} error={null} noDataset={false} />);
    expect(screen.getByRole("status")).toHaveTextContent("Нет непрерывных признаков");
  });
});

