import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { PreprocessingSmoothingPipeline } from "./PreprocessingSmoothingPipeline";


const RESPONSE = {
  applied: false, column: "Price", method: "ema", output_column: "Price_ema",
  rows_before: 96, rows_after: 96, columns_before: 2, columns_after: 3,
  metadata: { kind: "smoothing", source_column: "Price", method: "ema", parameters: { span: 7 }, causal: true, modeling_safe: true, inverse_supported: false, fitted_on_n: 96 },
};


describe("PreprocessingSmoothingPipeline", () => {
  it("previews on a copy and applies only after confirmation", async () => {
    const onApplied = jest.fn();
    global.fetch = jest.fn()
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(RESPONSE) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ ...RESPONSE, applied: true }) });
    render(<PreprocessingSmoothingPipeline column="Price" recommendedMethod="ema" onApplied={onApplied} />);

    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр сглаживания" }));
    expect(await screen.findByText(/Price_ema/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Подтверждаю добавление сглаженной колонки" }));
    fireEvent.click(screen.getByRole("button", { name: "Добавить сглаженную колонку" }));
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
    expect(global.fetch).toHaveBeenLastCalledWith(
      expect.stringContaining("/dataset/preprocessing/smoothing-transformations"),
      expect.objectContaining({ method: "POST", body: expect.stringContaining('"apply":true') }),
    );
  });

  it("requires a separate leakage acknowledgement for offline methods", () => {
    global.fetch = jest.fn();
    render(<PreprocessingSmoothingPipeline column="Price" recommendedMethod="ema" onApplied={jest.fn()} />);
    fireEvent.change(screen.getByRole("combobox", { name: "Метод сглаживания" }), { target: { value: "lowess" } });
    expect(screen.getByRole("checkbox", { name: "Подтверждаю некаузальный offline-режим" })).toBeInTheDocument();
    expect(screen.getByText(/будущие наблюдения/i)).toBeInTheDocument();
  });
});
