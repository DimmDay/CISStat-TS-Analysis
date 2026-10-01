// scripts/audit_scripts/progr4cert_oracles.test.ts
//
// Task PROGR-4-CERT (2026-09-25) -- независимые оракул-тесты аудитора на
// СВОИх данных (не копия packages/ui/lib/progress.test.ts).
//
// ПЕРЕСМОТР (Task PROGR-10, 2026-09-29, Расхождение №1): фронтенд-движок
// статусов удалён -- вывод статуса из фактов решений живёт в ЕДИНОМ
// движке бэкенда app/core/node_status.py (панель рендерит готовое
// состояние /trace, не вычисляет). Оракулы удалённого поведения сняты,
// живое поведение продолжают кейсы-эквиваленты:
//
//   OR-H (foldNodeStatuses, 2800 комбинаций fixture)      -- СНЯТ:
//        свёртка §12 п.10 теперь канонический fold_status_values на
//        бэкенде; эквиваленты -- test_node_status_engine.py
//        (TestDeriveStageStates) и Контур 1.1 test_progress_panel.py;
//   OR-I (deriveNodeStatuses I1-I5)                        -- СНЯТ:
//        эквиваленты -- test_node_status_engine.py (TestDeriveNodeStatuses);
//   OR-J (stageSummary J1-J5)                              -- СНЯТ:
//        тексты §6.2 собираются из готовых счётчиков
//        (stageStateText); эквиваленты -- progress.test.ts
//        (stageStateText) + Контур 1.1 (счётчики /trace);
//   OR-K1/K4 (collectForecastTraceEvents + слияние)        -- СНЯТЫ:
//        слияние слоя 1 с ForecastRun.trace -- серверное
//        (progress.py::_canonical_forecast_trace_events); эквивалент --
//        Контур 1.1 test_progress_panel.py (server-side merge);
//   OR-K2/K3 (sortEventsChronologically: стабильность равных ts,
//        битые ts в конец)                                 -- ЖИВЫ;
//   OR-L  (stageLabel -- единый источник с навигацией)     -- ЖИВ.
//
// Fixture progr4cert_fold_fixture.json и генератор
// progr4cert_gen_fold_fixture.py ОСТАВЛЕНЫ как артефакт сертификации
// PROGR-4-CERT (2800-комбинационная разметка живым Python 2026-09-25);
// импорт fixture из этого файла снят вместе с OR-H.

import {
  sortEventsChronologically,
  stageLabel,
  type TraceEventInfo,
} from "../../packages/ui/lib/progress";
import { STAGE_DEFS } from "../../packages/ui/lib/stages";

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

// OR-K (живые кейсы). Хронология на своём корпусе.
describe("OR-K sort (живые кейсы после пересмотра PROGR-10)", () => {
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
