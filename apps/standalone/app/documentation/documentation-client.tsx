// apps/standalone/app/documentation/documentation-client.tsx
//
// DOCLOG-4: клиентская обвязка страницы «Документы исследования».
// Отдельный файл ("use client") -- серверная страница читает searchParams
// (Next.js App Router) и передаёт начальные значения пропсами; внутри --
// DocumentationWorkspace из @cisstat/ui (общий компонент standalone и
// embedded).
//
// C01 (DOCLOG-E2E-RECHECK-1-FIX): URL ?run= имеет приоритет; при его
// отсутствии страница разрешает ТЕКУЩЕЕ исследование (GET
// /v1/progress/trace -- тот же единый источник run_id слоя 1, что у
// ProgressDrawer) и передаёт его в Workspace. Пустой query больше не
// маскируется под пустой реестр документов: если текущего run нет,
// Workspace показывает честное no-run-состояние с подсказкой (акт §9.1).

"use client";

import { useEffect, useState } from "react";
import { DocumentationWorkspace, resolveCurrentRun } from "@cisstat/ui";

export function DocumentationClient({
  initialRunId,
  initialKind,
}: {
  initialRunId: string | null;
  initialKind: string | null;
}) {
  // C01: runId == undefined -- резолв ещё идёт (Workspace в loading);
  // null -- резолв выполнен, текущего run нет (честный no-run);
  // строка -- URL-параметр либо разрешённый текущий run.
  const [runId, setRunId] = useState<string | null | undefined>(
    initialRunId === null ? undefined : initialRunId,
  );

  useEffect(() => {
    if (initialRunId) {
      setRunId(initialRunId);
      return;
    }
    let cancelled = false;
    resolveCurrentRun().then((result) => {
      if (cancelled) return;
      setRunId(result.ok ? result.data?.run_id ?? null : null);
    });
    return () => {
      cancelled = true;
    };
  }, [initialRunId]);

  if (runId === undefined) {
    return (
      <p role="status" className="text-sm text-neutral-500">
        Определение текущего исследования…
      </p>
    );
  }
  return <DocumentationWorkspace runId={runId} initialKind={initialKind} />;
}
