// packages/ui/components/dvecert_toggle_oracles.test.tsx
//
// НЕЗАВИСИМЫЕ интеграционные оракулы сертификации DATASET-VIEW-EDITOR-1-CERT
// (2026-10-16): кнопка «Редактор датасета» в заголовках Мастеров --
// СВОИ остановки сертификатора (дизъюнктны repo-сюитам задачи, которые
// водят «Сглаживание»/«Форматы»; здесь -- «Стабилизация дисперсии»,
// «Уникальность»; негативные байт-инварианты -- Пропуски/Выбросы/Спектр,
// «Типы данных»). Корпус -- «порт-звонки» (dvecert_*).
//
// Запуск: npx jest dvecert_toggle_oracles (из корня монорепо).
// Правила AGENTS.md: артефакт сертификации, commit/push НЕ выполняются.

import "@testing-library/jest-dom";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { TsAnalysisPreprocessing } from "./TsAnalysisPreprocessing";
import { TsAnalysisValidation } from "./TsAnalysisValidation";
import { AppShellProvider } from "../context/AppShellContext";

const DERIVED = {
  columns: [
    { column: "cargo_kt_yj", stage: "variance_stab", source: "variance_stab:yeo_johnson:cargo_kt", created_at: "2026-10-16T10:30:00+00:00" },
  ],
  total: 1,
};

const ROWS_PAGE = {
  columns: ["month", "calls", "cargo_kt", "cargo_kt_yj"],
  rows: [["2023-03-01", "12", "305.5", "5.4"]],
  offset: 0,
  limit: 200,
  total_rows: 3,
  returned: 1,
  has_more: false,
};

const TARGET_COLUMN = {
  target_column: "calls",
  suggested_column: "calls",
  available_columns: ["calls"],
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
  generated_at: "2026-10-16T10:30:00Z",
};

