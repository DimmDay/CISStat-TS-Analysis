import "@testing-library/jest-dom";
import { render, screen, waitFor } from "@testing-library/react";

import {
  OutlierLineChart, OutlierHistogramChart, OutlierDensityChart, OutlierBoxplotChart,
} from "./PreprocessingOutliersVisualizations";

// ── Дефект «график выбросов не изменился после кэпирования» (2026-09-25) ──
// Контракт всех четырёх графиков Обзора: изменение refreshKey (сигнал
// «данные сессии обновились» — тот же, что перезапрашивает профиль/счётчик)
// обязано перезапросить данные графика; ревизия передаётся в query (revision)
// как cache-buster. Без этого UI противоречит сам себе: счётчик «выбросов — 0»
// после кэпирования, а график показывает старый ряд (запрос сделан до коммита
// apply — медленный прод — и больше не повторяется при смонтированном графике).
describe("Outlier charts refetch on refreshKey (revision cache-buster)", () => {
  const cases: Array<{
    name: string;
    props: Record<string, unknown>;
    path: string;
    element: (props: Record<string, unknown>) => React.ReactElement;
  }> = [
    {
      name: "OutlierLineChart",
      props: { column: "Price" },
      path: "/dataset/outlier-line",
      element: (props) => <OutlierLineChart column={props.column as string} refreshKey={props.refreshKey as number} />,
    },
    {
      name: "OutlierHistogramChart",
      props: { column: "Price", method: "iqr" },
      path: "/dataset/outlier-histogram",
      element: (props) => <OutlierHistogramChart column={props.column as string} method={props.method as string} refreshKey={props.refreshKey as number} />,
    },
    {
      name: "OutlierDensityChart",
      props: { column: "Price" },
      path: "/dataset/outlier-density",
      element: (props) => <OutlierDensityChart column={props.column as string} refreshKey={props.refreshKey as number} />,
    },
    {
      name: "OutlierBoxplotChart",
      props: { column: "Price", method: "iqr" },
      path: "/dataset/outlier-boxplot",
      element: (props) => <OutlierBoxplotChart column={props.column as string} method={props.method as string} refreshKey={props.refreshKey as number} />,
    },
  ];

  it.each(cases)("$name refetches with a new revision when refreshKey changes", async ({ props, path, element }) => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        points: [{ x: 0, y: 1 }], sampled: false, sampling_method: null, original_count: 1,
        bins: [{ x0: 0, x1: 10, count: 1 }], bounds: null,
        outliers: null, normal: null, column: "Price",
      }),
    });
    global.fetch = fetchMock as unknown as typeof fetch;

    const { rerender } = render(element({ ...props, refreshKey: 0 }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(String(fetchMock.mock.calls[0][0])).toContain(path);
    expect(String(fetchMock.mock.calls[0][0])).toContain("revision=0");

    rerender(element({ ...props, refreshKey: 2 }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const secondUrl = String(fetchMock.mock.calls[1][0]);
    expect(secondUrl).toContain(path);
    expect(secondUrl).toContain("revision=2");
  });
});

