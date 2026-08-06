"use client";

// packages/ui/components/TsAnalysisValidation.tsx
//
// ОБЩИЙ компонент фичи "Валидация" -- используется И embedded-,
// И standalone-приложением. По структуре повторяет 3-колоночный
// лейаут TsAnalysisPreprocessing, но с собственным набором проверок
// (10 критериев Data Quality) и заголовком модуля со справкой.
//
// Компоновка:
//   [Левая ~240px]     [Центр flex-1]         [Правая ~320px]
//   ▼ Признак: price   Описание               Проверка: ...
//   3/10 ████░░         [текстовое поле]       описание
//   ┌─Типы данных──⚠─┐  Обзор: Типы данных    [бейдж нарушения]
//   ├─Форматы────⚠─┤   [график]               [Метрики и алгоритм]
//   └────────────────┘  [Строк][Проп][Выбр]    [Полный пайплайн]
//                                                [Запустить проверку]
//
// Справка по стандартам DQ раскрывается в центральном текстовом окне
// при нажатии кнопки «Справка» в заголовке модуля.

import { useState, useRef, useEffect, useCallback } from "react";
import { Settings, ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "./Button";
import { Metric } from "./Metric";
import { StatusIcon, type CheckStatus } from "./StatusIcon";
import { RulesManagementPanel } from "./RulesManagementPanel";

// ── Типы ──────────────────────────────────────────────────────

interface Check {
  id: string;
  label: string;
  status: CheckStatus;
  count: number | null;
  description: string;
}

// ── 10 критериев Data Quality (маппинг на Streamlit app.py, шаги 1-10) ──

const CHECKS: Check[] = [
  { id: "data_types", label: "Типы данных", status: "warning", count: 4,
    description: "Несоответствие типов данных схеме (строка вместо числа, object вместо datetime) ломает парсинг и агрегации. Pandera-схема валидирует dtypes по каждому столбцу." },
  { id: "formats", label: "Форматы и шаблоны", status: "warning", count: 3,
    description: "Значения, не прошедшие regex-проверку (email, телефон, ИНН, дата), не могут быть использованы в автоматическом пайплайне. Проверка validate_formats выявляет все нарушения по шаблонам из rules.yaml." },
  { id: "ranges", label: "Диапазоны значений", status: "done", count: 0,
    description: "Выход за допустимые min/max (отрицательная цена, дата вне горизонта, процент > 100) искажает статистику и ломает модели. validate_ranges проверяет границы из rules.yaml." },
  { id: "consistency", label: "Логика и хронология", status: "warning", count: 7,
    description: "Нарушение бизнес-правил (close < open для цен, хронология дат, монотонность индекса) делает данные внутренне противоречивыми. validate_consistency проверяет логику и хронологию." },
  { id: "uniqueness", label: "Уникальность", status: "done", count: 0,
    description: "Дублирующиеся строки и временные метки ломают уникальность индекса и искажают агрегации. check_uniqueness выявляет полные и частичные дубликаты." },
  { id: "inclusion", label: "Принадлежность к набору", status: "pending", count: null,
    description: "Значения, не входящие в допустимый справочник (код региона, категория, единица измерения), не могут быть интерпретированы. check_inclusion проверяет membership по словарям из rules.yaml." },
  { id: "referential", label: "Ссылочная целостность", status: "pending", count: null,
    description: "Внешние ключи, ссылающиеся на несуществующие записи в связанных таблицах, ломают JOIN-операции. validate_referential проверяет все FK-связи." },
  { id: "text_quality", label: "Целостность текста", status: "warning", count: 12,
    description: "Мусорные символы, некорректная кодировка, пустые строки и дубликаты пробелов искажают категориальный анализ и полнотекстовый поиск. validate_text_quality выявляет все нарушения." },
  { id: "regularity", label: "Равномерность шага", status: "pending", count: null,
    description: "Нерегулярный временной шаг (пропуски дат, дублирование, сбой частоты) мешает STL-декомпозиции, ACF/PACF и моделям ARIMA/SARIMA. validate_regular_step проверяет частоту и gaps." },
  { id: "sufficiency", label: "Достаточность наблюдений", status: "pending", count: null,
    description: "Недостаточное число наблюдений для идентификации параметров модели (минимум 2×сезонный_период для SARIMA, 30+ для ADF). validate_sufficiency оценивает длину ряда и выдаёт рекомендации." },
];

// Моковый список числовых признаков (заменить на activeDataset.columns)
const NUMERIC_FEATURES = [
  "price", "volume", "open", "high", "low", "close", "adj_close",
];

// ── Справка по стандартам качества данных ────────────────────

const DQ_STANDARDS_HELP = `Стандарты качества данных (Data Quality)

Модуль «Валидация» реализует комплексную проверку данных по 10 критериям, основанным на международной классификации DAMA DMBOK (Data Management Body of Knowledge) и дополненным спецификой временных рядов.

Классификация проверок по категориям DAMA:

1. Полнота (Completeness)
   - Пропуски (NaN, null, пустые строки) — критичны для временных рядов, ломают DatetimeIndex и STL-декомпозицию.

2. Достоверность (Accuracy)
   - Диапазоны значений — выход за допустимые min/max.
   - Типы данных — несоответствие dtype схеме (строка вместо числа).

3. Согласованность (Consistency)
   - Логика и хронология — бизнес-правила (close >= open) и монотонность индекса.
   - Ссылочная целостность — FK-связи между таблицами.
   - Равномерность шага — частота и gaps временного ряда.

4. Уникальность (Uniqueness)
   - Дубликаты строк и временных меток.

5. Валидность (Validity)
   - Форматы и шаблоны — regex-проверка (email, ИНН, дата).
   - Принадлежность к набору — membership в справочниках.

6. Целостность текста (Integrity)
   - Мусорные символы, кодировка, нормализация пробелов.

7. Достаточность (Sufficiency)
   - Минимальное число наблюдений для идентификации модели (2×сезонный_период для SARIMA, 30+ для ADF).

Интегральный показатель Data Quality Score (DQ) вычисляется как взвешенное среднее по всем 10 критериям. Порог DQ >= 0.8 считается достаточным для передачи данных в модуль «Предобработка».

Ссылки:
- DAMA DMBOK, 2nd Edition, Chapter 13: Data Quality
- ISO 8000 — Data Quality Standard
- Практика Data Quality в финансовой аналитике (CBR, MOEX)`;

// ── Компонент ─────────────────────────────────────────────────

export function TsAnalysisValidation() {
  const [activeCheckId, setActiveCheckId] = useState(CHECKS[0].id);
  const [activeFeature, setActiveFeature] = useState(NUMERIC_FEATURES[0]);
  const [descriptionSection, setDescriptionSection] = useState<"metrics" | "pipeline" | "help" | "rules" | null>(null);
  const [descriptionExpanded, setDescriptionExpanded] = useState(false);
  const [hasOverflow, setHasOverflow] = useState(false);
  const descRef = useRef<HTMLDivElement>(null);

  // Сворачиваем при смене секции
  useEffect(() => {
    setDescriptionExpanded(false);
  }, [descriptionSection]);

  // Click-outside: сворачиваем при клике вне description box
  const handleOutsideClick = useCallback((e: MouseEvent) => {
    if (descRef.current && !descRef.current.contains(e.target as Node)) {
      setDescriptionExpanded(false);
    }
  }, []);
  useEffect(() => {
    if (descriptionExpanded) {
      document.addEventListener("mousedown", handleOutsideClick);
      return () => document.removeEventListener("mousedown", handleOutsideClick);
    }
  }, [descriptionExpanded, handleOutsideClick]);

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

  // Показать справку по стандартам DQ
  const handleHelpClick = () => {
    setDescriptionSection((prev) => prev === "help" ? null : "help");
  };

  // Показать/скрыть «Управление правилами»
  const handleRulesClick = () => {
    setDescriptionSection((prev) => prev === "rules" ? null : "rules");
  };

  // ── Overflow detection для expandable description ──
  useEffect(() => {
    const el = descRef.current;
    if (!el) return;
    const checkOverflow = () => {
      setHasOverflow(el.scrollHeight > el.clientHeight + 2);
    };
    checkOverflow();
    const observer = new ResizeObserver(checkOverflow);
    observer.observe(el);
    return () => observer.disconnect();
  }, [descriptionSection]); // ResizeObserver отслеживает контент

  // Текст описания для центрального поля
  const descriptionContent = (() => {
    if (descriptionSection === "help") return DQ_STANDARDS_HELP;
    if (descriptionSection === "rules") return null; // RulesManagementPanel рендерится отдельно
    if (!descriptionSection) return null;
    if (descriptionSection === "metrics") {
      return `Метрики и алгоритм: ${activeCheck.label}\n\n${activeCheck.description}\n\nАлгоритм выявления: автоматический скрининг с порогом по умолчанию, ручная верификация аналитиком.`;
    }
    return `Полный пайплайн: ${activeCheck.label.toLowerCase()}\n\n1. Обнаружение → 2. Диагностика → 3. Преобразование → 4. Верификация\n\n${activeCheck.description}`;
  })();

  // Подзаголовок центрального поля
  const descriptionSubtitle = (() => {
    if (descriptionSection === "help") return "Справка по стандартам качества данных";
    if (descriptionSection === "rules") return "Управление правилами валидации";
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
              Data Quality
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
            Контроль качества данных
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
                if (descriptionSection === "help" || descriptionSection === "rules") setDescriptionSection(null);
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

        {/* ── Кнопка «Управление правилами» — внизу степпера ── */}
        {/* Визуально отличается от степпер-бейджей: dashed border, */}
        {/* brand-colored text, Settings icon — не заливка, а outline-стиль */}
        <div className="mt-3 pt-3 border-t border-neutral-200">
          <button
            onClick={handleRulesClick}
            data-testid="rules-management-btn"
            className={`w-full flex items-center justify-center gap-2 rounded-md border-2 border-dashed px-3 py-2.5 text-sm font-medium transition-colors ${
              descriptionSection === "rules"
                ? "border-brand bg-brand/10 text-brand"
                : "border-brand/40 text-brand hover:border-brand hover:bg-brand/5"
            }`}
          >
            <Settings size={16} />
            Управление правилами
          </button>
        </div>
      </aside>

      {/* ── ЦЕНТРАЛЬНАЯ КОЛОНКА: описание + график + метрики ── */}
      <section className="flex-1 min-w-0">
        {/* Блок «Описание» — текстовое поле над графиком */}
        <div className="mb-5">
          <h3 className="font-semibold mb-1">
            Описание
          </h3>
          <p className="text-xs text-neutral-500 mb-2">
            {descriptionSubtitle}
          </p>
          {/* ── Expandable Description Box ──
              collapsed: min-h=220px, max-h=220px, scroll (in-flow)
              expanded: position:absolute overlay over graph, max-h=calc(100vh-180px)
              chevron: shown only when hasOverflow
          */}
          <div className="relative min-h-[220px]">
            <div
              ref={descRef}
              className={`rounded-lg bg-brand-light border border-neutral-200 px-4 py-3 overflow-y-auto text-sm text-neutral-600 whitespace-pre-wrap ${
                descriptionExpanded
                  ? "absolute top-0 left-0 right-0 z-20 max-h-[calc(100vh-180px)] shadow-lg border-brand/30 min-h-[220px]"
                  : "max-h-[220px] min-h-[220px]"
              }`}
            >
              {descriptionSection === "rules" ? (
                <RulesManagementPanel />
              ) : descriptionContent ? (
                descriptionContent
              ) : (
                <span className="text-neutral-400 italic">
                  Нажмите «Метрики и алгоритм», «Полный пайплайн», «Справка» или «Управление правилами»
                </span>
              )}
            </div>
            {/* Chevron toggle — только при overflow */}
            {hasOverflow && !descriptionExpanded && (
              <button
                onClick={() => setDescriptionExpanded(true)}
                className="absolute bottom-1 left-1/2 -translate-x-1/2 flex items-center justify-center w-8 h-5 rounded-t bg-brand/10 hover:bg-brand/20 text-brand transition-colors"
                aria-label="Развернуть описание"
                data-testid="desc-expand-btn"
              >
                <ChevronDown size={14} />
              </button>
            )}
            {descriptionExpanded && (
              <button
                onClick={() => setDescriptionExpanded(false)}
                className="absolute bottom-1 left-1/2 -translate-x-1/2 flex items-center justify-center w-8 h-5 rounded-t bg-brand/10 hover:bg-brand/20 text-brand transition-colors"
                aria-label="Свернуть описание"
                data-testid="desc-collapse-btn"
              >
                <ChevronUp size={14} />
              </button>
            )}
          </div>
        </div>

        {/* График */}
        <div>
          <h3 className="font-semibold mb-1">Обзор: {activeCheck.label}</h3>
          <p className="text-xs text-neutral-500 mb-3">
            Визуализация результатов проверки по активному критерию.
          </p>

          <div className="bg-brand-light rounded-lg h-[420px] flex items-center justify-center text-sm text-neutral-500">
            [ график для «{activeCheck.label}» ]
          </div>

          <div className="grid grid-cols-4 gap-3 mt-4">
            <Metric label="Строк" value="200" />
            <Metric label="Нарушений" value="26" />
            <Metric label="DQ Score" value="0.74" />
            <Metric label="Частота" value="D" />
          </div>
        </div>
      </section>

      {/* ── ПРАВАЯ КОЛОНКА: список проверок ── */}
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

              <Button>Запустить проверку ({check.label.toLowerCase()})</Button>
            </article>
          ))}
        </div>
      </aside>
    </div>
  );
}
