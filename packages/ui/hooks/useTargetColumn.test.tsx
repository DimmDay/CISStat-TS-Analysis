// packages/ui/hooks/useTargetColumn.test.tsx
//
// Тесты хука useTargetColumn -- PROGR-25-B (spec_progress_target_column.md
// §4-B, план §2). Ключевой разворот поведения: тихий авто-POST рекомендации
// СНЯТ ПОЛНОСТЬЮ (правка R1 акта сертификации) -- авто-фиксация
// исследуемого признака стала исключительной компетенцией бэкенда
// (PROGR-25-A: авто-фиксация при загрузке при ровно одном кандидате).
// Хук после снятия:
//   1. Читает GET /v1/session/target-column и отображает состояние --
//     НИКОГДА не выполняет POST сам (монтирование любой вкладки с хуком
//     не создаёт target_column_changed -- ни при одной, ни при нескольких
//     числовых кандидатах).
//   2. suggested_column остаётся ОТОБРАЖАЕМОЙ рекомендацией (состояние
//     хука), а не фиксацией.
//   3. wasAutoSelected -- честное происхождение из ФАКТА бэкенда
//     (target_column_source === "auto", PROGR-25-A); ответ старого
//     бэкенда без поля (undefined) читается как "не авто".
//   4. Фиксация -- только ручной setColumn (POST, source=user).
//   5. Уведомление о сбросе (columnResetNotice) сохранено и живёт в
//     общем пути фетча: "ранее непустой target стал null" -- newColumn
//     несёт РЕКОМЕНДАЦИЮ (suggested_column) или null (ничего не выбрано).

import "@testing-library/jest-dom";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useTargetColumn } from "./useTargetColumn";
import type { TargetColumnResponse } from "../lib/modeling";

function mockTargetColumnFetch(
  sequence: TargetColumnResponse[],
  postResponse?: TargetColumnResponse,
): jest.Mock {
  let callIndex = 0;
  return jest.fn((url: string, init?: RequestInit) => {
    if (String(url).includes("/target-column")) {
      if (init?.method === "POST") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve(
              postResponse ?? {
                target_column: JSON.parse(String(init.body ?? "{}")).column,
                suggested_column: JSON.parse(String(init.body ?? "{}")).column,
                available_columns: [],
                has_dataset: true,
              },
            ),
        });
      }
      const response = sequence[Math.min(callIndex, sequence.length - 1)];
      callIndex += 1;
      return Promise.resolve({ ok: true, json: () => Promise.resolve(response) });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
  }) as jest.Mock;
}

