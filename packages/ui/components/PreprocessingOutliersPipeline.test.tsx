import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { PreprocessingOutliersPipeline } from "./PreprocessingOutliersPipeline";

const PROFILE = {
  rule_source: "system", mode: "auto", status: "warning", status_reason: null, method: "iqr",
  total_rows: 21, total_numeric_columns: 1, total_outliers: 1, outlier_rate_pct: 4.76,
  affected_columns: ["Price"],
  columns: [{
    column: "Price", sample_size: 21, outlier_count: 1, outlier_pct: 4.76,
    recommended_method: "iqr", bounds: { lower: -5, upper: 25 },
    outlier_examples: [20], insufficient_sample: false,
  }],
};

const ALL_COLUMNS = { columns: [{ column: "Price" }, { column: "Date" }] };

const PREVIEW = {
  applied: false, strategy: "cap", method: "iqr", used_residual: false,
  total_outliers: 1, total_changed: 1, total_still_outliers: 0,
  rows_removed: 0, added_columns: [],
  status: "done", total_outliers_after: 0,
  columns: [{
    column: "Price", outlier_count: 1, changed_count: 1, still_outliers: 0, outlier_examples: [20], flag_column: null,
    stats_before: { mean: 57, median: 10, std: 216.3 },
    stats_after: { mean: 11, median: 10, std: 3.4 },
  }],
  profile: [{ ...PROFILE.columns[0], outlier_count: 0, outlier_pct: 0, outlier_examples: [] }],
};

function mockFetchSequence(...responses: unknown[]) {
  const queue = [...responses];
  global.fetch = jest.fn(() => {
    const next = queue.shift() ?? responses[responses.length - 1];
    return Promise.resolve({ ok: true, json: () => Promise.resolve(next) });
  }) as unknown as typeof fetch;
}

describe("PreprocessingOutliersPipeline", () => {
  beforeEach(() => {
    mockFetchSequence(PROFILE, ALL_COLUMNS);
  });

  it("renders the five-step correction flow with columns pre-selected", async () => {
    render(<PreprocessingOutliersPipeline onApplied={jest.fn()} />);

    expect(screen.getByRole("region", { name: "Мастер исправления выбросов" })).toBeInTheDocument();
    expect(await screen.findByRole("checkbox", { name: "Выбрать колонку Price" })).toBeChecked();
    expect(screen.getByText("2. Метод обнаружения")).toBeInTheDocument();
    expect(screen.getByText("3. Стратегия исправления")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Modified Z-score (MAD)" })).toBeInTheDocument();
  });

  it("enables the residual toggle only when exactly one column is selected", async () => {
    render(<PreprocessingOutliersPipeline onApplied={jest.fn()} />);
    await screen.findByText("Price"); // дожидаемся, пока профиль и allColumns осядут (оба setState в одном тике)
    const toggle = screen.getByRole("checkbox", { name: "Обнаруживать на остатке после STL-декомпозиции" });
    await waitFor(() => expect(toggle).not.toBeDisabled());

    fireEvent.click(toggle);
    expect(await screen.findByRole("combobox", { name: "Колонка с датой для декомпозиции" })).toBeInTheDocument();
  });

  it("previews and applies only after confirmation", async () => {
    // PROGR-6: после preview фоном идёт POST /v1/progress/mentor/sanity-check
    mockFetchSequence(PROFILE, ALL_COLUMNS, PREVIEW, { warnings: [] }, { ...PREVIEW, applied: true });
    const onApplied = jest.fn();
    render(<PreprocessingOutliersPipeline onApplied={onApplied} />);

    await screen.findByText("Price");
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    expect(await screen.findByText("Найдено выбросов: 1")).toBeInTheDocument();

    const apply = screen.getByRole("button", { name: "Применить исправления" });
    expect(apply).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /Подтверждаю изменение активного датасета/i }));
    fireEvent.click(apply);
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
  });

  it("shows a positive terminal state when there are no outliers", async () => {
    mockFetchSequence({ ...PROFILE, total_outliers: 0, columns: [{ ...PROFILE.columns[0], outlier_count: 0 }] }, ALL_COLUMNS);
    render(<PreprocessingOutliersPipeline onApplied={jest.fn()} />);
    expect(await screen.findByText(/Выбросов в датасете не найдено/)).toBeInTheDocument();
  });

  it("shows the before/after impact forecast in the preview step", async () => {
    mockFetchSequence(PROFILE, ALL_COLUMNS, PREVIEW, { warnings: [] });
    render(<PreprocessingOutliersPipeline onApplied={jest.fn()} />);

    await screen.findByText("Price");
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));

    expect(await screen.findByText("Прогноз влияния на статистики")).toBeInTheDocument();
    expect(screen.getByText("10 → 10")).toBeInTheDocument(); // медиана не меняется
    expect(screen.getByText(/216,3 → 3,4/)).toBeInTheDocument(); // std резко падает
  });
});

