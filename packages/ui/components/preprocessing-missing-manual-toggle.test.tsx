// packages/ui/components/preprocessing-missing-manual-toggle.test.tsx
//
// Интеграционные оракулы кнопки «Исправить вручную» в заголовке окна
// «Мастер исправления пропусков» (задача MANUAL-MISSING-1, 2026-10-15):
//
// (1) кнопка появляется ТОЛЬКО в режиме остановки «Пропуски» + pipeline
//     (заголовок мастера), отцентрована по правому краю строки-заголовка
//     (h3 flex-1 прижимает кнопку к правому краю центральной колонки,
//     кнопка shrink-0 -- структурный паттерн левых колонок
//     UI-UPLOAD-HELP-1/UI-PREPR-HDR-1);
// (2) клик открывает редактор (region «Ручное исправление пропусков»)
//     ВМЕСТО сетки мастера, кнопка получает активное состояние
//     (bg-brand text-white -- паттерн toggle «Справки»); повторный клик
//     возвращает сетку мастера;
// (3) переключение остановки закрывает ручной режим (возврат к «Пропускам»
//     показывает сетку мастера, не редактор) -- зеркально инварианту
//     Справки;
// (4) у ДРУГИХ остановок кнопки «Исправить
//     вручную» НЕТ, строка заголовка без flex-1 (байт-инвариант остальных
//     окон). VERSIONED (MANUAL-OUTLIERS-1, 2026-10-15): «Выбросы» ВЫШЛИ
//     из этого пина -- получили СВОЮ кнопку в заголовке мастера (тот же
//     паттерн). VERSIONED (DATASET-VIEW-EDITOR-1, 2026-10-16): «Регулярность»
//     ВЫШЛА из пина -- получила кнопку «Редактор датасета» и flex-1
//     (остановка-источник новых колонок); регрессионная цель
//     байт-инварианта -- «Спектральный анализ» (без новых колонок,
//     без кнопок).
//
// Корпус дизъюнктен: мок /session/current с маркером сессии
// manual-missing-1; маршруты редактора -- свои страницы «метеостанции».

import "@testing-library/jest-dom";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { TsAnalysisPreprocessing } from "./TsAnalysisPreprocessing";
import { AppShellProvider } from "../context/AppShellContext";

const MISSING_PROFILE = {
  rule_source: "system",
  mode: "auto",
  status: "warning",
  status_reason: null,
  total_rows: 3,
  total_columns: 3,
  total_missing: 3,
  missing_rate_pct: 33.33,
  rows_with_missing: 3,
  rows_with_missing_pct: 100,
  empty_rows: 0,
  columns: [
    {
      column: "temp_c", dtype: "float64", semantic: "numeric", total_count: 3,
      missing_count: 2, non_missing_count: 1, missing_pct: 66.67,
      recommended_strategy: "interpolate", missing_examples: [1, 2],
    },
  ],
  row_histogram: [],
};

const OUTLIERS_PROFILE = {
  rule_source: "system",
  mode: "auto",
  status: "done",
  status_reason: null,
  method: "iqr",
  total_rows: 3,
  total_numeric_columns: 1,
  total_outliers: 0,
  outlier_rate_pct: 0,
  affected_columns: [],
  columns: [],
};

const EDITOR_PAGE = {
  columns: [
    { column: "recorded_at", dtype: "object", semantic: "text" },
    { column: "temp_c", dtype: "float64", semantic: "numeric" },
    { column: "humidity", dtype: "float64", semantic: "numeric" },
  ],
  rows: [{ row_index: 2, cells: ["2024-06-03", null, 60.0] }],
  offset: 0,
  limit: 200,
  total_rows: 3,
  returned: 1,
  has_more: false,
};

