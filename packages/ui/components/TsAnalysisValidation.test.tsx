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
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
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

function mockActiveValidation(validateResponse: (url?: string) => Promise<unknown>) {
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
    if (url.includes("/dataset/range-profile")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ rule_source: "not_applicable", columns: [] }),
      });
    }
    if (url.includes("/dataset/consistency-profile")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ rule_source: "not_applicable", rules: [] }),
      });
    }
    if (url.includes("/dataset/inclusion-profile")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ rule_source: "not_applicable", columns: [] }),
      });
    }
    if (url.includes("/dataset/referential-profile")) return validateResponse(url);
    if (url.includes("/dataset/regularity-profile")) return validateResponse(url);
    if (url.includes("/dataset/sufficiency-profile")) return validateResponse(url);
    if (url.includes("/dataset/validate")) return validateResponse(url);
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
    expect(screen.getByRole("heading", { name: "Паспорт свойств ряда: Валидация" })).toBeInTheDocument();
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
    expect(screen.queryByRole("button", { name: "Полный пайплайн" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Настроить план анализа" })).toBeInTheDocument();
    fireEvent.click(correctionButton);

    expect(screen.getAllByText("Мастер исправления типов").length).toBeGreaterThan(0);
    expect(screen.getByText(/Отметьте проблемные колонки/i)).toBeInTheDocument();
    expect(screen.getByText(/Предпросмотр не изменяет датасет/i)).toBeInTheDocument();
    expect(screen.getByText(/Подтвердите применение/i)).toBeInTheDocument();
  });

  it("opens the specialized uniqueness metrics, overview and correction master", async () => {
    mockActiveValidation(() => Promise.resolve({
      ok: true,
      json: () => Promise.resolve({
        ...validationResponse("done", "schema", 0),
        checks: Object.fromEntries(EXPECTED_CHECK_IDS_ARR.map((id) => [id, {
          status: "done", count: 0, items: [], scope: "dataset", rule_source: "system",
        }])),
      }),
    }));
    renderValidation();
    const runButton = await screen.findByRole("button", { name: "Запустить валидацию" });
    await waitFor(() => expect(runButton).toBeEnabled());
    fireEvent.click(runButton);
    await screen.findAllByText("Проверка пройдена");

    const uniquenessStop = screen.getAllByRole("button", { name: /Уникальность/ })[0];
    fireEvent.click(uniquenessStop);
    fireEvent.click(screen.getAllByRole("button", { name: "Метрики и алгоритм" })[0]);
    expect(screen.getByText(/Duplicate groups/i)).toBeInTheDocument();
    expect(screen.getByText(/profile_uniqueness/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Исправить уникальность" }));
    expect(screen.getAllByText("Мастер исправления уникальности").length).toBeGreaterThan(0);
  });

  it("opens the specialized inclusion metrics and correction master", async () => {
    renderValidation();

    const inclusionStop = (await screen.findAllByRole("button", { name: /Принадлежность к набору/ }))[0];
    fireEvent.click(inclusionStop);
    fireEvent.click(screen.getAllByRole("button", { name: "Метрики и алгоритм" })[0]);
    expect(screen.getByText(/N_inclusion/i)).toBeInTheDocument();
    expect(screen.getByText(/profile_inclusion/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Исправить принадлежность к набору" }));
    expect(screen.getAllByText("Мастер исправления принадлежности к набору").length).toBeGreaterThan(0);
    expect(screen.getByRole("region", { name: "Мастер исправления принадлежности к набору" })).toBeInTheDocument();
  });

  it("opens the specialized text-quality metrics and correction master", async () => {
    renderValidation();

    const textStop = (await screen.findAllByRole("button", { name: /Целостность текста/ }))[0];
    fireEvent.click(textStop);
    fireEvent.click(screen.getAllByRole("button", { name: "Метрики и алгоритм" })[0]);
    expect(screen.getByText(/N_text/i)).toBeInTheDocument();
    expect(screen.getByText(/profile_text_quality/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Исправить целостность текста" }));
    expect(screen.getAllByText("Мастер исправления целостности текста").length).toBeGreaterThan(0);
    expect(screen.getByRole("region", { name: "Мастер исправления целостности текста" })).toBeInTheDocument();
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

  // ── Приглашение «Перейти к предобработке» (паттерн Загрузки) ──

  it("shows the 'Перейти к предобработке' invitation below 'Управление правилами' (Upload stepper pattern)", async () => {
    // Паттерн "Ведём исследователя за руку" (StepperNextModuleButton):
    // та же механика, что и на «Загрузке» -- кнопка-приглашение внизу
    // степпера, отделённая светло-серой полосой, со ссылкой на следующий
    // модуль пайплайна (Валидация -> Предобработка).
    renderValidation();
    const rulesButton = await screen.findByTestId("rules-management-btn");

    // 1. Кнопка-приглашение -- ссылка на /preprocessing.
    const invite = screen.getByRole("link", { name: /Перейти к предобработке/ });
    expect(invite).toHaveAttribute("href", "/preprocessing");

    // 2. Порядок DOM: строго НИЖЕ кнопки «Управление правилами».
    // eslint-disable-next-line no-bitwise
    expect(
      rulesButton.compareDocumentPosition(invite) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();

    // 3. Светло-серая полоса НАД кнопкой: border-t border-neutral-200
    //    на обёртке (контракт StepperNextModuleButton).
    const wrapper = invite.closest("div");
    expect(wrapper?.className).toContain("border-t");
    expect(wrapper?.className).toContain("border-neutral-200");

    // 4. Дизайн в точности по паттерну Загрузки: та же геометрия, что у
    //    кнопок степпера (rounded-md/border/px-3 py-2/text-sm), статичная
    //    пастельная заливка bg-brand-light/50, фирменный индиго и белый
    //    текст при наведении.
    expect(invite.className).toContain("rounded-md");
    expect(invite.className).toContain("border");
    expect(invite.className).toContain("bg-brand-light/50");
    expect(invite.className).toContain("hover:bg-brand");
    expect(invite.className).toContain("hover:border-brand");
    expect(invite.className).toContain("hover:text-white");
    expect(invite.className).toContain("px-3");
    expect(invite.className).toContain("py-2");
    expect(invite.className).toContain("text-sm");
  });


  it("the rules button has a distinct data-testid to differentiate from stepper badges", async () => {
    renderValidation();
    const rulesButton = await screen.findByTestId("rules-management-btn");
    expect(rulesButton).toBeInTheDocument();
  });

  it("clicking the rules button shows rules content in the central text area", async () => {
    renderValidation();
    const rulesButton = await screen.findByTestId("rules-management-btn");

    // До клика — центральное поле показывает метрики активной остановки
    // (инвариант автозагрузки «Метрики и алгоритм», 2026-09-15): placeholder
    // больше никогда не появляется.
    expect(screen.getByText("Метрики и алгоритм — Типы данных")).toBeInTheDocument();
    expect(screen.queryByText(/Нажмите «Метрики и алгоритм»/i)).not.toBeInTheDocument();

    // Клик
    fireEvent.click(rulesButton);

    // После клика — появляется заголовок панели правил (текст "Управление
    // правилами" совпадает ещё и с кнопкой, и с подзаголовком центрального
    // поля -- используем getByRole('heading') для однозначности)
    expect(screen.getByRole("heading", { name: /Управление правилами валидации/i })).toBeInTheDocument();
    expect(screen.getAllByText(/шаблон/i).length).toBeGreaterThan(0);
  });

  it("clicking the rules button toggles content off on second click (back to active stop metrics)", async () => {
    renderValidation();
    const rulesButton = await screen.findByTestId("rules-management-btn");

    // Первый клик — показываем панель правил
    fireEvent.click(rulesButton);
    expect(screen.queryByText(/Нажмите «Метрики и алгоритм»/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Метрики и алгоритм — Типы данных")).not.toBeInTheDocument();

    // Второй клик — скрываем (toggle): возврат к метрикам активной
    // остановки (инвариант автозагрузки), НЕ к placeholder.
    fireEvent.click(rulesButton);
    expect(screen.getByText("Метрики и алгоритм — Типы данных")).toBeInTheDocument();
    expect(screen.queryByText(/Нажмите «Метрики и алгоритм»/i)).not.toBeInTheDocument();
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
    // С инвариантом автозагрузки (2026-09-15) контент метрик активной
    // остановки показывается сразу; в jsdom нет layout (scrollHeight/
    // clientHeight = 0) -> overflow не детектируется -> chevron нет.
    const expandBtn = screen.queryByTestId("desc-expand-btn");
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

  it("explains an unconfigured formats check instead of generic not-applicable", async () => {
    mockActiveValidation(() => Promise.resolve({
      ok: true,
      json: () => Promise.resolve({
        ...validationResponse("done", "schema", 0),
        checks: Object.fromEntries(EXPECTED_CHECK_IDS_ARR.map((id) => [id, {
          status: id === "formats" ? "pending" : "done",
          count: id === "formats" ? null : 0,
          items: [],
          scope: id === "formats" ? "column" : "dataset",
          rule_source: id === "formats" ? "not_applicable" : "system",
        }])),
      }),
    }));

    renderValidation();
    const runButton = await screen.findByRole("button", { name: "Запустить валидацию" });
    await waitFor(() => expect(runButton).toBeEnabled());
    fireEvent.click(runButton);

    expect(await screen.findByText("Эталон форматов не задан")).toBeInTheDocument();
    expect(screen.getByText("Нет эталона")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Форматы и шаблоны/ }));
    expect(screen.getByText(/Задайте regex-правила в «Управлении правилами»/i)).toBeInTheDocument();
  });

  it("shows auto non-applicable and manually disabled checks as neutral states", async () => {
    mockActiveValidation(() => Promise.resolve({
      ok: true,
      json: () => Promise.resolve({
        ...validationResponse("done", "schema", 0),
        checks: Object.fromEntries(EXPECTED_CHECK_IDS_ARR.map((id) => [id, {
          status: id === "inclusion" || id === "referential" ? "skipped" : "done",
          count: 0,
          items: [],
          scope: "dataset",
          rule_source: "not_applicable",
          mode: id === "referential" ? "disabled" : "auto",
          status_reason: id === "referential" ? "disabled" : id === "inclusion" ? "not_required" : null,
        }])),
      }),
    }));

    renderValidation();
    const runButton = await screen.findByRole("button", { name: "Запустить валидацию" });
    await waitFor(() => expect(runButton).toBeEnabled());
    fireEvent.click(runButton);

    expect(await screen.findAllByText("Не требуется")).not.toHaveLength(0);
    expect(screen.getAllByText("Отключено")).not.toHaveLength(0);
    expect(screen.getByText("8/8")).toBeInTheDocument();
    expect(screen.getByText("1.00")).toBeInTheDocument();
  });

  it("changes a check mode from the control panel and reruns validation", async () => {
    let validateCalls = 0;
    global.fetch = jest.fn((url: string, options?: RequestInit) => {
      if (url.includes("/session/current")) return Promise.resolve({ ok: true, json: () => Promise.resolve({
        has_active_dataset: true,
        dataset: { dataset_id: "d1", name: "ohlcv.csv", rows: 3, columns: 6, size_label: "1 KB" },
        stages: {}, last_active_stage: null,
      }) });
      if (url.includes("/target-column")) return Promise.resolve({ ok: true, json: () => Promise.resolve({ target_column: null, suggested_column: null, available_columns: [], has_dataset: true }) });
      if (url.includes("/validation-check-modes")) {
        if (options?.method === "PUT") return Promise.resolve({ ok: true, json: () => Promise.resolve({ modes: { inclusion: "disabled" } }) });
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ modes: { inclusion: "auto" } }) });
      }
      if (url.includes("/dataset/validate")) {
        validateCalls += 1;
        return Promise.resolve({ ok: true, json: () => Promise.resolve(validationResponse("done", "schema", 0)) });
      }
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve(null) });
    }) as unknown as typeof fetch;

    renderValidation();
    const runButton = await screen.findByRole("button", { name: "Запустить валидацию" });
    await waitFor(() => expect(runButton).toBeEnabled());
    fireEvent.click(runButton);
    await waitFor(() => expect(validateCalls).toBe(1));
    // validateCalls increments before the response is committed to React state.
    // Wait for the completed render so changing the mode cannot race the first run.
    await waitFor(() => {
      expect(screen.getByText("1.00")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Запустить валидацию" })).toBeEnabled();
    });

    fireEvent.change(screen.getByRole("combobox", { name: "Режим проверки Принадлежность к набору" }), {
      target: { value: "disabled" },
    });
    await waitFor(() => expect(validateCalls).toBe(2));
    const putCall = (global.fetch as jest.Mock).mock.calls.find(
      (call: [string, RequestInit?]) => call[0].includes("/validation-check-modes") && call[1]?.method === "PUT"
    );
    expect(JSON.parse(putCall[1].body as string)).toEqual({ modes: { inclusion: "disabled" } });
  });

  it("uses the ranges status, overview and correction-master contract", async () => {
    mockActiveValidation(() => Promise.resolve({
      ok: true,
      json: () => Promise.resolve({
        ...validationResponse("done", "schema", 0),
        checks: Object.fromEntries(EXPECTED_CHECK_IDS_ARR.map((id) => [id, {
          status: id === "ranges" ? "pending" : "done",
          count: id === "ranges" ? null : 0,
          items: [],
          scope: id === "ranges" ? "column" : "dataset",
          rule_source: id === "ranges" ? "not_applicable" : "system",
        }])),
      }),
    }));

    renderValidation();
    const runButton = await screen.findByRole("button", { name: "Запустить валидацию" });
    await waitFor(() => expect(runButton).toBeEnabled());
    fireEvent.click(runButton);

    expect(await screen.findByText("Эталон диапазонов не задан")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Диапазоны значений/ }));
    // Точный текст: строка статуса в карточке панели управления. Regex
    // здесь более не годится (инвариант автозагрузки, 2026-09-15):
    // метрики «Диапазонов значений» сами документируют статус фразой
    // «Эталон диапазонов не задан» и тоже совпадали бы по подстроке.
    expect(await screen.findByText("Эталон диапазонов не задан")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Исправить диапазоны значений" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Исправить диапазоны значений" }));
    expect(screen.getAllByText("Мастер исправления диапазонов").length).toBeGreaterThan(0);
  });

  it("uses the consistency status, overview and correction-master contract", async () => {
    mockActiveValidation(() => Promise.resolve({
      ok: true,
      json: () => Promise.resolve({
        ...validationResponse("done", "schema", 0),
        checks: Object.fromEntries(EXPECTED_CHECK_IDS_ARR.map((id) => [id, {
          status: id === "consistency" ? "pending" : "done",
          count: id === "consistency" ? null : 0,
          items: [],
          scope: "dataset",
          rule_source: id === "consistency" ? "not_applicable" : "system",
        }])),
      }),
    }));

    renderValidation();
    const runButton = await screen.findByRole("button", { name: "Запустить валидацию" });
    await waitFor(() => expect(runButton).toBeEnabled());
    fireEvent.click(runButton);

    expect(await screen.findByText("Эталон логики и хронологии не задан")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Логика и хронология/ }));
    expect(await screen.findByText(/Эталон логики и хронологии не задан/i)).toBeInTheDocument();

    const metricsButtons = screen.getAllByRole("button", { name: "Метрики и алгоритм" });
    fireEvent.click(metricsButtons[0]);
    expect(screen.getByText(/N_logic/i)).toBeInTheDocument();
    expect(screen.getByText(/единый профилировщик правил/i)).toBeInTheDocument();

    const correction = screen.getByRole("button", { name: "Исправить логику и хронологию" });
    fireEvent.click(correction);
    expect(screen.getAllByText("Мастер исправления логики и хронологии").length).toBeGreaterThan(0);
    expect(screen.getByRole("region", { name: "Мастер исправления логики и хронологии" })).toBeInTheDocument();
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

    fireEvent.click(screen.getByRole("button", { name: /Форматы и шаблоны/ }));
    expect(screen.queryByRole("table", { name: "Матрица типов колонок" })).not.toBeInTheDocument();
    expect(screen.getByText(/Эталон форматов не задан\. Задайте regex-правила/i)).toBeInTheDocument();
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

  it("opens the referential overview and correction master", async () => {
    mockActiveValidation((url) => {
      if (url.includes("/referential-profile")) return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          rule_source: "session",
          rules: [{
            rule_index: 0, rule_name: "Код страны существует", child_column: "CountryCode",
            allowed_values: ["BY", "KZ"], reference_count: 2, applicable: true,
            applicability_message: null, total_count: 3, valid_count: 2, invalid_count: 1,
            invalid_pct: 33.33, invalid_values: [{ value: "XX", count: 1 }],
            default_value: "BY", default_valid: true,
            supported_actions: ["mode", "replace_null", "drop_rows", "replace_default", "flag"],
          }],
        }),
      });
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(validationResponse("warning", "schema", 1)),
      });
    });

    renderValidation();
    const runButton = await screen.findByRole("button", { name: "Запустить валидацию" });
    await waitFor(() => expect(runButton).toBeEnabled());
    fireEvent.click(runButton);
    await screen.findByText("Найдены проблемы: 1");

    fireEvent.click(screen.getByRole("button", { name: /Ссылочная целостность/ }));
    expect(await screen.findByRole("table", { name: "Матрица ссылочной целостности" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Исправить ссылочную целостность" }));
    expect(screen.getByRole("region", { name: "Мастер исправления ссылочной целостности" })).toBeInTheDocument();
  });

  it("opens the regularity overview and correction master", async () => {
    const regularityProfile = {
      rule_source: "system",
      profile: {
        applicable: true, applicability_message: null, date_column: "Date", entity_column: "Country",
        target_frequency: "D", detected_frequency: null, gap_threshold_multiplier: 1.5,
        is_sorted: true, sort_violations: 0, invalid_date_count: 0, duplicate_count: 0,
        gap_count: 1, missing_period_count: 1, total_violations: 1,
        groups: [{ group: "A", observations: 3, inferred_frequency: null, modal_interval: "1 days", gap_count: 1, missing_period_count: 1, duplicate_count: 0, sort_violations: 0, gap_examples: [] }],
        supported_actions: ["sort", "interpolate", "ffill", "bfill", "asfreq", "fictitious_zero", "flag"],
      },
    };
    mockActiveValidation((url) => {
      if (url.includes("/regularity-profile")) return Promise.resolve({ ok: true, json: () => Promise.resolve(regularityProfile) });
      return Promise.resolve({ ok: true, json: () => Promise.resolve(validationResponse("warning", "schema", 1)) });
    });

    renderValidation();
    const runButton = await screen.findByRole("button", { name: "Запустить валидацию" });
    await waitFor(() => expect(runButton).toBeEnabled());
    fireEvent.click(runButton);
    await screen.findByText("Найдены проблемы: 1");

    fireEvent.click(screen.getByRole("button", { name: /Равномерность шага/ }));
    expect(await screen.findByRole("table", { name: "Матрица равномерности временного шага" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Исправить равномерность шага" }));
    expect(screen.getByRole("region", { name: "Мастер исправления равномерности шага" })).toBeInTheDocument();
  });

  it("opens the sufficiency overview and analysis-plan master", async () => {
    const sufficiencyProfile = {
      rule_source: "system", plan: {},
      profile: {
        applicable: true, applicability_message: null, date_column: "Date", entity_column: "Country", target_column: "Value",
        frequency: "D", seasonal_period: 7, groups_total: 1, sufficient_groups: 0, insufficient_groups: 1, total_failed_checks: 2,
        thresholds: [], supported_actions: ["restrict_models", "flag_groups", "drop_groups"],
        groups: [{ group: "A", rows_total: 10, valid_observations: 10, invalid_target_count: 0, invalid_date_count: 0, unique_timestamps: 10, frequency: "D", seasonal_period: 7, seasonal_cycles: 1, failed_checks: 2, passed_checks: 4, checks: [], available_capabilities: ["Тренд"], unavailable_capabilities: ["ARIMA", "ML"] }],
      },
    };
    mockActiveValidation((url) => {
      if (url.includes("/sufficiency-profile")) return Promise.resolve({ ok: true, json: () => Promise.resolve(sufficiencyProfile) });
      return Promise.resolve({ ok: true, json: () => Promise.resolve(validationResponse("warning", "schema", 2)) });
    });

    renderValidation();
    const runButton = await screen.findByRole("button", { name: "Запустить валидацию" });
    await waitFor(() => expect(runButton).toBeEnabled());
    fireEvent.click(runButton);
    await screen.findByText("Найдены проблемы: 2");

    fireEvent.click(screen.getByRole("button", { name: /Достаточность наблюдений/ }));
    expect(await screen.findByRole("table", { name: "Матрица достаточности наблюдений" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Настроить план анализа" }));
    expect(screen.getByRole("region", { name: "Мастер решений по достаточности" })).toBeInTheDocument();
  });
});


// ── Зелёная подсветка пройденных остановок степпера (паттерн Моделирования) ──
//
// Паттерн перенесён с вкладки «Моделирование» (TsAnalysisModeling) и уже
// применён к «Разведочному EDA» (Task EDA-2) и «Предобработке»
// (Task PREPR-1): «Если остановка степпера пройдена и имеет зелёную
// галочку, то кнопка остановки окрашивается в светло-зелёный цвет и текст
// становится зелёным. При других статусах кнопка остановки не окрашивается
// и цвет текста не меняется». Контракт цветов -- ветка done в className
// кнопки степпера: bg-green-50 border-green-200 text-green-800; активная
// остановка (bg-brand text-white) сохраняет приоритет, как в эталоне.
//
// Особенность «Валидации»: зелёная галочка видна только через
// StatusIcon(displayedStatus(check)), а displayedStatus отображает "done"
// один-в-один, поэтому подсветка обязана идти строго по
// check.status === "done"; спец-бейджи («Отключено», «Настроить», «Нет
// эталона») и статусы warning/pending/skipped/error подсветки не получают.
//
// Механика тестов -- ТА ЖЕ, что у проходящих тестов выше (прямой
// global.fetch только для /session/current и /dataset/validate, остальные
// эндпоинты -- ok:false; ожидание СРАЗУ по DOM-сигналу завершения запуска).

function buildChecks(
  overrides: Record<string, { status: string; status_reason?: string | null; rule_source?: string }>,
) {
  return Object.fromEntries(
    EXPECTED_CHECK_IDS_ARR.map((id) => [id, {
      status: overrides[id]?.status ?? "pending",
      count: 0,
      items: [],
      scope: "dataset",
      rule_source: overrides[id]?.rule_source ?? "system",
      // status_reason включается в ответ ТОЛЬКО когда задан: форма объекта
      // байт-в-байт совпадает с ответами существующих проходящих тестов.
      ...(overrides[id]?.status_reason ? { status_reason: overrides[id].status_reason } : {}),
    }]),
  );
}

function renderValidationWithChecks(
  checks: Record<string, { status: string; status_reason?: string | null; rule_source?: string }>,
) {
  global.fetch = jest.fn((url: string) => {
    if (typeof url === "string" && url.includes("/session/current")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          has_active_dataset: true,
          dataset: { dataset_id: "d1", name: "types.csv", rows: 50, columns: 3, size_label: "1 KB" },
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
          total_rows: 50,
          total_columns: 3,
          type_validation_mode: "profile",
          type_profile: [],
          checks: buildChecks(checks),
        }),
      });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve(null) });
  }) as unknown as typeof fetch;

  return render(
    <AppShellProvider>
      <TsAnalysisValidation />
    </AppShellProvider>
  );
}

