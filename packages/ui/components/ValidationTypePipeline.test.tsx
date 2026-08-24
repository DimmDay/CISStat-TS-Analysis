import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ValidationTypePipeline } from "./ValidationTypePipeline";
import type { ValidationTypeProfileItem } from "./ValidationTypeMatrix";

const PROFILE: ValidationTypeProfileItem[] = [
  { name: "Country", dtype: "object", type_icon: "categorical", non_null: 3, nulls: 0, unique: 3 },
  { name: "Price", dtype: "object", type_icon: "text", non_null: 3, nulls: 0, unique: 3 },
];

const PREVIEW_RESPONSE = {
  applied: false,
  invalid_policy: "reject",
  total_invalid: 1,
  target_column_reset: false,
  columns: [
    {
      column: "Price",
      from_dtype: "object",
      to_dtype: "Float64",
      converted_count: 2,
      invalid_count: 1,
      invalid_examples: ["bad"],
    },
  ],
  type_profile: PROFILE,
};

describe("ValidationTypePipeline", () => {
  beforeEach(() => {
    global.fetch = jest.fn();
  });

  it("renders the four-step correction algorithm with active controls", () => {
    render(<ValidationTypePipeline profile={PROFILE} onApplied={jest.fn()} />);

    expect(screen.getByRole("region", { name: "Мастер исправления типов" })).toBeInTheDocument();
    expect(screen.getByText("1. Выбор колонок")).toBeInTheDocument();
    expect(screen.getByText("2. Ожидаемые типы")).toBeInTheDocument();
    expect(screen.getByText("3. Предпросмотр")).toBeInTheDocument();
    expect(screen.getByText("4. Применение")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Выбрать колонку Price" })).toBeEnabled();
    expect(screen.getByRole("combobox", { name: "Целевой тип для Price" })).toBeEnabled();
    expect(screen.getByRole("combobox", { name: "Политика ошибок" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Сохранить эталон и проверить" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Предпросмотр изменений" })).toBeDisabled();
  });

  it("saves selected expected types as the session schema", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({
        saved: true,
        columns: [{ column: "Price", target_type: "float" }],
      }),
    });
    const onSchemaSaved = jest.fn();
    render(
      <ValidationTypePipeline
        profile={PROFILE}
        onApplied={jest.fn()}
        onSchemaSaved={onSchemaSaved}
      />
    );

    fireEvent.click(screen.getByRole("checkbox", { name: "Выбрать колонку Price" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Целевой тип для Price" }), {
      target: { value: "float" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить эталон и проверить" }));

    await waitFor(() => expect(onSchemaSaved).toHaveBeenCalledTimes(1));
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/v1/session/dataset/type-schema"),
      expect.objectContaining({
        method: "PUT",
        credentials: "include",
        body: JSON.stringify({
          columns: [{ column: "Price", target_type: "float" }],
        }),
      })
    );
    expect(screen.getByText("Эталон типов сохранён, проверка запущена")).toBeInTheDocument();
  });

  it("previews selected conversions and applies only after explicit confirmation", async () => {
    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(PREVIEW_RESPONSE) })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ ...PREVIEW_RESPONSE, applied: true, invalid_policy: "coerce" }),
      });
    const onApplied = jest.fn();
    render(<ValidationTypePipeline profile={PROFILE} onApplied={onApplied} />);

    fireEvent.click(screen.getByRole("checkbox", { name: "Выбрать колонку Price" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Целевой тип для Price" }), {
      target: { value: "float" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Политика ошибок" }), {
      target: { value: "coerce" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));

    await waitFor(() => expect(screen.getByText("Неприводимых значений: 1")).toBeInTheDocument());
    expect(screen.getByText(/bad/)).toBeInTheDocument();
    expect(global.fetch).toHaveBeenNthCalledWith(
      1,
      expect.stringContaining("/v1/session/dataset/convert-types"),
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        body: JSON.stringify({
          conversions: [{ column: "Price", target_type: "float" }],
          invalid_policy: "coerce",
          apply: false,
        }),
      })
    );

    const applyButton = screen.getByRole("button", { name: "Применить исправления" });
    expect(applyButton).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /Подтверждаю изменение активного датасета/i }));
    expect(applyButton).toBeEnabled();
    fireEvent.click(applyButton);

    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      expect.stringContaining("/v1/session/dataset/convert-types"),
      expect.objectContaining({ body: expect.stringContaining('"apply":true') })
    );
    expect(screen.getByText("Изменения применены к активному датасету")).toBeInTheDocument();
  });

  it("shows a backend rejection without marking the dataset as changed", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: false,
      json: () => Promise.resolve({ detail: "Колонка 'Price': 1 значений не удалось преобразовать" }),
    });
    const onApplied = jest.fn();
    render(<ValidationTypePipeline profile={PROFILE} onApplied={onApplied} />);

    fireEvent.click(screen.getByRole("checkbox", { name: "Выбрать колонку Price" }));
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("не удалось преобразовать");
    expect(onApplied).not.toHaveBeenCalled();
  });

  it("initializes suggested targets when the profile arrives after mount", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ ...PREVIEW_RESPONSE, total_invalid: 0 }),
    });
    const { rerender } = render(<ValidationTypePipeline profile={[]} onApplied={jest.fn()} />);

    rerender(<ValidationTypePipeline profile={PROFILE} onApplied={jest.fn()} />);
    fireEvent.click(screen.getByRole("checkbox", { name: "Выбрать колонку Price" }));
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));

    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/v1/session/dataset/convert-types"),
      expect.objectContaining({ body: expect.stringContaining('"target_type":"string"') })
    );
  });
});
