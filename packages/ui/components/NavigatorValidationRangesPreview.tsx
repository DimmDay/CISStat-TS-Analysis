"use client";

// packages/ui/components/NavigatorValidationRangesPreview.tsx
//
// Статичная информационная блок-схема для окна «Обзор» пункта «Диапазоны
// значений» (id="ranges", третий пункт) секции «Этапы модуля» остановки
// «Валидация» на странице Навигатор (Task NAVDET-RANGES, 2026-09-22).
// Родственник NavigatorValidationFormatsPreview.
//
// ── Контракт ────────────────────────────────────────────────────────
//   • Визуализация — СТАТИЧНАЯ информационная блок-схема алгоритма
//     проверки «Диапазоны значений» (третий из 10 критериев Data
//     Quality): эталон min/max-правил → системный вывод границ по
//     семантике имени числовой колонки → маска нарушений (ниже min /
//     выше max, пропуски отдельно) → полный профиль применимых правил →
//     прогон/сбор нарушений → статусы чека → исправление через
//     «Мастер исправления диапазонов».
//   • Схема основана на РЕАЛЬНОЙ логике:
//       - validation/rule_resolver.py::resolve_validation_rules
//         (_deep_merge(_deep_merge(system_rules, template_rules),
//         overrides) — приоритет: сессия > шаблон YAML
//         (rules/<template>.yaml, по умолчанию default_rules.yaml) >
//         системный вывод; CHECK_SECTIONS["ranges"] = "ranges";
//         системный слой не строит произвольные min/max из наблюдаемого
//         диапазона)
//       - validation/engine.py::auto_generate_rules (системный слой для
//         ranges): только числовые колонки; правило по семантике ИМЕНИ —
//         price/цена/стоимость → положительная цена (min 0), year/год →
//         разумный год (1900–2100), percent/%/доля → процент (0–100);
//         неизвестной числовой семантике диапазон НЕ назначается из
//         фактических min/max — это гарантировало бы ложное прохождение
//       - rules/default_rules.yaml::ranges — шаблонные правила вида
//         keywords + min/max: price/cost ≥ 0, pct/percent 0–100,
//         rate/доля/share 0–1, volume/quantity/count ≥ 0, moisture
//         0–100, sugar 0–30, age ≥ 0
//       - validation/engine.py::range_invalid_mask
//         (series.notna() & (series < min) — ниже минимума;
//         series.notna() & (series > max) — выше максимума; min и max
//         независимы — правило может задавать только одну границу;
//         пропуски проверяются отдельно и не считаются нарушениями
//         диапазона)
//       - validation/engine.py::profile_ranges (только числовые колонки;
//         правило подбирается по keywords в имени колонки; правило без
//         min и max пропускается; total/valid/invalid_count, invalid_pct;
//         actual_min/actual_max — факт против min_allowed/max_allowed;
//         invalid_examples — до 5 уникальных; ПОЛНЫЙ профиль применимых
//         правил — включая колонки с 0 нарушений)
//       - validation/engine.py::validate_ranges (строка результата
//         ТОЛЬКО для колонок с нарушениями: Правило «min ≤ x ≤ max» с
//         −∞/∞ для отсутствующей границы, Нарушений, % брака, Min факт,
//         Max факт; rule_bounds заполняется для КАЖДОЙ matched колонки —
//         надёжный сигнал применимости)
//       - validation/engine.py::_run_all_checks::_ranges (scope="column"
//         — при выбранном признаке: признак не в bounds → pending
//         (честный сигнал «правила нет», а не «нарушений нет»), matched
//         → статус по нарушениям признака; без признака: bounds пуст →
//         pending, items из raw, count = Σ; отличие от «Типов данных»,
//         где scope="dataset")
//       - apps/api/routers/session.py::get_dataset_range_profile
//         (GET /v1/session/dataset/range-profile — полный профиль
//         применимых min/max-правил + rule_source) и
//         correct_dataset_ranges (POST /v1/session/dataset/
//         range-corrections — preview/apply; маска и границы всегда из
//         resolved rules сервера, а не из клиента; preview на глубокой
//         копии, apply сохраняет подготовленную копию атомарно)
//       - apps/api/range_correction.py::preview_range_corrections
//         (5 стратегий: clip — кэпирование до границ; median — медиана
//         только корректных значений, уже находящихся в диапазоне;
//         replace_null — нарушения → NA; drop_rows — удаление строк по
//         ОБЪЕДИНЁННОЙ маске всех выбранных колонок; flag — булева
//         колонка <имя>_range_valid без изменения значений; для колонки
//         без активного правила диапазона — ошибка исправления)
//   • Отображается ПРИ ЛЮБЫХ УСЛОВИЯХ — НЕ зависит от useAppShell,
//     activeDataset, fetch, сети, сессии (паттерн других остановок:
//     NavigatorTechInfoPreview, NavigatorPassportPreview,
//     NavigatorValidationFormatsPreview и родня).
//
// ── a11y ────────────────────────────────────────────────────────────
//   • Корень: role="img" + aria-label со всей цепочкой — скринридер
//     читает блок-схему как одно изображение.
//   • Стрелки/иконки — aria-hidden="true" (дублируют текст, единый
//     паттерн с другими Navigator*Preview).

