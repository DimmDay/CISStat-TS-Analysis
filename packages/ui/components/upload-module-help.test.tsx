// packages/ui/components/upload-module-help.test.tsx
//
// Задача UI-UPLOAD-HELP-1 (2026-10-14, постановка тимлида): на вкладке
// «Загрузка» (/upload):
//
//   1) к заголовку колонки «Загрузка» добавлена кнопка «Справка» (паттерн
//      вкладки «Валидация»: toggle-кнопка в строке заголовка модуля, при
//      нажатии окно «Описание» показывает РАЗВЁРНУТОЕ описание модуля);
//   2) данные описания берутся из ЕДИНОГО источника методологий и
//      описаний платформы -- реестра справки packages/ui/lib/knowledge
//      (describeNode("upload", null, "module_help")); никаких строковых
//      констант в компоненте (единый источник -- реестр);
//   3) заголовок окна «Обзор» приведён к паттерну заголовков layout
//      данной страницы (задача UI-UPLOAD-HDR-1): строка flex items-center
//      gap-2 + lucide-иконка (size 16, text-brand, aria-hidden) +
//      text-lg font-semibold text-neutral-800.
//
// Поведенческие оракулы (структурные -- в upload-column-headers-unified
// .test.tsx, реестровые -- в lib/knowledge/help.test.ts). Оракулы
// построены на СВОИХ данных (дизъюнкт с TsAnalysisUpload.test.tsx и
// upload-column-headers-unified.test.tsx): свой файл help-toggle-check.csv,
// свои колонки day_ts/value_rub, свой dataset_id.
//
// Инвариант информативности (паттерн «Валидации»): переключение остановки
// при открытой Справке закрывает её и показывает описание НОВОЙ остановки;
// клик по УЖЕ активной остановке открытую Справку сохраняет.

import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { TsAnalysisUpload } from "./TsAnalysisUpload";
import { AppShellProvider } from "../context/AppShellContext";
import { describeNode } from "../lib/knowledge/knowledge";
// Тот же единый реестр остановок, что читает компонент (STOPS): описания
// остановок -- данные общего JSON, тест не дублирует строки.
import uploadStopsJson from "../../../shared/pipeline_nodes/upload_stops.json";

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn(), warning: jest.fn() },
}));

// Polyfill: ResizeObserver нужен Recharts ResponsiveContainer (тот же
// паттерн, что и в TsAnalysisUpload.test.tsx).
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// ── СВОЙ корпус данных (дизъюнкт с существующими тестами) ────────────

const helpUploadResponse = {
  dataset_id: "help-toggle-1",
  name: "help-toggle-check.csv",
  rows: 10,
  columns: 2,
  size_label: "0.01 MB",
  parse_warnings: [] as string[],
  preview: {
    head: [
      ["day_ts", "value_rub"],
      ["2026-02-01", "120"],
      ["2026-02-02", "135"],
    ],
    tail: [["2026-02-09", "128"], ["2026-02-10", "141"]],
  },
  columns_info: [
    { name: "day_ts", dtype: "object", type_icon: "datetime", non_null: 10, nulls: 0, unique: 10 },
    { name: "value_rub", dtype: "float64", type_icon: "numeric", non_null: 10, nulls: 0, unique: 10 },
  ],
  quality: {
    cols_with_missing: 0,
    cols_with_outliers: 0,
    rows_total: 10,
    duplicates: 0,
    missing_cols: [] as string[],
    outlier_cols: [] as string[],
  },
};

const helpStatsResponse = {
  columns: [
    {
      name: "value_rub",
      non_null_count: 10,
      stats: {
        mean: 130.5,
        median: 130,
        std: 7.5,
        skewness: 0.1,
        kurtosis: -0.8,
        q1: 125,
        q3: 136,
        iqr: 11,
        distribution_hint: "Близко к нормальному",
      },
    },
  ],
  min_non_null_for_stats: 2,
};

const helpDetection = {
  date_col: {
    selected: "day_ts",
    confidence: 92,
    candidates: [{ name: "day_ts", score: 0.92 }],
  },
  entity_col: {
    selected: "(нет)",
    confidence: 0,
    candidates: [{ name: "day_ts", score: 0.0 }],
  },
};

