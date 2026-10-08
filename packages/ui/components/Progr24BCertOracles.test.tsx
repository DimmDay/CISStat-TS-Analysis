import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { PreprocessingOutliersPipeline } from "./PreprocessingOutliersPipeline";
import { PreprocessingOutliersOverview, spikesLabel } from "./PreprocessingOutliersOverview";
import { PreprocessingStationarityPipeline } from "./PreprocessingStationarityPipeline";

// ── PROGR-24-B-CERT: независимый оракул сертификации задачи B ──────────
// (spec_status_original_series.md: grouping in Outlier wizard + neutral
// Overview plate + Stationarity preview note). СВОИ данные и сценарии:
// колонки revenue/temperature (+ нечисловая region), производные
// revenue_log_diff (3 всплеска) и revenue_ma7 (0), флаг-колонка
// revenue_outlier_flag (6) в apply-ответе. Числа и имена НЕ совпадают с
// моками разработчика -- это независимая реконструкция контрактов.
// Части оракула, падающие на коде без задачи B -- RED-доказательство;
// убиваемость мутантов -- kill-обязательство протокола сертификации.

const ORACLE_PROFILE = {
  rule_source: "system", mode: "auto", status: "warning", status_reason: null, method: "iqr",
  total_rows: 96, total_numeric_columns: 2, total_outliers: 2, outlier_rate_pct: 2.08,
  affected_columns: ["revenue"],
  columns: [
    {
      column: "revenue", sample_size: 96, outlier_count: 2, outlier_pct: 2.08,
      recommended_method: "iqr", bounds: { lower: -12.5, upper: 40.2 },
      outlier_examples: [31, 77], insufficient_sample: false,
    },
    {
      column: "temperature", sample_size: 96, outlier_count: 0, outlier_pct: 0,
      recommended_method: "mad", bounds: { lower: -8, upper: 31 },
      outlier_examples: [], insufficient_sample: false,
    },
  ],
};

const ORACLE_DERIVED = {
  total_columns: 2, total_numeric_columns: 2, total_outliers: 3,
  affected_columns: ["revenue_log_diff"],
  columns: [
    {
      column: "revenue_log_diff", sample_size: 95, outlier_count: 3, outlier_pct: 3.16,
      recommended_method: "iqr", bounds: { lower: -0.21, upper: 0.19 },
      outlier_examples: [12, 45, 80], insufficient_sample: false,
    },
    {
      column: "revenue_ma7", sample_size: 90, outlier_count: 0, outlier_pct: 0,
      recommended_method: "iqr", bounds: { lower: -5, upper: 5 },
      outlier_examples: [], insufficient_sample: false,
    },
  ],
};

const ORACLE_PROFILE_FULL = { ...ORACLE_PROFILE, derived_summary: ORACLE_DERIVED };

const ORACLE_ALL_COLUMNS = { columns: [{ column: "revenue" }, { column: "temperature" }, { column: "region" }] };

const ORACLE_PREVIEW = {
  applied: false, strategy: "cap", method: "iqr", used_residual: false,
  total_outliers: 5, total_changed: 5, total_still_outliers: 0,
  rows_removed: 0, added_columns: [],
  status: "done", total_outliers_after: 0,
  columns: [
    {
      column: "revenue", outlier_count: 2, changed_count: 2, still_outliers: 0, outlier_examples: [31, 77], flag_column: null,
      stats_before: { mean: 31.4, median: 30.1, std: 12.8 },
      stats_after: { mean: 30.2, median: 30.1, std: 4.1 },
    },
    {
      column: "revenue_log_diff", outlier_count: 3, changed_count: 3, still_outliers: 0, outlier_examples: [12, 45, 80], flag_column: null,
      stats_before: { mean: 0.01, median: 0.0, std: 0.14 },
      stats_after: { mean: 0.0, median: 0.0, std: 0.05 },
    },
  ],
  profile: [
    { column: "revenue", sample_size: 96, outlier_count: 0, outlier_pct: 0, recommended_method: "iqr", bounds: { lower: -12.5, upper: 40.2 }, outlier_examples: [], insufficient_sample: false },
    { column: "temperature", sample_size: 96, outlier_count: 0, outlier_pct: 0, recommended_method: "mad", bounds: { lower: -8, upper: 31 }, outlier_examples: [], insufficient_sample: false },
  ],
};

