// packages/ui/lib/progress.test.ts
//
// Тесты чистой логики панели «Прогресс» (Task PROGR-4, spec_progress.md
// §3 + §12 п.10 + аддендум §4.1-4.2): свёртка статусов узлов стадии в три
// визуальных состояния, вывод статуса узла из фактов трассы (§4.1 --
// трасса журнал решений, не статистика), человекочитаемые метки узлов,
// слияние forecasting-событий ForecastRun.trace (статус Прогнозирования
// §3: "по факту наличия ForecastRun/конкретных trace_events").
//
// Полная таблица свёртки -- зеркальный порт app/core/pipeline_graph.py::
// fold_status_values (§12 п.10): любой единичный warning/error делает
// карточку жёлтой; skipped агрегатно не мешает пройденности; неизвестный
// статус -- ошибка, а не тихий нейтральный узел. Расхождение порта с
// бэкенд-таблицей ловится этими кейсами + sync-тестом реестра узлов
// (tests/api/test_progress_panel.py).

import {
  PROGRESS_STAGE_NODES,
  nodeLabel,
  deriveNodeStatuses,
  foldNodeStatuses,
  stageSummary,
  collectForecastTraceEvents,
  sortEventsChronologically,
  type TraceEventInfo,
} from "./progress";

const ev = (overrides: Partial<TraceEventInfo>): TraceEventInfo => ({
  event_id: "e1",
  run_id: "RUN-TEST000",
  ts: "2026-09-25T10:00:00+00:00",
  stage: "validation",
  node_id: "formats",
  event_type: "correction_applied",
  payload: {},
  actor: "user",
  ...overrides,
});

describe("PROGRESS_STAGE_NODES (реестр узлов, sync с графом бэкенда)", () => {
  it("содержит 6 стадий в каноническом порядке §2", () => {
    expect(Object.keys(PROGRESS_STAGE_NODES)).toEqual([
      "upload", "validation", "preprocessing", "eda", "modeling", "forecasting",
    ]);
  });

  it("суммарно 46 узлов (1+10+10+10+11+4)", () => {
    const counts = Object.values(PROGRESS_STAGE_NODES).map((n) => n.length);
    expect(counts).toEqual([1, 10, 10, 10, 11, 4]);
  });

  it("у каждого узла есть непустая человекочитаемая метка", () => {
    for (const [stage, nodes] of Object.entries(PROGRESS_STAGE_NODES)) {
      for (const nodeId of nodes) {
        const label = nodeLabel(stage, nodeId);
        expect(label).toBeTruthy();
        expect(label).not.toBe(nodeId); // метка, а не сырой id
      }
    }
  });

  it("неизвестный узел отдаёт сырой id как честный фоллбек", () => {
    expect(nodeLabel("validation", "no_such_node")).toBe("no_such_node");
  });
});

