// packages/ui/components/NavigatorChartPreview.test.tsx
//
// Тесты статичного линейного графика для окна «Обзор» остановки «График»
// (id="chart") остановки «Загрузка» на странице Навигатор.
//
// Контракт (задача 2026-08-29):
//   - График СТАТИЧНЫЙ: данные — детерминированный синтетический датасет
//     demo_finance_ohlcv.csv (packages/ui/lib/demoDatasets.ts ::
//     generateFinanceOhlcv, mulberry32(20260821), 500 торговых дней).
//   - Признак: volume (колонка 5 в CSV: date,open,high,low,close,volume).
//   - Отображается ПРИ ЛЮБЫХ УСЛОВИЯХ, даже если сам датасет удалён:
//     компонент НЕ зависит от useAppShell / activeDataset / fetch / сети.
//
// Архитектурно — ближайший родственник TimeSeriesLineChart, но без
// пропов data/loading и без API-вызова: данные генерируются на лету из
// того же детерминированного генератора, что и демо-датасет Загрузки.

import React from "react";
import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import {
  NavigatorChartPreview,
  NAVIGATOR_CHART_PREVIEW_DATASET_ID,
  NAVIGATOR_CHART_PREVIEW_FEATURE,
} from "./NavigatorChartPreview";
import { getDemoFinanceOhlcvVolumeSeries } from "../lib/demoDatasets";

// ─────────────────────────────────────────────────────────────────────────
// Контракт данных: детерминированный генератор -> массив точек
// ─────────────────────────────────────────────────────────────────────────

