// packages/ui/lib/visualExportRegistry.pgv11coverage.test.ts
//
// PGV-11 coverage-гвард (spec_passport_graphics_visual.md §13, строка
// PGV-11; паттерн гварда PGV-10): КАЖДЫЙ pgv-03 research view остановок
// EDA (16) и задач (tasks.causes.fold_importance -- 17 сайтов)
// монтирует «Скачать PNG» (VisualExportButton) в своей поверхности
// рендера. Статический скан исходников: view_id кнопки обязан входить
// в скоуп PGV-11 (чужой viewId -- ошибка), каждый сайт скоупа обязан
// быть вмонтирован (unknown site блокирует CERT -- §5). Сериализация
// -- СВОЙ chart-узел (serializeChartSvgSafe -- не первый SVG
// документа; контракт -- serializeChartSvg.test.ts).

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

interface VisualSiteRecord {
  view_id: string;
  module_id: string;
  renderer_kind: string;
  source_adapter: string;
  applicability: string;
}

const REPO_ROOT = resolve(__dirname, "../../..");
const REGISTRY_PATH = resolve(REPO_ROOT, "config/visual_registry.json");

function registrySites(): VisualSiteRecord[] {
  const raw = JSON.parse(readFileSync(REGISTRY_PATH, "utf-8")) as {
    sites: VisualSiteRecord[];
  };
  return raw.sites;
}

// Поверхности EDA/задач (PGV-11): один файл несёт один/несколько
// view_id кнопок (мультивидовые Обзоры -- кнопка следует активному
// представлению).
const SURFACE_FILES = [
  "EdaDescriptiveOverview.tsx",
  "EdaCorrelationOverview.tsx",
  "EdaIhOverview.tsx",
  "EdaSeasonalityOverview.tsx",
  "EdaStationarityOverview.tsx",
  "EdaDistributionOverview.tsx",
  "EdaStructuralBreaksOverview.tsx",
  "EdaFeatureSelectionOverview.tsx",
  "EdaValidationStrategyOverview.tsx",
  "EdaModelMatrixOverview.tsx",
  "TasksCauses.tsx",
];

function wiredViewIdsFromSources(): Map<string, string[]> {
  const found = new Map<string, string[]>();
  const componentsDir = resolve(__dirname, "../components");
  for (const file of SURFACE_FILES) {
    const src = readFileSync(resolve(componentsDir, file), "utf-8");
    const push = (viewId: string) => {
      const list = found.get(viewId) ?? [];
      list.push(file);
      found.set(viewId, list);
    };
    for (const match of src.matchAll(/viewId=\{?[`"]([a-z_.]+)[`"]/g)) {
      push(match[1]);
    }
    for (const match of src.matchAll(/viewId=\{`([a-z_.]+)\.\$\{[a-zA-Z]+\}`/g)) {
      push(`${match[1]}.`);
    }
    // Вычисляемый viewId (кнопка следует активному представлению --
    // тернарник в viewId={...}): собираем ВСЕ research-id вида
    // eda.* / tasks.* внутри блока.
    for (const block of src.matchAll(/viewId=\{([\s\S]*?)\}/g)) {
      for (const id of block[1].matchAll(/[a-z_]+\.[a-z_]+(?:\.[a-z_]+)+/g)) {
        if (id[0].startsWith("eda.") || id[0].startsWith("tasks.")) push(id[0]);
      }
    }
  }
  return found;
}

describe("PGV-11: «Скачать PNG» на всех render sites EDA и задач", () => {
  const sites = registrySites();
  const scope = sites.filter(
    (site) =>
      ["eda", "tasks"].includes(site.module_id) &&
      site.source_adapter.startsWith("pgv-03/") &&
      site.applicability !== "static_demo",
  );
  const wired = wiredViewIdsFromSources();

  it("каждый сайт скоупа (17) монтирует VisualExportButton", () => {
    expect(scope).toHaveLength(17);
    const missing = scope.filter((site) => !wired.has(site.view_id));
    expect(missing).toEqual([]);
  });

  it("паспорта EDA (pgv-04/13) НЕ монтируют кнопку (вне скоупа PGV-11)", () => {
    const passport = sites.filter((site) =>
      site.view_id.startsWith("eda.passport."),
    );
    expect(passport.length).toBe(2);
    for (const site of passport) {
      expect(wired.has(site.view_id)).toBe(false);
    }
  });

  it("viewId кнопок -- только сайты скоупа PGV-11 (чужой view -- ошибка)", () => {
    const scopeIds = new Set(scope.map((site) => site.view_id));
    const foreign = [...wired.keys()].filter(
      (viewId) => !viewId.endsWith(".") && !scopeIds.has(viewId),
    );
    expect(foreign).toEqual([]);
  });

  it("chart-сайты скоупа сериализуют СВОЙ узел (getScreenSvg по ref)", () => {
    const chartKinds = new Set(["recharts_svg", "mixed"]);
    const chartScope = scope.filter((site) => chartKinds.has(site.renderer_kind));
    expect(chartScope.length).toBeGreaterThan(0);
    for (const site of chartScope) {
      const files = wired.get(site.view_id) ?? [];
      const mounted = files.some((file) => {
        const src = readFileSync(resolve(__dirname, "../components", file), "utf-8");
        return (
          src.includes("serializeChartSvgSafe") ||
          src.includes("VisualExportChartScope")
        );
      });
      expect(mounted).toBe(true);
    }
  });
});