function oracleFetchSequence(...responses: unknown[]) {
  const queue = [...responses];
  global.fetch = jest.fn(() => {
    const next = queue.shift() ?? responses[responses.length - 1];
    return Promise.resolve({ ok: true, json: () => Promise.resolve(next) });
  }) as unknown as typeof fetch;
}

describe("PROGR-24-B-CERT O1: spikesLabel -- русская плюрализация на СВОИХ числах", () => {
  it("1/21/101 всплеск; 2-4/22-24/122 всплеска; 5-20/11-14/111/100 всплесков", () => {
    const cases: Array<[number, string]> = [
      [1, "1 всплеск"], [21, "21 всплеск"], [101, "101 всплеск"], [121, "121 всплеск"],
      [2, "2 всплеска"], [3, "3 всплеска"], [4, "4 всплеска"], [22, "22 всплеска"],
      [23, "23 всплеска"], [24, "24 всплеска"], [122, "122 всплеска"],
      // GREEN-фаза оракула: 214 оканчивается на «-надцать» (mod100=14) --
      // «всплесков»; контрпример 224 (mod100=24>14) -- «всплеска».
      [214, "214 всплесков"], [224, "224 всплеска"],
      [5, "5 всплесков"], [11, "11 всплесков"], [12, "12 всплесков"], [13, "13 всплесков"],
      [14, "14 всплесков"], [15, "15 всплесков"], [20, "20 всплесков"], [100, "100 всплесков"],
      [111, "111 всплесков"], [112, "112 всплесков"], [125, "125 всплесков"],
    ];
    for (const [n, expected] of cases) {
      expect(spikesLabel(n)).toBe(expected);
    }
  });
});

