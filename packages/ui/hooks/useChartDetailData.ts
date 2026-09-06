"use client";

// packages/ui/hooks/useChartDetailData.ts
//
// Task 97.3 (Этап 3, spec_max_graf_fix.md §6.3) — условная догрузка
// detail_level=expanded для раскрытого графика Обзора.
//
// Контракт дозагрузки (§6.3):
// 1. Компонент, отрисовывающий график (НЕ сам ExpandableChartPanel —
//    он универсален и не знает про data fetching), включает `enabled`,
//    когда его панель стала раскрыта: сигнал приходит из того же
//    источника, что и onExpandChange панели (expandedChartId === chartId).
// 2. Кэш детального payload ключуется составом
//    (profileKey, fingerprint, params) — где fingerprint несёт идентичность
//    датасета (datasetId) и инвалидируется теми же триггерами, что и
//    остальные профили (смена датасета/target/параметров, §6.3.5).
//    Идентификатор сессии в ключе не нужен: фронтенд не держит его в
//    состоянии (cookie cisstat_session_id), а смена сессии всегда
//    меняет и датасет/fingerprint.
// 3. Попадание в кэш — данные отдаются сразу, без похода в сеть.
// 4. Промах — фоновый повторный запрос с detail_level=expanded; пока он
//    летит, data остаётся null и Обзор продолжает показывать уже
//    отрисованный compact-график (ResponsiveContainer растягивает его на
//    раскрытый контейнер), поверх которого Обзор рисует лёгкий
//    unobtrusive-индикатор по loading (§6.3.3).
// 5. Graceful degradation (§6.3.6): ошибка сети или HTTP-ответ backend'а,
//    ещё не поддерживающего параметр, превращаются в error без исключения
//    — Обзор продолжает показывать компактные данные в увеличенном виде.

import { useEffect, useRef, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";

export interface ChartDetailDataResult<T> {
  /** Раскрытый payload; null — рендерить компактные данные. */
  data: T | null;
  /** Идёт фоновый дозапрос expanded — индикатор поверх compact-графика. */
  loading: boolean;
  /** Ошибка дозапроса (не блокирует просмотр компактных данных). */
  error: string | null;
}

export interface UseChartDetailDataOptions {
  /** Путь профильного endpoint'а, например "/dataset/eda-structural-breaks". */
  path: string;
  /** Уникальный и стабильный ключ профиля (обычно chartId панели). */
  profileKey: string;
  /**
   * Базовые query-параметры профильного запроса (те же, что у compact-феча
   * контейнера — методология compact/expanded должна совпадать, §6.4).
   * Значения null/undefined пропускаются, как опциональные query-параметры.
   */
  params: Record<string, string | number | boolean | null | undefined>;
  /**
   * Идентичность входных данных для инвалидации кэша (datasetId/имя
   * датасета). Смена fingerprint = новый ключ кэша = дозапрос.
   */
  fingerprint?: string | null;
  /** Сигнал «панель раскрыта» — триггер дозагрузки §6.3.1. */
  enabled: boolean;
  /** Подмена fetch для тестов; по умолчанию globalThis.fetch. */
  fetchImpl?: typeof fetch;
}

/** Вторичный потолок кэша детальных payload на одну страницу Обзора:
 * FIFO-вытеснение, чтобы память не росла бесконечно при переключении
 * датасетов/параметров в рамках сессии (§6.3.5). */
export const MAX_CHART_DETAIL_CACHE_ENTRIES = 40;

const detailCache = new Map<string, unknown>();

export function __clearChartDetailCacheForTests(): void {
  detailCache.clear();
}

function buildCacheKey(
  profileKey: string,
  fingerprint: string | null | undefined,
  params: UseChartDetailDataOptions["params"],
): string {
  const normalized = Object.entries(params)
    .filter(([, value]) => value !== null && value !== undefined)
    .map(([key, value]) => `${key}=${String(value)}`)
    .sort();
  return `${profileKey}::${fingerprint ?? ""}::${normalized.join("&")}`;
}

function buildDetailUrl(path: string, params: UseChartDetailDataOptions["params"]): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== null && value !== undefined) query.set(key, String(value));
  });
  query.set("detail_level", "expanded");
  return `${sessionApiUrl(path)}?${query.toString()}`;
}

export function useChartDetailData<T>(
  options: UseChartDetailDataOptions,
): ChartDetailDataResult<T> {
  const { path, profileKey, params, fingerprint, enabled, fetchImpl } = options;
  // Ключ стабилен между рендерами (строка), поэтому эффект не перезапускается
  // из-за новой объектной обёртки params на каждый рендер родителя.
  const cacheKey = buildCacheKey(profileKey, fingerprint, params);
  const fetchRef = useRef(fetchImpl);
  fetchRef.current = fetchImpl;

  const [state, setState] = useState<{
    key: string;
    data: T | null;
    loading: boolean;
    error: string | null;
  }>(() => ({
    key: cacheKey,
    data: enabled ? detailCache.get(cacheKey) as T | undefined ?? null : null,
    loading: false,
    error: null,
  }));

  useEffect(() => {
    if (!enabled) {
      // Свёрнуто: Обзор снова показывает компактные данные; кэш не трогаем,
      // чтобы повторное раскрытие отдалось из кэша без сети (§6.3.2).
      setState((prev) =>
        prev.data === null && prev.error === null && !prev.loading && prev.key === cacheKey
          ? prev
          : { key: cacheKey, data: null, loading: false, error: null },
      );
      return;
    }

    const cached = detailCache.get(cacheKey);
    if (cached !== undefined) {
      setState({ key: cacheKey, data: cached as T, loading: false, error: null });
      return;
    }

    let active = true;
    const controller = new AbortController();
    const doFetch = fetchRef.current ?? globalThis.fetch;
    if (typeof doFetch !== "function") {
      // Graceful degradation (§6.3.6): нет транспорта (jsdom в старых
      // тестах, экзотические окружения) — просто показываем compact.
      setState({ key: cacheKey, data: null, loading: false, error: "fetch недоступен" });
      return;
    }
    setState((prev) => ({
      key: cacheKey,
      // мягкий переход: если ключ не менялся (повторная попытка), не мигаем
      data: prev.key === cacheKey ? null : null,
      loading: true,
      error: null,
    }));

    doFetch(buildDetailUrl(path, params), { credentials: "include", signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return (await response.json()) as T;
      })
      .then((payload) => {
        // FIFO-вытеснение: Map итерируется по порядку вставки
        detailCache.delete(cacheKey);
        detailCache.set(cacheKey, payload);
        while (detailCache.size > MAX_CHART_DETAIL_CACHE_ENTRIES) {
          const oldest = detailCache.keys().next();
          if (oldest.done) break;
          detailCache.delete(oldest.value);
        }
        if (active) setState({ key: cacheKey, data: payload, loading: false, error: null });
      })
      .catch((caught: unknown) => {
        if (!active) return;
        if (caught instanceof DOMException && caught.name === "AbortError") return;
        setState({
          key: cacheKey,
          data: null,
          loading: false,
          error: caught instanceof Error ? caught.message : "Не удалось загрузить детальные данные",
        });
      });

    return () => {
      active = false;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, cacheKey, path]);

  return { data: state.data, loading: state.loading, error: state.error };
}
