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
});
