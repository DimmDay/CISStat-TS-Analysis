"use client";

// apps/standalone/components/ProductJourneyGuide.tsx
//
// "Путеводитель" для НЕавторизованного посетителя standalone (маркетинг,
// см. MarketingHome в StandaloneHome.tsx) -- по образцу JourneyGuide на
// главной портала (https://cis-stat-portal-k9tu.vercel.app/,
// components/JourneyGuide.tsx в репозитории CISStat_PORTAL): слева
// вертикальный маршрут с "остановками", справа сетка карточек-функций
// активной остановки, цветокодировано.
//
// ОТЛИЧИЕ ОТ ПОРТАЛА: остановки здесь -- НЕ произвольные категории
// контента, а РЕАЛЬНЫЕ 6 ЭТАПОВ пайплайна (ключи 1:1 с
// packages/ui/lib/stages.ts / apps/api/session_store.py STAGES) --
// путеводитель одновременно и продаёт, и быстро ориентирует в структуре
// продукта: посетитель за один взгляд видит весь путь от загрузки файла
// до прогноза и что происходит на каждом шаге.
//
// Фичи внутри остановок взяты из РЕАЛЬНОГО кода модулей (label-массивы
// в TsAnalysisValidation.tsx/TsAnalysisPreprocessing.tsx/TsAnalysisEDA.tsx,
// контракт в шапке TsAnalysisUpload.tsx, docs/ARCHITECTURE.md для
// Modeling/Forecasting) -- не выдуманы для красоты.
//
// Клик по карточке ведёт на страницу модуля -- ровно то же поведение,
// что у существующей кнопки "Открыть в браузере" (роуты пока не защищены
// авторизацией на уровне страницы, см. TODO в lib/useAuth.ts).

import { useState } from "react";
import Link from "next/link";
import {
  Upload,
  ShieldCheck,
  Wrench,
  BarChart3,
  Brain,
  TrendingUp,
  FileText,
  Calendar,
  Database,
  Scale,
  Fingerprint,
  Clock,
  AlertTriangle,
  Layers,
  Activity,
  Waves,
  FileDown,
  RefreshCw,
  Code,
  MapPin,
  ChevronRight,
  type LucideIcon,
} from "lucide-react";

interface GuideItem {
  title: string;
  description: string;
  icon: LucideIcon;
}

interface StopColors {
  bg: string;
  dark: string;
}

interface GuideStop {
  id: string;
  href: string;
  label: string;
  subtitle: string;
  icon: LucideIcon;
  colors: StopColors;
  items: GuideItem[];
}