describe("NavigatorChartPreview — data contract", () => {
  it("getDemoFinanceOhlcvVolumeSeries() returns 500 points (matches the generator)", () => {
    const series = getDemoFinanceOhlcvVolumeSeries();
    expect(series).toHaveLength(500);
  });

  it("each point has date (YYYY-MM-DD) and numeric volume", () => {
    const series = getDemoFinanceOhlcvVolumeSeries();
    series.forEach((p) => {
      expect(p.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(typeof p.volume).toBe("number");
      expect(Number.isFinite(p.volume)).toBe(true);
      expect(p.volume).toBeGreaterThan(0);
    });
  });

  it("is deterministic — two calls produce identical series", () => {
    const a = getDemoFinanceOhlcvVolumeSeries();
    const b = getDemoFinanceOhlcvVolumeSeries();
    expect(a).toEqual(b);
  });

  it("first trading day is 2022-01-03 (Monday) — matches generateFinanceOhlcv seed", () => {
    const series = getDemoFinanceOhlcvVolumeSeries();
    expect(series[0].date).toBe("2022-01-03");
  });

  it("excludes weekends (no Saturday/Sunday in series)", () => {
    const series = getDemoFinanceOhlcvVolumeSeries();
    series.forEach((p) => {
      // 2022-01-03 = Monday. Parse as UTC noon to avoid TZ edge cases.
      const dow = new Date(p.date + "T12:00:00Z").getUTCDay();
      expect(dow).not.toBe(0); // not Sunday
      expect(dow).not.toBe(6); // not Saturday
    });
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Рендер: статичный график, без зависимостей от сессии/сети
// ─────────────────────────────────────────────────────────────────────────

describe("NavigatorChartPreview — rendering", () => {
  it("renders without AppShellProvider (no session dependency)", () => {
    // Если компонент попытается вызвать useAppShell() — упадёт с
    // "useAppShell должен вызываться внутри <AppShellProvider>".
    // Не оборачиваем в провайдер намеренно.
    const { container } = render(<NavigatorChartPreview />);
    expect(container.firstChild).not.toBeNull();
  });

  it("renders a recharts responsive container (chart frame)", () => {
    const { container } = render(<NavigatorChartPreview />);
    expect(container.querySelector(".recharts-responsive-container")).toBeTruthy();
  });

  // Примечание: проверка наличия <path> линии (recharts-line-curve) убрана —
  // в jsdom ResponsiveContainer рендерится с width/height 0×0 (ResizeObserver
  // stub не вызывает layout), поэтому recharts НЕ строит внутренний SVG.
  // Существование контейнера .recharts-responsive-container достаточно —
  // это и есть сигнал, что компонент реально рендерит график, а не заглушку.
  // Та же конвенция в BacktestComparisonChart.test.tsx / DistributionCharts
  // тестах проекта.

  it("exposes static dataset id = demo_finance_ohlcv (matches DEMO_DATASETS fileName without .csv)", () => {
    expect(NAVIGATOR_CHART_PREVIEW_DATASET_ID).toBe("demo_finance_ohlcv");
  });

  it("exposes feature name = volume", () => {
    expect(NAVIGATOR_CHART_PREVIEW_FEATURE).toBe("volume");
  });

  it("renders dataset name visible to the user", () => {
    render(<NavigatorChartPreview />);
    // Имя файла встречается дважды: в шапке (как моно-текст) и в подписи
    // под графиком («500 точек · demo_finance_ohlcv.csv»). Используем
    // getAllByText — минимум одно вхождение и должно быть.
    const matches = screen.getAllByText(/demo_finance_ohlcv\.csv/i);
    expect(matches.length).toBeGreaterThanOrEqual(1);
  });

  it("renders feature label visible to the user", () => {
    render(<NavigatorChartPreview />);
    expect(screen.getByText(/volume/i)).toBeInTheDocument();
  });

  it("renders an informative caption about point count", () => {
    render(<NavigatorChartPreview />);
    // 500 точек — фиксированное число из детерминированного генератора.
    expect(screen.getByText(/500\s*точек/i)).toBeInTheDocument();
  });

  it("renders without loading/empty state — always shows chart", () => {
    // Никаких "Загрузка...", "Нет данных" и т.п. Проверка на «пример»
    // убрана: компонент сам может помечать себя как «статичный пример» —
    // это полезная информация для пользователя, а не индикатор empty-state.
    const { container } = render(<NavigatorChartPreview />);
    expect(screen.queryByText(/загрузка/i)).toBeNull();
    expect(screen.queryByText(/нет данных/i)).toBeNull();
    expect(container.querySelector(".recharts-responsive-container")).toBeTruthy();
  });

  it("does not make any network call (no fetch, no XMLHttpRequest)", () => {
    // Подмена глобального fetch — если компонент попытается, тест упадёт.
    const originalFetch = global.fetch;
    const originalXHR = global.XMLHttpRequest;
    let fetchCalled = false;
    let xhrCreated = false;
    global.fetch = (() => {
      fetchCalled = true;
      throw new Error("NavigatorChartPreview must not call fetch");
    }) as unknown as typeof fetch;
    // @ts-expect-error — intentionally stub XHR
    global.XMLHttpRequest = function () {
      xhrCreated = true;
      throw new Error("NavigatorChartPreview must not create XHR");
    };

    try {
      render(<NavigatorChartPreview />);
      expect(fetchCalled).toBe(false);
      expect(xhrCreated).toBe(false);
    } finally {
      global.fetch = originalFetch;
      global.XMLHttpRequest = originalXHR;
    }
  });

  it("renders the same chart on subsequent renders (deterministic)", () => {
    // В jsdom recharts НЕ строит внутренний SVG (нет layout), поэтому
    // путь линии недоступен. Проверяем детерминизм на уровне данных,
    // которые передаются в LineChart — это и есть источник истины.
    // Два вызова генератора должны вернуть идентичный массив точек.
    const a = getDemoFinanceOhlcvVolumeSeries();
    const b = getDemoFinanceOhlcvVolumeSeries();
    expect(a).toEqual(b);
    // И оба рендера должны показать контейнер графика.
    const { container: c1 } = render(<NavigatorChartPreview />);
    const { container: c2 } = render(<NavigatorChartPreview />);
    expect(c1.querySelector(".recharts-responsive-container")).toBeTruthy();
    expect(c2.querySelector(".recharts-responsive-container")).toBeTruthy();
  });
});
