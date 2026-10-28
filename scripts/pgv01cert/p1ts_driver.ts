// scripts/pgv01cert/p1ts_driver.ts
//
// PGV-01-CERT — TS-канал паритетного оракула (мутанты на своих мутантах,
// оракулы на своих данных). Читает джоб p1cases.ts_job() из файла (argv[2]),
// запускает РЕАЛЬНЫЕ валидаторы поставки PGV-01 над реальным реестром
// PGV-00 и печатает исходы {id → [[code, path], …]} в stdout.
//
// Сертификаторский драйвер: не импортирует repo-тесты; только валидаторы
// и реестр поставки. Спец-маркеры чисел {"__special__": "NaN"|"Infinity"|
// "-Infinity"} разворачиваются до настоящих non-finite значений.
//
// Запуск: node --experimental-strip-types scripts/pgv01cert/p1ts_driver.ts <job.json>

import { readFileSync } from "node:fs";

import {
  isUnitDeclared,
  validatePrintSetManifest,
  validateVisualPrintSnapshot,
  validateVisualResult,
} from "../../packages/ui/print/printSchema.ts";
import { VISUAL_SITE_REGISTRY } from "../../packages/ui/lib/visualExportRegistry.ts";

type Outcome = [string, string];

interface Case {
  id: string;
  kind: "snapshot" | "result" | "manifest";
  payload: unknown;
  site: string | null;
}

interface Job {
  cases: Case[];
}

function unfoldSpecials(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(unfoldSpecials);
  if (value !== null && typeof value === "object") {
    const rec = value as Record<string, unknown>;
    const keys = Object.keys(rec);
    if (keys.length === 1 && keys[0] === "__special__") {
      if (rec.__special__ === "NaN") return NaN;
      if (rec.__special__ === "Infinity") return Infinity;
      if (rec.__special__ === "-Infinity") return -Infinity;
      throw new Error(`p1cert-driver: unknown special marker ${String(rec.__special__)}`);
    }
    const out: Record<string, unknown> = {};
    for (const key of keys) out[key] = unfoldSpecials(rec[key]);
    return out;
  }
  return value;
}

function outcomesOf(caseItem: Case): Outcome[] {
  const payload = unfoldSpecials(caseItem.payload);
  if (caseItem.kind === "snapshot") {
    const site = VISUAL_SITE_REGISTRY.find((candidate) => candidate.view_id === caseItem.site);
    if (!site) throw new Error(`p1cert-driver: site not found: ${caseItem.site}`);
    return validateVisualPrintSnapshot(payload, site).map((violation) => [violation.code, violation.path] as Outcome);
  }
  if (caseItem.kind === "result") {
    return validateVisualResult(payload).map((violation) => [violation.code, violation.path] as Outcome);
  }
  if (caseItem.kind === "manifest") {
    return validatePrintSetManifest(payload).map((violation) => [violation.code, violation.path] as Outcome);
  }
  if (caseItem.kind === "unit_decl") {
    const declared = isUnitDeclared(payload as { value: string | null; reason: string | null });
    return [[declared ? "unit_declared" : "unit_not_declared", "value"] as Outcome];
  }
  throw new Error(`p1cert-driver: unknown case kind: ${String(caseItem.kind)}`);
}

const jobPath = process.argv[2];
if (!jobPath) {
  console.error("usage: node --experimental-strip-types p1ts_driver.ts <job.json>");
  process.exit(2);
}
const job = JSON.parse(readFileSync(jobPath, "utf-8")) as Job;
if (!Array.isArray(job.cases) || job.cases.length === 0) {
  console.error("p1cert-driver: job.cases must be a non-empty array");
  process.exit(2);
}
const results = job.cases.map((caseItem) => {
  try {
    return { id: caseItem.id, outcomes: outcomesOf(caseItem) };
  } catch (error) {
    return { id: caseItem.id, outcomes: [["__driver_exception__", String(error).slice(0, 120)]] as Outcome[] };
  }
});
process.stdout.write(JSON.stringify({ driver: "p1cert/1", results }));
