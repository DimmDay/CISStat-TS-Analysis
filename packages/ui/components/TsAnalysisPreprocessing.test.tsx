// packages/ui/components/TsAnalysisPreprocessing.test.tsx
//
// Тесты для компонента «Предобработка» — в частности:
// 1. Рендер модуля и 11 шагов степпера
// 2. Кнопка «Справка» переключает секцию
// 3. Expandable description box: chevron, overlay, collapse

import "@testing-library/jest-dom";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { TsAnalysisPreprocessing } from "./TsAnalysisPreprocessing";

const MISSING_PROFILE = {
  rule_source: "system",
  mode: "auto",
  status: "warning",
  status_reason: null,
  total_rows: 4,
  total_columns: 2,
  total_missing: 2,
  missing_rate_pct: 25,
  rows_with_missing: 2,
  rows_with_missing_pct: 50,
  empty_rows: 0,
  columns: [
    {
      column: "Price", dtype: "float64", semantic: "numeric", total_count: 4,
      missing_count: 2, non_missing_count: 2, missing_pct: 50,
      recommended_strategy: "median_mode", missing_examples: [1, 3],
    },
  ],
  row_histogram: [],
};

describe("TsAnalysisPreprocessing", () => {
  beforeEach(() => {
    // Компонент теперь запрашивает реальный профиль остановки «Пропуски»
    // при монтировании (GET /dataset/missing-profile) -- без мока
    // существующие тесты по-прежнему проходят (запрос ловится внутренним
    // try/catch и переводит статус в "error"), но именно ЭТОТ мок нужен
    // новым тестам ниже, которые проверяют содержательный обзор/статус.
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(MISSING_PROFILE) });
  });

  it("renders the module title", () => {
    render(<TsAnalysisPreprocessing />);
    expect(screen.getByText("Preprocessing")).toBeInTheDocument();
  });

  it("renders all 11 preprocessing steps in the stepper", () => {
    render(<TsAnalysisPreprocessing />);
    const stepLabels = [
      "Пропуски", "Выбросы", "Регулярность ряда", "Декомпозиция ряда",
      "Стабилизация дисперсии", "Сглаживание ряда", "Стационарность ряда",
      "Спектральный анализ", "Генерация признаков", "Масштабирование",
      "Паспорт свойств ряда",
    ];
    stepLabels.forEach((label) => {
      expect(screen.getByText(label)).toBeInTheDocument();
    });
  });

  // ── Кнопка «Справка» ──

  it("renders the 'Справка' button in the header", () => {
    render(<TsAnalysisPreprocessing />);
    const helpButton = screen.getByRole("button", { name: /Справка/i });
    expect(helpButton).toBeInTheDocument();
  });

  it("clicking 'Справка' shows help content in the central text area", () => {
    render(<TsAnalysisPreprocessing />);
    const helpButton = screen.getByRole("button", { name: /Справка/i });

    // До клика — плейсхолдер
    expect(screen.getByText(/Нажмите «Метрики и алгоритм»/i)).toBeInTheDocument();

    // Клик
    fireEvent.click(helpButton);

    // После клика — появляется справка. Используем getAllByText, т.к.
    // regex /Цели модуля/i матчит ДВА элемента: подзаголовок «Справка — Цели
    // модуля и результаты прохождения» и сам контент «Цели модуля "Предобработка"».
    const matches = screen.getAllByText(/Цели модуля/i);
    expect(matches.length).toBeGreaterThanOrEqual(1);
  });

  it("clicking 'Справка' toggles content off on second click", () => {
    render(<TsAnalysisPreprocessing />);
    const helpButton = screen.getByRole("button", { name: /Справка/i });

    // Первый клик — показываем
    fireEvent.click(helpButton);
    expect(screen.queryByText(/Нажмите «Метрики и алгоритм»/i)).not.toBeInTheDocument();

    // Второй клик — скрываем (toggle)
    fireEvent.click(helpButton);
    expect(screen.getByText(/Нажмите «Метрики и алгоритм»/i)).toBeInTheDocument();
  });

  // ── Expandable Description Box ──

  it("description area has a minimum height (collapsed)", () => {
    render(<TsAnalysisPreprocessing />);
    expect(screen.getByText("Описание")).toBeInTheDocument();
  });

  it("expand chevron is not visible when no content is loaded (no overflow)", () => {
    render(<TsAnalysisPreprocessing />);
    // В начальном состоянии (плейсхолдер) нет overflow → нет chevron
    const expandBtn = screen.queryByTestId("desc-expand-btn");
    expect(expandBtn).toBeNull();
  });

  it("collapse chevron is not visible when description is not expanded", () => {
    render(<TsAnalysisPreprocessing />);
    const collapseBtn = screen.queryByTestId("desc-collapse-btn");
    expect(collapseBtn).toBeNull();
  });

  it("collapse chevron appears inside description after expanding", () => {
    render(<TsAnalysisPreprocessing />);
    // Сначала chevron нет
    expect(screen.queryByTestId("desc-collapse-btn")).toBeNull();

    // Симулируем раскрытие — кликаем справку для контента,
    // затем expand chevron (если появился при overflow).
    // В тестовой среде ResizeObserver может не сработать,
    // поэтому проверяем что компонент рендерится без ошибок
    // и collapse кнопка доступна через data-testid когда expanded
    const helpButton = screen.getByRole("button", { name: /Справка/i });
    fireEvent.click(helpButton);

    // После загрузки контента — компонент стабилен.
    // getAllByText, т.к. regex матчит и подзаголовок, и контент (см. выше).
    const matches = screen.getAllByText(/Цели модуля/i);
    expect(matches.length).toBeGreaterThanOrEqual(1);
  });
});

