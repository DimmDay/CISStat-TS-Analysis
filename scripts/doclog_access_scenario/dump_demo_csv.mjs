// Дамп demo-CSV forecast_monitor_synthetic_n150.csv РОВНО тем генератором,
// что исполняется в браузере аналитика (packages/ui/lib/demoDatasets.ts,
// первая демо-карточка forecast_monitor_n150, fileName
// forecast_monitor_synthetic_n150.csv). Node >= 22.6 (--experimental-strip-types,
// в Node 24 включено по умолчанию) исполняет этот TS-модуль напрямую,
// без пересборки монорепо.
import { writeFileSync } from "node:fs";
import { DEMO_DATASETS } from "../../packages/ui/lib/demoDatasets.ts";

const demo = DEMO_DATASETS.find((d) => d.fileName === "forecast_monitor_synthetic_n150.csv");
if (!demo) throw new Error("demo card forecast_monitor_n150 not found");
const csv = demo.generateCsv();
writeFileSync(new URL("./forecast_monitor_synthetic_n150.csv", import.meta.url), csv, "utf8");
console.log(JSON.stringify({ fileName: demo.fileName, bytes: Buffer.byteLength(csv, "utf8"), lines: csv.split("\n").length - 2 }));
