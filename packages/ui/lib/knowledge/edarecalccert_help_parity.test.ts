// packages/ui/lib/knowledge/edarecalccert_help_parity.test.ts
//
// НЕЗАВИСИМАЯ СЕРТИФИКАЦИЯ задачи EDA-RECALC-COMPENSATION (d0eb261; пункт
// ⑤ компенсирующего набора) — оракулы сертификатора, читающие ТРИ стороны
// реестра знаний напрямую:
//   1. packages/ui/lib/knowledge/help.ts (TS-реестр — источник истины);
//   2. packages/ui/lib/knowledge/help-parity.fixture.json (фикстура-оракул);
//   3. apps/api/knowledge/registry_data.json (backend-артефакт промоушена).
//
// Пинируемый контракт:
//   P1  семь pipeline-фасетов EDA (descriptive, correlation, distribution,
//       ih_analysis, seasonality, stationarity, structural) байт-в-байт
//       совпадают во всех трёх сторонах;
//   P2  ни одна запись этапа eda не упоминает удалённые кнопки
//       («Пересчитать…», «ручная кнопка»); семь pipeline-фасетов описывают
//       фактическую механику — «Повторить» при сбое и авто-перечитывание
//       при возврате во вкладку; три фасета, кнопку не описывавшие
//       (feature_select, validation_strategy, model_matrix), «Повторить»
//       не упоминают (не тронуты);
//   P3  состав реестра синхронен на трёх сторонах: 78 записей, одинаковые
//       наборы entry_id, нативная upload.module.module_help присутствует
//       во всех трёх сторонах с superseded_constant === null.

import { readFileSync } from "fs";
import * as path from "path";
import { KNOWLEDGE_HELP_ENTRIES } from "./help";

interface RegistryHelpEntry {
  entry_id: string;
  stage_id: string;
  node_id: string | null;
  facet: string;
  superseded_constant: string | null;
  text: string;
}

interface FixtureEntry {
  entry_id: string;
  stage_id: string;
  node_id: string | null;
  facet: string;
  text: string;
  superseded_constant: string | null;
}

const REPO_ROOT = path.join(__dirname, "..", "..", "..", "..");
const FIXTURE_PATH = path.join(__dirname, "help-parity.fixture.json");
const REGISTRY_PATH = path.join(REPO_ROOT, "apps", "api", "knowledge", "registry_data.json");

const fixture = JSON.parse(readFileSync(FIXTURE_PATH, "utf8")) as FixtureEntry[];
const registry = JSON.parse(readFileSync(REGISTRY_PATH, "utf8")) as {
  help_entries: RegistryHelpEntry[];
};

// Семь остановок, чья pipeline-справка описывала удалённую кнопку и была
// переведена на фактическую механику (EDA-RECALC-RESEARCH; d0eb261).
const UPDATED_PIPELINE_IDS = [
  "eda.descriptive.pipeline",
  "eda.correlation.pipeline",
  "eda.distribution.pipeline",
  "eda.ih_analysis.pipeline",
  "eda.seasonality.pipeline",
  "eda.stationarity.pipeline",
  "eda.structural.pipeline",
];

// Три остановки, кнопку не описывавшие, — вне правки ⑤.
const UNTOUCHED_PIPELINE_IDS = [
  "eda.feature_select.pipeline",
  "eda.validation_strategy.pipeline",
  "eda.model_matrix.pipeline",
];

const NATIVE_ENTRY_ID = "upload.module.module_help";

