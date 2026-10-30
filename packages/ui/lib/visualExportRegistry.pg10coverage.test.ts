// packages/ui/lib/visualExportRegistry.pg10coverage.test.ts
//
// PGV-10 coverage-гвард (spec_passport_graphics_visual.md §13, строка
// PGV-10; паттерн coverage-оракула PGV-00): КАЖДЫЙ pgv-03 research view
// остановок upload/validation/preprocessing (38 сайтов) монтирует
// «Скачать PNG» (VisualExportButton/VisualExportChartScope) в своей
// поверхности рендера. Статический скан исходников: view_id кнопки
// обязан входить в скоуп PGV-10 (чужой viewId -- ошибка), каждый сайт
// скоупа обязан быть вмонтирован (unknown site блокирует CERT -- §5).
// Сериализация -- СВОЙ chart-узел (serializeChartSvgSafe -- не первый
// SVG документа; проверяется отдельным тестом serializeChartSvg.test.ts).

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

function wiredViewIdsFromSources(): Map<string, string[]> {
  // view_id -> файлы поверхностей, монтирующие кнопку
  const found = new Map<string, string[]>();
  const componentsDir = resolve(__dirname, "../components");
  const files = [
    "TsAnalysisUpload.tsx",
    "StructuralClassSchema.tsx",
    "TsAnalysisValidation.tsx",
    "ValidationTypeMatrix.tsx",
    "ValidationRangeOverview.tsx",
    "ValidationConsistencyOverview.tsx",
    "ValidationUniquenessOverview.tsx",
    "ValidationInclusionOverview.tsx",
    "ValidationReferentialOverview.tsx",
    "ValidationTextQualityOverview.tsx",
    "ValidationRegularityOverview.tsx",
    "ValidationSufficiencyOverview.tsx",
    "PreprocessingMissingOverview.tsx",
    "PreprocessingMissingVisualizations.tsx",
    "PreprocessingOutliersOverview.tsx",
    "PreprocessingOutliersVisualizations.tsx",
    "PreprocessingRegularityOverview.tsx",
    "PreprocessingRegularityVisualizations.tsx",
    "PreprocessingDecompositionOverview.tsx",
    "PreprocessingVarianceOverview.tsx",
    "PreprocessingSmoothingOverview.tsx",
    "PreprocessingStationarityOverview.tsx",
    "PreprocessingSpectralOverview.tsx",
    "PreprocessingFeatureEngineeringOverview.tsx",
    "PreprocessingScalingOverview.tsx",
  ];
  for (const file of files) {
    const src = readFileSync(resolve(componentsDir, file), "utf-8");
    for (const match of src.matchAll(/viewId=\{?[`"]([a-z_.]+)[`"]/g)) {
      const viewId = match[1];
      const list = found.get(viewId) ?? [];
      list.push(file);
      found.set(viewId, list);
    }
    for (const match of src.matchAll(/viewId=\{`([a-z_.]+)\.\$\{view\}`/g)) {
      // Шаблон субвидов (кнопка следует активному subview): префикс;
      // первый regex такое не захватывает -- срезаем хвост-суффикс.
      const prefix = `${match[1]}.`;
      const list = found.get(prefix) ?? [];
      list.push(file);
      found.set(prefix, list);
    }
  }
  return found;
}

describe("PGV-10: «Скачать PNG» на всех render sites трёх остановок", () => {
  const sites = registrySites();
  const scope = sites.filter(
    (site) =>
      ["upload", "validation", "preprocessing"].includes(site.module_id) &&
      site.source_adapter.startsWith("pgv-03/") &&
      site.applicability !== "static_demo",
  );
  const wired = wiredViewIdsFromSources();

  it("каждый сайт скоупа (38) монтирует VisualExportButton", () => {
    expect(scope).toHaveLength(38);
    const missing = scope.filter((site) => {
      if (wired.has(site.view_id)) return false;
      // Субвиды Обзора стабилизации дисперсии монтируются шаблоном
      // viewId={`preprocessing.variance_stab.${view}`} (кнопка следует
      // активному субвиду): префикс покрывает все пять view.
      const prefixKey = `preprocessing.variance_stab.`;
      // Покрытый префиксом сайт -- НЕ missing (false), иначе missing.
      return !(site.view_id.startsWith(prefixKey) && wired.has(prefixKey));
    });
    expect(missing).toEqual([]);
  });

  it("viewId кнопок -- только сайты скоупа PGV-10 (чужой view -- ошибка)", () => {
    const scopeIds = new Set(scope.map((site) => site.view_id));
    const foreign = [...wired.keys()].filter(
      (viewId) =>
        // ключи с хвостовым "." -- шаблонные префиксы субвидов
        // (кнопка следует активному subview), не чужие view.
        !viewId.endsWith(".") && !scopeIds.has(viewId),
    );
    expect(foreign).toEqual([]);
  });

  it("chart-сайты скоупа сериализуют СВОЙ узел (getScreenSvg по ref)", () => {
    // Каждый recharts/mixed сайт скоупа обязан передавать
    // getScreenSvg (frozen геометрия -- §4.1 passthrough), кроме
    // чисто табличных/карточных видов.
    const chartKinds = new Set(["recharts_svg", "mixed"]);
    const chartScope = scope.filter((site) => chartKinds.has(site.renderer_kind));
    expect(chartScope.length).toBeGreaterThan(0);
    const varianceTemplatePrefix = "preprocessing.variance_stab.";
    for (const site of chartScope) {
      const files = wired.get(site.view_id) ?? (site.view_id.startsWith(varianceTemplatePrefix) ? wired.get(varianceTemplatePrefix) ?? [] : []);
      const mounted = files.some((file) => {
        // Frozen геометрия -- СВОЙ узел: файл-поверхность обязан
        // сериализовать scoped (serializeChartSvgSafe напрямую либо
        // через VisualExportChartScope -- скоуп с внутренним ref).
        const src = readFileSync(resolve(__dirname, "../components", file), "utf-8");
        return (
          src.includes("serializeChartSvgSafe") ||
          src.includes("VisualExportChartScope")
        );
      });
      expect(mounted).toBe(true);
    }
  });

  it("сериализатор -- scoped (не document.body): контракт serializeChartSvgSafe", () => {
    // Статический пин: сериализатор принимает КОНКРЕТНЫЙ контейнер,
    // а не документ (критерий «не первый SVG»).
    const src = readFileSync(resolve(__dirname, "serializeChartSvg.ts"), "utf-8");
    expect(src).toContain('container.querySelector("svg")');
    expect(src).not.toContain("document.querySelector");
  });
});
