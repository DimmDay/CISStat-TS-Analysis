"use client";

// packages/ui/components/DocumentPreview.tsx
//
// DOCLOG-4 (спека §12.2-§12.3): панель предпросмотра одной версии.
//
// Безопасность (§12.3/AC16): «HTML/SVG из внешних источников не
// исполняются» -- HTML-рендер сервера изолируется в sandboxed iframe
// (sandbox="" -- БЕЗ allow-scripts/allow-same-origin); src ведёт на
// авторизованный GET /revisions/{id}/preview (тот же first-party /api
// прокси в проде; cookie уходит по same-origin). Переключатели «Кратко /
// Методическое приложение / Основания» -- представления ОДНОЙ версии
// (одно чтение, §12.2), не три документа: данные из уже загруженного
// снимка, новых запросов переключение не требует.
//
// Инспектор основания (§12.2): «внутренние ID доступны по раскрытию, не
// заполняют обычный текст» -- refs рендерятся в блоке «Основания» внутри
// <details> (без JS).

import { useMemo } from "react";
import { revisionPreviewUrl, type SnapshotPayload } from "../lib/documentation";

export type DocumentViewMode = "brief" | "methodology" | "basis";

interface DocumentPreviewProps {
  revisionId: string;
  snapshot: SnapshotPayload;
  viewMode: DocumentViewMode;
}

const VALIDITY_LABELS: Record<string, string> = {
  current: "актуально",
  stale: "устарело",
  unknown: "неизвестно",
};

export function DocumentPreview({ revisionId, snapshot, viewMode }: DocumentPreviewProps) {
  // URL предпросмотра детерминирован версией (одно авторизованное чтение
  // серверного HTML-рендера; переключения представлений его не меняют).
  const previewSrc = useMemo(() => revisionPreviewUrl(revisionId), [revisionId]);

  const methodologyRefs = useMemo(
    () =>
      snapshot.sections
        .map((section) => ({
          code: section.code,
          title: section.title,
          stage: section.methodology_stage,
        }))
        .filter((item) => item.stage),
    [snapshot.sections],
  );

  const claims = useMemo(
    () =>
      snapshot.sections.flatMap((section) =>
        (section.claims ?? []).map((claim) => ({
          section: section.code,
          sectionTitle: section.title,
          ...claim,
          // Контракт -- массивы; старый ответ без полей деградирует честно.
          event_refs: claim.event_refs ?? [],
          result_refs: claim.result_refs ?? [],
        })),
      ),
    [snapshot.sections],
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      {viewMode === "brief" && (
        <iframe
          title={`Предпросмотр документа (версия ${revisionId})`}
          sandbox=""
          src={previewSrc}
          className="h-[520px] w-full rounded-xl border border-neutral-200 bg-white dark:border-neutral-700"
        />
      )}

      {viewMode === "methodology" && (
        <div className="rounded-xl border border-neutral-200 p-3 text-sm dark:border-neutral-700">
          <h3 className="mb-2 font-semibold">Методическое приложение</h3>
          {methodologyRefs.length === 0 && (
            <p className="text-neutral-500">
              Методология-refs в этой версии не зафиксированы (честное отсутствие).
            </p>
          )}
          <ul className="ml-4 list-disc space-y-1">
            {methodologyRefs.map((item) => (
              <li key={item.code}>
                {item.title} ({item.code}) — этап{" "}
                <code className="font-mono text-xs">{item.stage}</code>{" "}
                <span className="text-xs text-neutral-500">
                  (ref реестра знаний; версия снимка {snapshot.knowledge_version ?? "—"})
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {viewMode === "basis" && (
        <div className="rounded-xl border border-neutral-200 p-3 text-sm dark:border-neutral-700">
          <h3 className="mb-2 font-semibold">Основания (proof refs)</h3>
          {claims.length === 0 && (
            <p className="text-neutral-500">Утверждений в этой версии нет.</p>
          )}
          <ul className="space-y-2">
            {claims.map((claim, index) => (
              <li
                key={`${claim.section}-${index}`}
                className="rounded-lg bg-neutral-50 p-2 dark:bg-neutral-800"
              >
                <p>
                  {claim.text}{" "}
                  <span className="text-xs font-medium text-neutral-500">
                    [{VALIDITY_LABELS[claim.validity] ?? claim.validity}]
                  </span>
                </p>
                <p className="mt-1 text-xs text-neutral-500">
                  {claim.sectionTitle} ({claim.section}) ·{" "}
                  {claim.evidence_level ?? "evidence: —"}
                </p>
                {/* Внутренние ID -- по раскрытию (§12.2), <details> без JS */}
                <details className="mt-1 text-xs">
                  <summary className="cursor-pointer text-neutral-500">
                    Ссылки на факты
                  </summary>
                  <ul className="ml-4 mt-1 list-disc font-mono">
                    {claim.event_refs.map((ref) => (
                      <li key={ref}>{ref}</li>
                    ))}
                    {claim.result_refs.map((ref) => (
                      <li key={ref}>{ref}</li>
                    ))}
                    {claim.event_refs.length === 0 && claim.result_refs.length === 0 && (
                      <li className="font-sans">— (refs нет: честный unknown)</li>
                    )}
                  </ul>
                </details>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
