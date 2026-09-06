import { renderHook, waitFor, act } from "@testing-library/react";

// Task 97.3 (Этап 3, spec_max_graf_fix.md §6.3): хук условной догрузки
// detail_level=expanded при раскрытии графика. Проверяются: сигнал
// enabled (из onExpandChange/expandedChartId Обзора), кэш
// (profileKey + fingerprint + params) без повторного похода в сеть,
// graceful degradation (§6.3.6) и abort при размонтировании.

import {
  MAX_CHART_DETAIL_CACHE_ENTRIES,
  useChartDetailData,
  __clearChartDetailCacheForTests,
} from "./useChartDetailData";

type Payload = { points: Array<{ x: number; y: number }> };

const BASE_OPTIONS = {
  path: "/dataset/eda-structural-breaks",
  profileKey: "structural-regimes",
  params: { column: "Price", alpha: "0.05" },
  fingerprint: "ds-1",
};

const PAYLOAD_A: Payload = { points: [{ x: 0, y: 1 }, { x: 2, y: 3 }] };
const PAYLOAD_B: Payload = { points: [{ x: 1, y: 5 }] };

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  } as unknown as Response;
}

describe("useChartDetailData", () => {
  beforeEach(() => {
    __clearChartDetailCacheForTests();
    global.fetch = jest.fn();
  });

  it("не ходит в сеть, пока график свёрнут (enabled=false)", () => {
    renderHook(() => useChartDetailData<Payload>({ ...BASE_OPTIONS, enabled: false }));

    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("при раскрытии дозапрашивает detail_level=expanded с параметрами профиля", async () => {
    (global.fetch as jest.Mock).mockResolvedValue(jsonResponse(PAYLOAD_A));
    const { result, rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) => useChartDetailData<Payload>({ ...BASE_OPTIONS, enabled }),
      { initialProps: { enabled: false } },
    );

    // сигнал «панель стала раскрыта» (onExpandChange → enabled=true)
    rerender({ enabled: true });

    await waitFor(() => expect(result.current.data).toEqual(PAYLOAD_A));
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [url, init] = (global.fetch as jest.Mock).mock.calls[0];
    expect(String(url)).toContain("/dataset/eda-structural-breaks");
    expect(String(url)).toContain("column=Price");
    expect(String(url)).toContain("alpha=0.05");
    expect(String(url)).toContain("detail_level=expanded");
    expect(init.credentials).toBe("include");
  });

  it("loading=true, пока запрос в полёте; компактные данные не блокируются (§6.3.3)", async () => {
    let resolveFetch: ((value: Response) => void) | null = null;
    (global.fetch as jest.Mock).mockReturnValue(
      new Promise<Response>((resolve) => { resolveFetch = resolve; }),
    );
    const { result } = renderHook(() => useChartDetailData<Payload>({ ...BASE_OPTIONS, enabled: true }));

    await waitFor(() => expect(result.current.loading).toBe(true));
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBeNull();

    await act(async () => { resolveFetch?.(jsonResponse(PAYLOAD_A)); });
    await waitFor(() => expect(result.current.data).toEqual(PAYLOAD_A));
    expect(result.current.loading).toBe(false);
  });

  it("повторное раскрытие берёт payload из кэша — второй сети нет (§6.3.2)", async () => {
    (global.fetch as jest.Mock).mockResolvedValue(jsonResponse(PAYLOAD_A));
    const { result, rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) => useChartDetailData<Payload>({ ...BASE_OPTIONS, enabled }),
      { initialProps: { enabled: false } },
    );

    rerender({ enabled: true });
    await waitFor(() => expect(result.current.data).toEqual(PAYLOAD_A));

    rerender({ enabled: false });
    rerender({ enabled: true });
    await waitFor(() => expect(result.current.data).toEqual(PAYLOAD_A));

    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(result.current.loading).toBe(false);
  });

  it("смена fingerprint (датасет/параметры) инвалидирует кэш и делает новый запрос", async () => {
    (global.fetch as jest.Mock).mockResolvedValue(jsonResponse(PAYLOAD_A));
    const { result, rerender } = renderHook(
      ({ fingerprint }: { fingerprint: string }) =>
        useChartDetailData<Payload>({ ...BASE_OPTIONS, enabled: true, fingerprint }),
      { initialProps: { fingerprint: "ds-1" } },
    );
    await waitFor(() => expect(result.current.data).toEqual(PAYLOAD_A));

    rerender({ fingerprint: "ds-2" });
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
    expect(result.current.data).toBeNull(); // старый payload другого датасета не показывается
  });

  it("смена параметров профиля — новый запрос (методология должна совпадать с compact)", async () => {
    (global.fetch as jest.Mock).mockResolvedValue(jsonResponse(PAYLOAD_A));
    const { result, rerender } = renderHook(
      ({ alpha }: { alpha: string }) =>
        useChartDetailData<Payload>({ ...BASE_OPTIONS, enabled: true, params: { column: "Price", alpha } }),
      { initialProps: { alpha: "0.05" } },
    );
    await waitFor(() => expect(result.current.data).toEqual(PAYLOAD_A));

    rerender({ alpha: "0.01" });
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
    const [secondUrl] = (global.fetch as jest.Mock).mock.calls[1];
    expect(String(secondUrl)).toContain("alpha=0.01");
  });

  it("ошибка сети — graceful degradation: error без падения компактных данных (§6.3.6)", async () => {
    (global.fetch as jest.Mock).mockRejectedValue(new Error("network down"));
    const { result } = renderHook(() => useChartDetailData<Payload>({ ...BASE_OPTIONS, enabled: true }));

    await waitFor(() => expect(result.current.error).toBe("network down"));
    expect(result.current.data).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it("HTTP-ошибка (backend без поддержки параметра) — error, не падение", async () => {
    (global.fetch as jest.Mock).mockResolvedValue({ ok: false, status: 500 } as Response);
    const { result } = renderHook(() => useChartDetailData<Payload>({ ...BASE_OPTIONS, enabled: true }));

    await waitFor(() => expect(result.current.error).toBe("HTTP 500"));
    expect(result.current.data).toBeNull();
  });

  it("размонтирование в полёте — abort и отсутствие setState после размонтажа", async () => {
    let capturedSignal: AbortSignal | null = null;
    (global.fetch as jest.Mock).mockImplementation(
      (_url: string, init: RequestInit) => {
        capturedSignal = init.signal;
        return new Promise<Response>(() => {});
      },
    );
    const { unmount } = renderHook(() => useChartDetailData<Payload>({ ...BASE_OPTIONS, enabled: true }));
    await waitFor(() => expect(capturedSignal).not.toBeNull());

    unmount();
    expect(capturedSignal?.aborted).toBe(true);
  });

  it("кэш ограничен: старейшие записи вытесняются (FIFO)", async () => {
    (global.fetch as jest.Mock).mockResolvedValue(jsonResponse(PAYLOAD_B));
    const { result, rerender } = renderHook(
      ({ fingerprint }: { fingerprint: string }) =>
        useChartDetailData<Payload>({ ...BASE_OPTIONS, enabled: true, fingerprint }),
      { initialProps: { fingerprint: "k-0" } },
    );
    await waitFor(() => expect(result.current.data).toEqual(PAYLOAD_B));

    // заполняем кэш до потолка и ещё на одну запись
    for (let index = 1; index <= MAX_CHART_DETAIL_CACHE_ENTRIES; index += 1) {
      rerender({ fingerprint: `k-${index}` });
      // eslint-disable-next-line no-await-in-loop
      await waitFor(() => expect(result.current.loading).toBe(false));
    }

    expect((global.fetch as jest.Mock).mock.calls.length).toBeGreaterThanOrEqual(
      MAX_CHART_DETAIL_CACHE_ENTRIES + 1,
    );

    // самая первая запись вытеснена — возврат к ней идёт в сеть снова
    (global.fetch as jest.Mock).mockClear();
    (global.fetch as jest.Mock).mockResolvedValue(jsonResponse(PAYLOAD_A));
    rerender({ fingerprint: "k-0" });
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
  });
});