import {
  ChevronDown,
  ClipboardList,
  FileCog,
  FileText,
  ListChecks,
  Ruler,
  ShieldCheck,
  Wrench,
  type LucideIcon,
} from "lucide-react";

// ── 3 источника эталона (validation/rule_resolver.py) ────────────────

interface RuleSource {
  /** Номер приоритета (1 — высший). */
  priority: number;
  /** Источник. */
  id: "session" | "template" | "system";
  label: string;
  /** Что кладёт в эталон. */
  detail: string;
  /** Реальный код/файл источника. */
  source: string;
}

const RULE_SOURCES: RuleSource[] = [
  {
    priority: 1,
    id: "session",
    label: "Сессия",
    detail:
      "overrides сессии — исправления из «Мастера исправления диапазонов» (ranges-секция правил)",
    source: "session overrides",
  },
  {
    priority: 2,
    id: "template",
    label: "Шаблон",
    detail:
      "YAML-шаблон правил: rules/<template>.yaml — колонка → keywords + min/max (по умолчанию default_rules.yaml)",
    source: "default_rules.yaml",
  },
  {
    priority: 3,
    id: "system",
    label: "Система",
    detail:
      "авто-вывод min/max по семантике имени числовых колонок",
    source: "auto_generate_rules",
  },
];

// ── Системный вывод границ (validation/engine.py::auto_generate_rules) ──

interface RangeLane {
  /** Семантика имени (стабильна — на ней строятся тесты). */
  id: string;
  /** Токены имени колонки. */
  tokens: string;
  /** Правило. */
  rule: string;
  /** Границы дефолтного правила. */
  bounds: string;
  icon: LucideIcon;
}

const RANGE_LANES: RangeLane[] = [
  {
    id: "price",
    tokens: "price / цена / стоимость",
    rule: "Положительная цена",
    bounds: "min 0 · max ∞",
    icon: Ruler,
  },
  {
    id: "year",
    tokens: "year / год",
    rule: "Разумный год",
    bounds: "1900–2100",
    icon: Ruler,
  },
  {
    id: "percent",
    tokens: "percent / % / доля",
    rule: "Процент",
    bounds: "0–100",
    icon: Ruler,
  },
];

// ── Шаблонные правила (rules/default_rules.yaml::ranges) ─────────────

const TEMPLATE_LANES: Array<{ keywords: string; bounds: string }> = [
  { keywords: "rate / доля / share", bounds: "0–1" },
  { keywords: "volume / quantity / count", bounds: "≥ 0" },
  { keywords: "moisture / влажность", bounds: "0–100" },
  { keywords: "sugar / сахар", bounds: "0–30" },
  { keywords: "age / возраст", bounds: "≥ 0" },
];

// ── Механика маски нарушений (validation/engine.py::range_invalid_mask) ──

