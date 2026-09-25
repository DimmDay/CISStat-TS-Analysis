"use client";

// packages/ui/components/ProgressDrawer.tsx
//
// Контейнер правой панели «Прогресс» (Task PROGR-4, spec_progress.md
// §6.1-§6.2 + аддендум §4.2). Механика -- прямой повтор архитектуры
// EventsLogDrawer (fixed top-0 right-0 h-full, транзишн translate-x,
// затемнение bg-black/20 закрывает по клику вне панели, крестик в
// правом верхнем углу), ширина -- ровно в два раза шире w-80:
// w-[40rem] (аддендум §4.2 -- 2×w-80 не совпадает с именованным
// токеном Tailwind, поэтому произвольный класс).
//
// Шапка §6.1: датасет (activeDataset из AppShellContext), признак
// (target_column -- отдаётся GET /v1/session/current, §6.1: «поле есть,
// новых данных не требуется»), календарная дата открытия (клиентский
// рендер), run_id («новое, см. §5») и «Начат N мин назад» (в слое 1 --
// ts первого события; research_runs.created_at придёт с PROGR-5).
//
// Данные: GET /v1/progress/trace (слой 1, apps/api/routers/progress.py)
// + GET /v1/session/modeling/forecast (события ForecastRun.trace, §3) --
// слияние и хронологическая сортировка в lib/progress.ts. Запросы
// best-effort (паттерн хука PROGR-3): сбой сети не роняет панель.
//
// Кнопки «Пауза»/«Сохранить точку»/«Наставник» (§6.2) -- не в объёме
// PROGR-4: пауза/чекпоинты -- PROGR-5, Наставник -- PROGR-6 (§6.3,
// план_progress.md); без бэкенда они были бы мёртвыми элементами.

import { useCallback, useEffect, useState } from "react";
import { useAppShell } from "../context/AppShellContext";
import { progressApiUrl, sessionApiUrl } from "../lib/apiClient";
import {
  collectForecastTraceEvents,
  sortEventsChronologically,
  type TraceEventInfo,
} from "../lib/progress";
import { ProgressStageFlow } from "./ProgressStageFlow";
import { ProgressTraceLog } from "./ProgressTraceLog";

interface ProgressTraceState {
  loading: boolean;
  runId: string | null;
  startedAt: string | null;
  events: TraceEventInfo[];
}

const EMPTY_TRACE: ProgressTraceState = {
  loading: false,
  runId: null,
  startedAt: null,
  events: [],
};

function startedAgoLabel(startedAt: string | null): string {
  if (!startedAt) return "";
  const started = new Date(startedAt).getTime();
  if (Number.isNaN(started)) return "";
  const minutes = Math.floor((Date.now() - started) / 60000);
  if (minutes < 1) return "Начат менее минуты назад";
  return `Начат ${minutes} мин назад`;
}

export function ProgressDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { activeDataset, targetColumn } = useAppShell();
  const [trace, setTrace] = useState<ProgressTraceState>(EMPTY_TRACE);
  const [traceExpanded, setTraceExpanded] = useState(false);
  // Контент монтируется с первого открытия и остаётся (плавное
  // закрывание, как у EventsLogDrawer); на никогда не открывавшейся
  // панели содержимого нет -- закрытая панель не дублирует тексты
  // стадий в DOM рядом с бейджами меню.
  const [hasOpened, setHasOpened] = useState(false);
  // Календарная дата открытия панели (§6.1) -- только клиентский рендер
  // при открытой панели: setState в эффекте исключает SSR-расхождение.
  const [openedDate, setOpenedDate] = useState<string>("");

  useEffect(() => {
    if (open) setHasOpened(true);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setOpenedDate(new Date().toLocaleDateString("ru-RU"));

    const load = async (): Promise<void> => {
      setTrace((previous) => ({ ...previous, loading: true }));
      try {
        // Слой 1 (§5) + события Прогнозирования (§3: ForecastRun.trace --
        // унификация хранения в PROGR-5); оба запроса независимы.
        const [traceResp, forecastResp] = await Promise.all([
          fetch(progressApiUrl("/trace"), { credentials: "include" }),
          fetch(sessionApiUrl("/modeling/forecast"), { credentials: "include" }),
        ]);
        const traceData = traceResp.ok ? await traceResp.json() : null;
        const forecastData = forecastResp.ok ? await forecastResp.json() : null;
        if (cancelled) return;
        const layer1: TraceEventInfo[] = traceData?.events ?? [];
        const forecastEvents = collectForecastTraceEvents(forecastData?.forecasts ?? []);
        setTrace({
          loading: false,
          runId: traceData?.run_id ?? null,
          startedAt: traceData?.started_at ?? null,
          events: sortEventsChronologically([...layer1, ...forecastEvents]),
        });
      } catch {
        // Бэкенд недоступен -- панель остаётся с пустой трассой и
        // прочерками шапки (best-effort, §4.2: трасса вспомогательна).
        if (!cancelled) setTrace((previous) => ({ ...previous, loading: false }));
      }
    };
    void load();

    return () => {
      cancelled = true;
    };
  }, [open]);

  const handleBackdropClick = useCallback(() => onClose(), [onClose]);
  const handleToggleTrace = useCallback(() => setTraceExpanded((v) => !v), []);

  return (
    <>
      {/* Затемнение фона -- закрывает панель по клику вне неё (§6.1 дословно) */}
      {open && (
        <div className="fixed inset-0 bg-black/20 z-40" onClick={handleBackdropClick} aria-hidden />
      )}

      <aside
        id="progress-drawer"
        aria-label="Прогресс исследования"
        className={`fixed top-0 right-0 h-full w-[40rem] max-w-full bg-white shadow-xl z-50 transform transition-transform duration-200 ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        {!hasOpened ? null : (
          <>
        <div className="flex items-center justify-between px-4 py-3 border-b border-neutral-200">
          <h3 className="font-semibold">Прогресс исследования</h3>
          <button
            onClick={onClose}
            aria-label="Закрыть"
            className="text-neutral-500 hover:text-neutral-900"
          >
            ✕
          </button>
        </div>

        <div className="border-b border-neutral-100 px-4 py-2 text-sm text-neutral-600">
          <p>
            Датасет: {activeDataset?.name ?? "—"} · Признак: {targetColumn ?? "—"}
            {openedDate && <span> · {openedDate}</span>}
          </p>
          <p className="mt-0.5 text-xs text-neutral-500">
            Запуск:{" "}
            <span className="font-mono">{trace.runId ?? "—"}</span>
            {trace.startedAt && <span> · {startedAgoLabel(trace.startedAt)}</span>}
          </p>
        </div>

        <div className="overflow-y-auto h-[calc(100%-96px)] feed-scroll">
          <ProgressStageFlow events={trace.events} />

          <div className="px-4 pb-2">
            <button
              type="button"
              onClick={handleToggleTrace}
              aria-expanded={traceExpanded}
              className="text-sm text-neutral-600 hover:text-neutral-900"
            >
              Развернуть трассу {traceExpanded ? "▴" : "▾"}
            </button>
          </div>

          {traceExpanded && <ProgressTraceLog events={trace.events} />}
        </div>
          </>
        )}
      </aside>
    </>
  );
}
