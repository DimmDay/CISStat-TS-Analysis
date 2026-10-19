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
// recommended_action («stage.node_id») превращается в deep-link.
// MNS-LINK-3 (spec_mentor_next_step.md §5.3, Q6): известный узел
// warning-способной стадии -- якорь остановки степпера «#stop=<node_id>»
// (resolveRecommendationLink); процессные стадии и неизвестный узел --
// прежний фолбэк на вкладку стадии (recommendedStageHref, контракт «как
// сейчас»); неизвестная стадия -- chip без ссылки. Same-route переход
// (панель доступна на всех вкладках) -- явным событием GOTO_STOP_EVENT
// (lib/stopLinks.ts): клиентская навигация Next по якорю не порождает
// hashchange гарантированно.
// Запросы best-effort: сбой -- честная надпись «недоступен», панель
// «Прогресс» не падает.

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { fetchMentorNextStep, type MentorNextStepInfo, type SanityWarningInfo } from "../lib/mentor";
import { isKnownNode, nodeLabel, stageLabel } from "../lib/progress";
import { STAGE_DEFS } from "../lib/stages";
import {
  DEEP_LINK_STOP_STAGES,
  dispatchGotoStop,
  stopAnchor,
} from "../lib/stopLinks";

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

/** Разрешение ссылки рекомендации v2 (MNS-LINK-3, spec_mentor_next_step.md
 * §5.3): (1) известный узел warning-способной стадии -- stop-link: якорь
 * остановки «#stop=<node_id>» + метка остановки (nodeLabel -- единый
 * реестр с бэкенд-графом); (2) иначе -- фолбэк «как сейчас» через
 * recommendedStageHref: известная стадия -- вкладка стадии (процессные
 * стадии modeling/forecasting и рекомендации с неизвестным узлом),
 * неизвестная -- null (chip без ссылки). Данные для whitelist -- единый
 * реестр PROGRESS_STAGE_NODES (lib/progress.ts), копий нет. */
export interface RecommendationLink {
  /** "stop" -- якорь остановки; "stage" -- фолбэк на вкладку. */
  kind: "stop" | "stage";
  href: string;
  /** Метка цели: остановки (stop) или стадии (фолбэк). */
  targetLabel: string;
  stage: string;
  /** Узел stop-ссылки; у фолбэка -- null. */
  nodeId: string | null;
}

export function resolveRecommendationLink(
  recommendedAction: string | null | undefined,
): RecommendationLink | null {
  if (!recommendedAction) return null;
  // Прежняя семантика стадии -- split(".")[0] (recommendedStageHref):
  // узел -- всё после первой точки, может быть пустым/составным.
  const stage = recommendedAction.split(".")[0];
  const dotIndex = recommendedAction.indexOf(".");
  const nodeId = dotIndex > 0 ? recommendedAction.slice(dotIndex + 1) : "";
  if (
    DEEP_LINK_STOP_STAGES.includes(stage) &&
    nodeId.length > 0 &&
    isKnownNode(stage, nodeId)
  ) {
    const stageDef = STAGE_DEFS.find((def) => def.key === stage);
    if (stageDef) {
      return {
        kind: "stop",
        href: `${stageDef.href}${stopAnchor(nodeId)}`,
        targetLabel: nodeLabel(stage, nodeId),
        stage,
        nodeId,
      };
    }
  }
  const stageHref = recommendedStageHref(recommendedAction);
  if (!stageHref) return null;
  return { kind: "stage", href: stageHref, targetLabel: stageLabel(stage), stage, nodeId: null };
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

  const link = resolveRecommendationLink(data?.recommendation?.recommended_action);

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
              {link ? (
                <Link
                  href={link.href}
                  // MNS-LINK-3: same-route переход на уже открытой вкладке --
                  // явным событием (якорь Next не порождает hashchange
                  // гарантированно); cross-stage переходы читают якорь
                  // при монтировании новой страницы.
                  onClick={
                    link.kind === "stop" && link.nodeId
                      ? () => dispatchGotoStop(link.stage, link.nodeId as string)
                      : undefined
                  }
                  className="mt-1.5 inline-block text-xs font-medium text-brand underline hover:no-underline"
                >
                  Перейти: {link.targetLabel} →
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
