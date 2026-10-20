// packages/ui/components/upload-panel-transforms.test.tsx
//
// UPLOAD-RECOMP-2 (2026-10-20), пункт (в): панельные микросервисы на
// остановке «Структура» -- при структурном классе панели под карточкой
// класса появляется блок «Панельные данные: три пути исследования»:
//   1. «Фильтр сущности»     -- сведение панели к одному ряду одной
//      сущности (POST /dataset/entity-filter, preview/apply);
//   2. «Агрегация по времени»-- один агрегированный ряд по сущностям
//      (POST /dataset/panel-aggregate, mean/sum/median/min/max);
//   3. Бейдж «Ряд не трансформируем, исследуем панельные данные» --
//      пассивная альтернатива по умолчанию.
//
// После apply любого микросервиса -- re-detection контура модуля
// (класс становится одномерным рядом, блок исчезает), факты просмотров
// сбрасываются (transformEpoch -- новая вселенная, H27-безопасно).
//
// Поведенческие оракулы на СВОИХ данных (дизъюнкт с TsAnalysisUpload
// .test.tsx): файл panel-paths.csv, колонки dt/region/sales,
// dataset_id panel-paths-1, свой корпус preview/apply в моках.

import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { TsAnalysisUpload } from "./TsAnalysisUpload";
import { AppShellProvider } from "../context/AppShellContext";

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn(), warning: jest.fn() },
}));

global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

function dropFiles(input: Element, files: File[]) {
  fireEvent.drop(input, {
    dataTransfer: {
      files,
      items: files.map((file) => ({ kind: "file", type: file.type, getAsFile: () => file })),
      types: ["Files"],
    },
  });
}

// ── СВОЙ корпус: панель 2 сущности x 4 даты ─────────────────────────────

const panelUploadResponse = {
  dataset_id: "panel-paths-1",
  name: "panel-paths.csv",
  rows: 8,
  columns: 3,
  size_label: "0.01 MB",
  parse_warnings: [] as string[],
  preview: {
    head: [
      ["dt", "region", "sales"],
      ["2024-01-01", "north", "10"],
      ["2024-01-01", "south", "50"],
    ],
    tail: [["2024-01-04", "south", "53"]],
  },
  columns_info: [
    { name: "dt", dtype: "object", type_icon: "datetime", non_null: 8, nulls: 0, unique: 4 },
    { name: "region", dtype: "object", type_icon: "categorical", non_null: 8, nulls: 0, unique: 2 },
    { name: "sales", dtype: "int64", type_icon: "numeric", non_null: 8, nulls: 0, unique: 8 },
  ],
  quality: {
    cols_with_missing: 0,
    cols_with_outliers: 0,
    rows_total: 8,
    duplicates: 0,
    missing_cols: [],
    outlier_cols: [],
  },
};

const univariateUploadResponse = {
  ...panelUploadResponse,
  dataset_id: "panel-paths-1", // transformEpoch: тот же файл, новое содержимое
  rows: 4,
  columns: 2,
  columns_info: [
    { name: "dt", dtype: "object", type_icon: "datetime", non_null: 4, nulls: 0, unique: 4 },
    { name: "sales", dtype: "int64", type_icon: "numeric", non_null: 4, nulls: 0, unique: 4 },
  ],
};

const panelDetection = {
  date_col: {
    selected: "dt",
    confidence: 95,
    candidates: [{ name: "dt", score: 0.95 }],
  },
  entity_col: {
    selected: "region",
    confidence: 90,
    candidates: [{ name: "region", score: 0.9 }],
  },
};

const univariateDetection = {
  date_col: {
    selected: "dt",
    confidence: 95,
    candidates: [{ name: "dt", score: 0.95 }],
  },
  entity_col: {
    selected: "(нет)",
    confidence: 0,
    candidates: [{ name: "sales", score: 0.0 }],
  },
};

const entityFilterOptions = {
  applied: false,
  entity_col: "region",
  value: null,
  available_values: ["north", "south"],
  n_rows_before: 8,
  n_rows_after: null,
  n_dates: null,
  date_min: null,
  date_max: null,
  frequency: null,
};

