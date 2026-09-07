import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import {
  PreprocessingDecompositionOverview,
  type PreprocessingDecompositionProfile,
  type PreprocessingDecompositionProfileResponse,
} from "./PreprocessingDecompositionOverview";
import { __clearChartDetailCacheForTests } from "../hooks/useChartDetailData";

// Зонд вместо реального recharts: в jsdom ResponsiveContainer даёт 0×0 и
// DOM recharts пуст (см. NavigatorChartPreview.test.tsx — path-ассерты сняты).
// Контракт этого файла — какой payload дошёл до графика как data — проверяем
// через JSON-пробу в DOM.
jest.mock("recharts", () => {
  const React = require("react");
  const probe = (testId: string) => (props: { data?: unknown }) =>
    React.createElement("div", { "data-testid": testId }, JSON.stringify(props.data ?? null));
  const nil = () => null;
  const passthrough = ({ children }: { children?: ReactNode }) => React.createElement("div", null, children);
  return {
    ResponsiveContainer: passthrough,
    LineChart: probe("recharts-data-line"),
    BarChart: probe("recharts-data-bar"),
    Line: nil,
    Bar: nil,
    CartesianGrid: nil,
    XAxis: nil,
    YAxis: nil,
    Tooltip: nil,
    Legend: nil,
    ReferenceLine: nil,
  };
});

// Реальный эндпоинт /dataset/preprocessing/decomposition-profile возвращает
// конверт статуса проверки (его хранит контейнер TsAnalysisPreprocessing,
// в Обзор передаётся развёрнутый .profile) — detail-дозагрузка получает
// тот же конверт.
function envelope(profile: PreprocessingDecompositionProfile): PreprocessingDecompositionProfileResponse {
  return { mode: "auto", status: "done", status_reason: null, profile };
}


const PROFILE: PreprocessingDecompositionProfile = {
  column: "Price", date_column: "Date", applicable: true, reason: null,
  method: "STL", robust: true, frequency: "MS", period: 12, n_points: 60,
  sampled: false, original_count: 60, trend_strength: 0.91,
  seasonal_strength: 0.88, residual_mean: 0.01, residual_std: 1.2,
  ljung_box_lag: 12, ljung_box_pvalue: 0.21, jarque_bera_pvalue: 0.08,
  points: [
    { x: "2024-01-01T00:00:00", observed: 10, trend: 9, seasonal: 1.2, resid: -0.2 },
    { x: "2024-02-01T00:00:00", observed: 12, trend: 9.5, seasonal: 2, resid: 0.5 },
  ],
  seasonal_pattern: [{ phase: 1, label: "1", value: 1.2 }],
  residual_acf: [{ lag: 0, value: 1 }, { lag: 1, value: 0.1 }],
  warnings: [], recommendation: "Сезонность выражена.", methodology_note: "STL additive",
};


describe("PreprocessingDecompositionOverview", () => {
  it("renders diagnostics and light-grey badge tabs", () => {
    render(<PreprocessingDecompositionOverview profile={PROFILE} loading={false} error={null} noDataset={false} />);

    expect(screen.getByText(/STL · период 12/)).toBeInTheDocument();
    const active = screen.getByRole("tab", { name: "Компоненты" });
    const inactive = screen.getByRole("tab", { name: "Сезонный профиль" });
    expect(active).toHaveClass("bg-neutral-200");
    expect(inactive).toHaveClass("bg-neutral-50");
    expect(active).not.toHaveClass("bg-brand");
  });

  it("switches graph views with accessible tabs", () => {
    render(<PreprocessingDecompositionOverview profile={PROFILE} loading={false} error={null} noDataset={false} />);
    fireEvent.click(screen.getByRole("tab", { name: "ACF остатка" }));
    expect(screen.getByRole("img", { name: "ACF остатка STL" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "ACF остатка" })).toHaveAttribute("aria-selected", "true");
  });

  it("shows an honest not-applicable reason", () => {
    render(<PreprocessingDecompositionOverview profile={{ ...PROFILE, applicable: false, reason: "Ряд нерегулярный" }} loading={false} error={null} noDataset={false} />);
    expect(screen.getByRole("status")).toHaveTextContent("Ряд нерегулярный");
  });
});

