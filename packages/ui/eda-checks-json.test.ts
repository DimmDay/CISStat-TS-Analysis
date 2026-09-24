// packages/ui/eda-checks-json.test.ts
// Task PROGR-2 -- §12 п.2: общий JSON реестра остановок EDA
// (shared/pipeline_nodes/eda_checks.json) -- единственный источник
// id/label/description для TsAnalysisEDA.tsx и app/core/pipeline_graph.py.
// Тесты страхуют синхронизацию на стороне фронтенда.
import fs from "fs";
import path from "path";
import edaChecksJson from "../../shared/pipeline_nodes/eda_checks.json";

const REPO_ROOT = path.resolve(__dirname, "../..");
const EDA_TSX_PATH = path.join(REPO_ROOT, "packages/ui/components/TsAnalysisEDA.tsx");

// spec_progress.md §2 -- проверенный по коду реестр вкладки «Разведочный EDA».
const EXPECTED_IDS = [
  "descriptive", "correlation", "ih_analysis", "seasonality",
  "stationarity", "distribution", "structural", "feature_select",
  "validation_strategy", "model_matrix",
];

describe("§12 п.2 -- общий JSON реестра EDA", () => {
  it("содержит ровно 10 остановок в порядке степпера", () => {
    expect(edaChecksJson.stage).toBe("eda");
    expect(edaChecksJson.nodes.map((n) => n.id)).toEqual(EXPECTED_IDS);
  });

  it("каждая остановка имеет непустые label и description", () => {
    for (const node of edaChecksJson.nodes) {
      expect(node.label.trim()).not.toBe("");
      expect(node.description.trim()).not.toBe("");
    }
  });

  it("TsAnalysisEDA.tsx импортирует общий JSON, а не держит вшитый список", () => {
    const src = fs.readFileSync(EDA_TSX_PATH, "utf-8");
    expect(src).toContain("shared/pipeline_nodes/eda_checks.json");
    // Вшитого литерала больше нет: записи вида `{ id: "descriptive", label:`
    // в компоненте не встречаются.
    expect(src).not.toMatch(/\{\s*id:\s*"descriptive",\s*label:/);
  });

  it("каждому id из JSON соответствует ветка рантайм-маппинга статуса", () => {
    const src = fs.readFileSync(EDA_TSX_PATH, "utf-8");
    for (const node of edaChecksJson.nodes) {
      expect(src).toContain(`check.id === "${node.id}"`);
    }
  });
});
