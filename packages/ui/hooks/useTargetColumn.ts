"use client";

// packages/ui/hooks/useTargetColumn.ts
//
// Единый "исследуемый признак" для всей платформы (2026-08-14). До этого
// изменения три вкладки решали, какая колонка активна, независимо:
//   - Моделирование: реальный target_column из сессии (Phase 0.5, единственная
//     рабочая реализация -- см. TsAnalysisModeling.tsx, НЕ рефакторится этим
//     хуком, чтобы не трогать уже стабильный код; дублирование с этим хуком
//     признано и оставлено как известный технический долг).
//   - Загрузка: локальный useState, сбрасывался при каждом уходе с вкладки
//     (React unmount на смену route), откатывался к первой числовой колонке
//     ПО ПОРЯДКУ В ДАТАФРЕЙМЕ -- для датасета Country/Year/Price это Year,
//     не Price.
//   - Валидация: NUMERIC_FEATURES был захардкоженный мок-список тикеров
//     (['price','volume',...]) -- то, что выглядело как "Price", было
//     совпадением, а не синхронизацией.
//
// Этот хук -- общий клиент для GET/POST /v1/session/target-column,
// переиспользуемый в Загрузке и Валидации (TsAnalysisModeling.tsx на этом
// шаге НЕ трогаем -- её собственная реализация уже стабильна и протестирована).
//
// Дефолт при пустом target_column: suggested_column с бэкенда (эвристика
// "первая числовая, исключая date/year-похожие имена", см.
// apps/api/routers/session.py::_suggest_target_column) АВТОМАТИЧЕСКИ
// POST-ится как реальный target_column при первом маунте потребителя,
// если сессия ещё ни разу не имела target_column -- иначе Моделирование
// продолжало бы показывать "не выбрано" даже после того, как Upload
// "визуально" показал Price (без auto-POST это осталось бы только
// локальным отображением, не меняющим состояние сессии).