describe("PROGR-24-B-CERT O2/O3/O9: мастер «Выбросов» на своих данных", () => {
  it("O2: исходные предзаполнены (revenue да, temperature нет), производные свёрнуты в <details>, НЕ предзаполнены, с пояснением, счётчик «всплесков»", async () => {
    oracleFetchSequence(ORACLE_PROFILE_FULL, ORACLE_ALL_COLUMNS);
    render(<PreprocessingOutliersPipeline onApplied={jest.fn()} />);

    expect(await screen.findByRole("checkbox", { name: "Выбрать колонку revenue" })).toBeChecked();
    // Каноническая колонка без выбросов НЕ предзаполнена (своя пара чисел: revenue=2, temperature=0).
    expect(screen.getByRole("checkbox", { name: "Выбрать колонку temperature" })).not.toBeChecked();
    expect(screen.getByText("Исходные")).toBeInTheDocument();

    const summary = screen.getByText(/Производные \(2\)/);
    const group = summary.closest("details");
    expect(group).not.toBeNull();
    expect(group).not.toHaveAttribute("open");
    // Производные с всплесками НЕ предзаполнены: выбор -- осознанное действие.
    expect(screen.getByRole("checkbox", { name: "Выбрать колонку revenue_log_diff" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Выбрать колонку revenue_ma7" })).not.toBeChecked();
    // Пояснение методологии -- свой текст-маркер спеки.
    expect(group).toHaveTextContent(/другой статистический вопрос/);

    fireEvent.click(summary);
    expect(screen.getByText("всплесков: 3")).toBeInTheDocument();
    expect(screen.getByText("всплесков: 0")).toBeInTheDocument();
    expect(screen.getByText("выбросов: 2")).toBeInTheDocument();
  });

  it("O9: осознанно отмеченная производная revenue_log_diff уходит в POST-тело коррекции вместе с канонической revenue", async () => {
    oracleFetchSequence(ORACLE_PROFILE_FULL, ORACLE_ALL_COLUMNS, ORACLE_PREVIEW, { warnings: [] });
    render(<PreprocessingOutliersPipeline onApplied={jest.fn()} />);

    await screen.findByRole("checkbox", { name: "Выбрать колонку revenue" });
    fireEvent.click(screen.getByText(/Производные \(2\)/));
    fireEvent.click(screen.getByRole("checkbox", { name: "Выбрать колонку revenue_log_diff" }));
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    expect(await screen.findByText("Найдено выбросов: 5")).toBeInTheDocument();

    const correctionCalls = (global.fetch as unknown as jest.Mock).mock.calls.filter((call: unknown[]) =>
      String(call[0]).includes("/dataset/outlier-corrections"),
    );
    expect(correctionCalls).toHaveLength(1);
    const [, init] = correctionCalls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body)).columns).toEqual(["revenue", "revenue_log_diff"]);
  });

  it("O3: после apply флаг-колонка revenue_outlier_flag появляется ТОЛЬКО в свёрнутой группе производных и неснятой; канонические перезаполняются только профилем", async () => {
    const ORACLE_APPLY = {
      ...ORACLE_PREVIEW,
      applied: true,
      total_changed: 5,
      total_still_outliers: 0,
      status: "done",
      total_outliers_after: 0,
      derived_summary: {
        total_columns: 3,
        total_numeric_columns: 3,
        total_outliers: 9,
        affected_columns: ["revenue_log_diff", "revenue_outlier_flag"],
        columns: [
          ...ORACLE_DERIVED.columns,
          {
            column: "revenue_outlier_flag", sample_size: 96, outlier_count: 6, outlier_pct: 6.25,
            recommended_method: "iqr", bounds: { lower: -0.5, upper: 0.5 },
            outlier_examples: [31, 77], insufficient_sample: false,
          },
        ],
      },
    };
    oracleFetchSequence(ORACLE_PROFILE_FULL, ORACLE_ALL_COLUMNS, ORACLE_PREVIEW, { warnings: [] }, ORACLE_APPLY);
    const onApplied = jest.fn();
    render(<PreprocessingOutliersPipeline onApplied={onApplied} />);

    await screen.findByRole("checkbox", { name: "Выбрать колонку revenue" });
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    expect(await screen.findByText("Найдено выбросов: 5")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /Подтверждаю изменение активного датасета/i }));
    fireEvent.click(screen.getByRole("button", { name: "Применить исправления" }));
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));

    // Флаг-колонка из apply-ответа -- в группе производных (раскрыть) ...
    fireEvent.click(screen.getByText(/Производные \(3\)/));
    const flagCheckbox = screen.getByRole("checkbox", { name: "Выбрать колонку revenue_outlier_flag" });
    // ...НЕ предзаполнена (петля «+6 от самой флаг-колонки» невозможна)...
    expect(flagCheckbox).not.toBeChecked();
    expect(screen.getByText("всплесков: 6")).toBeInTheDocument();
    expect(screen.getByText("всплесков: 3")).toBeInTheDocument();
    expect(screen.getAllByText("всплесков: 0")).toHaveLength(1);
    // ...а канонические чекбоксы перезаполняются только профилем (выбросов после = 0).
    expect(screen.getByRole("checkbox", { name: "Выбрать колонку revenue" })).not.toBeChecked();
  });

  it("O4: старый API без derived_summary -- ни «Исходные», ни группы «Производные» (пин обратной совместимости на своих данных)", async () => {
    oracleFetchSequence(ORACLE_PROFILE, ORACLE_ALL_COLUMNS);
    render(<PreprocessingOutliersPipeline onApplied={jest.fn()} />);

    await screen.findByRole("checkbox", { name: "Выбрать колонку revenue" });
    expect(screen.queryByText(/Производные \(/)).not.toBeInTheDocument();
    expect(screen.queryByText("Исходные")).not.toBeInTheDocument();
  });

  it("O10: переключение производного чекбокса Сбрасывает устаревший предпросмотр (invalidatePreview)", async () => {
    oracleFetchSequence(ORACLE_PROFILE_FULL, ORACLE_ALL_COLUMNS, ORACLE_PREVIEW);
    render(<PreprocessingOutliersPipeline onApplied={jest.fn()} />);

    await screen.findByRole("checkbox", { name: "Выбрать колонку revenue" });
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    expect(await screen.findByText("Найдено выбросов: 5")).toBeInTheDocument();

    // Переключение производной колонки делает предпросмотр устаревшим --
    // как и переключение канонической, он обязан исчезнуть.
    fireEvent.click(screen.getByText(/Производные \(2\)/));
    fireEvent.click(screen.getByRole("checkbox", { name: "Выбрать колонку revenue_log_diff" }));
    await waitFor(() => expect(screen.queryByText("Найдено выбросов: 5")).not.toBeInTheDocument());
  });
});

