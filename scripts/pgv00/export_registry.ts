// scripts/pgv00/export_registry.ts
//
// PGV-00: экспорт JSON-твина реестра render-sites.
// Источник истины — packages/ui/lib/visualExportRegistry.ts (TypeScript);
// JSON-твин config/visual_registry.json — machine-readable поставка для
// бэкенда (PGV-01/02) и doc-проверок (scripts/pgv00/check_documents.py).
// Паритет TS⇄JSON гвардится тестом visualExportRegistry.coverage.test.ts.
//
// Запуск: node --experimental-strip-types scripts/pgv00/export_registry.ts

import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { serializeVisualRegistry } from "../../packages/ui/lib/visualExportRegistry.ts";

const repoRoot = path.resolve(import.meta.dirname!, "..", "..");
const json = serializeVisualRegistry();
const outPath = path.join(repoRoot, "config", "visual_registry.json");

mkdirSync(path.dirname(outPath), { recursive: true });
writeFileSync(outPath, `${JSON.stringify(json, null, 2)}\n`, "utf-8");

const modules = Object.entries(json.modules)
  .map(([m, n]) => `${m}=${n}`)
  .join(", ");
console.log(`OK: ${path.relative(repoRoot, outPath)} — ${json.total_sites} sites (${modules}), ${json.exclusions.length} exclusions`);
