// packages/ui/lib/progress.test.ts
//
// Тесты чистой логики панели «Прогресс» (Task PROGR-4, spec_progress.md
// §3 + §12 п.10 + аддендум §4.1-4.2; Расхождение №1 -- Task PROGR-10):
// реестр узлов (sync с графом бэкенда), сборка подписи карточки §6.2 из
// ГОТОВЫХ счётчиков ответа /trace, метки статусов запуска, якорь
// чекпоинта, хронология.
//
// PROGR-10: вывод статуса из фактов решений и свёртка §12 п.10
// вычисляются НА БЭКЕНДЕ (единый движок app/core/node_status.py для
// панели/Наставника/admin-аналитики); фронтенд рендерит, не вычисляет.
// Тесты удалённого фронтенд-движка (deriveNodeStatuses /
// foldNodeStatuses / stageSummary / collectForecastTraceEvents) сняты
// -- кейсы-эквиваленты живут в tests/api/test_node_status_engine.py и
// Контуре 1.1 tests/api/test_progress_panel.py. Оракулы сертификации
// PROGR-4-CERT пересмотрены (scripts/audit_scripts/
// progr4cert_oracles.test.ts, шапка фиксирует пересмотр).

import {
  PROGRESS_STAGE_NODES,
  nodeLabel,
  stageStateText,
  stageLabel,
  sortEventsChronologically,
  runStatusLabel,
  lastCheckpointableEvent,
  type StageStateInfo,
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

const stage = (overrides: Partial<StageStateInfo>): StageStateInfo => ({
  stage: "validation",
  fold: "not_started",
  done_count: 0,
  warning_nodes: 0,
  total_nodes: 10,
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
    for (const [stageKey, nodes] of Object.entries(PROGRESS_STAGE_NODES)) {
      for (const nodeId of nodes) {
        const label = nodeLabel(stageKey, nodeId);
        expect(label).toBeTruthy();
        expect(label).not.toBe(nodeId); // метка, а не сырой id
      }
    }
  });

  it("неизвестный узел отдаёт сырой id как честный фоллбек", () => {
    expect(nodeLabel("validation", "no_such_node")).toBe("no_such_node");
  });
});

describe("stageStateText (подпись карточки §6.2 из ГОТОВЫХ счётчиков, PROGR-10)", () => {
  it("not_started -> «не начато» (счётчики не показываются)", () => {
    expect(stageStateText(stage({ fold: "not_started" }))).toBe("не начато");
  });

  it("passed -> «N/N, пройдено»", () => {
    expect(
      stageStateText(stage({ stage: "upload", fold: "passed", done_count: 1, total_nodes: 1 })),
    ).toBe("1/1, пройдено");
  });

  it("attention с warning_nodes > 0 -> «N/total, найдены проблемы»", () => {
    expect(
      stageStateText(stage({ fold: "attention", done_count: 1, warning_nodes: 1 })),
    ).toBe("1/10, найдены проблемы");
    // Честный ноль done при наличии найденных проблем (§6.2).
    expect(
      stageStateText(stage({ fold: "attention", done_count: 0, warning_nodes: 1 })),
    ).toBe("0/10, найдены проблемы");
  });

  it("attention без warning (running) -> «N/total, в работе»", () => {
    expect(
      stageStateText(stage({ stage: "modeling", fold: "attention", done_count: 3, total_nodes: 11 })),
    ).toBe("3/11, в работе");
  });
});

describe("runStatusLabel (бейдж статуса запуска, §5/§5.2)", () => {
  it("четыре канонических статуса §5 имеют человекочитаемые метки", () => {
    expect(runStatusLabel("active")).toBe("В работе");
    expect(runStatusLabel("paused")).toBe("На паузе");
    expect(runStatusLabel("completed")).toBe("Завершён");
    expect(runStatusLabel("abandoned")).toBe("Брошен");
  });

  it("неизвестный статус возвращается как есть (честный текст, не маскировка)", () => {
    expect(runStatusLabel("future_status")).toBe("future_status");
    expect(runStatusLabel("")).toBe("");
  });
});

describe("lastCheckpointableEvent (якорь чекпоинта, §5.1)", () => {
  it("берёт ПОСЛЕДНЕЕ в хронологии событие с непустым event_id", () => {
    const first = ev({ event_id: "e-1", ts: "2026-09-25T10:00:00+00:00" });
    const middle = ev({ event_id: "e-2", ts: "2026-09-25T10:01:00+00:00", event_type: "profile_viewed" });
    const last = ev({ event_id: "e-3", ts: "2026-09-25T10:02:00+00:00" });
    expect(lastCheckpointableEvent([first, middle, last])).toBe(last);
  });

  it("события без event_id (legacy/канонизируемые ForecastRun.trace) не становятся якорями (§5.1 прежняя)", () => {
    const anchored = ev({ event_id: "e-1", ts: "2026-09-25T10:00:00+00:00" });
    // Сервер не выдумывает run_id/event_id канонизируемым событиям
    // артефакта (PROGR-10) -- приходят без идентификаторов.
    const forecast = ev({ event_id: undefined, ts: "2026-09-25T10:05:00+00:00", stage: "forecasting", node_id: "forecast_generated", event_type: "forecast_generated" });
    expect(lastCheckpointableEvent([anchored, forecast])).toBe(anchored);
  });

  it("нет ни одного события с event_id -- null (чекпоинт не к чему привязать)", () => {
    expect(lastCheckpointableEvent([])).toBeNull();
    expect(lastCheckpointableEvent([ev({ event_id: undefined })])).toBeNull();
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

  it("равные ts сохраняют взаимный порядок (стабильность, оракул K2)", () => {
    const a = ev({ ts: "2026-09-25T07:00:00+00:00", event_type: "correction_previewed" });
    const b = ev({ ts: "2026-09-25T07:00:00+00:00", event_type: "correction_applied" });
    const sorted = sortEventsChronologically([b, a]);
    expect(sorted[0]).toBe(b); // вошёл раньше -- вышел раньше
    expect(sorted[1]).toBe(a);
  });
});

describe("stageLabel (единый источник с навигацией, оракул OR-L)", () => {
  it("метки стадий -- из STAGE_DEFS (блок-схема не расходится с меню)", () => {
    for (const def of [
      { key: "upload", label: "Загрузка" },
      { key: "forecasting", label: "Прогнозирование" },
    ]) {
      expect(stageLabel(def.key)).toBe(def.label);
    }
    expect(stageLabel("mystery")).toBe("mystery"); // честный фоллбек
  });
});