function mockHelpFetch() {
  global.fetch = jest.fn((url: string) => {
    if (typeof url === "string" && url.includes("/session/current")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            has_active_dataset: false,
            dataset: null,
            stages: {},
            last_active_stage: null,
            updated_at: null,
          }),
      });
    }
    if (typeof url === "string" && url.includes("/target-column")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            target_column: "value_rub",
            suggested_column: "value_rub",
            available_columns: ["value_rub"],
            has_dataset: true,
          }),
      });
    }
    if (typeof url === "string" && url.includes("/dataset/structure-detection")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(helpDetection) });
    }
    if (typeof url === "string" && url.includes("/dataset/stats")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(helpStatsResponse) });
    }
    if (typeof url === "string" && url.includes("/dataset/distribution")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            column: "value_rub",
            non_null_count: 10,
            min: 118,
            max: 145,
            scatter: Array.from({ length: 10 }, (_, i) => ({ x: i, y: 118 + i * 3 })),
            scatter_sampled: false,
            scatter_sampling_method: null,
            scatter_original_count: 10,
            histogram: [
              { x0: 118, x1: 131, count: 5 },
              { x0: 131, x1: 145, count: 5 },
            ],
            kde: Array.from({ length: 4 }, (_, i) => ({ x: 118 + i * 9, y: 0.02 * (i + 1) })),
          }),
      });
    }
    if (typeof url === "string" && url.includes("/dataset/timeseries")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            column: "value_rub",
            date_column: "day_ts",
            points: Array.from({ length: 10 }, (_, i) => ({
              x: `2026-02-${String(i + 1).padStart(2, "0")}`,
              y: 118 + i * 3,
            })),
            sampled: false,
            sampling_method: null,
            original_count: 10,
            was_resorted: false,
          }),
      });
    }
    if (typeof url === "string" && url.includes("/dataset/decomposition")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }
    if (typeof url === "string" && url.includes("/dataset/panel-balance")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ balanced: false, n_entities: 0, n_distinct_date_sets: 0 }),
      });
    }
    if (typeof url === "string" && url.includes("upload-stops")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ reported: 5, run_id: null }) });
    }
    if (typeof url === "string" && url.includes("/upload")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(helpUploadResponse) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  }) as jest.Mock;
}

// ── Хелперы рендера и контракта ──────────────────────────────────────

function dropHelpFile() {
  const file = new File(["day_ts,value_rub\n2026-02-01,120"], "help-toggle-check.csv", { type: "text/csv" });
  fireEvent.drop(screen.getByTestId("dropzone-input"), {
    dataTransfer: {
      files: [file],
      items: [{ kind: "file", type: file.type, getAsFile: () => file }],
      types: ["Files"],
    },
  });
}

async function renderUploaded() {
  mockHelpFetch();
  render(
    <AppShellProvider>
      <TsAnalysisUpload />
    </AppShellProvider>
  );
  dropHelpFile();
  await waitFor(() => {
    expect(screen.getByRole("heading", { name: "Загрузка", level: 2 })).toBeInTheDocument();
  });
}

function getHelpButton(): HTMLElement {
  const hUpload = screen.getByRole("heading", { name: "Загрузка", level: 2 });
  const row = hUpload.parentElement!;
  return within(row).getByRole("button", { name: "Справка" });
}

function stopDescription(stopId: string): string {
  const node = (uploadStopsJson.nodes as Array<{ id: string; description: string }>).find(
    (n) => n.id === stopId,
  );
  expect(node).toBeTruthy();
  return node!.description;
}

// testing-library (dom.esm.js: matches/fuzzyMatches) сравнивает
// нормализованный DOM-текст с СЫРЫМ строковым матчером (только lower-case,
// без collapseWhitespace) -- многострочный реестровый текст ("\n\n") точным
// строковым матчером не ловится. Реестровый текст сравниваем в
// нормализованной форме: рендер окна «Описание» сохраняет переводы строк
// через whitespace-pre-wrap (пинится отдельной проверкой), а байт-паритет
// самого текста реестра пинит help.test.ts против help-parity.fixture.json.
function normWs(s: string): string {
  return s.replace(/\s+/g, " ").trim();
}

function registryHelpTextNormalized(): string {
  const text = describeNode("upload", null, "module_help")?.text;
  // Единый источник наполнен: развёрнутое описание существует в реестре.
  expect(text).toBeTruthy();
  return normWs(text!);
}

// ── Оракулы ──────────────────────────────────────────────────────────

