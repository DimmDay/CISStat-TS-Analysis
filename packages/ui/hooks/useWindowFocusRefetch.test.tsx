// packages/ui/hooks/useWindowFocusRefetch.test.tsx
//
// Юнит-тесты хука useWindowFocusRefetch (PROGR-9-FOCUS).
//
// Контракт хука (см. useWindowFocusRefetch.ts):
//   1. НЕ вызывает колбэк при монтировании (только по событиям).
//   2. Вызывает колбэк по window "focus" (возврат в окно браузера).
//   3. Вызывает колбэк по document "visibilitychange" ТОЛЬКО при переходе
//      в visible (возврат во вкладку браузера); переход в hidden молчит.
//   4. Дедуплицирует пару focus+visibilitychange одной нормализации окна
//      в пределах minIntervalMs (по умолчанию 750 мс) — одна синхронизация
//      не должна порождать двойную волну GET.
//   5. После размонтирования слушатели сняты — колбэк не вызывается.
//   6. Между рендерами использует СВЕЖИЙ колбэк без переподписки слушателей.
//
// Время контролируется шпионом на Date.now (без fake timers: Testing
// Library waitFor использует таймеры, их подмена ломает findBy*).

import "@testing-library/jest-dom";
import { renderHook, act } from "@testing-library/react";
import { useWindowFocusRefetch } from "./useWindowFocusRefetch";

function setVisibilityState(state: "visible" | "hidden") {
  // jsdom: visibilityState -- геттер на Document.prototype; переопределяем
  // собственным свойством, в afterEach снимаем (delete) -- геттер прототипа
  // восстанавливается.
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    value: state,
  });
}

function dispatchVisibilityChange() {
  act(() => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

function dispatchWindowFocus() {
  act(() => {
    window.dispatchEvent(new Event("focus"));
  });
}

describe("useWindowFocusRefetch", () => {
  let dateNowSpy: jest.SpyInstance;

  beforeEach(() => {
    dateNowSpy = jest.spyOn(Date, "now").mockReturnValue(1_000);
  });

  afterEach(() => {
    dateNowSpy.mockRestore();
    // Снять собственное свойство, если тест его ставил (геттер прототипа
    // Document снова в силе; jsdom-дефолт -- "visible").
    delete (document as unknown as { visibilityState?: string }).visibilityState;
  });

  it("не вызывает колбэк при монтировании (только по событиям)", () => {
    const onRefetch = jest.fn();
    renderHook(() => useWindowFocusRefetch(onRefetch));
    expect(onRefetch).not.toHaveBeenCalled();
  });

  it("вызывает колбэк по window focus (возврат в окно)", () => {
    const onRefetch = jest.fn();
    renderHook(() => useWindowFocusRefetch(onRefetch));
    dispatchWindowFocus();
    expect(onRefetch).toHaveBeenCalledTimes(1);
  });

  it("вызывает колбэк по visibilitychange при переходе в visible (возврат во вкладку)", () => {
    setVisibilityState("visible");
    const onRefetch = jest.fn();
    renderHook(() => useWindowFocusRefetch(onRefetch));
    dispatchVisibilityChange();
    expect(onRefetch).toHaveBeenCalledTimes(1);
  });

  it("молчит по visibilitychange при переходе в hidden (уход из вкладки -- не повод перезапрашивать)", () => {
    const onRefetch = jest.fn();
    renderHook(() => useWindowFocusRefetch(onRefetch));
    // Первое событие -- visible (легитимный перезапрос).
    setVisibilityState("visible");
    dispatchVisibilityChange();
    expect(onRefetch).toHaveBeenCalledTimes(1);
    // Гарантированно выходим за окно дедупликации: следующий hidden-переход
    // молчит именно из-за guard'а visibilityState, а не из-за дедупликации.
    dateNowSpy.mockReturnValue(5_000);
    setVisibilityState("hidden");
    dispatchVisibilityChange();
    expect(onRefetch).toHaveBeenCalledTimes(1);
  });

  it("дедуплицирует пару focus+visibilitychange в пределах minIntervalMs (одна волна, не две)", () => {
    setVisibilityState("visible");
    const onRefetch = jest.fn();
    renderHook(() => useWindowFocusRefetch(onRefetch));
    dispatchWindowFocus();
    dispatchVisibilityChange(); // тот же момент времени (Date.now = 1000)
    expect(onRefetch).toHaveBeenCalledTimes(1);
    // За пределами окна дедупликации -- новый легитимный перезапрос.
    dateNowSpy.mockReturnValue(1_000 + 751);
    dispatchVisibilityChange();
    expect(onRefetch).toHaveBeenCalledTimes(2);
  });

  it("уважает пользовательский minIntervalMs", () => {
    setVisibilityState("visible");
    const onRefetch = jest.fn();
    renderHook(() => useWindowFocusRefetch(onRefetch, { minIntervalMs: 3_000 }));
    dispatchWindowFocus();
    dateNowSpy.mockReturnValue(1_000 + 751); // меньше 3 с -- дедуп активен
    dispatchVisibilityChange();
    expect(onRefetch).toHaveBeenCalledTimes(1);
    dateNowSpy.mockReturnValue(1_000 + 3_001);
    dispatchWindowFocus();
    expect(onRefetch).toHaveBeenCalledTimes(2);
  });

  it("после размонтирования слушатели сняты -- колбэк не вызывается", () => {
    setVisibilityState("visible");
    const onRefetch = jest.fn();
    const { unmount } = renderHook(() => useWindowFocusRefetch(onRefetch));
    unmount();
    dateNowSpy.mockReturnValue(50_000);
    dispatchWindowFocus();
    dispatchVisibilityChange();
    expect(onRefetch).not.toHaveBeenCalled();
  });

  it("использует свежий колбэк между рендерами без переподписки", () => {
    setVisibilityState("visible");
    const first = jest.fn();
    const second = jest.fn();
    const { rerender } = renderHook(
      ({ callback }) => useWindowFocusRefetch(callback),
      { initialProps: { callback: first } },
    );
    rerender({ callback: second });
    dateNowSpy.mockReturnValue(50_000);
    dispatchVisibilityChange();
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });
});
