// packages/ui/components/preprocessing-dataset-editor-toggle.test.tsx
//
// Интеграционные оракулы кнопки «Редактор датасета» в заголовках окон
// Мастеров «Предобработки» (задача DATASET-VIEW-EDITOR-1, 2026-10-16,
// проект решения в worklog10.md; скоуп-уточнение тимлида в чате сессии:
// остановки «Пропуски» и «Выбросы» НЕ трогаются -- там остаётся
// однокнопочный правый край «Исправить вручную» MANUAL-MISSING-1/
// MANUAL-OUTLIERS-1, их контракты не изменяются).
//
// (1) кнопка есть ТОЛЬКО в 6 остановках-источниках новых колонок
//     (regularity, decomposition, variance_stab, smoothing, stationarity,
//     feature_eng) в pipeline-режиме; у «Спектрального анализа» и
//     «Масштабирования» кнопки НЕТ (байт-инвариант остановок без новых
//     колонок); у «Пропусков»/«Выбросов» -- ТОЛЬКО «Исправить вручную»
//     (двукнопочный правый край не вводится);
// (2) клик свапает контент окна: сетка стратегий → регион «Редактор
//     датасета» (DatasetViewEditor) и обратно; активное состояние
//     bg-brand text-white;
// (3) переключение остановки закрывает режим редактора;
// (4) режимы «Исправить вручную» (Пропуски) и «Редактор датасета»
//     независимы: открытие/закрытие одного не влияет на другое.
//
// Корпус дизъюнктен: маркер сессии ds-editor-prepr-1, страницы строк
// «метеостанции», derived-реестр -- 1 производная колонка.

import "@testing-library/jest-dom";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { TsAnalysisPreprocessing } from "./TsAnalysisPreprocessing";
import { AppShellProvider } from "../context/AppShellContext";

const DERIVED = {
  columns: [
    { column: "temp_c_smoothed", stage: "smoothing", source: "smoothing:ema:temp_c", created_at: "2026-10-16T09:00:00+00:00" },
  ],
  total: 1,
};

const ROWS_PAGE = {
  columns: ["recorded_at", "temp_c", "temp_c_smoothed"],
  rows: [["2024-06-01", "10.5", "10.4"]],
  offset: 0,
  limit: 200,
  total_rows: 3,
  returned: 1,
  has_more: false,
};

const TARGET_COLUMN = {
  target_column: "temp_c",
  suggested_column: "temp_c",
  available_columns: ["temp_c"],
  has_dataset: true,
};

function routeFetch() {
  return jest.fn((url: string, init?: RequestInit) => {
    if (typeof url === "string" && url.includes("/session/current")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            has_active_dataset: true,
            dataset: { dataset_id: "ds-editor-meteo-1", name: "meteo.csv", rows: 3, columns: 3, size_label: "1 KB" },
            stages: {},
            last_active_stage: null,
            target_column: null,
            updated_at: null,
          }),
      });
    }
    if (typeof url === "string" && url.includes("/dataset/derived-columns")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(DERIVED) });
    }
    if (typeof url === "string" && url.includes("/dataset/rows")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(ROWS_PAGE) });
    }
    if (typeof url === "string" && url.includes("/target-column")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(TARGET_COLUMN) });
    }
    if (typeof url === "string" && init?.method === "POST") {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ applied: false }) });
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({ detail: "no dataset" }) });
  }) as unknown as typeof fetch;
}

function renderPreprocessing() {
  return render(
    <AppShellProvider>
      <TsAnalysisPreprocessing />
    </AppShellProvider>,
  );
}

// [лейбл остановки в степпере, имя кнопки открытия мастера, имя региона мастера]
const NEWCOL_STOPS: Array<[string, string, string]> = [
  ["Регулярность ряда", "Исправить регулярность", "Мастер исправления регулярности"],
  ["Декомпозиция ряда", "Настроить декомпозицию", "Мастер декомпозиции ряда"],
  ["Стабилизация дисперсии", "Настроить трансформацию", "Мастер стабилизации дисперсии"],
  ["Сглаживание ряда", "Настроить сглаживание", "Мастер сглаживания ряда"],
  ["Стационарность ряда", "Обеспечить стационарность", "Мастер обеспечения стационарности"],
  ["Генерация признаков", "Сгенерировать признаки", "Мастер генерации признаков"],
];

