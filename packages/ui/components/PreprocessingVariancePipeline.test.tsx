import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { PreprocessingVariancePipeline } from "./PreprocessingVariancePipeline";


const RESPONSE = {
  applied: false, column: "Price", method: "box_cox", lambda_value: 0.2,
  output_column: "Price_box_cox", rows_before: 96, rows_after: 96,
  columns_before: 2, columns_after: 3,
  metadata: { source_column: "Price", method: "box_cox", lambda_value: 0.2, inverse_supported: true, fitted_on_n: 96 },
};

describe("PreprocessingVariancePipeline", () => {
  it("previews on a copy and applies only after confirmation", async () => {
    const onApplied = jest.fn();
    global.fetch = jest.fn()
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(RESPONSE) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ ...RESPONSE, applied: true }) });
    render(<PreprocessingVariancePipeline column="Price" recommendedMethod="box_cox" onApplied={onApplied} />);

    expect(screen.getByRole("combobox", { name: "Метод трансформации" })).toHaveValue("box_cox");
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    expect(await screen.findByText(/Price_box_cox/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Подтверждаю добавление трансформированной колонки" }));
    fireEvent.click(screen.getByRole("button", { name: "Добавить колонку" }));
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
    expect(global.fetch).toHaveBeenLastCalledWith(
      expect.stringContaining("/dataset/preprocessing/variance-transformations"),
      expect.objectContaining({ method: "POST", body: expect.stringContaining('"apply":true') }),
    );
  });

  it("offers manual lambda only for power transforms", () => {
    global.fetch = jest.fn();
    render(<PreprocessingVariancePipeline column="Price" recommendedMethod="box_cox" onApplied={jest.fn()} />);
    expect(screen.getByRole("checkbox", { name: "Подбирать λ автоматически по MLE" })).toBeChecked();
    fireEvent.click(screen.getByRole("checkbox", { name: "Подбирать λ автоматически по MLE" }));
    expect(screen.getByRole("spinbutton", { name: "Значение λ" })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Метод трансформации" }), { target: { value: "log" } });
    expect(screen.queryByRole("checkbox", { name: "Подбирать λ автоматически по MLE" })).not.toBeInTheDocument();
  });
});