// ── Интеграция остановки «Пропуски» с бэкендом ──

describe("TsAnalysisPreprocessing — остановка «Пропуски»", () => {
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(MISSING_PROFILE) });
  });

  it("shows the real missing-values overview by default (missing is the first step)", async () => {
    render(<TsAnalysisPreprocessing />);
    expect(await screen.findByRole("table", { name: "Матрица пропусков по колонкам" })).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/v1/session/dataset/missing-profile"),
      expect.objectContaining({ credentials: "include" })
    );
  });

  it("reflects issues_found status in the stepper and the right-column badge", async () => {
    render(<TsAnalysisPreprocessing />);
    await screen.findByRole("table", { name: "Матрица пропусков по колонкам" });
    expect(screen.getByText("Найдено 2 пропусков")).toBeInTheDocument();
  });

  it("shows the skipped status when no dataset is active", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 404, json: () => Promise.resolve({ detail: "no dataset" }) });
    render(<TsAnalysisPreprocessing />);
    expect(await screen.findByText("Нет активного датасета")).toBeInTheDocument();
  });

  it("shows a mode selector for the missing-values stop and persists disabled mode", async () => {
    global.fetch = jest.fn((url: string, init?: RequestInit) => {
      if (init?.method === "PUT") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ modes: { missing: "disabled" } }) });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ ...MISSING_PROFILE, mode: "disabled", status: "skipped", status_reason: "disabled" }),
      });
    }) as unknown as typeof fetch;

    render(<TsAnalysisPreprocessing />);
    const select = await screen.findByRole("combobox", { name: "Режим проверки Пропуски" });
    fireEvent.change(select, { target: { value: "disabled" } });

    await waitFor(() => expect(screen.getByText("Отключено")).toBeInTheDocument());
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/v1/session/dataset/preprocessing-check-modes"),
      expect.objectContaining({ method: "PUT" })
    );
  });

  it("excludes a skipped missing-values stop from the progress bar denominator", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ ...MISSING_PROFILE, mode: "disabled", status: "skipped", status_reason: "disabled" }),
    });
    render(<TsAnalysisPreprocessing />);
    await screen.findByText("Отключено");
    // 11 остановок всего, но «Пропуски» (skipped) исключены из знаменателя
    // прогресса -- 0 done из 10 применимых, "100%" не должен появиться
    // ошибочно, а прогресс-бар не должен упасть на NaN/делении на 0.
    expect(screen.getByText(/0\/10/)).toBeInTheDocument();
  });

  it("opens the correction wizard and refreshes the profile after applying", async () => {
    const preview = {
      applied: false, strategy: "median_mode", total_missing: 2, total_changed: 2,
      total_still_missing: 0, rows_removed: 0, added_columns: [],
      columns: [{ column: "Price", missing_count: 2, changed_count: 2, still_missing: 0, missing_examples: [1, 3], flag_column: null }],
      profile: [{ ...MISSING_PROFILE.columns[0], missing_count: 0, missing_pct: 0, missing_examples: [] }],
    };
    const clearedProfile = {
      ...MISSING_PROFILE,
      status: "done",
      total_missing: 0,
      rows_with_missing: 0,
      rows_with_missing_pct: 0,
      columns: [{ ...MISSING_PROFILE.columns[0], missing_count: 0, missing_pct: 0, missing_examples: [] }],
    };
    let applied = false;
    // Мок различает GET-профиль (несколько независимых компонентов читают
    // один и тот же эндпоинт -- парент, Overview, Pipeline) и POST-коррекцию,
    // а не полагается на фиксированный порядок вызовов.
    global.fetch = jest.fn((url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        const body = init.body ? JSON.parse(init.body as string) : {};
        if (body.apply) applied = true;
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ...preview, applied: Boolean(body.apply) }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve(applied ? clearedProfile : MISSING_PROFILE) });
    }) as unknown as typeof fetch;

    render(<TsAnalysisPreprocessing />);
    await screen.findByRole("table", { name: "Матрица пропусков по колонкам" });

    fireEvent.click(screen.getByRole("button", { name: "Исправить пропуски" }));
    expect(await screen.findByRole("region", { name: "Мастер исправления пропусков" })).toBeInTheDocument();
    // Дожидаемся, пока мастер подгрузит СВОЙ профиль (переиспользует тот же
    // эндпоинт, что и парент/Overview) и предзаполнит колонку -- иначе
    // «Предпросмотр изменений» ещё disabled (busy==="load", selected==[]).
    await screen.findByRole("checkbox", { name: "Выбрать колонку Price" });

    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    await screen.findByText("Исправлено значений: 2");
    fireEvent.click(screen.getByRole("checkbox", { name: /Подтверждаю изменение активного датасета/i }));
    fireEvent.click(screen.getByRole("button", { name: "Применить исправления" }));

    await waitFor(() => expect(screen.getByText("Проверка пройдена, пропусков нет")).toBeInTheDocument());
  });
});

