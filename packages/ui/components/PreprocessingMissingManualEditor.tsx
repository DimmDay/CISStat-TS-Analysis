"use client";

// Ручное исправление пропусков -- редактор датасета остановки «Пропуски»
// (MANUAL-MISSING-1, 2026-10-15, постановка тимлида). Перенос legacy-
// функционала app.py (~7760-7930) с улучшениями:
//   radio «Все/Пропуски/Без пропусков» → чекбоксы «Только с пропусками»/
//   «Весь датасет» + кнопка «Выбрать» (явное применение фильтра; дефолт --
//   «Только с пропусками», применён сразу: окно остановки открывается в
//   контексте исправления пропусков);
//   st.data_editor → виртуализированная сетка с input-ячейками
//   (пагинация GET /dataset/missing-editor-rows по ОБЛАСТИ фильтра, кэш
//   страниц, ползунок на все строки области -- паттерн «Весь датасет»
//   UI-UPLOAD-FULL-1; NaN -- пустая ячейка, честно);
//   «💾 Сохранить» (df_work.update(edited_df)) → кнопка «Применить»
//   (POST /dataset/missing-manual-corrections apply:true) --
//   функционально соответствует «Применить исправления» мастера: датасет
//   заменяется атомарно (AUDIT-C: no-op не повышает ревизию), профиль
//   пересчитывается, каскад handleApplied (datasetVersion) запускается.
//
// Правки адресуются ПОЗИЦИОННЫМ row_index (несут страницы API) и
// переживают смену фильтра/прокрутку (Map в стейте, не в страницах);
// числа валидируются на клиенте до POST (нечисловое значение в
// numeric-колонке -- честная ошибка без запроса), бэкенд валидирует
// повторно (defence in depth). aria-label ячейки: «Строка N, колонка X»
// (N -- позиция 1-based, как в нумерации ведущей колонки).

import { useCallback, useEffect, useRef, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";

type FilterMode = "missing" | "all";
type Semantic = "numeric" | "datetime" | "categorical" | "text";

interface EditorColumn {
  column: string;
  dtype: string;
  semantic: Semantic;
}

interface EditorRow {
  row_index: number;
  cells: Array<string | number | null>;
}

interface EditorRowsResponse {
  columns: EditorColumn[];
  rows: EditorRow[];
  offset: number;
  limit: number;
  total_rows: number;
  returned: number;
  has_more: boolean;
}

interface ManualApplyResponse {
  applied: boolean;
  total_edited_requested: number;
  total_changed: number;
  total_missing_before: number;
  total_missing_after: number;
}

const PAGE_LIMIT = 200; // строк на страницу запроса (<= капы бэкенда)
const ROW_H = 32;
const HEADER_H = 36;
const OVERSCAN_ROWS = 10;
// jsdom не считает layout (clientHeight = 0) -- фолбэк высоты вьюпорта
// для расчёта видимого окна; в браузере clientHeight реален.
const VIEWPORT_FALLBACK_H = 480;

async function responseDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Нейтральная ошибка ниже покрывает ответ без JSON.
  }
  return `Не удалось выполнить операцию (HTTP ${response.status})`;
}

function displayCellValue(cell: string | number | null): string {
  return cell === null ? "" : String(cell);
}

