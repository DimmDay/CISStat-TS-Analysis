// packages/ui/components/PreprocessingOutliersManualEditor.test.tsx
//
// Оракулы ручного исправления выбросов (задача MANUAL-OUTLIERS-1,
// 2026-10-15): редактор датасета в окне «Мастер исправления выбросов»
// -- паттерн MANUAL-MISSING-1 с ДОБАВКАМИ постановки:
//
// (1) фильтры-чекбоксы «Только с выбросами» (дефолт, применён сразу --
//     legacy «Только выбросы» app.py ~8263) / «Весь датасет» (legacy
//     «Все») -- взаимоисключающие, кнопка «Выбрать» применяет фильтр
//     (перепросмотр окна с outliers_only=...), снятие обоих чекбоксов
//     блокирует «Выбрать»;
// (2) таблица -- виртуализированные окна GET /dataset/outlier-editor-rows
//     (пагинация offset/limit, кэш страниц); NaN -- пустой input (честно);
// (3) НОВОЕ -- ЦВЕТОВОЙ МАРКЕР изменённых ячеек: ячейка с несохранённой
//     правкой подсвечена (bg-amber-класс на input) -- аналитик видит
//     объем ручной работы до применения;
// (4) НОВОЕ -- кнопка «Сбросить» (рядом с «Применить», правый край):
//     отменяет НЕсохранённые правки (ячейки возвращаются к значениям
//     окна, маркеры снимаются), disabled без правок, сеть НЕ дёргает;
// (5) правки ячеек: input с aria-label «Строка N, колонка X»; правки
//     переживают смену фильтра; «Применить» активен только при наличии
//     правок; POST /dataset/outlier-manual-corrections {edits, apply:true}
//     (= функционал «Применить исправления» мастера: атомарная замена,
//     пересчёт профиля, каскад onApplied); числовая колонка с
//     неприводимым значением -- клиентская 422-стопа БЕЗ POST; успех --
//     «Изменения применены, профиль пересчитан» + счётчики, правки
//     сняты, onApplied вызван, окно перечитано;
// (6) ошибка apply -- role="alert", правки И маркеры СОХРАНЕНЫ
//     (аналитик не теряет работу).
//
// Корпус дизъюнктен существующим сюитам: датасет «метеостанция с
// выбросами» (dataset_id manual-outliers-1), колонки
// recorded_at/temp_c/humidity, свои ответы всех маршрутов.

import "@testing-library/jest-dom";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { PreprocessingOutliersManualEditor } from "./PreprocessingOutliersManualEditor";

const EDITOR_COLUMNS = [
  { column: "recorded_at", dtype: "object", semantic: "text" },
  { column: "temp_c", dtype: "float64", semantic: "numeric" },
  { column: "humidity", dtype: "float64", semantic: "numeric" },
];

function page0() {
  return {
    columns: EDITOR_COLUMNS,
    rows: [
      { row_index: 1, cells: ["2024-06-02", 41.0, 61.5] },
      { row_index: 8, cells: ["2024-06-09", -8.0, null] },
    ],
    offset: 0,
    limit: 200,
    total_rows: 2,
    returned: 2,
    has_more: false,
  };
}

function page0All() {
  return {
    columns: EDITOR_COLUMNS,
    rows: [
      { row_index: 0, cells: ["2024-06-01", 12.5, 58.0] },
      { row_index: 1, cells: ["2024-06-02", 41.0, 61.5] },
      { row_index: 2, cells: ["2024-06-03", 13.1, null] },
    ],
    offset: 0,
    limit: 200,
    total_rows: 3,
    returned: 3,
    has_more: false,
  };
}

function renderEditor(onApplied = jest.fn()) {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const applied = jest.fn();
  global.fetch = jest.fn((url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (url.includes("/dataset/outlier-editor-rows")) {
      const outliersOnly = url.includes("outliers_only=true");
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(outliersOnly ? page0() : page0All()),
      });
    }
    if (url.includes("/dataset/outlier-manual-corrections")) {
      const body = JSON.parse(String(init?.body ?? "{}"));
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            applied: true,
            total_edited_requested: body.edits.length,
            total_changed: body.edits.length,
            total_outliers_before: 2,
            total_outliers_after: 2 - body.edits.length,
            profile: [],
          }),
      });
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({ detail: "not found" }) });
  }) as unknown as typeof fetch;
  render(<PreprocessingOutliersManualEditor onApplied={applied} />);
  return { calls, applied };
}