describe("useTargetColumn (PROGR-25-B: снятие тихого авто-POST, R1)", () => {
  it("монтирование НЕ выполняет авто-POST: одна числовая, есть рекомендация (R1, однозначный класс)", async () => {
    // Ровно сценарий Г1/A: бэкенд ещё не зафиксировал признак (target null),
    // рекомендация есть. Раньше хук здесь POST-ил -- теперь молчит.
    global.fetch = mockTargetColumnFetch([
      { target_column: null, suggested_column: "value", available_columns: ["value"], has_dataset: true },
    ]);

    const { result } = renderHook(() => useTargetColumn("n150.csv"));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.targetColumn).toBeNull();
    expect(result.current.suggestedColumn).toBe("value");

    const calls = (global.fetch as jest.Mock).mock.calls.map((c) => String(c[0]));
    const methods = (global.fetch as jest.Mock).mock.calls
      .filter((c) => String(c[0]).includes("/target-column"))
      .map((c) => c[1]?.method ?? "GET");
    expect(calls.some((u) => u.includes("/target-column"))).toBe(true);
    expect(methods).toEqual(["GET"]); // ровно один GET, POST нет
  });

  it("монтирование НЕ выполняет авто-POST: несколько числовых (R1, неоднозначный класс)", async () => {
    global.fetch = mockTargetColumnFetch([
      {
        target_column: null,
        suggested_column: "sales",
        available_columns: ["sales", "profit", "margin"],
        has_dataset: true,
      },
    ]);

    const { result } = renderHook(() => useTargetColumn("sales_demo.csv"));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.targetColumn).toBeNull();
    // Рекомендация ОТОБРАЖАЕТСЯ состоянием хука -- фиксации нет.
    expect(result.current.suggestedColumn).toBe("sales");

    const methods = (global.fetch as jest.Mock).mock.calls
      .filter((c) => String(c[0]).includes("/target-column"))
      .map((c) => c[1]?.method ?? "GET");
    expect(methods).toEqual(["GET"]);
  });

  it("wasAutoSelected -- из факта бэкенда source=auto; ручной setColumn гасит", async () => {
    // Бэкенд авто-фиксировал признак при загрузке (PROGR-25-A) -- GET
    // возвращает source="auto"; бейдж "выбрано автоматически" честен.
    global.fetch = mockTargetColumnFetch([
      {
        target_column: "value",
        target_column_source: "auto",
        suggested_column: "value",
        available_columns: ["value"],
        has_dataset: true,
      },
    ]);

    const { result } = renderHook(() => useTargetColumn("n150.csv"));
    await waitFor(() => expect(result.current.targetColumn).toBe("value"));
    expect(result.current.wasAutoSelected).toBe(true);

    // Ручной выбор -- POST; источник становится user; бейдж гаснет.
    await act(async () => {
      await result.current.setColumn("price2");
    });
    expect(result.current.targetColumn).toBe("price2");
    expect(result.current.wasAutoSelected).toBe(false);
  });

  it("ответ старого бэкенда без target_column_source (undefined) -- не авто", async () => {
    global.fetch = mockTargetColumnFetch([
      { target_column: "value", suggested_column: "value", available_columns: ["value"], has_dataset: true },
    ]);

    const { result } = renderHook(() => useTargetColumn("n150.csv"));
    await waitFor(() => expect(result.current.targetColumn).toBe("value"));
    // Происхождение неизвестно -- честно НЕ помечаем как авто.
    expect(result.current.wasAutoSelected).toBe(false);
  });

  it("columnResetNotice живёт без авто-POST: был Price, стал null -- newColumn = рекомендация", async () => {
    global.fetch = mockTargetColumnFetch([
      { target_column: "Price", suggested_column: "Price", available_columns: ["Year", "Price"], has_dataset: true },
      { target_column: null, suggested_column: "Volume", available_columns: ["Volume"], has_dataset: true },
    ]);

    const { result } = renderHook(() => useTargetColumn("fao.csv"));
    await waitFor(() => expect(result.current.targetColumn).toBe("Price"));

    // Новый датасет: колонка Price исчезла, бэкенд сбросил target.
    await act(async () => {
      await result.current.refetch();
    });
    await waitFor(() => expect(result.current.columnResetNotice).not.toBeNull());
    expect(result.current.columnResetNotice).toEqual({
      previousColumn: "Price",
      newColumn: "Volume", // рекомендация, НЕ фиксация
    });

    act(() => {
      result.current.dismissColumnResetNotice();
    });
    expect(result.current.columnResetNotice).toBeNull();
  });

  it("columnResetNotice без рекомендации (сuggested null) -- newColumn: null", async () => {
    global.fetch = mockTargetColumnFetch([
      { target_column: "Price", suggested_column: "Price", available_columns: ["Price"], has_dataset: true },
      { target_column: null, suggested_column: null, available_columns: [], has_dataset: true },
    ]);

    const { result } = renderHook(() => useTargetColumn("fao.csv"));
    await waitFor(() => expect(result.current.targetColumn).toBe("Price"));

    await act(async () => {
      await result.current.refetch();
    });
    await waitFor(() => expect(result.current.columnResetNotice).not.toBeNull());
    expect(result.current.columnResetNotice).toEqual({
      previousColumn: "Price",
      newColumn: null,
    });
  });

  it("первый фетч с target=null -- НЕ сброс (previousColumn никогда не было)", async () => {
    global.fetch = mockTargetColumnFetch([
      { target_column: null, suggested_column: "value", available_columns: ["value"], has_dataset: true },
    ]);

    const { result } = renderHook(() => useTargetColumn("n150.csv"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.columnResetNotice).toBeNull();
  });

  it("повторное монтирование с другим datasetKey -- тоже без POST (каждая вкладка)", async () => {
    global.fetch = mockTargetColumnFetch([
      { target_column: null, suggested_column: "value", available_columns: ["value"], has_dataset: true },
    ]);

    const { result, rerender } = renderHook(
      ({ datasetKey }: { datasetKey: string | null }) => useTargetColumn(datasetKey),
      { initialProps: { datasetKey: "a.csv" as string | null } },
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    rerender({ datasetKey: "b.csv" });
    await waitFor(() => {
      const methods = (global.fetch as jest.Mock).mock.calls
        .filter((c) => String(c[0]).includes("/target-column"))
        .map((c) => c[1]?.method ?? "GET");
      expect(methods).toEqual(["GET", "GET"]); // только GET-ы
    });
  });
});