describe("deriveNodeStatuses (статус узла из фактов трассы §4.1)", () => {
  it("терминальные события дают done: applied/upload/backtest/tuning/select/card/forecast_*", () => {
    const events = [
      ev({ stage: "upload", node_id: "structure_confirmed", event_type: "upload_completed" }),
      ev({ stage: "validation", node_id: "formats", event_type: "correction_applied" }),
      ev({ stage: "modeling", node_id: "backtest", event_type: "backtest_run" }),
      ev({ stage: "modeling", node_id: "tuning", event_type: "tuning_trial_completed" }),
      ev({ stage: "modeling", node_id: "selection", event_type: "model_selected" }),
      ev({ stage: "modeling", node_id: "model_card", event_type: "model_card_generated" }),
      ev({ stage: "forecasting", node_id: "forecast_generated", event_type: "forecast_generated" }),
      ev({ stage: "forecasting", node_id: "forecast_exported", event_type: "forecast_exported" }),
    ];
    const statuses = deriveNodeStatuses(events);
    expect(statuses["upload/structure_confirmed"]).toBe("done");
    expect(statuses["validation/formats"]).toBe("done");
    expect(statuses["modeling/backtest"]).toBe("done");
    expect(statuses["forecasting/forecast_generated"]).toBe("done");
  });

  it("correction_previewed -> warning (проблемы найдены, решение не применено)", () => {
    const statuses = deriveNodeStatuses([
      ev({ stage: "preprocessing", node_id: "missing", event_type: "correction_previewed" }),
    ]);
    expect(statuses["preprocessing/missing"]).toBe("warning");
  });

  it("profile_viewed -> running (узел исследуется)", () => {
    const statuses = deriveNodeStatuses([
      ev({ stage: "eda", node_id: "correlation", event_type: "profile_viewed" }),
    ]);
    expect(statuses["eda/correlation"]).toBe("running");
  });

  it("последнее событие узла выигрывает: previewed -> applied = done", () => {
    const statuses = deriveNodeStatuses([
      ev({ stage: "validation", node_id: "ranges", event_type: "correction_previewed" }),
      ev({ stage: "validation", node_id: "ranges", event_type: "correction_applied" }),
    ]);
    expect(statuses["validation/ranges"]).toBe("done");
  });

  it("события уровня стадии (node_id=null) не создают статусов узлов", () => {
    const statuses = deriveNodeStatuses([
      ev({ stage: "validation", node_id: null, event_type: "target_column_changed" }),
      ev({ stage: "eda", node_id: null, event_type: "passport_captured" }),
    ]);
    expect(statuses).toEqual({});
  });

  it("события вне узлов графа не создают фантомных узлов (fail-safe)", () => {
    const statuses = deriveNodeStatuses([
      ev({ stage: "validation", node_id: "ghost_node", event_type: "correction_applied" }),
      ev({ stage: "forecasting", node_id: "formats", event_type: "forecast_generated" }),
    ]);
    expect(statuses).toEqual({});
  });

  it("события неизвестных типов молча пропускаются (трасса шире узловых статусов)", () => {
    const statuses = deriveNodeStatuses([
      ev({ stage: "validation", node_id: "formats", event_type: "mode_changed" }),
    ]);
    expect(statuses).toEqual({});
  });
});

describe("foldNodeStatuses (свёртка §12 п.10, порт fold_status_values)", () => {
  it("пусто -> не начато", () => {
    expect(foldNodeStatuses([])).toBe("not_started");
  });

  it("любой warning/error -> attention, даже среди done", () => {
    expect(foldNodeStatuses(["done", "warning", "done"])).toBe("attention");
    expect(foldNodeStatuses(["error"])).toBe("attention");
  });

  it("все done -> passed", () => {
    expect(foldNodeStatuses(["done", "done"])).toBe("passed");
  });

  it("done+skipped (есть done) -> passed; только skipped -> not_started", () => {
    expect(foldNodeStatuses(["done", "skipped"])).toBe("passed");
    expect(foldNodeStatuses(["skipped", "skipped"])).toBe("not_started");
  });

  it("started-признаки (running/in_progress) -> attention", () => {
    expect(foldNodeStatuses(["running"])).toBe("attention");
    expect(foldNodeStatuses(["in_progress"])).toBe("attention");
    expect(foldNodeStatuses(["done", "pending", "running"])).toBe("attention");
  });

  it("pending/смесь pending+skipped -> not_started", () => {
    expect(foldNodeStatuses(["pending"])).toBe("not_started");
    expect(foldNodeStatuses(["pending", "skipped"])).toBe("not_started");
  });

  it("неизвестный статус -> ошибка (fail-closed, не тихий нейтральный)", () => {
    expect(() => foldNodeStatuses(["excellent"])).toThrow(/Неизвестный статус узла/);
  });
});

