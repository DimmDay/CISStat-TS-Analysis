// packages/ui/lib/visualExportRegistry.pgv12coverage.test.ts
//
// PGV-12 coverage-гвард (spec_passport_graphics_visual.md §13, строка
// PGV-12; паттерн гвардов PGV-10/11): КАЖДЫЙ pgv-03 research view
// моделирования (6) и прогнозирования (7) монтирует «Скачать PNG»
// (VisualExportButton) в своей поверхности рендера. Статический скан
// исходников: view_id кнопки обязан входить в скоуп PGV-12 (чужой
// viewId -- ошибка), каждый сайт скоупа обязан быть вмонтирован
// (unknown site блокирует CERT -- §5). Сериализация -- СВОЙ chart-узел
// (serializeChartSvgSafe -- не первый SVG документа).
//
// Дополнительно (§10.1/§13 «CSV/JSON/audit сохранены»): legacy PNG
// ForecastExportMenu переехал на общий pipeline -- downloadChartPng/
// canvas-путь удалён, PNG идёт через requestVisualExport(view
// forecasting.forecast.chart); recordClientExport сохранён.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

interface VisualSiteRecord {
  view_id: string;
  module_id: string;
  renderer_kind: string;
  render_site?: string;
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

// Поверхности моделирования/прогнозирования/панели/мониторинга (PGV-12):
// workflow-обзор несёт ДВА view (таблица стадий + отчёт диагностики),
// TsAnalysisModeling -- панельные метрики, TsAnalysisForecasting --
// chart/panel/comparison/sensitivity.
const SURFACE_FILES = [
  "ModelingWorkflowOverview.tsx",
  "ModelingTraceabilityOverview.tsx",
  "BacktestComparisonChart.tsx",
  "BacktestOofChart.tsx",
  "TsAnalysisModeling.tsx",
  "TsAnalysisForecasting.tsx",
  "ForecastAccuracyPanel.tsx",
  "MonitoringComparisonPanel.tsx",
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
    for (const match of src.matchAll(/viewId=\{?[`"]([a-z0-9_.]+)[`"]/g)) {
      push(match[1]);
    }
    for (const block of src.matchAll(/viewId=\{([\s\S]*?)\}/g)) {
      for (const id of block[1].matchAll(/[a-z0-9_]+\.[a-z0-9_.]+(?:\.[a-z0-9_.]+)+/g)) {
        if (id[0].startsWith("modeling.") || id[0].startsWith("forecasting.")) {
          push(id[0]);
        }
      }
    }
  }
  return found;
}

describe("PGV-12: «Скачать PNG» на всех render sites моделирования и прогнозирования", () => {
  const sites = registrySites();
  const scope = sites.filter(
    (site) =>
      ["modeling", "forecasting"].includes(site.module_id) &&
      site.source_adapter.startsWith("pgv-03/") &&
      site.applicability !== "static_demo",
  );
  const wired = wiredViewIdsFromSources();

  it("каждый сайт скоупа (13) монтирует VisualExportButton", () => {
    expect(scope).toHaveLength(13);
    const missing = scope.filter((site) => !wired.has(site.view_id));
    expect(missing).toEqual([]);
  });

  it("viewId кнопок -- только сайты скоупа PGV-12 (чужой view -- ошибка)", () => {
    const scopeIds = new Set(scope.map((site) => site.view_id));
    const foreign = [...wired.keys()].filter((viewId) => !scopeIds.has(viewId));
    expect(foreign).toEqual([]);
  });

  it("chart-сайты скоупа сериализуют СВОЙ узел (getScreenSvg по ref)", () => {
    const chartKinds = new Set(["recharts_svg", "mixed"]);
    const chartScope = scope.filter((site) => chartKinds.has(site.renderer_kind));
    expect(chartScope.length).toBeGreaterThan(0);
    for (const site of chartScope) {
      const files = wired.get(site.view_id) ?? [];
      const mounted = files.some((file) => {
        const src = readFileSync(
          resolve(__dirname, "../components", file),
          "utf-8",
        );
        return (
          src.includes("serializeChartSvgSafe") ||
          src.includes("VisualExportChartScope")
        );
      });
      expect(mounted).toBe(true);
    }
  });

  it("диагностика: печать следует смонтированной поверхности (workflow-обзор)", () => {
    // ResidualDiagnosticsPanel остаётся несмонтированным standalone-
    // компонентом (честная маркировка); печатная поверхность отчёта
    // диагностики -- ModelingWorkflowOverview (реестр обновлён PGV-12).
    const diagnostics = sites.find(
      (site) => site.view_id === "modeling.diagnostics.residuals",
    );
    expect(diagnostics).toBeDefined();
    expect(diagnostics!.render_site).toContain("ModelingWorkflowOverview");
    expect(wired.has("modeling.diagnostics.residuals")).toBe(true);
  });
});

describe("PGV-12: legacy PNG-меню прогноза переехало на общий pipeline", () => {
  const menuPath = resolve(__dirname, "../components/ForecastExportMenu.tsx");
  const menuSrc = readFileSync(menuPath, "utf-8");

  it("в меню нет клиентского canvas-PNG (downloadChartPng удалён)", () => {
    expect(menuSrc).not.toContain("downloadChartPng");
    expect(menuSrc).not.toContain("canvas.toBlob");
    expect(menuSrc).not.toContain("new Image()");
  });

  it("PNG меню идёт через общий pipeline (requestVisualExport + СВОЙ узел)", () => {
    expect(menuSrc).toContain("requestVisualExport");
    expect(menuSrc).toContain("serializeChartSvgSafe");
  });

  it("CSV/JSON и client-export audit сохранены (§10.1/§13)", () => {
    expect(menuSrc).toContain('data-testid="export-csv"');
    expect(menuSrc).toContain('data-testid="export-json"');
    expect(menuSrc).toContain("recordClientExport");
  });

  it("реестр: сайт legacy_client снят с учёта (путь объединён с forecast.chart)", () => {
    const legacy = registrySites().find(
      (site) => site.view_id === "forecasting.forecast.legacy_png",
    );
    expect(legacy).toBeUndefined();
  });
});