function routeFetch() {
  return jest.fn((url: string, init?: RequestInit) => {
    if (typeof url === "string" && url.includes("/session/current")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            has_active_dataset: true,
            dataset: { dataset_id: "manual-meteo-1", name: "meteo.csv", rows: 3, columns: 3, size_label: "1 KB" },
            stages: {},
            last_active_stage: null,
            target_column: null,
            updated_at: null,
          }),
      });
    }
    if (url.includes("/dataset/missing-editor-rows")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(EDITOR_PAGE) });
    }
    if (url.includes("/dataset/missing-manual-corrections")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            applied: true,
            total_edited_requested: 1,
            total_changed: 1,
            total_missing_before: 3,
            total_missing_after: 2,
            profile: [],
            derived_summary: null,
          }),
      });
    }
    if (url.includes("/dataset/outlier-profile")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(OUTLIERS_PROFILE) });
    }
    if (url.includes("/dataset/missing-profile")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(MISSING_PROFILE) });
    }
    if (url.includes("/target-column")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            target_column: "temp_c",
            suggested_column: "temp_c",
            available_columns: ["temp_c"],
            has_dataset: true,
          }),
      });
    }
    if (init?.method === "POST") {
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

describe("«Исправить вручную» в заголовке мастера пропусков (MANUAL-MISSING-1)", () => {
  beforeEach(() => {
    global.fetch = routeFetch();
  });

  it("shows the manual button right-aligned in the missing-master header row (h3 flex-1, button shrink-0)", async () => {
    renderPreprocessing();
    await screen.findByRole("table", { name: "Матрица пропусков по колонкам" });
    fireEvent.click(screen.getByRole("button", { name: "Исправить пропуски" }));
    expect(await screen.findByRole("region", { name: "Мастер исправления пропусков" })).toBeInTheDocument();

    const button = screen.getByRole("button", { name: "Исправить вручную" });
    expect(button).toBeInTheDocument();
    // структурный пин правого края: строка-заголовок -- flex-контейнер,
    // h3 растянут (flex-1), кнопка не сжимается (shrink-0)
    const row = button.parentElement as HTMLElement;
    expect(row).toHaveClass("flex", "items-center");
    const h3 = row.querySelector("h3") as HTMLElement;
    expect(h3).toHaveClass("flex-1");
    expect(button).toHaveClass("shrink-0");
  });

  it("click opens the manual editor INSTEAD of the master grid; click again returns the master", async () => {
    renderPreprocessing();
    await screen.findByRole("table", { name: "Матрица пропусков по колонкам" });
    fireEvent.click(screen.getByRole("button", { name: "Исправить пропуски" }));
    expect(await screen.findByRole("region", { name: "Мастер исправления пропусков" })).toBeInTheDocument();
    expect(screen.getByText("1. Колонки с пропусками")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Исправить вручную" }));
    const editor = await screen.findByRole("region", { name: "Ручное исправление пропусков" });
    expect(editor).toBeInTheDocument();
    expect(screen.queryByText("1. Колонки с пропусками")).not.toBeInTheDocument();
    // активное состояние кнопки (toggle-паттерн «Справки»)
    expect(screen.getByRole("button", { name: "Исправить вручную" })).toHaveClass("bg-brand");

    fireEvent.click(screen.getByRole("button", { name: "Исправить вручную" }));
    await waitFor(() => {
      expect(screen.getByText("1. Колонки с пропусками")).toBeInTheDocument();
    });
    expect(screen.queryByRole("region", { name: "Ручное исправление пропусков" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Исправить вручную" })).toHaveClass("bg-brand-light");
  });

  it("switching a stop closes manual mode (return shows metrics section; reopened master is the grid, not the editor)", async () => {
    renderPreprocessing();
    await screen.findByRole("table", { name: "Матрица пропусков по колонкам" });
    fireEvent.click(screen.getByRole("button", { name: "Исправить пропуски" }));
    expect(await screen.findByRole("region", { name: "Мастер исправления пропусков" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Исправить вручную" }));
    expect(await screen.findByRole("region", { name: "Ручное исправление пропусков" })).toBeInTheDocument();

    // переключились на «Выбросы» кнопкой степпера
    fireEvent.click(screen.getByText("Выбросы"));
    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Ручное исправление пропусков" })).not.toBeInTheDocument();
    });

    // вернулись к «Пропускам» -- метрики-секция (инвариант информативности),
    // редактор НЕ открыт
    fireEvent.click(screen.getByText("Пропуски"));
    await waitFor(() => {
      expect(screen.getByRole("table", { name: "Матрица пропусков по колонкам" })).toBeInTheDocument();
    });
    expect(screen.queryByRole("region", { name: "Ручное исправление пропусков" })).not.toBeInTheDocument();

    // повторно открыли мастер -- сетка стратегий, а НЕ редактор (режим закрыт)
    fireEvent.click(screen.getByRole("button", { name: "Исправить пропуски" }));
    await waitFor(() => {
      expect(screen.getByText("1. Колонки с пропусками")).toBeInTheDocument();
    });
    expect(screen.queryByRole("region", { name: "Ручное исправление пропусков" })).not.toBeInTheDocument();
  });

  it("VERSIONED MANUAL-OUTLIERS-1 + DATASET-VIEW-EDITOR-1: outliers master got its own manual button; spectral master keeps the byte-identical row", async () => {
    renderPreprocessing();
    await screen.findByRole("table", { name: "Матрица пропусков по колонкам" });
    // VERSIONED (MANUAL-OUTLIERS-1): «Выбросы» ВЫШЛИ из пина «окон без
    // кнопки» -- мастер выбросов несёт СВОЮ кнопку «Исправить вручную»
    // и flex-1 (тот же структурный паттерн, что мастер пропусков).
    fireEvent.click(screen.getByText("Выбросы"));
    fireEvent.click(await screen.findByRole("button", { name: "Исправить выбросы" }));
    expect(await screen.findByRole("region", { name: "Мастер исправления выбросов" })).toBeInTheDocument();
    const outliersButton = screen.getByRole("button", { name: "Исправить вручную" });
    const outliersRow = outliersButton.parentElement as HTMLElement;
    expect(outliersRow).toHaveClass("flex", "items-center");
    expect(outliersRow.querySelector("h3")).toHaveClass("flex-1");
    expect(outliersButton).toHaveClass("shrink-0");

    // VERSIONED (DATASET-VIEW-EDITOR-1): «Регулярность» ВЫШЛА из пина
    // -- несёт кнопку «Редактор датасета» (отдельную от «Исправить
    // вручную», которого у неё нет) и flex-1.
    fireEvent.click(screen.getByText("Регулярность ряда"));
    fireEvent.click(await screen.findByRole("button", { name: "Исправить регулярность" }));
    expect(await screen.findByRole("region", { name: "Мастер исправления регулярности" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Исправить вручную" })).not.toBeInTheDocument();
    const regularityButton = screen.getByRole("button", { name: "Редактор датасета" });
    const regularityRow = regularityButton.parentElement as HTMLElement;
    expect(regularityRow.querySelector("h3")).toHaveClass("flex-1");
    expect(regularityButton).toHaveClass("shrink-0");

    // Спектральный анализ -- регрессионная цель байт-инварианта: без
    // «Исправить вручную», без «Редактора датасета», h3 без flex-1.
    fireEvent.click(screen.getByText("Спектральный анализ"));
    fireEvent.click(await screen.findByRole("button", { name: "Зафиксировать периоды" }));
    expect(await screen.findByRole("region", { name: "Мастер спектрального анализа" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Исправить вручную" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Редактор датасета" })).not.toBeInTheDocument();
    const h3 = screen.getByRole("heading", { name: "Мастер спектрального анализа" });
    expect(h3).not.toHaveClass("flex-1");
  });
});