describe("PROGR-24-B-CERT O5/O6: Обзор «Выбросов» -- нейтральная плашка на своих данных", () => {
  it("O5: плашка «На производных колонках: 3 всплеска (информативно, статус не меняет)» -- роль note, серый фон, в шапке до tablist, колонки перечислены", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ ...ORACLE_PROFILE, derived_summary: ORACLE_DERIVED }),
    });
    render(<PreprocessingOutliersOverview refreshKey={1} />);
    await screen.findByRole("table", { name: "Выбросы по числовым колонкам" });

    const banner = screen.getByRole("note");
    // Число всплесков -- именно из derived_summary (3), не канонических (2).
    expect(banner).toHaveTextContent("На производных колонках: 3 всплеска (информативно, статус не меняет)");
    expect(banner).toHaveTextContent("revenue_log_diff");
    expect(banner).not.toHaveTextContent("2 всплеска");
    expect(banner).toHaveClass("bg-neutral-50");
    expect(banner.className).not.toContain("bg-amber-50");
    expect(banner.className).not.toContain("bg-red-50");
    // Свой структурный пин: плашка в шапке Обзора -- сразу ПЕРЕД tablist,
    // значит видна во всех вкладках-представлениях.
    expect(banner.nextElementSibling?.getAttribute("role")).toBe("tablist");
  });

  it("O6: плашки нет при нулевых всплесках и для старого API без derived_summary", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(ORACLE_PROFILE) });
    const { rerender } = render(<PreprocessingOutliersOverview refreshKey={1} />);
    await screen.findByRole("table", { name: "Выбросы по числовым колонкам" });
    expect(screen.queryByRole("note")).not.toBeInTheDocument();

    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        ...ORACLE_PROFILE,
        derived_summary: {
          ...ORACLE_DERIVED,
          total_outliers: 0,
          affected_columns: [],
          columns: [{ ...ORACLE_DERIVED.columns[0], outlier_count: 0, outlier_pct: 0, outlier_examples: [] }],
        },
      }),
    });
    rerender(<PreprocessingOutliersOverview refreshKey={2} />);
    await screen.findByRole("table", { name: "Выбросы по числовым колонкам" });
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });
});

describe("PROGR-24-B-CERT O7: мастер «Стационарности» -- заметка о структурном сдвиге", () => {
  it("O7: заметки нет до предпросмотра; после предпросмотра -- текст спеки, инфо-фон (bg-blue-50), не warning/error", async () => {
    const ORACLE_FD = {
      applied: false, column: "revenue", method: "first_difference", output_column: "revenue_fd1",
      rows_before: 240, rows_after: 239, rows_dropped: 3, columns_before: 3, columns_after: 4,
      metadata: { kind: "stationarity", source_column: "revenue", output_column: "revenue_fd1", method: "first_difference", regular_order: 1, seasonal_order: 0, seasonal_period: null, domain_transform: null, causal: true, modeling_safe: true, inverse_supported: true, lost_observations: 3, fitted_on_n: 240, history_tail: [1.5], trend_intercept: null, trend_slope: null },
    };
    global.fetch = jest.fn()
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(ORACLE_FD) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ ...ORACLE_FD, applied: true }) });
    render(<PreprocessingStationarityPipeline column="revenue" recommendedMethod="first_difference" seasonalPeriod={7} onApplied={jest.fn()} />);

    expect(screen.queryByText(/структурным сдвигом/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр преобразования" }));
    const note = await screen.findByText(/Скачки в преобразованном ряду могут быть структурным сдвигом/);
    expect(note).toHaveTextContent("Структурные сдвиги");
    expect(note).toHaveClass("bg-blue-50");
    expect(note.className).not.toContain("bg-amber-50");
    expect(note.className).not.toContain("bg-red-50");
  });
});
