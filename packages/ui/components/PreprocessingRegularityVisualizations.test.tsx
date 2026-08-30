import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";

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
