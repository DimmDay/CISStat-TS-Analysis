// packages/ui/lib/stopLinks.ts
//
// Узловые deep-link Наставника «Следующий шаг» (Task MNS-LINK-3, план
// docs/mentor_next_step_review_2026-10-19.md §6; контракт --
// spec_mentor_next_step.md §5.3, решение Q6: «deep-link на остановку --
// якорь/параметр степпера модуля; фолбэк на вкладку стадии»).
//
// Механизм -- ЯКОРЬ #stop=<node_id>:
// - чтение при монтировании степпера -- cross-stage переход, перезагрузка,
//   закладка/шаринг ссылки;
// - подписка hashchange -- back/forward браузера;
// - явное событие GOTO_STOP_EVENT из onClick ссылки MentorPanel --
//   детерминированный same-route переход (панель «Прогресс» доступна на
//   всех модульных страницах; клиентская навигация Next по якорю не
//   порождает hashchange гарантированно -- pushState события не стреляет).
//
// FAIL-CLOSED WHITELIST (паттерн allowlist-перехвата PROGR-3): узел
// принимается только если он -- известная остановка ИМЕННО этой стадии.
// Источник whitelist -- PROGRESS_STAGE_NODES (lib/progress.ts, единый
// реестр с бэкенд-графом; sync страхует test_progress_panel.py) -- копий
// реестра здесь нет. Неизвестное значение не падает и не угадывается.
//
// Переход по рекомендации -- СОВЕТ, не факт (§3.2 spec_progress.md):
// событие в трассу не пишется, новых событий/запросов нет.

import { PROGRESS_STAGE_NODES } from "./progress";

// ── Warning-способные стадии канона mns_canon_v2 ─────────────────────

/** Стадии, чьи остановки принимают узловый deep-link: РОВНО три
 * warning-способные стадии канона (spec_mentor_next_step.md §3.1;
 * решения Q3/Q4: eda/modeling/forecasting warning-семантики не имеют,
 * рекомендации остальных стадий -- фолбэк на вкладку стадии). Порядок --
 * порядок STAGES. Гвард состава и покрытия 25 остановок --
 * stopLinks.test.ts. */
export const DEEP_LINK_STOP_STAGES: readonly string[] = [
  "upload",
  "validation",
  "preprocessing",
];

// ── Якорь остановки ──────────────────────────────────────────────────

/** Якорь остановки степпера: «#stop=<node_id>» (контракт MNS-LINK-3).
 * Узел кодируется честно (encodeURIComponent); известные node_id --
 * [a-z_], кодировка для них тождественна. */
export function stopAnchor(nodeId: string): string {
  return `#stop=${encodeURIComponent(nodeId)}`;
}

/** Парс якоря с fail-closed whitelist: узел обязан быть известной
 * остановкой СТРОГО этой стадии (PROGRESS_STAGE_NODES), иначе null --
 * степпер остаётся на дефолтной остановке. Формат: «#stop=<node_id>»;
 * тело якоря парсится как query (URLSearchParams), кодировка
 * декодируется автоматически. Без исключений и угадывания. */
export function stopFromHash(
  hash: string | null | undefined,
  stage: string,
): string | null {
  if (typeof hash !== "string" || !hash.startsWith("#")) return null;
  const value = new URLSearchParams(hash.slice(1)).get("stop");
  if (!value) return null;
  return (PROGRESS_STAGE_NODES[stage] ?? []).includes(value) ? value : null;
}

// ── Same-route переход (MentorPanel -> степпер той же вкладки) ───────

/** Явное событие перехода на остановку внутри уже смонтированного
 * степпера. Детали -- GotoStopDetail; степперы фильтруют по своей
 * стадии (событие чужой стадии игнорируется). */
export const GOTO_STOP_EVENT = "cisstat:goto-stop";

export interface GotoStopDetail {
  stage: string;
  node_id: string;
}

/** Диспатч события перехода (best-effort: без window -- no-op, SSR). */
export function dispatchGotoStop(stage: string, nodeId: string): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent<GotoStopDetail>(GOTO_STOP_EVENT, {
      detail: { stage, node_id: nodeId },
    }),
  );
}
