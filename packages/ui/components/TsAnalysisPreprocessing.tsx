"use client";

// packages/ui/components/TsAnalysisPreprocessing.tsx
//
// ОБЩИЙ компонент фичи "Предобработка" -- используется И embedded-,
// И standalone-приложением. Только внешняя "рамка" (шапка/навигация)
// вокруг него отличается между apps/embedded и apps/standalone;
// сама аналитическая UI-логика -- одна, чтобы не плодить дубли
// (см. историю разговора: 4 копии calculate_ts_passport -- урок учтён).
//
// Компоновка v2 (по макету «Компоновка2 вкладки_Предобработка»):
//   [Левая ~240px]     [Центр flex-1]         [Правая ~320px]
//   ▼ Признак: price   Метрики и алгоритм     Проверка: ...
//   3/10 ████░░         [текстовое поле]       [бейдж результата]
//   ┌─Пропуски──⚠─┐    Обзор: Пропуски        описание
//   ├─Выбросы───⚠─┤    [график]               ▼ Метрики
//   └─────────────┘    [Строк][Проп][Выбр]    ▼ Пайплайн
//                                                [Пересчитать]

import { useState } from "react";
import { Button } from "./Button";
import { Metric } from "./Metric";
import { StatusIcon, type CheckStatus } from "./StatusIcon";

// ── Типы ──────────────────────────────────────────────────────

interface Check {
  id: string;
  label: string;
  status: CheckStatus;
  count: number | null;
  description: string;
}

// ── Моковые данные (заменить на API) ─────────────────────────

const CHECKS: Check[] = [
  { id: "missing", label: "Пропуски", status: "warning", count: 11,
    description: "Пропуски нарушают DatetimeIndex, делают невозможной STL-декомпозицию, искажают ACF/PACF и ломают ARIMA/SARIMA." },
  { id: "outliers", label: "Выбросы", status: "warning", count: 1145,
    description: "Выбросы завышают дисперсию, искажают оценки тренда и ломают тесты стационарности (ADF/KPSS)." },
  { id: "duplicates", label: "Дубликаты", status: "done", count: 0,
    description: "Дублирующиеся временные метки ломают уникальность индекса." },
  { id: "regularity", label: "Регулярность шага", status: "pending", count: null,
    description: "Нерегулярный шаг мешает корректной декомпозиции и прогнозированию." },
  { id: "text_quality", label: "Качество текста", status: "pending", count: null,
    description: "Мусорные символы и пустые строки искажают категориальный анализ." },
  { id: "ranges", label: "Диапазоны значений", status: "done", count: 0,
    description: "Значения вне допустимого диапазона искажают статистику." },
  { id: "referential", label: "Ссылочная целостность", status: "pending", count: null,
    description: "Нарушение ссылочной целостности между справочниками." },
  { id: "formats", label: "Форматы", status: "warning", count: 3,
    description: "Несогласованные форматы дат/чисел ломают парсинг." },
  { id: "consistency", label: "Согласованность", status: "done", count: 0,
    description: "Нарушение хронологии внутри групп панельных данных." },
  { id: "ts_properties", label: "Свойства ряда", status: "pending", count: null,
    description: "Базовые свойства ряда для выбора модели прогнозирования." },
];

// Моковый список числовых признаков (заменить на activeDataset.columns)
const NUMERIC_FEATURES = [
  "price", "volume", "open", "high", "low", "close", "adj_close",
];

// ── Справка по целям модуля «Предобработка» (из app.py) ───────────

const PREPROCESSING_HELP = `Цели модуля "Предобработка"

Большинство классических моделей временных рядов и нейросетей предъявляют строгие требования к данным:
- отсутствие пропусков
- стационарность
- гомоскедастичность
- нормальность распределения и др.

Цель раздела. Применить математические преобразования, чтобы удовлетворить эти требования, сохранив при этом полезный сигнал (тренд, цикличность, сезонность). Предобработка решает задачу превращения данных в формат, пригодный для машинного обучения.

Что мы получим на выходе? Применив обратные преобразования после предобработки, мы имеем трансформированный датасет, готовый к загрузке в блок «Моделирование». Пользователь получает рекомендации по доступным моделям прогнозирования и сравнительные паспорта свойств ряда для анализа их изменения:
- v1.0 до валидации vs v1.3 после предобработки
- v1.2 до предобработки vs v1.3 после предобработки

Доступные преобразования:
- Заполнение пропусков (interpolation, forward-fill, mean)
- Удаление выбросов (IQR, Z-score, isolation forest)
- Логарифмирование (log, log1p) — для гетероскедастичности
- Дифференцирование (1-й, 2-й порядок) — для стационарности
- Box-Cox / Yeo-Johnson — для нормальности
- STL-декомпозиция — для удаления сезонности`;