const entityFilterPreviewNorth = {
  applied: false,
  entity_col: "region",
  value: "north",
  available_values: ["north", "south"],
  n_rows_before: 8,
  n_rows_after: 4,
  n_dates: 4,
  date_min: "2024-01-01",
  date_max: "2024-01-04",
  frequency: "D — ежедневная",
};

const entityFilterApplied = {
  applied: true,
  entity_col: "region",
  value: "north",
  available_values: ["north"],
  n_rows_before: 8,
  n_rows_after: 4,
  n_dates: 4,
  date_min: "2024-01-01",
  date_max: "2024-01-04",
  frequency: "D — ежедневная",
};

const aggPreview = {
  applied: false,
  date_col: "dt",
  func: "mean",
  n_rows_before: 8,
  n_rows_after: 4,
  n_dates: 4,
  n_dates_skipped: 0,
  dropped_columns: ["region"],
  numeric_columns: ["sales"],
  first_kept_columns: [],
};

const aggApplied = { ...aggPreview, applied: true };

const okStatsResponse = {
  columns: [
    {
      name: "sales",
      non_null_count: 4,
      stats: {
        mean: 30,
        median: 30,
        std: 1,
        skewness: 0,
        kurtosis: 0,
        q1: 29,
        q3: 31,
        iqr: 2,
        distribution_hint: "Близко к нормальному",
      },
    },
  ],
  min_non_null_for_stats: 2,
};

// ── Мок: детекция по последовательности (до/после re-detection) ─────────

function panelMock(detectionSequence: unknown[]) {
  let detectionCall = 0;
  const entityFilterBodies: unknown[] = [];
  const aggBodies: unknown[] = [];
  const dateColumnBodies: unknown[] = [];
  global.fetch = jest.fn((url: string, init?: RequestInit) => {
    if (typeof url === "string" && url.includes("/session/current")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ has_active_dataset: false, dataset: null, stages: {}, last_active_stage: null, updated_at: null }),
      });
    }
    if (typeof url === "string" && url.endsWith("/session/dataset")) {
      // Гидратация и ре-фетч превью после apply: dataset_id тот же --
      // transformEpoch изолирует факты; содержимое по очереди ответов.
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(detectionCall >= 2 ? univariateUploadResponse : panelUploadResponse),
      });
    }
    if (typeof url === "string" && url.includes("/dataset/structure-detection")) {
      const payload = detectionSequence[Math.min(detectionCall, detectionSequence.length - 1)];
      detectionCall += 1;
      return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
    }
    if (typeof url === "string" && url.includes("/dataset/entity-filter")) {
      const body = JSON.parse(String(init?.body ?? "{}"));
      entityFilterBodies.push(body);
      if (body.apply) return Promise.resolve({ ok: true, json: () => Promise.resolve(entityFilterApplied) });
      if (body.value) return Promise.resolve({ ok: true, json: () => Promise.resolve(entityFilterPreviewNorth) });
      return Promise.resolve({ ok: true, json: () => Promise.resolve(entityFilterOptions) });
    }
    if (typeof url === "string" && url.includes("/dataset/panel-aggregate")) {
      const body = JSON.parse(String(init?.body ?? "{}"));
      aggBodies.push(body);
      return Promise.resolve({ ok: true, json: () => Promise.resolve(body.apply ? aggApplied : aggPreview) });
    }
    if (typeof url === "string" && url.includes("/date-column")) {
      dateColumnBodies.push(JSON.parse(String(init?.body ?? "{}")));
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ date_column: "dt", has_dataset: true }) });
    }
    if (typeof url === "string" && url.includes("/dataset/stats")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(okStatsResponse) });
    }
    if (typeof url === "string" && url.includes("/dataset/distribution")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ column: "sales", non_null_count: 4, min: 10, max: 50, scatter: [], scatter_sampled: false, scatter_sampling_method: null, scatter_original_count: 4, histogram: [], kde: [] }) });
    }
    if (typeof url === "string" && url.includes("/dataset/panel-balance")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ balanced: true, n_entities: 2, n_distinct_date_sets: 1 }) });
    }
    if (typeof url === "string" && url.includes("/target-column")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ target_column: "sales", suggested_column: "sales", available_columns: ["sales"], has_dataset: true }),
      });
    }
    if (typeof url === "string" && url.includes("/dataset/rows")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ columns: ["dt", "region", "sales"], rows: [], offset: 0, limit: 200, total_rows: 8, returned: 0, has_more: false }),
      });
    }
    if (typeof url === "string" && url.includes("upload-stops")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ reported: 5, run_id: null }) });
    }
    if (typeof url === "string" && url.includes("/trace")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ nodes: [] }) });
    }
    if (typeof url === "string" && url.includes("/upload")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(panelUploadResponse) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  }) as jest.Mock;
  return { entityFilterBodies, aggBodies, dateColumnBodies };
}

