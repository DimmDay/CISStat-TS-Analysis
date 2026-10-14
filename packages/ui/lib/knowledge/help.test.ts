// packages/ui/lib/knowledge/help.test.ts
//
// Task EDU-HELP-1 (Шаг 3, ревизия 2026-09-22 spec_education.md §2.1/§13,
// docs/education_knowledge_base_architecture.md §3 п.7) — инварианты реестра
// контекстной справки и адаптера describeNode(...).
//
// Постановка тимлида: миграция контента справки в единый реестр — источник
// истины; секции окна «Описание» (metrics/pipeline/module_help) рендерят
// статью по (stage_id, node_id, facet) через describeNode(...); БЕЗ
// ContextHelpButton и новых панелей на узлах — окно «Описание» остаётся
// единственной справочной поверхностью узла, дублирование исключено;
// паритет-снапшоты байт-в-байт.
//
// Ключевые контракты:
//   - паритет: текст каждой записи реестра === текст мигрированной константы
//     (help-parity.fixture.json — оракул, снятый с кода до миграции);
//   - покрытие двунаправленное: реестр покрывает РОВНО ключи фиксстуры
//     (ни одной утерянной и ни одной лишней записи; нативные записи —
//     созданные прямо в реестре без константы-предшественника — входят в
//     фиксстуру с superseded_constant: null и пинятся отдельным тестом);
//   - UI-UPLOAD-HELP-1 (2026-10-14, постановка тимлида): кнопка «Справка»
//     заголовка колонки «Загрузка» рендерит развёрнутое описание модуля из
//     реестра (upload.module.module_help, нативная запись) — описание
//     написано В РЕЕСТРЕ (единый источник методологий/описаний), константы
//     в TsAnalysisUpload.tsx нет и быть не должно (греп-инвариант ниже).
//   - ключ (stage_id, node_id, facet) уникален, entry_id уникален;
//   - честный промах: несуществующий ключ → null (no fabricated results);
//   - superseded_constant — аудит происхождения («файл::КОНСТАНТА»);
//   - греп-инвариант: в TsAnalysis*.tsx нет методологических строковых
//     констант справки — второй источник текстов не существует по построению.

import { readFileSync } from "fs";
import { join } from "path";
import { KNOWLEDGE_STAGES } from "./types";
import { KNOWLEDGE_HELP_ENTRIES, describeNode } from "./knowledge";
import type { KnowledgeHelpEntry, KnowledgeHelpFacet } from "./types";

interface FixtureEntry {
  entry_id: string;
  stage_id: string;
  node_id: string | null;
  facet: string;
  superseded_constant: string | null; // null — нативная запись реестра (§1.1 spec_education.md: str | None)
  text: string;
}

const fixture: FixtureEntry[] = JSON.parse(
  readFileSync(join(__dirname, "help-parity.fixture.json"), "utf-8"),
) as FixtureEntry[];

const registryKey = (e: { stage_id: string; node_id: string | null; facet: string }) =>
  `${e.stage_id}|${e.node_id ?? "module"}|${e.facet}`;