function cellInput(rowIndex: number, column: string): HTMLInputElement {
  // aria-label ячейки -- позиция 1-based (row_index + 1), как в ведущей
  // колонке № редактора.
  return screen.getByLabelText(`Строка ${rowIndex + 1}, колонка ${column}`) as HTMLInputElement;
}

const APPLY_BUTTON = "Применить";
const SELECT_BUTTON = "Выбрать";
const RESET_BUTTON = "Сбросить";

describe("PreprocessingOutliersManualEditor (MANUAL-OUTLIERS-1)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("renders filter checkboxes with 'Только с выбросами' applied by default and honest buttons", async () => {
    const { calls } = renderEditor();
    const outliersBox = screen.getByLabelText("Только с выбросами") as HTMLInputElement;
    const allBox = screen.getByLabelText("Весь датасет") as HTMLInputElement;
    expect(outliersBox.checked).toBe(true);
    expect(allBox.checked).toBe(false);
    expect(screen.getByRole("button", { name: SELECT_BUTTON })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: APPLY_BUTTON })).toBeDisabled(); // правок ещё нет
    expect(screen.getByRole("button", { name: RESET_BUTTON })).toBeDisabled(); // сбрасывать нечего
    // стартовое окно -- фильтр «Только с выбросами» применён сразу
    await waitFor(() => {
      expect(calls.some((c) => c.url.includes("/dataset/outlier-editor-rows"))).toBe(true);
    });
    expect(calls.some((c) => c.url.includes("outliers_only=true"))).toBe(true);
    // значения -- числа окна; NaN -- пустой input
    await waitFor(() => {
      expect(cellInput(1, "temp_c").value).toBe("41");
    });
    expect(cellInput(8, "temp_c").value).toBe("-8");
    expect(cellInput(8, "humidity").value).toBe("");
  });

  it("checkboxes are mutually exclusive; 'Выбрать' applies pending filter and refetches with outliers_only=false", async () => {
    const { calls } = renderEditor();
    await screen.findByLabelText("Строка 2, колонка temp_c");

    fireEvent.click(screen.getByLabelText("Весь датасет"));
    const outliersBox = screen.getByLabelText("Только с выбросами") as HTMLInputElement;
    const allBox = screen.getByLabelText("Весь датасет") as HTMLInputElement;
    expect(allBox.checked).toBe(true);
    expect(outliersBox.checked).toBe(false); // взаимоисключающие

    const before = calls.length;
    fireEvent.click(screen.getByRole("button", { name: SELECT_BUTTON }));
    await waitFor(() => {
      expect(calls.slice(before).some((c) => c.url.includes("outliers_only=false"))).toBe(true);
    });
    // окно «Весь датасет» отрисовано
    expect(await screen.findByLabelText("Строка 1, колонка temp_c")).toBeInTheDocument();

    // клик по ЧЕКНУТОМУ чекбоксу снимает чек (честная checkbox-семантика:
    // оба сняты -- «Выбрать» блокируется, пока не выбран фильтр)
    fireEvent.click(screen.getByLabelText("Весь датасет"));
    expect((screen.getByLabelText("Весь датасет") as HTMLInputElement).checked).toBe(false);
    expect((screen.getByLabelText("Только с выбросами") as HTMLInputElement).checked).toBe(false);
    expect(screen.getByRole("button", { name: SELECT_BUTTON })).toBeDisabled();
  });

  it("edited cell gets the COLOR MARKER (bg-amber class) and enables 'Применить'/'Сбросить'", async () => {
    renderEditor();
    const input = await screen.findByLabelText("Строка 2, колонка temp_c");
    // до правки маркера нет
    expect(input.className).not.toContain("bg-amber");

    fireEvent.change(input, { target: { value: "13.3" } });
    const marked = cellInput(1, "temp_c");
    // ЦВЕТОВОЙ МАРКЕР: изменённая ячейка подсвечена
    expect(marked.value).toBe("13.3");
    expect(marked.className).toContain("bg-amber");
    expect(screen.getByRole("button", { name: APPLY_BUTTON })).toBeEnabled();
    expect(screen.getByRole("button", { name: RESET_BUTTON })).toBeEnabled();

    // соседняя ячейка без правки -- без маркера
    expect(cellInput(1, "humidity").className).not.toContain("bg-amber");
  });

  it("'Сбросить' cancels pending edits: values restored, markers gone, buttons honest, NO post", async () => {
    const { calls } = renderEditor();
    const input = await screen.findByLabelText("Строка 2, колонка temp_c");
    fireEvent.change(input, { target: { value: "13.3" } });
    expect(cellInput(1, "temp_c").className).toContain("bg-amber");

    fireEvent.click(screen.getByRole("button", { name: RESET_BUTTON }));
    // значение вернулось к окну, маркер снят
    expect(cellInput(1, "temp_c").value).toBe("41");
    expect(cellInput(1, "temp_c").className).not.toContain("bg-amber");
    // кнопки честно погасли, сеть НЕ дёрнулась
    expect(screen.getByRole("button", { name: APPLY_BUTTON })).toBeDisabled();
    expect(screen.getByRole("button", { name: RESET_BUTTON })).toBeDisabled();
    expect(calls.some((c) => c.url.includes("/dataset/outlier-manual-corrections"))).toBe(false);
  });

  it("edits a cell, POSTs edits with apply:true, clears edits and calls onApplied", async () => {
    const { calls, applied } = renderEditor();
    const input = await screen.findByLabelText("Строка 2, колонка temp_c");

    fireEvent.change(input, { target: { value: "13.3" } });
    fireEvent.click(screen.getByRole("button", { name: APPLY_BUTTON }));
    await waitFor(() => {
      expect(screen.getByText("Изменения применены, профиль пересчитан")).toBeInTheDocument();
    });
    const post = calls.find((c) => c.url.includes("/dataset/outlier-manual-corrections"));
    expect(post).toBeDefined();
    const body = JSON.parse(String(post!.init?.body));
    expect(body.apply).toBe(true);
    expect(body.edits).toEqual([{ row_index: 1, column: "temp_c", value: 13.3 }]);
    expect(applied).toHaveBeenCalledTimes(1); // каскад мастера (datasetVersion)
    // правка снята, маркер снят, input перечитан из окна (мок отдаёт ту же
    // страницу -- значение правки ушло)
    await waitFor(() => {
      expect(cellInput(1, "temp_c").value).toBe("41");
    });
    expect(cellInput(1, "temp_c").className).not.toContain("bg-amber");
    expect(screen.getByRole("button", { name: APPLY_BUTTON })).toBeDisabled();
    expect(screen.getByRole("button", { name: RESET_BUTTON })).toBeDisabled();
  });

  it("apply success shows honest outlier counters from the response", async () => {
    renderEditor();
    const input = await screen.findByLabelText("Строка 2, колонка temp_c");
    fireEvent.change(input, { target: { value: "13.3" } });
    fireEvent.click(screen.getByRole("button", { name: APPLY_BUTTON }));
    await waitFor(() => {
      // честные счётчики кард-шкалы из ответа (выбросов до → после)
      expect(screen.getByText(/Выбросов: 2 → 1/)).toBeInTheDocument();
    });
  });

  it("empty edit value is sent as null (honest clearing to NaN)", async () => {
    const { calls } = renderEditor();
    // humidity строки 2 -- NaN (пустой input в окне «Весь датасет»)
    fireEvent.click(screen.getByLabelText("Весь датасет"));
    fireEvent.click(screen.getByRole("button", { name: SELECT_BUTTON }));
    const input = (await screen.findByLabelText("Строка 3, колонка humidity")) as HTMLInputElement;
    expect(input.value).toBe("");
    // вписали и стёрли = очистка
    fireEvent.change(input, { target: { value: "55" } });
    fireEvent.change(input, { target: { value: "" } });

    fireEvent.click(screen.getByRole("button", { name: APPLY_BUTTON }));
    await waitFor(() => {
      expect(calls.some((c) => c.url.includes("/dataset/outlier-manual-corrections"))).toBe(true);
    });
    const post = calls.find((c) => c.url.includes("/dataset/outlier-manual-corrections"));
    const body = JSON.parse(String(post!.init?.body));
    expect(body.edits).toEqual([{ row_index: 2, column: "humidity", value: null }]);
  });

  it("invalid numeric value stops client-side with honest error and NO post", async () => {
    const { calls } = renderEditor();
    const input = await screen.findByLabelText("Строка 2, колонка temp_c"); // numeric
    fireEvent.change(input, { target: { value: "abc" } });
    fireEvent.click(screen.getByRole("button", { name: APPLY_BUTTON }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/не является числом/);
    });
    expect(calls.some((c) => c.url.includes("/dataset/outlier-manual-corrections"))).toBe(false);
  });

  it("apply error keeps edits and markers (analyst does not lose work) and shows backend detail", async () => {
    const failing = jest.fn((url: string, init?: RequestInit) => {
      if (url.includes("/dataset/outlier-manual-corrections")) {
        return Promise.resolve({
          ok: false,
          status: 422,
          json: () => Promise.resolve({ detail: "Значение 'abc' в колонке 'temp_c' (строка 2) не приводится к числу" }),
        });
      }
      if (url.includes("/dataset/outlier-editor-rows")) {
        const outliersOnly = url.includes("outliers_only=true");
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(outliersOnly ? page0() : page0All()),
        });
      }
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({ detail: "not found" }) });
    }) as unknown as typeof fetch;
    global.fetch = failing;
    render(<PreprocessingOutliersManualEditor onApplied={jest.fn()} />);

    const input = await screen.findByLabelText("Строка 2, колонка temp_c");
    fireEvent.change(input, { target: { value: "13.3" } });
    fireEvent.click(screen.getByRole("button", { name: APPLY_BUTTON }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/не приводится к числу/);
    });
    // правка сохранена в поле, маркер жив (аналитик не теряет работу)
    expect(cellInput(1, "temp_c").value).toBe("13.3");
    expect(cellInput(1, "temp_c").className).toContain("bg-amber");
    expect(screen.getByRole("button", { name: APPLY_BUTTON })).toBeEnabled();
  });

  it("edits survive filter switch and are all sent on apply", async () => {
    const { calls } = renderEditor();
    const input = await screen.findByLabelText("Строка 2, колонка temp_c");
    fireEvent.change(input, { target: { value: "13.3" } });

    // переключили фильтр на «Весь датасет» и применили
    fireEvent.click(screen.getByLabelText("Весь датасет"));
    fireEvent.click(screen.getByRole("button", { name: SELECT_BUTTON }));
    const allInput = (await screen.findByLabelText("Строка 1, колонка temp_c")) as HTMLInputElement;
    expect(allInput.value).toBe("12.5"); // окно всего датасета

    // правка строки 1 пережила смену фильтра (маркер жив)
    expect(cellInput(1, "temp_c").value).toBe("13.3");
    expect(cellInput(1, "temp_c").className).toContain("bg-amber");

    fireEvent.click(screen.getByRole("button", { name: APPLY_BUTTON }));
    await waitFor(() => {
      expect(calls.some((c) => c.url.includes("/dataset/outlier-manual-corrections"))).toBe(true);
    });
    const post = calls.find((c) => c.url.includes("/dataset/outlier-manual-corrections"));
    const body = JSON.parse(String(post!.init?.body));
    expect(body.edits).toEqual([{ row_index: 1, column: "temp_c", value: 13.3 }]);
  });

  it("shows honest row-window status footer", async () => {
    renderEditor();
    await screen.findByLabelText("Строка 2, колонка temp_c");
    expect(screen.getByText(/Строки 1–2 из 2/)).toBeInTheDocument();
  });
});
