// apps/print-renderer/src/smokeScenarios.ts
//
// PGV-08 — Sandboxed renderer container: смоук-сценарии финального
// контейнера (критерий §13 «Final image smoke кириллица/IH/A4»).
//
// Три сценария на своих данных (прецедент серии CERT):
//   S1 «кириллица» — figure-landscape 2400×1500: карточки/таблица с
//      русскими подписями (заголовок/подзаголовок/мета §7);
//   S2 «IH»        — a4-landscape 3508×2480: PrintIhConditionalMatrix
//      (все bins, проценты, знаменатели, правило 100 %, шкала — AC02);
//   S3 «A4»        — a4-portrait 2480×3508: пропорция A4 (AC16).
//
// Проверки структуры PNG — байт-уровнем (parsePngChunks), без растровых
// библиотек: сигнатура, IHDR == px профиля, pHYs 11811 (300 ppi),
// непустой IDAT, различимость хэшей. Пиксельная приёмка (чернила/OCR/
// цвета) — scripts/pgv08/verify_local.py вне контейнера (Pillow/tesseract).

import { createHash } from "node:crypto";

import {
  parsePngChunks,
  RENDER_PAYLOAD_SCHEMA_VERSION,
  type RenderPagePayload,
} from "./rendererCore";
import type { VisualPrintSnapshotV1 } from "../../../packages/ui/print/printSchema";
import type { PrintRenderWorker } from "./renderWorker";

// ── Сборка сценариев (свой ряд: известные counts/rates/bins) ──────

function baseSnapshot(profileId: VisualPrintSnapshotV1["print"]["profile_id"]): VisualPrintSnapshotV1 {
  return {
    schema_version: "pgv.visual_print_snapshot/1",
    view_id: "smoke.pgv08.container",
    scope: "demo",
    refs: { demo_dataset_id: "smoke-demo-0001" },
    result: {
      result_ref: "vr-smoke0800000001",
      result_schema_version: "pgv.visual_result/1",
      result_digest: "smoke",
      result_digest_reason: null,
    },
    data_artifact: {
      artifact_id: null,
      artifact_version: "smoke-v1",
      source_hash: null,
      hash_algorithm: null,
      hash_reason: "smoke-фикстура без durable-источника",
    },
    expected_context: { context_id: null, data_revision: null, expected_data_digest: null },
    dimensions: {
      target_column: "Оборот розничной торговли",
      date_column: "Месяц",
      entity_column: null,
      entity_id: null,
      mode: "univariate",
    },
    times: {
      computed_at: "2026-10-29T10:00:00+00:00",
      computed_at_reason: null,
      captured_at: "2026-10-29T10:05:00+00:00",
      captured_at_reason: null,
      checkpoint_confirmed_at: null,
      render_requested_at: null,
      timezone: "UTC",
      locale: "ru-RU",
    },
    checkpoint: null,
    display: {
      title: "Смоук рендер-контейнера: кириллица, IH, A4",
      subtitle: "PGV-08 — финальный образ: шрифты/бандл/браузер",
      detail_level: "compact",
      sections: [],
    },
    method: { origin: "producer_freeze", method: "smoke", parameters: { suite: "pgv08" } },
    selection: { allowlist: [], values: {} },
    sampling: { applicable: true, mode: "full", point_cap: null, reason: null },
    annotations: { revision: 0, author: "analyst", text: null },
    print: { profile_id: profileId, page_count: 1, theme: "light-print" },
    renderer_env: {
      renderer_version: "print-renderer/1",
      font_profile: "print-fonts-dejavu/1",
      dependency_status: "available",
      unavailable_reason: null,
    },
    data_flow: { before_revision: null, after_revision: null },
    sensitive: { raw_data_included: false, sensitive_fields_policy: "metadata_only" },
    warnings: ["Смоук-сценарий: данные фиксированные, известные counts/rates/bins."],
  };
}

