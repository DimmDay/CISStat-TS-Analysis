import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { PreprocessingDecompositionPipeline } from "./PreprocessingDecompositionPipeline";


const PROFILE = {
  column: "Price", date_column: "Date", applicable: true, reason: null,
  method: "STL" as const, robust: true, frequency: "MS", period: 12,
  n_points: 60, sampled: false, original_count: 60, trend_strength: 0.9,
  seasonal_strength: 0.8, residual_mean: 0, residual_std: 1,
  ljung_box_lag: 12, ljung_box_pvalue: 0.2, jarque_bera_pvalue: 0.1,
  points: [], seasonal_pattern: [], residual_acf: [], warnings: [],
  recommendation: "ok", methodology_note: "STL",
};

const RESPONSE = {
  applied: false, period: 12, rows_before: 60, rows_after: 60,
  columns_before: 2, columns_after: 5,
  added_columns: ["Price_trend", "Price_seasonal", "Price_resid"],
};

describe("PreprocessingDecompositionPipeline", () => {
  it("previews on a copy and applies only after confirmation", async () => {
    const onApplied = jest.fn();
    global.fetch = jest.fn()
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(RESPONSE) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ ...RESPONSE, applied: true }) });
    render(<PreprocessingDecompositionPipeline column="Price" profile={PROFILE} onApplied={onApplied} />);

    expect(screen.getByRole("spinbutton", { name: "Сезонный период" })).toHaveValue(12);
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    expect(await screen.findByText(/Price_trend/)).toBeInTheDocument();
    expect(onApplied).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("checkbox", { name: "Подтверждаю добавление колонок декомпозиции" }));
    fireEvent.click(screen.getByRole("button", { name: "Добавить колонки" }));
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
    expect(global.fetch).toHaveBeenLastCalledWith(
      expect.stringContaining("/dataset/preprocessing/decomposition-outputs"),
      expect.objectContaining({ method: "POST", body: expect.stringContaining('"apply":true') }),
    );
  });

  it("does not allow a request without selected outputs", () => {
    global.fetch = jest.fn();
    render(<PreprocessingDecompositionPipeline column="Price" profile={PROFILE} onApplied={jest.fn()} />);
    fireEvent.click(screen.getByRole("checkbox", { name: "Компоненты" }));
    expect(screen.getByRole("button", { name: "Предпросмотр изменений" })).toBeDisabled();
  });
});