// ── PROGR-6 (§7.2): sanity-предупреждения Наставника в Мастере ────────

describe("PreprocessingOutliersPipeline + Наставник (PROGR-6)", () => {
  beforeEach(() => {
    // Свежий fetch на каждый тест -- иначе mock.calls копятся между тестами.
    mockFetchSequence(PROFILE, ALL_COLUMNS);
  });

  function sanityCalls(): unknown[][] {
    return (global.fetch as unknown as jest.Mock).mock.calls.filter((call: unknown[]) =>
      String(call[0]).includes("/v1/progress/mentor/sanity-check"),
    );
  }

  it("после preview отправляет CorrectionOutcomeSummary с method и «худшей» колонкой статистик", async () => {
    mockFetchSequence(PROFILE, ALL_COLUMNS, PREVIEW, { warnings: [] });
    render(<PreprocessingOutliersPipeline onApplied={jest.fn()} />);

    await screen.findByText("Price");
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    await waitFor(() => expect(sanityCalls()).toHaveLength(1));

    const [url, init] = sanityCalls()[0] as [string, RequestInit];
    expect(url).toContain("/v1/progress/mentor/sanity-check");
    expect(JSON.parse(String(init.body))).toEqual({
      stage: "preprocessing",
      node_id: "outliers",
      strategy: "cap",
      method: "iqr",
      affected_count_before: 1,
      changed_count: 1,
      still_affected_count: 0,
      rows_before: 21, // PROFILE.total_rows
      rows_after: 21, // 21 - rows_removed(0)
      stats_before: { mean: 57, median: 10, std: 216.3 },
      stats_after: { mean: 11, median: 10, std: 3.4 },
    });
  });

  it("предупреждение рендерится НАД кнопкой применения и НЕ блокирует её (§12 п.8)", async () => {
    mockFetchSequence(
      PROFILE,
      ALL_COLUMNS,
      PREVIEW,
      {
        warnings: [
          {
            rule_id: "over_aggressive",
            severity: "warning",
            message: "После исправления стандартное отклонение упало более чем в 5 раз.",
            suggested_action: null,
          },
        ],
      },
    );
    render(<PreprocessingOutliersPipeline onApplied={jest.fn()} />);

    await screen.findByText("Price");
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    expect(
      await screen.findByText("После исправления стандартное отклонение упало более чем в 5 раз."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /Подтверждаю изменение активного датасета/i }));
    expect(screen.getByRole("button", { name: "Применить исправления" })).toBeEnabled();
  });
});

// ── G345-фикс (PROGR-23): честный баннер мастера (Г4) ─────────────────

