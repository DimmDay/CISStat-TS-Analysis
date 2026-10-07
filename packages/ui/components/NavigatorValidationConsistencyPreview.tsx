"use client";

// packages/ui/components/NavigatorValidationConsistencyPreview.tsx
//
// Статичная информационная блок-схема для окна «Обзор» пункта «Логика и
// хронология» (id="consistency", четвёртый пункт) секции «Этапы модуля»
// остановки «Валидация» на странице Навигатор (Task NAVDET-CONSISTENCY,
// 2026-10-08). Родственник NavigatorValidationRangesPreview.
//
// ── Контракт ────────────────────────────────────────────────────────
//   • Визуализация — СТАТИЧНАЯ информационная блок-схема алгоритма
//     проверки «Логика и хронология» (четвёртый из 10 критериев Data
//     Quality): эталон consistency-правил → системный вывод (правило
//     хронологии по date-колонке) → диспетчер типов правил (chronology /
//     comparison / предметные) → единая оценка и профиль → прогон/сбор
//     нарушений → статусы чека → исправление через «Мастер исправления
//     логики и хронологии».
//   • Схема основана на РЕАЛЬНОЙ логике:
//       - validation/rule_resolver.py::resolve_validation_rules
//         (_deep_merge(_deep_merge(system_rules, template_rules),
//         overrides) — приоритет: сессия > шаблон YAML
//         (rules/<template>.yaml, по умолчанию default_rules.yaml) >
//         системный вывод; CHECK_SECTIONS["consistency"] = "consistency")
//       - validation/engine.py::auto_generate_rules (системный слой
//         согласованности): при наличии date/time-колонки (datetime dtype
//         или токены имени year/год/date/дата/time/время/timestamp/
//         period/период) добавляется ОДНО правило «Хронологический
//         порядок» (type="chronology", columns=[первая date-колонка])
//       - rules/default_rules.yaml::consistency — шаблонные правила:
//         condition-правила (date_order: end_date > start_date,
//         total_match) и предметные типовые (temp_precip, profit_revenue,
//         steps_distance, energy_subsystem)
//       - validation/engine.py::_evaluate_consistency_rule — диспетчер по
//         rule_type:
//           · chronology → _chronology_evaluation: time_column = первая
//             колонка правила; group_column из правила или авто-детект
//             (object/string/category, 1 < уникальных ≤ min(100, полвины
//             строк)); по группам shift(1) — сравнение с предыдущей
//             точкой; реверс values < previous — время идёт назад; маска
//             помечает ОБЕ строки нарушающей пары; пары с пропусками не
//             сравниваются; примеры «group=X: прошлое → текущее» (до 5)
//           · comparison → _comparison_evaluation: ровно 2 колонки,
//             оператор из 6 (<, <=, >, >=, ==, !=); comparable = обе
//             notna; invalid = comparable & ~valid; condition-правило
//             парсится безопасным regex «левое оп правое» БЕЗ eval()
//             (_condition_evaluation)
//           · предметные: negative_price (>= 0), positive_prices (> 0),
//             profit_revenue (прибыль ≤ выручка), energy_subsystem
//             (подсистема ≤ общее потребление), steps_distance (шаги = 0
//             при расстоянии > 0), speed_fuel (скорость = 0 при расходе
//             > 1), temp_precip (снег при t > 0, дождь при t < 0)
//       - validation/engine.py::evaluate_consistency_rules — ЕДИНЫЙ
//         источник масок для общей проверки, обзора и исправлений;
//         изоляция ошибок: сбой одного предметного правила →
//         applicable=false («Ошибка правила: …»), проверка не падает;
//         неприменимое правило — applicability_message («Колонка …
//         отсутствует», «Типы колонок нельзя сравнить», «Тип правила …
//         не поддерживается»); вывод: checked/valid/invalid_count,
//         affected_rows (реверс помечает обе строки пары),
//         invalid_examples до 5, supported_actions, correction_columns
//       - validation/engine.py::profile_consistency — полный профиль
//         настроенных правил, включая pass и неприменимость (маска и
//         correction_columns в API-профиль не отдаются)
//       - validation/engine.py::validate_consistency — legacy-контракт
//         поверх профилировщика: строки ТОЛЬКО для применимых правил:
//         Правило, Тип, Колонки, Нарушений, Затронуто строк, Статус
//         «⚠️ Нарушено»/«✅ Соблюдено»
//       - validation/engine.py::_run_all_checks::_consistency (scope=
//         "dataset" — межколоночные правила и ось времени ПРИНЦИПИАЛЬНО
//         не скоупятся до одной колонки, в отличие от ranges/formats;
//         items=[{label: Правило, count: Нарушений}], count = Σ;
//         применимых правил нет → count=None → pending)
//       - apps/api/routers/session.py::get_dataset_consistency_profile
//         (GET /v1/session/dataset/consistency-profile — полный профиль
//         правил + rule_source, not_applicable без применимых правил) и
//         correct_dataset_consistency (POST /v1/session/dataset/
//         consistency-corrections — preview/apply; правила и маски всегда
//         из resolved rules сервера, а не из клиента; preview на глубокой
//         копии, apply — атомарная подмена датасета)
//       - apps/api/consistency_correction.py::preview_consistency_corrections
//         (4 стратегии: sort_chronology — только для chronology-правил,
//         стабильная группо-устойчивая сортировка по времени, NaT — в
//         конец, счёт — изменившие позицию строки; drop_rows — удаление
//         строк по ОБЪЕДИНЁННОЙ маске выбранных правил; replace_null —
//         корректируемые колонки правила → NA по маске; flag — булева
//         колонка <имя>_consistency_valid, коллизия имени — ошибка;
//         пустой выбор/дубликаты индексов/неприменимое или неизвестное
//         правило отклоняются — 422)
//   • Отображается ПРИ ЛЮБЫХ УСЛОВИЯХ — НЕ зависит от useAppShell,
//     activeDataset, fetch, сети, сессии (паттерн других остановок:
//     NavigatorTechInfoPreview, NavigatorPassportPreview,
//     NavigatorValidationRangesPreview и родня).
//
// ── a11y ────────────────────────────────────────────────────────────
//   • Корень: role="img" + aria-label со всей цепочкой — скринридер
//     читает блок-схему как одно изображение.
//   • Стрелки/иконки — aria-hidden="true" (дублируют текст, единый
//     паттерн с другими Navigator*Preview).

