"use client";

// packages/ui/components/ProgressCheckpointBar.tsx
//
// Полоса действий панели «Прогресс» (Task PROGR-5.1, spec_progress.md
// §6.2-§6.3: «Кнопки „Пауза"/„Сохранить точку"/„Наставник"»; §5.1-§5.2 --
// семантика чекпоинтов и паузы). Бэкенд -- контракт PROGR-5
// (apps/api/routers/progress.py, namespace /v1/progress/runs/{run_id}):
//
//   POST .../pause       (§5.2)  явная фиксация run.status="paused";
//                                только из active (иначе 409 -- ошибка
//                                клиента, поэтому кнопка disabled заранее
//                                для completed/abandoned/паузы)
//   POST .../resume      (§5.2)  возврат к работе, только из paused
//   POST .../checkpoints (§5.1)  {event_id, label?} -- именованная ссылка
//                                на событие ЭТОГО запуска (404 на чужое);
//                                якорь -- последнее событие с event_id
//                                («текущий момент»), label опционален
//
// Кнопка «Наставник» (§6.2/§6.3) -- сознательно НЕ рендерится: её бэкенд --
// отдельная задача PROGR-6 (plan_progress.md); мёртвых кнопок в панели нет
// (решение PROGR-4, здесь продолжено).
//
// N-2 (находка PROGR-4): run-level события (run_paused/run_resumed/
// checkpoint_saved, node_id=null) компонентом никуда не кладутся -- статусы
// узлов считаются в lib/progress.ts только по узловым событиям, своды
// стадий не затрагиваются. N-4: никаких семантик закрытия/навигации --
// об успехе родитель (ProgressDrawer) узнаёт только через onChanged()
// (обновление данных), панель не закрывается.
//
// Ошибки (409/404/503/сеть) -- inline role="alert" (best-effort, паттерн
// панели PROGR-4: сбой сети/слоя 2 не роняет панель).

import { useCallback, useState } from "react";
import {
  runStatusLabel,
  type CheckpointInfo,
  type TraceEventInfo,
} from "../lib/progress";
import { progressApiUrl } from "../lib/apiClient";

interface ProgressCheckpointBarProps {
  runId: string | null;
  /** Статус запуска слоя 2 (null -- деталь запуска недоступна: 503/404/загрузка). */
  status: string | null;
  /** Последнее событие с event_id -- якорь нового чекпоинта (§5.1). */
  lastEvent: TraceEventInfo | null;
  /** Сохранённые чекпоинты запуска (GET /v1/progress/runs/{run_id}). */
  checkpoints: CheckpointInfo[];
  /** Уведомление родителя об успешном действии: обновить трассу слоя 1
   * (run-level событие зеркалится в неё) и деталь запуска слоя 2. */
  onChanged: () => void;
}

/** Действия имеют смысл только для живого запуска (§5.1/§5.2: pause --
 * только из active, checkpoint -- не для completed/abandoned). Неизвестный
 * статус (слой 2 недоступен: 503/404/сеть) тоже блокирует: бэкенд гарантированно
 * откажет (503/404) -- «гарантированный отказ не кликается» (паттерн панели). */
function runAcceptsActions(status: string | null): boolean {
  return status === "active" || status === "paused";
}

function formatCheckpointTime(ts: string): string {
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return ts;
  return date.toLocaleTimeString("ru-RU");
}

