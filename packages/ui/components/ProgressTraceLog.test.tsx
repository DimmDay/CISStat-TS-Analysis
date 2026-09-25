// packages/ui/components/ProgressTraceLog.test.tsx
//
// Тесты развернутой трассы (Task PROGR-4, spec_progress.md §6.2):
// плоский хронологический список trace_events -- то, что раньше показывал
// EventsLogDrawer, теперь здесь, с реальной персистентностью (слой 1
// PROGR-3 + ForecastRun.trace), с фильтром по стадии/узлу.

import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";
import { ProgressTraceLog } from "./ProgressTraceLog";
import type { TraceEventInfo } from "../lib/progress";

const ev = (overrides: Partial<TraceEventInfo>): TraceEventInfo => ({
  event_id: "e1",
  run_id: "RUN-TEST000",
  ts: "2026-09-25T10:00:00+00:00",
  stage: "validation",
  node_id: "formats",
  event_type: "correction_applied",
  payload: { total_changed: 3, strategy: "clip" },
  actor: "user",
  ...overrides,
});

const EVENTS: TraceEventInfo[] = [
  ev({
    event_id: "e-1",
    ts: "2026-09-25T09:00:00+00:00",
    stage: "upload",
    node_id: "structure_confirmed",
    event_type: "upload_completed",
    payload: { name: "fao_prices.csv" },
  }),
  ev({ event_id: "e-2", ts: "2026-09-25T10:00:00+00:00" }),
  ev({
    event_id: "e-3",
    ts: "2026-09-25T11:00:00+00:00",
    stage: "eda",
    node_id: "correlation",
    event_type: "profile_viewed",
    payload: {},
  }),
  ev({
    event_id: "e-4",
    ts: "2026-09-25T12:00:00+00:00",
    stage: "modeling",
    node_id: "backtest",
    event_type: "backtest_run",
    payload: { model_id: "arima" },
  }),
];

describe("ProgressTraceLog", () => {
  it("рендерирует хронологический список: старые события раньше новых", () => {
    render(<ProgressTraceLog events={[EVENTS[1], EVENTS[0]]} />);
    const log = screen.getByRole("log");
    const rows = Array.from(log.querySelectorAll("li"));
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain("upload_completed");
    expect(rows[1].textContent).toContain("correction_applied");
  });

  it("каждая строка: тип события, стадия, узел и факты payload (§4.1)", () => {
    render(<ProgressTraceLog events={[EVENTS[1]]} />);
    const row = screen.getByRole("log").querySelector("li") as HTMLElement;
    expect(row.textContent).toContain("correction_applied");
    expect(row.textContent).toContain("Валидация");
    // Узел -- человекочитаемой меткой (раскрытие трассы §6.2 -- для
    // пользователя, не для отладки id).
    expect(row.textContent).toContain("Форматы и шаблоны");
    expect(row.textContent).toContain("total_changed");
  });

  it("события уровня стадии (node_id=null) рендерируются без узла", () => {
    render(
      <ProgressTraceLog
        events={[ev({ node_id: null, event_type: "target_column_changed", payload: { target_column: "Price" } })]}
      />
    );
    const row = screen.getByRole("log").querySelector("li") as HTMLElement;
    expect(row.textContent).toContain("target_column_changed");
    expect(row.textContent).toContain("target_column");
  });

  it("фильтр по стадии: остаются только события выбранной стадии", () => {
    render(<ProgressTraceLog events={EVENTS} />);
    fireEvent.change(screen.getByLabelText(/Стадия/), { target: { value: "eda" } });
    const rows = Array.from(screen.getByRole("log").querySelectorAll("li"));
    expect(rows).toHaveLength(1);
    expect(rows[0].textContent).toContain("profile_viewed");
  });

  it("фильтр по узлу: подстраивается под выбранную стадию и фильтрует", () => {
    render(<ProgressTraceLog events={EVENTS} />);
    fireEvent.change(screen.getByLabelText(/Стадия/), { target: { value: "modeling" } });
    const nodeSelect = screen.getByLabelText(/Узел/) as HTMLSelectElement;
    const options = Array.from(nodeSelect.options).map((o) => o.value);
    expect(options).toContain("backtest");
    expect(options).not.toContain("formats");
    fireEvent.change(nodeSelect, { target: { value: "backtest" } });
    const rows = Array.from(screen.getByRole("log").querySelectorAll("li"));
    expect(rows).toHaveLength(1);
    expect(rows[0].textContent).toContain("backtest_run");
  });

  it("без стадии фильтр узла недоступен (нечего перечислять)", () => {
    render(<ProgressTraceLog events={EVENTS} />);
    expect((screen.getByLabelText(/Узел/) as HTMLSelectElement).disabled).toBe(true);
  });

  it("пустая трасса -- честное «Событий пока нет.»", () => {
    render(<ProgressTraceLog events={[]} />);
    expect(screen.getByText("Событий пока нет.")).toBeInTheDocument();
  });

  it("фильтр без совпадений -- «Событий пока нет.», а не пустой блок", () => {
    render(<ProgressTraceLog events={[EVENTS[0]]} />);
    fireEvent.change(screen.getByLabelText(/Стадия/), { target: { value: "eda" } });
    expect(screen.getByText("Событий пока нет.")).toBeInTheDocument();
  });
});