import {
  ArrowRightLeft,
  ChevronDown,
  ClipboardList,
  Clock,
  FileCog,
  FileText,
  ListChecks,
  Scale,
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
      "overrides сессии — правила согласованности, скорректированные в рамках сессии (consistency-секция правил)",
    source: "session overrides",
  },
  {
    priority: 2,
    id: "template",
    label: "Шаблон",
    detail:
      "YAML-шаблон правил: rules/<template>.yaml — condition- и предметные правила (по умолчанию default_rules.yaml)",
    source: "default_rules.yaml",
  },
  {
    priority: 3,
    id: "system",
    label: "Система",
    detail:
      "авто-вывод: при наличии date/time-колонки — правило «Хронологический порядок»",
    source: "auto_generate_rules",
  },
];

// ── Диспетчер типов правил (validation/engine.py::_evaluate_consistency_rule) ──

interface RuleLane {
  /** rule_type (стабилен — на нём строятся тесты). */
  id: string;
  /** Название ветки диспетчера. */
  label: string;
  /** Механика вычисления нарушений. */
  mechanics: string[];
  /** Реальная функция ветки. */
  fn: string;
  icon: LucideIcon;
}

const RULE_LANES: RuleLane[] = [
  {
    id: "chronology",
    label: "Хронология",
    mechanics: [
      "time_column — первая колонка правила; group_column — из правила или авто-детект (1 < уникальных ≤ min(100, половина строк))",
      "по группам shift(1) — сравнение каждой точки с предыдущей; реверс values < previous — время идёт назад",
      "маска помечает ОБЕ строки нарушающей пары; пары с пропусками не сравниваются",
    ],
    fn: "_chronology_evaluation",
    icon: Clock,
  },
  {
    id: "comparison",
    label: "Сравнение",
    mechanics: [
      "ровно 2 колонки, оператор из 6: <, <=, >, >=, ==, !=",
      "сравниваются только строки, где обе notna; invalid = comparable & ~valid",
      "condition-правило парсится безопасным regex «левое оп правое» — без eval()",
    ],
    fn: "_comparison_evaluation",
    icon: ArrowRightLeft,
  },
  {
    id: "domain",
    label: "Предметные",
    mechanics: [
      "negative_price ≥ 0 · positive_prices > 0 · profit_revenue: прибыль ≤ выручка",
      "energy_subsystem: подсистема ≤ общее потребление · steps_distance: шаги=0 при расстоянии>0 · speed_fuel: скорость=0 при расходе>1",
      "temp_precip: снег при t>0, дождь при t<0",
    ],
    fn: "default_rules.yaml",
    icon: Scale,
  },
];

