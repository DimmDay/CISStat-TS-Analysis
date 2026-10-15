// packages/ui/components/PreprocessingMissingManualEditor.test.tsx
//
// Оракулы ручного исправления пропусков (задача MANUAL-MISSING-1,
// 2026-10-15): редактор датасета в окне «Мастер исправления пропусков».
//
// Контракт:
// (1) фильтры-чекбоксы «Только с пропусками» (дефолт, применён сразу) /
//     «Весь датасет» -- взаимоисключающие, клик по чекнутому сохраняет
//     чек (pending-состояние), кнопка «Выбрать» применяет фильтр
//     (перепросмотр окна с missing_only=...), снятие обоих чекбоксов
//     блокирует «Выбрать»;
// (2) таблица -- виртуализированные окна GET /dataset/missing-editor-rows
//     (пагинация offset/limit, кэш страниц, ползунок на все строки
//     области фильтра); NaN -- пустой input (честно), числа/строки --
//     значения окна;
// (3) правки ячеек: input с aria-label «Строка N, колонка X»; правки
//     переживают смену фильтра; «Применить» активен только при наличии
//     правок; POST /dataset/missing-manual-corrections {edits, apply:true};
//     числовая колонка с неприводимым значением -- клиентская 422-стопа
//     БЕЗ POST (честная ошибка), пустое значение -- value=null;
//     успех -- «Изменения применены, профиль пересчитан» + счётчик,
//     правки сняты, onApplied вызван, окно перечитано;
// (4) ошибка apply -- role="alert", правки СОХРАНЕНЫ (аналитик не теряет
//     работу).
//
// Корпус дизъюнктен существующим сюитам: датасет «метеостанция»
// (dataset_id manual-meteo-1), колонки recorded_at/temp_c/humidity,
// свои ответы всех маршрутов.

import "@testing-library/jest-dom";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { PreprocessingMissingManualEditor } from "./PreprocessingMissingManualEditor";

const EDITOR_COLUMNS = [
  { column: "recorded_at", dtype: "object", semantic: "text" },
  { column: "temp_c", dtype: "float64", semantic: "numeric" },
  { column: "humidity", dtype: "float64", semantic: "numeric" },
];

function page0() {
  return {
    columns: EDITOR_COLUMNS,
    rows: [
      { row_index: 2, cells: ["2024-06-03", null, 60.0] },
      { row_index: 5, cells: ["2024-06-06", null, 62.0] },
      { row_index: 7, cells: ["2024-06-08", 14.9, null] },
    ],
    offset: 0,
    limit: 200,
    total_rows: 3,
    returned: 3,
    has_more: false,
  };
}

function page0All() {
  return {
    columns: EDITOR_COLUMNS,
    rows: [
      { row_index: 0, cells: ["2024-06-01", 12.5, 58.0] },
      { row_index: 1, cells: ["2024-06-02", null, 61.5] },
      { row_index: 2, cells: ["2024-06-03", null, 60.0] },
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
    if (url.includes("/dataset/missing-editor-rows")) {
      const missingOnly = url.includes("missing_only=true");
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(missingOnly ? page0() : page0All()),
      });
    }
    if (url.includes("/dataset/missing-manual-corrections")) {
      const body = JSON.parse(String(init?.body ?? "{}"));
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            applied: true,
            total_edited_requested: body.edits.length,
            total_changed: body.edits.length,
            total_missing_before: 4,
            total_missing_after: 4 - body.edits.length,
            profile: [],
            derived_summary: null,
          }),
      });
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({ detail: "not found" }) });
  }) as unknown as typeof fetch;
  render(<PreprocessingMissingManualEditor onApplied={applied} />);
  return { calls, applied };
}

function cellInput(rowIndex: number, column: string): HTMLInputElement {
  // aria-label ячейки -- позиция 1-based (row_index + 1), как в ведущей
  // колонке № редактора.
  return screen.getByLabelText(`Строка ${rowIndex + 1}, колонка ${column}`) as HTMLInputElement;
}

const APPLY_BUTTON = "Применить";
const SELECT_BUTTON = "Выбрать";

