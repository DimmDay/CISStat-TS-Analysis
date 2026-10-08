import "@testing-library/jest-dom";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { PreprocessingOutliersOverview } from "./PreprocessingOutliersOverview";

const PROFILE = {
  rule_source: "system",
  mode: "auto",
  status: "warning",
  status_reason: null,
  method: "iqr",
  total_rows: 21,
  total_numeric_columns: 2,
  total_outliers: 1,
  outlier_rate_pct: 2.4,
  affected_columns: ["Price"],
  columns: [
    {
      column: "Price", sample_size: 21, outlier_count: 1, outlier_pct: 4.76,
      recommended_method: "iqr", bounds: { lower: -5, upper: 25 },
      outlier_examples: [20], insufficient_sample: false,
    },
    {
      column: "Clean", sample_size: 21, outlier_count: 0, outlier_pct: 0,
      recommended_method: "iqr", bounds: { lower: -3, upper: 30 },
      outlier_examples: [], insufficient_sample: false,
    },
  ],
};

describe("PreprocessingOutliersOverview", () => {
  it("renders a per-column outlier table with bounds", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE) });
    render(<PreprocessingOutliersOverview refreshKey={1} />);

    expect(await screen.findByRole("table", { name: "Выбросы по числовым колонкам" })).toBeInTheDocument();
    expect(screen.getByText("Найдены проблемы")).toBeInTheDocument();
    expect(screen.getByText("Пройдено")).toBeInTheDocument();
    expect(screen.getByText("-5.00 … 25.00")).toBeInTheDocument();
  });

  // Task w/n-3: бейдж-паттерн «Генерации признаков» (серые pill-бейджи с
  // рамкой, усиление фона при наведении) распространён на всю
  // «Предобработку». Контракт эталона
  // PreprocessingFeatureEngineeringOverview: tablist живёт ВНУТРИ шапки
  // Обзора (блок p-4 с border-b), классы mt-3 flex flex-wrap gap-2;
  // активный бейдж border-neutral-300 bg-neutral-200 text-neutral-800,
  // неактивный border-neutral-200 bg-neutral-50 text-neutral-500 с
  // hover:bg-neutral-100; семантика role="tab" + aria-selected.
  it("переключатели представлений следуют бейдж-паттерну «Генерации признаков»", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE) });
    render(<PreprocessingOutliersOverview refreshKey={1} />);
    await screen.findByRole("table", { name: "Выбросы по числовым колонкам" });

    const tablist = screen.getByRole("tablist", { name: "Представления проверки выбросов" });
    expect(tablist).toHaveClass("mt-3", "flex", "flex-wrap", "gap-2");
    expect(tablist.parentElement).toHaveClass("p-4");
    expect(tablist.parentElement?.className).toContain("border-b border-neutral-100");

    const active = screen.getByRole("tab", { name: "Таблица" });
    expect(active).toHaveAttribute("aria-selected", "true");
    expect(active).toHaveClass("rounded-full", "border", "px-3", "py-1", "text-xs");
    expect(active).toHaveClass("border-neutral-300", "bg-neutral-200", "text-neutral-800");

    const inactive = screen.getByRole("tab", { name: "Линейный" });
    expect(inactive).toHaveAttribute("aria-selected", "false");
    expect(inactive).toHaveClass("rounded-full", "border", "px-3", "py-1", "text-xs");
    expect(inactive).toHaveClass("border-neutral-200", "bg-neutral-50", "text-neutral-500", "hover:bg-neutral-100");
  });

  it("explains when there are no numeric columns", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ ...PROFILE, columns: [] }),
    });
    render(<PreprocessingOutliersOverview refreshKey={1} />);
    expect(await screen.findByText(/нет числовых колонок/i)).toBeInTheDocument();
  });

  it("shows a neutral explanation when the check is disabled", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ ...PROFILE, mode: "disabled", status: "skipped", status_reason: "disabled" }),
    });
    render(<PreprocessingOutliersOverview refreshKey={1} />);
    expect(await screen.findByRole("status")).toHaveTextContent("отключена аналитиком");
  });

  it("shows an alert when the profile request fails", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 404, json: () => Promise.resolve({ detail: "нет датасета" }) });
    render(<PreprocessingOutliersOverview refreshKey={1} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("нет датасета");
  });

  it("switches to a chart tab and shows the globally selected feature", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE) });
    render(<PreprocessingOutliersOverview refreshKey={1} column="Price" />);
    await screen.findByRole("table", { name: "Выбросы по числовым колонкам" });

    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ bins: [{ x0: 0, x1: 10, count: 3 }], bounds: null }),
    });
    fireEvent.click(screen.getByRole("tab", { name: "Гистограмма" }));

    expect(await screen.findByText(/Признак:/)).toBeInTheDocument();
    expect(screen.getByText("Price")).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Выбросы по числовым колонкам" })).not.toBeInTheDocument();
  });

  // ── Дефект «график выбросов не изменился после кэпирования» (2026-09-25) ──
  // Инвариант согласованности: счётчик (профиль) и графики Обзора подписаны
  // на ОДИН сигнал обновления (refreshKey = outliersRefreshKey + datasetVersion).
  // Применение исправления при смонтированном Обзоре (медленный apply на проде:
  // пользователь вернулся к графику до коммита POST, datasetVersion пришёл
  // ПОСЛЕ монтирования) обязано перезапросить И профиль (счётчик), И ряд
  // линейного графика — иначе UI противоречит сам себе: счётчик «выбросов — 0»,
  // а график показывает старый ряд с выбросами. Ревизия передаётся в URL
  // (cache-buster), чтобы исключить и устаревший HTTP-кэш.
  it("refetches the line series together with the profile when refreshKey changes while mounted", async () => {
    const fetchMock = jest.fn((url: unknown) => {
      const u = String(url);
      if (u.includes("/dataset/outlier-profile")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(PROFILE) });
      }
      if (u.includes("/dataset/outlier-line")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            points: [{ x: 0, y: 1 }, { x: 1, y: 2 }],
            sampled: false, sampling_method: null, original_count: 2,
          }),
        });
      }
      return Promise.reject(new Error(`unexpected fetch: ${u}`));
    });
    global.fetch = fetchMock as unknown as typeof fetch;

    const { rerender } = render(<PreprocessingOutliersOverview refreshKey={0} column="value" />);
    await screen.findByRole("table", { name: "Выбросы по числовым колонкам" });
    fireEvent.click(screen.getByRole("tab", { name: "Линейный" }));
    const lineUrls = () => fetchMock.mock.calls.map(([u]) => String(u)).filter((u) => u.includes("/dataset/outlier-line"));
    await waitFor(() => expect(lineUrls().length).toBe(1));

    rerender(<PreprocessingOutliersOverview refreshKey={1} column="value" />);

    // Профиль перезапросился (счётчик обновился) — гардирует сценарий:
    // это поведение уже есть, оно обязано остаться.
    await waitFor(() => {
      const profileCalls = fetchMock.mock.calls.filter(([u]) => String(u).includes("/dataset/outlier-profile")).length;
      expect(profileCalls).toBe(2);
    });
    // Ряд линейного графика перезапросился вместе с профилем: последний
    // вызов ряда несёт НОВУЮ ревизию (cache-buster). Точное число вызовов
    // не фиксируется: существующий «loading-flash» профиля перемонтирует
    // графики и даёт дополнительный (отбрасываемый active-guard-ом) запрос —
    // контракт о последнем состоянии, не о числе попыток.
    await waitFor(() => {
      const calls = lineUrls();
      expect(calls.length).toBeGreaterThanOrEqual(2);
      expect(calls[calls.length - 1]).toContain("revision=1");
    });
  });
});

