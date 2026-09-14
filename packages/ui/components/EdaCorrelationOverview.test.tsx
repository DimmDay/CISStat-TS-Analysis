import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";

import {
  EdaCorrelationOverview,
  type EdaCorrelationResponse,
} from "./EdaCorrelationOverview";


const PROFILE: EdaCorrelationResponse = {
  column: "Price",
  applicable: true,
  reason: null,
  n_observations: 80,
  missing_count: 0,
  requested_max_lags: 20,
  max_lag: 2,
  alpha: 0.05,
  order_source: "time_column",
  order_column: "Date",
  order_warning: null,
  frequency: "D",
  acf: [
    { lag: 0, value: 1, confidence_lower: -0.2, confidence_upper: 0.2, significant: false },
    { lag: 1, value: 0.72, confidence_lower: -0.2, confidence_upper: 0.2, significant: true },
    { lag: 2, value: 0.31, confidence_lower: -0.25, confidence_upper: 0.25, significant: true },
  ],
  pacf: [
    { lag: 0, value: 1, confidence_lower: -0.2, confidence_upper: 0.2, significant: false },
    { lag: 1, value: 0.7, confidence_lower: -0.2, confidence_upper: 0.2, significant: true },
    { lag: 2, value: 0.04, confidence_lower: -0.2, confidence_upper: 0.2, significant: false },
  ],
  significant_acf_lags: [1, 2],
  significant_pacf_lags: [1],
  ljung_box_lag: 10,
  ljung_box_pvalue: 0.001,
  is_white_noise: false,
  suggested_p: 1,
  suggested_q: 2,
};


describe("EdaCorrelationOverview", () => {
  it("fills the workspace with charts while preserving the scrollable table layout", () => {
    render(
      <EdaCorrelationOverview
        profile={PROFILE}
        loading={false}
        error={null}
        noDataset={false}
        maxLags={20}
        onMaxLagsChange={jest.fn()}
      />,
    );

    const chart = screen.getByRole("img", { name: "График ACF для Price" });
    expect(chart).toHaveClass("min-h-0", "flex-1");
    expect(chart).not.toHaveClass("h-[275px]");
    expect(chart.closest("section")).toHaveClass("flex", "overflow-y-auto", "feed-scroll");

    fireEvent.click(screen.getByRole("tab", { name: "Таблица" }));
    const tableSection = screen.getByRole("table", { name: "Значения ACF и PACF по лагам" }).closest("section");
    expect(tableSection).toHaveClass("overflow-y-auto");
    expect(screen.getByRole("table", { name: "Значения ACF и PACF по лагам" }).parentElement).toHaveClass("shrink-0");
  });

  it("switches between ACF, PACF and lag table views", () => {
    render(
      <EdaCorrelationOverview
        profile={PROFILE}
        loading={false}
        error={null}
        noDataset={false}
        maxLags={20}
        onMaxLagsChange={jest.fn()}
      />,
    );

    expect(screen.getByRole("img", { name: "График ACF для Price" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "PACF" }));
    expect(screen.getByRole("img", { name: "График PACF для Price" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Таблица" }));
    expect(screen.getByRole("table", { name: "Значения ACF и PACF по лагам" })).toBeInTheDocument();
    expect(screen.getAllByText("Значимая", { selector: "span" }).length).toBeGreaterThan(0);
  });

  it("lets the analyst request another lag horizon", () => {
    const onMaxLagsChange = jest.fn();
    render(
      <EdaCorrelationOverview
        profile={PROFILE}
        loading={false}
        error={null}
        noDataset={false}
        maxLags={20}
        onMaxLagsChange={onMaxLagsChange}
      />,
    );

    fireEvent.change(screen.getByRole("combobox", { name: "Максимальный лаг" }), {
      target: { value: "40" },
    });
    expect(onMaxLagsChange).toHaveBeenCalledWith(40);
  });

  it("shows an honest not-applicable reason", () => {
    render(
      <EdaCorrelationOverview
        profile={{ ...PROFILE, applicable: false, reason: "Панельные данные требуют выбора сущности" }}
        loading={false}
        error={null}
        noDataset={false}
        maxLags={20}
        onMaxLagsChange={jest.fn()}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("Панельные данные");
  });

  it("renders transport errors without fabricated values", () => {
    render(
      <EdaCorrelationOverview
        profile={null}
        loading={false}
        error="Не удалось рассчитать корреляцию"
        noDataset={false}
        maxLags={20}
        onMaxLagsChange={jest.fn()}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Не удалось рассчитать корреляцию");
  });

  // Task w/n-4: бейдж-паттерн переключателей представлений «Обзора»
  // вкладки «Предобработка» (эталон «Генерации признаков») — tablist
  // внутри шапки Обзора (p-4 с border-b), mt-3 flex flex-wrap gap-2;
  // геометрия эталона px-3 py-1 text-xs; активный border-neutral-300
  // bg-neutral-200 text-neutral-800, неактивный border-neutral-200
  // bg-neutral-50 text-neutral-500 hover:bg-neutral-100.
  it("переключатели представлений следуют бейдж-паттерну «Обзора» «Предобработки»", () => {
    render(
      <EdaCorrelationOverview
        profile={PROFILE}
        loading={false}
        error={null}
        noDataset={false}
        maxLags={20}
        onMaxLagsChange={jest.fn()}
      />,
    );

    const tablist = screen.getByRole("tablist", { name: "Представления корреляционной структуры" });
    expect(tablist).toHaveClass("mt-3", "flex", "flex-wrap", "gap-2");
    expect(tablist.parentElement).toHaveClass("p-4");
    expect(tablist.parentElement?.className).toContain("border-b border-neutral-100");

    const active = screen.getByRole("tab", { name: "ACF" });
    expect(active).toHaveAttribute("aria-selected", "true");
    expect(active).toHaveClass("rounded-full", "border", "px-3", "py-1", "text-xs");
    expect(active).toHaveClass("border-neutral-300", "bg-neutral-200", "text-neutral-800");

    const inactive = screen.getByRole("tab", { name: "PACF" });
    expect(inactive).toHaveAttribute("aria-selected", "false");
    expect(inactive).toHaveClass("rounded-full", "border", "px-3", "py-1", "text-xs");
    expect(inactive).toHaveClass("border-neutral-200", "bg-neutral-50", "text-neutral-500", "hover:bg-neutral-100");
  });
});
