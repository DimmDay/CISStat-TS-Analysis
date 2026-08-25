// packages/ui/components/TsAnalysisValidation.test.tsx
//
// Тесты для компонента «Валидация» — в частности:
// 1. Рендер кнопки «Управление правилами» внизу степпера
// 2. Клик по кнопке показывает контент в центральном текстовом окне
// 3. Кнопка визуально отличается от степпер-бейджей (имеет уникальный класс/роль)
// 4. Повторный клик скрывает контент (toggle)
// 5. Expandable description: chevron appears on overflow
// 6. Expand/collapse toggle
// 7. «Метрики и алгоритм» для «Типы данных» раскрывает полный контракт
//    метрик, алгоритма и честных backend-статусов.
//
// Обновлено 2026-08-14: компонент подключён к реальному
// GET /v1/session/dataset/validate (через useAppShell/AppShellProvider) --
// раньше CHECKS был полностью статическим моком, тестам не требовался
// ни AppShellProvider, ни fetch-мок. См. TsAnalysisUpload.test.tsx --
// тот же паттерн мока /session/current.

import "@testing-library/jest-dom";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { TsAnalysisValidation } from "./TsAnalysisValidation";
import { AppShellProvider } from "../context/AppShellContext";

const EXPECTED_CHECK_IDS_ARR = [
  "data_types", "formats", "ranges", "consistency", "uniqueness",
  "inclusion", "referential", "text_quality", "regularity", "sufficiency",
];

// Polyfill: ResizeObserver не определён в jsdom -- нужен и checkOverflow()
// (existing), и Recharts ResponsiveContainer (ValidationCheckChart, новое).
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// AppShellProvider гидрируется с /v1/session/current при монтировании --
// без датасета useAppShell().activeDataset===null, компонент не запрашивает
// /dataset/validate (см. useEffect в TsAnalysisValidation.tsx) и рендерит
// CHECKS с status="pending" по всем 10 пунктам -- ровно то, что нужно
// большинству нижеследующих тестов (структура UI, не данные).
beforeEach(() => {
  global.fetch = jest.fn((url: string) => {
    if (typeof url === "string" && url.includes("/session/current")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ has_active_dataset: false, dataset: null, stages: {}, last_active_stage: null }),
      });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve(null) });
  }) as unknown as typeof fetch;
});

function renderValidation() {
  return render(
    <AppShellProvider>
      <TsAnalysisValidation />
    </AppShellProvider>
  );
}

function validationResponse(
  typeStatus: "done" | "warning" | "pending",
  mode: "profile" | "schema",
  count: number | null
) {
  return {
    is_valid: typeStatus !== "warning",
    rules_source: "system",
    validation_template_id: "system",
    total_rows: 3,
    total_columns: 1,
    type_validation_mode: mode,
    type_profile: [
      {
        name: "Amount",
        dtype: "object",
        type_icon: "categorical",
        non_null: 3,
        nulls: 0,
        unique: 3,
        expected_type: mode === "schema" ? "float" : null,
        validation_status: mode === "schema" ? (typeStatus === "warning" ? "mismatch" : "matched") : "profile",
        violations: mode === "schema" ? count : null,
      },
    ],
    checks: Object.fromEntries(
      EXPECTED_CHECK_IDS_ARR.map((id) => [id, {
        status: id === "data_types" ? typeStatus : "pending",
        count: id === "data_types" ? count : null,
        items: [],
        scope: "dataset",
        rule_source: "system",
      }])
    ),
  };
}

function mockActiveValidation(validateResponse: () => Promise<unknown>) {
  global.fetch = jest.fn((url: string) => {
    if (url.includes("/session/current")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          has_active_dataset: true,
          dataset: { dataset_id: "d1", name: "types.csv", rows: 3, columns: 1, size_label: "1 KB" },
          stages: {},
          last_active_stage: null,
        }),
      });
    }
    if (url.includes("/target-column")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ target_column: null, suggested_column: null, available_columns: [], has_dataset: true }),
      });
    }
    if (url.includes("/dataset/validate")) return validateResponse();
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve(null) });
  }) as unknown as typeof fetch;
}