describe("PreprocessingMissingManualEditor (MANUAL-MISSING-1)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("renders filter checkboxes with 'Только с пропусками' applied by default and honest buttons", async () => {
    const { calls } = renderEditor();
    const missingBox = screen.getByLabelText("Только с пропусками") as HTMLInputElement;
    const allBox = screen.getByLabelText("Весь датасет") as HTMLInputElement;
    expect(missingBox.checked).toBe(true);
    expect(allBox.checked).toBe(false);
    expect(screen.getByRole("button", { name: SELECT_BUTTON })).toBeInTheDocument();
    const apply = screen.getByRole("button", { name: APPLY_BUTTON });
    expect(apply).toBeDisabled(); // правок ещё нет
    // стартовое окно -- фильтр «Только с пропусками» применён сразу
    await waitFor(() => {
      expect(calls.some((c) => c.url.includes("/dataset/missing-editor-rows"))).toBe(true);
    });
    expect(calls.some((c) => c.url.includes("missing_only=true"))).toBe(true);
    // NaN -- пустой input, значения -- числа окна
    await waitFor(() => {
      expect(cellInput(2, "temp_c").value).toBe("");
    });
    expect(cellInput(7, "temp_c").value).toBe("14.9");
    expect(cellInput(7, "humidity").value).toBe("");
  });

  it("checkboxes are mutually exclusive; 'Выбрать' applies pending filter and refetches with missing_only=false", async () => {
    const { calls } = renderEditor();
    await screen.findByLabelText("Строка 3, колонка temp_c");

    fireEvent.click(screen.getByLabelText("Весь датасет"));
    const missingBox = screen.getByLabelText("Только с пропусками") as HTMLInputElement;
    const allBox = screen.getByLabelText("Весь датасет") as HTMLInputElement;
    expect(allBox.checked).toBe(true);
    expect(missingBox.checked).toBe(false); // взаимоисключающие

    const before = calls.length;
    fireEvent.click(screen.getByRole("button", { name: SELECT_BUTTON }));
    await waitFor(() => {
      expect(calls.slice(before).some((c) => c.url.includes("missing_only=false"))).toBe(true);
    });
    // окно «Весь датасет» отрисовано
    expect(await screen.findByLabelText("Строка 1, колонка temp_c")).toBeInTheDocument();

    // клик по ЧЕКНУТОМУ чекбоксу снимает чек (честная checkbox-семантика:
    // оба сняты -- «Выбрать» блокируется, пока не выбран фильтр)
    fireEvent.click(screen.getByLabelText("Весь датасет"));
    expect((screen.getByLabelText("Весь датасет") as HTMLInputElement).checked).toBe(false);
    expect((screen.getByLabelText("Только с пропусками") as HTMLInputElement).checked).toBe(false);
    expect(screen.getByRole("button", { name: SELECT_BUTTON })).toBeDisabled();
  });

  it("unchecking both filters disables 'Выбрать' honestly", async () => {
    renderEditor();
    await screen.findByLabelText("Строка 3, колонка temp_c");
    // снять единственный чекнутый («Только с пропусками»)
    fireEvent.click(screen.getByLabelText("Только с пропусками"));
    expect((screen.getByLabelText("Только с пропусками") as HTMLInputElement).checked).toBe(false);
    expect((screen.getByLabelText("Весь датасет") as HTMLInputElement).checked).toBe(false);
    expect(screen.getByRole("button", { name: SELECT_BUTTON })).toBeDisabled();
  });

  it("edits a cell, enables 'Применить', POSTs edits with apply:true, clears edits and calls onApplied", async () => {
    const { calls, applied } = renderEditor();
    const input = await screen.findByLabelText("Строка 3, колонка temp_c");

    fireEvent.change(input, { target: { value: "14.6" } });
    const apply = screen.getByRole("button", { name: APPLY_BUTTON });
    expect(apply).toBeEnabled();

    fireEvent.click(apply);
    await waitFor(() => {
      expect(screen.getByText("Изменения применены, профиль пересчитан")).toBeInTheDocument();
    });
    const post = calls.find((c) => c.url.includes("/dataset/missing-manual-corrections"));
    expect(post).toBeDefined();
    const body = JSON.parse(String(post!.init?.body));
    expect(body.apply).toBe(true);
    expect(body.edits).toEqual([{ row_index: 2, column: "temp_c", value: 14.6 }]);
    expect(applied).toHaveBeenCalledTimes(1); // каскад мастера (datasetVersion)
    // правка снята, input перечитан из окна (мок отдаёт ту же страницу —
    // значение правки ушло, поле снова пустое NaN-окно)
    await waitFor(() => {
      expect(cellInput(2, "temp_c").value).toBe("");
    });
    expect(screen.getByRole("button", { name: APPLY_BUTTON })).toBeDisabled();
  });

  it("empty edit value is sent as null (honest clearing to NaN)", async () => {
    const { calls } = renderEditor();
    const input = await screen.findByLabelText("Строка 8, колонка humidity");
    // humidity строки 7 -- NaN (пустой input); вписали и стёрли = очистка
    fireEvent.change(input, { target: { value: "55" } });
    fireEvent.change(input, { target: { value: "" } });

    fireEvent.click(screen.getByRole("button", { name: APPLY_BUTTON }));
    await waitFor(() => {
      expect(calls.some((c) => c.url.includes("/dataset/missing-manual-corrections"))).toBe(true);
    });
    const post = calls.find((c) => c.url.includes("/dataset/missing-manual-corrections"));
    const body = JSON.parse(String(post!.init?.body));
    expect(body.edits).toEqual([{ row_index: 7, column: "humidity", value: null }]);
  });

  it("invalid numeric value stops client-side with honest error and NO post", async () => {
    const { calls } = renderEditor();
    const input = await screen.findByLabelText("Строка 3, колонка temp_c"); // numeric
    fireEvent.change(input, { target: { value: "abc" } });
    fireEvent.click(screen.getByRole("button", { name: APPLY_BUTTON }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/не является числом/);
    });
    expect(calls.some((c) => c.url.includes("/dataset/missing-manual-corrections"))).toBe(false);
  });

  it("apply error keeps edits (analyst does not lose work) and shows backend detail", async () => {
    const failing = jest.fn((url: string, init?: RequestInit) => {
      if (url.includes("/dataset/missing-manual-corrections")) {
        return Promise.resolve({
          ok: false,
          status: 422,
          json: () => Promise.resolve({ detail: "Значение 'abc' в колонке 'temp_c' (строка 3) не приводится к числу" }),
        });
      }
      if (url.includes("/dataset/missing-editor-rows")) {
        const missingOnly = url.includes("missing_only=true");
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(missingOnly ? page0() : page0All()),
        });
      }
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({ detail: "not found" }) });
    }) as unknown as typeof fetch;
    global.fetch = failing;
    render(<PreprocessingMissingManualEditor onApplied={jest.fn()} />);

    const input = await screen.findByLabelText("Строка 3, колонка temp_c");
    fireEvent.change(input, { target: { value: "14.6" } });
    fireEvent.click(screen.getByRole("button", { name: APPLY_BUTTON }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/не приводится к числу/);
    });
    // правка сохранена в поле (аналитик не теряет работу)
    expect(cellInput(2, "temp_c").value).toBe("14.6");
    expect(screen.getByRole("button", { name: APPLY_BUTTON })).toBeEnabled();
  });

  it("edits survive filter switch and are all sent on apply", async () => {
    const { calls } = renderEditor();
    const input = await screen.findByLabelText("Строка 3, колонка temp_c");
    fireEvent.change(input, { target: { value: "14.6" } });

    // переключили фильтр на «Весь датасет» и применили
    fireEvent.click(screen.getByLabelText("Весь датасет"));
    fireEvent.click(screen.getByRole("button", { name: SELECT_BUTTON }));
    const allInput = (await screen.findByLabelText("Строка 1, колонка temp_c")) as HTMLInputElement;
    expect(allInput.value).toBe("12.5"); // окно всего датасета

    // правка строки 2 пережила смену фильтра
    expect(cellInput(2, "temp_c").value).toBe("14.6");

    fireEvent.click(screen.getByRole("button", { name: APPLY_BUTTON }));
    await waitFor(() => {
      expect(calls.some((c) => c.url.includes("/dataset/missing-manual-corrections"))).toBe(true);
    });
    const post = calls.find((c) => c.url.includes("/dataset/missing-manual-corrections"));
    const body = JSON.parse(String(post!.init?.body));
    expect(body.edits).toEqual([{ row_index: 2, column: "temp_c", value: 14.6 }]);
  });

  it("shows honest row-window status footer", async () => {
    renderEditor();
    await screen.findByLabelText("Строка 3, колонка temp_c");
    expect(screen.getByText(/Строки 1–3 из 3/)).toBeInTheDocument();
  });
});