describe("PreprocessingOutliersPipeline + честный баннер (G345-фикс)", () => {
  beforeEach(() => {
    mockFetchSequence(PROFILE, ALL_COLUMNS);
  });

  async function applyCorrection(applyResponse: Record<string, unknown>) {
    mockFetchSequence(PROFILE, ALL_COLUMNS, PREVIEW, { warnings: [] }, applyResponse);
    const onApplied = jest.fn();
    render(<PreprocessingOutliersPipeline onApplied={onApplied} />);
    await screen.findByText("Price");
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    await screen.findByText("Найдено выбросов: 1");
    fireEvent.click(screen.getByRole("checkbox", { name: /Подтверждаю изменение активного датасета/i }));
    fireEvent.click(screen.getByRole("button", { name: "Применить исправления" }));
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
  }

  it("полная коррекция: зелёный баннер с числом изменённых значений", async () => {
    await applyCorrection({
      ...PREVIEW,
      applied: true,
      total_changed: 1,
      total_still_outliers: 0,
      status: "done",
      total_outliers_after: 0,
    });
    // роль "status" у мастера не одна (зелёный бокс «выбросов нет») --
    // баннер ищем по тексту, классы проверяем на нём же.
    const banner = await screen.findByText(/Изменено значений: 1/);
    expect(banner).toHaveClass("bg-green-50");
  });

  it("класс C5 (ничего не исправлено, карточка жёлтая): янтарный баннер с фактами, а не «профиль пересчитан»", async () => {
    await applyCorrection({
      ...PREVIEW,
      applied: true,
      total_outliers: 0,
      total_changed: 0,
      total_still_outliers: 0,
      status: "warning",
      total_outliers_after: 4,
    });
    const banner = await screen.findByText(/Изменений нет: выбранные колонки не содержат выбросов методом мастера/);
    expect(banner).toHaveTextContent("в датасете остались выбросы по профилю карточки: 4");
    expect(banner).toHaveClass("bg-amber-50");
  });

  it("частичная коррекция (still>0): баннер называет остаток по методу мастера", async () => {
    await applyCorrection({
      ...PREVIEW,
      applied: true,
      total_changed: 4,
      total_still_outliers: 4,
      status: "warning",
      total_outliers_after: 4,
    });
    const banner = await screen.findByText(/Изменено значений: 4/);
    expect(banner).toHaveTextContent("по методу мастера осталось выбросов: 4");
    expect(banner).toHaveTextContent("в датасете остались выбросы по профилю карточки: 4");
    expect(banner).toHaveClass("bg-amber-50");
  });

  it("стратегия flag: значения не изменены, но добавлены флаг-колонки -- баннер честно различает", async () => {
    await applyCorrection({
      ...PREVIEW,
      applied: true,
      strategy: "flag",
      total_changed: 0,
      total_still_outliers: 0,
      added_columns: ["value_outlier_flag"],
      status: "warning",
      total_outliers_after: 4,
    });
    const banner = await screen.findByText(/Значения не изменены, добавлены флаг-колонки: value_outlier_flag/);
    expect(banner).toHaveClass("bg-amber-50");
  });
});

// ── spec_status_original_series.md, задача B (PROGR-24-ORIGIN-B):
//    группировка чекбоксов мастера «Исходные» / «Производные» ───────────
// Спека §«Что показывать вместо статуса» п.2: чекбоксы делятся на
// «Исходные» (выбраны по умолчанию) и «Производные» (свёрнуты, по
// умолчанию не предлагаются, с пояснением). Данные -- derived_summary
// из профиля и ответов коррекций (задача A).

const DERIVED_SUMMARY = {
  total_columns: 2,
  total_numeric_columns: 2,
  total_outliers: 4,
  affected_columns: ["value_detrended"],
  columns: [
    {
      column: "value_detrended", sample_size: 150, outlier_count: 4, outlier_pct: 2.7,
      recommended_method: "iqr", bounds: { lower: -51.83, upper: 50.61 },
      outlier_examples: [25, 70, 105, 130], insufficient_sample: false,
    },
    {
      column: "value_smoothed", sample_size: 150, outlier_count: 0, outlier_pct: 0,
      recommended_method: "iqr", bounds: { lower: -40, upper: 40 },
      outlier_examples: [], insufficient_sample: false,
    },
  ],
};

const PROFILE_DERIVED = { ...PROFILE, derived_summary: DERIVED_SUMMARY };

