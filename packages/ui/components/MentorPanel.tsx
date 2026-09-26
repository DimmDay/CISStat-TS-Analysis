"use client";

// packages/ui/components/MentorPanel.tsx
//
// Панель «Наставник» внутри правой панели «Прогресс» (Task PROGR-6,
// spec_progress.md §6.2 макет: «[Сохранить точку]  [Наставник →]»,
// §6.3 MentorPanel.tsx; §7.1 «Следующий шаг»). Открывается кнопкой
// полосы действий (ProgressCheckpointBar, слот справа -- макет §6.2),
// данные -- GET /v1/progress/runs/{run_id}/mentor/next-step (PROGR-6).
//
// Состав ответа §7.1: ОДНА рекомендация (первое сработавшее правило по
// priority) + текст пояснения текущей фазы + краткая сводка узлов
// стадии (пересказ уже посчитанного); здесь же -- history-предупреждения
// on_demand_with_history (§7.2 «мечется»: показываются в панели,
// не инлайн в Мастере).
//
// N-4: панель «Прогресс» НЕ закрывается -- компонент не имеет onClose;
// recommended_action («stage.node_id») превращается в deep-link на
// вкладку стадии (Link на href из STAGE_DEFS -- тот же механизм, что у
// ProgressStageFlow §6.2 «клик по узлу -- переход на вкладку»).
// Запросы best-effort: сбой -- честная надпись «недоступен», панель
// «Прогресс» не падает.

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { fetchMentorNextStep, type MentorNextStepInfo, type SanityWarningInfo } from "../lib/mentor";
import { stageLabel } from "../lib/progress";
import { STAGE_DEFS } from "../lib/stages";

interface MentorPanelProps {
  runId: string;
}

/** deep-link рекомендации: «preprocessing.regularity» -> href вкладки
 * «Предобработка». Неизвестная стадия -- null (chip без ссылки). */
export function recommendedStageHref(recommendedAction: string | null | undefined): string | null {
  if (!recommendedAction) return null;
  const stage = recommendedAction.split(".")[0];
  return STAGE_DEFS.find((def) => def.key === stage)?.href ?? null;
}

function HistoryWarningItem({ warning }: { warning: SanityWarningInfo }) {
  return (
    <li className="rounded bg-neutral-50 p-2 text-xs text-neutral-700" role="status">
      {warning.message}
    </li>
  );
}

export function MentorPanel({ runId }: MentorPanelProps) {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<MentorNextStepInfo | null>(null);
  // null -- запрос не удался (503/404/сеть): честная недоступность,
  // а не пустая «рекомендаций нет» (разные состояния UI).
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    const next = await fetchMentorNextStep(runId);
    if (next === null) {
      setFailed(true);
      setData(null);
    } else {
      setData(next);
    }
    setLoading(false);
  }, [runId]);

  useEffect(() => {
    void load();
  }, [load]);

  const href = recommendedStageHref(data?.recommendation?.recommended_action);

  return (
    <section
      id="mentor-panel"
      aria-label="Наставник"
      className="border-b border-neutral-100 px-4 py-3"
    >
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold text-neutral-800">Наставник</h4>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="text-xs text-neutral-500 hover:text-neutral-900 disabled:cursor-not-allowed disabled:text-neutral-300"
        >
          {loading ? "Загрузка…" : "Обновить"}
        </button>
      </div>

      {loading && <p className="mt-2 text-sm text-neutral-400">Наставник думает…</p>}

      {!loading && failed && (
        <p role="alert" className="mt-2 text-xs text-red-600">
          Наставник недоступен; попробуйте обновить позже.
        </p>
      )}

      {!loading && data && (
        <>
          <p className="mt-1.5 text-xs text-neutral-500">{data.phase_text}</p>

          {data.recommendation ? (
            <div className="mt-2 rounded border border-amber-200 bg-amber-50 p-2">
              <p className="text-xs font-medium text-neutral-800">Следующий шаг</p>
              <p className="mt-0.5 text-xs text-neutral-700">{data.recommendation.message}</p>
              {href ? (
                <Link
                  href={href}
                  className="mt-1.5 inline-block text-xs font-medium text-brand underline hover:no-underline"
                >
                  Перейти: {stageLabel(data.recommendation.stage)} →
                </Link>
              ) : (
                <p className="mt-1.5 text-[11px] text-neutral-500">
                  Рекомендация: {data.recommendation.recommended_action}
                </p>
              )}
            </div>
          ) : (
            <p className="mt-2 rounded bg-green-50 p-2 text-xs text-green-700">
              Критичных подсказок нет — исследование идёт по плану.
            </p>
          )}

          {data.history_warnings.length > 0 && (
            <div className="mt-2">
              <p className="text-xs font-medium text-neutral-800">Замечания по истории решений</p>
              <ul className="mt-1 space-y-1">
                {data.history_warnings.map((warning) => (
                  <HistoryWarningItem key={warning.rule_id} warning={warning} />
                ))}
              </ul>
            </div>
          )}

          <p className="mt-2 text-[11px] text-neutral-500">
            Стадия «{stageLabel(data.summary.stage)}»: {data.summary.done_count}/
            {data.summary.total_nodes} пройдено
            {data.summary.warning_nodes > 0 && `, с замечаниями: ${data.summary.warning_nodes}`}.
          </p>
        </>
      )}
    </section>
  );
}