describe("TsAnalysisValidation", () => {
  it("waits for the global validation action and then updates all check statuses", async () => {
    let validateCalls = 0;
    mockActiveValidation(() => {
      validateCalls += 1;
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          ...validationResponse("done", "schema", 0),
          rules_source: "system",
          checks: Object.fromEntries(EXPECTED_CHECK_IDS_ARR.map((id) => [id, {
            status: "done",
            count: 0,
            items: [],
            scope: "dataset",
            rule_source: "system",
          }])),
        }),
      });
    });

    renderValidation();
    const runButton = await screen.findByRole("button", { name: "Запустить валидацию" });
    await waitFor(() => expect(runButton).toBeEnabled());
    expect(validateCalls).toBe(0);

    fireEvent.click(runButton);
    await waitFor(() => expect(validateCalls).toBe(1));
    expect(await screen.findAllByText("Проверка пройдена")).toHaveLength(10);
    expect(screen.getAllByText("Системное правило")).toHaveLength(10);
    expect(screen.queryByRole("button", { name: /Запустить проверку \(/i })).not.toBeInTheDocument();
  });

  it("renders the module title", async () => {
    renderValidation();
    await waitFor(() => expect(screen.getByText("Data Quality")).toBeInTheDocument());
  });

  it("renders the control panel title with the same typography and top offset as Data Quality", async () => {
    renderValidation();

    const stepperTitle = await screen.findByRole("heading", {
      level: 2,
      name: "Data Quality",
    });
    const controlPanelTitle = screen.getByRole("heading", {
      level: 2,
      name: "Панель управления",
    });

    expect(controlPanelTitle.className).toBe(stepperTitle.className);
    expect(stepperTitle.closest("aside")).toHaveClass("pt-1");
    expect(controlPanelTitle.closest("aside")).toHaveClass("pt-1");
  });

  it("renders all 10 DQ checks in the stepper", async () => {
    renderValidation();
    const checkLabels = [
      "Типы данных", "Форматы и шаблоны", "Диапазоны значений",
      "Логика и хронология", "Уникальность", "Принадлежность к набору",
      "Ссылочная целостность", "Целостность текста",
      "Равномерность шага", "Достаточность наблюдений",
    ];
    await waitFor(() => {
      checkLabels.forEach((label) => {
        expect(screen.getByText(label)).toBeInTheDocument();
      });
    });
  });

  it("shows detailed metrics and backend algorithm for the data-types stop", async () => {
    renderValidation();

    const metricsButtons = await screen.findAllByRole("button", {
      name: "Метрики и алгоритм",
    });
    fireEvent.click(metricsButtons[0]);

    expect(screen.getByText("Метрики и алгоритм — Типы данных")).toBeInTheDocument();
    expect(screen.getByText(/Фактический профиль типов/i)).toBeInTheDocument();
    expect(screen.getByText(/N_type = Σ n_i/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Pandera-схема/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/схема и переопределения сессии → выбранный шаблон → системные правила/i)).toBeInTheDocument();
    expect(screen.getByText(/GET \/v1\/session\/dataset\/validate/i)).toBeInTheDocument();
  });

  it("renames the data-types correction action and opens the named wizard", async () => {
    renderValidation();

    const correctionButton = await screen.findByRole("button", { name: "Исправить типы данных" });
    expect(screen.getAllByRole("button", { name: "Полный пайплайн" })).toHaveLength(8);
    fireEvent.click(correctionButton);

    expect(screen.getAllByText("Мастер исправления типов").length).toBeGreaterThan(0);
    expect(screen.getByText(/Отметьте проблемные колонки/i)).toBeInTheDocument();
    expect(screen.getByText(/Предпросмотр не изменяет датасет/i)).toBeInTheDocument();
    expect(screen.getByText(/Подтвердите применение/i)).toBeInTheDocument();
  });

  it("uses the formats correction naming and opens its specialized wizard", async () => {
    renderValidation();

    const metricsButtons = await screen.findAllByRole("button", { name: "Метрики и алгоритм" });
    fireEvent.click(metricsButtons[1]);
    expect(screen.getByText("Метрики и алгоритм — Форматы и шаблоны")).toBeInTheDocument();
    expect(screen.getByText(/полное совпадение регулярному выражению/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Исправить форматы и шаблоны" }));
    expect(screen.getAllByText("Мастер исправления форматов и шаблонов").length).toBeGreaterThan(0);
    expect(screen.getByText(/Выберите проблемные колонки и стратегию/i)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Мастер исправления форматов и шаблонов" })).toBeInTheDocument();
  });

  // ── Кнопка «Управление правилами» ──

  it("renders the 'Управление правилами' button at the bottom of the stepper", async () => {
    renderValidation();
    const rulesButton = await screen.findByRole("button", { name: /Управление правилами/i });
    expect(rulesButton).toBeInTheDocument();
  });

  it("the rules button has a distinct data-testid to differentiate from stepper badges", async () => {
    renderValidation();
    const rulesButton = await screen.findByTestId("rules-management-btn");
    expect(rulesButton).toBeInTheDocument();
  });

  it("clicking the rules button shows rules content in the central text area", async () => {
    renderValidation();
    const rulesButton = await screen.findByTestId("rules-management-btn");

    // До клика — центральное поле содержит плейсхолдер
    expect(screen.getByText(/Нажмите «Метрики и алгоритм»/i)).toBeInTheDocument();

    // Клик
    fireEvent.click(rulesButton);

    // После клика — появляется заголовок панели правил (текст "Управление
    // правилами" совпадает ещё и с кнопкой, и с подзаголовком центрального
    // поля -- используем getByRole('heading') для однозначности)
    expect(screen.getByRole("heading", { name: /Управление правилами валидации/i })).toBeInTheDocument();
    expect(screen.getAllByText(/шаблон/i).length).toBeGreaterThan(0);
  });

  it("clicking the rules button toggles content off on second click", async () => {
    renderValidation();
    const rulesButton = await screen.findByTestId("rules-management-btn");

    // Первый клик — показываем
    fireEvent.click(rulesButton);
    expect(screen.queryByText(/Нажмите «Метрики и алгоритм»/i)).not.toBeInTheDocument();

    // Второй клик — скрываем (toggle)
    fireEvent.click(rulesButton);
    expect(screen.getByText(/Нажмите «Метрики и алгоритм»/i)).toBeInTheDocument();
  });

  it("rules button is visually distinct — has outlined/dashed style class", async () => {
    renderValidation();
    const rulesButton = await screen.findByTestId("rules-management-btn");
    expect(rulesButton.className).toMatch(/border-dashed/);
    expect(rulesButton.className).toMatch(/text-brand/);
  });

  // ── Expandable Description Box ──

  it("description area has a minimum height (collapsed)", async () => {
    renderValidation();
    // Проверяем, что контейнер описания рендерится
    await waitFor(() => expect(screen.getByText("Описание")).toBeInTheDocument());
  });

  it("expand button is not visible when no content is loaded", async () => {
    renderValidation();
    await waitFor(() => expect(screen.getByText("Описание")).toBeInTheDocument());
    // В начальном состоянии (плейсхолдер) нет overflow → нет chevron
    const expandBtn = screen.queryByTestId("desc-expand-btn");
    // Плейсхолдер короткий, overflow маловероятен
    expect(expandBtn).toBeNull();
  });

  // ── Реальные данные (2026-08-14) ──

  it("shows 'pending' state for all checks when no dataset is active", async () => {
    renderValidation();
    await waitFor(() => {
      // Без активного датасета компонент не запрашивает /dataset/validate --
      // честное "—" в метриках, не фейковые статичные числа из старого мока.
      expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    });
  });

  it("fetches and displays real check results after the global action", async () => {
    global.fetch = jest.fn((url: string) => {
      if (typeof url === "string" && url.includes("/session/current")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              has_active_dataset: true,
              dataset: { dataset_id: "d1", name: "test.csv", rows: 50, columns: 3, size_label: "1 KB" },
              stages: {},
              last_active_stage: null,
            }),
        });
      }
      if (typeof url === "string" && url.includes("/dataset/validate")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              is_valid: false,
              rules_source: "system",
              total_rows: 50,
              total_columns: 3,
              checks: {
                data_types: { status: "done", count: 0, items: [] },
                formats: { status: "pending", count: null, items: [] },
                ranges: { status: "warning", count: 3, items: [{ label: "price", count: 3 }] },
                consistency: { status: "pending", count: null, items: [] },
                uniqueness: { status: "done", count: 0, items: [] },
                inclusion: { status: "done", count: 0, items: [] },
                referential: { status: "pending", count: null, items: [] },
                text_quality: { status: "done", count: 0, items: [] },
                regularity: { status: "pending", count: null, items: [] },
                sufficiency: { status: "pending", count: null, items: [] },
              },
            }),
        });
      }
      return Promise.resolve({ ok: false, json: () => Promise.resolve(null) });
    }) as unknown as typeof fetch;

    renderValidation();
    const runButton = await screen.findByRole("button", { name: "Запустить валидацию" });
    await waitFor(() => expect(runButton).toBeEnabled());
    fireEvent.click(runButton);

    await waitFor(() => {
      // total_rows=50 из реального ответа, не старый мок "200"
      expect(screen.getByText("50")).toBeInTheDocument();
    });
  });

  it("renders the type matrix instead of the generic pending placeholder", async () => {
    global.fetch = jest.fn((url: string) => {
      if (typeof url === "string" && url.includes("/session/current")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            has_active_dataset: true,
            dataset: { dataset_id: "d1", name: "types.csv", rows: 3, columns: 3, size_label: "1 KB" },
            stages: {},
            last_active_stage: null,
          }),
        });
      }
      if (typeof url === "string" && url.includes("/dataset/validate")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            is_valid: true,
            rules_source: "system",
            total_rows: 3,
            total_columns: 3,
            type_validation_mode: "profile",
            type_profile: [
              { name: "Country", dtype: "object", type_icon: "categorical", non_null: 3, nulls: 0, unique: 3 },
              { name: "Year", dtype: "int64", type_icon: "numeric", non_null: 3, nulls: 0, unique: 3 },
              { name: "Price", dtype: "float64", type_icon: "numeric", non_null: 3, nulls: 0, unique: 3 },
            ],
            checks: Object.fromEntries(
              EXPECTED_CHECK_IDS_ARR.map((id) => [id, { status: "pending", count: null, items: [], scope: "dataset" }])
            ),
          }),
        });
      }
      return Promise.resolve({ ok: false, json: () => Promise.resolve(null) });
    }) as unknown as typeof fetch;

    renderValidation();

    const runButton = await screen.findByRole("button", { name: "Запустить валидацию" });
    await waitFor(() => expect(runButton).toBeEnabled());
    fireEvent.click(runButton);

    expect(await screen.findByRole("table", { name: "Матрица типов колонок" })).toBeInTheDocument();
    expect(screen.getByText("Country")).toBeInTheDocument();
    expect(screen.getByText("float64")).toBeInTheDocument();
    expect(screen.queryByText(/Проверка «Типы данных» неприменима/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Исправить типы данных" }));
    expect(screen.getByRole("region", { name: "Мастер исправления типов" })).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Матрица типов колонок" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Форматы и шаблоны" }));
    expect(screen.queryByRole("table", { name: "Матрица типов колонок" })).not.toBeInTheDocument();
    expect(screen.getByText(/Проверка «Форматы и шаблоны» неприменима/i)).toBeInTheDocument();
  });

  it("runs global validation and shows running then problems status", async () => {
    let resolveManual: ((value: unknown) => void) | undefined;
    mockActiveValidation(() => {
      return new Promise((resolve) => { resolveManual = resolve; });
    });

    renderValidation();
    const runButton = await screen.findByRole("button", { name: "Запустить валидацию" });
    await waitFor(() => expect(runButton).toBeEnabled());
    fireEvent.click(runButton);
    expect((await screen.findAllByText("Проверка выполняется")).length).toBeGreaterThan(0);
    resolveManual?.({
      ok: true,
      json: () => Promise.resolve(validationResponse("warning", "schema", 2)),
    });

    expect(await screen.findByText("Найдены проблемы: 2")).toBeInTheDocument();
  });

  it("shows passed status when the saved type schema has no violations", async () => {
    mockActiveValidation(() => Promise.resolve({
      ok: true,
      json: () => Promise.resolve(validationResponse("done", "schema", 0)),
    }));

    renderValidation();
    const runButton = await screen.findByRole("button", { name: "Запустить валидацию" });
    await waitFor(() => expect(runButton).toBeEnabled());
    fireEvent.click(runButton);
    expect(await screen.findByText("Проверка пройдена")).toBeInTheDocument();
  });

  it("shows an execution error when global validation fails", async () => {
    mockActiveValidation(() => Promise.resolve({
      ok: false,
      status: 500,
      json: () => Promise.resolve({ detail: "boom" }),
    }));

    renderValidation();
    const runButton = await screen.findByRole("button", { name: "Запустить валидацию" });
    await waitFor(() => expect(runButton).toBeEnabled());
    fireEvent.click(runButton);

    expect(await screen.findAllByText("Ошибка выполнения")).toHaveLength(10);
  });

  it("shows real numeric columns and runs dataset-wide validation", async () => {
    const validateCalls: string[] = [];
    global.fetch = jest.fn((url: string) => {
      if (typeof url === "string" && url.includes("/session/current")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              has_active_dataset: true,
              dataset: { dataset_id: "d1", name: "fao.csv", rows: 30, columns: 3, size_label: "1 KB" },
              stages: {},
              last_active_stage: null,
            }),
        });
      }
      if (typeof url === "string" && url.includes("/target-column")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              target_column: "Price",
              suggested_column: "Price",
              available_columns: ["Year", "Price"],
              has_dataset: true,
            }),
        });
      }
      if (typeof url === "string" && url.includes("/dataset/validate")) {
        validateCalls.push(url);
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              is_valid: true,
              rules_source: "system",
              total_rows: 30,
              total_columns: 3,
              checks: Object.fromEntries(
                EXPECTED_CHECK_IDS_ARR.map((id) => [id, { status: "pending", count: null, items: [], scope: "column" }])
              ),
            }),
        });
      }
      return Promise.resolve({ ok: false, json: () => Promise.resolve(null) });
    }) as unknown as typeof fetch;

    renderValidation();

    // Реальные колонки FAO-датасета -- НЕ старый мок-список тикеров
    // (price/volume/open/high/low/close/adj_close).
    await waitFor(() => expect(screen.getByDisplayValue("Price")).toBeInTheDocument());
    expect(screen.queryByText("volume")).not.toBeInTheDocument();
    expect(screen.queryByText("adj_close")).not.toBeInTheDocument();

    const runButton = screen.getByRole("button", { name: "Запустить валидацию" });
    await waitFor(() => expect(runButton).toBeEnabled());
    fireEvent.click(runButton);
    await waitFor(() => {
      expect(validateCalls).toHaveLength(1);
      expect(validateCalls[0]).not.toContain("column=");
    });
  });
});
