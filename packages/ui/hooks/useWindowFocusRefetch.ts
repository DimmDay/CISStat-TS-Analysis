"use client";

// packages/ui/hooks/useWindowFocusRefetch.ts
//
// PROGR-9-FOCUS: автоперезапрос данных при возврате пользователя во
// вкладку/окно браузера. Закрывает последний сценарий, где в Панели
// управления «Предобработки» были оправданы ручные кнопки пересчёта:
//
//   • «Вторая вкладка»: HTTP-сессия живёт в общей cookie
//     (cisstat_session_id), поэтому мутация активного датасета в соседней
//     вкладке (upload/apply мастера) НЕ видна открытой вкладке — её
//     профили молча устаревают. Ни datasetVersion, ни собственные
//     refreshKey об этом узнать не могут: это чисто клиентские счётчики.
//     window "focus" покрывает возврат в окно (Alt-Tab, клик по окну),
//     document "visibilitychange"→visible — возврат во вкладку браузера
//     (в части браузеров focus при смене вкладок не срабатывает).
//   • Ретрай после сбоя GET: упавший профиль остаётся в статусе ошибки
//     до следующей инвалидации; возврат во вкладку перезапускает эффекты.
//
// Дедупликация: одна нормализация окна в браузерах порождает ПАРУ событий
// (visibilitychange, затем focus) — без склейки каждый возврат давал бы
// двойную волну GET (2×N профилей). Паре событий в пределах minIntervalMs
// (по умолчанию 750 мс) соответствует ровно один колбэк; то же окно
// мягко троттлит частое Alt-Tab переключение.
//
// Подписка стабильна: свежий колбэк берётся из ref на момент события,
// слушатели не переподписываются на каждый рендер; при размонтировании
// слушатели снимаются.

import { useEffect, useRef } from "react";

export interface UseWindowFocusRefetchOptions {
  /** Окно дедупликации/троттлинга, мс (по умолчанию 750). */
  minIntervalMs?: number;
}

export function useWindowFocusRefetch(
  onRefetch: () => void,
  options?: UseWindowFocusRefetchOptions,
): void {
  const minIntervalMs = options?.minIntervalMs ?? 750;

  // Момент последнего срабатывания — для дедупликации пары событий
  // (visibilitychange + focus) и мягкого троттлинга Alt-Tab. Инициализация
  // -Infinity: ПЕРВОЕ событие после монтирования легитимно всегда
  // (не зависит от текущего значения Date.now()).
  const lastRefetchAtRef = useRef<number>(-Infinity);

  // Свежий колбэк без переподписки слушателей (latest-ref паттерн);
  // обновление в эффекте, а не в рендере (строгий React 18 concurrent).
  const onRefetchRef = useRef(onRefetch);
  useEffect(() => {
    onRefetchRef.current = onRefetch;
  }, [onRefetch]);

  useEffect(() => {
    const trigger = () => {
      const now = Date.now();
      if (now - lastRefetchAtRef.current < minIntervalMs) return;
      lastRefetchAtRef.current = now;
      onRefetchRef.current();
    };

    // Возврат в окно браузера (Alt-Tab, клик вне страницы).
    const handleFocus = () => trigger();
    // Возврат во вкладку (смена вкладок/сворачивание). Событие приходит
    // и на уход (hidden) — перезапрашиваем ТОЛЬКО на появление.
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") trigger();
    };

    window.addEventListener("focus", handleFocus);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      window.removeEventListener("focus", handleFocus);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [minIntervalMs]);
}
