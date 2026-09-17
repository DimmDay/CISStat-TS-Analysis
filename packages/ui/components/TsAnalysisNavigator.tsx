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
// Task NAVDET-1 (2026-09-17): сжатие компоновки по ширине по паттерну
//   главной страницы — боковые зазоры 24px от границ страницы (px-6
//   на корне flex). Механика распределения сжатия: левая колонка
//   «Маршрут исследования» (w-60) и средняя «Этапы модуля» (w-80)
//   фиксированы и shrink-0 — их ширина НЕ меняется; правая колонка
//   «Описание»+«Обзор» (flex-1 min-w-0) — единственная гибкая, поэтому
//   ВСЁ сжатие (48px суммарно) поглощается именно ею. Зазор между
//   колонками (gap-[49px], Task 23b) не тронут — сжатие не через gap.
//
// Task NAVDET-2 (2026-09-17): статичные заголовок и подзаголовок средней
//   колонки — h2 «Этапы модуля: …» и подзаголовок «Превью всех пунктов
//   модуля.» вынесены ИЗ окна скроллинга (div.max-h-[820px]
//   overflow-y-auto) наружу, в сам aside. Теперь при прокрутке списка
//   карточек заголовок с подзаголовком остаются на месте — как статичные
//   заголовки соседних колонок («Маршрут исследования», «Описание»).
//   Скроллится только список карточек пунктов; само окно скроллинга
//   (max-h-[820px], overflow-y-auto, pr-1, space-y-3) не менялось.
//   Зазор h2→подзаголовок сохранён прежним (12px): внутри space-y-3 он
//   складывался из коллапса mb-1 h2 и mt 12px от space-y; вне space-y
//   та же геометрия воспроизведена классом mb-3 у h2.
//
// Task NAVDET-3 (2026-09-17): тематические иконки СПЕРЕДИ заголовков
//   «Этапы модуля», «Описание» и «Обзор» — по паттерну секции 2
//   «Примеры прикладных задач» (AppliedTasksNavigator): обёртка
//   flex items-center gap-2 [mb-*], lucide-иконка size={16}
//   className="text-brand" aria-hidden="true"; отступ mb перенесён
//   с заголовка на обёртку — геометрия прежняя. Словарь иконок
//   секции 2: «Этапы модуля» → ListChecks (списковая тематика,
//   как «Основная задача»), «Описание» → BriefcaseBusiness,
//   «Обзор» → Eye — те же иконки у тех же смысловых заголовков.
//   Заголовок «Маршрут исследования» уже с иконкой MapPin — не тронут.
//
// Task NAVDET-5 (2026-09-17): (1) окно «Обзор» пункта «Источник: файл или
//   БД» (upload+source, 9-й пункт «Загрузки») получило статичную блок-схему
//   источника данных NavigatorSourceFileDbPreview — по паттерну других
//   остановок (NavigatorFormatsVolumePreview и родня); текстовая заглушка
//   для этого пункта больше не показывается, все 9 пунктов остановки
//   «Загрузка» имеют специализированный Обзор. (2) Из блока метрик под
//   окном «Обзор» удалены бейджи «Файл»/«Строк»/«Размер» (решение
//   тимлида); остались опциональные «Частота»/«Рядов» и пример без
//   датасета; пустая сетка бейджей не рендерится.
//
// Правое окно "Обзор": если в сессии есть активный датасет —
// реальные показатели из activeDataset; иначе статичный пример-иллюстрация
// с пометкой «пример» (решение тимлида, вопрос 4: гибрид (c)+(a)).

