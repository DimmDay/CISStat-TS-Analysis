// apps/standalone/app/documentation/page.tsx
//
// DOCLOG-4 (спека §12.1): страница раздела «Документы исследования».
// Глубокие ссылки -- stage entry points: /documentation?run=RUN-…&kind=D07
// (из «Прогресса» -- «Открыть отчёт истории», из оболочки -- кнопка
// «Документы»). Открытие страницы НЕ создаёт документ фактом открытия
// (§12.1) -- workspace только читает.
//
// Точечные UI-правки (следом за DOCLOG-4) — статическая оболочка страницы
// (фон «О платформе» усечённый сверху, брендовый индиго-заголовок, 24px
// инсеты) вынесена в documentation-shell.tsx: Next.js разрешает page-модулю
// только default export. Асинхронная searchParams-водопроводка не менялась.
//
// Клиентский контур вынесен в documentation-client.tsx («use client»):
// useSearchParams требует клиентского компонента, страница остаётся
// серверной (паттерн Next.js App Router).

import { Suspense } from "react";
import { DocumentationPageShell } from "./documentation-shell";
import { DocumentationClient } from "./documentation-client";

type SearchParams = Promise<{ run?: string; kind?: string }>;

export default function DocumentationPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  return (
    <DocumentationPageShell>
      <Suspense
        fallback={
          <p role="status" className="text-sm text-neutral-500">
            Загрузка документов…
          </p>
        }
      >
        <DocumentationPageContent searchParams={searchParams} />
      </Suspense>
    </DocumentationPageShell>
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
