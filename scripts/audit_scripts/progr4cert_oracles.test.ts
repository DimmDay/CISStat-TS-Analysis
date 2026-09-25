// scripts/audit_scripts/progr4cert_oracles.test.ts
//
// Task PROGR-4-CERT (2026-09-25) -- независимые оракул-тесты аудитора на
// СВОИХ данных (не копия packages/ui/lib/progress.test.ts):
//
//  OR-H. Кросс-языковой fixture свёртки §12 п.10: ВСЕ 2800 комбинаций
//        статусов длины 1..4, размеченные живым бэкендом
//        app/core/pipeline_graph.py::fold_status_values
//        (progr4cert_gen_fold_fixture.py) -- TS-порт обязан совпасть
//        на каждой строке.
//  OR-I. deriveNodeStatuses на своём корпусе: перезапись последним
//        событием, коллизии id между стадиями (regularity валидации и
//        предобработки), фантомы, stage-level (node_id=null), unknown-типы.
//  OR-J. stageSummary на своих ожиданиях текстов §6.2.
//  OR-K. collectForecastTraceEvents + sortEventsChronologically на своём
//        корпусе: стабильность равных ts, битые ts в конец, чужие типы.
//  OR-L. stageLabel -- единый источник с навигацией (STAGE_DEFS).

import {
  deriveNodeStatuses,
  foldNodeStatuses,
  stageSummary,
  stageLabel,
  sortEventsChronologically,
  collectForecastTraceEvents,
  type TraceEventInfo,
} from "../../packages/ui/lib/progress";
import { STAGE_DEFS } from "../../packages/ui/lib/stages";
import fixture from "./progr4cert_fold_fixture.json";

const ev = (o: Partial<TraceEventInfo>): TraceEventInfo => ({
  event_id: "cert-" + Math.random().toString(36).slice(2, 8),
  run_id: "RUN-CERT025",
  ts: "2026-09-25T06:00:00+00:00",
  stage: "validation",
  node_id: "formats",
  event_type: "correction_applied",
  payload: {},
  actor: "user",
  ...o,
});

// OR-H. Кросс-языковой fixture: 2800 комбинаций против живого Python.
describe("OR-H foldNodeStatuses vs живой fold_status_values (2800 комбинаций)", () => {
  it("каждая строка fixture совпадает с TS-портом", () => {
    const rows = fixture.rows as Array<{ statuses: string[]; fold: string }>;
    expect(rows).toHaveLength(2800);
    for (const row of rows) {
      expect(foldNodeStatuses(row.statuses)).toBe(row.fold);
    }
  });
});

// OR-I. Свой корпус deriveNodeStatuses.
describe("OR-I deriveNodeStatuses (свой корпус)", () => {
  it("I1 последнее событие узла выигрывает: applied -> previewed (деградация до warning)", () => {
    const statuses = deriveNodeStatuses([
      ev({ stage: "preprocessing", node_id: "smoothing", event_type: "correction_applied", ts: "t1" }),
      ev({ stage: "preprocessing", node_id: "smoothing", event_type: "correction_previewed", ts: "t2" }),
    ]);
    // НОВОЕ событие перезаписывает: после preview поверх applied узел warning.
    expect(statuses["preprocessing/smoothing"]).toBe("warning");
  });

  it("I2 коллизия id между стадиями: regularity валидации и предобработки независимы", () => {
    const statuses = deriveNodeStatuses([
      ev({ stage: "validation", node_id: "regularity", event_type: "correction_applied" }),
      ev({ stage: "preprocessing", node_id: "regularity", event_type: "correction_previewed" }),
    ]);
    expect(statuses["validation/regularity"]).toBe("done");
    expect(statuses["preprocessing/regularity"]).toBe("warning");
  });

  it("I3 узел чужой стадии не получает статус (stage-квалифицированный ключ)", () => {
    const statuses = deriveNodeStatuses([
      ev({ stage: "validation", node_id: "missing", event_type: "correction_applied" }),
    ]);
    // missing -- узел preprocessing, не validation: фантома нет.
    expect(statuses["validation/missing"]).toBeUndefined();
    expect(statuses["preprocessing/missing"]).toBeUndefined();
  });

  it("I4 stage-level события (node_id=null) и неизвестные типы -- мимо статусов", () => {
    const statuses = deriveNodeStatuses([
      ev({ node_id: null, event_type: "mode_changed" }),
      ev({ node_id: null, event_type: "passport_captured" }),
      ev({ event_type: "totally_unknown_type" }),
    ]);
    expect(statuses).toEqual({});
  });

  it("I5 forecasting-события из слияния дают done на своих узлах", () => {
    const statuses = deriveNodeStatuses([
      ev({ stage: "forecasting", node_id: "forecast_generated", event_type: "forecast_generated" }),
      ev({ stage: "forecasting", node_id: "forecast_compared", event_type: "forecast_compared" }),
    ]);
    expect(statuses["forecasting/forecast_generated"]).toBe("done");
    expect(statuses["forecasting/forecast_compared"]).toBe("done");
  });
});