// ── Ветви единой оценки (validation/engine.py::evaluate_consistency_rules) ──

const EVAL_STEPS: Array<{ code: string; meaning: string }> = [
  { code: "единый источник масок", meaning: "одни и те же маски для общей проверки, обзора и исправлений — расхождение исключено" },
  { code: "try/except на правило", meaning: "сбой одного предметного правила → applicable=false («Ошибка правила: …»), проверка не падает" },
  { code: "applicability_message", meaning: "«Колонка … отсутствует», «Типы колонок нельзя сравнить», «Тип правила … не поддерживается»" },
  { code: "invalid_examples ≤ 5", meaning: "первые нарушающие значения; affected_rows ≥ реверсов — реверс помечает обе строки пары" },
];

// ── Статусы чека (_run_all_checks::_consistency) ─────────────────────

const STATUS_ITEMS: Array<{ status: string; meaning: string }> = [
  { status: "done", meaning: "0 нарушений — все применимые правила соблюдены" },
  { status: "warning", meaning: ">0 нарушений — хотя бы одно правило нарушено" },
  { status: "pending", meaning: "нет применимых правил (нет date-колонки / правила ссылаются на отсутствующие колонки)" },
];

// ── Стратегии исправления (apps/api/consistency_correction.py) ───────

const STRATEGIES: Array<{ id: string; detail: string }> = [
  { id: "sort_chronology", detail: "только для chronology-правил: стабильная сортировка по времени внутри групп, NaT — в конец; счёт — изменившие позицию строки" },
  { id: "drop_rows", detail: "удаление строк по ОБЪЕДИНЁННОЙ маске всех выбранных правил" },
  { id: "replace_null", detail: "корректируемые колонки правила → NA по маске нарушений" },
  { id: "flag", detail: "булева колонка <имя>_consistency_valid без изменения значений; коллизия имени — ошибка" },
];

// ── Компонент ──────────────────────────────────────────────────────