/** S1 «кириллица»: карточки + таблица с русскими подписями (2400×1500). */
export function cyrillicScenario(): RenderPagePayload {
  return {
    schema_version: RENDER_PAYLOAD_SCHEMA_VERSION,
    request_id: "smoke-cyrillic",
    snapshot: baseSnapshot("figure-landscape"),
    sections: [
      {
        section_id: "smoke-cards",
        kind: "html_cards",
        title: "Ключевые показатели (кириллица)",
        cards: [
          { label: "Наблюдений", value: "9 876", unit: { value: "набл.", reason: null } },
          { label: "Пропусков", value: "12", unit: { value: null, reason: "dimensionless" } },
          { label: "Среднее", value: "1 234,5", unit: { value: "млрд руб.", reason: null } },
        ],
      },
      {
        section_id: "smoke-table",
        kind: "html_table",
        title: "Оборот розничной торговли по месяцам",
        headings: { row: ["Месяц", "Оборот", "Доля"], column: [] },
        rows: [
          ["Январь 2026", "1 050,2", "33,3 %"],
          ["Февраль 2026", "1 100,5", "66,7 %"],
        ],
        units: [{ value: "млрд руб.", reason: null }],
        caption: "Смоук-таблица кириллицы: длинные русские подписи, ЁёЙй Ѫѫ пример",
      },
    ],
    options: {},
  };
}

/** S2 «IH»: условная матрица IH со шкалой 0–100 % (3508×2480). */
export function ihScenario(): RenderPagePayload {
  return {
    schema_version: RENDER_PAYLOAD_SCHEMA_VERSION,
    request_id: "smoke-ih",
    snapshot: baseSnapshot("a4-landscape"),
    sections: [
      {
        section_id: "smoke-ih",
        kind: "ih_conditional",
        title: "Условное распределение цели по интервалам фактора (IH)",
        ih_input: {
          feature_label: "Инвестиции в основной капитал",
          target_label: "Оборот розничной торговли",
          x_bins: ["[0; 100)", "[100; 250)", "[250; ∞)"],
          y_bins: ["низкая", "средняя", "высокая"],
          rows: [
            { x_bin: "[0; 100)", values: [60, 30, 10] },
            { x_bin: "[100; 250)", values: [25, 50, 25] },
            { x_bin: "[250; ∞)", values: [10, 20, 70] },
          ],
          n_observations: 9876,
          row_totals: [100, 200, 300],
          denominator_note: null,
        },
      },
    ],
    options: {},
  };
}

/** S3 «A4»: портретный лист с таблицей (2480×3508, пропорция 210/297). */
export function a4Scenario(): RenderPagePayload {
  return {
    schema_version: RENDER_PAYLOAD_SCHEMA_VERSION,
    request_id: "smoke-a4",
    snapshot: baseSnapshot("a4-portrait"),
    sections: [
      {
        section_id: "smoke-a4-table",
        kind: "html_table",
        title: "Лист A4 (книжная ориентация)",
        headings: { row: ["Показатель", "Значение"], column: [] },
        rows: [
          ["Ширина листа, мм", "210"],
          ["Высота листа, мм", "297"],
          ["Разрешение, ppi", "300"],
        ],
        units: [],
      },
    ],
    options: {},
  };
}

// ── Проверки и отчёт ──────────────────────────────────────────────

export interface SmokeScenarioReport {
  scenario: string;
  profile_id: string;
  expected_width: number;
  expected_height: number;
  actual_width: number;
  actual_height: number;
  phys_ppu: number | null;
  idat_bytes: number;
  sha256: string;
  checks: Record<string, boolean>;
  duration_ms: number;
  error: string | null;
}

export interface SmokeReport {
  verdict: "passed" | "failed";
  renderer_version: string;
  scenarios: SmokeScenarioReport[];
  checks: { cyrillic: boolean; ih: boolean; a4: boolean; distinct_hashes: boolean };
  error: string | null;
}

const EXPECTED_GEOMETRY: Record<string, { width: number; height: number; ppi: number }> = {
  "figure-landscape": { width: 2400, height: 1500, ppi: 300 },
  "a4-portrait": { width: 2480, height: 3508, ppi: 300 },
  "a4-landscape": { width: 3508, height: 2480, ppi: 300 },
};

/** Минимальный IDAT: страница с контентом не может быть почти пустой. */
const MIN_IDAT_BYTES = 2000;