describe("Кнопка «Справка» колонки «Загрузка» -- описание модуля из единого реестра (паттерн «Валидации»)", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("кнопка «Справка» находится в строке заголовка колонки «Загрузка»; до нажатия -- неактивна (описание остановки)", async () => {
    await renderUploaded();

    const btn = getHelpButton();
    // Паттерн «Валидации»: неактивная кнопка -- светлая заливка бренда.
    expect(btn.className).toContain("bg-brand-light");

    // Дефолтное состояние окна «Описание» -- описание активной остановки.
    expect(screen.getByText(stopDescription("overview"))).toBeInTheDocument();
    // Режимный подзаголовок справки не показан.
    expect(screen.queryByText("Справка по модулю «Загрузка»")).not.toBeInTheDocument();
  });

  it("нажатие «Справки» показывает в окне «Описание» РОВНО реестровый текст describeNode('upload', null, 'module_help') + подзаголовок + pre-wrap", async () => {
    await renderUploaded();

    const registryText = registryHelpTextNormalized();

    fireEvent.click(getHelpButton());

    // В окне -- реестровый текст (single source), а не локальная копия.
    expect(screen.getByText(registryText)).toBeInTheDocument();
    expect(screen.getByText("Справка по модулю «Загрузка»")).toBeInTheDocument();

    // Паттерн «Валидации»: многострочный текст сохраняет переводы строк
    // (whitespace-pre-wrap) и длинный текст скроллится (overflow-y-auto).
    const helpBox = screen.getByText(registryText).closest("div")!;
    expect(helpBox.className).toContain("whitespace-pre-wrap");
    expect(helpBox.className).toContain("overflow-y-auto");

    // Активное состояние кнопки (паттерн «Валидации»).
    expect(getHelpButton().className).toContain("text-white");
  });

  it("повторное нажатие «Справки» (toggle) возвращает описание активной остановки -- не placeholder", async () => {
    await renderUploaded();

    const registryText = registryHelpTextNormalized();

    fireEvent.click(getHelpButton());
    expect(screen.getByText(registryText)).toBeInTheDocument();

    fireEvent.click(getHelpButton());
    expect(screen.queryByText(registryText)).not.toBeInTheDocument();
    expect(screen.getByText(stopDescription("overview"))).toBeInTheDocument();
    expect(screen.queryByText("Справка по модулю «Загрузка»")).not.toBeInTheDocument();
  });

  it("переключение остановки при открытой Справке закрывает её (описание НОВОЙ остановки); клик по той же остановке Справку сохраняет", async () => {
    await renderUploaded();
    const leftAside = screen.getByRole("heading", { name: "Загрузка", level: 2 }).closest("aside")!;

    const registryText = registryHelpTextNormalized();

    fireEvent.click(getHelpButton());
    expect(screen.getByText(registryText)).toBeInTheDocument();

    // Клик по УЖЕ активной остановке («Превью датасета») -- Справка остаётся
    // (инвариант информативности, паттерн «Валидации»).
    fireEvent.click(within(leftAside).getByRole("button", { name: /^Превью датасета/ }));
    expect(screen.getByText(registryText)).toBeInTheDocument();

    // Клик по ДРУГОЙ остановке -- Справка закрывается, показано описание
    // новой остановки.
    fireEvent.click(within(leftAside).getByRole("button", { name: /^График/ }));
    expect(screen.queryByText(registryText)).not.toBeInTheDocument();
    expect(screen.getByText(stopDescription("chart"))).toBeInTheDocument();
    expect(screen.queryByText("Справка по модулю «Загрузка»")).not.toBeInTheDocument();
  });
});

describe("Заголовок окна «Обзор» -- паттерн заголовков layout страницы (UI-UPLOAD-HDR-1)", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  // Контракт заголовков страницы: строка flex items-center gap-2 +
  // иконка (size 16, text-brand, aria-hidden) + text-lg font-semibold
  // neutral-800 (тот же, что у колонок «Загрузка»/«Описание»/«Файл»).
  function expectOverviewHeaderPattern(header: HTMLElement) {
    expect(header.className).toContain("text-lg");
    expect(header.className).toContain("font-semibold");
    expect(header.className).toContain("text-neutral-800");

    const row = header.parentElement!;
    expect(row.className).toContain("flex");
    expect(row.className).toContain("items-center");
    expect(row.className).toContain("gap-2");

    const icon = row.querySelector("svg");
    expect(icon).toBeTruthy();
    expect(icon).toHaveAttribute("aria-hidden", "true");
    expect(icon!.getAttribute("class")).toContain("text-brand");
  }

  it("дефолтная остановка: «Обзор: Превью датасета» -- text-lg, строка-паттерн с иконкой", async () => {
    await renderUploaded();
    const header = screen.getByRole("heading", { name: "Обзор: Превью датасета", level: 3 });
    expectOverviewHeaderPattern(header);
  });

  it("после переключения остановки заголовок следует за активной остановкой с тем же паттерном", async () => {
    await renderUploaded();
    const leftAside = screen.getByRole("heading", { name: "Загрузка", level: 2 }).closest("aside")!;

    fireEvent.click(within(leftAside).getByRole("button", { name: /^Качество/ }));
    const header = await screen.findByRole("heading", { name: "Обзор: Качество", level: 3 });
    expectOverviewHeaderPattern(header);
  });
});