export function NavigatorValidationConsistencyPreview() {
  // Описание для скринридера — вся цепочка одной строкой.
  const ariaLabel =
    "Блок-схема проверки «Логика и хронология» остановки «Валидация». " +
    "Эталон consistency-правил — три источника по приоритету " +
    "(resolve_validation_rules, глубокое слияние system → template → " +
    "session): сессия, шаблон YAML (default_rules.yaml), системный вывод " +
    "auto_generate_rules — при наличии date/time-колонки одно правило " +
    "«Хронологический порядок». " +
    "Диспетчер _evaluate_consistency_rule по rule_type: хронология — " +
    "группы, shift(1), реверс времени, маска на обе строки пары; " +
    "сравнение — 2 колонки, 6 операторов, condition без eval(); " +
    "предметные — negative_price, profit_revenue, energy_subsystem, " +
    "steps_distance, speed_fuel, temp_precip. " +
    "Единая оценка evaluate_consistency_rules — единый источник масок, " +
    "изоляция ошибок («Ошибка правила: …»), applicability_message; " +
    "профиль profile_consistency — включая pass и неприменимость. " +
    "Прогон validate_consistency — строки только для применимых правил; " +
    "агрегация items, count — сумма нарушений, scope dataset — чек не " +
    "скоупится до одной колонки; статусы done, warning, pending. " +
    "Исправление — «Мастер исправления логики и хронологии» через " +
    "consistency-profile и consistency-corrections: 4 стратегии " +
    "sort_chronology, drop_rows, replace_null, flag; правила и маски " +
    "всегда из resolved rules сервера, не из клиента";

  return (
    <div
      role="img"
      aria-label={ariaLabel}
      className="rounded-lg border border-neutral-200 bg-white p-3"
    >
      {/* Шапка: заголовок + фронт-контракт чека */}
      <div className="flex items-baseline justify-between gap-2 mb-3 px-1">
        <h3 className="text-[13px] font-semibold text-neutral-900">
          Логика и хронология: Валидация
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
            Эталон consistency-правил — 3 источника, приоритет фиксирован
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

      {/* Блок 2: диспетчер типов правил */}
      <div className="rounded-md border border-brand/30 bg-white px-3 py-2 mb-2">
        <div className="flex items-center gap-2 mb-1.5">
          <span
            className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-brand-light text-brand"
            aria-hidden="true"
          >
            <Scale size={12} />
          </span>
          <span className="text-[11px] font-semibold text-neutral-900 leading-tight">
            Диспетчер типов правил: механика вычисления нарушений по rule_type
          </span>
          <code className="ml-auto text-[9px] text-neutral-400 font-mono hidden sm:inline">
            _evaluate_consistency_rule
          </code>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-1.5">
          {RULE_LANES.map((lane) => {
            const Icon = lane.icon;
            return (
              <div
                key={lane.id}
                className="rounded border border-neutral-200 px-2 py-1.5 flex flex-col gap-0.5 min-w-0"
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
                  <span className="ml-auto text-[8.5px] font-semibold text-neutral-600 leading-tight">
                    {lane.label}
                  </span>
                </div>
                <ul className="flex flex-col gap-0.5">
                  {lane.mechanics.map((step) => (
                    <li key={step} className="text-[8.5px] text-neutral-600 leading-snug pl-1 border-l border-neutral-100">
                      {step}
                    </li>
                  ))}
                </ul>
                <code className="text-[8px] text-neutral-400 font-mono leading-tight break-all mt-auto">
                  {lane.fn}
                </code>
              </div>
            );
          })}
        </div>
        <p className="text-[9.5px] text-neutral-500 leading-snug mt-1 pl-1 border-l border-neutral-100">
          Системный слой (<span className="font-mono">auto_generate_rules</span>):{" "}
          при наличии date/time-колонки — <span className="font-semibold">одно</span>{" "}
          правило <span className="font-semibold text-neutral-700">«Хронологический порядок»</span>{" "}
          (type=<span className="font-mono">chronology</span>, первая date-колонка).
          Сравнение колонок в condition-правилах — безопасным парсером,{" "}
          <span className="font-semibold">без eval()</span>: произвольный код из шаблона
          правил не исполняется.
        </p>
      </div>

      <div className="flex justify-center" aria-hidden="true">
        <ChevronDown size={16} className="text-neutral-400" aria-label="chevron down" role="img" />
      </div>

      {/* Блок 3: единая оценка + профиль */}
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
              Единая оценка правил
            </span>
            <code className="ml-auto text-[9px] text-neutral-400 font-mono hidden sm:inline">
              evaluate_consistency_rules
            </code>
          </div>
          <ul className="flex flex-col gap-0.5">
            {EVAL_STEPS.map((step) => (
              <li key={step.code} className="text-[9px] text-neutral-600 leading-snug pl-1 border-l border-neutral-100">
                <code className="font-mono text-neutral-700">{step.code}</code> —{" "}
                <span className="text-neutral-500">{step.meaning}</span>
              </li>
            ))}
          </ul>
          <p className="text-[9px] text-neutral-500 leading-snug mt-1">
            Одно правило не роняет проверку: изоляция ошибок на каждом
            предметном правиле.
          </p>
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
              Профиль настроенных правил
            </span>
            <code className="ml-auto text-[9px] text-neutral-400 font-mono hidden sm:inline">
              profile_consistency
            </code>
          </div>
          <div className="text-[9px] text-neutral-600 leading-snug">
            Полный профиль —{" "}
            <span className="font-semibold text-neutral-700">включая pass и неприменимость</span>{" "}
            правил: честный обзор вместо тишины по неприменимым правилам.
          </div>
          <div className="mt-1 text-[9px] text-neutral-600 leading-snug">
            <span className="font-mono text-neutral-700">checked</span> /{" "}
            <span className="font-mono text-neutral-700">valid</span> /{" "}
            <span className="font-mono text-neutral-700">invalid_count</span> по каждому
            правилу; <span className="font-mono text-neutral-700">supported_actions</span> —
            разрешённые стратегии исправления.
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
            validate_consistency → _consistency
          </code>
        </div>
        <div className="text-[9.5px] text-neutral-600 leading-snug">
          <code className="font-mono text-neutral-700">validate_consistency</code> эмитит
          запись ТОЛЬКО для применимых правил: Правило, Тип, Колонки, Нарушений,{" "}
          <span className="font-mono">Затронуто строк</span>, Статус{" "}
          <span className="text-neutral-700">«⚠️ Нарушено»</span> /{" "}
          <span className="text-neutral-700">«✅ Соблюдено»</span>.{" "}
          <span className="font-mono">items=[{"{"}label: Правило, count: Нарушений{"}"}]</span>,{" "}
          <span className="font-mono">count = Σ</span> по нарушениям правил.
        </div>
        <p className="text-[9.5px] text-neutral-500 leading-snug mt-1 pl-1 border-l border-neutral-100">
          <span className="font-mono text-neutral-700">scope=&quot;dataset&quot;</span> — чек{" "}
          <span className="font-semibold text-neutral-700">ПРИНЦИПИАЛЬНО не скоупится</span>{" "}
          до одной колонки при выбранном признаке: межколоночные правила и ось времени не
          принадлежат одному признаку. Отличие от «Диапазонов значений» и «Форматов»
          (scope=&quot;column&quot;, где правило принадлежит конкретной колонке).
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
            Итог чека «Логика и хронология»
          </span>
          <code className="ml-auto text-[9px] text-neutral-400 font-mono hidden sm:inline">
            _run_all_checks → _consistency
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

      {/* Финальный блок: исправление через Мастер согласованности */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <div className="rounded-md border border-brand/30 bg-brand-light/30 px-2 py-1.5 flex items-start gap-1.5">
          <Wrench size={12} className="text-brand shrink-0 mt-0.5" aria-hidden="true" />
          <div className="text-[9.5px] text-neutral-700 leading-tight min-w-0">
            <span className="font-semibold">«Мастер исправления логики и хронологии»</span> в
            карточке чека: выбор правил и стратегии.
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
            <code className="font-mono">GET /v1/session/dataset/consistency-profile</code> —
            профиль правил + rule_source;{" "}
            <code className="font-mono">POST /v1/session/dataset/consistency-corrections</code> —
            preview/apply.
            <div className="mt-1">
              Правила и маски всегда из resolved rules сервера — не из клиента; preview на
              глубокой копии, apply — атомарная подмена датасета. Пустой выбор, дубликаты
              индексов и правило, которое должно быть применимо, но им не является,
              отклоняются (ошибка 422).
            </div>
          </div>
        </div>
      </div>

      {/* Подпись: место чека в методике + честный статус */}
      <p className="text-[10px] text-neutral-500 mt-2.5 px-1 leading-snug">
        «Логика и хронология» — четвёртый из 10 критериев Data Quality (DAMA DMBOK)
        вкладки «Валидация»: согласованность колонок и монотонность времени (дата
        окончания не раньше начала, прибыль не выше выручки, снег не при плюсовой
        температуре, время не течёт назад). Нарушенная согласованность искажает
        бизнес-логику датасета и модели — проверка выявляет все нарушения до расчётов.
      </p>
    </div>
  );
}