describe("EDU-HELP-1: реестр контекстной справки — источник истины (Шаг 3)", () => {
  test("фикстура-оракул: 77 мигрированных констант пяти модулей + нативная запись модуля «Загрузка» (UI-UPLOAD-HELP-1)", () => {
    expect(fixture).toHaveLength(78);
    const byStage: Record<string, number> = {};
    for (const f of fixture) byStage[f.stage_id] = (byStage[f.stage_id] ?? 0) + 1;
    expect(byStage).toEqual({
      validation: 21,
      preprocessing: 21,
      eda: 21,
      modeling: 12,
      forecasting: 2,
      upload: 1, // нативная запись upload.module.module_help — создана в реестре
    });
  });

  test("паритет байт-в-байт: каждый текст реестра === текст фиксстуры (мигрированной константы / нативной записи)", () => {
    for (const f of fixture) {
      const entry = describeNode(
        f.stage_id as never,
        f.node_id as never,
        f.facet as never,
      );
      expect(entry).not.toBeNull();
      expect((entry as KnowledgeHelpEntry).text).toBe(f.text);
    }
  });

  test("покрытие двунаправленное: ключи реестра === ключи фиксстуры (без дублей и лишних)", () => {
    const registryKeys = KNOWLEDGE_HELP_ENTRIES.map(registryKey).sort();
    const fixtureKeys = fixture.map(registryKey).sort();
    expect(new Set(registryKeys).size).toBe(registryKeys.length);
    expect(registryKeys).toEqual(fixtureKeys);
  });

  test("ключ (stage_id, node_id, facet) уникален и entry_id уникален", () => {
    const keys = KNOWLEDGE_HELP_ENTRIES.map(registryKey);
    expect(new Set(keys).size).toBe(keys.length);
    const ids = KNOWLEDGE_HELP_ENTRIES.map((e) => e.entry_id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  test("stage_id каждой записи — из словаря STAGES платформы (§1.1)", () => {
    for (const e of KNOWLEDGE_HELP_ENTRIES) {
      expect(KNOWLEDGE_STAGES).toContain(e.stage_id);
    }
  });

  test("контракт facet/node_id: metrics|pipeline — на узле; module_help — модульный (node_id=null)", () => {
    for (const e of KNOWLEDGE_HELP_ENTRIES) {
      if (e.facet === "metrics" || e.facet === "pipeline") {
        expect(e.node_id).not.toBeNull();
      }
      if (e.facet === "module_help") {
        expect(e.node_id).toBeNull();
      }
    }
  });

  test("модульная справка (module_help) есть у всех шести реализованных этапов, включая «Загрузку»", () => {
    for (const stage of ["upload", "validation", "preprocessing", "eda", "modeling", "forecasting"] as const) {
      expect(describeNode(stage, null, "module_help")).not.toBeNull();
    }
  });

  test("нативная запись upload.module.module_help содержательно наполнена (остановки, выходы, анонс Валидации)", () => {
    const entry = describeNode("upload", null, "module_help");
    expect(entry).not.toBeNull();
    const text = (entry as KnowledgeHelpEntry).text;
    // Структура следует паттерну module_help остальных модулей (Цели → выходы → пайплайн).
    expect(text).toContain("Цели модуля");
    // Все 5 остановок степпера названы (реестр upload_stops.json).
    for (const stop of ["Обзор", "График", "Распределение", "Структура", "Качество"]) {
      expect(text).toContain(stop);
    }
    // Развёрнутое описание: выходы модуля + честный анонс следующего этапа.
    expect(text).toContain("Исследуемый признак");
    expect(text).toContain("Валидация");
    expect(text.length).toBeGreaterThan(1200);
  });

  test("stage_overview: Моделирование покрывает 11 стадий графа, Прогнозирование — этап целиком", () => {
    const modelingStages = KNOWLEDGE_HELP_ENTRIES.filter(
      (e) => e.stage_id === "modeling" && e.facet === "stage_overview",
    ).map((e) => e.node_id);
    expect(modelingStages).toHaveLength(11);
    expect(modelingStages).toContain("problem_definition");
    expect(describeNode("forecasting", null, "stage_overview")).not.toBeNull();
  });

  test("честный промах: несуществующий ключ → null (no fabricated results)", () => {
    expect(describeNode("validation", "nonexistent_check", "metrics")).toBeNull();
    expect(describeNode("eda", "descriptive", "module_help")).toBeNull();
    expect(describeNode("upload", "anything", "metrics" as KnowledgeHelpFacet)).toBeNull();
    // module_help — модульная грань (node_id=null): узлового ключа у «Загрузки» нет.
    expect(describeNode("upload", "overview", "module_help")).toBeNull();
  });

  test("superseded_constant — аудит происхождения: мигрированные «Файл::КОНСТАНТА», нативные — null (набор запинен)", () => {
    // Нативные записи (созданы прямо в реестре, константы-предшественника
    // не существовало) — честный null, а не вымышленная ссылка (§1.1:
    // str | None). Набор нативных записей запинен явно.
    const native = KNOWLEDGE_HELP_ENTRIES.filter((e) => e.superseded_constant === null).map((e) => e.entry_id);
    expect(native).toEqual(["upload.module.module_help"]);
    for (const e of KNOWLEDGE_HELP_ENTRIES) {
      if (e.superseded_constant !== null) {
        expect(e.superseded_constant).toMatch(/^TsAnalysis[A-Za-z]+\.tsx::[A-Za-z_0-9.]+$/);
      }
    }
  });

  test("греп-инвариант: в TsAnalysis*.tsx больше нет строковых констант справки (один источник — реестр)", () => {
    const componentsDir = join(__dirname, "..", "..", "components");
    const files = [
      "TsAnalysisUpload.tsx",
      "TsAnalysisValidation.tsx",
      "TsAnalysisPreprocessing.tsx",
      "TsAnalysisEDA.tsx",
      "TsAnalysisModeling.tsx",
      "TsAnalysisForecasting.tsx",
    ];
    const forbidden = [
      /const [A-Z_0-9]+_(METRICS_DESCRIPTION|PIPELINE_DESCRIPTION|HELP) = `/,
      /const FORECASTING_DESCRIPTION = `/,
      /const MODELING_STAGE_DESCRIPTIONS[:\s]/,
    ];
    for (const file of files) {
      const src = readFileSync(join(componentsDir, file), "utf-8");
      for (const pattern of forbidden) {
        expect(pattern.test(src)).toBe(false);
      }
    }
  });
});
