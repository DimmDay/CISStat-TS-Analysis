// packages/ui/lib/apiUrlPrefixGuard.test.ts
//
// PROGR-15-A guard: ловля КЛАССА дефекта, а не отдельного случая.
//
// Хелперы apiClient (apiUrl / sessionApiUrl / progressApiUrl) уже
// добавляют "/v1[/...]" к базе сами (см. apiClient.ts); ручное вложение
// "/v1..." в аргумент даёт двойной префикс вида
// /v1/session/v1/progress/upload-stops -- гарантированный 404 на любом
// окружении. Именно этот дефект (PROGR-15-REPRO, Г-1) годами прятал
// отчёт остановок «Загрузки» от панели «Прогресс»: fetch резолвится и с
// HTTP-ошибкой, res.ok не проверялся, .catch ловит только сеть --
// «успешный» отчёт ни разу не дошёл до единого движка. URL-ассерты в
// UI-тестах контракта не покрывали, а мок по подстроке "/upload"
// обслуживал и мусорный URL.
//
// Инвариант прост и проверяем статически: НИ ОДИН вызов *ApiUrl() во
// всём фронтенд-коде не содержит "/v1" в аргументе. Тест сканирует
// исходники packages/ и apps/ (ts/tsx, без тестов и сборки) и падает на
// этапе CI, а не в проде (паттерн TRACE_ROUTES PROGR-3: опечатка не
// доходит до рантайма).

import { readFileSync, readdirSync, statSync } from "fs";
import { join } from "path";

const ROOTS = [
  join(__dirname, ".."), // packages/ui
  join(__dirname, "..", "..", "..", "apps"), // apps/* (standalone/embedded/api-фронт)
];

// Хелперы, ДОБАВЛЯЮЩИЕ /v1-префикс сами; аргумент начинается с "/" без /v1.
const BAD_PATTERN = /(apiUrl|sessionApiUrl|progressApiUrl)\(\s*[`"']\/v1/;

function collectSources(dir: string, acc: string[] = []): string[] {
  let entries: string[];
  try {
    entries = readdirSync(dir);
  } catch {
    return acc; // отсутствующая директория -- не повод ронять guard
  }
  for (const name of entries) {
    if (name === "node_modules" || name === ".next" || name === ".git") continue;
    const full = join(dir, name);
    const stat = statSync(full);
    if (stat.isDirectory()) {
      collectSources(full, acc);
    } else if (
      /\.(ts|tsx)$/.test(name) &&
      !name.endsWith(".test.ts") &&
      !name.endsWith(".test.tsx")
    ) {
      acc.push(full);
    }
  }
  return acc;
}

describe("PROGR-15-A guard: ручное вложение /v1 в аргументы *ApiUrl запрещено", () => {
  it("ни один исходник фронтенда не содержит *ApiUrl(\"/v1...\") -- класс дефекта двойного префикса", () => {
    const offenders: string[] = [];
    for (const root of ROOTS) {
      for (const file of collectSources(root)) {
        if (BAD_PATTERN.test(readFileSync(file, "utf8"))) {
          offenders.push(file);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});
