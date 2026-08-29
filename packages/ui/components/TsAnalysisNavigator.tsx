"use client";

// packages/ui/components/TsAnalysisNavigator.tsx
//
// ОБЩИЙ компонент "Путеводитель" для страницы "Навигатор" — используется
// И embedded-, И standalone-приложением. Не плодит копию UI-логики между
// apps/* — тот же урок, что с TsAnalysisPreprocessing/Validation/EDA
// (см. MIGRATION_ARCHITECTURE.md §2.1).
//
// Компоновка (Task 23 — перекомпоновка колонок):
//
//   [Левая w-60]           [Средняя w-80]               [Правая flex-1]
//   Маршрут исследования   Этапы модуля: <стоп>          Описание
//   ┌─Загрузка──●─┐       ┌─ Автопревью ────┐          [текстовое окно]
//   ├─Валидация─○─┤       │  График         │          Обзор: <пункт>
//   ├─Предобр.──○─┤       │  Подтверждение │          [область графика]
//   ├─EDA──────○─┤       │  ...           │          [Metric-карточки]
//   ├─Моделир.──○─┤       └────────────────┘
//   ├─Прогноз───○─┤       кнопка "Запустить..."
//   ├─Сценарный─○Soon
//   ├─Причинный─○Soon    Синяя кнопка
//   ├─Принятие──○Soon    "Начать анализ" → /upload
//   └─Мониторинг○Soon
//
// Новая последовательность слева направо (Task 23):
//   1. Степпер (w-60)               ← левая колонка
//   2. Этапы модуля (w-80)          ← бывшая правая → теперь средняя
//   3. Описание + Обзор (flex-1)    ← бывший центр → теперь правая
//
// Поведение:
//   - Клик по остановке степпера → меняет активный пункт (средняя панель
//     и правое окно "Обзор").
//   - Клик по пункту в средней панели → меняет содержимое правого
//     окна "Обзор" (заголовок + описание) и таблицы метрик.
//   - Кнопка "Запустить..." в средней панели — disabled (по решению
//     тимлида, вопрос 3: превью без возможности запуска).
//   - Для 4 будущих остановок (soon=true) средняя панель показывает
//     заглушку "Скоро", кнопка "Начать анализ" скрыта.
//
// Правое окно "Обзор": если в сессии есть активный датасет —
// реальные показатели из activeDataset; иначе статичный пример-иллюстрация
// с пометкой «пример» (решение тимлида, вопрос 4: гибрид (c)+(a)).

import { useState } from "react";
import Link from "next/link";
import { MapPin, ArrowRight, Lock } from "lucide-react";
import { useAppShell } from "../context/AppShellContext";
import { Metric } from "./Metric";
import {
  NAVIGATOR_STOPS,
  OVERVIEW_EXAMPLE_METRICS,
  type NavigatorStop,
} from "../lib/navigator-stops";
import { UploadAutoPreviewPipeline } from "./UploadAutoPreviewPipeline";
import { NavigatorChartPreview } from "./NavigatorChartPreview";
import { NavigatorStructureConfirmPreview } from "./NavigatorStructureConfirmPreview";
import { NavigatorQualityTeaserPreview } from "./NavigatorQualityTeaserPreview";

// ── Компонент ─────────────────────────────────────────────────

