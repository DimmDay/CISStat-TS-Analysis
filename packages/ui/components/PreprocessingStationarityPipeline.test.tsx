import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { PreprocessingStationarityPipeline } from "./PreprocessingStationarityPipeline";


const RESPONSE = {
  applied: false, column: "Price", method: "first_difference", output_column: "Price_diff1",
  rows_before: 180, rows_after: 179, rows_dropped: 1, columns_before: 2, columns_after: 3,
  metadata: { kind: "stationarity", source_column: "Price", output_column: "Price_diff1", method: "first_difference", regular_order: 1, seasonal_order: 0, seasonal_period: null, domain_transform: null, causal: true, modeling_safe: true, inverse_supported: true, lost_observations: 1, fitted_on_n: 180, history_tail: [2.5], trend_intercept: null, trend_slope: null },
};


describe("PreprocessingStationarityPipeline", () => {
  it("previews row loss and applies only after confirmation", async () => {
    const onApplied = jest.fn();
    global.fetch = jest.fn()
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(RESPONSE) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ ...RESPONSE, applied: true }) });
    render(<PreprocessingStationarityPipeline column="Price" recommendedMethod="first_difference" seasonalPeriod={12} onApplied={onApplied} />);

    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр преобразования" }));
    expect(await screen.findByText(/Будет удалено начальных строк: 1/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Подтверждаю изменение активного датасета" }));
    fireEvent.click(screen.getByRole("button", { name: "Применить преобразование" }));
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
    expect(global.fetch).toHaveBeenLastCalledWith(
      expect.stringContaining("/dataset/preprocessing/stationarity-transformations"),
      expect.objectContaining({ method: "POST", body: expect.stringContaining('"apply":true') }),
    );
  });

  it("requires separate acknowledgement for full-history linear detrend", () => {
    global.fetch = jest.fn();
    render(<PreprocessingStationarityPipeline column="Price" recommendedMethod="first_difference" seasonalPeriod={12} onApplied={jest.fn()} />);
    fireEvent.change(screen.getByRole("combobox", { name: "Метод обеспечения стационарности" }), { target: { value: "linear_detrend" } });
    expect(screen.getByRole("checkbox", { name: "Подтверждаю некаузальный offline-detrend" })).toBeInTheDocument();
    expect(screen.getByText(/переоценить только на train/i)).toBeInTheDocument();
  });
});