const STOPS: GuideStop[] = [
  {
    id: "upload",
    href: "/data/upload",
    label: "ЗАГРУЗКА",
    subtitle: "файл → структура за секунды",
    icon: Upload,
    colors: { bg: "#dbeeff", dark: "#1a5490" },
    items: [
      { title: "Автопревью и типы колонок", description: "Первые/последние строки, dtype, пропуски, уникальные значения — сразу после загрузки", icon: FileText },
      { title: "Подтверждение автоопределения", description: "Дата, группирующая колонка, частота ряда — определяются автоматически, можно поправить", icon: Calendar },
      { title: "Teaser качества", description: "Пропуски, дубликаты, потенциальные выбросы — счётчиками, до перехода к Валидации", icon: ShieldCheck },
      { title: "Форматы и объём", description: ".csv, .xlsx, .xls, .json — drag-and-drop, до 50MB", icon: Database },
    ],
  },
  {
    id: "validation",
    href: "/validation",
    label: "ВАЛИДАЦИЯ",
    subtitle: "10 критериев Data Quality",
    icon: ShieldCheck,
    colors: { bg: "#fdeddb", dark: "#7a4b0a" },
    items: [
      { title: "Типы данных и форматы", description: "Автопроверка соответствия типов и текстовых шаблонов по колонкам", icon: Scale },
      { title: "Диапазоны и хронология", description: "Допустимые значения и логическая согласованность дат", icon: Clock },
      { title: "Уникальность и целостность", description: "Дубликаты, принадлежность к набору, ссылочная целостность", icon: Fingerprint },
      { title: "Равномерность и достаточность", description: "Регулярность шага ряда и минимально необходимое число наблюдений", icon: AlertTriangle },
    ],
  },
  {
    id: "preprocessing",
    href: "/preprocessing",
    label: "ПРЕДОБРАБОТКА",
    subtitle: "11 операций подготовки ряда",
    icon: Wrench,
    colors: { bg: "#E0F4F1", dark: "#0b686b" },
    items: [
      { title: "Пропуски и выбросы", description: "Методы заполнения пропусков и обработки аномальных значений", icon: AlertTriangle },
      { title: "Декомпозиция ряда", description: "Разложение на тренд, сезонность и остаток", icon: Layers },
      { title: "Стабилизация и сглаживание", description: "Стабилизация дисперсии, сглаживание, приведение к стационарности", icon: Activity },
      { title: "Признаки и масштабирование", description: "Генерация признаков, масштабирование перед моделированием", icon: Wrench },
    ],
  },
  {
    id: "eda",
    href: "/eda",
    label: "EDA",
    subtitle: "11 методов разведочного анализа",
    icon: BarChart3,
    colors: { bg: "#ece5fc", dark: "#4b2e92" },
    items: [
      { title: "Описательные статистики", description: "Распределение, форма, асимметрия и эксцесс", icon: BarChart3 },
      { title: "Корреляция, ACF/PACF", description: "Автокорреляция и частная автокорреляция для подбора модели", icon: Activity },
      { title: "Спектральный анализ", description: "FFT, периодограмма, вейвлет — поиск скрытой периодичности", icon: Waves },
      { title: "Сезонность и структурные сдвиги", description: "Верификация стационарности, поиск точек излома ряда", icon: Layers },
    ],
  },
  {
    id: "modeling",
    href: "/modeling",
    label: "МОДЕЛИРОВАНИЕ",
    subtitle: "паспорт из 13 метрик",
    icon: Brain,
    colors: { bg: "#FCE8F0", dark: "#6e173b" },
    items: [
      { title: "Полный паспорт ряда", description: "ADF/KPSS, Hurst, сезонность, спектр — 13 метрик одним вызовом API", icon: FileText },
      { title: "Каталог моделей", description: "Кросс-валидация и сравнение кандидатов по метрикам качества", icon: Layers },
      { title: "KS-тест распределений", description: "Фиттинг и сравнение трёх кандидатных распределений", icon: Scale },
      { title: "Excel-отчёт", description: "Итоги паспорта и рекомендации — выгрузка одним файлом", icon: FileDown },
    ],
  },
  {
    id: "forecasting",
    href: "/forecasting",
    label: "ПРОГНОЗ",
    subtitle: "горизонт + доверительные интервалы",
    icon: TrendingUp,
    colors: { bg: "#e6f5ea", dark: "#1e531f" },
    items: [
      { title: "Прогноз на горизонт h", description: "Применение лучшей модели из Моделирования к будущим точкам", icon: TrendingUp },
      { title: "Переобучение на всех данных", description: "Дообучение на Train ∪ Test для максимизации истории перед прогнозом", icon: RefreshCw },
      { title: "Доверительные интервалы", description: "Границы неопределённости прогноза, не только точечная оценка", icon: Activity },
      { title: "API для интеграции", description: "Тот же прогноз — программно, в вашу ИТ-систему", icon: Code },
    ],
  },
];

