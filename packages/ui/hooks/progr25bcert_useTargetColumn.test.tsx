// packages/ui/hooks/progr25bcert_useTargetColumn.test.tsx
//
// СЕРТИФИКАЦИОННЫЕ ОРАКУЛЫ задачи PROGR-25-B (PROGR-25-B-CERT, независимый
// аудит хука useTargetColumn). Сюит НЕ копирует repo-тесты задачи
// (useTargetColumn.test.tsx): свои сценарные данные, свои моки, свои
// последовательности ответов. Свои данные сертификации (линейка
// energy-датасетов сертификации A-CERT): energy_hourly.csv, колонки
// ts (datetime) / load / price / temp (numeric); рекомендация бэкенда
// "load" (однозначный класс) и "price" (сброс после смены датасета).
//
// Контракты, покрываемые ОРАКУЛАМИ АУДИТОРА (спека §4-B, план §2):
//   CERT-H1/H2  -- монтирование хука НИКОГДА не POST-ит (R1): ни в
//                  однозначном классе (есть рекомендация), ни в
//                  неоднозначном (рекомендации нет);
//   CERT-H3     -- wasAutoSelected = ФАКТ ответа (target_column_source
//                  === "auto"); user/undefined (legacy) -- не авто;
//   CERT-H4     -- фиксация только ручная: setColumn POST-ит {column};
//   CERT-H5/H6  -- уведомление о сбросе несёт РЕКОМЕНДАЦИЮ
//                  (suggested_column) или null, не фиксированное значение;
//   CERT-H7     -- первый фетч (история пуста) -- не сброс;
//   CERT-H8     -- повторные маунты/рефетчи -- только GET;
//   CERT-H9     -- сетевой сбой -- honest error, без POST.

import "@testing-library/jest-dom";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useTargetColumn } from "./useTargetColumn";

interface SeqStep {
  target_column: string | null;
  target_column_source?: string;
  suggested_column: string | null;
  available_columns: string[];
  has_dataset: boolean;
}

const COLS = ["ts", "load", "price", "temp"];

/** Свой мок-стенд аудитора: последовательность GET-ответов /target-column
 * + опциональный ответ на POST. Протоколирует ВСЕ вызовы (url, method,
 * body) -- основа инвариантов «нет POST» / «только GET». */
function certFetchMock(getSequence: SeqStep[], postResponse?: SeqStep) {
  const calls: Array<{ url: string; method: string; body: string | null }> = [];
  let getIdx = 0;
  const impl = (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const body = typeof init?.body === "string" ? init.body : null;
    calls.push({ url: String(url), method, body });
    if (String(url).includes("/target-column")) {
      if (method === "POST") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve(
              postResponse ?? {
                target_column: JSON.parse(body ?? "{}").column,
                target_column_source: "user",
                suggested_column: JSON.parse(body ?? "{}").column,
                available_columns: COLS,
                has_dataset: true,
              },
            ),
        });
      }
      const step = getSequence[Math.min(getIdx, getSequence.length - 1)];
      getIdx += 1;
      return Promise.resolve({ ok: true, json: () => Promise.resolve(step) });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
  };
  global.fetch = jest.fn(impl as unknown as typeof fetch);
  return calls;
}

const targetCalls = (calls: Array<{ url: string; method: string }>): string[] =>
  calls.filter((c) => c.url.includes("/target-column")).map((c) => c.method);

