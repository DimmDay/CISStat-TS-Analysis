// packages/ui/lib/visualExportRegistry.pgv00fix.test.ts
//
// PGV-00-FIX — пины исправления находок сертификации F-P0C2/F-P0C3/F-P0C4
// (акт docs/cert_pgv00_2026-10-28.md, план §7; RED-свидетельства —
// scripts/pgv00cert/test_p0cert_findings_evidence.py, Класс B).
//
// Суть исправления (spec §5 — обязательный охват):
//   - F-P0C2: NavigatorDistributionPreview монтирует ТРИ recharts-графика
//     (scatter/histogram/KDE через переиспользуемый DistributionCharts.tsx),
//     реестр держал только scatter/histogram → +navigator.upload.distribution.kde,
//     +renderer_component у navigator distribution-записей (сильная
//     паттерн-доказательность вместо пина слабых сигнатур);
//   - F-P0C3: научные ветки «Наложение прогнозов» (comparison-view) и
//     «Веер чувствительности» (sensitivity-view) в Прогнозировании —
//     представления артефактов FORECAST-1, не контролы → +2 записи;
//   - F-P0C4: остановка Навигатора upload.preview рендерит
//     UploadAutoPreviewPipeline — статичную научную блок-схему пайплайна
//     автопревью (родственник зарегистрированного StructuralClassSchema),
//     ошибочно попавшую под glob-исключение мастеров коррекций →
//     +navigator.upload.preview.schema и сужение glob до
//     Validation*/Preprocessing*-мастеров.
//
// Оракулы написаны ДО правки реестра (TDD RED на 06f0f65: 6/6 падений).

import path from "node:path";
import { existsSync, readdirSync, readFileSync } from "node:fs";

import {
  VISUAL_SITE_REGISTRY,
  VISUAL_RENDER_SITE_EXCLUSIONS,
  VISUAL_STOP_CATALOG,
  visualRegistrySummary,
} from "./visualExportRegistry";

const REPO_ROOT = path.resolve(__dirname, "..", "..", "..");

function getSite(viewId: string) {
  const site = VISUAL_SITE_REGISTRY.find((s) => s.view_id === viewId);
  expect(site).toBeDefined();
  return site!;
}

function globToRegExp(glob: string): RegExp {
  const escaped = glob.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*");
  return new RegExp(`^${escaped}$`);
}

/** Все не-тестовые .tsx файлы пакетов компонентов (для проверок glob-исключений). */
function componentFiles(): string[] {
  const dir = path.join(REPO_ROOT, "packages", "ui", "components");
  return readdirSync(dir)
    .filter((f) => /\.tsx$/.test(f) && !/\.test\.tsx$/.test(f))
    .map((f) => `packages/ui/components/${f}`);
}

// ── F-P0C2: KDE в обязательном охвате Навигатора ────────────────────