// OR-J. stageSummary на своих текстах §6.2.
describe("OR-J stageSummary (свои тексты §6.2)", () => {
  it("J1 только preview: 0/N «найдены проблемы» (честный ноль done, N-1 worklog)", () => {
    const statuses = deriveNodeStatuses([
      ev({ stage: "validation", node_id: "data_types", event_type: "correction_previewed" }),
    ]);
    const s = stageSummary("validation", statuses);
    expect(s.text).toBe("0/10, найдены проблемы");
    expect(s.fold).toBe("attention");
    expect(s.doneCount).toBe(0);
  });

  it("J2 смешанное: 2/10 done + preview -- «2/10, найдены проблемы»", () => {
    const statuses = deriveNodeStatuses([
      ev({ stage: "validation", node_id: "data_types", event_type: "correction_applied" }),
      ev({ stage: "validation", node_id: "formats", event_type: "correction_applied" }),
      ev({ stage: "validation", node_id: "ranges", event_type: "correction_previewed" }),
    ]);
    expect(stageSummary("validation", statuses).text).toBe("2/10, найдены проблемы");
  });

  it("J3 моделирование 3/11 в работе (без warning)", () => {
    const statuses = deriveNodeStatuses([
      ev({ stage: "modeling", node_id: "backtest", event_type: "backtest_run" }),
      ev({ stage: "modeling", node_id: "tuning", event_type: "tuning_trial_completed" }),
      ev({ stage: "modeling", node_id: "selection", event_type: "model_selected" }),
      ev({ stage: "modeling", node_id: "diagnostics", event_type: "profile_viewed" }),
    ]);
    const s = stageSummary("modeling", statuses);
    expect(s.text).toBe("3/11, в работе");
    expect(s.fold).toBe("attention"); // running -> started -> attention
  });

  it("J4EDA: 1/10 -- узел correlation (свой узел общего JSON)", () => {
    const statuses = deriveNodeStatuses([
      ev({ stage: "eda", node_id: "correlation", event_type: "profile_viewed" }),
    ]);
    expect(stageSummary("eda", statuses).text).toBe("0/10, в работе");
  });

  it("J5 неизвестная стадия -- не начато, total 0 (fail-safe)", () => {
    const s = stageSummary("no_such_stage", {});
    expect(s.fold).toBe("not_started");
    expect(s.total).toBe(0);
  });
});

// OR-K. Слияние forecasting + хронология на своём корпусе.
describe("OR-K collect + sort (свой корпус)", () => {
  it("K1 слияние: канон 4 типов + пропуск чужих, ts из timestamp", () => {
    const events = collectForecastTraceEvents([
      { forecast_id: "f1", trace_events: [
        { event_type: "forecast_generated", timestamp: "2026-09-25T07:00:00+00:00" },
        { event_type: "forecast_exported", timestamp: "2026-09-25T07:30:00+00:00" },
      ] },
      { forecast_id: "f2", trace_events: [
        { event_type: "foreign_type", timestamp: "2026-09-25T08:00:00+00:00" },
        { event_type: "forecast_sensitivity_computed", timestamp: "2026-09-25T08:15:00+00:00" },
      ] },
    ]);
    expect(events).toHaveLength(3);
    expect(events.map((e) => e.node_id)).toEqual([
      "forecast_generated", "forecast_exported", "forecast_sensitivity_computed",
    ]);
    expect(events.every((e) => e.stage === "forecasting")).toBe(true);
  });

  it("K2 хронология: равные ts сохраняют взаимный порядок (стабильность)", () => {
    const a = ev({ ts: "2026-09-25T07:00:00+00:00", event_type: "correction_previewed" });
    const b = ev({ ts: "2026-09-25T07:00:00+00:00", event_type: "correction_applied" });
    const sorted = sortEventsChronologically([b, a]);
    expect(sorted[0]).toBe(b); // вошёл раньше -- вышел раньше
    expect(sorted[1]).toBe(a);
  });

  it("K3 битые ts -- в конец, не в начало", () => {
    const good = ev({ ts: "2026-09-25T07:00:00+00:00" });
    const bad = ev({ ts: "мусор" });
    const sorted = sortEventsChronologically([bad, good]);
    expect(sorted.map((e) => e.ts)).toEqual(["2026-09-25T07:00:00+00:00", "мусор"]);
  });

  it("K4 слияние слоя 1 и forecasting: перемежается по ts, не блоками", () => {
    const layer1 = [
      ev({ ts: "2026-09-25T06:00:00+00:00", stage: "upload", node_id: "structure_confirmed", event_type: "upload_completed" }),
      ev({ ts: "2026-09-25T09:00:00+00:00", stage: "modeling", node_id: "backtest", event_type: "backtest_run" }),
    ];
    const forecast = collectForecastTraceEvents([
      { forecast_id: "f1", trace_events: [
        { event_type: "forecast_generated", timestamp: "2026-09-25T07:30:00+00:00" },
      ] },
    ]);
    const merged = sortEventsChronologically([...layer1, ...forecast]);
    expect(merged.map((e) => e.event_type)).toEqual([
      "upload_completed", "forecast_generated", "backtest_run",
    ]);
  });
});

// OR-L. stageLabel -- единый источник с навигацией.
describe("OR-L stageLabel", () => {
  it("L1 все 6 стадий из STAGE_DEFS, порядок блок-схемы = порядок меню", () => {
    expect(STAGE_DEFS.map((s) => s.key)).toEqual([
      "upload", "validation", "preprocessing", "eda", "modeling", "forecasting",
    ]);
    for (const s of STAGE_DEFS) {
      expect(stageLabel(s.key)).toBe(s.label);
    }
  });
  it("L2 неизвестная стадия -- сырой id (честный фоллбек)", () => {
    expect(stageLabel("mystery")).toBe("mystery");
  });
});
