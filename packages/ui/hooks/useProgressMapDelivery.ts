"use client";

// packages/ui/hooks/useProgressMapDelivery.ts
//
// ЕДИНЫЙ механизм доставки карт статусов четырёх модулей (Загрузка/
// Валидация/Предобработка/EDA) в контур «Прогресса» -- задача AUDIT-2B
// (plan_progress_audit.md §12; контракт docs/progress_audit_contract.md
// аддендум v1.0-2B §20). Заменяет четыре копии «ref-маркер + один
// fetch» (PROGR-13-A5/16-A/17/18), которые не покрывали класс дефектов
// доставки (спека spec_progress_audit.md §5):
//
//   * H26 -- один отказ доставки при неизменном снапшоте оставался без
//     повтора (ref сбрасывался, зависимости effect не менялись);
//   * delivered-маркер ставился ДО ответа (оптимистично) -- «принято»
//     не отличалось от «записано в долговременный слой»;
//   * отчёт не был привязан к контексту расчёта -- P24/F04 на стороне
//     клиента (старое тело принималось новым запуском);
//   * поздние/устаревшие ответы могли сбрасывать маркеры новой
//     вселенной фактов.
//
// Механизм (план §12, состав 1–6):
//
//   1. report-id: каждая поставка получает уникальный report_id
//      (map-<uuid>); retry повторяет ТОТ ЖЕ ключ и payload --
//      серверная идемпотентность AUDIT-2A (контракт §19.3) возвращает
//      прежний receipt без дублей (P07).
//   2. delivered ставится ТОЛЬКО после receipt (200 + mode="v2" +
//      receipt). Acceptance без receipt (легаси-режим) -- честный
//      accepted_legacy, delivered=false. Сброс ref-а не считается
//      механизмом повтора неизменного снапшота: retry -- таймерный,
//      внутри поставки.
//   3. Изоляция stale: каждая POST-попытка несёт токен; поздний ответ
//      устаревшей поставки (после смены снапшота/биндинга или unmount)
//      игнорируется; in-flight запрос абортируется (AbortController).
//      Смена вселенной фактов (map → null → map) перезапрашивает
//      биндинг.
//   4. Дедуп по (run_id, context_id, canonical snapshot), НЕ по имени
//      файла: повторная загрузка одноимённого файла (новый run_id)
//      доставляется заново; тот же снапшот в том же контексте -- нет.
//      anchor-снапшот (EDA-якорь seed'а) считается уже записанным.
//   5. 409 stale_run/stale_context -- refresh биндинга из
//      GET /v1/progress/trace (тот же источник, что проверяет сервер,
//      I3) + ОДНА повторная поставка текущего снапшота с НОВЫМ
//      report_id; повторный 409 -- стоп (не бесконечный повтор старого
//      тела). report_id_conflict / 400 / 404 / 422 -- постоянные ошибки
//      без retry. Механизм ТОЛЬКО доставляет карту: никакие коррекции
//      данных вместе с POST карты не запускаются (план §12 п.5).
//   6. offline/unmount: недоставленность честна (undelivered/stale
//      видны в состоянии хука; UI вправе показать); состояние in-memory
//      в браузере -- перезагрузка страницы НЕ переживается (очередь с
//      TTL не обещается; после remount текущий снапшот доставляется
//      как новое клиентское наблюдение -- ограничение задокументировано,
//      контракт §20.6).
//
// Retry-политика (v2-режим): сетевой отказ / 500–599 -- backoff по
// retryDelaysMs (по умолчанию 500мс/1с/2с; всего до 4 попыток) с тем же
// report_id; исчерпание -- undelivered. Легаси-режим НЕ ретраится:
// серверный legacy-контур без идемпотентности -- повтор задублировал бы
// факты (совместимость до отключения, контракт §19.5).
//
// Перевооружение после сбоя (детерминизм, R1/H26): поставка, завершившаяся
// ошибкой, перевооружается БЕЗ таймера -- сменой вселенной фактов
// (map → null → map: транзитные «running» волны перезапросов PROGR-9-FOCUS
// закрывают/открывают снапшот). Null→non-null переход перезапрашивает
// биндинг; завершение биндинга ставит поставку ПРЯМЫМ путём по refs
// (attemptDeliveryIfDue). Рендер-путь (setBindingVersion → перезапуск
// драйвера) остаётся основным, но НЕ единственным: обработка setState из
// асинхронного колбэка не гарантируется средой (jsdom +
// IS_REACT_ACT_ENVIRONMENT: обновление, вставшее в очередь после закрытия
// последнего act-окна, молча теряется -- updater не вызывается, перезапуск
// драйвера не происходит, поставка после сбоя зависает до следующей волны).
// Идемпотентность путей -- через «возможность поставки»: fetch биндинга
// вооружается на конкретный снапшот (bindingOpportunityRef); прямой путь
// израсходует возможность ровно один раз (bindingOpportunityUsedRef),
// рендер-путь пропускает израсходованную возможность, а pending-гардс и
// дедуп (§12 п.4) добивают остаточные гонки -- двойной POST невозможен
// в любом порядке завершения путей.
//
// Статус доставки -- вспомогательный контур (§12 п.8 spec_progress):
// сбой не ломает модуль и не мешает чтению научного результата; хук
// не выполняет алертов и не блокирует UI.