// ── spec_status_original_series.md, задача B (PROGR-24-ORIGIN-B):
//    нейтральная плашка Обзора о всплесках на производных колонках ──────
// Спека §«Что показывать вместо статуса» п.1: «На производных колонках:
// 4 всплеска (информативно, статус не меняет)». Плашка НЕ окрашивает
// остановку (нейтральный фон, не amber/red) и живёт в шапке Обзора --
// видна во всех вкладках-представлениях. Данные -- derived_summary
// (задача A), вне статуса.

const DERIVED_SUMMARY = {
  total_columns: 1,
  total_numeric_columns: 1,
  total_outliers: 4,
  affected_columns: ["value_detrended"],
  columns: [
    {
      column: "value_detrended", sample_size: 150, outlier_count: 4, outlier_pct: 2.7,
      recommended_method: "iqr", bounds: { lower: -51.83, upper: 50.61 },
      outlier_examples: [25, 70, 105, 130], insufficient_sample: false,
    },
  ],
};

describe("PreprocessingOutliersOverview + нейтральная плашка производных (PROGR-24-ORIGIN-B)", () => {
  it("показывает плашку с плюрализацией всплесков и именами колонок; фон нейтральный, в шапке Обзора", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ ...PROFILE, derived_summary: DERIVED_SUMMARY }),
    });
    render(<PreprocessingOutliersOverview refreshKey={1} />);
    await screen.findByRole("table", { name: "Выбросы по числовым колонкам" });

    const banner = screen.getByRole("note");
    expect(banner).toHaveTextContent("На производных колонках: 4 всплеска (информативно, статус не меняет)");
    expect(banner).toHaveTextContent("value_detrended");
    // Нейтральность: серый фон, НЕ янтарный/красный (не окрашивает остановку).
    expect(banner).toHaveClass("bg-neutral-50");
    expect(banner.className).not.toContain("bg-amber-50");
    expect(banner.className).not.toContain("bg-red-50");
    // Плашка живёт в шапке Обзора (блок с border-b) -- видна во всех вкладках.
    expect(banner.parentElement?.className).toContain("border-b border-neutral-100");
  });

  it("плашки нет для старого API без derived_summary и при нулевых всплесках", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE) });
    const { rerender } = render(<PreprocessingOutliersOverview refreshKey={1} />);
    await screen.findByRole("table", { name: "Выбросы по числовым колонкам" });
    expect(screen.queryByRole("note")).not.toBeInTheDocument();

    // Новый мок ДО rerender: смена refreshKey перезапрашивает профиль.
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        ...PROFILE,
        derived_summary: { ...DERIVED_SUMMARY, total_outliers: 0, affected_columns: [], columns: [{ ...DERIVED_SUMMARY.columns[0], outlier_count: 0, outlier_pct: 0, outlier_examples: [] }] },
      }),
    });
    rerender(<PreprocessingOutliersOverview refreshKey={2} />);
    await screen.findByRole("table", { name: "Выбросы по числовым колонкам" });
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });
});