async function renderPanelDataset(detectionSequence: unknown[] = [panelDetection, univariateDetection]) {
  const mocks = panelMock(detectionSequence);
  render(
    <AppShellProvider>
      <TsAnalysisUpload />
    </AppShellProvider>
  );
  dropFiles(screen.getByTestId("dropzone-input"), [new File(["a,b\n1,2"], "panel-paths.csv", { type: "text/csv" })]);
  await waitFor(() => expect(screen.getByText("Превью датасета")).toBeInTheDocument());
  fireEvent.click(screen.getByText("Структура"));
  await waitFor(() => expect(screen.getByText("Группирующая колонка")).toBeInTheDocument());
  return mocks;
}

describe("UPLOAD-RECOMP-2c: блок «Панельные данные: три пути исследования»", () => {
  it("панельный датасет -- блок с тремя альтернативами виден: фильтр сущности, агрегация по времени, бейдж", async () => {
    await renderPanelDataset();
    // Класс панели считается после panel-balance ответа.
    await waitFor(() => expect(screen.getByText("Panel Data — Balanced")).toBeInTheDocument());

    expect(screen.getByTestId("panel-paths-block")).toBeInTheDocument();
    expect(screen.getByText("Панельные данные: три пути исследования")).toBeInTheDocument();
    expect(screen.getByText("Фильтр сущности")).toBeInTheDocument();
    expect(screen.getByText("Агрегация по времени")).toBeInTheDocument();
    // Бейдж -- пассивная альтернатива по умолчанию, текст пинится.
    expect(screen.getByTestId("panel-badge")).toHaveTextContent("Ряд не трансформируем, исследуем панельные данные");
    // Подробные описания микросервисов (честность: платформа делает
    // преобразование внутри себя).
    expect(screen.getByText(/Оставить в датасете строки только одной сущности/)).toBeInTheDocument();
    expect(screen.getByText(/Для каждой даты усреднить/)).toBeInTheDocument();
  });

  it("непанельный датасет -- блок не показан (одномерный ряд в действиях не нуждается)", async () => {
    await renderPanelDataset([univariateDetection, univariateDetection]);
    await waitFor(() => expect(screen.getAllByText("Univariate TS").length).toBeGreaterThan(0));
    expect(screen.queryByTestId("panel-paths-block")).not.toBeInTheDocument();
  });
});

describe("UPLOAD-RECOMP-2c: микросервис «Фильтр сущности»", () => {
  it("селектор заполнен значениями entity-колонки с бэкенда (preview без value)", async () => {
    const { entityFilterBodies } = await renderPanelDataset();

    await waitFor(() => expect(screen.getByTestId("panel-entity-select")).toBeInTheDocument());
    // Первый запрос -- опрос доступных значений: value=null, apply=false.
    const optionsCall = entityFilterBodies.find((b) => (b as { value?: string | null }).value == null);
    expect(optionsCall).toMatchObject({ entity_col: "region", value: null, apply: false });
    // Значения селектора -- из ответа бэкенда.
    expect(withinSelect(screen.getByTestId("panel-entity-select"))).toEqual(
      expect.arrayContaining(["north", "south"]),
    );
  });

  it("выбор сущности -- preview результата; «Применить» -- apply:true, re-detection, блок исчезает, класс Univariate TS", async () => {
    const { entityFilterBodies } = await renderPanelDataset();

    const select = await waitFor(() => screen.getByTestId("panel-entity-select"));
    fireEvent.change(select, { target: { value: "north" } });

    // Preview по выбранной сущности.
    await waitFor(() => expect(screen.getByTestId("panel-entity-preview")).toHaveTextContent("4"));
    const previewCall = entityFilterBodies.find((b) => (b as { value?: string | null }).value === "north" && !(b as { apply?: boolean }).apply);
    expect(previewCall).toMatchObject({ entity_col: "region", value: "north", apply: false });

    // Кнопка «Применить» активна после выбора значения.
    const applyButton = screen.getByTestId("panel-entity-apply");
    expect(applyButton).not.toBeDisabled();
    fireEvent.click(applyButton);

    const applyCall = entityFilterBodies.find((b) => (b as { apply?: boolean }).apply === true);
    expect(applyCall).toMatchObject({ entity_col: "region", value: "north", apply: true });

    // Re-detection: класс становится одномерным рядом, блок исчезает.
    await waitFor(() => expect(screen.getAllByText("Univariate TS").length).toBeGreaterThan(0));
    expect(screen.queryByTestId("panel-paths-block")).not.toBeInTheDocument();
  });

  it("без выбранного значения «Применить» заблокирован (честное состояние)", async () => {
    await renderPanelDataset();
    const applyButton = await waitFor(() => screen.getByTestId("panel-entity-apply"));
    expect(applyButton).toBeDisabled();
  });
});