import { useCallback, useEffect, useRef, useState } from "react";
import { progressApiUrl } from "../lib/apiClient";

export type ProgressMapDeliveryStatus =
  | "idle"            // доставлять нечего (map пуст/вселенная фактов закрыта)
  | "binding"         // получение биндинга (run_id/context_id) из /trace
  | "pending"         // POST отправлен, ответ не получен
  | "delivered"       // 200 + mode="v2" + receipt -- записано долговременно
  | "accepted_legacy" // 200 без receipt (легаси-режим) -- принято best-effort
  | "undelivered"     // исчерпание retry / постоянная ошибка -- НЕ доставлено
  | "stale";          // 409 stale_run/stale_context -- нужен свежий контекст

export interface ProgressMapDeliveryState {
  status: ProgressMapDeliveryStatus;
  /** true ТОЛЬКО после receipt (v2-приёмка); план §12 п.2. */
  delivered: boolean;
  /** Ключ идемпотентности текущей/последней поставки (map-<uuid>). */
  reportId: string | null;
  /** Число сделанных POST-попыток текущей/последней поставки. */
  attempts: number;
  lastError: string | null;
  /** Наблюдаемый биндинг (GET /v1/progress/trace, I3). */
  runId: string | null;
  contextId: string | null;
  /** Принудительная повторная поставка текущего снапшота с НОВЫМ
   * report_id (Upload: ре-пост после подтверждения структуры). */
  redeliver: () => void;
}

export interface ProgressMapDeliveryOptions {
  /** Путь эндпоинта карты: "/upload-stops" | "/validation-checks" | ... */
  endpoint: string;
  /** Ключ карты в теле: "stops" | "checks". */
  bodyKey: string;
  /** Полная карта статусов; null -- доставлять нечего. */
  map: Record<string, string> | null;
  /**
   * Ключ вселенной фактов (datasetId/имя датасета). Смена ключа -- новая
   * вселенная: записанная поставка прежней вселенной не подавляет новую
   * (план §12 п.4 в легаси-фолбэке, где биндинг недоступен и ключ
   * (run, context) не различает запуски; в v2 новый run меняет ключ и
   * без этого параметра). Транзитный null карты (профиль «running»)
   * вселенную НЕ меняет -- фокус-рефетч с неизменной картиной не
   * репортится повторно (семантика прежних маркер-сбросов PROGR-16-A/17).
   */
  universeKey?: string | null;
  /**
   * Снапшот (JSON-строка карты), уже известный как записанный
   * (EDA-якорь seed'а трассы): идентичный текущему снапшот не
   * доставляется повторно.
   */
  anchorSnapshot?: string | null;
  /** Задержки backoff между retry (по умолчанию [500, 1000, 2000]). */
  retryDelaysMs?: number[];
}

interface Binding {
  runId: string;
  contextId: string;
}

interface PendingDelivery {
  reportId: string;
  snapshot: string;
  inFlight: boolean;
}

const DEFAULT_RETRY_DELAYS_MS = [500, 1000, 2000];

/** Каноническая строка карты: сортировка ключей -- дедуп не зависит от
 * порядка построения объекта (реестр везде фиксированный, но дедуп
 * обязан быть устойчивым и к перерендерам, и к рефакторингу). */
function canonicalMapString(map: Record<string, string>): string {
  const keys = Object.keys(map).sort();
  return JSON.stringify(keys.map((key) => [key, String(map[key])]));
}