export function ProgressCheckpointBar({
  runId,
  status,
  lastEvent,
  checkpoints,
  onChanged,
}: ProgressCheckpointBarProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<string | null>(null);
  const [checkpointFormOpen, setCheckpointFormOpen] = useState(false);
  const [checkpointLabel, setCheckpointLabel] = useState("");

  const actionsAvailable = runId !== null && runAcceptsActions(status);

  const post = useCallback(
    async (path: string, body?: Record<string, unknown>): Promise<Record<string, unknown> | null> => {
      if (!runId) return null;
      setBusy(true);
      setError(null);
      try {
        const response = await fetch(progressApiUrl(`/runs/${runId}${path}`), {
          method: "POST",
          credentials: "include",
          headers: body ? { "Content-Type": "application/json" } : undefined,
          body: body ? JSON.stringify(body) : undefined,
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          const detail =
            typeof (payload as { detail?: unknown })?.detail === "string"
              ? (payload as { detail: string }).detail
              : `Ошибка ${response.status}`;
          setError(detail);
          return null;
        }
        return payload as Record<string, unknown>;
      } catch {
        setError("Сеть недоступна; действие не выполнено");
        return null;
      } finally {
        setBusy(false);
      }
    },
    [runId],
  );

  const handlePauseResume = useCallback(async () => {
    if (!runId) return;
    const paused = status === "paused";
    const payload = await post(paused ? "/resume" : "/pause");
    if (payload !== null) onChanged();
  }, [runId, status, post, onChanged]);

  const handleOpenCheckpointForm = useCallback(() => {
    setConfirmation(null);
    setError(null);
    setCheckpointLabel("");
    setCheckpointFormOpen(true);
  }, []);

  const handleSaveCheckpoint = useCallback(async () => {
    if (!runId || !lastEvent?.event_id) return;
    const payload = await post("/checkpoints", {
      event_id: lastEvent.event_id,
      label: checkpointLabel.trim(),
    });
    if (payload !== null) {
      setCheckpointFormOpen(false);
      setCheckpointLabel("");
      const label = checkpointLabel.trim();
      setConfirmation(
        label
          ? `Контрольная точка сохранена: «${label}»`
          : "Контрольная точка сохранена",
      );
      onChanged();
    }
  }, [runId, lastEvent, checkpointLabel, post, onChanged]);

  return (
    <div
      role="group"
      aria-label="Действия исследования"
      className="border-b border-neutral-100 px-4 py-2"
    >
      <div className="flex items-center gap-2">
        {status && (
          <span
            className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
              status === "paused"
                ? "bg-amber-50 text-amber-700"
                : status === "active"
                  ? "bg-green-50 text-green-700"
                  : "bg-neutral-100 text-neutral-600"
            }`}
          >
            {runStatusLabel(status)}
          </span>
        )}

        <button
          type="button"
          onClick={() => void handlePauseResume()}
          disabled={!actionsAvailable || busy}
          className="rounded-full border border-brand px-3 py-1 text-xs font-medium text-brand hover:bg-brand/5 disabled:cursor-not-allowed disabled:border-neutral-200 disabled:text-neutral-400"
        >
          {status === "paused" ? "Продолжить" : "Пауза"}
        </button>

        <button
          type="button"
          onClick={handleOpenCheckpointForm}
          disabled={!actionsAvailable || !lastEvent?.event_id || busy}
          title={
            lastEvent?.event_id
              ? "Сохранить именованную ссылку на текущее событие (§5.1)"
              : "Нечего фиксировать: в трассе ещё нет событий"
          }
          className="rounded-full border border-brand px-3 py-1 text-xs font-medium text-brand hover:bg-brand/5 disabled:cursor-not-allowed disabled:border-neutral-200 disabled:text-neutral-400"
        >
          Сохранить точку
        </button>
      </div>

      {checkpointFormOpen && (
        <form
          className="mt-2 rounded border border-neutral-200 bg-neutral-50 p-2"
          onSubmit={(e) => {
            e.preventDefault();
            void handleSaveCheckpoint();
          }}
        >
          <label htmlFor="progress-checkpoint-label" className="block text-xs text-neutral-600">
            Комментарий (необязательно)
          </label>
          <input
            id="progress-checkpoint-label"
            type="text"
            value={checkpointLabel}
            onChange={(e) => setCheckpointLabel(e.target.value)}
            placeholder="Например: перед экспериментом со сглаживанием"
            className="mt-1 w-full rounded border border-neutral-200 px-2 py-1 text-sm"
          />
          <div className="mt-2 flex items-center gap-2">
            <button
              type="submit"
              disabled={busy}
              className="rounded-full bg-brand px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
            >
              Сохранить
            </button>
            <button
              type="button"
              onClick={() => setCheckpointFormOpen(false)}
              className="text-xs text-neutral-500 hover:text-neutral-900"
            >
              Отмена
            </button>
          </div>
        </form>
      )}

      {error && (
        <p role="alert" className="mt-2 text-xs text-red-600">
          {error}
        </p>
      )}
      {!error && confirmation && <p className="mt-2 text-xs text-green-700">{confirmation}</p>}

      {checkpoints.length > 0 && (
        <ul className="mt-2 space-y-1" aria-label="Сохранённые контрольные точки">
          {checkpoints.map((checkpoint) => (
            <li key={checkpoint.checkpoint_id} className="text-xs text-neutral-600">
              <span className="font-medium text-neutral-800">
                {checkpoint.label || "Без комментария"}
              </span>
              {" · "}
              <time dateTime={checkpoint.created_at}>
                {formatCheckpointTime(checkpoint.created_at)}
              </time>
              {checkpoint.has_snapshot && " · снимок данных"}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
