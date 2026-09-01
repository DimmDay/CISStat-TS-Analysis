// packages/ui/components/NavigatorDistributionPreview.test.tsx
//
// Тесты статичной визуализации распределения для окна «Обзор» остановки
// «Визуализация распределения» (id="distribution") секции «Этапы модуля»
// остановки «Загрузка» на странице Навигатор.
//
// Контракт (задача 2026-09-02):
//   - Визуализация — СТАТИЧНЫЕ графики распределения (точечный/гистограмма/KDE)
//     + бейджи описательной статистики синтетического датасета
//     demo_energy_consumption.csv (колонка consumption_mwh, 300 значений).
//   - Источник: packages/ui/lib/demoDatasets.ts::generateEnergyConsumption
//     (mulberry32 seed 20260820, 5 регионов × 60 месяцев, сбалансированная
//     панель; колонки: region, month, consumption_mwh).
//   - Визуализация закреплена СТАТИЧНО как пример — НЕ зависит от
//     useAppShell, activeDataset, fetch, сети, сессии. Даже если датасет
//     удалён, графики и бейджи остаются на месте.
//
// Архитектурно — ближайший родственник NavigatorChartPreview (Task 64)
// и NavigatorPreview55Preview (Task 85): статичные данные из
// детерминированного генератора, переиспользует существующие
// ScatterDistributionChart/HistogramDistributionChart/KdeDistributionChart
// из DistributionCharts.tsx.

import React from "react";
import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import {
  NavigatorDistributionPreview,
  NAVIGATOR_DISTRIBUTION_DATASET_FILE,
  NAVIGATOR_DISTRIBUTION_FEATURE,
} from "./NavigatorDistributionPreview";
import { getDemoEnergyDistributionData } from "../lib/demoDatasets";

// ── Polyfill: ResizeObserver не определён в jsdom (нужен Recharts ResponsiveContainer) ──
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// ─────────────────────────────────────────────────────────────────────────
// Контракт данных: детерминированный генератор → DistributionChartData + Stats
// ─────────────────────────────────────────────────────────────────────────

