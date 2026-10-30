// packages/ui/components/validation-dataset-editor-toggle.test.tsx
//
// Интеграционные оракулы кнопки «Редактор датасета» в заголовках окон
// Мастеров «Валидации» (задача DATASET-VIEW-EDITOR-1, 2026-10-16, проект
// решения в worklog10.md): 9 остановок-источников флаг-колонок получают
// кнопку правым краем заголовка (впервые для «Валидации»); «Типы данных»
// НЕ получают (байт-инвариант остановки без новых колонок).
//
// (1) кнопка есть в 9 остановках (formats, ranges, consistency, uniqueness,
//     inclusion, referential, text_quality, regularity, sufficiency) в
//     pipeline-режиме; у «Типов данных» кнопки НЕТ;
// (2) клик свапает контент окна: сетка мастера → регион «Редактор
//     датасета» и обратно; активное состояние bg-brand;
// (3) переключение проверки закрывает режим редактора.
//
// Корпус дизъюнктен: маркер сессии ds-editor-val-1, страницы строк
// «метеостанции», derived-реестр -- 1 флаг-колонка форматов.

import "@testing-library/jest-dom";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { TsAnalysisValidation } from "./TsAnalysisValidation";
import { AppShellProvider } from "../context/AppShellContext";

const DERIVED = {
  columns: [
    { column: "temp_c_format_valid", stage: "formats", source: "format_correction:flag:temp_c", created_at: "2026-10-16T09:00:00+00:00" },
  ],
  total: 1,
};

const ROWS_PAGE = {
  columns: ["recorded_at", "temp_c", "temp_c_format_valid"],
  rows: [["2024-06-01", "10.5", "1.0"]],
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

const VALIDATION_SUMMARY = {
  has_dataset: true,
  rule_source: "system",
  checks: [
    { id: "data_types", status: "pending", status_reason: null },
    { id: "formats", status: "pending", status_reason: null },
    { id: "ranges", status: "pending", status_reason: null },
    { id: "consistency", status: "pending", status_reason: null },
    { id: "uniqueness", status: "pending", status_reason: null },
    { id: "inclusion", status: "pending", status_reason: null },
    { id: "referential", status: "pending", status_reason: null },
    { id: "text_quality", status: "pending", status_reason: null },
    { id: "regularity", status: "pending", status_reason: null },
    { id: "sufficiency", status: "pending", status_reason: null },
  ],
  generated_at: "2026-10-16T09:00:00Z",
};

function routeFetch() {
  return jest.fn((url: string) => {
    if (typeof url === "string" && url.includes("/session/current")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            has_active_dataset: true,
            dataset: { dataset_id: "ds-editor-val-1", name: "meteo.csv", rows: 3, columns: 3, size_label: "1 KB" },
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
    if (typeof url === "string" && url.includes("/dataset/validate")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(VALIDATION_SUMMARY) });
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({ detail: "no dataset" }) });
  }) as unknown as typeof fetch;
}

function renderValidation() {
  return render(
    <AppShellProvider>
      <TsAnalysisValidation />
    </AppShellProvider>,
  );
}

// 9 остановок с кнопкой: [лейбл степпера, имя кнопки открытия мастера]
const NEWCOL_STOPS: Array<[RegExp, string]> = [
  [/^Форматы/, "Исправить форматы и шаблоны"],
  [/^Диапазоны/, "Исправить диапазоны значений"],
  [/^Логика/, "Исправить логику и хронологию"],
  [/^Уникальность/, "Исправить уникальность"],
  [/^Принадлежность/, "Исправить принадлежность к набору"],
  [/^Ссылочная/, "Исправить ссылочную целостность"],
  [/^Целостность/, "Исправить целостность текста"],
  [/^Равномерность/, "Исправить равномерность шага"],
  [/^Достаточность/, "Настроить план анализа"],
];

describe("«Редактор датасета» в заголовках Мастеров Валидации (DATASET-VIEW-EDITOR-1)", () => {
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

  it("кнопка есть в мастере «Форматов» (pipeline), клик свапает контент окна на регион «Редактор датасета», повторный клик возвращает мастер", async () => {
    renderValidation();
    fireEvent.click(await screen.findByRole("button", { name: "Исправить форматы и шаблоны" }));

    const button = await screen.findByRole("button", { name: "Редактор датасета" });
    const row = button.parentElement as HTMLElement;
    expect(row).toHaveClass("flex", "items-center");
    expect(row.querySelector("h3")).toHaveClass("flex-1");
    expect(button).toHaveClass("shrink-0");

    fireEvent.click(button);
    expect(await screen.findByRole("region", { name: "Редактор датасета" })).toBeInTheDocument();
    expect(await screen.findByText("temp_c_format_valid")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Редактор датасета" })).toHaveClass("bg-brand");

    fireEvent.click(screen.getByRole("button", { name: "Редактор датасета" }));
    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "Редактор датасета" })).toBeNull(),
    );
  });

  it.each(NEWCOL_STOPS)("кнопка есть в остановке %s (мастер «%s»)", async (stopLabel, fixLabel) => {
    renderValidation();
    // Hydrate the initial check before selecting this independent stop.
    await screen.findByRole("button", { name: "Исправить форматы и шаблоны" });
    const leftAside = screen.getByRole("heading", { name: "Data Quality", level: 2 }).closest("aside")!;
    fireEvent.click(within(leftAside).getByRole("button", { name: stopLabel }));
    fireEvent.click(await screen.findByRole("button", { name: fixLabel }));
    expect(await screen.findByRole("button", { name: "Редактор датасета" })).toBeInTheDocument();
  });

  it("у «Типов данных» кнопки НЕТ (байт-инвариант остановки без новых колонок)", async () => {
    renderValidation();
    fireEvent.click(await screen.findByRole("button", { name: "Исправить типы данных" }));
    expect(screen.queryByRole("button", { name: "Редактор датасета" })).toBeNull();
    // строка заголовка мастера типов -- без кнопок правого края (2 ребёнка)
    const hMaster = screen.getByRole("heading", { name: "Мастер исправления типов", level: 3 });
    expect(hMaster.parentElement!.children).toHaveLength(2);
  });

  it("переключение проверки закрывает режим редактора", async () => {
    renderValidation();
    fireEvent.click(await screen.findByRole("button", { name: "Исправить форматы и шаблоны" }));
    fireEvent.click(await screen.findByRole("button", { name: "Редактор датасета" }));
    expect(await screen.findByRole("region", { name: "Редактор датасета" })).toBeInTheDocument();

    const leftAside = screen.getByRole("heading", { name: "Data Quality", level: 2 }).closest("aside")!;
    fireEvent.click(within(leftAside).getByRole("button", { name: /^Диапазоны/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Исправить диапазоны значений" }));

    // Режим закрыт сменой проверки; у нового мастера кнопка есть, но не активна.
    const button = await screen.findByRole("button", { name: "Редактор датасета" });
    expect(button).not.toHaveClass("bg-brand");
    expect(screen.queryByRole("region", { name: "Редактор датасета" })).toBeNull();
  });
});