describe("stageSummary (свод по стадии: свёртка + краткий текст §6.2)", () => {
  it("нет событий -> not_started / «не начато»", () => {
    const summary = stageSummary("validation", {});
    expect(summary.fold).toBe("not_started");
    expect(summary.text).toBe("не начато");
  });

  it("есть warning -> attention / «N/total, найдены проблемы»", () => {
    const statuses = deriveNodeStatuses([
      ev({ stage: "validation", node_id: "formats", event_type: "correction_previewed" }),
      ev({ stage: "validation", node_id: "ranges", event_type: "correction_applied" }),
    ]);
    const summary = stageSummary("validation", statuses);
    expect(summary.fold).toBe("attention");
    expect(summary.text).toBe("1/10, найдены проблемы");
  });

  it("частично пройдено без warning -> attention / «N/total, в работе»", () => {
    const statuses = deriveNodeStatuses([
      ev({ stage: "modeling", node_id: "backtest", event_type: "backtest_run" }),
    ]);
    const summary = stageSummary("modeling", statuses);
    expect(summary.fold).toBe("attention");
    expect(summary.text).toBe("1/11, в работе");
  });

  it("все узлы done -> passed / «N/N, пройдено»", () => {
    const statuses: Record<string, string> = {};
    for (const nodeId of PROGRESS_STAGE_NODES.upload) {
      statuses[`upload/${nodeId}`] = "done";
    }
    const summary = stageSummary("upload", statuses);
    expect(summary.fold).toBe("passed");
    expect(summary.text).toBe("1/1, пройдено");
  });
});

describe("collectForecastTraceEvents (слияние ForecastRun.trace, §3)", () => {
  it("legacy-ключ timestamp -> ts, node_id = event_type, stage = forecasting", () => {
    const events = collectForecastTraceEvents([
      {
        forecast_id: "f-1",
        trace_events: [
          { event_type: "forecast_generated", timestamp: "2026-09-25T12:00:00+00:00", payload: { model_name: "ARIMA" } },
        ],
      },
    ]);
    expect(events).toHaveLength(1);
    expect(events[0].ts).toBe("2026-09-25T12:00:00+00:00");
    expect(events[0].stage).toBe("forecasting");
    expect(events[0].node_id).toBe("forecast_generated");
    expect(events[0].payload).toEqual({ model_name: "ARIMA" });
  });

  it("несколько прогнозов -> плоский список в порядке обхода", () => {
    const events = collectForecastTraceEvents([
      { forecast_id: "f-1", trace_events: [{ event_type: "forecast_generated", timestamp: "t1" }] },
      { forecast_id: "f-2", trace_events: [
        { event_type: "forecast_generated", timestamp: "t2" },
        { event_type: "forecast_exported", timestamp: "t3" },
      ] },
    ]);
    expect(events.map((e) => e.event_type)).toEqual([
      "forecast_generated", "forecast_generated", "forecast_exported",
    ]);
  });

  it("чужие типы событий и пустые трассы пропускаются (fail-safe)", () => {
    const events = collectForecastTraceEvents([
      { forecast_id: "f-1", trace_events: [{ event_type: "custom_event", timestamp: "t" }] },
      { forecast_id: "f-2", trace_events: [] },
      {},
    ]);
    expect(events).toEqual([]);
  });
});

describe("sortEventsChronologically (хронологический список §6.2)", () => {
  it("сортирует по ts по возрастанию, битые ts -- в конец", () => {
    const sorted = sortEventsChronologically([
      ev({ ts: "2026-09-25T12:00:00+00:00" }),
      ev({ ts: "2026-09-25T10:00:00+00:00" }),
      ev({ ts: "не дата" }),
      ev({ ts: "2026-09-25T11:00:00+00:00" }),
    ]);
    expect(sorted.map((e) => e.ts)).toEqual([
      "2026-09-25T10:00:00+00:00",
      "2026-09-25T11:00:00+00:00",
      "2026-09-25T12:00:00+00:00",
      "не дата",
    ]);
  });
});