describe("edarecalccert — P1: семь EDA pipeline-текстов байт-в-байт на трёх сторонах", () => {
  it("help.ts === fixture === registry_data.json для каждой из 7 записей", () => {
    expect(UPDATED_PIPELINE_IDS).toHaveLength(7);
    for (const entryId of UPDATED_PIPELINE_IDS) {
      const fromTs = KNOWLEDGE_HELP_ENTRIES.find((e) => e.entry_id === entryId);
      const fromFixture = fixture.find((e) => e.entry_id === entryId);
      const fromRegistry = registry.help_entries.find((e) => e.entry_id === entryId);
      expect(`${entryId}: TS=${fromTs ? "found" : "missing"}`).toMatch(/: TS=found$/);
      expect(`${entryId}: fixture=${fromFixture ? "found" : "missing"}`).toMatch(/: fixture=found$/);
      expect(`${entryId}: registry=${fromRegistry ? "found" : "missing"}`).toMatch(/: registry=found$/);

      // Байт-паритет текста между всеми тремя сторонами (===, не toEqual:
      // любые расхождения нормализации — падение).
      expect(fromTs!.text === fromFixture!.text).toBe(true);
      expect(fromTs!.text === fromRegistry!.text).toBe(true);

      // Текст содержателен и описывает фактическую механику.
      expect(fromTs!.text.length).toBeGreaterThan(400);
      expect(fromTs!.text).toContain("Повторить");
      expect(fromTs!.text).toMatch(/возврат[аеу]? во вкладку|фокус/i);

      // Происхождение: мигрированные записи несут константу-предшественника
      // (в отличие от нативных, superseded_constant === null).
      expect(fromTs!.superseded_constant).toMatch(/^[A-Za-z0-9_.]+\.tsx::[A-Z0-9_]+$/);
    }
  });
});

describe("edarecalccert — P2: EDA-справка описывает фактическую механику, не кнопки", () => {
  it("ни одна запись этапа eda не упоминает «Пересчитать»/ручную кнопку", () => {
    const edaEntries = KNOWLEDGE_HELP_ENTRIES.filter((e) => e.stage_id === "eda");
    expect(edaEntries.length).toBeGreaterThan(0);
    for (const entry of edaEntries) {
      // Падение идентифицируется entry_id по индексу цикла (см. список ниже).
      expect(entry.text).not.toMatch(/Пересчитать|ручная кнопка|кнопка ручного обновления/);
    }
  });

  it("7 pipeline-фасетов упоминают «Повторить», 3 нетронутых — нет", () => {
    for (const entryId of UPDATED_PIPELINE_IDS) {
      const entry = KNOWLEDGE_HELP_ENTRIES.find((e) => e.entry_id === entryId);
      // Идентификация падения — entry_id в сообщении; литеральный поиск
      // (переводы строк внутри текста поиску «Повторить» не мешают).
      expect(`${entryId}: ${entry?.text ?? "<отсутствует>"}`).toContain("Повторить");
    }
    for (const entryId of UNTOUCHED_PIPELINE_IDS) {
      const entry = KNOWLEDGE_HELP_ENTRIES.find((e) => e.entry_id === entryId);
      expect(`${entryId}: ${entry ? "found" : "missing"}`).toMatch(/: found$/);
      expect(`${entryId}: ${entry!.text}`).not.toMatch(/Повторить/);
    }
  });
});

describe("edarecalccert — P3: состав реестра синхронен на трёх сторонах", () => {
  it("78 записей, идентичные наборы entry_id, нативная запись во всех трёх сторонах", () => {
    expect(KNOWLEDGE_HELP_ENTRIES).toHaveLength(78);
    expect(fixture).toHaveLength(78);
    expect(registry.help_entries).toHaveLength(78);

    const tsIds = KNOWLEDGE_HELP_ENTRIES.map((e) => e.entry_id);
    const fixtureIds = fixture.map((e) => e.entry_id);
    const registryIds = registry.help_entries.map((e) => e.entry_id);
    expect(fixtureIds).toEqual(tsIds);
    expect(registryIds).toEqual(tsIds);

    const nativeTs = KNOWLEDGE_HELP_ENTRIES.find((e) => e.entry_id === NATIVE_ENTRY_ID);
    const nativeFixture = fixture.find((e) => e.entry_id === NATIVE_ENTRY_ID);
    const nativeRegistry = registry.help_entries.find((e) => e.entry_id === NATIVE_ENTRY_ID);
    expect(nativeTs).toBeDefined();
    expect(nativeFixture).toBeDefined();
    expect(nativeRegistry).toBeDefined();
    expect(nativeTs!.superseded_constant).toBeNull();
    expect(nativeFixture!.superseded_constant).toBeNull();
    expect(nativeRegistry!.superseded_constant).toBeNull();
    expect(nativeTs!.text === nativeFixture!.text).toBe(true);
    expect(nativeTs!.text === nativeRegistry!.text).toBe(true);
  });
});