describe("NavigatorDistributionPreview — data contract", () => {
  it("getDemoEnergyDistributionData() returns 300 data points (5 regions × 60 months)", () => {
    const data = getDemoEnergyDistributionData();
    expect(data.rawValues).toHaveLength(300);
  });

  it("each raw value is finite and positive (consumption in MWh)", () => {
    const data = getDemoEnergyDistributionData();
    data.rawValues.forEach((v) => {
      expect(Number.isFinite(v)).toBe(true);
      expect(v).toBeGreaterThan(0);
    });
  });

  it("is deterministic — two calls produce identical data", () => {
    const a = getDemoEnergyDistributionData();
    const b = getDemoEnergyDistributionData();
    expect(a).toEqual(b);
  });

  it("returns distribution data with scatter, histogram, kde", () => {
    const data = getDemoEnergyDistributionData();
    expect(data.distribution.column).toBe("consumption_mwh");
    expect(data.distribution.scatter.length).toBeGreaterThan(0);
    expect(data.distribution.histogram.length).toBeGreaterThan(0);
    expect(data.distribution.kde).not.toBeNull();
    expect(data.distribution.kde!.length).toBeGreaterThan(0);
  });

  it("returns descriptive stats (mean/median/std/skew/kurtosis/q1/q3/iqr)", () => {
    const stats = getDemoEnergyDistributionData().stats;
    expect(Number.isFinite(stats.mean)).toBe(true);
    expect(Number.isFinite(stats.median)).toBe(true);
    expect(Number.isFinite(stats.std)).toBe(true);
    expect(Number.isFinite(stats.q1)).toBe(true);
    expect(Number.isFinite(stats.q3)).toBe(true);
    expect(Number.isFinite(stats.iqr)).toBe(true);
    // skewness/kurtosis могут быть null для коротких рядов (бэкенд так же
    // сериализует NaN в null), но для 300 значений должны быть числами.
    expect(stats.skewness).not.toBeNull();
    expect(stats.kurtosis).not.toBeNull();
  });

  it("min/max in distribution match raw values", () => {
    const data = getDemoEnergyDistributionData();
    const min = Math.min(...data.rawValues);
    const max = Math.max(...data.rawValues);
    expect(data.distribution.min).toBeCloseTo(min, 0);
    expect(data.distribution.max).toBeCloseTo(max, 0);
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Рендер: статичная визуализация, без зависимостей от сессии/сети
// ─────────────────────────────────────────────────────────────────────────

describe("NavigatorDistributionPreview — rendering", () => {
  it("renders without AppShellProvider (no session dependency)", () => {
    const { container } = render(<NavigatorDistributionPreview />);
    expect(container.firstChild).not.toBeNull();
  });

  it("renders the section heading «Визуализация распределения»", () => {
    render(<NavigatorDistributionPreview />);
    expect(
      screen.getByRole("heading", {
        level: 3,
        name: /визуализация распределения/i,
      })
    ).toBeInTheDocument();
  });

  it("exposes static dataset file = demo_energy_consumption.csv", () => {
    expect(NAVIGATOR_DISTRIBUTION_DATASET_FILE).toBe("demo_energy_consumption.csv");
  });

  it("exposes feature name = consumption_mwh", () => {
    expect(NAVIGATOR_DISTRIBUTION_FEATURE).toBe("consumption_mwh");
  });

  it("renders the dataset filename visible to the user", () => {
    render(<NavigatorDistributionPreview />);
    expect(
      screen.getAllByText(/demo_energy_consumption\.csv/i).length
    ).toBeGreaterThanOrEqual(1);
  });

  it("renders the feature label consumption_mwh visible to the user", () => {
    render(<NavigatorDistributionPreview />);
    expect(
      screen.getAllByText(/consumption_mwh/i).length
    ).toBeGreaterThanOrEqual(1);
  });

  it("renders 3 recharts chart frames (scatter/histogram/kde)", () => {
    const { container } = render(<NavigatorDistributionPreview />);
    // 3 графика → 3 recharts-responsive-container.
    const containers = container.querySelectorAll(".recharts-responsive-container");
    expect(containers.length).toBe(3);
  });

  it("renders 8 descriptive statistics Metric badges", () => {
    render(<NavigatorDistributionPreview />);
    // 8 метрик: Mean, Median, Std, Skewness, Kurtosis, Q1, Q3, IQR.
    expect(screen.getByText(/mean.*среднее/i)).toBeInTheDocument();
    expect(screen.getByText(/median.*медиана/i)).toBeInTheDocument();
    expect(screen.getByText(/std.*стандартное/i)).toBeInTheDocument();
    expect(screen.getByText(/skewness.*асимметрия/i)).toBeInTheDocument();
    expect(screen.getByText(/kurtosis.*эксцесс/i)).toBeInTheDocument();
    expect(screen.getByText(/q1.*1 квартиль/i)).toBeInTheDocument();
    expect(screen.getByText(/q3.*3 квартиль/i)).toBeInTheDocument();
    expect(screen.getByText(/iqr.*межквартильный/i)).toBeInTheDocument();
  });

  it("renders the «статичный пример» badge", () => {
    render(<NavigatorDistributionPreview />);
    expect(screen.getByText(/статичный пример/i)).toBeInTheDocument();
  });

  it("renders without loading/empty state — always shows charts + stats", () => {
    const { container } = render(<NavigatorDistributionPreview />);
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
      throw new Error("NavigatorDistributionPreview must not call fetch");
    }) as unknown as typeof fetch;
    // @ts-expect-error — intentionally stub XHR
    global.XMLHttpRequest = function () {
      xhrCreated = true;
      throw new Error("NavigatorDistributionPreview must not create XHR");
    };

    try {
      render(<NavigatorDistributionPreview />);
      expect(fetchCalled).toBe(false);
      expect(xhrCreated).toBe(false);
    } finally {
      global.fetch = originalFetch;
      global.XMLHttpRequest = originalXHR;
    }
  });

  it("renders deterministically (no random content between renders)", () => {
    const { container: c1, rerender } = render(<NavigatorDistributionPreview />);
    const text1 = c1.textContent;
    rerender(<NavigatorDistributionPreview />);
    const text2 = c1.textContent;
    expect(text2).toBe(text1);
  });

  it("has role=img with informative aria-label on the root container", () => {
    const { container } = render(<NavigatorDistributionPreview />);
    const root = container.firstChild as HTMLElement;
    expect(root.getAttribute("role")).toBe("img");
    expect(root.getAttribute("aria-label") ?? "").toMatch(
      /распределение|demo_energy_consumption|consumption_mwh/i
    );
  });
});