describe("PGV-00-FIX / F-P0C2: navigator.upload.distribution.kde", () => {
  it("третий recharts-график NavigatorDistributionPreview зарегистрирован", () => {
    const site = getSite("navigator.upload.distribution.kde");
    expect(site.module_id).toBe("navigator");
    expect(site.stop_id).toBe("upload.distribution");
    expect(site.renderer_kind).toBe("recharts_svg");
    expect(site.render_site).toBe("packages/ui/components/NavigatorDistributionPreview.tsx#kde");
    expect(site.renderer_component).toBe(
      "packages/ui/components/DistributionCharts.tsx#KdeDistributionChart",
    );
    expect(site.applicability).toContain("static_demo");
    expect(site.required_refs).toContain("demo_dataset_id");
    expect(site.export_status).toBe("planned");
  });

  it("компонент KDE реально монтируется в NavigatorDistributionPreview (претест живости)", () => {
    const src = readFileSync(
      path.join(REPO_ROOT, "packages", "ui", "components", "NavigatorDistributionPreview.tsx"),
      "utf-8",
    );
    expect(src).toContain("<KdeDistributionChart");
  });

  it("все три navigator distribution-записи несут renderer_component (сильная сигнатура, снятие слабого пина)", () => {
    for (const viewId of [
      "navigator.upload.distribution.scatter",
      "navigator.upload.distribution.histogram",
      "navigator.upload.distribution.kde",
    ]) {
      const site = getSite(viewId);
      expect(site.renderer_component).toMatch(/^packages\/ui\/components\/DistributionCharts\.tsx#/);
      expect(existsSync(path.join(REPO_ROOT, site.renderer_component!.split("#")[0]))).toBe(true);
    }
  });
});

// ── F-P0C3: comparison/sensitivity ветки Прогнозирования ────────────

describe("PGV-00-FIX / F-P0C3: forecasting forecast comparison+sensitivity", () => {
  it("«Наложение прогнозов» (comparison-view) зарегистрирован как научный вид", () => {
    const site = getSite("forecasting.forecast.comparison");
    expect(site.module_id).toBe("forecasting");
    expect(site.stop_id).toBe("forecast");
    expect(site.renderer_kind).toBe("html_cards");
    expect(site.render_site).toBe("packages/ui/components/TsAnalysisForecasting.tsx#comparison-view");
    expect(site.required_refs).toEqual(
      expect.arrayContaining(["context_id", "data_revision", "forecast_artifact_ref"]),
    );
    expect(site.view_params).toEqual(expect.arrayContaining(["model_name", "horizon"]));
    expect(site.export_status).toBe("planned");
  });

  it("«Веер чувствительности» (sensitivity-view) зарегистрирован как научный вид", () => {
    const site = getSite("forecasting.forecast.sensitivity");
    expect(site.module_id).toBe("forecasting");
    expect(site.stop_id).toBe("forecast");
    expect(site.renderer_kind).toBe("html_cards");
    expect(site.render_site).toBe("packages/ui/components/TsAnalysisForecasting.tsx#sensitivity-view");
    expect(site.required_refs).toEqual(
      expect.arrayContaining(["context_id", "data_revision", "forecast_artifact_ref"]),
    );
    expect(site.view_params).toEqual(expect.arrayContaining(["varied_axes", "param_space"]));
    expect(site.export_status).toBe("planned");
  });

  it("обе ветки реально существуют в TsAnalysisForecasting (претест живости)", () => {
    const src = readFileSync(
      path.join(REPO_ROOT, "packages", "ui", "components", "TsAnalysisForecasting.tsx"),
      "utf-8",
    );
    expect(src).toContain('data-testid="comparison-view"');
    expect(src).toContain('data-testid="sensitivity-view"');
  });
});

// ── F-P0C4: остановка upload.preview + сужение glob-исключения ──────

describe("PGV-00-FIX / F-P0C4: navigator.upload.preview.schema", () => {
  it("схема пайплайна автопревью зарегистрирована на остановке upload.preview", () => {
    const site = getSite("navigator.upload.preview.schema");
    expect(site.module_id).toBe("navigator");
    expect(site.stop_id).toBe("upload.preview");
    expect(VISUAL_STOP_CATALOG.navigator).toContain("upload.preview");
    expect(site.render_site).toBe("packages/ui/components/UploadAutoPreviewPipeline.tsx");
    expect(site.applicability).toContain("static_demo");
    expect(site.required_refs).toContain("demo_dataset_id");
    expect(site.export_status).toBe("planned");
  });

  it("UploadAutoPreviewPipeline больше не под исключениями и покрыт реестром", () => {
    const file = "packages/ui/components/UploadAutoPreviewPipeline.tsx";
    for (const exclusion of VISUAL_RENDER_SITE_EXCLUSIONS) {
      for (const target of exclusion.targets) {
        if (target.includes("*")) {
          expect(globToRegExp(target).test(file)).toBe(false);
        } else {
          expect(target).not.toBe(file);
        }
      }
    }
    const covered = new Set<string>();
    for (const site of VISUAL_SITE_REGISTRY) {
      covered.add(site.render_site.split("#")[0]);
      if (site.renderer_component) covered.add(site.renderer_component.split("#")[0]);
    }
    expect(covered.has(file)).toBe(true);
  });

  it("суженный glob-исключение всё ещё покрывает ровно 20 мастеров Validation*/Preprocessing*", () => {
    const pipelineGroup = VISUAL_RENDER_SITE_EXCLUSIONS.find((e) =>
      e.targets.some((t) => t.includes("*Pipeline.tsx")),
    );
    expect(pipelineGroup).toBeDefined();
    expect(pipelineGroup!.reason_class).toBe("controls");
    const globs = pipelineGroup!.targets.filter((t) => t.includes("*"));
    expect(globs).toEqual([
      "packages/ui/components/Validation*Pipeline.tsx",
      "packages/ui/components/Preprocessing*Pipeline.tsx",
    ]);
    const matched = componentFiles().filter((f) => globs.some((g) => globToRegExp(g).test(f)));
    expect(matched.length).toBe(20);
    // Ни один матч не является не-мастером (UploadAutoPreviewPipeline выведен).
    for (const f of matched) {
      expect(/^packages\/ui\/components\/(Validation|Preprocessing)\w*Pipeline\.tsx$/.test(f)).toBe(true);
    }
  });

  it("группа исключений по-прежнему одна из 9 (сужение без роста групп)", () => {
    expect(VISUAL_RENDER_SITE_EXCLUSIONS.length).toBe(9);
  });
});

// ── Denominator после фикса (синхронно с cert-корпусом) ─────────────

describe("PGV-00-FIX: denominator 93", () => {
  it("состав по модулям: navigator 16, forecasting 8, всего 93", () => {
    expect(visualRegistrySummary().modules).toEqual({
      navigator: 16,
      upload: 12,
      validation: 12,
      preprocessing: 20,
      eda: 18,
      modeling: 6,
      forecasting: 8,
      tasks: 1,
    });
    expect(visualRegistrySummary().total).toBe(93);
    expect(VISUAL_SITE_REGISTRY.length).toBe(93);
  });
});
