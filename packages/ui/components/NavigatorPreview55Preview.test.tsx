// packages/ui/components/NavigatorPreview55Preview.test.tsx
//
// Тесты статичного превью 5+5 строк для окна «Обзор» остановки
// «Превью 5+5 строк» (id="preview_5_5") секции «Этапы модуля»
// остановки «Загрузка» на странице Навигатор.
//
// Контракт (задача 2026-09-01):
//   - Визуализация — СТАТИЧНАЯ таблица 5+5 строк синтетического датасета
//     demo_finance_ohlcv.csv (первые 5 строк + separator «…» + последние
//     5 строк), тот же детерминированный генератор, что и в Task 64
//     (NavigatorChartPreview).
//   - Источник: packages/ui/lib/demoDatasets.ts::generateFinanceOhlcv
//     (mulberry32 seed 20260821, 500 торговых дней, без выходных;
//     колонки: date,open,high,low,close,volume).
//   - Превью закреплено СТАТИЧНО как пример — НЕ зависит от useAppShell,
//     activeDataset, fetch, сети, сессии. Даже если датасет удалён,
//     превью остаётся на месте (это и есть требование тимлида).
//
// Архитектурно — ближайший родственник NavigatorChartPreview (Task 64):
// статичные данные из детерминированного генератора, role="img" +
// aria-label, без recharts (таблица вместо графика).

import React from "react";
import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import {
  NavigatorPreview55Preview,
  NAVIGATOR_PREVIEW55_DATASET_FILE,
  NAVIGATOR_PREVIEW55_FEATURE,
} from "./NavigatorPreview55Preview";
import { getDemoFinanceOhlcvPreview55 } from "../lib/demoDatasets";

// ─────────────────────────────────────────────────────────────────────────
// Контракт данных: детерминированный генератор -> { head, tail }
// ─────────────────────────────────────────────────────────────────────────