describe("«Редактор датасета» в заголовках Мастеров Предобработки (DATASET-VIEW-EDITOR-1)", () => {
  beforeEach(() => {
    global.ResizeObserver = class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver;
    global.fetch = routeFetch();
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("кнопка есть в мастере «Сглаживания» (pipeline), клик свапает контент окна на регион «Редактор датасета», повторный клик возвращает мастер", async () => {
    renderPreprocessing();
    const leftAside = screen.getByRole("heading", { name: "Preprocessing", level: 2 }).closest("aside")!;
    fireEvent.click(within(leftAside).getByRole("button", { name: /^Сглаживание/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Настроить сглаживание" }));

    const button = await screen.findByRole("button", { name: "Редактор датасета" });
    const row = button.parentElement as HTMLElement;
    expect(row).toHaveClass("flex", "items-center");
    expect(row.querySelector("h3")).toHaveClass("flex-1");
    expect(button).toHaveClass("shrink-0");

    fireEvent.click(button);
    expect(await screen.findByRole("region", { name: "Редактор датасета" })).toBeInTheDocument();
    expect(await screen.findByText("temp_c_smoothed")).toBeInTheDocument();
    // Активное состояние toggle (паттерн «Исправить вручную»).
    expect(screen.getByRole("button", { name: "Редактор датасета" })).toHaveClass("bg-brand");

    fireEvent.click(screen.getByRole("button", { name: "Редактор датасета" }));
    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Редактор датасета" })).toBeNull();
      expect(screen.getByRole("region", { name: "Мастер сглаживания ряда" })).toBeInTheDocument();
    });
  });

  it("кнопка есть во всех 6 остановках-источниках новых колонок (Регулярность/Декомпозиция/Дисперсия/Сглаживание/Стационарность/Генерация признаков)", async () => {
    renderPreprocessing();
    const leftAside = screen.getByRole("heading", { name: "Preprocessing", level: 2 }).closest("aside")!;
    for (const [stopLabel, fixLabel] of NEWCOL_STOPS.map(([s, f]) => [s, f] as const)) {
      fireEvent.click(within(leftAside).getByRole("button", { name: new RegExp(`^${stopLabel}`) }));
      fireEvent.click(await screen.findByRole("button", { name: fixLabel }));
      expect(await screen.findByRole("button", { name: "Редактор датасета" })).toBeInTheDocument();
    }
  });

  it("у «Спектрального анализа» и «Масштабирования» кнопки НЕТ (байт-инвариант остановок без новых колонок)", async () => {
    renderPreprocessing();
    const leftAside = screen.getByRole("heading", { name: "Preprocessing", level: 2 }).closest("aside")!;
    fireEvent.click(within(leftAside).getByRole("button", { name: /^Спектральный/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Зафиксировать периоды" }));
    expect(screen.queryByRole("button", { name: "Редактор датасета" })).toBeNull();

    fireEvent.click(within(leftAside).getByRole("button", { name: /^Масштабирование/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Настроить масштабирование" }));
    expect(screen.queryByRole("button", { name: "Редактор датасета" })).toBeNull();
  });

  it("у «Пропусков»/«Выбросов» правый край остаётся ТОЛЬКО с «Исправить вручную» (двукнопочный правый край не вводится)", async () => {
    renderPreprocessing();
    const leftAside = screen.getByRole("heading", { name: "Preprocessing", level: 2 }).closest("aside")!;

    fireEvent.click(await screen.findByRole("button", { name: "Исправить пропуски" }));
    expect(screen.getByRole("button", { name: "Исправить вручную" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Редактор датасета" })).toBeNull();
    // строка заголовка -- ровно 3 ребёнка: [иконка, h3, кнопка «Исправить вручную»]
    expect(screen.getByRole("button", { name: "Исправить вручную" }).parentElement!.children).toHaveLength(3);

    fireEvent.click(within(leftAside).getByRole("button", { name: /^Выбросы/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Исправить выбросы" }));
    expect(screen.getByRole("button", { name: "Исправить вручную" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Редактор датасета" })).toBeNull();
    expect(screen.getByRole("button", { name: "Исправить вручную" }).parentElement!.children).toHaveLength(3);
  });

  it("переключение остановки закрывает режим редактора; режим независим от «Исправить вручную»", async () => {
    renderPreprocessing();
    const leftAside = screen.getByRole("heading", { name: "Preprocessing", level: 2 }).closest("aside")!;
    fireEvent.click(within(leftAside).getByRole("button", { name: /^Сглаживание/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Настроить сглаживание" }));
    fireEvent.click(await screen.findByRole("button", { name: "Редактор датасета" }));
    expect(await screen.findByRole("region", { name: "Редактор датасета" })).toBeInTheDocument();

    // Переключение остановки закрывает режим редактора.
    fireEvent.click(within(leftAside).getByRole("button", { name: /^Пропуски/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Исправить пропуски" }));
    expect(await screen.findByRole("button", { name: "Исправить вручную" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Редактор датасета" })).toBeNull();

    // Возврат к «Сглаживанию» -- мастер сглаживания рендерится БЕЗ региона
    // редактора (режим был закрыт сменой остановки выше).
    fireEvent.click(within(leftAside).getByRole("button", { name: /^Сглаживание/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Настроить сглаживание" }));
    expect(await screen.findByRole("region", { name: "Мастер сглаживания ряда" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Редактор датасета" })).toBeNull();
  });
});