function routeFetch() {
  return jest.fn((url: string, init?: RequestInit) => {
    if (typeof url === "string" && url.includes("/session/current")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            has_active_dataset: true,
            dataset: { dataset_id: "ds-cert-port-1", name: "port_calls_2023.csv", rows: 3, columns: 4, size_label: "2 KB" },
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

function renderValidation() {
  return render(
    <AppShellProvider>
      <TsAnalysisValidation />
    </AppShellProvider>,
  );
}

describe("dvecert: кнопка «Редактор датасета» -- СВОИ остановки сертификации", () => {
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

  it("CERT-T1: Preprocessing «Стабилизация дисперсии» -- кнопка есть (aria-pressed, flex-1), своп на регион «Редактор датасета», повторный клик возвращает мастер", async () => {
    renderPreprocessing();
    const leftAside = screen.getByRole("heading", { name: "Preprocessing", level: 2 }).closest("aside")!;
    fireEvent.click(within(leftAside).getByRole("button", { name: /^Стабилизация дисперсии/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Настроить трансформацию" }));

    const button = await screen.findByRole("button", { name: "Редактор датасета" });
    expect(button).toHaveAttribute("aria-pressed", "false");
    const row = button.parentElement as HTMLElement;
    expect(row.querySelector("h3")).toHaveClass("flex-1");

    fireEvent.click(button);
    expect(await screen.findByRole("region", { name: "Редактор датасета" })).toBeInTheDocument();
    expect(await screen.findByText("cargo_kt_yj")).toBeInTheDocument();
    const active = screen.getByRole("button", { name: "Редактор датасета" });
    expect(active).toHaveAttribute("aria-pressed", "true");
    expect(active).toHaveClass("bg-brand");

    fireEvent.click(active);
    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Редактор датасета" })).toBeNull();
      expect(screen.getByRole("region", { name: "Мастер стабилизации дисперсии" })).toBeInTheDocument();
    });
  });

  it("CERT-T2: Preprocessing -- смена остановки закрывает режим редактора (Дисперсия → Пропуски)", async () => {
    renderPreprocessing();
    const leftAside = screen.getByRole("heading", { name: "Preprocessing", level: 2 }).closest("aside")!;
    fireEvent.click(within(leftAside).getByRole("button", { name: /^Стабилизация дисперсии/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Настроить трансформацию" }));
    fireEvent.click(await screen.findByRole("button", { name: "Редактор датасета" }));
    expect(await screen.findByRole("region", { name: "Редактор датасета" })).toBeInTheDocument();

    fireEvent.click(within(leftAside).getByRole("button", { name: /^Пропуски/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Исправить пропуски" }));
    expect(await screen.findByRole("button", { name: "Исправить вручную" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Редактор датасета" })).toBeNull();
  });

  it("CERT-T3 (байт-инвариант): Пропуски/Выбросы -- однокнопочный правый край «Исправить вручную» (3 ребёнка в строке заголовка)", async () => {
    renderPreprocessing();
    const leftAside = screen.getByRole("heading", { name: "Preprocessing", level: 2 }).closest("aside")!;

    fireEvent.click(await screen.findByRole("button", { name: "Исправить пропуски" }));
    expect(screen.getByRole("button", { name: "Исправить вручную" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Редактор датасета" })).toBeNull();
    expect(screen.getByRole("button", { name: "Исправить вручную" }).parentElement!.children).toHaveLength(3);

    fireEvent.click(within(leftAside).getByRole("button", { name: /^Выбросы/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Исправить выбросы" }));
    expect(screen.getByRole("button", { name: "Исправить вручную" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Редактор датасета" })).toBeNull();
    expect(screen.getByRole("button", { name: "Исправить вручную" }).parentElement!.children).toHaveLength(3);

    // Спектральный анализ -- без кнопки (остановка без новых колонок).
    fireEvent.click(within(leftAside).getByRole("button", { name: /^Спектральный/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Зафиксировать периоды" }));
    expect(screen.queryByRole("button", { name: "Редактор датасета" })).toBeNull();
  });

  it("CERT-T4: Validation «Уникальность» -- кнопка есть, своп контента, повторный клик возвращает мастер", async () => {
    renderValidation();
    const leftAside = screen.getByRole("heading", { name: "Data Quality", level: 2 }).closest("aside")!;
    fireEvent.click(within(leftAside).getByRole("button", { name: /^Уникальность/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Исправить уникальность" }));

    const button = await screen.findByRole("button", { name: "Редактор датасета" });
    fireEvent.click(button);
    expect(await screen.findByRole("region", { name: "Редактор датасета" })).toBeInTheDocument();
    expect(await screen.findByText("cargo_kt_yj")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Редактор датасета" }));
    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Редактор датасета" })).toBeNull();
    });
  });

  it("CERT-T5 (байт-инвариант): Validation «Типы данных» -- без кнопки, строка заголовка 2 ребёнка", async () => {
    renderValidation();
    fireEvent.click(await screen.findByRole("button", { name: "Исправить типы данных" }));
    expect(screen.queryByRole("button", { name: "Редактор датасета" })).toBeNull();
    const hMaster = screen.getByRole("heading", { name: "Мастер исправления типов", level: 3 });
    expect(hMaster.parentElement!.children).toHaveLength(2);
  });

  it("CERT-T6: Validation -- смена проверки закрывает режим редактора (Уникальность → Диапазоны)", async () => {
    renderValidation();
    const leftAside = screen.getByRole("heading", { name: "Data Quality", level: 2 }).closest("aside")!;
    fireEvent.click(within(leftAside).getByRole("button", { name: /^Уникальность/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Исправить уникальность" }));
    fireEvent.click(await screen.findByRole("button", { name: "Редактор датасета" }));
    expect(await screen.findByRole("region", { name: "Редактор датасета" })).toBeInTheDocument();

    fireEvent.click(within(leftAside).getByRole("button", { name: /^Диапазоны/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Исправить диапазоны значений" }));
    expect(await screen.findByRole("button", { name: "Редактор датасета" })).not.toHaveClass("bg-brand");
    expect(screen.queryByRole("region", { name: "Редактор датасета" })).toBeNull();
  });
});
