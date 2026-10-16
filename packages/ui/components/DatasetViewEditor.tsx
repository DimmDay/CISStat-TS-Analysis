"use client";

// Редактор датасета -- generic просмотр датасета из Мастеров
// остановок, добавляющих колонки (DATASET-VIEW-EDITOR-1, 2026-10-16,
// проект решения в worklog10.md; постановка тимлида: кнопка «Редактор
// датасета» в Мастерах остановок-источников новых колонок; бокс --
// просмотр всего датасета по умолчанию с удалением (скрытием) ТОЛЬКО
// добавленных колонок).
//
// Дефект-репорт тимлида (2026-10-16, сценарий: стратегия 1 добавляет в
// датасет 3 колонки, стратегия 2 следующей остановки рекомендует удалить
// одну из добавленных; аналитик удаляет её в редакторе, но СОХРАНИТЬ не
// может -- справа от «Вернуть все колонки» нет кнопки «Сохранить»):
// расширение -- кнопка «Сохранить», персистирующая удаление скрытых
// колонок через POST /dataset/derived-columns/delete (единственная
// мутация компонента); скрытые колонки -- очередь удаления,
// «Вернуть все колонки»/×-чип -- отмена до сохранения.
//
// Дизайн-принципы проекта решения:
//   P1 READ-ONLY СЕТКА: просмотр + управление колонками; ячеечных правок
//      НЕТ (эксклюзив MANUAL-редакторов Пропусков/Выбросов). Сеть --
//      два исходных GET (/dataset/derived-columns + /dataset/rows) и
//      РОВНО ОДИН POST сохранения удаления (только кликом «Сохранить»;
//      скрытие/возврат/фильтр -- локальны, без сети).
//   P2 «Удаление» производной колонки -- локальное скрытие из ПРЕДСТАВЛЕНИЯ
//      (клиентский Set), т.е. ОЧЕРЕДЬ удаления: до «Сохранить» ни один
//      контракт бэкенда не мутируется, data_revision не меняется. UX-
//      формулировки честные: «Скрыть из просмотра», подсказка «Удаление
//      применится кнопкой «Сохранить»», бейдж «датасет не изменён»
//      (истина до сохранения), строка «Скрыто из просмотра: N».
//   P3 Дефолт -- «Весь датасет» (все строки, все колонки), применён сразу
//      при открытии: точка входа -- проверка РЕЗУЛЬТАТА операции, а не
//      области проблемы (отличие от MANUAL-редакторов, где дефолт --
//      «Только с пропусками»/«Только с выбросами»).
//   P4 Источник истины о «добавленных» колонках -- реестр
//      session.derived_columns (PROGR-24-ORIGIN-A) через
//      GET /dataset/derived-columns, НЕ суффиксы имён.
//   P5 Один generic-компонент на обе вкладки вместо копий: сетка по
//      проверенному паттерну виртуализации MANUAL-*/UI-UPLOAD-FULL-1
//      (sticky-шапка, окна absolute, кэш страниц Map, in-flight guard,
//      overscan 10, фолбэк viewport 480).
//
// Строки -- GET /dataset/rows (единственный источник строк, читающий
// живой session.dataframe -- включая добавленные колонки); метаданные
// производных -- GET /dataset/derived-columns. Скрытие/возврат/фильтр --
// клиентские операции без сети; сохранение удаления -- POST
// /dataset/derived-columns/delete ({columns: [...]}) -- удаляет скрытые
// производные колонки из датасета (бэкенд валидирует: только реестр ∩
// кадр; исходные колонки не удаляемы) и снимает записи реестра
// (unregister_derived_columns); после успеха -- перечитка реестра и строк.

import { useCallback, useEffect, useRef, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";

async function responseDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Нейтральная ошибка ниже покрывает ответ без JSON.
  }
  return `Не удалось выполнить операцию (HTTP ${response.status})`;
}

type FilterMode = "all" | "derived";

interface DerivedColumnMeta {
  column: string;
  stage: string;
  source: string;
  created_at: string;
}

interface DerivedColumnsResponse {
  columns: DerivedColumnMeta[];
  total: number;
}

interface RowsResponse {
  columns: string[];
  rows: string[][];
  offset: number;
  limit: number;
  total_rows: number;
  returned: number;
  has_more: boolean;
}

interface DeleteColumnsResponse {
  deleted: string[];
  remaining_total: number;
}

const PAGE_LIMIT = 200; // строк на страницу запроса (<= капы бэкенда)
const ROW_H = 32;
const HEADER_H = 36;
const OVERSCAN_ROWS = 10;
// jsdom не считает layout (clientHeight = 0) -- фолбэк высоты вьюпорта
// для расчёта видимого окна; в браузере clientHeight реален.
const VIEWPORT_FALLBACK_H = 480;