describe("UPLOAD-RECOMP-2c: микросервис «Агрегация по времени»", () => {
  it("функция агрегации и «Применить»: preview автоматически, apply:true с func, re-detection, бейдж исчезает", async () => {
    const { aggBodies } = await renderPanelDataset();

    const select = await waitFor(() => screen.getByTestId("panel-agg-select"));
    // Функция агрегации доступна (mean по умолчанию), смена -- sum.
    fireEvent.change(select, { target: { value: "sum" } });

    await waitFor(() => expect(screen.getByTestId("panel-agg-preview")).toBeInTheDocument());
    // Последний preview-запрос -- уже с выбранной функцией sum (первый
    // был автоматический mean на монтировании блока).
    const previewCalls = aggBodies.filter((b) => (b as { apply?: boolean }).apply === false);
    expect(previewCalls[previewCalls.length - 1]).toMatchObject({ date_col: "dt", func: "sum", apply: false });

    const applyButton = screen.getByTestId("panel-agg-apply");
    await waitFor(() => expect(applyButton).not.toBeDisabled());
    fireEvent.click(applyButton);

    const applyCall = aggBodies.find((b) => (b as { apply?: boolean }).apply === true);
    expect(applyCall).toMatchObject({ date_col: "dt", func: "sum", apply: true });

    await waitFor(() => expect(screen.getAllByText("Univariate TS").length).toBeGreaterThan(0));
    expect(screen.queryByTestId("panel-paths-block")).not.toBeInTheDocument();
  });
});

describe("UPLOAD-RECOMP-2c: transformEpoch -- новая вселенная фактов после apply", () => {
  it("после apply просмотры остановок сбрасываются (Качество снова pending), структура ждёт подтверждения заново", async () => {
    await renderPanelDataset();

    // Просмотрели «Качество» до преобразования.
    fireEvent.click(screen.getByRole("button", { name: /^Качество/ }));
    fireEvent.click(screen.getByRole("button", { name: /^Структура/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /^Качество/ })).toHaveClass("bg-green-50"));

    // Применяем фильтр сущности.
    const select = await waitFor(() => screen.getByTestId("panel-entity-select"));
    fireEvent.change(select, { target: { value: "north" } });
    const applyButton = await waitFor(() => screen.getByTestId("panel-entity-apply"));
    await waitFor(() => expect(applyButton).not.toBeDisabled());
    fireEvent.click(applyButton);
    await waitFor(() => expect(screen.getAllByText("Univariate TS").length).toBeGreaterThan(0));

    // Новая вселенная: прежний просмотр не переживает преобразование.
    await waitFor(() => expect(screen.getByRole("button", { name: /^Качество/ })).toHaveClass("bg-white"));
    // Структура после re-detection -- не зелёная (ждёт нового подтверждения).
    expect(screen.getByRole("button", { name: /^Структура/ })).not.toHaveClass("bg-green-50");
  });
});

// Вспомогательная функция чтения опций селектора (тест-гард заполнения).
function withinSelect(select: HTMLElement): string[] {
  return Array.from(select.querySelectorAll("option")).map((o) => o.value).filter(Boolean);
}
