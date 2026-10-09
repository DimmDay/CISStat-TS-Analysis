// packages/ui/lib/prograuditscert_anchor_oracle.test.ts
//
// PROGR-AUDIT-S-CERT (2026-10-10) — независимый оракул аудита задачи
// AUDIT-S на СВОИХ данных (дизъюнктен кейсам progress.test.ts
// разработчика: другие node_id/event_type/ids/ts). Пин §5.1 + §12.6
// контракта: после AUDIT-S якорь чекпоинта отсеивает forecasting-
// события артефактов по stage (идентичность у них теперь ЕСТЬ —
// стабильная, F11 исправлен), а не по отсутствию event_id.
import { lastCheckpointableEvent, type TraceEventInfo } from "./progress";

const evWind = (overrides: Partial<TraceEventInfo>): TraceEventInfo => ({
  event_id: "c-wind-anchor-01",
  run_id: "RUN-CERTS-W01",
  ts: "2026-03-15T08:30:00+00:00",
  stage: "validation",
  node_id: "sufficiency",
  event_type: "validation_check_status",
  payload: { source: "wind_station" },
  actor: "operator",
  ...overrides,
});

describe("AUDIT-S-CERT: lastCheckpointableEvent на данных аудита (wind_station)", () => {
  it("TS1: forecasting-событие артефакта СО стабильным id (c-wind-fc-77) — НЕ якорь (stage-фильтр, §5.1)", () => {
    const anchored = evWind({});
    const artifact = evWind({
      event_id: "c-wind-fc-77",
      ts: "2026-03-15T09:10:00+00:00",
      stage: "forecasting",
      node_id: "forecast_exported",
      event_type: "forecast_exported",
    });
    expect(lastCheckpointableEvent([anchored, artifact])).toBe(anchored);
    expect(lastCheckpointableEvent([artifact])).toBeNull();
  });

  it("TS2: не-forecasting событие с id — якорь; оба моих типа (validation_check_status/outliers_profile_status)", () => {
    const validation = evWind({
      ts: "2026-03-15T08:30:00+00:00",
      event_type: "validation_check_status",
    });
    const outliers = evWind({
      event_id: "c-wind-anchor-02",
      ts: "2026-03-15T09:40:00+00:00",
      stage: "preprocessing",
      node_id: "outliers",
      event_type: "outliers_profile_status",
    });
    expect(lastCheckpointableEvent([validation, outliers])).toBe(outliers);
  });

  it("TS3: смешанный корпус — последний в хронологии не-forecasting с id; legacy без id пропускается", () => {
    const legacy = evWind({
      event_id: undefined,
      ts: "2026-03-15T10:20:00+00:00",
      event_type: "mode_changed",
    });
    const candidate = evWind({
      ts: "2026-03-15T09:55:00+00:00",
      node_id: "formats",
      event_type: "validation_check_status",
    });
    // legacy ПОЗЖЕ кандидата по ts, но без id — якорем становится
    // последний ИДЕНТИФИЦИРОВАННЫЙ не-forecasting факт.
    expect(lastCheckpointableEvent([candidate, legacy])).toBe(candidate);
  });

  it("TS4: envelope-поля TraceEventInfo принимают значения аудита (аддитивность типа, v0.2-AUDIT-S §12)", () => {
    const stamped: TraceEventInfo = evWind({
      schema_version: 2,
      evidence_level: "client_observation",
      operation_id: "op-certs-w-9",
      time_quality: { quality: "degraded", raw_ts: "2026-03-15 08:30 wind", observed_at: "2026-03-15T08:30:01+00:00" },
    });
    expect(stamped.schema_version).toBe(2);
    expect(stamped.evidence_level).toBe("client_observation");
    expect(stamped.operation_id).toBe("op-certs-w-9");
    expect(stamped.time_quality?.quality).toBe("degraded");
    expect(lastCheckpointableEvent([stamped])).toBe(stamped);
  });
});