const MASK_STEPS: Array<{ code: string; meaning: string }> = [
  { code: "series < min_value", meaning: "значения ниже минимума — нарушения (если min задан)" },
  { code: "series > max_value", meaning: "значения выше максимума — нарушения (если max задан)" },
  { code: "min и max независимы", meaning: "правило может задавать только одну границу" },
  { code: "series.notna()", meaning: "пропуски проверяются отдельно — не считаются нарушениями диапазона" },
];

// ── Стратегии исправления (apps/api/range_correction.py) ─────────────

const STRATEGIES: Array<{ id: string; detail: string }> = [
  { id: "clip", detail: "кэпирование до границ: значения ниже min заменяются на min, выше max — на max" },
  { id: "median", detail: "медиана корректных значений — только по значениям, уже находящимся в допустимом диапазоне" },
  { id: "replace_null", detail: "нарушающие значения → NA (обрабатываются отдельным этапом качества)" },
  { id: "drop_rows", detail: "удаление строк по объединённой маске нарушений всех выбранных колонок" },
  { id: "flag", detail: "булева колонка <имя>_range_valid — без изменения значений" },
];

// ── Статусы чека (_run_all_checks::_ranges) ──────────────────────────

const STATUS_ITEMS: Array<{ status: string; meaning: string }> = [
  { status: "done", meaning: "0 нарушений — все значения matched колонок внутри допустимых границ" },
  { status: "warning", meaning: ">0 нарушений — есть значения ниже min или выше max" },
  { status: "pending", meaning: "нет правила для колонки (или проверка не применима)" },
];

// ── Компонент ──────────────────────────────────────────────────────

