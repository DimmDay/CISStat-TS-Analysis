import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";

import {
  EdaStructuralBreaksOverview,
  type EdaStructuralBreaksResponse,
} from "./EdaStructuralBreaksOverview";


const PROFILE: EdaStructuralBreaksResponse = {
  column: "Price", applicable: true, reason: null, n_observations: 180, missing_count: 0,
  min_observations: 60, alpha: 0.05, requested_min_segment: 20, min_segment: 20,
  requested_penalty_multiplier: 2, penalty_multiplier: 2, penalty_value: 1.8,
  max_breaks: 10, jump: 1, model: "piecewise_linear", status: "breaks_detected",
  break_count: 1, supported_count: 1, order_source: "time_column", order_column: "Date",
  order_warning: null, frequency: "D", cusum: { statistic: 2.1, p_value: 0.001, reject_stability: true, critical_values: { "5%": 1.36 } },
  candidates: [{ rank: 1, index: 90, label: "2024-03-31T00:00:00", level_change: 3, standardized_level_change: 1.9, slope_before: 0.001, slope_after: 0.002, slope_change: 0.001, rss_gain: 0.88, chow_statistic: 340, p_value: 0.0001, adjusted_p_value: 0.0001, stability_support: 1, supported: true }],
  segments: [
    { id: 1, start_index: 0, end_index: 89, start_label: "2024-01-01T00:00:00", end_label: "2024-03-30T00:00:00", n_observations: 90, mean: 0, std: 0.2, slope: 0.001 },
    { id: 2, start_index: 90, end_index: 179, start_label: "2024-03-31T00:00:00", end_label: "2024-06-28T00:00:00", n_observations: 90, mean: 3, std: 0.2, slope: 0.002 },
  ],
  series: [{ index: 0, label: "2024-01-01T00:00:00", value: 0.1, fitted: 0, segment_id: 1 }, { index: 90, label: "2024-03-31T00:00:00", value: 3.1, fitted: 3, segment_id: 2 }],
  cusum_path: [{ index: 0, label: "2024-01-01T00:00:00", value: 0.1, upper: 1.36, lower: -1.36 }, { index: 90, label: "2024-03-31T00:00:00", value: 2.1, upper: 1.36, lower: -1.36 }],
  sensitivity: [{ penalty_multiplier: 1, index: 90, label: "2024-03-31T00:00:00" }, { penalty_multiplier: 2, index: 90, label: "2024-03-31T00:00:00" }],
  series_sampled: false, series_original_count: 180, cusum_sampled: false,
  recommendation: "Устойчивый структурный сдвиг около 2024-03-31.",
  recommendations: ["Проверьте модели по режимам."],
  warnings: ["Chow после выбора PELT является диагностикой."],
};


describe("EdaStructuralBreaksOverview", () => {
  it("switches five overview views backed by one response", () => {
    render(<EdaStructuralBreaksOverview profile={PROFILE} loading={false} error={null} noDataset={false} parameters={{ alpha: 0.05, minSegment: 20, penaltyMultiplier: 2 }} onParametersChange={jest.fn()} />);

    expect(screen.getByRole("img", { name: "Режимы и структурные сдвиги для Price" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "CUSUM" }));
    expect(screen.getByRole("img", { name: "CUSUM-диагностика для Price" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Чувствительность" }));
    expect(screen.getByRole("img", { name: "Устойчивость точек PELT для Price" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Сегменты" }));
    expect(screen.getByRole("table", { name: "Сегменты ряда" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Кандидаты" }));
    expect(screen.getByRole("table", { name: "Кандидаты структурных сдвигов" })).toBeInTheDocument();
  });

  it("updates method parameters without duplicating the shared target selector", () => {
    const onParametersChange = jest.fn();
    render(<EdaStructuralBreaksOverview profile={PROFILE} loading={false} error={null} noDataset={false} parameters={{ alpha: 0.05, minSegment: 20, penaltyMultiplier: 2 }} onParametersChange={onParametersChange} />);

    fireEvent.change(screen.getByRole("combobox", { name: "Уровень значимости α" }), { target: { value: "0.01" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Минимальная длина сегмента" }), { target: { value: "30" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Штраф PELT" }), { target: { value: "3" } });
    expect(onParametersChange).toHaveBeenCalledWith({ alpha: 0.01 });
    expect(onParametersChange).toHaveBeenCalledWith({ minSegment: 30 });
    expect(onParametersChange).toHaveBeenCalledWith({ penaltyMultiplier: 3 });
    expect(screen.queryByRole("combobox", { name: /исследуемый признак/i })).not.toBeInTheDocument();
  });

  it("shows an honest not-applicable state", () => {
    render(<EdaStructuralBreaksOverview profile={{ ...PROFILE, applicable: false, reason: "Временная сетка нерегулярна" }} loading={false} error={null} noDataset={false} parameters={{ alpha: 0.05, minSegment: 20, penaltyMultiplier: 2 }} onParametersChange={jest.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("Временная сетка нерегулярна");
  });
});

describe("EdaStructuralBreaksOverview: интеграция раскрытия графиков (Task 97.2, spec_max_graf_fix.md §7.3)", () => {
  const P = { profile: PROFILE, loading: false, error: null, noDataset: false, parameters: { alpha: 0.05, minSegment: 20, penaltyMultiplier: 2 }, onParametersChange: jest.fn() };

  it("раскрытие перекрывает Обзор, корень переключает overflow, Esc возвращает", () => {
    const { container } = render(<EdaStructuralBreaksOverview {...P} />);

    const section = container.querySelector("section");
    expect(section).not.toBeNull();
    // правки A+C в свёрнутом состоянии
    expect(section).toHaveClass("relative", "overflow-y-auto");
    expect(section).not.toHaveClass("overflow-hidden");

    fireEvent.click(screen.getByRole("button", { name: "Развернуть график до размера окна Обзора" }));

    // правка C: при раскрытом графике скролл корня выключен
    expect(section).toHaveClass("overflow-hidden");
    expect(section).not.toHaveClass("overflow-y-auto");
    const expandedPanel = container.querySelector("section > .absolute");
    expect(expandedPanel).not.toBeNull();
    expect(expandedPanel).toHaveClass("inset-0", "z-20");

    fireEvent.keyDown(window, { key: "Escape" });

    expect(section).toHaveClass("overflow-y-auto");
    expect(section).not.toHaveClass("overflow-hidden");
    expect(container.querySelector("section > .absolute")).toBeNull();
  });

  it("повторный клик по бейджу схлопывает график (toggle, без Esc)", () => {
    const { container } = render(<EdaStructuralBreaksOverview {...P} />);

    fireEvent.click(screen.getByRole("button", { name: "Развернуть график до размера окна Обзора" }));
    expect(container.querySelector("section")).toHaveClass("overflow-hidden");

    fireEvent.click(screen.getByRole("button", { name: "Свернуть график" }));

    expect(container.querySelector("section")).toHaveClass("overflow-y-auto");
    expect(container.querySelector("section > .absolute")).toBeNull();
  });
});