// ── Механика: только ПОДТВЁРДЕННАЯ в этом файле связка --
// mockActiveValidation (все служебные эндпоинты отвечают ok) + ожидание
// завершения запуска строго через findBy*/findAllBy* (asyncAct-промывка
// React 18 + RTL 16 + jest 30). Минимальный мок (ok:false на
// /target-column и profile-эндпоинтах) и waitFor-колбэки дают
// недетерминированную промывку рендера -- не использовать.

// Все 10 проверок done, КРОМЕ перечисленных pending-идентификаторов.
function allDoneExcept(pendingIds: string[]) {
  return Object.fromEntries(
    EXPECTED_CHECK_IDS_ARR
      .filter((id) => !pendingIds.includes(id))
      .map((id) => [id, { status: "done" }]),
  );
}

function mockValidationChecks(
  overrides: Record<string, { status: string; status_reason?: string | null; rule_source?: string }>,
  onCall?: () => void,
) {
  mockActiveValidation(() => {
    onCall?.();
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({
        ...validationResponse("done", "schema", 0),
        rules_source: "system",
        checks: buildChecks(overrides),
      }),
    });
  });
}

describe("TsAnalysisValidation — зелёная подсветка пройденных остановок степпера (паттерн Моделирования)", () => {
  it("colors a passed (done) stop light-green and keeps non-active pending stops uncolored", async () => {
    // 8 из 10 проверок -- done (зелёная галочка); «Достаточность
    // наблюдений» и «Уникальность» -- pending.
    let validateCalls = 0;
    mockValidationChecks(allDoneExcept(["sufficiency", "uniqueness"]), () => { validateCalls += 1; });
    renderValidation();
    const runButton = await screen.findByRole("button", { name: "Запустить валидацию" });
    await waitFor(() => expect(runButton).toBeEnabled());
    fireEvent.click(runButton);
    await waitFor(() => expect(validateCalls).toBe(1));
    expect((await screen.findAllByText("Проверка пройдена")).length).toBe(8);

    // Снимаем активность с дефолтной остановки «Типы данных» (done):
    // кликаем на «Достаточность наблюдений» (pending).
    fireEvent.click(screen.getByRole("button", { name: /^Достаточность наблюдений/ }));

    // Пройденная остановка (зелёная галочка) -> светло-зелёная кнопка
    // с зелёным текстом (эталон Моделирования: bg-green-50/green-200/green-800).
    const doneButton = screen.getByRole("button", { name: /^Типы данных/ });
    expect(doneButton).toHaveClass("bg-green-50", "border-green-200", "text-green-800");
    expect(doneButton).not.toHaveClass("bg-brand");
    expect(doneButton).not.toHaveClass("bg-white");

    // Не пройденная (pending) и не активная остановка -> БЕЗ окраски.
    const pendingButton = screen.getByRole("button", { name: /^Уникальность/ });
    expect(pendingButton).toHaveClass("bg-white", "border-neutral-200", "text-neutral-800");
    expect(pendingButton).not.toHaveClass("bg-green-50");
    expect(pendingButton).not.toHaveClass("border-green-200");
    expect(pendingButton).not.toHaveClass("text-green-800");
  });

  it("keeps the indigo active styling for an active stop even when it is done (active branch priority, as in Modeling)", async () => {
    // Все 10 проверок done; «Типы данных» остаётся активной по умолчанию
    // -> приоритет индиго (как в эталоне Моделирования).
    let validateCalls = 0;
    mockValidationChecks(allDoneExcept([]), () => { validateCalls += 1; });
    renderValidation();
    const runButton = await screen.findByRole("button", { name: "Запустить валидацию" });
    await waitFor(() => expect(runButton).toBeEnabled());
    expect(validateCalls).toBe(0);
    fireEvent.click(runButton);
    await waitFor(() => expect(validateCalls).toBe(1));
    expect(await screen.findAllByText("Проверка пройдена")).toHaveLength(10);

    const activeDoneButton = screen.getByRole("button", { name: /^Типы данных/ });
    expect(activeDoneButton).toHaveClass("bg-brand", "text-white", "border-brand");
    expect(activeDoneButton).not.toHaveClass("bg-green-50");
    expect(activeDoneButton).not.toHaveClass("text-green-800");
  });

  it("leaves the warning stop uncolored", async () => {
    // «Типы данных» -- warning (найдены проблемы), «Равномерность шага» --
    // done; подсветка обязана остаться только у done.
    mockValidationChecks({
      data_types: { status: "warning" },
      regularity: { status: "done" },
    });
    renderValidation();
    const runButton = await screen.findByRole("button", { name: "Запустить валидацию" });
    await waitFor(() => expect(runButton).toBeEnabled());
    fireEvent.click(runButton);
    expect((await screen.findAllByText(/^Найдены проблемы/)).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: /^Уникальность/ }));

    const warningButton = screen.getByRole("button", { name: /^Типы данных/ });
    expect(warningButton).toHaveClass("bg-white", "border-neutral-200", "text-neutral-800");
    expect(warningButton).not.toHaveClass("bg-green-50");
    expect(warningButton).not.toHaveClass("border-green-200");
    expect(warningButton).not.toHaveClass("text-green-800");
  });

  it("leaves the skipped stop ('Отключено' badge) uncolored", async () => {
    // «Достаточность наблюдений» -- skipped/disabled: бейдж «Отключено»
    // заменяет иконку; подсветки быть НЕ должно (паттерн красит только done).
    mockValidationChecks({
      sufficiency: { status: "skipped", status_reason: "disabled" },
    });
    renderValidation();
    const runButton = await screen.findByRole("button", { name: "Запустить валидацию" });
    await waitFor(() => expect(runButton).toBeEnabled());
    fireEvent.click(runButton);
    expect((await screen.findAllByText("Отключено")).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: /^Уникальность/ }));

    const skippedButton = screen.getByRole("button", { name: /^Достаточность наблюдений/ });
    expect(skippedButton).toHaveClass("bg-white", "border-neutral-200", "text-neutral-800");
    expect(skippedButton).not.toHaveClass("bg-green-50");
    expect(skippedButton).not.toHaveClass("border-green-200");
    expect(skippedButton).not.toHaveClass("text-green-800");
  });

  it("leaves the pending 'needs_rule' stop ('Настроить' badge) uncolored", async () => {
    // «Форматы и шаблоны» -- pending/needs_rule: бейдж «Настроить»
    // (displayedStatus отображает его в warning -- НЕ зелёная галочка).
    mockValidationChecks({
      formats: { status: "pending", status_reason: "needs_rule" },
    });
    renderValidation();
    const runButton = await screen.findByRole("button", { name: "Запустить валидацию" });
    await waitFor(() => expect(runButton).toBeEnabled());
    fireEvent.click(runButton);
    expect((await screen.findAllByText("Настроить")).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: /^Уникальность/ }));

    const needsRuleButton = screen.getByRole("button", { name: /^Форматы и шаблоны/ });
    expect(needsRuleButton).toHaveClass("bg-white", "border-neutral-200", "text-neutral-800");
    expect(needsRuleButton).not.toHaveClass("bg-green-50");
    expect(needsRuleButton).not.toHaveClass("border-green-200");
    expect(needsRuleButton).not.toHaveClass("text-green-800");
  });

});