export function NavigatorValidationRangesPreview() {
  // Описание для скринридера — вся цепочка одной строкой.
  const ariaLabel =
    "Блок-схема проверки «Диапазоны значений» остановки «Валидация». " +
    "Эталон min/max-правил — три источника по приоритету " +
    "(resolve_validation_rules, глубокое слияние system → template → " +
    "session): сессия, шаблон YAML (default_rules.yaml), системный вывод " +
    "по семантике имени числовой колонки (auto_generate_rules). " +
    "Системный вывод: цена не ниже нуля, разумный год 1900–2100, " +
    "процент 0–100; неизвестной числовой семантике диапазон не " +
    "назначается из фактических min/max. " +
    "Маска нарушений range_invalid_mask: значения ниже минимума и выше " +
    "максимума, границы независимы, пропуски проверяются отдельно. " +
    "Профиль profile_ranges: полный, включая колонки с 0 нарушений; " +
    "actual_min и actual_max против min_allowed/max_allowed, " +
    "invalid_examples до 5 уникальных. " +
    "Прогон validate_ranges — строки только для колонок с нарушениями, " +
    "правило min ≤ x ≤ max; rule_bounds для каждой matched колонки — " +
    "сигнал применимости; агрегация items, scope column — чек " +
    "скоупится до выбранного признака; статусы done, warning, pending. " +
    "Исправление — «Мастер исправления диапазонов» через " +
    "range-profile и range-corrections: 5 стратегий clip, median, " +
    "replace_null, drop_rows, flag; границы и маски всегда из resolved " +
    "rules сервера, не из клиента";

  return (
    <div
      role="img"
      aria-label={ariaLabel}
      className="rounded-lg border border-neutral-200 bg-white p-3"
    >
      {/* Шапка: заголовок + фронт-контракт чека */}
      <div className="flex items-baseline justify-between gap-2 mb-3 px-1">
        <h3 className="text-[13px] font-semibold text-neutral-900">
          Диапазоны значений: Валидация
        </h3>
        <code className="text-[10px] text-neutral-500 font-mono">
          GET /v1/session/dataset/validate
        </code>
      </div>

      {/* Блок 1: эталон правил — 3 источника с приоритетом */}
      <div className="rounded-md border border-brand/30 bg-white px-3 py-2 mb-2">
        <div className="flex items-center gap-2 mb-1.5">
          <span
            className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-brand-light text-brand"
            aria-hidden="true"
          >
            <ClipboardList size={12} />
          </span>
          <span className="text-[11px] font-semibold text-neutral-900 leading-tight">
            Эталон min/max-правил — 3 источника, приоритет фиксирован
          </span>
          <code className="ml-auto text-[9px] text-neutral-400 font-mono hidden sm:inline">
            resolve_validation_rules
          </code>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-1.5">
          {RULE_SOURCES.map((src) => (
            <div
              key={src.id}
              className="rounded border border-neutral-200 px-2 py-1.5 min-w-0"
            >
              <div className="flex items-center gap-1">
                <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-brand text-white text-[8.5px] font-bold" aria-hidden="true">
                  {src.priority}
                </span>
                <span className="text-[10px] font-semibold text-neutral-900 leading-tight">
                  {src.label}
                </span>
              </div>
              <p className="text-[9px] text-neutral-600 leading-snug mt-0.5">
                {src.detail}
              </p>
              <code className="text-[8.5px] text-neutral-400 font-mono leading-tight break-all">
                {src.source}
              </code>
            </div>
          ))}
        </div>
        <p className="text-[9.5px] text-neutral-500 leading-snug mt-1 pl-1 border-l border-neutral-100">
          Механика резолва:{" "}
          <code className="font-mono text-neutral-700">_deep_merge(_deep_merge(system, template), overrides)</code>{" "}
          — верхний слой слияния выигрывает, источник правила фиксируется
          для честного отображения на фронте.
        </p>
      </div>

      <div className="flex justify-center" aria-hidden="true">
        <ChevronDown size={16} className="text-neutral-400" aria-label="chevron down" role="img" />
      </div>

      {/* Блок 2: системный вывод границ по имени колонки */}
      <div className="rounded-md border border-brand/30 bg-white px-3 py-2 mb-2">
        <div className="flex items-center gap-2 mb-1.5">
          <span
            className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-brand-light text-brand"
            aria-hidden="true"
          >
            <Ruler size={12} />
          </span>
          <span className="text-[11px] font-semibold text-neutral-900 leading-tight">
            Системный вывод: границы по семантике имени числовой колонки
          </span>
          <code className="ml-auto text-[9px] text-neutral-400 font-mono hidden sm:inline">
            auto_generate_rules
          </code>
        </div>
        <div className="grid grid-cols-3 gap-1.5">
          {RANGE_LANES.map((lane) => {
            const Icon = lane.icon;
            return (
              <div
                key={lane.id}
                className="rounded border border-neutral-200 px-1.5 py-1.5 flex flex-col gap-0.5 min-w-0"
              >
                <div className="flex items-center gap-1">
                  <span
                    className="flex h-4 w-4 shrink-0 items-center justify-center rounded bg-brand-light text-brand"
                    aria-hidden="true"
                  >
                    <Icon size={10} />
                  </span>
                  <span className="text-[9px] font-semibold text-neutral-900 leading-tight font-mono truncate">
                    {lane.id}
                  </span>
                </div>
                <code className="text-[8px] text-neutral-400 font-mono leading-tight break-all">
                  {lane.tokens}
                </code>
                <span className="text-[9px] text-neutral-600 leading-snug">
                  {lane.rule}
                </span>
                <span className="text-[8.5px] font-mono font-semibold text-brand leading-tight">
                  {lane.bounds}
                </span>
              </div>
            );
          })}
        </div>
        <div className="mt-1.5 rounded border border-neutral-200 bg-neutral-50 px-2 py-1">
          <div className="flex items-center gap-1 flex-wrap">
            <span className="text-[8.5px] font-semibold text-neutral-500 font-mono">
              default_rules.yaml:
            </span>
            {TEMPLATE_LANES.map((lane) => (
              <span key={lane.keywords} className="text-[8.5px] text-neutral-600 leading-snug">
                <code className="font-mono text-neutral-700">{lane.keywords}</code>{" "}
                <span className="font-mono font-semibold text-brand">{lane.bounds}</span>;
              </span>
            ))}
          </div>
        </div>
        <p className="text-[9.5px] text-neutral-500 leading-snug mt-1 pl-1 border-l border-neutral-100">
          Только <span className="font-mono">number</span>-колонки. Колонке{" "}
          <span className="font-semibold">неизвестной семантики</span> диапазон не
          назначается из фактических min/max данных: это гарантировало бы{" "}
          <span className="font-semibold">ложное прохождение</span> — каждое
          наблюдаемое значение стало бы валидным по построению.
        </p>
      </div>

      <div className="flex justify-center" aria-hidden="true">
        <ChevronDown size={16} className="text-neutral-400" aria-label="chevron down" role="img" />
      </div>

      {/* Блок 3: маска нарушений + профиль */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-2">
        <div className="rounded-md border border-brand/30 bg-white px-2 py-2 min-w-0">
          <div className="flex items-center gap-1.5 mb-1">
            <span
              className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-brand-light text-brand"
              aria-hidden="true"
            >
              <FileText size={12} />
            </span>
            <span className="text-[11px] font-semibold text-neutral-900 leading-tight">
              Маска нарушений
            </span>
            <code className="ml-auto text-[9px] text-neutral-400 font-mono hidden sm:inline">
              range_invalid_mask
            </code>
          </div>
          <ul className="flex flex-col gap-0.5">
            {MASK_STEPS.map((step) => (
              <li key={step.code} className="text-[9px] text-neutral-600 leading-snug pl-1 border-l border-neutral-100">
                <code className="font-mono text-neutral-700">{step.code}</code> —{" "}
                <span className="text-neutral-500">{step.meaning}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="rounded-md border border-neutral-300 bg-brand-light/40 px-2 py-2 min-w-0">
          <div className="flex items-center gap-1.5 mb-1">
            <span
              className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-white text-brand border border-brand/30"
              aria-hidden="true"
            >
              <ListChecks size={12} />
            </span>
            <span className="text-[11px] font-semibold text-neutral-900 leading-tight">
              Профиль применимых правил
            </span>
            <code className="ml-auto text-[9px] text-neutral-400 font-mono hidden sm:inline">
              profile_ranges
            </code>
          </div>
          <div className="text-[9px] text-neutral-600 leading-snug">
            Правило подбирается по <span className="font-mono text-neutral-700">keywords</span>{" "}
            в имени колонки; правило без min и max пропускается. Полный профиль —{" "}
            <span className="font-semibold text-neutral-700">включая колонки с 0</span>{" "}
            нарушений.
          </div>
          <div className="mt-1 text-[9px] text-neutral-600 leading-snug">
            <span className="font-mono text-neutral-700">actual_min</span> /{" "}
            <span className="font-mono text-neutral-700">actual_max</span> — факт против{" "}
            <span className="font-mono text-neutral-700">min_allowed</span> /{" "}
            <span className="font-mono text-neutral-700">max_allowed</span>;{" "}
            <span className="font-mono text-neutral-700">invalid_examples</span> — до 5
            уникальных нарушающих значений.
          </div>
        </div>
      </div>

      <div className="flex justify-center" aria-hidden="true">
        <ChevronDown size={16} className="text-neutral-400" aria-label="chevron down" role="img" />
      </div>

      {/* Блок 4: прогон + агрегация нарушений */}
      <div className="rounded-md border border-neutral-300 bg-white px-3 py-2 mb-2">
        <div className="flex items-center gap-2 mb-1">
          <FileCog size={12} className="text-brand" aria-hidden="true" />
          <span className="text-[11px] font-semibold text-neutral-900">
            Прогон и сбор нарушений
          </span>
          <code className="ml-auto text-[9px] text-neutral-400 font-mono hidden sm:inline">
            validate_ranges → _ranges
          </code>
        </div>
        <div className="text-[9.5px] text-neutral-600 leading-snug">
          <code className="font-mono text-neutral-700">validate_ranges</code> эмитит
          запись ТОЛЬКО для колонок с нарушениями: Правило{" "}
          <span className="font-mono text-neutral-700">«min ≤ x ≤ max»</span>{" "}
          (с −∞ / ∞ для отсутствующей границы), Нарушений, % брака, Min факт,
          Max факт.{" "}
          <span className="font-mono">rule_bounds</span> заполняется для{" "}
          <span className="font-semibold text-neutral-700">каждой matched колонки</span> —
          надёжный сигнал применимости: по одному raw нельзя отличить «0 нарушений»
          от «правила нет».
        </div>
        <p className="text-[9.5px] text-neutral-500 leading-snug mt-1 pl-1 border-l border-neutral-100">
          <span className="font-mono text-neutral-700">scope=&quot;column&quot;</span> — при
          выбранном признаке чек скоупится до одной колонки: признака нет в{" "}
          <span className="font-mono">bounds</span> →{" "}
          <span className="font-mono">pending</span> (честный сигнал «правила нет», а не
          «нарушений нет»); matched → статус по её нарушениям. В отличие от «Типов
          данных» (scope=&quot;dataset&quot;), правило диапазона принадлежит конкретной колонке.
        </p>
      </div>

      <div className="flex justify-center" aria-hidden="true">
        <ChevronDown size={16} className="text-neutral-400" aria-label="chevron down" role="img" />
      </div>

      {/* Блок 5: статусы чека */}
      <div className="rounded-md border border-neutral-300 bg-brand-light/40 px-3 py-2 mb-2">
        <div className="flex items-center gap-2 mb-1">
          <ListChecks size={12} className="text-brand" aria-hidden="true" />
          <span className="text-[11px] font-semibold text-neutral-900">
            Итог чека «Диапазоны значений»
          </span>
          <code className="ml-auto text-[9px] text-neutral-400 font-mono hidden sm:inline">
            _run_all_checks → _ranges
          </code>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-1.5">
          {STATUS_ITEMS.map((s) => (
            <div key={s.status} className="rounded border border-neutral-200 bg-white px-2 py-1 min-w-0">
              <span className="text-[9.5px] font-mono font-semibold text-brand">{s.status}</span>
              <p className="text-[8.5px] text-neutral-600 leading-snug mt-0.5">{s.meaning}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Финальный блок: исправление через Мастер диапазонов */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <div className="rounded-md border border-brand/30 bg-brand-light/30 px-2 py-1.5 flex items-start gap-1.5">
          <Wrench size={12} className="text-brand shrink-0 mt-0.5" aria-hidden="true" />
          <div className="text-[9.5px] text-neutral-700 leading-tight min-w-0">
            <span className="font-semibold">«Мастер исправления диапазонов»</span> в карточке
            чека: выбор колонок и стратегии.
            <div className="mt-1 flex flex-col gap-0.5">
              {STRATEGIES.map((s) => (
                <span key={s.id} className="text-[8.5px] leading-snug">
                  <code className="font-mono text-neutral-700">{s.id}</code> — {s.detail}
                </span>
              ))}
            </div>
          </div>
        </div>
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1.5 flex items-start gap-1.5">
          <ShieldCheck size={12} className="text-emerald-600 shrink-0 mt-0.5" aria-hidden="true" />
          <div className="text-[9.5px] text-emerald-800 leading-tight min-w-0">
            <code className="font-mono">GET /v1/session/dataset/range-profile</code> —
            профиль применимых правил + rule_source;{" "}
            <code className="font-mono">POST /v1/session/dataset/range-corrections</code> —
            preview/apply.
            <div className="mt-1">
              Границы и маски всегда из resolved rules сервера — не из клиента; preview
              на глубокой копии, apply — атомарная подмена датасета. Для колонки,
              у которой нет активного правила диапазона, исправление отклоняется
              (ошибка 422).
            </div>
          </div>
        </div>
      </div>

      {/* Подпись: место чека в методике + честный статус */}
      <p className="text-[10px] text-neutral-500 mt-2.5 px-1 leading-snug">
        «Диапазоны значений» — третий из 10 критериев Data Quality (DAMA DMBOK)
        вкладки «Валидация»: числовые поля сверяются с допустимыми минимумами и
        максимумами из resolved rules (отрицательная цена, нереалистичный год,
        процент больше 100). Выход за границы искажает статистику и ломает модели —
        проверка выявляет все нарушения до расчётов.
      </p>
    </div>
  );
}