describe("NavigatorPreview55Preview — data contract", () => {
  it("getDemoFinanceOhlcvPreview55() returns head with 1 header + 5 data rows", () => {
    const { head } = getDemoFinanceOhlcvPreview55();
    // head[0] — заголовки колонок (6 колонок: date,open,high,low,close,volume)
    expect(head).toHaveLength(6);
    expect(head[0]).toEqual([
      "date", "open", "high", "low", "close", "volume",
    ]);
  });

  it("getDemoFinanceOhlcvPreview55() returns tail with exactly 5 rows", () => {
    const { tail } = getDemoFinanceOhlcvPreview55();
    expect(tail).toHaveLength(5);
  });

  it("head data rows have 6 cells each (matches header)", () => {
    const { head } = getDemoFinanceOhlcvPreview55();
    head.slice(1).forEach((row) => {
      expect(row).toHaveLength(6);
    });
  });

  it("tail rows have 6 cells each", () => {
    const { tail } = getDemoFinanceOhlcvPreview55();
    tail.forEach((row) => {
      expect(row).toHaveLength(6);
    });
  });

  it("first head data row date is 2022-01-03 (Monday) — matches seed", () => {
    const { head } = getDemoFinanceOhlcvPreview55();
    expect(head[1][0]).toBe("2022-01-03");
  });

  it("is deterministic — two calls produce identical preview", () => {
    const a = getDemoFinanceOhlcvPreview55();
    const b = getDemoFinanceOhlcvPreview55();
    expect(a).toEqual(b);
  });

  it("head and tail do NOT overlap (500 rows > 5+5)", () => {
    const { head, tail } = getDemoFinanceOhlcvPreview55();
    const headDates = new Set(head.slice(1).map((r) => r[0]));
    const tailDates = new Set(tail.map((r) => r[0]));
    // 500 строк, head — первые 5, tail — последние 5 → пересечение пусто.
    tailDates.forEach((d) => {
      expect(headDates.has(d)).toBe(false);
    });
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Рендер: статичная таблица 5+5, без зависимостей от сессии/сети
// ─────────────────────────────────────────────────────────────────────────

describe("NavigatorPreview55Preview — rendering", () => {
  it("renders without AppShellProvider (no session dependency)", () => {
    // Если компонент попытается вызвать useAppShell() — упадёт с
    // "useAppShell должен вызываться внутри <AppShellProvider>".
    const { container } = render(<NavigatorPreview55Preview />);
    expect(container.firstChild).not.toBeNull();
  });

  it("renders the section heading «Превью 5+5 строк»", () => {
    render(<NavigatorPreview55Preview />);
    expect(
      screen.getByRole("heading", {
        level: 3,
        name: /превью 5\+5 строк/i,
      })
    ).toBeInTheDocument();
  });

  it("exposes static dataset id = demo_finance_ohlcv", () => {
    expect(NAVIGATOR_PREVIEW55_DATASET_FILE).toBe("demo_finance_ohlcv.csv");
  });

  it("exposes feature name = OHLCV preview", () => {
    expect(NAVIGATOR_PREVIEW55_FEATURE).toBe("OHLCV");
  });

  it("renders the dataset filename visible to the user", () => {
    render(<NavigatorPreview55Preview />);
    expect(screen.getAllByText(/demo_finance_ohlcv\.csv/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders all 6 column headers in the table", () => {
    render(<NavigatorPreview55Preview />);
    // Заголовки: date, open, high, low, close, volume
    expect(screen.getByText("date")).toBeInTheDocument();
    expect(screen.getByText("open")).toBeInTheDocument();
    expect(screen.getByText("high")).toBeInTheDocument();
    expect(screen.getByText("low")).toBeInTheDocument();
    expect(screen.getByText("close")).toBeInTheDocument();
    expect(screen.getByText("volume")).toBeInTheDocument();
  });

  it("renders the separator row «…» between head and tail", () => {
    render(<NavigatorPreview55Preview />);
    // Разделитель «…» между первыми 5 и последними 5 строками —
    // тот же визуальный паттерн, что в TsAnalysisUpload.tsx:1035.
    expect(screen.getByText(/…/)).toBeInTheDocument();
  });

  it("renders exactly 5 head data rows + 5 tail data rows (10 total)", () => {
    render(<NavigatorPreview55Preview />);
    // Каждая строка данных помечена data-testid="preview-row".
    // Должно быть ровно 10: 5 head + 5 tail (header и separator не считаются).
    const rows = document.querySelectorAll('[data-testid="preview-row"]');
    expect(rows).toHaveLength(10);
  });

  it("renders first head data row date = 2022-01-03", () => {
    render(<NavigatorPreview55Preview />);
    // Первая строка данных (после header) — 2022-01-03 (понедельник).
    expect(screen.getByText("2022-01-03")).toBeInTheDocument();
  });

  it("renders without loading/empty state — always shows table", () => {
    const { container } = render(<NavigatorPreview55Preview />);
    expect(screen.queryByText(/нет данных/i)).toBeNull();
    expect(container.firstChild).not.toBeNull();
  });

  it("does not make any network call (no fetch, no XMLHttpRequest)", () => {
    const originalFetch = global.fetch;
    const originalXHR = global.XMLHttpRequest;
    let fetchCalled = false;
    let xhrCreated = false;
    global.fetch = (() => {
      fetchCalled = true;
      throw new Error("NavigatorPreview55Preview must not call fetch");
    }) as unknown as typeof fetch;
    // @ts-expect-error — intentionally stub XHR
    global.XMLHttpRequest = function () {
      xhrCreated = true;
      throw new Error("NavigatorPreview55Preview must not create XHR");
    };

    try {
      render(<NavigatorPreview55Preview />);
      expect(fetchCalled).toBe(false);
      expect(xhrCreated).toBe(false);
    } finally {
      global.fetch = originalFetch;
      global.XMLHttpRequest = originalXHR;
    }
  });

  it("renders deterministically (no random content between renders)", () => {
    const { container: c1, rerender } = render(<NavigatorPreview55Preview />);
    const text1 = c1.textContent;
    rerender(<NavigatorPreview55Preview />);
    const text2 = c1.textContent;
    expect(text2).toBe(text1);
  });

  it("has role=img with informative aria-label on the root container", () => {
    const { container } = render(<NavigatorPreview55Preview />);
    const root = container.firstChild as HTMLElement;
    expect(root.getAttribute("role")).toBe("img");
    expect(root.getAttribute("aria-label") ?? "").toMatch(
      /превью|5\+5|demo_finance_ohlcv/i
    );
  });

  it("renders the static example badge (статичный пример)", () => {
    render(<NavigatorPreview55Preview />);
    // Помечаем превью как статичный пример, чтобы пользователь понимал,
    // что это не реальные данные из сессии.
    expect(screen.getByText(/статичный пример/i)).toBeInTheDocument();
  });
});