import { useState } from "react";
import Link from "next/link";
import { MapPin, ArrowRight, Lock, ListChecks, BriefcaseBusiness, Eye } from "lucide-react";
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
import { NavigatorTechInfoPreview } from "./NavigatorTechInfoPreview";
import { NavigatorPreview55Preview } from "./NavigatorPreview55Preview";
import { NavigatorDistributionPreview } from "./NavigatorDistributionPreview";
import { NavigatorFormatsVolumePreview } from "./NavigatorFormatsVolumePreview";
import { NavigatorSourceFileDbPreview } from "./NavigatorSourceFileDbPreview";

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

  // Показатели под окном «Обзор». Task NAVDET-5: бейджи «Файл»/«Строк»/
  // «Размер» удалены по решению тимлида — остаются только опциональные
  // «Частота»/«Рядов» (если метаданные есть в сессии) либо пример без
  // датасета (OVERVIEW_EXAMPLE_METRICS, решение тимлида, вопрос 4).
  // Если массив пуст — сетка бейджей не рендерится вовсе.
  const hasRealDataset = Boolean(activeDataset);
  const overviewMetrics = hasRealDataset
    ? [
        ...(activeDataset!.frequency
          ? [{ label: "Частота", value: activeDataset!.frequency }]
          : []),
        ...(activeDataset!.nSeries
          ? [{ label: "Рядов", value: String(activeDataset!.nSeries) }]
          : []),
      ]
    : OVERVIEW_EXAMPLE_METRICS;

  return (
    <div className="flex gap-[49px] mt-8 px-6">
      {/* Боковые зазоры 24px (px-6, Task NAVDET-1) — паттерн главной
          страницы. Сжатие распределяется механикой flex: колонки
          w-60/w-80 shrink-0 сохраняют ширину, flex-1 «Описание»
          поглощает все 48px. */}
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
        {/* Заголовок и подзаголовок — ВНЕ окна скроллинга (Task NAVDET-2):
            статично на странице, как заголовки соседних колонок.
            Зазор h2→подзаголовок 12px (mb-3) — эквивалент прежнего
            коллапса mb-1 + space-y-3 внутри окна скролла.
            Тематическая иконка заголовка (Task NAVDET-3) — по паттерну
            секции 2 (AppliedTasksNavigator): обёртка flex items-center
            gap-2, lucide size={16} text-brand aria-hidden; отступ mb-3
            перенесён с h2 на обёртку — геометрия прежняя. */}
        <div className="flex items-center gap-2 mb-3">
          <ListChecks size={16} className="text-brand" aria-hidden="true" />
          <h2 className="text-base font-semibold text-neutral-800">
            Этапы модуля: {activeStop.label}
          </h2>
        </div>
        <p className="text-[11px] text-neutral-500 mb-3">
          {!activeStop.soon
            ? "Превью всех пунктов модуля."
            : "Модуль в разработке. Пункты — проектные, могут измениться."}
        </p>

        {/* Окно скроллинга: только карточки пунктов модуля (Task NAVDET-2)
            — заголовок/подзаголовок вынесены выше и при прокрутке
            остаются на месте. */}
        <div className="max-h-[820px] overflow-y-auto pr-1 space-y-3">
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
          {/* Тематическая иконка заголовка «Описание» (Task NAVDET-3) —
              BriefcaseBusiness, точно как в секции 2 (AppliedTasksNavigator);
              отступ mb-1 перенесён с h3 на обёртку — геометрия прежняя. */}
          <div className="flex items-center gap-2 mb-1">
            <BriefcaseBusiness size={16} className="text-brand" aria-hidden="true" />
            <h3 className="font-semibold text-neutral-900">Описание</h3>
          </div>
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
          {/* Тематическая иконка заголовка «Обзор» (Task NAVDET-3) — Eye,
              точно как в секции 2 (AppliedTasksNavigator); отступ mb-1
              перенесён с h3 на обёртку — геометрия прежняя. */}
          <div className="flex items-center gap-2 mb-1">
            <Eye size={16} className="text-brand" aria-hidden="true" />
            <h3 className="font-semibold text-neutral-900">
              Обзор: {activeItem.title}
            </h3>
          </div>
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

              Задача 2026-08-31 (Техническая информация): для пары
              «Загрузка» + «Техническая информация» (id="upload" +
              id="tech_info") рендерим статичную блок-схему построения
              технической информации по каждой колонке (4 ветки type_icon
              по dtype + 3 метрики non_null/nulls/unique) на основе
              РЕАЛЬНОЙ бэкенд-логики (_compute_column_info, ColumnInfoOut).
              Аналитик мгновенно понимает алгоритм благодаря инфографике.

              Задача 2026-09-01 (Превью 5+5 строк): для пары «Загрузка» +
              «Превью 5+5 строк» (id="upload" + id="preview_5_5")
              рендерим СТАТИЧНУЮ таблицу 5+5 строк синтетического датасета
              demo_finance_ohlcv.csv (первые 5 строк + separator + последние
              5). Превью закреплено как пример и сохраняется ВНЕ
              ЗАВИСИМОСТИ от того, удалён датасет или нет — данные берутся
              из детерминированного клиентского генератора (НЕ из сети).

              Задача 2026-09-02 (Визуализация распределения): для пары
              «Загрузка» + «Визуализация распределения» (id="upload" +
              id="distribution") рендерим СТАТИЧНЫЕ графики распределения
              (точечный/гистограмма/KDE) + 8 бейджей описательной статистики
              синтетического датасета demo_energy_consumption.csv (колонка
              consumption_mwh). Визуализация закреплена как пример и
              сохраняется ВНЕ ЗАВИСИМОСТИ от того, удалён датасет или нет.

              Task NAVDET-4 (Форматы и объём): для пары «Загрузка» +
              «Форматы и объём» (id="upload" + id="formats") рендерим
              СТАТИЧНУЮ блок-схему приёма файла (NavigatorFormatsVolume-
              Preview): форматы .csv/.xls/.xlsx/.json, проверки типа и
              размера (dropzone, лимит 4MB прод), формат по расширению,
              3 дорожки парсинга CSV/Excel/JSON, ошибки → HTTP 400,
              результат UploadResponse → SessionStore — на основе РЕАЛЬНОЙ
              логики (TsAnalysisUpload.tsx + app/data/file_loader.py +
              apps/api/upload_common.py). ВНЕ ЗАВИСИМОСТИ от датасета/сети.

              Task NAVDET-5 (Источник: файл или БД): для пары «Загрузка» +
              «Источник: файл или БД» (id="upload" + id="source") рендерим
              СТАТИЧНУЮ блок-схему источника данных (NavigatorSourceFileDb-
              Preview): переключатель «Файл / База данных (SQL)», файловая
              дорожка (drag-and-drop → POST /v1/internal/upload →
              read_uploaded_file → DataFrame, 4 демо-датасета), дорожка БД
              (PostgreSQL/ClickHouse, форма Host/Port/Database/User/Password,
              SQL-запрос с LIMIT, тест подключения SELECT 1/ping,
              pd.read_sql/query_df, таймауты 10с/60с), общий результат
              (датасет в сессии), ошибки обеих дорожек — на основе РЕАЛЬНОЙ
              логики (TsAnalysisUpload.tsx + init_db_connection в
              app/data/file_loader.py + app.py). Честный статус: форма БД
              на странице «Загрузка» — заглушка, бэкенд готов. ВНЕ
              ЗАВИСИМОСТИ от датасета/сети.

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
          ) : activeStopId === "upload" && activeItemId === "tech_info" ? (
            <NavigatorTechInfoPreview />
          ) : activeStopId === "upload" && activeItemId === "preview_5_5" ? (
            <NavigatorPreview55Preview />
          ) : activeStopId === "upload" && activeItemId === "distribution" ? (
            <NavigatorDistributionPreview />
          ) : activeStopId === "upload" && activeItemId === "formats" ? (
            <NavigatorFormatsVolumePreview />
          ) : activeStopId === "upload" && activeItemId === "source" ? (
            <NavigatorSourceFileDbPreview />
          ) : (
            <div
              className="bg-brand-light rounded-lg h-[280px] flex items-center justify-center text-sm text-neutral-500 border border-brand/10"
              role="img"
              aria-label={`Область визуализации для «${activeItem.title}»`}
            >
              [ область графика/таблицы/блок-схемы для «{activeItem.title}» ]
            </div>
          )}

          {/* Метрики: реальные (если есть датасет) или пример.
              Task NAVDET-5: при пустом массиве сетка не рендерится. */}
          {overviewMetrics.length > 0 && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4">
              {overviewMetrics.map((m) => (
                <Metric key={m.label} label={m.label} value={m.value} />
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