async function runScenario(
  worker: Pick<PrintRenderWorker, "renderPayload">,
  name: string,
  payload: RenderPagePayload,
): Promise<SmokeScenarioReport> {
  const startedAt = Date.now();
  const profileId = payload.snapshot.print.profile_id;
  const expected = EXPECTED_GEOMETRY[profileId];
  try {
    const outcome = await worker.renderPayload(payload, 1, 1);
    const info = parsePngChunks(outcome.png);
    const checks: Record<string, boolean> = {
      png_signature: true, // parsePngChunks бросил бы иначе
      dimensions: info.width === expected.width && info.height === expected.height,
      phys_300ppi: info.hasPhys && info.physPpuX === 11811 && info.physPpuY === 11811,
      non_empty_idat: info.idatBytes >= MIN_IDAT_BYTES,
      non_trivial_bytes: outcome.png.length > MIN_IDAT_BYTES,
    };
    return {
      scenario: name,
      profile_id: profileId,
      expected_width: expected.width,
      expected_height: expected.height,
      actual_width: info.width,
      actual_height: info.height,
      phys_ppu: info.physPpuX,
      idat_bytes: info.idatBytes,
      sha256: createHash("sha256").update(outcome.png).digest("hex"),
      checks,
      duration_ms: Date.now() - startedAt,
      error: null,
    };
  } catch (error) {
    return {
      scenario: name,
      profile_id: profileId,
      expected_width: expected.width,
      expected_height: expected.height,
      actual_width: 0,
      actual_height: 0,
      phys_ppu: null,
      idat_bytes: 0,
      sha256: "",
      checks: { rendered: false },
      duration_ms: Date.now() - startedAt,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

/** Полный смоук (кириллица/IH/A4): /v1/smoke и entrypoint контейнера.
 *  Последовательно: смоук — детерминизм, а не производительность
 *  (max_concurrent контейнера не должен влиять на вердикт смоука). */
export async function runFullSmoke(
  worker: Pick<PrintRenderWorker, "renderPayload">,
): Promise<SmokeReport> {
  const cyrillic = await runScenario(worker, "cyrillic", cyrillicScenario());
  const ih = await runScenario(worker, "ih", ihScenario());
  const a4 = await runScenario(worker, "a4", a4Scenario());
  const scenarios = [cyrillic, ih, a4];
  const hashes = scenarios.filter((s) => s.sha256).map((s) => s.sha256);
  const distinct = new Set(hashes).size === 3;
  const checks = {
    cyrillic: Object.values(cyrillic.checks).every(Boolean) && cyrillic.error === null,
    ih: Object.values(ih.checks).every(Boolean) && ih.error === null,
    a4: Object.values(a4.checks).every(Boolean) && a4.error === null,
    distinct_hashes: distinct,
  };
  const verdict = Object.values(checks).every(Boolean) ? "passed" : "failed";
  return {
    verdict,
    renderer_version: "print-renderer/1",
    scenarios,
    checks,
    error: verdict === "passed" ? null : "не все смоук-сценарии прошли",
  };
}

/** Быстрый probe readiness: мини-рендер кириллицы (scale=0.05). */
export async function runProbeSmoke(
  worker: Pick<PrintRenderWorker, "renderPayload">,
): Promise<{ verdict: "passed" | "failed"; scenario: string; error: string | null }> {
  const payload = cyrillicScenario();
  payload.request_id = "probe-cyrillic";
  payload.options = { scale: 0.05 };
  try {
    const outcome = await worker.renderPayload(payload, 1, 1);
    const info = parsePngChunks(outcome.png);
    // Мини-рендер: геометрия = px профиля × scale (округление), pHYs честен.
    const expectedW = Math.round(2400 * 0.05);
    const expectedH = Math.round(1500 * 0.05);
    const ok =
      info.width === expectedW &&
      info.height === expectedH &&
      info.hasPhys &&
      info.physPpuX === 11811 &&
      info.idatBytes > 100;
    return { verdict: ok ? "passed" : "failed", scenario: "probe-cyrillic", error: ok ? null : "структура мини-рендера не сошлась" };
  } catch (error) {
    return {
      verdict: "failed",
      scenario: "probe-cyrillic",
      error: error instanceof Error ? error.message : String(error),
    };
  }
}