// ─────────────────────────────────────────────────────────────────────────────
// Автозагрузка «Метрики и алгоритм» активной остановки в окно «Описание»
// (инвариант информативности, 2026-09-15).
//
// Постановка тимлида: при загрузке страницы степпер стоит на первой активной
// остановке «Типы данных», а в окне «Описание» — placeholder «Нажмите
// «Метрики и алгоритм»…». Принцип: активная остановка степпера АВТОМАТИЧЕСКИ
// загружает в «Описание» содержимое кнопки «Метрики и алгоритм» данной
// остановки (и делает кнопку активной). Вне зависимости от статуса остановки.
//
// Блокирующих зависимостей нет: контент метрик — статические константы
// (*_METRICS_DESCRIPTION) + статический CHECK_META; не зависит ни от
// GET /dataset/validate, ни от статуса, ни от наличия датасета. Кнопки
// рендерятся для всех 10 проверок безусловно.
//
// Инвариант покрывает ВСЕ пути возврата: загрузка страницы (initial state),
// клик по остановке степпера, закрытие Справки, закрытие Управления правилами.
// Явный пользовательский выбор («Исправить этап проверки»/pipeline) остаётся
// приоритетным, пока пользователь сам не вернётся к метрикам.
// ─────────────────────────────────────────────────────────────────────────────
describe("TsAnalysisValidation — автозагрузка «Метрики и алгоритм» активной остановки (инвариант информативности)", () => {
  it("auto-loads the active stop's metrics into the description box on page load (pending status, no dataset)", async () => {
    // Без датасета все проверки pending — инвариант действует вне зависимости
    // от статуса: «Описание» сразу показывает метрики «Типы данных».
    renderValidation();

    expect(await screen.findByText("Метрики и алгоритм — Типы данных")).toBeInTheDocument();
    expect(screen.getByText(/Фактический профиль типов/i)).toBeInTheDocument();
    // Placeholder больше никогда не появляется.
    expect(screen.queryByText(/Нажмите «Метрики и алгоритм»/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Выберите раздел в боковой панели")).not.toBeInTheDocument();

    // Кнопка «Метрики и алгоритм» активной остановки — в активном (индиго)
    // состоянии; кнопка соседней карточки — нет.
    const metricsButtons = screen.getAllByRole("button", { name: "Метрики и алгоритм" });
    expect(metricsButtons[0]).toHaveClass("bg-brand", "text-white");
    expect(metricsButtons[1]).not.toHaveClass("bg-brand");
    expect(metricsButtons[1]).toHaveClass("bg-brand-light");
  });

  it("auto-loads metrics when switching stops via the stepper (pending stop, no second click)", async () => {
    renderValidation();

    // Клик по другой остановке степпера («Уникальность», pending без датасета)
    fireEvent.click((await screen.findAllByRole("button", { name: /Уникальность/ }))[0]);

    // Метрики автозагрузились БЕЗ клика по кнопке «Метрики и алгоритм».
    expect(screen.getByText("Метрики и алгоритм — Уникальность")).toBeInTheDocument();
    expect(screen.getByText(/Duplicate groups/i)).toBeInTheDocument();
    expect(screen.queryByText(/Нажмите «Метрики и алгоритм»/i)).not.toBeInTheDocument();

    // Кнопка новой активной остановки активна (orderedChecks сортирует её
    // первой), кнопка прежней активной остановки — нет.
    const metricsButtons = screen.getAllByRole("button", { name: "Метрики и алгоритм" });
    expect(metricsButtons[0]).toHaveClass("bg-brand", "text-white");
    expect(metricsButtons[1]).not.toHaveClass("bg-brand");
  });

  it("auto-loads metrics for a done stop after validation has run (status-independence)", async () => {
    let validateCalls = 0;
    mockActiveValidation(() => {
      validateCalls += 1;
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          ...validationResponse("done", "schema", 0),
          checks: Object.fromEntries(EXPECTED_CHECK_IDS_ARR.map((id) => [id, {
            status: "done", count: 0, items: [], scope: "dataset", rule_source: "system",
          }])),
        }),
      });
    });
    renderValidation();
    const runButton = await screen.findByRole("button", { name: "Запустить валидацию" });
    await waitFor(() => expect(runButton).toBeEnabled());
    fireEvent.click(runButton);
    await waitFor(() => expect(validateCalls).toBe(1));
    expect((await screen.findAllByText("Проверка пройдена")).length).toBe(10);

    // Клик по пройденной (done) остановке — метрики автозагружаются
    // так же, как для pending: статус не влияет на инвариант.
    fireEvent.click(screen.getByRole("button", { name: /^Форматы и шаблоны/ }));

    expect(screen.getByText("Метрики и алгоритм — Форматы и шаблоны")).toBeInTheDocument();
    expect(screen.getByText(/полное совпадение регулярному выражению/i)).toBeInTheDocument();
    expect(screen.queryByText(/Нажмите «Метрики и алгоритм»/i)).not.toBeInTheDocument();
  });

  it("closing the Help toggle returns to the active stop's metrics (not the placeholder)", async () => {
    renderValidation();

    fireEvent.click(await screen.findByRole("button", { name: "Справка" }));
    expect(screen.getByText("Справка по стандартам качества данных")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Справка" }));
    expect(screen.getByText("Метрики и алгоритм — Типы данных")).toBeInTheDocument();
    expect(screen.queryByText(/Нажмите «Метрики и алгоритм»/i)).not.toBeInTheDocument();
  });

  it("closing the Rules management toggle returns to the active stop's metrics (not the placeholder)", async () => {
    renderValidation();
    const rulesButton = await screen.findByTestId("rules-management-btn");

    fireEvent.click(rulesButton);
    expect(screen.getByRole("heading", { name: /Управление правилами валидации/i })).toBeInTheDocument();

    fireEvent.click(rulesButton);
    expect(screen.getByText("Метрики и алгоритм — Типы данных")).toBeInTheDocument();
    expect(screen.queryByText(/Нажмите «Метрики и алгоритм»/i)).not.toBeInTheDocument();
  });

  it("explicit pipeline click still wins over the invariant until the user switches back", async () => {
    renderValidation();

    // Гард: автозагрузка не ломает явный пользовательский выбор мастера.
    fireEvent.click(await screen.findByRole("button", { name: "Исправить типы данных" }));
    expect(screen.getAllByText("Мастер исправления типов").length).toBeGreaterThan(0);
    expect(screen.queryByText("Метрики и алгоритм — Типы данных")).not.toBeInTheDocument();

    // Возврат к метрикам — явным кликом по кнопке «Метрики и алгоритм».
    fireEvent.click(screen.getAllByRole("button", { name: "Метрики и алгоритм" })[0]);
    expect(screen.getByText("Метрики и алгоритм — Типы данных")).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Task PREPR-4 (аудит PREPR-3-класса на других вкладках). Валидация —
// ЭТАЛОННАЯ реализация сквозной инвалидации: применения в пайплайнах и
// сохранение правил (onRulesApplied) перезапускают runValidation, а
// fetchValidation бампит validationVersion, который получает КАЖДЫЙ из
// 8 self-fetch Обзор-компонентов. Исходник-гарды прижимают контракт
// (прецедент гард-тестов исходника — ProductHeaderThemeToggle.test.tsx):
// мутант «убрать бамп validationVersion» или «подменить живой ключ
// константой» ловится здесь без длинной интеграционной кампании.
// ─────────────────────────────────────────────────────────────────────────────
describe("TsAnalysisValidation — живая инвалидация Обзоров (PREPR-4, эталон контракта)", () => {
  const SOURCE_PATH = resolve(process.cwd(), "packages/ui/components/TsAnalysisValidation.tsx");

  it("every check overview receives the live validationVersion (no frozen keys)", () => {
    const source = readFileSync(SOURCE_PATH, "utf8");
    // 8 Обзор-компонентов (data_types использует матрицу из общего стейта,
    // поэтому self-fetch Обзор-панелей ровно 8).
    const liveKeys = source.match(/refreshKey=\{validationVersion\}/g) ?? [];
    expect(liveKeys).toHaveLength(8);
    expect(source).not.toMatch(/refreshKey=\{\d+\}/);
  });

  it("global validation bumps the version once per run (invalidation source)", () => {
    const source = readFileSync(SOURCE_PATH, "utf8");
    // Бамп ровно один: в fetchValidation после успешного ответа.
    expect(source.match(/setValidationVersion\(\(current\) => current \+ 1\)/g)).toHaveLength(1);
  });

  it("correction masters and rules management rerun the global validation (onApplied/onRulesApplied)", () => {
    const source = readFileSync(SOURCE_PATH, "utf8");
    // 9 пайплайнов onApplied={runValidation} + 1 расширенный onApplied
    // (data_types) + onRulesApplied={runValidation}.
    expect(source.match(/onApplied=\{runValidation\}/g)).toHaveLength(9);
    expect(source).toContain("onRulesApplied={runValidation}");
  });
});
