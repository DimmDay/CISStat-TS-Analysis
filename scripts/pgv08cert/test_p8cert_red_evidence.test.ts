/**
 * PGV-08-CERT — Class B: RED-свидетельства находок сертификации
 * (прецедент scripts/pgv07cert/test_p7cert_findings.test.tsx).
 *
 * Эти тесты ДОКУМЕНТИРУЮТ находки F-P8C4/F-P8C5/F-P8C6 и НА СЕГОДНЯШНЕЙ
 * поставке (main@3500775) ПАДАЮТ — это ожидаемое RED-состояние:
 * тест зелёный ⇔ находка устранена. В полный регресс вносятся как
 * «известные RED-свидетельства PGV-08-CERT» (честная арифметика —
 * в worklog-записи).
 *
 *   R1 (F-P8C4): политика запросов — blocklist, а не allowlist: схемы
 *      вне перечня (javascript:/chrome:/vbscript:) проходят shouldBlock,
 *      хотя собственный контракт реализации (rendererCore.tsx, докомментарий
 *      buildRequestPolicy) заявляет «разрешены только data: и about:blank»,
 *      а spec_documentation_logging §375 требует «allowlist sanitizer».
 *      Смягчения (JS-off, CSP, no-network) остаются — см. акт сертификации.
 *   R2 (F-P8C5): options.scale не ограничен лимитом 12 MP страницы
 *      (PRINT_LIMITS.max_megapixels_per_page, PGV-01 §7): payload с
 *      scale=10 проходит validateRenderPayload без нарушений, а рендер
 *      вышел бы за пиксельный лимит профиля (паритет кодов PGV-01 неполный).
 *   R3 (F-P8C6): знаменатели смоук-фикстуры IH несогласны:
 *      row_totals [100,200,300] = 600 ≠ n_observations 9 876 — смоук
 *      §13 печатает «Наблюдений: 9 876» и построчные знаменатели 100/200/300
 *      на одном листе (честность знаменателей AC02).
 */
import {
  buildRequestPolicy,
  validateRenderPayload,
  RENDER_PAYLOAD_SCHEMA_VERSION,
  type RenderPagePayload,
} from "../../apps/print-renderer/src/rendererCore";
import { ihScenario } from "../../apps/print-renderer/src/smokeScenarios";
import type { VisualPrintSnapshotV1 } from "../../packages/ui/print/printSchema";

function snapshot(): VisualPrintSnapshotV1 {
  return {
    schema_version: "pgv.visual_print_snapshot/1",
    view_id: "cert.pgv08.red_evidence",
    scope: "demo",
    refs: { context_id: "ctx-cert-08-red", data_revision: "rev-cert-2026-10-29" },
    result: {
      result_ref: "vr-cert08red000001",
      result_schema_version: "pgv.visual_result/1",
      result_digest: "red",
      result_digest_reason: null,
    },
    data_artifact: {
      artifact_id: null,
      artifact_version: "red-v1",
      source_hash: null,
      hash_algorithm: null,
      hash_reason: "RED-свидетельство без durable-источника",
    },
    expected_context: { context_id: null, data_revision: null, expected_data_digest: null },
    dimensions: {
      target_column: "Экспорт продукции",
      date_column: "Квартал",
      entity_column: null,
      entity_id: null,
      mode: "univariate",
    },
    times: {
      computed_at: "2026-10-29T08:00:00+00:00",
      computed_at_reason: null,
      captured_at: "2026-10-29T08:30:00+00:00",
      captured_at_reason: null,
      checkpoint_confirmed_at: null,
      render_requested_at: null,
      timezone: "UTC",
      locale: "ru-RU",
    },
    checkpoint: null,
    display: {
      title: "RED-свидетельство PGV-08-CERT",
      subtitle: "F-P8C4 / F-P8C5 — падает, пока находка не устранена",
      detail_level: "compact",
      sections: [],
    },
    method: { origin: "producer_freeze", method: "cert_red", parameters: {} },
    selection: { allowlist: [], values: {} },
    sampling: { applicable: true, mode: "full", point_cap: null, reason: null },
    annotations: { revision: 0, author: "analyst", text: null },
    print: { profile_id: "figure-landscape", page_count: 1, theme: "light-print" },
    renderer_env: {
      renderer_version: null,
      font_profile: null,
      dependency_status: "available",
      unavailable_reason: null,
    },
    data_flow: { before_revision: null, after_revision: null },
    sensitive: { raw_data_included: false, sensitive_fields_policy: "metadata_only" },
    warnings: [],
  };
}

describe("p8cert RED-свидетельства (падают, пока находки не устранены)", () => {
  it("R1 / F-P8C4: не-перечисленные схемы (javascript:/chrome:/vbscript:) обязаны блокироваться allowlist'ом", () => {
    const policy = buildRequestPolicy();
    // Собственный контракт реализации: «разрешены только data: и about:blank».
    // Фактически blocklist пропускает всё, что не начинается с перечисленных префиксов.
    expect(policy.shouldBlock("javascript:alert(1)")).toBe(true);
    expect(policy.shouldBlock("chrome://settings")).toBe(true);
    expect(policy.shouldBlock("vbscript:msgbox")).toBe(true);
  });

  it("R2 / F-P8C5: scale, выводящий рендер за 12 MP (PGV-01), обязан нарушать валидацию", () => {
    const payload: RenderPagePayload = {
      schema_version: RENDER_PAYLOAD_SCHEMA_VERSION,
      request_id: "cert-red-scale",
      snapshot: snapshot(),
      sections: [
        {
          section_id: "cert-red-table",
          kind: "html_table",
          headings: { row: ["Округ", "Объём"], column: [] },
          rows: [["Центральный ФО", "12 345"]],
        },
      ],
      // 2400×1500 px × scale 10 = 24000×15000 = 360 MP >> 12 MP каталога PGV-01.
      options: { scale: 10 },
    };
    const res = validateRenderPayload(payload);
    expect(res.violations.length).toBeGreaterThan(0);
  });

  it("R3 / F-P8C6: знаменатели смоук-фикстуры IH согласны (row_totals суммируются к n_observations)", () => {
    const payload = ihScenario();
    const ih = payload.sections[0];
    if (!ih || ih.kind !== "ih_conditional") throw new Error("ожидается ih_conditional");
    const sum = (ih.ih_input.row_totals ?? []).reduce((acc, v) => acc + (v ?? 0), 0);
    expect(sum).toBe(ih.ih_input.n_observations);
  });
});