export function ProductJourneyGuide() {
  const [activeId, setActiveId] = useState(STOPS[0].id);
  const active = STOPS.find((s) => s.id === activeId)!;
  const { bg, dark } = active.colors;

  return (
    <div className="bg-white rounded-lg border border-neutral-200 overflow-hidden">
      <div className="flex flex-col md:flex-row">
        {/* ── Мобильная версия: горизонтальная лента остановок ── */}
        <div className="flex md:hidden gap-2 overflow-x-auto p-4 border-b border-neutral-200">
          {STOPS.map((stop) => {
            const Icon = stop.icon;
            const isActive = stop.id === activeId;
            return (
              <button
                key={stop.id}
                type="button"
                onClick={() => setActiveId(stop.id)}
                style={isActive ? { backgroundColor: stop.colors.dark, color: "#fff" } : undefined}
                className={`shrink-0 inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium border transition-colors ${
                  isActive ? "border-transparent" : "border-neutral-200 text-neutral-600"
                }`}
              >
                <Icon size={13} aria-hidden="true" />
                {stop.label}
              </button>
            );
          })}
        </div>

        {/* ── Десктоп: вертикальный маршрут слева ── */}
        <div className="hidden md:block w-[220px] shrink-0 border-r border-neutral-200 py-5 pl-5 pr-3">
          <div className="mb-4 flex items-center gap-2">
            <MapPin size={14} className="text-brand" aria-hidden="true" />
            <h2 className="text-[13px] font-semibold text-neutral-800">Путеводитель по анализу</h2>
          </div>

          <div className="relative">
            <div className="absolute left-[5px] top-2 bottom-2 w-0 border-l-2 border-dashed border-neutral-200" />
            <div className="flex flex-col gap-0.5">
              {STOPS.map((stop) => {
                const Icon = stop.icon;
                const isActive = stop.id === activeId;
                const c = stop.colors;
                return (
                  <button
                    key={stop.id}
                    type="button"
                    onClick={() => setActiveId(stop.id)}
                    onMouseEnter={() => setActiveId(stop.id)}
                    style={isActive ? { backgroundColor: `${c.bg}99` } : undefined}
                    className={`relative flex items-center gap-2.5 rounded-lg px-1.5 py-2 w-full text-left transition-colors ${
                      !isActive ? "hover:bg-neutral-50" : ""
                    }`}
                  >
                    <div
                      className="relative z-10 h-3 w-3 shrink-0 rounded-full border-2 transition-colors"
                      style={isActive ? { borderColor: c.dark, backgroundColor: c.dark } : { borderColor: "#D4D4D4", backgroundColor: "#fff" }}
                    />
                    <div
                      className="flex h-6 w-6 shrink-0 items-center justify-center rounded transition-colors"
                      style={isActive ? { backgroundColor: c.dark, color: "#fff" } : { backgroundColor: "#F5F5F5", color: "#A3A3A3" }}
                    >
                      <Icon size={14} aria-hidden="true" />
                    </div>
                    <div className="min-w-0">
                      <div className="text-[12px] font-semibold leading-none transition-colors" style={{ color: isActive ? c.dark : "#404040" }}>
                        {stop.label}
                      </div>
                      <div className="text-[10px] text-neutral-400 mt-0.5 leading-tight">{stop.subtitle}</div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {/* ── Правая часть: карточки функций активного этапа ── */}
        <div className="flex-1 p-4 md:p-5">
          <div className="flex items-center justify-between mb-3 md:hidden">
            <p className="text-xs text-neutral-500">{active.subtitle}</p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {active.items.map((item, idx) => {
              const ItemIcon = item.icon;
              return (
                <Link
                  key={`${activeId}-${idx}`}
                  href={active.href}
                  className="group flex flex-col overflow-hidden rounded-xl border transition-colors"
                  style={{ borderColor: `${dark}30` }}
                >
                  <div className="flex items-center gap-3 px-3.5 py-2.5 text-left" style={{ backgroundColor: bg }}>
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-white" style={{ color: dark }}>
                      <ItemIcon size={15} aria-hidden="true" />
                    </div>
                    <span className="min-w-0 flex-1 text-[13px] font-semibold leading-snug" style={{ color: dark }}>
                      {item.title}
                    </span>
                    <ChevronRight size={14} className="shrink-0 opacity-40 group-hover:opacity-100 transition-opacity" style={{ color: dark }} aria-hidden="true" />
                  </div>
                  <div className="px-3.5 py-2 bg-white">
                    <p className="text-[11px] text-neutral-500 leading-relaxed">{item.description}</p>
                  </div>
                </Link>
              );
            })}
          </div>
          <Link
            href={active.href}
            className="mt-4 inline-flex items-center gap-1.5 text-sm font-medium hover:underline"
            style={{ color: dark }}
          >
            Открыть «{active.label.charAt(0) + active.label.slice(1).toLowerCase()}» <ChevronRight size={14} aria-hidden="true" />
          </Link>
        </div>
      </div>
    </div>
  );
}