describe("PreprocessingOutliersPipeline + группировка Исходные/Производные (PROGR-24-ORIGIN-B)", () => {
  beforeEach(() => {
    mockFetchSequence(PROFILE_DERIVED, ALL_COLUMNS);
  });

  it("исходные предзаполнены, производные свёрнуты и НЕ предложены по умолчанию, с пояснением", async () => {
    render(<PreprocessingOutliersPipeline onApplied={jest.fn()} />);

    expect(await screen.findByRole("checkbox", { name: "Выбрать колонку Price" })).toBeChecked();
    expect(screen.getByText("Исходные")).toBeInTheDocument();

    // Группа производных -- <details>, свёрнутый по умолчанию.
    const summary = screen.getByText(/Производные \(2\)/);
    const group = summary.closest("details");
    expect(group).not.toBeNull();
    expect(group).not.toHaveAttribute("open");

    // Чекбоксы производных существуют, но НЕ предзаполнены, даже при всплесках.
    const derivedCheckbox = screen.getByRole("checkbox", { name: "Выбрать колонку value_detrended" });
    expect(derivedCheckbox).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Выбрать колонку value_smoothed" })).not.toBeChecked();

    // Пояснение методологии внутри группы.
    expect(group).toHaveTextContent(/другой статистический вопрос/);
  });

  it("у производных счётчик «всплесков» (терминология спеки), раскрывается по клику", async () => {
    render(<PreprocessingOutliersPipeline onApplied={jest.fn()} />);
    await screen.findByRole("checkbox", { name: "Выбрать колонку Price" });

    fireEvent.click(screen.getByText(/Производные \(2\)/));
    expect(screen.getByText("всплесков: 4")).toBeInTheDocument();
    expect(screen.getByText("всплесков: 0")).toBeInTheDocument();
  });

  it("осознанно отмеченная производная колонка уходит в запрос коррекции", async () => {
    mockFetchSequence(PROFILE_DERIVED, ALL_COLUMNS, PREVIEW, { warnings: [] });
    render(<PreprocessingOutliersPipeline onApplied={jest.fn()} />);

    await screen.findByRole("checkbox", { name: "Выбрать колонку Price" });
    fireEvent.click(screen.getByText(/Производные \(2\)/));
    fireEvent.click(screen.getByRole("checkbox", { name: "Выбрать колонку value_detrended" }));
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    await screen.findByText("Найдено выбросов: 1");

    const correctionCalls = (global.fetch as unknown as jest.Mock).mock.calls.filter((call: unknown[]) =>
      String(call[0]).includes("/dataset/outlier-corrections"),
    );
    expect(correctionCalls).toHaveLength(1);
    const [, init] = correctionCalls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body)).columns).toEqual(["Price", "value_detrended"]);
  });

  it("старый API без derived_summary: группы производных нет (обратная совместимость)", async () => {
    mockFetchSequence(PROFILE, ALL_COLUMNS);
    render(<PreprocessingOutliersPipeline onApplied={jest.fn()} />);

    await screen.findByRole("checkbox", { name: "Выбрать колонку Price" });
    expect(screen.queryByText(/Производные \(/)).not.toBeInTheDocument();
    expect(screen.queryByText("Исходные")).not.toBeInTheDocument();
  });

  it("после apply группа производных обновляется из ответа: флаг-колонка появляется ТОЛЬКО свёрнутой и неснятой (петля PROGR-22 не возвращается)", async () => {
    const APPLY_RESPONSE = {
      ...PREVIEW,
      applied: true,
      total_changed: 1,
      total_still_outliers: 0,
      status: "done",
      total_outliers_after: 0,
      // Операция добавила флаг-колонку: она приходит в derived_summary
      // apply-ответа (задача A) и обязана появиться в свёрнутой группе
      // производных, а НЕ в исходных чекбоксах и НЕ предзаполненной.
      derived_summary: {
        total_columns: 3,
        total_numeric_columns: 3,
        total_outliers: 8,
        affected_columns: ["value_detrended", "value_outlier_flag"],
        columns: [
          ...DERIVED_SUMMARY.columns,
          {
            column: "value_outlier_flag", sample_size: 150, outlier_count: 4, outlier_pct: 2.7,
            recommended_method: "iqr", bounds: { lower: -0.5, upper: 0.5 },
            outlier_examples: [25, 70, 105, 130], insufficient_sample: false,
          },
        ],
      },
    };
    mockFetchSequence(PROFILE_DERIVED, ALL_COLUMNS, PREVIEW, { warnings: [] }, APPLY_RESPONSE);
    const onApplied = jest.fn();
    render(<PreprocessingOutliersPipeline onApplied={onApplied} />);

    await screen.findByRole("checkbox", { name: "Выбрать колонку Price" });
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    await screen.findByText("Найдено выбросов: 1");
    fireEvent.click(screen.getByRole("checkbox", { name: /Подтверждаю изменение активного датасета/i }));
    fireEvent.click(screen.getByRole("button", { name: "Применить исправления" }));
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));

    // Флаг-колонка из apply-ответа видна в группе производных...
    const flagCheckbox = await screen.findByRole("checkbox", { name: "Выбрать колонку value_outlier_flag" });
    // ...НЕ предзаполнена («+4 от самой флаг-колонки» невозможно по построению)...
    expect(flagCheckbox).not.toBeChecked();
    // value_detrended (4 всплеска) и value_outlier_flag (4 всплеска).
    expect(screen.getAllByText("всплесков: 4")).toHaveLength(2);
    // ...а исходные чекбоксы перезаполняются только каноническим профилем.
    expect(screen.getByRole("checkbox", { name: "Выбрать колонку Price" })).not.toBeChecked();
  });
});
