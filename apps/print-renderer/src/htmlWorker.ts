// Isolated execution of the SAME PGV-07 SSR bundle; no second renderer.
import { parentPort, workerData } from "node:worker_threads";
import { buildPrintHtml } from "./rendererCore";
try {
  parentPort?.postMessage({ html: buildPrintHtml(workerData.payload, workerData.pageIndex, workerData.pageCount) });
} catch {
  parentPort?.postMessage({ error: "print SSR failed" });
}
