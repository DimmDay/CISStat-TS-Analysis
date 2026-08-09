"use client";

// apps/standalone/components/ProductJourneyGuide.tsx
//
// "Путеводитель" для НЕавторизованного посетителя standalone (маркетинг,
// см. MarketingHome в StandaloneHome.tsx) -- ТОЧНАЯ калька дизайна с
// главной портала (components/JourneyGuide.tsx в репозитории
// CISStat_PORTAL, https://cis-stat-portal-k9tu.vercel.app/): слева
// вертикальный маршрут с "остановками" и пунктирной линией, справа сетка
// 2×4 = 8 карточек-функций активной остановки, цветокодировано,
// hover-переходы на бордере карточки и chevron идентичны оригиналу.
//
// ОТЛИЧИЕ ОТ ПОРТАЛА: остановки -- НЕ произвольные категории контента,
// а РЕАЛЬНЫЕ 6 ЭТАПОВ пайплайна (ключи 1:1 с packages/ui/lib/stages.ts /
// apps/api/session_store.py STAGES) -- путеводитель одновременно и
// продаёт, и быстро ориентирует в структуре продукта.
//
// Все 48 карточек (8 × 6 этапов) взяты из РЕАЛЬНОГО кода/спецификаций:
//   - Загрузка:     контракт в шапке TsAnalysisUpload.tsx
//   - Валидация:    CHECKS в TsAnalysisValidation.tsx (10 критериев, топ-8)
//   - Предобработка: CHECKS в TsAnalysisPreprocessing.tsx (топ-8 из 10)
//   - EDA:          CHECKS в TsAnalysisEDA.tsx (8 из 10, самые показательные)
//   - Моделирование: MODEL_FAMILIES в packages/ui/lib/modeling.ts (ровно 8)
//   - Прогнозирование: ARCHITECTURE.md §forecasting/monitoring/scenario
//     (модуль ещё ModulePlaceholder, но объём спроектирован и задокументирован)
// Не выдумано для красоты.

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
  Type,
  GitBranch,
  Percent,
  Sparkles,
  ShieldAlert,
  Combine,
  SplitSquareHorizontal,
  Network,
  ListChecks,
  Zap,
  Cpu,
  FlaskConical,
  GitCompare,
  TrendingDown,
  ShieldQuestion,
  LineChart,
  Gauge,
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
      { title: "Техническая информация", description: "dtype, non-null, уникальные значения по каждой колонке в отдельной таблице", icon: Database },
      { title: "Превью 5+5 строк", description: "Первые и последние строки датасета — проверка, что файл прочитан правильно", icon: ListChecks },
      { title: "Визуализация распределения", description: "Точечный график, гистограмма и KDE по выбранной числовой колонке", icon: BarChart3 },
      { title: "Форматы и объём", description: ".csv, .xlsx, .xls, .json — drag-and-drop, до 50MB", icon: FileDown },
      { title: "Источник: файл или БД", description: "Загрузка файла или подключение к SQL-базе данных", icon: Database },
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
      { title: "Типы данных", description: "Автопроверка соответствия типов колонок ожидаемым", icon: Type },
      { title: "Форматы и шаблоны", description: "Проверка текстовых полей на соответствие маскам и шаблонам", icon: FileText },
      { title: "Диапазоны значений", description: "Допустимые минимумы/максимумы по каждому числовому полю", icon: Scale },
      { title: "Логика и хронология", description: "Согласованность дат и бизнес-правил между колонками", icon: Clock },
      { title: "Уникальность", description: "Поиск дублирующихся строк и нарушений первичного ключа", icon: Fingerprint },
      { title: "Принадлежность к набору", description: "Проверка категориальных значений на допустимый список", icon: ListChecks },
      { title: "Ссылочная целостность", description: "Согласованность связей между сущностями датасета", icon: GitBranch },
      { title: "Целостность текста", description: "Кодировки, лишние пробелы, скрытые символы в текстовых полях", icon: AlertTriangle },
    ],
  },
  {
    id: "preprocessing",
    href: "/preprocessing",
    label: "ПРЕДОБРАБОТКА",
    subtitle: "10 операций подготовки ряда",
    icon: Wrench,
    colors: { bg: "#E0F4F1", dark: "#0b686b" },
    items: [
      { title: "Пропуски", description: "Методы заполнения пропущенных значений во временном ряде", icon: AlertTriangle },
      { title: "Выбросы", description: "Обнаружение и обработка аномальных значений", icon: ShieldAlert },
      { title: "Регулярность ряда", description: "Приведение временного индекса к равномерному шагу", icon: Clock },
      { title: "Декомпозиция ряда", description: "Разложение на тренд, сезонность и остаток", icon: Layers },
      { title: "Стабилизация дисперсии", description: "Преобразования (Box-Cox, логарифм) для однородной дисперсии", icon: Activity },
      { title: "Сглаживание ряда", description: "Устранение шума при сохранении структуры сигнала", icon: Waves },
      { title: "Стационарность ряда", description: "Дифференцирование и тесты ADF/KPSS перед моделированием", icon: TrendingDown },
      { title: "Спектральный анализ", description: "Предварительный поиск периодичности до глубокого EDA", icon: Zap },
    ],
  },
  {
    id: "eda",
    href: "/eda",
    label: "EDA",
    subtitle: "разведочный анализ ряда",
    icon: BarChart3,
    colors: { bg: "#ece5fc", dark: "#4b2e92" },
    items: [
      { title: "Описательные статистики", description: "Mean, std, skew, kurtosis, квантили — сравнение до/после предобработки", icon: BarChart3 },
      { title: "Корреляция (ACF/PACF)", description: "Автокорреляция с доверительными интервалами — вход для подбора ARIMA-порядков", icon: Activity },
      { title: "IH-анализ", description: "Shannon/Sample/Permutation entropy, mutual information, transfer entropy", icon: Brain },
      { title: "Сезонность и периодичность", description: "FFT/периодограмма, множественная сезонность, доминантные частоты", icon: Waves },
      { title: "Верификация стационарности", description: "Финальные ADF/KPSS/PP на преобразованном ряде с рекомендацией", icon: ShieldQuestion },
      { title: "Распределение", description: "Гистограмма, QQ-plot, тесты Jarque-Bera / Shapiro-Wilk / KS", icon: Combine },
      { title: "Структурные сдвиги", description: "Поиск точек regime change: CUSUM, Chow test, PELT", icon: SplitSquareHorizontal },
      { title: "Матрица моделей", description: "Таблица применимости: модель → требование → статус ряда → вывод", icon: Network },
    ],
  },
  {
    id: "modeling",
    href: "/modeling",
    label: "МОДЕЛИРОВАНИЕ",
    subtitle: "8 семейств моделей",
    icon: Brain,
    colors: { bg: "#FCE8F0", dark: "#6e173b" },
    items: [
      { title: "Базовые модели", description: "Naive, среднее, сезонный naive — точка отсчёта для сравнения", icon: FlaskConical },
      { title: "Эксп. сглаживание", description: "Simple/Holt/Holt-Winters — быстрые модели с малым числом параметров", icon: TrendingUp },
      { title: "ARIMA", description: "ARIMA/SARIMA с автоподбором порядков по стационарности ряда", icon: LineChart },
      { title: "Многомерные", description: "VAR и другие модели для нескольких связанных временных рядов", icon: GitCompare },
      { title: "Волатильность", description: "ARCH/GARCH-семейство для рядов с меняющейся дисперсией", icon: Waves },
      { title: "Структурные", description: "Модели с явным выделением тренда, сезонности и уровня", icon: Layers },
      { title: "Деревья и бустинг", description: "XGBoost/LightGBM на признаках, сгенерированных в EDA", icon: Network },
      { title: "Нейросетевые", description: "LSTM и другие модели для сложной нелинейной динамики", icon: Cpu },
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
      { title: "Прогноз на горизонт h", description: "Переобучение лучшей модели на Train ∪ Test перед прогнозом", icon: TrendingUp },
      { title: "Доверительные интервалы", description: "Границы неопределённости прогноза, не только точечная оценка", icon: Activity },
      { title: "Локальная интерпретируемость", description: "SHAP waterfall/force — почему модель дала именно такой прогноз", icon: Sparkles },
      { title: "Анализ дрифта", description: "Мониторинг смещения распределения данных и прогнозов во времени", icon: RefreshCw },
      { title: "Анализ смещения", description: "Систематическая ошибка (bias) прогноза относительно факта", icon: Percent },
      { title: "Сценарный анализ (What-if)", description: "Shock Propagation Engine: бизнес-гипотезы через причинные графы и IRF", icon: GitBranch },
      { title: "Мониторинг: прогноз vs факт", description: "Сравнение по мере поступления новых фактических данных", icon: Gauge },
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

        {/* ── Десктоп: вертикальный маршрут слева (1:1 с JourneyGuide портала) ── */}
        <div className="hidden md:block w-[210px] shrink-0 border-r border-neutral-200 py-5 pl-5 pr-3">
          <div className="mb-4 flex items-center gap-2">
            <MapPin size={14} className="text-brand" aria-hidden="true" />
            <h2 className="text-[13px] font-semibold text-neutral-800">Путеводитель</h2>
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

        {/* ── Правая часть: 2×4 = 8 карточек функций активного этапа ── */}
        <div className="flex-1 p-4 md:p-5 md:min-w-[580px]">
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
                  onMouseEnter={(e) => {
                    (e.currentTarget as HTMLElement).style.borderColor = dark;
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLElement).style.borderColor = `${dark}30`;
                  }}
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
