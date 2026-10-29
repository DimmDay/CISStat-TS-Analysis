// apps/print-renderer/src/smoke.ts
//
// PGV-08 — Sandboxed renderer container: entrypoint контейнера.
//
// Режимы:
//   --serve   HTTP-сервис рендера (продовый путь, порт 8907);
//   --probe   быстрый readiness-probe (healthcheck Dockerfile): мини-
//             рендер кириллицы, exit 0/1;
//   --smoke   полный смоук финального образа кириллица/IH/A4
//             (критерий §13), JSON-отчёт в stdout, exit 0/1.
//
// Смоук идёт через ТУ же цепочку, что и продовый рендер: dependency-
// манифест (AC17) → SSR из общего бандла PGV-07 → sandbox-браузер
// (AC19) → hard timeout (AC20) → pHYs 300 ppi (AC16).

import { PrintRenderWorker, readConfig } from "./renderWorker";
import { runFullSmoke, runProbeSmoke } from "./smokeScenarios";

function emit(value: unknown): void {
  process.stdout.write(`${JSON.stringify(value, null, 2)}\n`);
}

async function main(): Promise<void> {
  const mode = process.argv[2] ?? "--smoke";
  const config = readConfig();
  const worker = new PrintRenderWorker(config);

  const shutdown = (signal: string): void => {
    void worker.shutdown().finally(() => process.exit(0));
    setTimeout(() => process.exit(0), 5000).unref();
  };
  process.on("SIGTERM", () => shutdown("SIGTERM"));
  process.on("SIGINT", () => shutdown("SIGINT"));

  if (mode === "--serve") {
    // Продовый путь — делегируем server.ts (require, чтобы сохранить
    // семантику main() с обработчиками сигналов самого сервера).
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { createRendererServer } = require("./server") as typeof import("./server");
    const server = createRendererServer();
    server.listen(config.port, "0.0.0.0", () => {
      process.stdout.write(
        `${JSON.stringify({ event: "renderer_listening", port: config.port })}\n`,
      );
    });
    return;
  }

  try {
    const manifest = worker.dependencyManifest();
    if (manifest.dependency_status === "unavailable") {
      emit({
        verdict: "failed",
        dependency_status: manifest.dependency_status,
        unavailable_reason: manifest.unavailable_reason,
      });
      process.exitCode = 1;
      return;
    }
    if (mode === "--probe") {
      const report = await runProbeSmoke(worker);
      emit(report);
      process.exitCode = report.verdict === "passed" ? 0 : 1;
      return;
    }
    const report = await runFullSmoke(worker);
    emit(report);
    process.exitCode = report.verdict === "passed" ? 0 : 1;
  } catch (error) {
    emit({
      verdict: "failed",
      error: error instanceof Error ? error.message : String(error),
    });
    process.exitCode = 1;
  } finally {
    await worker.shutdown();
  }
}

void main();
