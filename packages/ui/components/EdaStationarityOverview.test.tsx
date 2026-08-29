import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";

import {
  EdaStationarityOverview,
  type EdaStationarityResponse,
} from "./EdaStationarityOverview";


const PROFILE: EdaStationarityResponse = {
  column: "Price",
  applicable: true,
  reason: null,
  n_observations: 120,
  missing_count: 0,
  min_observations: 30,
  alpha: 0.05,
  requested_rolling_window: 12,
  rolling_window: 12,
  consensus: "stationary",
  recommendation: "Ряд стационарен вокруг уровня.",
  order_source: "time_column",
  order_column: "Date",
  order_warning: null,
  frequency: "D",
  breakpoint_index: 60,
  breakpoint_label: "2024-03-01T00:00:00",
  tests: [
    { id: "adf_level", label: "ADF (уровень)", null_hypothesis: "Единичный корень", alternative_hypothesis: "Стационарность вокруг уровня", available: true, statistic: -4.2, p_value: 0.001, lags: 2, reject_null: true, supports_stationarity: true, critical_values: { "5%": -2.9 }, note: null },
    { id: "adf_trend", label: "ADF (тренд)", null_hypothesis: "Единичный корень", alternative_hypothesis: "Стационарность вокруг тренда", available: true, statistic: -4.4, p_value: 0.004, lags: 2, reject_null: true, supports_stationarity: true, critical_values: { "5%": -3.4 }, note: null },
    { id: "kpss_level", label: "KPSS (уровень)", null_hypothesis: "Стационарность вокруг уровня", alternative_hypothesis: "Единичный корень", available: true, statistic: 0.1, p_value: 0.1, lags: 4, reject_null: false, supports_stationarity: true, critical_values: { "5%": 0.463 }, note: "p-value ограничен таблицей" },
    { id: "kpss_trend", label: "KPSS (тренд)", null_hypothesis: "Стационарность вокруг тренда", alternative_hypothesis: "Единичный корень", available: true, statistic: 0.05, p_value: 0.1, lags: 4, reject_null: false, supports_stationarity: true, critical_values: { "5%": 0.146 }, note: null },
    { id: "pp", label: "Phillips–Perron", null_hypothesis: "Единичный корень", alternative_hypothesis: "Стационарность вокруг уровня", available: true, statistic: -4.1, p_value: 0.001, lags: 12, reject_null: true, supports_stationarity: true, critical_values: { "5%": -2.9 }, note: null },
    { id: "zivot_andrews", label: "Zivot–Andrews", null_hypothesis: "Единичный корень с одним разрывом", alternative_hypothesis: "Стационарность с одним разрывом", available: true, statistic: -5.2, p_value: 0.02, lags: 2, reject_null: true, supports_stationarity: true, critical_values: { "5%": -4.8 }, note: "Кандидат разрыва: 60" },
  ],
  rolling: Array.from({ length: 24 }, (_, index) => ({
    index,
    label: `2024-01-${String(index + 1).padStart(2, "0")}T00:00:00`,
    value: Math.sin(index / 3),
    rolling_mean: index < 11 ? null : 0.1,
    rolling_std: index < 11 ? null : 0.8,
  })),
  rolling_sampled: false,
  rolling_original_count: 120,
  recommendations: ["ADF и KPSS согласованы."],
  warnings: [],
};


describe("EdaStationarityOverview", () => {
  it("switches four overview visualizations backed by one response", () => {
    render(<EdaStationarityOverview profile={PROFILE} loading={false} error={null} noDataset={false} parameters={{ alpha: 0.05, rollingWindow: 12 }} onParametersChange={jest.fn()} />);

    expect(screen.getByRole("img", { name: "Ряд и скользящее среднее для Price" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Скользящее σ" }));
    expect(screen.getByRole("img", { name: "Скользящее стандартное отклонение для Price" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "p-value" }));
    expect(screen.getByRole("img", { name: "Сопоставление p-value тестов стационарности для Price" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Таблица" }));
    expect(screen.getByRole("table", { name: "Результаты тестов стационарности" })).toBeInTheDocument();
    expect(screen.getByText("Phillips–Perron")).toBeInTheDocument();
  });

  it("updates alpha and rolling window without adding another target selector", () => {
    const onParametersChange = jest.fn();
    render(<EdaStationarityOverview profile={PROFILE} loading={false} error={null} noDataset={false} parameters={{ alpha: 0.05, rollingWindow: 12 }} onParametersChange={onParametersChange} />);

    fireEvent.change(screen.getByRole("combobox", { name: "Уровень значимости α" }), { target: { value: "0.01" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Окно скользящих статистик" }), { target: { value: "20" } });
    expect(onParametersChange).toHaveBeenCalledWith({ alpha: 0.01 });
    expect(onParametersChange).toHaveBeenCalledWith({ rollingWindow: 20 });
    expect(screen.queryByRole("combobox", { name: /исследуемый признак/i })).not.toBeInTheDocument();
  });

  it("shows an honest not-applicable state", () => {
    render(<EdaStationarityOverview profile={{ ...PROFILE, applicable: false, reason: "Временная сетка нерегулярна" }} loading={false} error={null} noDataset={false} parameters={{ alpha: 0.05, rollingWindow: 12 }} onParametersChange={jest.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("Временная сетка нерегулярна");
  });
});
