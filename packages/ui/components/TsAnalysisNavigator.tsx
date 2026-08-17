"use client";

// packages/ui/components/TsAnalysisNavigator.tsx
//
// ОБЩИЙ компонент "Путеводитель" для страницы "Навигатор" — используется
// И embedded-, И standalone-приложением. Не плодит копию UI-логики между
// apps/* — тот же урок, что с TsAnalysisPreprocessing/Validation/EDA
// (см. MIGRATION_ARCHITECTURE.md §2.1).
//
// Компоновка (по макету «Навигатор_NEW.png», см. upload/Навигатор_NEW.png):
//
//   [Левая ~240px]         [Центр flex-1]              [Правая ~320px]
//   Путеводитель           Описание                    {превью пунктов
//   ┌─Загрузка──●─┐        [текстовое окно]             активной
//   ├─Валидация─○─┤        Обзор: <пункт>               остановки,
//   ├─Предобр.──○─┤        [область графика]            radio-список,
//   ├─EDA──────○─┤        [Metric-карточки]            кнопка
//   ├─Моделир.──○─┤                                    "Запустить..."
//   ├─Прогноз───○─┤        ─ серая черта ─              неактивна}
//   ├─Сценарный─○Soon    Синяя кнопка
//   ├─Причинный─○Soon    "Начать анализ" → /upload
//   ├─Принятие──○Soon
//   └─Мониторинг○Soon    Субмодуль "Тарифы"
//                          radio: demo/starter/
//                          professional/enterprise
//
// Поведение:
//   - Клик по остановке степпера → меняет активный пункт (правая панель
//     и центральное окно).
//   - Клик по пункту в правой панели → меняет содержимое центрального
//     окна "Обзор" (заголовок + описание) и таблицы метрик.
//   - Кнопка "Запустить..." в правой панели — disabled (по решению
//     тимлида, вопрос 3: превью без возможности запуска).
//   - Для 4 будущих остановок (soon=true) правая панель показывает
//     заглушку "Скоро", кнопка "Начать анализ" скрыта.
//   - "Тарифы" — декоративный STUB (выбор radio ни к чему не ведёт,
//     отдельная задача — см. lib/plans.ts и будущий work по биллингу).
//
// Центральное окно "Обзор": если в сессии есть активный датасет —
// реальные показатели из activeDataset; иначе статичный пример-иллюстрация
// с пометкой «пример» (решение тимлида, вопрос 4: гибрид (c)+(a)).

import { useState } from "react";
import Link from "next/link";
import { MapPin, ArrowRight, Lock } from "lucide-react";
import { useAppShell } from "../context/AppShellContext";
import { PLAN_DEFINITIONS, type PlanName } from "../lib/plans";
import { Metric } from "./Metric";
import {
  NAVIGATOR_STOPS,
  OVERVIEW_EXAMPLE_METRICS,
  type NavigatorStop,
} from "../lib/navigator-stops";

// ── Компонент ─────────────────────────────────────────────────

export function TsAnalysisNavigator() {
  const [activeStopId, setActiveStopId] = useState<string>(NAVIGATOR_STOPS[0].id);
  const [activeItemId, setActiveItemId] = useState<string>(NAVIGATOR_STOPS[0].items[0].id);
  // Декоративный STUB: выбор тарифа ни к чему не ведёт (отдельная задача).
  const [activePlan, setActivePlan] = useState<PlanName>("professional");

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
    <div className="flex gap-6 mt-8">
      {/* ── ЛЕВАЯ КОЛОНКА: Путеводитель (степпер + Тарифы) ── */}
      <aside className="w-60 shrink-0 flex flex-col gap-4">
        {/* Заголовок */}
        <div className="flex items-center gap-2">
          <MapPin size={16} className="text-brand" aria-hidden="true" />
          <h2 className="text-base font-semibold text-neutral-800">Путеводитель</h2>
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

        {/* ── Субмодуль "Тарифы" ──
            Декоративный STUB (по решению тимлида, вопрос 5): выбор radio
            ни к чему не ведёт, изменения — через отдельную задачу. */}
        <div className="mt-2">
          <h3 className="text-[13px] font-semibold text-neutral-800 mb-2">Тарифы</h3>
          <div className="flex flex-col gap-1">
            {(Object.keys(PLAN_DEFINITIONS) as PlanName[]).map((planName) => {
              const isActive = planName === activePlan;
              return (
                <label
                  key={planName}
                  className={`flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-sm cursor-pointer transition-colors ${
                    isActive
                      ? "border-brand bg-brand-light text-neutral-900"
                      : "border-neutral-200 bg-white text-neutral-600 hover:bg-neutral-50"
                  }`}
                >
                  <input
                    type="radio"
                    name="tariff-plan"
                    value={planName}
                    checked={isActive}
                    onChange={() => setActivePlan(planName)}
                    className="sr-only"
                  />
                  <span
                    className={`h-3.5 w-3.5 rounded-full border-2 flex items-center justify-center ${
                      isActive ? "border-brand" : "border-neutral-300"
                    }`}
                    aria-hidden="true"
                  >
                    {isActive && <span className="h-1.5 w-1.5 rounded-full bg-brand" />}
                  </span>
                  <span className="font-medium capitalize">{planName}</span>
                </label>
              );
            })}
          </div>
        </div>
      </aside>

      {/* ── ЦЕНТРАЛЬНАЯ КОЛОНКА: Описание + Обзор ── */}
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

          {/* Область графика — заглушка, реальный график зависит от пункта */}
          <div
            className="bg-brand-light rounded-lg h-[280px] flex items-center justify-center text-sm text-neutral-500 border border-brand/10"
            role="img"
            aria-label={`Область визуализации для «${activeItem.title}»`}
          >
            [ область графика/таблицы/блок-схемы для «{activeItem.title}» ]
          </div>

          {/* Метрики: реальные (если есть датасет) или пример */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4">
            {overviewMetrics.map((m) => (
              <Metric key={m.label} label={m.label} value={m.value} />
            ))}
          </div>
        </div>
      </section>

      {/* ── ПРАВАЯ КОЛОНКА: превью пунктов активной остановки ── */}
      <aside className="w-80 shrink-0">
        <div className="max-h-[820px] overflow-y-auto pr-1 space-y-3">
          <h3 className="text-sm font-semibold text-neutral-800 mb-1">
            Пункты: {activeStop.label}
          </h3>
          <p className="text-[11px] text-neutral-500 mb-3">
            {!activeStop.soon
              ? "Превью всех пунктов модуля. Кнопка «Запустить…» доступна в самом модуле."
              : "Модуль в разработке. Пункты — проектные, могут измениться."}
          </p>

          {activeStop.items.map((item) => {
            const isActive = item.id === activeItemId;
            return (
              <article
                key={item.id}
                className={`rounded-lg border p-3 transition-colors cursor-pointer ${
                  isActive
                    ? "border-brand bg-brand-light border-l-4 border-l-brand"
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
    </div>
  );
}
