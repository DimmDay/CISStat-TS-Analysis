import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";

import {
  EdaDistributionOverview,
  type EdaDistributionResponse,
} from "./EdaDistributionOverview";


const PROFILE: EdaDistributionResponse = {
  column: "Price", applicable: true, reason: null, n_observations: 240,
  missing_count: 0, min_observations: 8, alpha: 0.05, requested_bins: 20,
  bins: 20, is_discrete: false, unique_count: 240, mean: 10, median: 9.8,
  std: 2, q1: 8.5, q3: 11.2, iqr: 2.7, mad: 1.3, skewness: 0.08,
  excess_kurtosis: -0.12, shape_label: "Почти симметричное распределение",
  normality_applicable: true, normality_status: "compatible", qq_r: 0.997,
  qq_slope: 1.95, qq_intercept: 10, tests: [
    { id: "shapiro", label: "Shapiro–Wilk", available: true, statistic: 0.99, p_value: 0.32, adjusted_p_value: 0.64, reject_normality: false, n_used: 240, calibration: "standard", note: null },
    { id: "jarque_bera", label: "Jarque–Bera", available: true, statistic: 0.8, p_value: 0.67, adjusted_p_value: 0.67, reject_normality: false, n_used: 240, calibration: "monte_carlo", note: "p-значение откалибровано методом Монте-Карло." },
    { id: "lilliefors", label: "K–S (Лиллиефорс)", available: true, statistic: 0.04, p_value: 0.44, adjusted_p_value: 0.64, reject_normality: false, n_used: 240, calibration: "table", note: null },
  ],
  histogram: [{ x0: 4, x1: 6, count: 10, density: 0.02, normal_expected_count: 8.2 }],
  density: [{ x: 4, empirical: 0.01, normal: 0.005 }, { x: 10, empirical: 0.2, normal: 0.199 }],
  qq: [{ theoretical: -2, observed: 6, reference: 6.1 }, { theoretical: 2, observed: 14, reference: 13.9 }],
  cdf: [{ x: 6, empirical: 0.03, normal: 0.023 }, { x: 14, empirical: 0.98, normal: 0.977 }],
  recommendation: "Форма ряда совместима с нормальным распределением.",
  recommendations: ["Сопоставьте вывод с Q–Q графиком."],
  warnings: ["Формальная нормальность для модели проверяется на остатках."],
};


describe("EdaDistributionOverview", () => {
  it("switches five overview views backed by one response", () => {
    render(<EdaDistributionOverview profile={PROFILE} loading={false} error={null} noDataset={false} parameters={{ alpha: 0.05, bins: 20 }} onParametersChange={jest.fn()} />);

    expect(screen.getByRole("img", { name: "Гистограмма распределения для Price" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Плотность" }));
    expect(screen.getByRole("img", { name: "Сравнение плотностей для Price" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Q–Q" }));
    expect(screen.getByRole("img", { name: "Q–Q график для Price" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "F(x)" }));
    expect(screen.getByRole("img", { name: "Сравнение функций распределения для Price" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Тесты" }));
    expect(screen.getByRole("table", { name: "Тесты нормальности" })).toBeInTheDocument();
    expect(screen.getByText("K–S (Лиллиефорс)")).toBeInTheDocument();
  });

  it("updates alpha and bins without adding another target selector", () => {
    const onParametersChange = jest.fn();
    render(<EdaDistributionOverview profile={PROFILE} loading={false} error={null} noDataset={false} parameters={{ alpha: 0.05, bins: 20 }} onParametersChange={onParametersChange} />);

    fireEvent.change(screen.getByRole("combobox", { name: "Уровень значимости α" }), { target: { value: "0.01" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Число интервалов" }), { target: { value: "30" } });
    expect(onParametersChange).toHaveBeenCalledWith({ alpha: 0.01 });
    expect(onParametersChange).toHaveBeenCalledWith({ bins: 30 });
    expect(screen.queryByRole("combobox", { name: /исследуемый признак/i })).not.toBeInTheDocument();
  });

  it("shows an honest not-applicable state", () => {
    render(<EdaDistributionOverview profile={{ ...PROFILE, applicable: false, reason: "В ряду есть пропуски" }} loading={false} error={null} noDataset={false} parameters={{ alpha: 0.05, bins: 20 }} onParametersChange={jest.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("В ряду есть пропуски");
  });
});