// gridTemplateColumns: ведущая колонка № + minmax по видимым колонкам
// (паттерн fullGridTemplate() «Весь датасет» UI-UPLOAD-FULL-1).
function buildGridTemplate(visibleCount: number): string {
  if (visibleCount <= 0) return "44px";
  return `44px ${Array.from({ length: visibleCount }, () => "minmax(150px, 1fr)").join(" ")}`;
}

export function DatasetViewEditor() {
  // ── Фильтр состава колонок (P3: дефолт «Весь датасет» применён сразу) ──
  // pendingFilter -- состояние чекбоксов; appliedFilter -- состав,
  // применённый к сетке (меняется ТОЛЬКО кнопкой «Выбрать»). Чекбоксы
  // взаимоисключающие (клик по чекнутому снимает чек); оба сняты --
  // «Выбрать» честно заблокирован.
  const [pendingFilter, setPendingFilter] = useState<FilterMode | null>("all");
  const [appliedFilter, setAppliedFilter] = useState<FilterMode>("all");

  // ── Реестр производных колонок (P4) ──
  const [derivedMap, setDerivedMap] = useState<Map<string, DerivedColumnMeta>>(new Map());
  const [derivedTotal, setDerivedTotal] = useState<number | null>(null);

  // ── Скрытые колонки (P2: клиентский Set -- очередь удаления; persist
  //    ТОЛЬКО кнопкой «Сохранить») ──
  const [hidden, setHidden] = useState<Set<string>>(new Set());

  // ── Сохранение удаления (дефект-репорт: кнопка «Сохранить») ──
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null);

  // ── Строки / виртуализация (паттерн MANUAL-*/UI-UPLOAD-FULL-1) ──
  const [meta, setMeta] = useState<{ columns: string[]; totalRows: number } | null>(null);
  const [pages, setPages] = useState<Map<number, string[][]>>(new Map());
  const [pending, setPending] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [derivedError, setDerivedError] = useState<string | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportH, setViewportH] = useState(0);
  const [refreshKey, setRefreshKey] = useState(0);

  const scrollRef = useRef<HTMLDivElement>(null);
  const inFlightRef = useRef<Set<number>>(new Set());

  // Реестр производных -- один GET при монтировании (read-only).
  const fetchDerived = useCallback(async () => {
    setDerivedError(null);
    try {
      const res = await fetch(sessionApiUrl("/dataset/derived-columns"), { credentials: "include" });
      if (!res.ok) throw new Error(`Не удалось загрузить реестр добавленных колонок (HTTP ${res.status})`);
      const data: DerivedColumnsResponse = await res.json();
      setDerivedMap(new Map(data.columns.map((entry) => [entry.column, entry])));
      setDerivedTotal(data.total);
    } catch (caught) {
      setDerivedError(caught instanceof Error ? caught.message : "Не удалось загрузить реестр добавленных колонок");
    }
  }, []);

  // Страница строк -- GET /dataset/rows (единственный источник строк;
  // фильтр состава колонок -- клиентский, страницы от фильтра НЕ зависят:
  // один кэш на оба режима -- контраст с MANUAL-редакторами, у которых
  // область фильтра серверная).
  const fetchPage = useCallback(async (page: number) => {
    if (inFlightRef.current.has(page)) return;
    inFlightRef.current.add(page);
    setPending((n) => n + 1);
    try {
      const offset = page * PAGE_LIMIT;
      const res = await fetch(
        sessionApiUrl(`/dataset/rows?offset=${offset}&limit=${PAGE_LIMIT}`),
        { credentials: "include" },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: RowsResponse = await res.json();
      setMeta((prev) => (prev && prev.totalRows === data.total_rows ? prev : { columns: data.columns, totalRows: data.total_rows }));
      setPages((prev) => {
        const next = new Map(prev);
        next.set(page, data.rows);
        return next;
      });
      setLoadError(null);
    } catch {
      setLoadError("Не удалось загрузить строки датасета — проверьте соединение с API");
    } finally {
      inFlightRef.current.delete(page);
      setPending((n) => n - 1);
    }
  }, []);

  useEffect(() => {
    void fetchDerived();
  }, [fetchDerived, refreshKey]);

  // Видимое окно [start, end) по позиции ползунка: страницы, пересекающие
  // окно, догружаются (кэш: обратная прокрутка не перезапрашивает;
  // in-flight защита от повторов) -- паттерн «Весь датасет» UI-UPLOAD-FULL-1.
  const totalRows = meta?.totalRows ?? 0;
  const viewport = viewportH || VIEWPORT_FALLBACK_H;
  const start = Math.max(0, Math.floor(scrollTop / ROW_H) - OVERSCAN_ROWS);
  const end = Math.min(totalRows, Math.ceil((scrollTop + viewport) / ROW_H) + OVERSCAN_ROWS);

  useEffect(() => {
    if (totalRows === 0 && meta) return;
    const firstPage = Math.floor(start / PAGE_LIMIT);
    const lastPage = Math.floor(Math.max(end - 1, start) / PAGE_LIMIT);
    for (let p = firstPage; p <= lastPage; p++) {
      if (!pages.has(p)) void fetchPage(p);
    }
    // pages сознательно вне зависимостей: проверка актуальна на момент
    // эффекта, лишние зависимости вызвали бы цикл (fetchPage сам защищён
    // от повторов in-flight) -- паттерн «Весь датасет» UI-UPLOAD-FULL-1.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey, start, end, totalRows, meta, fetchPage]);

  // Состав видимых колонок: применённый фильтр минус скрытые (клиентский
  // своп состава -- сети не требует, P2).
  const allColumns = meta?.columns ?? [];
  const visibleColumns =
    appliedFilter === "derived"
      ? allColumns.filter((name) => derivedMap.has(name) && !hidden.has(name))
      : allColumns.filter((name) => !hidden.has(name));

  // Индексы колонок в строках API для видимого состава.
  const columnIndices = visibleColumns.map((name) => allColumns.indexOf(name));

  const visibleRows: Array<{ position: number; rowIndex: number; values: string[] }> = [];
  if (meta && totalRows > 0) {
    for (let i = start; i < end; i++) {
      const page = Math.floor(i / PAGE_LIMIT);
      const pageRows = pages.get(page);
      const row = pageRows ? pageRows[i - page * PAGE_LIMIT] : undefined;
      if (row) visibleRows.push({ position: i, rowIndex: i, values: row });
    }
  }

  const gridTemplate = buildGridTemplate(visibleColumns.length);

  const hideColumn = (name: string) => {
    setHidden((prev) => {
      const next = new Set(prev);
      next.add(name);
      return next;
    });
  };

  const restoreColumn = (name: string) => {
    setHidden((prev) => {
      const next = new Set(prev);
      next.delete(name);
      return next;
    });
  };

  const restoreAll = () => setHidden(new Set());

  // Сохранение удаления: скрытые колонки (только производные -- защитный
  // фильтр по реестру; бэкенд валидирует повторно) уходят РОВНО ОДНИМ
  // POST /dataset/derived-columns/delete. Успех: скрытие сброшено, кэш
  // страниц и меты очищен (состав колонок изменился!), refreshKey
  // перечитывает реестр и окно строк -- сетка показывает датасет после
  // удаления; честный статус «Сохранено: удалено колонок: N». Отказ:
  // alert с detail, скрытие СОХРАНЕНО (можно повторить).
  const saveDeletion = async () => {
    if (hidden.size === 0 || saving) return;
    const targets = [...hidden].filter((name) => derivedMap.has(name));
    if (targets.length === 0) return;
    setSaving(true);
    setSaveError(null);
    setSaveSuccess(null);
    try {
      const res = await fetch(sessionApiUrl("/dataset/derived-columns/delete"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ columns: targets }),
      });
      if (!res.ok) throw new Error(await responseDetail(res));
      const data: DeleteColumnsResponse = await res.json();
      setHidden(new Set());
      setPages(new Map());
      setMeta(null);
      setRefreshKey((k) => k + 1);
      setSaveSuccess(`Сохранено: удалено колонок: ${data.deleted.length}`);
    } catch (caught) {
      setSaveError(caught instanceof Error ? caught.message : "Не удалось сохранить удаление колонок");
    } finally {
      setSaving(false);
    }
  };

  const emptyRegistry = derivedTotal !== null && derivedTotal === 0;

  return (
    <section
      role="region"
      aria-label="Редактор датасета"
      className="h-[468px] rounded-lg border border-neutral-200 bg-white p-4 flex flex-col"
    >
      {/* Верхняя строка бокса: слева фильтры-чекбоксы + «Выбрать»
          (паттерн MANUAL-*), справа -- «Вернуть все колонки» (отмена
          скрытия, disabled при пустом) и ПРАВЕЕ неё «Сохранить»
          (первичная кнопка: persist удаления скрытых, disabled при
          пустом скрытии) -- дефект-репорт: сохранить удаление было
          НЕВОЗМОЖНО. */}
      <div className="flex items-center gap-3 mb-2 shrink-0">
        <label className="flex items-center gap-1.5 text-xs text-neutral-700">
          <input
            type="checkbox"
            checked={pendingFilter === "all"}
            onChange={() => setPendingFilter((prev) => (prev === "all" ? null : "all"))}
            className="accent-brand"
          />
          Весь датасет
        </label>
        <label className="flex items-center gap-1.5 text-xs text-neutral-700">
          <input
            type="checkbox"
            checked={pendingFilter === "derived"}
            onChange={() => setPendingFilter((prev) => (prev === "derived" ? null : "derived"))}
            className="accent-brand"
          />
          Только добавленные колонки
        </label>
        <button
          type="button"
          disabled={pendingFilter === null}
          title={pendingFilter === null ? "Выберите фильтр" : undefined}
          onClick={() => {
            if (pendingFilter !== null) setAppliedFilter(pendingFilter);
          }}
          className="rounded bg-brand-light px-2 py-1 text-xs text-neutral-700 hover:bg-brand-light/80 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Выбрать
        </button>
        <button
          type="button"
          disabled={hidden.size === 0 || saving}
          onClick={restoreAll}
          className="ml-auto rounded bg-brand-light px-2 py-1 text-xs text-neutral-700 hover:bg-brand-light/80 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Вернуть все колонки
        </button>
        <button
          type="button"
          disabled={hidden.size === 0 || saving}
          onClick={() => void saveDeletion()}
          title={
            hidden.size === 0
              ? "Скрытых колонок нет"
              : `Удалить из датасета скрытые колонки: ${hidden.size}`
          }
          className="rounded bg-brand px-3 py-1.5 text-xs font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
        >
          {saving ? "Сохранение…" : "Сохранить"}
        </button>
      </div>

      {/* Чипы скрытых колонок с индивидуальной возвратной ×; честная
          строка «Скрыто из просмотра: N» + бейдж «датасет не изменён»
          (истина ДО сохранения) + подсказка, что удаление применится
          кнопкой «Сохранить» (P2: скрытие -- очередь удаления). */}
      {hidden.size > 0 && (
        <div className="mb-2 flex flex-wrap items-center gap-2 shrink-0" data-testid="view-editor-hidden-chips">
          <span className="text-xs text-neutral-500">Скрыто из просмотра: {hidden.size}</span>
          <span
            data-testid="view-editor-unchanged-badge"
            className="rounded-full bg-green-100 px-2 py-0.5 text-[10px] font-medium text-green-700"
            title="Колонки скрыты только из этого просмотра; сам датасет изменится только после «Сохранить»"
          >
            датасет не изменён
          </span>
          <span className="text-xs text-neutral-500">Удаление применится кнопкой «Сохранить»</span>
          {[...hidden].map((name) => (
            <span
              key={name}
              className="flex items-center gap-1 rounded bg-neutral-100 px-2 py-0.5 text-xs text-neutral-700"
            >
              {name}
              <button
                type="button"
                aria-label={`Вернуть колонку ${name} в просмотр`}
                onClick={() => restoreColumn(name)}
                className="text-neutral-400 hover:text-neutral-700"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Честное пустое состояние реестра: отсутствие производных колонок
          -- информативный факт, а не ноль-заглушка (P4/совместимость
          column_origin.py). Сетка просмотра остаётся работоспособной. */}
      {emptyRegistry && (
        <p
          data-testid="view-editor-empty-registry"
          className="mb-2 rounded bg-brand-light/50 px-3 py-2 text-xs text-neutral-600 shrink-0"
        >
          Добавленных колонок нет — датасет в исходном составе
        </p>
      )}

      <div
        ref={scrollRef}
        data-testid="view-editor-scroll"
        onScroll={(event) => {
          const el = event.currentTarget;
          setScrollTop(el.scrollTop);
          setViewportH(el.clientHeight);
        }}
        className="flex-1 min-h-0 overflow-auto rounded-md border border-neutral-200 relative feed-scroll"
      >
        {meta && totalRows > 0 ? (
          <div
            data-testid="view-editor-spacer"
            className="relative"
            style={{ height: HEADER_H + totalRows * ROW_H, width: "max-content", minWidth: "100%" }}
          >
            {/* Sticky-шапка колонок (паттерн «Весь датасет»):
                производные -- бейдж «добавлена» + title «stage · source»
                + кнопка × (скрыть из просмотра, без сети); канонические --
                имя и dtype-нейтральный вид. */}
            <div
              className="sticky top-0 z-10 grid bg-neutral-50 border-b border-neutral-200"
              style={{ gridTemplateColumns: gridTemplate, height: HEADER_H, width: "max-content", minWidth: "100%" }}
            >
              <div className="flex items-center px-2 text-[11px] font-medium text-neutral-500">№</div>
              {visibleColumns.map((name) => {
                const derived = derivedMap.get(name);
                return (
                  <div
                    key={name}
                    className={`flex items-center gap-1 px-2 text-[11px] font-medium truncate ${
                      derived ? "text-brand" : "text-neutral-700"
                    }`}
                    title={derived ? `${name} · ${derived.stage} · ${derived.source}` : name}
                  >
                    <span className="truncate">{name}</span>
                    {derived && (
                      <span className="shrink-0 rounded-full bg-brand-light px-1.5 py-0.5 text-[9px] font-medium text-brand">
                        добавлена
                      </span>
                    )}
                    {derived && (
                      <button
                        type="button"
                        aria-label={`Скрыть колонку ${name} из просмотра`}
                        title="Скрыть из просмотра; удаление из датасета -- кнопкой «Сохранить»"
                        onClick={() => hideColumn(name)}
                        className="shrink-0 text-neutral-400 hover:text-neutral-700"
                      >
                        ×
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
            {visibleRows.map(({ position, rowIndex, values }) => (
              <div
                key={rowIndex}
                data-row-index={rowIndex}
                className={`absolute grid border-b border-neutral-100 ${position % 2 === 0 ? "bg-white" : "bg-neutral-50/60"}`}
                style={{ top: HEADER_H + position * ROW_H, height: ROW_H, gridTemplateColumns: gridTemplate, left: 0, width: "max-content", minWidth: "100%" }}
              >
                <div className="flex items-center px-2 text-[11px] text-neutral-400 tabular-nums">
                  {rowIndex + 1}
                </div>
                {/* Ячейки -- ТОЛЬКО текст (P1 read-only: input/textarea
                    в сетке запрещены, правка -- эксклюзив MANUAL-редакторов). */}
                {columnIndices.map((colIdx, j) => {
                  const name = visibleColumns[j];
                  const derived = derivedMap.get(name);
                  return (
                    <div
                      key={name}
                      className={`flex items-center px-3 text-xs truncate ${
                        derived ? "bg-brand-light/20" : ""
                      }`}
                      title={values[colIdx] ?? ""}
                    >
                      {values[colIdx] ?? ""}
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        ) : pending > 0 && !loadError ? (
          <p className="p-3 text-sm text-neutral-400">Загрузка строк…</p>
        ) : loadError ? (
          <div className="p-3">
            <p role="alert" className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">{loadError}</p>
            <button
              type="button"
              onClick={() => setRefreshKey((k) => k + 1)}
              className="mt-2 rounded bg-brand px-3 py-1.5 text-xs font-medium text-white"
            >
              Повторить
            </button>
          </div>
        ) : (
          <p className="p-3 text-sm text-neutral-500">
            {meta && totalRows === 0 ? "Датасет не содержит строк." : "…"}
          </p>
        )}
      </div>

      {/* Честный статус окна строк + догрузка + ошибка реестра
          (ошибка сети -- error-стейт с «Повторить», уже загруженные
          страницы сохранены: сетка остаётся в DOM). */}
      <div className="mt-2 flex items-center gap-2 text-[11px] text-neutral-500 shrink-0" data-testid="view-editor-footer">
        <span>{meta ? `Строки ${start + 1}–${end} из ${totalRows}` : "…"}</span>
        {pending > 0 && <span>· догружаем…</span>}
      </div>
      {derivedError && (
        <p role="alert" className="mt-2 flex items-center gap-2 rounded bg-red-50 px-3 py-2 text-sm text-red-700 shrink-0">
          {derivedError}
          <button
            type="button"
            onClick={() => void fetchDerived()}
            className="ml-auto shrink-0 rounded bg-white border border-red-300 px-2 py-0.5 text-xs text-red-700 hover:bg-red-100"
          >
            Повторить
          </button>
        </p>
      )}

      {/* Сохранение удаления (дефект-репорт): отказ -- alert с detail
          бэкенда (скрытие сохранено, можно повторить), успех -- честный
          статус (паттерн MANUAL-редакторов). */}
      {saveError && (
        <p role="alert" className="mt-2 rounded bg-red-50 px-3 py-2 text-sm text-red-700 shrink-0">
          {saveError}
        </p>
      )}
      {saveSuccess && (
        <div role="status" className="mt-2 rounded bg-green-50 px-3 py-2 text-sm text-green-700 shrink-0">
          <p>{saveSuccess}</p>
        </div>
      )}
    </section>
  );
}
