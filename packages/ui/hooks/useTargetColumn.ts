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
// переиспользуемый в Загрузке, Валидации, Предобработке и EDA
// (TsAnalysisModeling.tsx пока не трогаем -- её собственная реализация
// уже стабильна и протестирована).
//
// ПРОГР-25-B (спека spec_progress_target_column.md §4-B, правка R1 акта
// сертификации): тихий авто-POST рекомендации СНЯТ ПОЛНОСТЬЮ.
// Авто-фиксация исследуемого признака -- исключительная компетенция
// бэкенда (ПРОГР-25-A: при загрузке датасета, ровно один кандидат).
// Хук только ЧИТАЕТ состояние (GET) и отображает его:
//   - suggested_column остаётся ОТОБРАЖАЕМОЙ рекомендацией селектора
//     (никогда не персистится хуком);
//   - фиксация -- только ручной выбор setColumn (POST, источник user);
//   - wasAutoSelected -- честное происхождение из ФАКТА бэкенда
//     (target_column_source === "auto"); ответ старого бэкенда без поля
//     читается как "не авто";
//   - монтирование любой вкладки с хуком НЕ создаёт
//     target_column_changed -- ни при одной, ни при нескольких числовых.

import { useCallback, useEffect, useRef, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";
import type { TargetColumnResponse } from "../lib/modeling";

export interface ColumnResetNotice {
  previousColumn: string;
  /** Рекомендация бэкенда (suggested_column) на момент сброса или null,
   * если рекомендации нет. НЕ фиксированное значение: с снятием
   * авто-POST (ПРОГР-25-B) фиксация -- только ручной выбор. */
  newColumn: string | null;
}

export interface UseTargetColumnResult {
  targetColumn: string | null;
  suggestedColumn: string | null;
  availableColumns: string[];
  hasDataset: boolean;
  loading: boolean;
  error: string | null;
  /** true, когда в сессии значение зафиксировано АВТОМАТИЧЕСКИ -- честный
 * факт происхождения из ответа бэкенда (target_column_source === "auto",
 * ПРОГР-25-A), а не действие этого хука (авто-POST снят, ПРОГР-25-B).
 * Для инлайн-подсказки "выбрано автоматически" у селектора. Сбрасывается
 * в false при ручном выборе setColumn() и на ответах старого бэкенда
 * без поля source (undefined -- происхождение неизвестно). */
  wasAutoSelected: boolean;
  /** Заполняется, когда РАНЕЕ выбранная (не пустая) колонка перестала
   * существовать в сессии между двумя фетчами ЭТОГО хука (типичная
   * причина -- загружен новый датасет с другим набором колонок).
   * newColumn -- РЕКОМЕНДАЦИЯ бэкенда (suggested_column) или null, если
   * рекомендаций нет: с снятием авто-POST (ПРОГР-25-B) хук ничего не
   * фиксирует сам, поэтому поле означает "предложено", а не "выбрано".
   * Отличается от обычного "выбор ещё не сделан" (там previousColumn
   * никогда не был непустым) -- используется потребителем для toast,
   * а не только инлайн-бейджа. Читается один раз потребителем и должно
   * быть явно погашено вызовом dismissColumnResetNotice(). */
  columnResetNotice: ColumnResetNotice | null;
  dismissColumnResetNotice: () => void;
  passportResetNotice: ColumnResetNotice | null;
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
  const [passportResetNotice, setPassportResetNotice] = useState<ColumnResetNotice | null>(null);

  // Последнее НЕПУСТОЕ значение target_column, увиденное ЭТИМ инстансом
  // хука -- сигнал для различения "первый выбор в сессии" (previousColumn
  // никогда не было -- без уведомления) от "датасет сменился, старая
  // колонка пропала" (previousColumn было -- toast+инлайн, см. Upload).
  // Не переживает полную перезагрузку страницы (это ОК --
  // best-effort уведомление в рамках текущего визита на вкладку).
  const lastKnownColumn = useRef<string | null>(null);
  const hasFetchedOnce = useRef(false);

  const applyResponse = useCallback((data: TargetColumnResponse) => {
    setTargetColumnState(data.target_column);
    setSuggestedColumn(data.suggested_column);
    setAvailableColumns(data.available_columns);
    setHasDataset(data.has_dataset);
    // ПРОГР-25-B: "авто" -- честный факт происхождения из ОТВЕТА бэкенда
    // (ПРОГР-25-A), а не действие хука; undefined (старый бэкенд) -- не авто.
    setWasAutoSelected(data.target_column_source === "auto");
    if (data.target_column !== null) {
      lastKnownColumn.current = data.target_column;
    }
  }, []);

  const fetchTargetColumn = useCallback(async () => {
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

      // ПРОГР-25-B (R1): авто-ПОСТ СНЯТ. Хук ничего не фиксирует --
      // только отображает ответ бэкенда: рекомендация (suggested_column)
      // остаётся отображаемой подсказкой селектора, фиксация -- только
      // ручной setColumn. Синхронизацию между вкладками обеспечивает
      // сам бэкенд: авто-фиксация при загрузке (ПРОГР-25-A) и общее
      // состояние сессии -- у всех вкладок один источник.
      applyResponse(data);

      // Уведомление о сбросе теперь живёт в общем пути фетча (раньше --
      // в ветке авто-ПОСТА): "ранее непустой target стал null". newColumn
      // -- РЕКОМЕНДАЦИЯ (не фиксация!); потребитель строит честный текст.
      if (isReset && previousColumn) {
        setColumnResetNotice({ previousColumn, newColumn: data.suggested_column });
      }
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
      setPassportResetNotice(null);
      const previousColumn = targetColumn;
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
        if (data.passport_history_reset && previousColumn && data.target_column) {
          setPassportResetNotice({ previousColumn, newColumn: data.target_column });
        }
        setWasAutoSelected(false); // осознанный выбор пользователя
      } catch (err) {
        setError(err instanceof Error ? err.message : "Не удалось выбрать признак");
      } finally {
        setLoading(false);
      }
    },
    [applyResponse, targetColumn]
  );

  useEffect(() => {
    void fetchTargetColumn();
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
    passportResetNotice,
    setColumn,
    refetch: fetchTargetColumn,
  };
}
