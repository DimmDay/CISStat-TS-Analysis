import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PreprocessingScalingPipeline } from "./PreprocessingScalingPipeline";
import type { ScalingProfile } from "./PreprocessingScalingOverview";


const profile = {
  target_column: "Price", applicable: true, n_observations: 100,
  suggested_columns: ["Volume", "Temperature"], recommended_method: "standard",
  columns: [
    { name: "Price", eligible: true, recommended: false, binary: false, constant: false, role: "target", exclusion_reason: null },
    { name: "Volume", eligible: true, recommended: true, binary: false, constant: false, role: "source", exclusion_reason: null },
    { name: "Temperature", eligible: true, recommended: true, binary: false, constant: false, role: "source", exclusion_reason: null },
  ],
} as ScalingProfile;


describe("PreprocessingScalingPipeline", () => {
  beforeEach(() => {
    global.fetch = jest.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ applied: false, method: "standard", columns: ["Volume", "Temperature"], metrics: [{ column: "Volume", mean_after: 0, std_after: 1 }], warnings: [] }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ applied: true, method: "standard", columns: ["Volume", "Temperature"], metrics: [{ column: "Volume", mean_after: 0, std_after: 1 }], warnings: [] }) });
  });

  it("previews then separately saves a fold-safe recipe", async () => {
    const onApplied = jest.fn();
    render(<PreprocessingScalingPipeline targetColumn="Price" profile={profile} onApplied={onApplied} />);

    fireEvent.click(screen.getByRole("button", { name: "Проверить рецепт" }));
    await screen.findByText(/Колонок в рецепте: 2/);
    fireEvent.click(screen.getByLabelText("Подтверждаю сохранение рецепта"));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить рецепт" }));
    await waitFor(() => expect(onApplied).toHaveBeenCalled());
    expect(JSON.parse((global.fetch as jest.Mock).mock.calls[0][1].body)).toMatchObject({
      target_column: "Price", columns: ["Volume", "Temperature"], method: "standard", apply: false,
    });
    expect(screen.getByText(/fit выполняется заново внутри каждого train-fold/i)).toBeInTheDocument();
  });

  it("requires a separate acknowledgement for nonlinear quantile mapping", async () => {
    render(<PreprocessingScalingPipeline targetColumn="Price" profile={profile} onApplied={jest.fn()} />);
    fireEvent.change(screen.getByLabelText("Метод масштабирования"), { target: { value: "quantile" } });
    expect(screen.getByLabelText(/Разрешаю нелинейное ранговое преобразование/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Проверить рецепт" })).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/Разрешаю нелинейное ранговое преобразование/i));
    expect(screen.getByRole("button", { name: "Проверить рецепт" })).toBeEnabled();
  });
});

