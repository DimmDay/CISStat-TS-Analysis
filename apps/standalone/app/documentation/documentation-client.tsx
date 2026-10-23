// apps/standalone/app/documentation/documentation-client.tsx
//
// DOCLOG-4: клиентская обвязка страницы «Документы исследования».
// Отдельный файл ("use client") -- серверная страница читает searchParams
// (Next.js App Router) и передаёт начальные значения пропсами; внутри --
// DocumentationWorkspace из @cisstat/ui (общий компонент standalone и
// embedded).

"use client";

import { DocumentationWorkspace } from "@cisstat/ui";

export function DocumentationClient({
  initialRunId,
  initialKind,
}: {
  initialRunId: string | null;
  initialKind: string | null;
}) {
  return (
    <DocumentationWorkspace runId={initialRunId} initialKind={initialKind} />
  );
}
