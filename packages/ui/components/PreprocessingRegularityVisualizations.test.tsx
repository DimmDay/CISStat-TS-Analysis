import "@testing-library/jest-dom";
import { render, screen, waitFor } from "@testing-library/react";

import { RegularityIntervalsChart, RegularityTimelineChart } from "./PreprocessingRegularityVisualizations";

describe("RegularityIntervalsChart", () => {
  it("renders the modal/threshold hint once data loads", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        group: "Весь датасет",
        bins: [{ x0: 0, x1: 2678400, count: 5 }],
        modal_seconds: 2678400,
        threshold_seconds: 4017600,
      }),
    });
    render(<RegularityIntervalsChart refreshKey={1} />);
    expect(await screen.findByText(/Модальный интервал/)).toBeInTheDocument();
  });

  it("explains when there is not enough data", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ group: "", bins: [], modal_seconds: null, threshold_seconds: null }),
    });
    render(<RegularityIntervalsChart refreshKey={1} />);
    expect(await screen.findByText(/Недостаточно данных/)).toBeInTheDocument();
  });

  it("shows an alert when the request fails", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 404, json: () => Promise.resolve({ detail: "нет датасета" }) });
    render(<RegularityIntervalsChart refreshKey={1} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("нет датасета");
  });
});

describe("RegularityTimelineChart", () => {
  it("shows a positive message when there are no events", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ date_column: "Date", entity_column: null, min_date: null, max_date: null, events: [], truncated: false }),
    });
    render(<RegularityTimelineChart refreshKey={1} />);
    expect(await screen.findByText(/Нарушений не найдено/)).toBeInTheDocument();
  });

  it("renders a truncation notice when events exceed the cap", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        date_column: "Date", entity_column: null, min_date: "2020-01-01", max_date: "2020-02-01",
        events: [{ date: "2020-01-15", kind: "gap", group: "Весь датасет" }],
        truncated: true,
      }),
    });
    render(<RegularityTimelineChart refreshKey={1} />);
    expect(await screen.findByText(/Показаны первые 1 событий/)).toBeInTheDocument();
  });
});

// ── Волна 3 plan_review_charts.md (Task RCH-3): унификация cache-buster.
// «Регулярность» была подписана на refresh с Task 72, но с legacy-параметром
// `_r=` -- единственным отклонением от канона OUTL-1 (`revision=`). Контракт
// тот же: изменение refreshKey (regularityRefreshKey + datasetVersion -- ТЕМ
// же сигналом перезапрашивается профиль/счётчик Обзора) обязано перезапросить
// оба графика, а ревизия включается в query как cache-buster. Унификация
// оставляет в кодовой базе ОДИН канонический параметр: URL не имеет права
// нести legacy `_r=`. Неизвестный query-параметр FastAPI игнорирует --
// бэкенд не меняется.
describe("Regularity charts carry the canonical revision cache-buster (wave 3)", () => {
  // Надмножество полей обоих ответов: каждый чарт рендерит своё нейтральное
  // пустое состояние (ранние return-ы) -- этого достаточно для контракта о
  // ПОВТОРНЫХ запросах, содержимое отрисовки покрыто сюитами выше.
  const CHART_FIXTURE = {
    group: "", bins: [], modal_seconds: null, threshold_seconds: null,
    date_column: null, entity_column: null, min_date: null, max_date: null,
    events: [], truncated: false,
  };

  const cases: Array<{
    name: string;
    path: string;
    element: (refreshKey: number) => React.ReactElement;
  }> = [
    {
      name: "RegularityIntervalsChart",
      path: "/dataset/preprocessing/regularity-intervals",
      element: (refreshKey) => <RegularityIntervalsChart refreshKey={refreshKey} />,
    },
    {
      name: "RegularityTimelineChart",
      path: "/dataset/preprocessing/regularity-timeline",
      element: (refreshKey) => <RegularityTimelineChart refreshKey={refreshKey} />,
    },
  ];

  it.each(cases)("$name refetches with a new canonical revision when refreshKey changes", async ({ path, element }) => {
    const fetchMock = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(CHART_FIXTURE) });
    global.fetch = fetchMock as unknown as typeof fetch;

    const { rerender } = render(element(1));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const firstUrl = String(fetchMock.mock.calls[0][0]);
    expect(firstUrl).toContain(path);
    expect(firstUrl).toContain("revision=1");
    // Канон волны 3: legacy-параметр выведен из обращения.
    expect(firstUrl).not.toContain("_r=");

    rerender(element(2));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const secondUrl = String(fetchMock.mock.calls[1][0]);
    expect(secondUrl).toContain(path);
    expect(secondUrl).toContain("revision=2");
    expect(secondUrl).not.toContain("_r=");
  });
});
