"use client";

// packages/ui/components/EmbeddedHome.tsx
//
// Sessions-aware стартовая страница embedded-режима. Задача -- ориентация
// и продолжение, НЕ продажа (пользователь уже внутри портала, по решению
// тимлида). Если в сессии есть активный датасет -- сразу "Рабочий стол"
// (WorkbenchSummary); если нет -- онбординг: превью шести этапов
// (некликабельно, мини-версия ModuleNav) + "Загрузить датасет" +
// "Попробовать на демо-данных" (снимает барьер "нет файла под рукой,
// чтобы оценить инструмент").
//
// Не содержит auth-логики -- в embedded-режиме пользователь уже внутри
// портала (сотрудник CISStat), доступ регулируется на уровне портала,
// не здесь (см. ROLES_AND_PLANS_SPEC.md).

import { useState } from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { useAppShell } from "../context/AppShellContext";
import { STAGE_DEFS } from "../lib/stages";
import { sessionApiUrl } from "../lib/apiClient";
import { WorkbenchSummary } from "./WorkbenchSummary";
import { Button } from "./Button";

export function EmbeddedHome() {
  const { activeDataset, stages, lastActiveStage, sessionLoading, refreshSession } = useAppShell();
  const [loadingDemo, setLoadingDemo] = useState(false);
  const [demoError, setDemoError] = useState<string | null>(null);

  const handleTryDemo = async () => {
    setLoadingDemo(true);
    setDemoError(null);
    try {
      const resp = await fetch(sessionApiUrl("/demo"), { method: "POST", credentials: "include" });
      if (!resp.ok) {
        throw new Error("Не удалось загрузить демо-датасет");
      }
      await refreshSession();
    } catch (e) {
      setDemoError(e instanceof Error ? e.message : "Неизвестная ошибка");
    } finally {
      setLoadingDemo(false);
    }
  };

  if (sessionLoading) {
    return (
      <div className="flex items-center gap-2 text-neutral-500 text-sm py-10">
        <Loader2 size={16} className="animate-spin" aria-hidden="true" /> Загрузка сессии…
      </div>
    );
  }

  if (activeDataset) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-xl font-semibold text-neutral-900">CISStat TS Analysis</h1>
          <p className="text-neutral-600 text-sm mt-1">Раздел портала: анализ временных рядов.</p>
        </div>
        <WorkbenchSummary dataset={activeDataset} stages={stages} lastActiveStage={lastActiveStage} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-neutral-900">CISStat TS Analysis</h1>
        <p className="text-neutral-600 text-sm mt-1 max-w-xl">
          Анализ временных рядов в шесть этапов — от загрузки данных до прогноза.
        </p>
      </div>

      {/* Превью этапов -- некликабельно, только ориентация, не навигация */}
      <ol className="flex flex-wrap items-center gap-2" aria-label="Этапы анализа (превью)">
        {STAGE_DEFS.map((stage, i) => (
          <li key={stage.key} className="flex items-center gap-2">
            <span className="inline-flex items-center rounded-full border border-neutral-200 bg-white px-3 py-1 text-xs text-neutral-600">
              {i + 1}. {stage.label}
            </span>
            {i < STAGE_DEFS.length - 1 && <span className="text-neutral-300">→</span>}
          </li>
        ))}
      </ol>

      <div className="flex flex-wrap items-center gap-3">
        <Link
          href="/data/upload"
          className="inline-block bg-brand text-white rounded px-4 py-2 text-sm font-medium hover:bg-brand/90 transition-colors"
        >
          Загрузить датасет →
        </Link>
        <Button onClick={handleTryDemo} disabled={loadingDemo} variant="secondary">
          {loadingDemo ? "Загружаем демо…" : "Попробовать на демо-данных"}
        </Button>
      </div>
      {demoError && <p className="text-sm text-red-600">{demoError}</p>}
    </div>
  );
}