import { useCallback, useEffect, useRef, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";
import type { TargetColumnResponse } from "../lib/modeling";

export interface ColumnResetNotice {
  previousColumn: string;
  newColumn: string;
}

export interface UseTargetColumnResult {
  targetColumn: string | null;
  suggestedColumn: string | null;
  availableColumns: string[];
  hasDataset: boolean;
  loading: boolean;
  error: string | null;
  /** true, пока в текущем сеансе значение было выбрано автоматически
   * (suggested_column), а не явным действием пользователя -- для
   * инлайн-подсказки "выбрано автоматически" у селектора. Сбрасывается
   * в false, как только пользователь делает осознанный выбор через
   * setColumn(). */
  wasAutoSelected: boolean;
  /** Заполняется, когда РАНЕЕ выбранная (не пустая) колонка перестала
   * существовать в сессии между двумя фетчами ЭТОГО хука (типичная
   * причина -- загружен новый датасет с другим набором колонок).
   * Отличается от обычного "выбор ещё не сделан" (там previousColumn
   * никогда не был непустым) -- используется потребителем для toast,
   * а не только инлайн-бейджа. Читается один раз потребителем и должно
   * быть явно погашено вызовом dismissColumnResetNotice(). */
  columnResetNotice: ColumnResetNotice | null;
  dismissColumnResetNotice: () => void;
  /** Явный выбор пользователя -- POST на сервер, wasAutoSelected -> false. */
  setColumn: (column: string) => Promise<void>;
  /** Ручной рефетч (например, после подтверждённой загрузки датасета). */
  refetch: () => Promise<void>;
}

/**
 * datasetKey -- сигнал "датасет сессии мог измениться" (например,
 * activeDataset?.name из useAppShell()) -- триггерит refetch, аналогично
 * паттерну activeDatasetName в TsAnalysisModeling.tsx.
 */
export function useTargetColumn(datasetKey: string | null | undefined): UseTargetColumnResult {
  const [targetColumn, setTargetColumnState] = useState<string | null>(null);
  const [suggestedColumn, setSuggestedColumn] = useState<string | null>(null);
  const [availableColumns, setAvailableColumns] = useState<string[]>([]);
  const [hasDataset, setHasDataset] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [wasAutoSelected, setWasAutoSelected] = useState(false);
  const [columnResetNotice, setColumnResetNotice] = useState<ColumnResetNotice | null>(null);

  // Защита от двойного авто-POST при конкурентных маунтах/эффектах
  // (StrictMode double-effect в dev, или Upload+Validation монтируются
  // одновременно в редком сценарии) -- ref, не state, чтобы не триггерить
  // лишний рендер и не создавать гонку между проверкой и записью.
  const autoSelectInFlight = useRef(false);

  // Последнее НЕПУСТОЕ значение target_column, увиденное ЭТИМ инстансом
  // хука -- сигнал для различения "первый выбор в сессии" (previousColumn
  // никогда не было -- без уведомления) от "датасет сменился, старая
  // колонка пропала" (previousColumn было -- toast+инлайн, см. Upload/
  // Validation). Не переживает полную перезагрузку страницы (это ОК --
  // best-effort уведомление в рамках текущего визита на вкладку).
  const lastKnownColumn = useRef<string | null>(null);
  const hasFetchedOnce = useRef(false);

  const applyResponse = useCallback((data: TargetColumnResponse) => {
    setTargetColumnState(data.target_column);
    setSuggestedColumn(data.suggested_column);
    setAvailableColumns(data.available_columns);
    setHasDataset(data.has_dataset);
    if (data.target_column !== null) {
      lastKnownColumn.current = data.target_column;
    }
  }, []);

  const fetchAndMaybeAutoSelect = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(sessionApiUrl("/target-column"), {
        method: "GET",
        credentials: "include",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: TargetColumnResponse = await res.json();

      // Сброс: этот хук РАНЕЕ видел непустой target_column (lastKnownColumn),
      // а сейчас сервер вернул null -- значит между фетчами что-то обнулило
      // сессию (типично: новый датасет загружен, backend сам сбрасывает
      // target_column в set_dataset(), см. apps/api/upload_common.py).
      // Не путать с самым первым фетчем (hasFetchedOnce=false) -- тогда
      // "null" это норма, а не сброс.
      const isReset = hasFetchedOnce.current && data.target_column === null && lastKnownColumn.current !== null;
      const previousColumn = lastKnownColumn.current;
      hasFetchedOnce.current = true;

      // Автовыбор: target_column ещё не установлен в сессии, но есть
      // разумный дефолт -- фиксируем его как РЕАЛЬНЫЙ target_column
      // (POST), не просто отображаем. Иначе синхронизация между
      // вкладками не работает: другая вкладка (например, Моделирование)
      // читает то же /target-column и увидит null, пока кто-то явно не
      // выберет колонку.
      if (data.target_column === null && data.suggested_column !== null && !autoSelectInFlight.current) {
        autoSelectInFlight.current = true;
        try {
          const postRes = await fetch(sessionApiUrl("/target-column"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({ column: data.suggested_column }),
          });
          if (postRes.ok) {
            const postData: TargetColumnResponse = await postRes.json();
            applyResponse(postData);
            setWasAutoSelected(true);
            if (isReset && previousColumn && postData.target_column) {
              setColumnResetNotice({ previousColumn, newColumn: postData.target_column });
            }
            return;
          }
        } finally {
          autoSelectInFlight.current = false;
        }
      }

      applyResponse(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось получить исследуемый признак");
    } finally {
      setLoading(false);
    }
  }, [applyResponse]);

  const setColumn = useCallback(
    async (column: string) => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(sessionApiUrl("/target-column"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ column }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data: TargetColumnResponse = await res.json();
        applyResponse(data);
        setWasAutoSelected(false); // осознанный выбор пользователя
      } catch (err) {
        setError(err instanceof Error ? err.message : "Не удалось выбрать признак");
      } finally {
        setLoading(false);
      }
    },
    [applyResponse]
  );

  useEffect(() => {
    fetchAndMaybeAutoSelect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetKey]);

  return {
    targetColumn,
    suggestedColumn,
    availableColumns,
    hasDataset,
    loading,
    error,
    wasAutoSelected,
    columnResetNotice,
    dismissColumnResetNotice: () => setColumnResetNotice(null),
    setColumn,
    refetch: fetchAndMaybeAutoSelect,
  };
}
