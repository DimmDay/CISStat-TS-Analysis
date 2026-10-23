// apps/standalone/app/documentation/page.tsx
//
// DOCLOG-4 (спека §12.1): страница раздела «Документы исследования».
// Глубокие ссылки -- stage entry points: /documentation?run=RUN-…&kind=D07
// (из «Прогресса» -- «Открыть отчёт истории», из оболочки -- бейдж
// «Документы»). Открытие страницы НЕ создаёт документ фактом открытия
// (§12.1) -- workspace только читает.
//
// Клиентский контур вынесен в documentation-client.tsx («use client»):
// useSearchParams требует клиентского компонента, страница остаётся
// серверной (паттерн Next.js App Router).

import { Suspense } from "react";
import { DocumentationClient } from "./documentation-client";

type SearchParams = Promise<{ run?: string; kind?: string }>;

export default function DocumentationPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  return (
    <div className="mx-auto w-full max-w-[1600px]">
      <header className="mb-4">
        <h1 className="text-xl font-semibold text-neutral-900 dark:text-neutral-100">
          Документы исследования
        </h1>
        <p className="mt-1 max-w-3xl text-sm text-neutral-600 dark:text-neutral-400">
          Замороженные снимки исследования (D01–D09): планы, паспорта,
          протоколы, записки EDA, карточки моделей и выпуски прогноза.
          Просмотр и скачивание не меняют состояние исследования; сборка
          формата выполняется поверх зафиксированной версии.
        </p>
      </header>
      <Suspense
        fallback={
          <p role="status" className="text-sm text-neutral-500">
            Загрузка документов…
          </p>
        }
      >
        <DocumentationPageContent searchParams={searchParams} />
      </Suspense>
    </div>
  );
}

async function DocumentationPageContent({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  return (
    <Suspense
      fallback={
        <p role="status" className="text-sm text-neutral-500">
          Загрузка документов…
        </p>
      }
    >
      <DocumentationClient initialRunId={params.run ?? null} initialKind={params.kind ?? null} />
    </Suspense>
  );
}