describe("PreprocessingDecompositionOverview: дозагрузка detail_level (Task 97.3, spec_max_graf_fix.md §6.3)", () => {
  beforeEach(() => {
    global.fetch = jest.fn();
    // кэш detail-хука модульный — изолируем тесты друг от друга
    __clearChartDetailCacheForTests();
  });
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("свёрнутый Обзор не ходит в сеть; раскрытие «Компонентов» запрашивает expanded", async () => {
    const fetchMock = jest.fn().mockResolvedValue({ ok: true, status: 200, json: async () => envelope(PROFILE) });
    global.fetch = fetchMock as unknown as typeof fetch;
    render(<PreprocessingDecompositionOverview profile={PROFILE} loading={false} error={null} noDataset={false} />);

    // §6.3.1: пока панель не раскрыта — дозапроса нет
    expect(fetchMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Развернуть график до размера окна Обзора" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/dataset/preprocessing/decomposition-profile");
    expect(String(url)).toContain("column=Price");
    expect(String(url)).toContain("detail_level=expanded");
    expect(init.credentials).toBe("include");
  });

  it("раскрытие «Сезонного профиля» и «ACF» не дозагружает данные (§6.3.6)", async () => {
    const fetchMock = jest.fn().mockResolvedValue({ ok: true, status: 200, json: async () => envelope(PROFILE) });
    global.fetch = fetchMock as unknown as typeof fetch;
    render(<PreprocessingDecompositionOverview profile={PROFILE} loading={false} error={null} noDataset={false} />);

    fireEvent.click(screen.getByRole("tab", { name: "Сезонный профиль" }));
    fireEvent.click(screen.getByRole("button", { name: "Развернуть график до размера окна Обзора" }));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(document.querySelector("section > .absolute")).not.toBeNull();

    // возврат на «Компоненты»: сброс происходит по клику на видимую часть?
    // Нет — expandedChartId сохраняется; схлопываем и проверяем ACF
    fireEvent.click(screen.getByRole("button", { name: "Свернуть график" }));
    fireEvent.click(screen.getByRole("tab", { name: "ACF остатка" }));
    fireEvent.click(screen.getByRole("button", { name: "Развернуть график до размера окна Обзора" }));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  // Регресс Task 97.4b (полевая ошибка Этапа 3): эндпоинт возвращает конверт
  // {mode, status, profile}; хук кладёт его в data сырым, и график получал
  // конверт вместо профиля — profile.points === undefined → LineChart
  // рендерил пустое поле с живой легендой (скриншот «Компоненты»).
  it("detail-ответ-конверт разворачивается: график получает развёрнутый профиль, а не конверт", async () => {
    const detailProfile: PreprocessingDecompositionProfile = {
      ...PROFILE,
      n_points: 240,
      points: [{ x: "2024-01-01T00:00:00", observed: 42.25, trend: 9, seasonal: 1.2, resid: -0.2 }],
    };
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => envelope(detailProfile),
    });
    global.fetch = fetchMock as unknown as typeof fetch;
    render(<PreprocessingDecompositionOverview profile={PROFILE} loading={false} error={null} noDataset={false} />);

    fireEvent.click(screen.getByRole("button", { name: "Развернуть график до размера окна Обзора" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const probe = await screen.findByTestId("recharts-data-line");
    // в data графика — развёрнутый detail-профиль (нет полей конверта)
    expect(probe).not.toHaveTextContent('"mode":"auto"');
    expect(probe).not.toHaveTextContent('"status_reason"');
    // и это именно detail-точки, а не compact-фолбэк (там observed: 10/12)
    expect(probe).toHaveTextContent('"observed":42.25');
  });

  it("ошибка дозагрузки сохраняет компактный график (graceful degradation, §6.3.6)", async () => {
    const fetchMock = jest.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({ detail: "нет" }) });
    global.fetch = fetchMock as unknown as typeof fetch;
    render(<PreprocessingDecompositionOverview profile={PROFILE} loading={false} error={null} noDataset={false} />);

    fireEvent.click(screen.getByRole("button", { name: "Развернуть график до размера окна Обзора" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const probe = await screen.findByTestId("recharts-data-line");
    // компактные данные остались в графике, конверт/ошибка не прокинулись
    expect(probe).toHaveTextContent('"observed":10');
    expect(probe).not.toHaveTextContent('"mode"');
  });
});