export function PreprocessingMissingManualEditor({ onApplied }: { onApplied: () => void }) {
  // ── Фильтр области просмотра (legacy «Все/Пропуски») ──
  // pendingFilter -- состояние чекбоксов; appliedFilter -- область,
  // применённая к окну (меняется ТОЛЬКО кнопкой «Выбрать»). Чекбоксы
  // взаимоисключающие (проверка одного снимает другой); клик по
  // чекнутому снимает чек (честная checkbox-семантика); оба сняты --
  // «Выбрать» честно заблокирован. Дефолт -- «Только с пропусками»
  // (применён сразу при монтировании).
  const [pendingFilter, setPendingFilter] = useState<FilterMode | null>("missing");
  const [appliedFilter, setAppliedFilter] = useState<FilterMode>("missing");

  const [meta, setMeta] = useState<{ columns: EditorColumn[]; totalRows: number } | null>(null);
  const [pages, setPages] = useState<Map<string, EditorRow[]>>(new Map());
  const [pending, setPending] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportH, setViewportH] = useState(0);
  const [refreshKey, setRefreshKey] = useState(0);

  // Правки ячеек: ключ `${row_index}::${column}` → сырая строка input.
  // Живут НЕ в страницах -- переживают смену фильтра/прокрутку/догрузку.
  const [edits, setEdits] = useState<Map<string, string>>(new Map());
  const [busy, setBusy] = useState<"apply" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [appliedCount, setAppliedCount] = useState<number | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);
  const inFlightRef = useRef<Set<string>>(new Set());

  const fetchPage = useCallback(
    async (filter: FilterMode, page: number) => {
      const key = `${filter}:${page}`;
      if (inFlightRef.current.has(key)) return;
      inFlightRef.current.add(key);
      setPending((n) => n + 1);
      try {
        const offset = page * PAGE_LIMIT;
        const res = await fetch(
          sessionApiUrl(
            `/dataset/missing-editor-rows?offset=${offset}&limit=${PAGE_LIMIT}&missing_only=${filter === "missing" ? "true" : "false"}`,
          ),
          { credentials: "include" },
        );
        if (!res.ok) throw new Error(await responseDetail(res));
        const data: EditorRowsResponse = await res.json();
        setMeta((prev) => (prev && prev.totalRows === data.total_rows ? prev : { columns: data.columns, totalRows: data.total_rows }));
        setPages((prev) => {
          const next = new Map(prev);
          next.set(key, data.rows);
          return next;
        });
        setLoadError(null);
      } catch (caught) {
        setLoadError(caught instanceof Error ? caught.message : "Не удалось загрузить строки датасета");
      } finally {
        inFlightRef.current.delete(key);
        setPending((n) => n - 1);
      }
    },
    [],
  );

  // Смена применённого фильтра -- новая область: страницы и меты сброшены,
  // прокрутка к началу (ползунок размечен заново по total_rows области).
  useEffect(() => {
    setPages(new Map());
    setMeta(null);
    setLoadError(null);
    setScrollTop(0);
    if (scrollRef.current) scrollRef.current.scrollTop = 0;
  }, [appliedFilter]);

  // Видимое окно [start, end) по позиции ползунка: страницы, пересекающие
  // окно, догружаются (кэш: обратная прокрутка/смена вкладок не
  // перезапрашивает; in-flight защита от повторов). refreshKey --
  // принудительная перечитка окна после apply/ошибки.
  const totalRows = meta?.totalRows ?? 0;
  const viewport = viewportH || VIEWPORT_FALLBACK_H;
  const start = Math.max(0, Math.floor(scrollTop / ROW_H) - OVERSCAN_ROWS);
  const end = Math.min(totalRows, Math.ceil((scrollTop + viewport) / ROW_H) + OVERSCAN_ROWS);

  useEffect(() => {
    if (totalRows === 0 && meta) return;
    const firstPage = Math.floor(start / PAGE_LIMIT);
    const lastPage = Math.floor(Math.max(end - 1, start) / PAGE_LIMIT);
    for (let p = firstPage; p <= lastPage; p++) {
      if (!pages.has(`${appliedFilter}:${p}`)) void fetchPage(appliedFilter, p);
    }
    // pages сознательно вне зависимостей: проверка актуальна на момент
    // эффекта, лишние зависимости вызвали бы цикл (fetchPage сам защищён
    // от повторов in-flight) -- паттерн «Весь датасет» UI-UPLOAD-FULL-1.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appliedFilter, refreshKey, start, end, totalRows, meta, fetchPage]);

  const visibleRows: Array<{ row: EditorRow; position: number }> = [];
  if (meta && totalRows > 0) {
    for (let i = start; i < end; i++) {
      const page = Math.floor(i / PAGE_LIMIT);
      const pageRows = pages.get(`${appliedFilter}:${page}`);
      if (!pageRows) continue;
      const within = i - page * PAGE_LIMIT;
      const row = pageRows[within];
      if (row) visibleRows.push({ row, position: i });
    }
  }

  const gridTemplate = buildGridTemplate(meta?.columns ?? []);

  const setEdit = (rowIndex: number, column: string, raw: string) => {
    setEdits((prev) => {
      const next = new Map(prev);
      next.set(`${rowIndex}::${column}`, raw);
      return next;
    });
  };

  const applyEdits = async () => {
    if (edits.size === 0 || busy !== null || !meta) return;
    // Клиентская валидация numeric-колонок ДО POST: нечисловое значение
    // -- честная ошибка без запроса (бэкенд валидирует повторно).
    const payloads: Array<{ row_index: number; column: string; value: string | number | null }> = [];
    for (const [key, raw] of edits) {
      const separator = key.indexOf("::");
      const rowIndex = Number(key.slice(0, separator));
      const column = key.slice(separator + 2);
      const semantic = meta.columns.find((c) => c.column === column)?.semantic;
      if (semantic === "numeric" && raw.trim() !== "") {
        const num = Number(raw);
        if (!isFinite(num)) {
          setError(`Значение «${raw}» в колонке «${column}» (строка ${rowIndex + 1}) не является числом`);
          return;
        }
        payloads.push({ row_index: rowIndex, column, value: num });
      } else {
        payloads.push({ row_index: rowIndex, column, value: raw.trim() === "" ? null : raw });
      }
    }
    setBusy("apply");
    setError(null);
    setSuccess(null);
    try {
      const res = await fetch(sessionApiUrl("/dataset/missing-manual-corrections"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ edits: payloads, apply: true }),
      });
      if (!res.ok) throw new Error(await responseDetail(res));
      const data: ManualApplyResponse = await res.json();
      setEdits(new Map());
      setPages(new Map());
      setRefreshKey((k) => k + 1);
      setSuccess("Изменения применены, профиль пересчитан");
      setAppliedCount(data.total_changed);
      onApplied();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось применить правки");
    } finally {
      setBusy(null);
    }
  };

  const statusLabel =
    totalRows === 0 && meta
      ? appliedFilter === "missing"
        ? "Пропусков в этой области нет"
        : "Датасет не содержит строк"
      : `Строки ${start + 1}–${end} из ${totalRows}`;

  return (
    <section
      role="region"
      aria-label="Ручное исправление пропусков"
      className="h-[468px] rounded-lg border border-neutral-200 bg-white p-4 flex flex-col"
    >
      {/* Верхняя строка бокса: слева фильтры-чекбоксы + «Выбрать», справа
          («на этом же уровне») -- «Применить» (ml-auto, правый край). */}
      <div className="flex items-center gap-3 mb-3 shrink-0">
        <label className="flex items-center gap-1.5 text-xs text-neutral-700">
          <input
            type="checkbox"
            checked={pendingFilter === "missing"}
            onChange={() => setPendingFilter((prev) => (prev === "missing" ? null : "missing"))}
            className="accent-brand"
          />
          Только с пропусками
        </label>
        <label className="flex items-center gap-1.5 text-xs text-neutral-700">
          <input
            type="checkbox"
            checked={pendingFilter === "all"}
            onChange={() => setPendingFilter((prev) => (prev === "all" ? null : "all"))}
            className="accent-brand"
          />
          Весь датасет
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
          disabled={edits.size === 0 || busy !== null}
          onClick={() => void applyEdits()}
          className="ml-auto rounded bg-brand px-3 py-1.5 text-xs font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy === "apply" ? "Применение…" : "Применить"}
        </button>
      </div>

      <div
        ref={scrollRef}
        onScroll={(event) => {
          const el = event.currentTarget;
          setScrollTop(el.scrollTop);
          setViewportH(el.clientHeight);
        }}
        className="flex-1 min-h-0 overflow-auto rounded-md border border-neutral-200 relative feed-scroll"
      >
        {meta && totalRows > 0 ? (
          <div
            data-testid="manual-editor-spacer"
            className="relative"
            style={{ height: HEADER_H + totalRows * ROW_H }}
          >
            {/* Sticky-шапка колонок (паттерн «Весь датасет» UI-UPLOAD-FULL-1) */}
            <div
              className="sticky top-0 z-10 grid bg-neutral-50 border-b border-neutral-200"
              style={{ gridTemplateColumns: gridTemplate, height: HEADER_H }}
            >
              <div className="flex items-center px-2 text-[11px] font-medium text-neutral-500">№</div>
              {(meta?.columns ?? []).map((col) => (
                <div
                  key={col.column}
                  className="flex items-center px-2 text-[11px] font-medium text-neutral-700 truncate"
                  title={`${col.column} · ${col.dtype} · ${col.semantic}`}
                >
                  {col.column}
                </div>
              ))}
            </div>
            {visibleRows.map(({ row, position }) => (
              <div
                key={row.row_index}
                className={`absolute grid border-b border-neutral-100 ${position % 2 === 0 ? "bg-white" : "bg-neutral-50/60"}`}
                style={{ top: HEADER_H + position * ROW_H, height: ROW_H, gridTemplateColumns: gridTemplate, left: 0, right: 0 }}
              >
                <div className="flex items-center px-2 text-[11px] text-neutral-400">
                  {row.row_index + 1}
                </div>
                {(meta?.columns ?? []).map((col, colIdx) => {
                  const key = `${row.row_index}::${col.column}`;
                  const edited = edits.get(key);
                  const value = edited ?? displayCellValue(row.cells[colIdx] ?? null);
                  return (
                    <div key={col.column} className="flex items-stretch min-w-0">
                      <input
                        type="text"
                        inputMode={col.semantic === "numeric" ? "decimal" : undefined}
                        value={value}
                        onChange={(event) => setEdit(row.row_index, col.column, event.target.value)}
                        aria-label={`Строка ${row.row_index + 1}, колонка ${col.column}`}
                        className="w-full h-full px-2 text-xs bg-transparent outline-none focus:bg-brand-light/30 min-w-0"
                      />
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        ) : busy === null && meta === null && !loadError && pending > 0 ? (
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
          <p className="p-3 text-sm text-neutral-500">{statusLabel}</p>
        )}
      </div>

      {/* Честный статус окна строк + догрузка/счётчики применения */}
      <div className="mt-2 flex items-center gap-2 text-[11px] text-neutral-500 shrink-0" data-testid="manual-editor-footer">
        <span>{meta ? statusLabel : "…"}</span>
        {pending > 0 && <span>· догружаем…</span>}
      </div>
      {error && <p role="alert" className="mt-2 rounded bg-red-50 px-3 py-2 text-sm text-red-700 shrink-0">{error}</p>}
      {success && (
        <div role="status" className="mt-2 rounded bg-green-50 px-3 py-2 text-sm text-green-700 shrink-0">
          <p>{success}</p>
          {appliedCount !== null && <p className="mt-0.5 text-xs">Изменено значений: {appliedCount}</p>}
        </div>
      )}
    </section>
  );
}

// gridTemplateColumns: ведущая колонка № + minmax по колонкам датасета
// (паттерн fullGridTemplate() «Весь датасет» UI-UPLOAD-FULL-1).
function buildGridTemplate(columns: EditorColumn[]): string {
  const suffix = columns.map(() => "minmax(150px, 1fr)").join(" ");
  return `44px ${suffix}`.trim();
}