// ── Компонент ─────────────────────────────────────────────────

export function TsAnalysisPreprocessing() {
  const [activeCheckId, setActiveCheckId] = useState(CHECKS[0].id);
  const [activeFeature, setActiveFeature] = useState(NUMERIC_FEATURES[0]);
  const [descriptionSection, setDescriptionSection] = useState<"metrics" | "pipeline" | "help" | null>(null);

  const doneCount = CHECKS.filter((c) => c.status === "done").length;
  const progressPct = Math.round((doneCount / CHECKS.length) * 100);
  const activeCheck = CHECKS.find((c) => c.id === activeCheckId)!;

  const orderedChecks = [...CHECKS].sort((a, b) =>
    a.id === activeCheckId ? -1 : b.id === activeCheckId ? 1 : 0
  );

  // Переключение секции описания в центральном текстовом поле
  const handleDescriptionClick = (check: Check, section: "metrics" | "pipeline") => {
    setActiveCheckId(check.id);
    setDescriptionSection(section);
  };

  // Показать/скрыть справку по целям модуля
  const handleHelpClick = () => {
    setDescriptionSection((prev) => prev === "help" ? null : "help");
  };

  // Текст описания для центрального поля — вычисляется из активной проверки и секции
  const descriptionContent = (() => {
    if (descriptionSection === "help") return PREPROCESSING_HELP;
    if (!descriptionSection) return null;
    if (descriptionSection === "metrics") {
      return `Метрики и алгоритм: ${activeCheck.label}\n\n${activeCheck.description}\n\nАлгоритм выявления: автоматический скрининг с порогом по умолчанию, ручная верификация аналитиком.`;
    }
    return `Полный пайплайн: ${activeCheck.label.toLowerCase()}\n\n1. Обнаружение → 2. Диагностика → 3. Преобразование → 4. Верификация\n\n${activeCheck.description}`;
  })();

  // Подзаголовок центрального поля
  const descriptionSubtitle = (() => {
    if (descriptionSection === "help") return "Справка — Цели модуля и результаты прохождения";
    if (!descriptionSection) return "Выберите раздел в боковой панели";
    if (descriptionSection === "metrics") return `Метрики и алгоритм — ${activeCheck.label}`;
    return `Полный пайплайн — ${activeCheck.label}`;
  })();

  return (
    <div className="flex gap-6">
      {/* ── ЛЕВАЯ КОЛОНКА: селектор признака + прогресс + степпер ── */}
      <aside className="w-60 shrink-0 flex flex-col gap-3 pt-1">
        {/* Заголовок модуля + справка */}
        <div className="mb-1">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-neutral-800">
              Preprocessing
            </h2>
            <button
              onClick={handleHelpClick}
              className={`text-xs px-2 py-1 rounded transition-colors ${
                descriptionSection === "help"
                  ? "bg-brand text-white"
                  : "bg-brand-light text-neutral-700 hover:bg-brand-light/80"
              }`}
            >
              Справка
            </button>
          </div>
          <p className="text-[11px] text-neutral-500 mt-0.5">
            Математические преобразования данных
          </p>
        </div>

        {/* Селектор числового признака */}
        <div>
          <label className="text-[11px] text-neutral-500 block mb-1">
            Исследуемый признак:
          </label>
          <select
            value={activeFeature}
            onChange={(e) => setActiveFeature(e.target.value)}
            className="w-full rounded border border-neutral-300 bg-white px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-brand"
          >
            {NUMERIC_FEATURES.map((f) => (
              <option key={f} value={f}>{f}</option>
            ))}
          </select>
        </div>

        {/* Прогресс */}
        <div className="flex items-center gap-2">
          <p className="text-[11px] text-neutral-500 tabular-nums">
            {doneCount}/{CHECKS.length}
          </p>
          <div className="flex-1 bg-neutral-200 rounded-full h-1.5">
            <div
              className="bg-brand h-1.5 rounded-full transition-all"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>

        {/* Степпер: прямоугольные карточки с текстом + иконка */}
        <div className="flex flex-col gap-1.5">
          {CHECKS.map((check) => (
            <button
              key={check.id}
              onClick={() => {
                setActiveCheckId(check.id);
                if (descriptionSection === "help") setDescriptionSection(null);
              }}
              className={`w-full flex items-center justify-between rounded-md border px-3 py-2 text-sm transition-colors ${
                check.id === activeCheckId
                  ? "bg-brand text-white border-brand"
                  : "bg-white border-neutral-200 hover:bg-neutral-50 text-neutral-800"
              }`}
            >
              <span className="truncate">{check.label}</span>
              <span className="ml-2 shrink-0">
                <StatusIcon status={check.status} />
              </span>
            </button>
          ))}
        </div>
      </aside>

      {/* ── ЦЕНТРАЛЬНАЯ КОЛОНКА: метрики-текст + график + метрики-карточки ── */}
      <section className="flex-1 min-w-0">
        {/* Блок «Описание» — текстовое поле над графиком */}
        <div className="mb-5">
          <h3 className="font-semibold mb-1">
            Описание
          </h3>
          <p className="text-xs text-neutral-500 mb-2">
            {descriptionSubtitle}
          </p>
          <div className="rounded-lg bg-brand-light/50 border border-neutral-200 px-4 py-3 min-h-[220px] max-h-[220px] overflow-y-auto text-sm text-neutral-600 whitespace-pre-wrap">
            {descriptionContent || (
              <span className="text-neutral-400 italic">
                Нажмите «Метрики и алгоритм», «Полный пайплайн» или «Справка»
              </span>
            )}
          </div>
        </div>

        {/* График */}
        <div>
          <h3 className="font-semibold mb-1">Обзор: {activeCheck.label}</h3>
          <p className="text-xs text-neutral-500 mb-3">
            Меняется автоматически под активную проверку.
          </p>

          <div className="bg-brand-light rounded-lg h-[420px] flex items-center justify-center text-sm text-neutral-500">
            [ график для «{activeCheck.label}» ]
          </div>

          <div className="grid grid-cols-4 gap-3 mt-4">
            <Metric label="Строк" value="200" />
            <Metric label="Пропусков" value="11" />
            <Metric label="Выбросов" value="3" />
            <Metric label="Частота" value="D" />
          </div>
        </div>
      </section>

      {/* ── ПРАВАЯ КОЛОНКА: список проверок (бывший центр) ── */}
      <aside className="w-80 shrink-0">
        <div className="max-h-[830px] overflow-y-auto pr-2 space-y-5 feed-scroll">
          {orderedChecks.map((check) => (
            <article
              key={check.id}
              className={`pb-5 border-b border-neutral-100 ${
                check.id === activeCheckId ? "border-l-4 border-l-brand pl-3" : ""
              }`}
            >
              <h3 className="font-semibold mb-1">
                <StatusIcon status={check.status} /> Проверка: {check.label}
              </h3>

              <p className="text-sm text-neutral-600 mb-2">{check.description}</p>

              {/* Бейдж результата — после описания */}
              {check.count !== null && check.count > 0 && (
                <p className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">
                  ⚠️ Найдено {check.count} нарушений
                </p>
              )}
              {check.status === "done" && (
                <p className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">
                  Проверка пройдена, нарушений нет
                </p>
              )}

              {/* Кнопка «Метрики и алгоритм» — активирует контент в центральном поле */}
              <button
                onClick={() => handleDescriptionClick(check, "metrics")}
                className={`w-full mb-2 rounded px-3 py-2 text-sm text-left font-medium transition-colors ${
                  check.id === activeCheckId && descriptionSection === "metrics"
                    ? "bg-brand text-white"
                    : "bg-brand-light hover:bg-brand-light/80 text-neutral-800"
                }`}
              >
                Метрики и алгоритм
              </button>

              {/* Кнопка «Полный пайплайн» — активирует контент в центральном поле */}
              <button
                onClick={() => handleDescriptionClick(check, "pipeline")}
                className={`w-full mb-3 rounded px-3 py-2 text-sm text-left font-medium transition-colors ${
                  check.id === activeCheckId && descriptionSection === "pipeline"
                    ? "bg-brand text-white"
                    : "bg-brand-light hover:bg-brand-light/80 text-neutral-800"
                }`}
              >
                Полный пайплайн
              </button>

              <Button>Пересчитать свойства после преобразования ({check.label.toLowerCase()})</Button>
            </article>
          ))}
        </div>
      </aside>
    </div>
  );
}