export function TsAnalysisNavigator() {
  const [activeStopId, setActiveStopId] = useState<string>(NAVIGATOR_STOPS[0].id);
  const [activeItemId, setActiveItemId] = useState<string>(NAVIGATOR_STOPS[0].items[0].id);

  const { activeDataset } = useAppShell();

  const activeStop: NavigatorStop =
    NAVIGATOR_STOPS.find((s) => s.id === activeStopId) ?? NAVIGATOR_STOPS[0];
  const activeItem =
    activeStop.items.find((it) => it.id === activeItemId) ?? activeStop.items[0];

  // При переключении остановки — сбросить активный пункт на первый.
  const handleStopClick = (stopId: string) => {
    const stop = NAVIGATOR_STOPS.find((s) => s.id === stopId);
    if (!stop) return;
    setActiveStopId(stopId);
    setActiveItemId(stop.items[0]?.id ?? "");
  };

  // Реальные показатели активного датасета, если есть; иначе — пример.
  const hasRealDataset = Boolean(activeDataset);
  const overviewMetrics = hasRealDataset
    ? [
        { label: "Файл", value: activeDataset!.name },
        { label: "Строк", value: activeDataset!.rows.toLocaleString("ru-RU") },
        { label: "Размер", value: activeDataset!.sizeLabel },
        ...(activeDataset!.frequency
          ? [{ label: "Частота", value: activeDataset!.frequency }]
          : []),
        ...(activeDataset!.nSeries
          ? [{ label: "Рядов", value: String(activeDataset!.nSeries) }]
          : []),
      ]
    : OVERVIEW_EXAMPLE_METRICS;

  return (
    <div className="flex gap-[49px] mt-8">
      {/* ── ЛЕВАЯ КОЛОНКА: Маршрут исследования ──
          Task 23: левая колонка остаётся на месте.
          Порядок слева направо: степпер | этапы модуля | описание+обзор. */}
      <aside className="w-60 shrink-0 flex flex-col gap-4">
        {/* Заголовок */}
        <div className="flex items-center gap-2">
          <MapPin size={16} className="text-brand" aria-hidden="true" />
          <h2 className="text-base font-semibold text-neutral-800">Маршрут исследования</h2>
        </div>

        {/* Степпер: 10 остановок с пунктирной линией */}
        <div className="relative">
          <div className="absolute left-[7px] top-2 bottom-2 w-0 border-l-2 border-dashed border-neutral-200" aria-hidden="true" />
          <ol className="flex flex-col gap-0.5">
            {NAVIGATOR_STOPS.map((stop, idx) => {
              const isActive = stop.id === activeStopId;
              return (
                <li key={stop.id}>
                  <button
                    type="button"
                    onClick={() => handleStopClick(stop.id)}
                    aria-pressed={isActive}
                    aria-label={stop.label}
                    className={`relative w-full flex items-center gap-2.5 rounded-lg px-1.5 py-2 text-left transition-colors ${
                      isActive ? "bg-brand-light" : "hover:bg-neutral-50"
                    }`}
                  >
                    {/* Точка-маркер на линии */}
                    <span
                      className={`relative z-10 h-3.5 w-3.5 shrink-0 rounded-full border-2 transition-colors ${
                        isActive
                          ? "border-brand bg-brand"
                          : stop.soon
                          ? "border-neutral-300 bg-white"
                          : "border-neutral-400 bg-white"
                      }`}
                      aria-hidden="true"
                    />
                    <div className="min-w-0 flex-1">
                      <div
                        className={`text-[12px] font-semibold leading-tight ${
                          isActive ? "text-brand" : stop.soon ? "text-neutral-400" : "text-neutral-700"
                        }`}
                      >
                        {stop.label}
                      </div>
                      <div className="text-[10px] text-neutral-400 mt-0.5 leading-tight truncate">
                        {stop.subtitle}
                      </div>
                    </div>
                    {stop.soon && (
                      <span
                        className="shrink-0 text-[9px] uppercase tracking-wide text-neutral-400 border border-neutral-200 rounded px-1 py-0.5"
                        title="Модуль в разработке"
                      >
                        Soon
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ol>
        </div>

        {/* Серая разделительная черта */}
        <div className="h-px bg-neutral-200" role="separator" />

        {/* Синяя кнопка "Начать анализ" — только для существующих остановок */}
        {!activeStop.soon && (
          <Link
            href={activeStop.href}
            className="inline-flex items-center justify-center gap-2 bg-brand text-white rounded px-4 py-2.5 text-sm font-medium hover:bg-brand/90 transition-colors"
          >
            Начать анализ <ArrowRight size={16} aria-hidden="true" />
          </Link>
        )}
        {activeStop.soon && (
          <div
            className="inline-flex items-center justify-center gap-2 bg-neutral-100 text-neutral-400 rounded px-4 py-2.5 text-sm font-medium cursor-not-allowed"
            aria-disabled="true"
          >
            <Lock size={14} aria-hidden="true" /> Скоро
          </div>
        )}

      </aside>

      {/* ── СРЕДНЯЯ КОЛОНКА: Этапы модуля (превью пунктов активной остановки) ──
          Task 23: перекомпоновка. Бывшая правая колонка теперь средняя.
          Порядок слева направо: степпер | этапы модуля | описание+обзор. */}
      <aside className="w-80 shrink-0">
        <div className="max-h-[820px] overflow-y-auto pr-1 space-y-3">
          <h2 className="text-base font-semibold text-neutral-800 mb-1">
            Этапы модуля: {activeStop.label}
          </h2>
          <p className="text-[11px] text-neutral-500 mb-3">
            {!activeStop.soon
              ? "Превью всех пунктов модуля."
              : "Модуль в разработке. Пункты — проектные, могут измениться."}
          </p>

          {activeStop.items.map((item) => {
            const isActive = item.id === activeItemId;
            return (
              <article
                key={item.id}
                className={`rounded-lg border p-3 transition-colors cursor-pointer ${
                  isActive
                    ? "border-brand bg-brand-light"
                    : "border-neutral-200 bg-white hover:bg-neutral-50"
                }`}
                onClick={() => setActiveItemId(item.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setActiveItemId(item.id);
                  }
                }}
                tabIndex={0}
                aria-pressed={isActive}
              >
                <div className="flex items-start gap-2 mb-1">
                  <span
                    className={`mt-1 h-3 w-3 shrink-0 rounded-full border-2 ${
                      isActive ? "border-brand bg-brand" : "border-neutral-300"
                    }`}
                    aria-hidden="true"
                  />
                  <h4 className="text-sm font-semibold text-neutral-800 leading-snug flex-1">
                    {item.title}
                  </h4>
                </div>
                <p className="text-xs text-neutral-600 leading-relaxed pl-5">
                  {item.description}
                </p>

                {/* Неактивная кнопка "Запустить..." */}
                <button
                  type="button"
                  disabled
                  className="mt-2 ml-5 inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium bg-neutral-100 text-neutral-400 cursor-not-allowed"
                  title="Доступно в самом модуле"
                >
                  Запустить анализ
                </button>
              </article>
            );
          })}
        </div>
      </aside>

      {/* ── ПРАВАЯ КОЛОНКА: Описание + Обзор ──
          Task 23: перекомпоновка. Бывшая центральная колонка теперь правая. */}
      <section className="flex-1 min-w-0 flex flex-col gap-5">
        {/* Окно "Описание" */}
        <div>
          <h3 className="font-semibold text-neutral-900 mb-1">Описание</h3>
          <p className="text-xs text-neutral-500 mb-2">
            {!activeStop.soon
              ? `${activeStop.label} — ${activeStop.subtitle}`
              : `${activeStop.label} — модуль в разработке`}
          </p>
          <div className="rounded-lg border border-neutral-200 bg-brand-light/50 px-4 py-3 min-h-[160px] max-h-[200px] overflow-y-auto">
            <p className="text-sm text-neutral-700 leading-relaxed whitespace-pre-wrap">
              {activeStop.description}
            </p>
          </div>
        </div>

        {/* Окно "Обзор" */}
        <div>
          <h3 className="font-semibold text-neutral-900 mb-1">
            Обзор: {activeItem.title}
          </h3>
          <p className="text-xs text-neutral-500 mb-2">
            {!activeStop.soon
              ? "Превью пункта активной остановки"
              : "Превью будущего функционала"}
            {!hasRealDataset && (
              <span className="ml-2 inline-flex items-center rounded bg-amber-50 border border-amber-200 px-1.5 py-0.5 text-[10px] text-amber-700 uppercase tracking-wide">
                пример
              </span>
            )}
          </p>

          {/* Область визуализации — зависит от пункта активной остановки.
              Task 22: для пары «Загрузка» + «Автопревью и типы колонок»
              (id="upload" + id="preview") рендерим блок-схему «Пайплайн
              автопревью» (UploadAutoPreviewPipeline) — статичную
              информационную схему последовательности шагов, которые
              бэкенд выполняет сразу после загрузки файла.

              Задача 2026-08-29: для пары «Загрузка» + «График»
              (id="upload" + id="chart") рендерим статичный линейный график
              признака volume синтетического датасета demo_finance_ohlcv.csv
              (NavigatorChartPreview). График НЕ зависит от сессии/сети —
              отображается при любых условиях, даже если сам датасет удалён.

              Задача 2026-08-30: для пары «Загрузка» + «Подтверждение
              автоопределения» (id="upload" + id="structure_confirm")
              рендерим статичную блок-схему алгоритма автоопределения
              структуры (3 параллельных детектора: date / entity / frequency)
              на основе РЕАЛЬНОЙ бэкенд-логики (score_all_columns_as_date /
              score_all_columns_as_entity_group / detect_column_frequency).
              Аналитик мгновенно понимает алгоритм благодаря инфографике.

              Задача 2026-08-30 (Teaser качества): для пары «Загрузка» +
              «Teaser качества» (id="upload" + id="quality_teaser")
              рендерим статичную блок-схему подсчёта 4 счётчиков качества
              (cols_with_missing / cols_with_outliers / rows_total /
              duplicates) на основе РЕАЛЬНОЙ бэкенд-логики
              (_compute_quality_teaser, QualityTeaserOut).

              Для остальных пунктов — текстовая заглушка (своя визуализация
              для каждого пункта в будущих задачах). */}
          {activeStopId === "upload" && activeItemId === "preview" ? (
            <UploadAutoPreviewPipeline />
          ) : activeStopId === "upload" && activeItemId === "chart" ? (
            <NavigatorChartPreview />
          ) : activeStopId === "upload" && activeItemId === "structure_confirm" ? (
            <NavigatorStructureConfirmPreview />
          ) : activeStopId === "upload" && activeItemId === "quality_teaser" ? (
            <NavigatorQualityTeaserPreview />
          ) : (
            <div
              className="bg-brand-light rounded-lg h-[280px] flex items-center justify-center text-sm text-neutral-500 border border-brand/10"
              role="img"
              aria-label={`Область визуализации для «${activeItem.title}»`}
            >
              [ область графика/таблицы/блок-схемы для «{activeItem.title}» ]
            </div>
          )}

          {/* Метрики: реальные (если есть датасет) или пример */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4">
            {overviewMetrics.map((m) => (
              <Metric key={m.label} label={m.label} value={m.value} />
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