describe("OutlierLineChart", () => {
  it("prompts to pick a column when none is selected", () => {
    render(<OutlierLineChart column={null} />);
    expect(screen.getByText(/Выберите числовой признак/)).toBeInTheDocument();
  });

  // ── Дефект 2026-09-25 «график не изменился после кэпирования» ──
  // Кэпирование прижимает выбросы К границе IQR (а не удаляет): без границ
  // метода на графике результат исправления визуально не отличим от исходного
  // ряда, хотя счётчик честно показывает 0 (прижатые значения лежат НА
  // границе). Линейный график обязан показывать те же границы-пунктир, что
  // уже показывает гистограмма, -- тогда «0 выбросов» читается с графика:
  // нет точек за пунктиром, прижатые значения сидят на нём.
  it("shows method bounds as fence lines and a hint when bounds are present", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        points: [{ x: 0, y: 10 }, { x: 1, y: 1000 }],
        sampled: false, sampling_method: null, original_count: 2,
        bounds: { lower: -5.5, upper: 25.25 },
      }),
    });
    render(<OutlierLineChart column="Price" method="iqr" />);
    expect(await screen.findByText(/Границы метода \(пунктир\)/)).toBeInTheDocument();
    // fmt -- ru-RU (запятая как десятичный разделитель, без хвостовых нулей).
    expect(screen.getByText(/-5,5 … 25,25/)).toBeInTheDocument();
    // Примечание: сами SVG-линии ReferenceLine в jsdom не рендерятся
    // (ResponsiveContainer с нулевым размером), визуальный рендер границ
    // верифицируется браузерным E2E-прогоном; здесь контракт -- данные
    // (bounds в ответе) и подсказка.
  });

  it("requests the line series with the detection method for bounds", async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ points: [{ x: 0, y: 1 }], sampled: false, sampling_method: null, original_count: 1, bounds: null }),
    });
    global.fetch = fetchMock as unknown as typeof fetch;
    render(<OutlierLineChart column="Price" method="mad" />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(String(fetchMock.mock.calls[0][0])).toContain("method=mad");
  });

  it("hides the bounds hint when bounds are absent", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        points: [{ x: 0, y: 1 }], sampled: false, sampling_method: null, original_count: 1,
        bounds: null,
      }),
    });
    render(<OutlierLineChart column="Price" method="iqr" />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(screen.queryByText(/Границы метода \(пунктир\)/)).not.toBeInTheDocument();
  });

  it("shows a sampling notice when the backend sampled points", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        points: [{ x: 0, y: 1 }, { x: 1, y: 2 }],
        sampled: true, sampling_method: "lttb", original_count: 5000,
        bounds: null,
      }),
    });
    render(<OutlierLineChart column="Price" method="iqr" />);
    expect(await screen.findByText(/Показано 2 из 5000 точек/)).toBeInTheDocument();
  });

  it("shows an alert when the request fails", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 422, json: () => Promise.resolve({ detail: "не числовая" }) });
    render(<OutlierLineChart column="Region" method="iqr" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("не числовая");
  });
});

describe("OutlierHistogramChart", () => {
  it("renders bounds hint when bounds are present", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        bins: [{ x0: 0, x1: 10, count: 5 }, { x0: 10, x1: 20, count: 2 }],
        bounds: { lower: -5, upper: 25 },
      }),
    });
    render(<OutlierHistogramChart column="Price" method="iqr" />);
    expect(await screen.findByText(/Границы метода \(пунктир\)/)).toBeInTheDocument();
  });

  it("explains when there are no bins", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ bins: [], bounds: null }) });
    render(<OutlierHistogramChart column="Price" method="iqr" />);
    expect(await screen.findByText("Нет данных.")).toBeInTheDocument();
  });
});

describe("OutlierDensityChart", () => {
  it("explains when density is undefined (constant column)", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ points: null }) });
    render(<OutlierDensityChart column="Price" />);
    expect(await screen.findByText(/Плотность не определена/)).toBeInTheDocument();
  });
});

describe("OutlierBoxplotChart", () => {
  it("renders both groups when data is present", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        column: "Price",
        outliers: { count: 1, min: 1000, q1: 1000, median: 1000, q3: 1000, max: 1000, mean: 1000 },
        normal: { count: 20, min: 5, q1: 8, median: 10, q3: 12, max: 15, mean: 10 },
      }),
    });
    render(<OutlierBoxplotChart column="Price" method="iqr" />);
    expect(await screen.findByText("Выброс")).toBeInTheDocument();
    expect(screen.getByText("Норма")).toBeInTheDocument();
    expect(screen.getByText("n=1, медиана=1000.00")).toBeInTheDocument();
  });

  it("shows 'no data' for an empty group", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ column: "Price", outliers: null, normal: { count: 5, min: 1, q1: 2, median: 3, q3: 4, max: 5, mean: 3 } }),
    });
    render(<OutlierBoxplotChart column="Price" method="iqr" />);
    expect(await screen.findByText("Нет данных")).toBeInTheDocument();
  });
});
