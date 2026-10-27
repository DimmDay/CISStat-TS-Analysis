// scripts/pgv01/export_print_schema.ts
//
// PGV-01: экспорт JSON-твина print-схем.
// Источник истины — packages/ui/print/printSchema.ts (TypeScript);
// JSON-твин config/print_schema.json — machine-readable поставка для
// Python-зеркала apps/api/print_schema.py (preflight PGV-02/09) и
// doc-проверок (scripts/pgv01/check_documents.py). Паритет TS⇄JSON
// гвардится jest-оракулом packages/ui/print/printSchema.test.ts.
//
// Запуск: node --experimental-strip-types scripts/pgv01/export_print_schema.ts

import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { serializePrintSchema } from "../../packages/ui/print/printSchema.ts";

const repoRoot = path.resolve(import.meta.dirname!, "..", "..");
const json = serializePrintSchema();
const outPath = path.join(repoRoot, "config", "print_schema.json");

mkdirSync(path.dirname(outPath), { recursive: true });
writeFileSync(outPath, `${JSON.stringify(json, null, 2)}\n`, "utf-8");

console.log(
  `OK: ${path.relative(repoRoot, outPath)} — ${json.profiles.length} profiles, ` +
    `${json.violation_codes.length} violation codes, schema ${json.schema_version}`,
);
