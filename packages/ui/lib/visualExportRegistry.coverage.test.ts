// packages/ui/lib/visualExportRegistry.coverage.test.ts
//
// PGV-00 — coverage-оракул реестра научных render-sites
// (spec_passport_graphics_visual.md §5, §13; критерий готовности:
// «HTML/panel/real navigator включены, exclusions явны, unknown site
// блокирует CERT и остаётся в denominator coverage»).
//
// Три канала проверки:
//   1) Интегрити-оракулы: схема записей, уникальность view_id, каталоги
//      модулей/остановок (сверка с источниками истины navigator-stops.ts),
//      честность export_status, существование файлов на диске.
//   2) Coverage-оракул: скан исходников UI по научным рендер-паттернам
//      (recharts / inline-svg / canvas / html-table / CSS-heatmap) —
//      каждый совпавший файл ДОЛЖЕН быть либо зарегистрирован, либо
//      исключён с явной причиной. Неизвестный файл = падение теста
//      (блокирует CERT,spec §5 «Unknown/unmapped scientific site»).
//   3) Семейные правила: все файлы научных семейств (Navigator*Preview,
//      Eda*Overview, Validation*Overview, Preprocessing*Overview/
//      *Visualizations) должны быть покрыты даже без pattern-совпадения
//      (закрывает слепую зону паттернов для grid/card-превью).
//
// Плюс гвард паритета TS⇄JSON (config/visual_registry.json) — паттерн
// реестра знаний EDU-API-1: JSON-твин для бэкенда (PGV-01/02) и
// doc-проверок (scripts/pgv00/check_documents.py), дрейф невозможен.

import { existsSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";

import {
  PGV_REGISTRY_SCHEMA_VERSION,
  VISUAL_MODULE_IDS,
  VISUAL_EXPORT_STATUSES,
  VISUAL_SITE_REGISTRY,
  VISUAL_RENDER_SITE_EXCLUSIONS,
  VISUAL_STOP_CATALOG,
  visualRegistrySummary,
  type VisualSiteRecord,
} from "./visualExportRegistry";
import { NAVIGATOR_STOPS } from "./navigator-stops";

// ── Инфраструктура скана ─────────────────────────────────────────

const REPO_ROOT = path.resolve(__dirname, "..", "..", "..");
const COMPONENTS_DIR = path.join(REPO_ROOT, "packages", "ui", "components");
const STANDALONE_APP_DIR = path.join(REPO_ROOT, "apps", "standalone", "app");
const EMBEDDED_APP_DIR = path.join(REPO_ROOT, "apps", "embedded", "app");

/** Научные рендер-паттерны (spec §5: «Поиск recharts/svg/canvas/HTML table/CSS heatmap — вспомогательный oracle»). */
const SCIENTIFIC_PATTERNS: ReadonlyArray<readonly [string, RegExp]> = [
  ["recharts-import", /from\s+["']recharts["']/],
  ["inline-svg", /<svg[\s>]/],
  ["canvas", /<canvas[\s>]/],
  ["html-table", /<table[\s>]/],
  ["css-heatmap-gradient", /linear-gradient\(/],
  ["css-heatmap-color-scale", /backgroundColor:\s*[`a-zA-Z]/],
];

/** Семейные правила: научные семейства файлов должны быть покрыты целиком. */
const SCIENTIFIC_FAMILY_RULES: ReadonlyArray<readonly [string, RegExp]> = [
  ["Navigator*Preview (реальные научные preview Навигатора)", /^packages\/ui\/components\/Navigator.+Preview\.tsx$/],
  ["Eda*Overview (субвиды EDA)", /^packages\/ui\/components\/Eda.+Overview\.tsx$/],
  ["Validation*Overview (обзоры проверок)", /^packages\/ui\/components\/Validation.+Overview\.tsx$/],
  ["Preprocessing*Overview (обзоры преобразований)", /^packages\/ui\/components\/Preprocessing.+Overview\.tsx$/],
  ["Preprocessing*Visualizations (визуализации остановок)", /^packages\/ui\/components\/Preprocessing.+Visualizations\.tsx$/],
];

function listSourceFiles(rootDir: string): string[] {
  if (!existsSync(rootDir)) return [];
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true }) as Array<{ name: string; isDirectory(): boolean }>) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === "node_modules" || entry.name.startsWith(".")) continue;
        walk(full);
      } else if (/\.tsx$/.test(entry.name) && !/\.test\.tsx$/.test(entry.name)) {
        out.push(full);
      }
    }
  };
  walk(rootDir);
  return out;
}

function toRepoRelative(file: string): string {
  return path.relative(REPO_ROOT, file).split(path.sep).join("/");
}

function scanScientificFiles(): Map<string, string[]> {
  const hits = new Map<string, string[]>();
  for (const root of [COMPONENTS_DIR, STANDALONE_APP_DIR, EMBEDDED_APP_DIR]) {
    for (const file of listSourceFiles(root)) {
      const text = readFileSync(file, "utf-8");
      const kinds = SCIENTIFIC_PATTERNS.filter(([, re]) => re.test(text)).map(([kind]) => kind);
      if (kinds.length > 0) hits.set(toRepoRelative(file), kinds);
    }
  }
  return hits;
}

function globToRegExp(glob: string): RegExp {
  const escaped = glob.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*");
  return new RegExp(`^${escaped}$`);
}

/** Файлы, покрытые реестром: render_site либо renderer_component. */
function registryCoveredFiles(): Set<string> {
  const covered = new Set<string>();
  for (const site of VISUAL_SITE_REGISTRY) {
    covered.add(site.render_site.split("#")[0]);
    if (site.renderer_component) covered.add(site.renderer_component.split("#")[0]);
  }
  return covered;
}

/** Файлы, покрытые явными исключениями (строки или glob-шаблоны). */
function exclusionCoveredFiles(allFiles: string[]): { files: Set<string>; matchedGlobs: Map<string, number> } {
  const files = new Set<string>();
  const matchedGlobs = new Map<string, number>();
  for (const exclusion of VISUAL_RENDER_SITE_EXCLUSIONS) {
    for (const target of exclusion.targets) {
      if (target.includes("*")) {
        const re = globToRegExp(target);
        let count = 0;
        for (const file of allFiles) {
          const rel = toRepoRelative(file);
          if (re.test(rel)) {
            files.add(rel);
            count += 1;
          }
        }
        matchedGlobs.set(target, count);
      } else {
        files.add(target);
      }
    }
  }
  return { files, matchedGlobs };
}

// ── Источники истины остановок ───────────────────────────────────

const NAVIGATOR_ITEM_IDS_BY_STAGE: Record<string, string[]> = Object.fromEntries(
  NAVIGATOR_STOPS.map((stop) => [stop.id, stop.items.map((item) => item.id)]),
);

// ── 1. Интегрити-оракулы ─────────────────────────────────────────

describe("PGV-00: интегрити реестра render-sites", () => {
  it("схема и минимальный состав: реестр непуст, schema_version закреплён", () => {
    expect(PGV_REGISTRY_SCHEMA_VERSION).toBe("pgv.visual_registry/1");
    expect(VISUAL_SITE_REGISTRY.length).toBeGreaterThan(0);
  });

  it("view_id уникальны и следуют канону <module>.<stop>.<view>", () => {
    const ids = VISUAL_SITE_REGISTRY.map((s) => s.view_id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) {
      expect(id).toMatch(/^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$/);
    }
  });

  it("каждая запись имеет полный обязательный состав полей (spec §5)", () => {
    for (const site of VISUAL_SITE_REGISTRY) {
      expect(VISUAL_MODULE_IDS).toContain(site.module_id);
      expect(VISUAL_STOP_CATALOG[site.module_id]).toContain(site.stop_id);
      expect(["recharts_svg", "html_table", "html_heatmap", "html_cards", "mixed"]).toContain(site.renderer_kind);
      expect(VISUAL_EXPORT_STATUSES).toContain(site.export_status);
      expect(site.caption_schema).toMatch(/^pgv\.caption\/[a-z0-9_.-]+\/\d+$/);
      expect(site.required_refs.length).toBeGreaterThan(0);
      expect(site.view_params.length).toBeGreaterThan(0);
      expect(site.applicability.length).toBeGreaterThan(0);
      expect(site.source_adapter).toMatch(/^pgv-\d{2}\//);
      expect(site.tests.length).toBeGreaterThan(0);
      // Честный статус: planned требует planned-адаптера, legacy/not_mounted — пояснения.
      if (site.export_status === "planned") {
        expect(site.source_adapter).toMatch(/^pgv-0[3-9]|^pgv-1[0-6]/);
      }
      if (site.export_status === "legacy_client" || site.export_status === "not_mounted") {
        expect(site.notes ?? "").toMatch(/\S/);
      }
    }
  });

  it("stop_id Навигатора привязан к источнику истины navigator-stops.ts (<stage>.<item>)", () => {
    const navigatorSites = VISUAL_SITE_REGISTRY.filter((s) => s.module_id === "navigator");
    expect(navigatorSites.length).toBeGreaterThan(0);
    for (const site of navigatorSites) {
      const [stage, item] = site.stop_id.split(".");
      const items = NAVIGATOR_ITEM_IDS_BY_STAGE[stage];
      expect(items).toBeDefined();
      expect(items).toContain(item);
    }
  });

  it("stop_id модулей-остановок согласован: upload — ветки модуля, остальные — пункты Навигатора", () => {
    for (const site of VISUAL_SITE_REGISTRY) {
      if (site.module_id === "navigator") continue;
      const allowed = VISUAL_STOP_CATALOG[site.module_id];
      expect(allowed).toContain(site.stop_id);
      // Для обзоров трёх этапов stop_id совпадает с пунктом Навигатора
      // (navigator-stops.ts: «id: совпадает с id в CHECK_META/CHECKS
      // соответствующего модуля») — реестр не расходится с UI. Паспортная
      // остановка — ветка самого модуля (в Навигаторе показана в «Загрузке»);
      // modeling/forecasting — групповые виды: пункты Навигатора — семейства
      // моделей, а не views (их согласованность несёт каталог остановок).
      if (["validation", "preprocessing", "eda"].includes(site.module_id)) {
        const items = NAVIGATOR_ITEM_IDS_BY_STAGE[site.module_id];
        if (items) {
          // «passport» — остановка-исключение: панель паспорта смонтирована
          // во всех четырёх модулях, а в пунктах Навигатора она показана
          // только в ветке «Загрузка» (navigator-stops.ts).
          expect(items.includes(site.stop_id) || site.stop_id === "passport").toBe(true);
        }
      }
    }
  });

  it("файлы render_site/renderer_component существуют на диске", () => {
    for (const site of VISUAL_SITE_REGISTRY) {
      expect(existsSync(path.join(REPO_ROOT, site.render_site.split("#")[0]))).toBe(true);
      if (site.renderer_component) {
        expect(existsSync(path.join(REPO_ROOT, site.renderer_component.split("#")[0]))).toBe(true);
      }
    }
  });

  it("честность export_status: legacy_client и not_mounted — ровно известные записи", () => {
    const legacy = VISUAL_SITE_REGISTRY.filter((s) => s.export_status === "legacy_client").map((s) => s.view_id);
    expect(legacy).toEqual(["forecasting.forecast.legacy_png"]);
    const notMounted = VISUAL_SITE_REGISTRY.filter((s) => s.export_status === "not_mounted").map((s) => s.view_id);
    expect(notMounted).toEqual(["modeling.diagnostics.residuals"]);
    // Реальные научные preview Навигатора зарегистрированы как planned
    // (static_demo), а не как вычислительные экспорты:
    for (const site of VISUAL_SITE_REGISTRY.filter((s) => s.module_id === "navigator")) {
      expect(site.applicability).toContain("static_demo");
    }
  });

  it("родительская спека D01–D12 не переименовывается: в реестре нет document-kind путаницы", () => {
    // D02 (паспорт-документ) — не P01 (saved passport); реестр не вводит
    // видов документов, только render-sites (spec §10.2 «D02 не P01»).
    for (const site of VISUAL_SITE_REGISTRY) {
      expect(site.view_id.startsWith("d")).toBe(false);
    }
  });

  it("паритет TS⇄JSON: config/visual_registry.json — байт-честный твин реестра", () => {
    const jsonPath = path.join(REPO_ROOT, "config", "visual_registry.json");
    expect(existsSync(jsonPath)).toBe(true);
    const json = JSON.parse(readFileSync(jsonPath, "utf-8")) as {
      schema_version: string;
      generated_from: string;
      modules: Record<string, number>;
      total_sites: number;
      sites: VisualSiteRecord[];
      exclusions: typeof VISUAL_RENDER_SITE_EXCLUSIONS;
    };
    expect(json.schema_version).toBe(PGV_REGISTRY_SCHEMA_VERSION);
    expect(json.generated_from).toBe("packages/ui/lib/visualExportRegistry.ts");
    expect(json.sites).toEqual(VISUAL_SITE_REGISTRY);
    expect(json.exclusions).toEqual(VISUAL_RENDER_SITE_EXCLUSIONS);
    expect(json.modules).toEqual(visualRegistrySummary().modules);
    expect(json.total_sites).toBe(VISUAL_SITE_REGISTRY.length);
  });

  it("denominator pins: состав по модулям закреплён (удаление записи падает)", () => {
    const summary = visualRegistrySummary();
    expect(summary.modules).toEqual({
      navigator: 14,
      upload: 12,
      validation: 12,
      preprocessing: 20,
      eda: 18,
      modeling: 6,
      forecasting: 6,
      tasks: 1,
    });
    expect(summary.total).toBe(89);
  });
});

// ── 2. Coverage-оракул: unknown site блокирует CERT ─────────────

describe("PGV-00: coverage-оракул — unknown scientific site blocks CERT", () => {
  const scanned = scanScientificFiles();
  const allFiles = [
    ...listSourceFiles(COMPONENTS_DIR),
    ...listSourceFiles(STANDALONE_APP_DIR),
    ...listSourceFiles(EMBEDDED_APP_DIR),
  ];
  const covered = registryCoveredFiles();
  const { files: excludedFiles, matchedGlobs } = exclusionCoveredFiles(allFiles);

  it("каждый файл с научным рендер-паттерном зарегистрирован или исключён с причиной", () => {
    const unknown: string[] = [];
    for (const [file, kinds] of [...scanned.entries()].sort()) {
      if (!covered.has(file) && !excludedFiles.has(file)) {
        unknown.push(`${file} [${kinds.join(",")}]`);
      }
    }
    expect(unknown).toEqual([]);
  });

  it("семейные правила: все файлы научных семейств покрыты (даже без pattern-совпадения)", () => {
    const uncovered: string[] = [];
    for (const file of allFiles) {
      const rel = toRepoRelative(file);
      if (!SCIENTIFIC_FAMILY_RULES.some(([, re]) => re.test(rel))) continue;
      if (!covered.has(rel) && !excludedFiles.has(rel)) uncovered.push(rel);
    }
    expect(uncovered).toEqual([]);
  });

  it("все 58 эталонных pattern-совпадений разведены по реестру/исключениям (baseline PGV-00)", () => {
    // Базлайн первичного аудита 2026-10-27. Рост числа файлов разрешён
    // только вместе с новыми записями/исключениями реестра; падение —
    // потеря render-site.
    expect(scanned.size).toBeGreaterThanOrEqual(58);
    const classified = [...scanned.keys()].filter((f) => covered.has(f) || excludedFiles.has(f));
    expect(classified.length).toBe(scanned.size);
  });

  it("исключения явны: у каждого файла-исключения есть причина и класс", () => {
    // Пин состава: 9 записей (декор ×3 группы, админ-таблицы, контролы
    // DocumentationWorkspace, редакторы ×1 группа, история прогнозов,
    // placeholder, мастера-контролы ×1 группа). Удаление записи падает.
    expect(VISUAL_RENDER_SITE_EXCLUSIONS.length).toBe(9);
    for (const exclusion of VISUAL_RENDER_SITE_EXCLUSIONS) {
      expect(exclusion.reason).toMatch(/\S/);
      expect(exclusion.reason_class.length).toBeGreaterThan(0);
      expect(exclusion.targets.length).toBeGreaterThan(0);
    }
    // Декоративные волны/герой/футер исключены и НЕ просочились в реестр:
    for (const decorative of [
      "packages/ui/components/HomeWavesBackground.tsx",
      "packages/ui/components/NavigatorWavesBackground.tsx",
      "packages/ui/components/DocumentationWavesBackground.tsx",
      "packages/ui/components/NavigatorHero.tsx",
      "packages/ui/components/HomeFooter.tsx",
    ]) {
      expect(excludedFiles.has(decorative)).toBe(true);
      expect(covered.has(decorative)).toBe(false);
    }
  });

  it("glob-шаблоны исключений не протухли: каждый шаблон находит хотя бы один файл", () => {
    for (const [glob, count] of [...matchedGlobs.entries()]) {
      if (glob.includes("*")) {
        expect(count).toBeGreaterThan(0);
      }
    }
  });

  it("текстовые файлы исключений существуют на диске (строчные цели, не glob)", () => {
    for (const exclusion of VISUAL_RENDER_SITE_EXCLUSIONS) {
      for (const target of exclusion.targets) {
        if (!target.includes("*")) {
          expect(existsSync(path.join(REPO_ROOT, target))).toBe(true);
        }
      }
    }
  });
});