describe("PROGR-25-B-CERT: хук useTargetColumn (свои оракулы аудита)", () => {
  it("CERT-H1: маунт в однозначном классе НЕ POST-ит (target null, рекомендация load, одна числовая)", async () => {
    const calls = certFetchMock([
      { target_column: null, suggested_column: "load", available_columns: COLS, has_dataset: true },
    ]);
    const { result } = renderHook(() => useTargetColumn("energy_hourly.csv"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.targetColumn).toBeNull();
    expect(result.current.suggestedColumn).toBe("load");
    expect(result.current.hasDataset).toBe(true);
    // R1: ровно GET, НИ ОДНОГО POST (авто-фиксация -- компетенция бэкенда).
    expect(targetCalls(calls)).toEqual(["GET"]);
    expect(result.current.wasAutoSelected).toBe(false);
  });

  it("CERT-H2: маунт в неоднозначном классе НЕ POST-ит (target null, рекомендации нет, 3 числовых)", async () => {
    const calls = certFetchMock([
      { target_column: null, suggested_column: null, available_columns: COLS, has_dataset: true },
    ]);
    const { result } = renderHook(() => useTargetColumn("energy_hourly.csv"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.targetColumn).toBeNull();
    expect(result.current.suggestedColumn).toBeNull();
    expect(targetCalls(calls)).toEqual(["GET"]);
  });

  it("CERT-H3: wasAutoSelected -- честный факт source ответа (auto -> true; user/undefined -> false)", async () => {
    // auto.
    certFetchMock([
      { target_column: "load", target_column_source: "auto", suggested_column: "load", available_columns: COLS, has_dataset: true },
    ]);
    const autoView = renderHook(() => useTargetColumn("energy_hourly.csv"));
    await waitFor(() => expect(autoView.result.current.loading).toBe(false));
    expect(autoView.result.current.wasAutoSelected).toBe(true);
    expect(autoView.result.current.targetColumn).toBe("load");
    autoView.unmount();

    // user (ручная фиксация бэкендом).
    certFetchMock([
      { target_column: "price", target_column_source: "user", suggested_column: "price", available_columns: COLS, has_dataset: true },
    ]);
    const userView = renderHook(() => useTargetColumn("energy_hourly.csv"));
    await waitFor(() => expect(userView.result.current.loading).toBe(false));
    expect(userView.result.current.wasAutoSelected).toBe(false);
    userView.unmount();

    // Legacy: старый бэкенд без поля source -- «не авто» (честно).
    certFetchMock([
      { target_column: "load", suggested_column: "load", available_columns: COLS, has_dataset: true },
    ]);
    const legacyView = renderHook(() => useTargetColumn("energy_hourly.csv"));
    await waitFor(() => expect(legacyView.result.current.loading).toBe(false));
    expect(legacyView.result.current.wasAutoSelected).toBe(false);
  });

  it("CERT-H4: фиксация только ручная -- setColumn POST-ит {column} и гасит wasAutoSelected", async () => {
    const calls = certFetchMock(
      [
        { target_column: "load", target_column_source: "auto", suggested_column: "load", available_columns: COLS, has_dataset: true },
      ],
      // Ответ сервера на ручной POST: пользователь выбрал price.
      { target_column: "price", target_column_source: "user", suggested_column: "price", available_columns: COLS, has_dataset: true },
    );
    const { result } = renderHook(() => useTargetColumn("energy_hourly.csv"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.wasAutoSelected).toBe(true);

    await act(async () => {
      await result.current.setColumn("price");
    });
    const post = calls.find((c) => c.method === "POST");
    expect(post).toBeDefined();
    expect(JSON.parse(post!.body ?? "{}")).toEqual({ column: "price" });
    expect(result.current.targetColumn).toBe("price");
    expect(result.current.wasAutoSelected).toBe(false);
  });

  it("CERT-H5: сброс (load -> null) несёт РЕКОМЕНДАЦИЮ suggested_column, без POST-ов", async () => {
    const calls = certFetchMock([
      { target_column: "load", target_column_source: "user", suggested_column: "load", available_columns: COLS, has_dataset: true },
      { target_column: null, suggested_column: "price", available_columns: COLS, has_dataset: true },
    ]);
    const { result } = renderHook(() => useTargetColumn("energy_hourly.csv"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.columnResetNotice).toBeNull();

    await act(async () => {
      await result.current.refetch();
    });
    // newColumn -- РЕКОМЕНДАЦИЯ (не фиксация): хук не POST-ит её.
    expect(result.current.columnResetNotice).toEqual({ previousColumn: "load", newColumn: "price" });
    expect(targetCalls(calls)).toEqual(["GET", "GET"]);
  });

  it("CERT-H6: сброс без рекомендации -- newColumn=null (честное «выберите сами»)", async () => {
    certFetchMock([
      { target_column: "load", target_column_source: "user", suggested_column: "load", available_columns: COLS, has_dataset: true },
      { target_column: null, suggested_column: null, available_columns: COLS, has_dataset: true },
    ]);
    const { result } = renderHook(() => useTargetColumn("energy_hourly.csv"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.refetch();
    });
    expect(result.current.columnResetNotice).toEqual({ previousColumn: "load", newColumn: null });
  });

  it("CERT-H7: самый первый фетч с null -- не сброс (notice нет)", async () => {
    certFetchMock([
      { target_column: null, suggested_column: "load", available_columns: COLS, has_dataset: true },
    ]);
    const { result } = renderHook(() => useTargetColumn("energy_hourly.csv"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.columnResetNotice).toBeNull();
  });

  it("CERT-H8: смена datasetKey и повторный маунт -- только GET-ы (хук никогда не POST-ит сам)", async () => {
    const calls = certFetchMock([
      { target_column: "load", target_column_source: "auto", suggested_column: "load", available_columns: COLS, has_dataset: true },
      { target_column: "load", target_column_source: "auto", suggested_column: "load", available_columns: COLS, has_dataset: true },
      { target_column: "load", target_column_source: "auto", suggested_column: "load", available_columns: COLS, has_dataset: true },
    ]);
    const first = renderHook(
      (props: { datasetKey: string }) => useTargetColumn(props.datasetKey),
      { initialProps: { datasetKey: "energy_hourly.csv" } },
    );
    await waitFor(() => expect(first.result.current.loading).toBe(false));
    first.rerender({ datasetKey: "energy_total_v2.csv" });
    await waitFor(() => expect((global.fetch as jest.Mock).mock.calls.length).toBeGreaterThanOrEqual(2));

    const second = renderHook(() => useTargetColumn("energy_total_v2.csv"));
    await waitFor(() => expect(second.result.current.loading).toBe(false));
    const methods = targetCalls(calls);
    expect(methods.length).toBeGreaterThanOrEqual(3);
    expect(new Set(methods)).toEqual(new Set(["GET"]));
    first.unmount();
    second.unmount();
  });

  it("CERT-H9: сетевой сбой -- честная ошибка, без POST, состояние не роняет потребителя", async () => {
    global.fetch = jest.fn(((url: string, init?: RequestInit) => {
      if (String(url).includes("/target-column") && (init?.method ?? "GET") === "GET") {
        return Promise.reject(new Error("network down"));
      }
      return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
    }) as unknown as typeof fetch);
    const { result } = renderHook(() => useTargetColumn("energy_hourly.csv"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toContain("network down");
    expect(result.current.targetColumn).toBeNull();
    expect(result.current.columnResetNotice).toBeNull();
  });
});