/** Ключ дедупа поставки: (run, context, snapshot) -- план §12 п.4. */
function deliveryKey(binding: Binding | null, snapshot: string): string {
  return `${binding?.runId ?? ""}|${binding?.contextId ?? ""}|${snapshot}`;
}

/** report_id поставки: map-<uuid> (≤200 символов, контракт §19.1). */
function generateReportId(): string {
  const cryptoRef = globalThis.crypto as Crypto | undefined;
  if (cryptoRef && typeof cryptoRef.randomUUID === "function") {
    return `map-${cryptoRef.randomUUID()}`;
  }
  return `map-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

interface TraceResponseShape {
  run_id?: unknown;
  context_id?: unknown;
}

/** Биндинг из /trace -- ТОТ ЖЕ источник, что проверяет сервер
 * (durable run.context_id, контракт §19.2, I3). Оба поля непустые --
 * иначе null (v2-конверт невозможен → легаси-фолбэк §20.5). */
async function fetchBinding(): Promise<Binding | null> {
  try {
    const response = await fetch(progressApiUrl("/trace"), { credentials: "include" });
    if (!response.ok) return null;
    const data = (await response.json()) as TraceResponseShape | null;
    const observedRunId = typeof data?.run_id === "string" ? data.run_id.trim() : "";
    const observedContextId = typeof data?.context_id === "string" ? data.context_id.trim() : "";
    if (!observedRunId || !observedContextId) return null;
    return { runId: observedRunId, contextId: observedContextId };
  } catch {
    // Биндинг недоступен (сеть/старый бэкенд) -- легаси-фолбэк одним
    // POST (контур фактов не ломается, §12 п.8 spec_progress).
    return null;
  }
}

type PostAttemptFn = (delivery: PendingDelivery) => void;

export function useProgressMapDelivery(
  options: ProgressMapDeliveryOptions,
): ProgressMapDeliveryState {
  const { endpoint, bodyKey, map, universeKey, anchorSnapshot, retryDelaysMs } = options;

  // ── Отражаемое состояние ──
  const [status, setStatus] = useState<ProgressMapDeliveryStatus>("idle");
  const [reportId, setReportId] = useState<string | null>(null);
  const [attempts, setAttempts] = useState(0);
  const [lastError, setLastError] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [contextId, setContextId] = useState<string | null>(null);
  // Версия биндинга и счётчик принудительных поставок -- триггеры
  // драйвера доставки (значения в deps эффекта).
  const [bindingVersion, setBindingVersion] = useState(0);
  const [redeliverTick, setRedeliverTick] = useState(0);

  // ── Служебные refs ──
  const mountedRef = useRef(true);
  const bindingRef = useRef<Binding | null>(null);
  const bindingReadyRef = useRef(false);       // биндинг получен для текущей вселенной
  const bindingFetchInFlightRef = useRef(false);
  const deliveredKeyRef = useRef<string | null>(null);   // дедуп: записанные поставки
  const anchorSnapshotRef = useRef<string | null>(null); // дедуп: EDA-якорь (канон. снапшот)
  const pendingRef = useRef<PendingDelivery | null>(null);
  const tokenRef = useRef(0);                  // изоляция stale-ответов (план §12 п.3)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const attemptCounterRef = useRef(0);
  const prevSnapshotRef = useRef<string | null>(null);   // детектор null↔non-null
  const staleArmRef = useRef(false);           // ОДНА повторная поставка после 409
  // «Возможность поставки»: снапшот, на который вооружён текущий fetch
  // биндинга, и возможность, уже израсходованная прямым путём (см.
  // «Перевооружение после сбоя» в шапке файла).
  const bindingOpportunityRef = useRef<string | null>(null);
  const bindingOpportunityUsedRef = useRef<string | null>(null);
  const universeKeyRef = useRef<string | null>(universeKey ?? null);
  const lastMapRef = useRef<Record<string, string> | null>(null);
  lastMapRef.current = map;
  const postAttemptRef = useRef<PostAttemptFn | null>(null);

  const retryDelaysRef = useRef(retryDelaysMs ?? DEFAULT_RETRY_DELAYS_MS);
  retryDelaysRef.current = retryDelaysMs ?? DEFAULT_RETRY_DELAYS_MS;

  // Канонический снапшот карты (примитив -- стабильные deps драйвера).
  const snapshot = map ? canonicalMapString(map) : null;

  // Anchor-канонизация НА РЕНДЕРЕ (до драйвера: первый прогон эффекта
  // уже видит якорь; эффект-вариант запаздывал на один прогон). Якорь
  // сравнивается по каноническому снапшоту, БЕЗ биндинга: EDA сам
  // сбрасывает якорь при смене вселенной фактов (datasetKey) -- смена
  // run внутри живого якоря невозможна (seed-эффект EDA перезапускается
  // раньше следующей поставки).
  if (!anchorSnapshot) {
    anchorSnapshotRef.current = null;
  } else {
    try {
      anchorSnapshotRef.current = canonicalMapString(
        JSON.parse(anchorSnapshot) as Record<string, string>,
      );
    } catch {
      anchorSnapshotRef.current = null;
    }
  }

  const setDeliveryState = useCallback(
    (next: ProgressMapDeliveryStatus, error: string | null) => {
      if (!mountedRef.current) return;
      setStatus(next);
      setLastError(error);
    },
    [],
  );

  const abortPending = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    tokenRef.current += 1; // поздние ответы прежней поставки игнорируются
    pendingRef.current = null;
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      // §12 п.6: unmount -- in-flight абортируется, таймеры сняты;
      // состояние недоставленности in-memory не переживает перезагрузку
      // (ограничение задокументировано, контракт §20.6).
      abortPending();
    };
  }, [abortPending]);

  // ── Смена вселенной фактов (universeKey) ──
  // Новая вселенная: записанная поставка прежней вселенной не подавляет
  // новую (дедуп-ключ очищается), биндинг перезапрашивается, 409-arm
  // сбрасывается; висящая поставка прежней вселенной замещается.
  useEffect(() => {
    const nextUniverse = universeKey ?? null;
    if (universeKeyRef.current === nextUniverse) return;
    universeKeyRef.current = nextUniverse;
    deliveredKeyRef.current = null;
    bindingReadyRef.current = false;
    bindingFetchInFlightRef.current = false;
    staleArmRef.current = false;
    bindingOpportunityRef.current = null;
    bindingOpportunityUsedRef.current = null;
    if (pendingRef.current) abortPending();
    setBindingVersion((v) => v + 1); // драйвер: свежий биндинг новой вселенной
  }, [universeKey, abortPending]);

  const startDelivery = useCallback(
    (snapshotString: string) => {
      const currentMap = lastMapRef.current;
      if (!currentMap) return;
      // Замещение прежней поставки (план §12 п.3): abort + снятие таймера;
      // прежняя поставка остаётся НЕ доставленной (deliveredKey не ставился).
      abortPending();
      const delivery: PendingDelivery = {
        reportId: generateReportId(),
        snapshot: snapshotString,
        inFlight: false,
      };
      attemptCounterRef.current = 0;
      postAttemptRef.current?.(delivery);
    },
    [abortPending],
  );

  // ── Прямая оценка «поставка назрела» по refs (без рендер-прохода) ──
  // Вызывается из колбэка завершения биндинга -- синхронно с получением
  // контекста, БЕЗ ставки на последующий рендер (см. «Перевооружение
  // после сбоя» в шапке файла). Гардсы зеркалят хвост драйвера доставки
  // плюс контракт «возможности»: доставляется ТОЛЬКО тот снапшот, на
  // который был вооружён этот fetch биндинга; возможность израсходуется
  // ровно один раз, остаточные гонки добивают pending-гардс и дедуп.
  const attemptDeliveryIfDue = useCallback(() => {
    const currentMap = lastMapRef.current;
    if (!currentMap) return; // вселенная закрыта/транзит -- доставлять нечего
    const currentSnapshot = canonicalMapString(currentMap);
    // Возможность вооружена драйвером под КОНКРЕТНЫЙ снапшот; если картина
    // ушла вперёд (или fetch не вооружён) -- решение за рендер-путём:
    // новый переход пересчитает биндинг и поставку на свежих гардсах.
    if (bindingOpportunityRef.current === null) return;
    if (currentSnapshot !== bindingOpportunityRef.current) return;
    if (anchorSnapshotRef.current !== null && anchorSnapshotRef.current === currentSnapshot) return;
    if (!bindingReadyRef.current) return;
    const key = deliveryKey(bindingRef.current, currentSnapshot);
    // Дедуп §12 п.4: (run, context, snapshot) уже записан.
    if (deliveredKeyRef.current === key) return;
    // Та же поставка уже в полёте/на retry -- дубликат не нужен.
    if (
      pendingRef.current &&
      pendingRef.current.snapshot === currentSnapshot &&
      (pendingRef.current.inFlight || timerRef.current !== null)
    ) {
      return;
    }
    bindingOpportunityUsedRef.current = currentSnapshot;
    startDelivery(currentSnapshot);
  }, [startDelivery]);

  // ── POST-попытка поставки (рекурсия retry -- через postAttemptRef) ──
  const postAttempt = useCallback(
    (delivery: PendingDelivery) => {
      if (!mountedRef.current) return;
      const binding = bindingRef.current;
      const currentMap = lastMapRef.current;
      if (!currentMap) return;
      attemptCounterRef.current += 1;
      const attemptNo = attemptCounterRef.current;
      const isV2 = binding !== null;
      const body: Record<string, unknown> = isV2
        ? {
            [bodyKey]: currentMap,
            schema_version: 2,
            run_id: binding.runId,
            context_id: binding.contextId,
            report_id: delivery.reportId,
          }
        : { [bodyKey]: currentMap };

      const controller = new AbortController();
      abortRef.current = controller;
      const token = ++tokenRef.current;
      pendingRef.current = { ...delivery, inFlight: true };
      setStatus("pending");
      setReportId(delivery.reportId);
      setAttempts(attemptNo);

      const isStaleDelivery =
        token !== tokenRef.current ||
        pendingRef.current?.reportId !== delivery.reportId;

      const scheduleRetryOrStop = (error: string) => {
        if (isStaleDelivery) return;
        // Retry ТОЛЬКО для v2 (идемпотентный ключ); легаси -- один POST
        // (контракт §20.5: серверный легаси без идемпотентности).
        if (!isV2) {
          pendingRef.current = null;
          setDeliveryState("undelivered", error);
          return;
        }
        const delayIndex = attemptNo - 1; // после 1-й попытки -- delays[0]
        if (delayIndex >= retryDelaysRef.current.length) {
          pendingRef.current = null;
          setDeliveryState("undelivered", error);
          return;
        }
        pendingRef.current = { ...delivery, inFlight: false };
        timerRef.current = setTimeout(() => {
          timerRef.current = null;
          if (
            mountedRef.current &&
            token === tokenRef.current &&
            pendingRef.current?.reportId === delivery.reportId
          ) {
            postAttemptRef.current?.(delivery);
          }
        }, retryDelaysRef.current[delayIndex]);
      };

      void fetch(progressApiUrl(endpoint), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(body),
        signal: controller.signal,
      })
        .then(async (res: Response) => {
          // Изоляция stale (план §12 п.3): ответ не текущей поставки игнорируется.
          if (token !== tokenRef.current || pendingRef.current?.reportId !== delivery.reportId) return;
          if (res.ok) {
            const data = (await res.json().catch(() => null)) as
              | { mode?: unknown; receipt?: unknown }
              | null;
            if (token !== tokenRef.current || pendingRef.current?.reportId !== delivery.reportId) return;
            // Receipt-гейт (план §12 п.2): delivered -- только после receipt.
            deliveredKeyRef.current = deliveryKey(bindingRef.current, delivery.snapshot);
            pendingRef.current = null;
            if (data && data.mode === "v2" && data.receipt) {
              setDeliveryState("delivered", null);
            } else {
              // Acceptance без receipt (легаси-режим сервера) -- честно
              // НЕ delivered (best-effort приёмка, контракт §20.4).
              setDeliveryState("accepted_legacy", null);
            }
            return;
          }
          const detail = (await res
            .json()
            .then((d: { detail?: unknown }) => (typeof d?.detail === "string" ? d.detail : null))
            .catch(() => null)) as string | null;
          if (token !== tokenRef.current || pendingRef.current?.reportId !== delivery.reportId) return;
          if (
            res.status === 409 &&
            detail &&
            (detail.startsWith("stale_run") || detail.startsWith("stale_context"))
          ) {
            // §12 п.5: refresh контекста, не бесконечный повтор старого
            // тела. ОДНА перевооружённая повторная поставка с НОВЫМ
            // report_id после refresh; повторный 409 -- стоп.
            pendingRef.current = null;
            setDeliveryState("stale", detail);
            if (!staleArmRef.current) {
              staleArmRef.current = true;
              bindingReadyRef.current = false;
              setBindingVersion((v) => v + 1); // драйвер: refresh → повтор
            }
            return;
          }
          if (res.status >= 500 && res.status <= 599) {
            scheduleRetryOrStop(detail ?? `HTTP ${res.status}`);
            return;
          }
          // report_id_conflict / 400 / 404 / 422 -- постоянные ошибки.
          pendingRef.current = null;
          setDeliveryState("undelivered", detail ?? `HTTP ${res.status}`);
        })
        .catch((err: unknown) => {
          if (token !== tokenRef.current || pendingRef.current?.reportId !== delivery.reportId) return;
          if (controller.signal.aborted) return; // supersede/unmount -- не отказ доставки
          scheduleRetryOrStop(err instanceof Error ? err.message : String(err));
        });
    },
    [bodyKey, endpoint, setDeliveryState],
  );
  postAttemptRef.current = postAttempt;

  // ── Драйвер доставки ──
  useEffect(() => {
    // Смена вселенной фактов (map → null → map): биндинг
    // перезапрашивается, перевооружение 409 сбрасывается (план §12 п.4).
    const prev = prevSnapshotRef.current;
    prevSnapshotRef.current = snapshot;
    if (snapshot !== null && prev === null) {
      bindingReadyRef.current = false;
      bindingFetchInFlightRef.current = false;
      staleArmRef.current = false;
      bindingOpportunityUsedRef.current = null; // новый переход -- новая возможность
    }
    if (snapshot === null) {
      // Вселенная закрыта: висящая поставка замещается (не delivered).
      if (pendingRef.current) {
        abortPending();
        setDeliveryState("idle", null);
      }
      return;
    }
    // Anchor (EDA-якорь) -- ДО получения биндинга: снапшот, уже
    // известный как записанный, не доставляется повторно (PROGR-18
    // семантика seed-маркера); биндинг для него не нужен вовсе.
    if (anchorSnapshotRef.current !== null && anchorSnapshotRef.current === snapshot) return;
    if (!bindingReadyRef.current) {
      // §12 п.3/I3: биндинг -- наблюдаемый контекст /trace (тот же
      // источник, что проверяет сервер). Один запрос на вселенную.
      if (!bindingFetchInFlightRef.current) {
        bindingFetchInFlightRef.current = true;
        bindingOpportunityRef.current = snapshot; // возможность вооружена на ЭТОТ снапшот
        setDeliveryState("binding", null);
        void (async () => {
          const binding = await fetchBinding();
          bindingFetchInFlightRef.current = false;
          if (!mountedRef.current) return;
          bindingRef.current = binding;
          bindingReadyRef.current = true;
          setRunId(binding?.runId ?? null);
          setContextId(binding?.contextId ?? null);
          setBindingVersion((v) => v + 1); // рендер-путь драйвера (основной)
          // Прямой путь (детерминизм перевооружения -- R1/H26): если среда
          // не обрабатывает этот setState (act-окно закрыто -- обновление
          // теряется), перезапуск драйвера не состоится и поставка после
          // сбоя зависнет до следующей волны. Контракт «возможности» и
          // pending-гардс делают пути взаимно идемпотентными.
          attemptDeliveryIfDue();
        })();
      }
      return;
    }
    const key = deliveryKey(bindingRef.current, snapshot);
    // Дедуп §12 п.4: (run, context, snapshot) уже записан (receipt/ack).
    if (deliveredKeyRef.current === key) return;
    // Та же поставка уже в полёте/на retry -- дубликат не нужен.
    if (
      pendingRef.current &&
      pendingRef.current.snapshot === snapshot &&
      (pendingRef.current.inFlight || timerRef.current !== null)
    ) {
      return;
    }
    // Возможность этого снапшота уже израсходована прямым путём из
    // колбэка биндинга -- повтор здесь задублировал бы POST (после сбоя
    // прямой путь pendingRef/deliveredKey не оставляет).
    if (bindingOpportunityUsedRef.current === snapshot) return;
    startDelivery(snapshot);
  }, [snapshot, bindingVersion, redeliverTick, abortPending, setDeliveryState, startDelivery, attemptDeliveryIfDue]);

  // ── Принудительная повторная поставка (Upload: подтверждение структуры) ──
  const redeliver = useCallback(() => {
    deliveredKeyRef.current = null;
    staleArmRef.current = false;
    bindingOpportunityUsedRef.current = null; // принудительная повторная поставка -- новая возможность
    setRedeliverTick((v) => v + 1);
  }, []);

  return {
    status,
    delivered: status === "delivered",
    reportId,
    attempts,
    lastError,
    runId,
    contextId,
    redeliver,
  };
}
