"use client";

// packages/ui/components/NavigatorValidationDataTypesPreview.tsx
//
// Статичная информационная блок-схема для окна «Обзор» пункта «Типы
// данных» (id="data_types", первый пункт) секции «Этапы модуля»
// остановки «Валидация» на странице Навигатор (Task NAVDET-DATATYPES,
// 2026-09-22).
//
// ── Контракт ────────────────────────────────────────────────────────
//   • Визуализация — СТАТИЧНАЯ информационная блок-схема алгоритма
//     проверки «Типы данных» (первый из 10 критериев Data Quality):
//     построение эталона типов → pandera-схема → прогон → агрегация
//     нарушений → исправление через «Мастер типов».
//   • Схема основана на РЕАЛЬНОЙ логике:
//       - validation/rule_resolver.py::resolve_validation_rules
//         (приоритет эталона: сессия type_schema > шаблон YAML
//         (default_rules / fao_prices / macro) > системный вывод;
//         CHECK_SECTIONS["data_types"] = "schema")
//       - validation/engine.py::infer_system_type_schema
//         (безопасный системный эталон: dtype + приводимость значений
//         через pd.to_numeric(errors="coerce") + семантика названия;
//         пороги numeric_ratio 0.5/0.9 и парсинга дат 0.8; смешанная
//         Price=[10, 20, "ошибка"] остаётся числовой и ЛОВИТ ошибку,
//         а не объявляется строковой целиком)
//       - validation/engine.py::build_pandera_schema (dtype_map:
//         integer→Int64, float→Float64, string→String, boolean→Bool,
//         datetime→DateTime; nullable→Check.notna, min/max→in_range,
//         allowed_values→isin, unique→Check.unique, pattern→
//         str_matches; Column(..., coerce=True); DataFrameSchema(
//         strict=False, coerce=True))
//       - validation/engine.py::validate_dataframe (schema.validate(
//         df, lazy=True) → SchemaErrors → failure_cases.groupby(
//         "column") → schema_errors_by_column)
//       - validation/engine.py::_run_all_checks::_data_types (нет
//         schema.columns → pending «проверка неприменима»; count=Σ;
//         items=[{label: колонка, count}]; done(0)/warning(>0);
//         scope="dataset" — принципиально не скоупится до одной колонки)
//       - apps/api/routers/session.py::get_dataset_validate
//         (GET /v1/session/dataset/validate — фронт-контракт чека)
//   • Отображается ПРИ ЛЮБЫХ УСЛОВИЯХ — НЕ зависит от useAppShell,
//     activeDataset, fetch, сети, сессии (паттерн других остановок:
//     NavigatorTechInfoPreview, NavigatorPassportPreview и родня).
//
// ── Что показывает аналитику ─────────────────────────────────────────
//
//   ┌────────────────────────────────────────────────────────────────┐
//   │ Эталон типов — 3 источника с фиксированным приоритетом:        │
//   │ 1 сессия (type_schema, «Мастер типов») > 2 шаблон YAML >       │
//   │ 3 система (авто-вывод по dtype/приводимости/имени)             │
//   └──────────────────────────────┬─────────────────────────────────┘
//   ┌──────────────────────────────▼─────────────────────────────────┐
//   │ Системный вывод infer_system_type_schema (для каждой колонки): │
//   │ boolean → integer → float → datetime (dtype) · иначе object:   │
//   │ приводимость to_numeric: год ≥0.5 · имя цены/объёма ≥0.5 ·     │
//   │ ≥0.9 → integer|float; имя даты + парсинг ≥0.8 → datetime;      │
//   │ fallback → string. Mixed Price=[10,20,"ошибка"] → числовая.    │
//   └──────────────────────────────┬─────────────────────────────────┘
//   ┌──────────────────────────────▼─────────────────────────────────┐
//   │ Pandera-схема build_pandera_schema:                            │
//   │ dtype_map → pa.Int64/Float64/String/Bool/DateTime +            │
//   │ Check.notna / in_range / isin / unique / str_matches;          │
//   │ coerce=True, strict=False                                      │
//   └──────────────────────────────┬─────────────────────────────────┘
//   ┌──────────────────────────────▼─────────────────────────────────┐
//   │ Прогон: schema.validate(df, lazy=True) → SchemaErrors →        │
//   │ failure_cases.groupby("column") → schema_errors_by_column      │
//   └──────────────────────────────┬─────────────────────────────────┘
//   ┌──────────────────────────────▼─────────────────────────────────┐
//   │ Агрегация _data_types: count = Σ ошибок; items = [{колонка}];  │
//   │ done (0) / warning (>0) / pending (нет схемы); scope=dataset   │
//   └────────────────────────────────────────────────────────────────┘
//   Исправление: «Мастер исправления типов» → type_schema сессии
//   (coerce=True) — высший приоритет при следующем прогоне.
//
//   Так аналитик мгновенно понимает:
//     1) откуда берётся эталон типов и почему у сессии приоритет;
//     2) как система консервативно выводит ожидаемый тип (и почему
//        смешанная колонка честно ловит ошибку);
//     3) как считаются нарушения и статусы «Типов данных»;
//     4) как исправить — через «Мастер исправления типов».
//
// ── Архитектурный выбор ──────────────────────────────────────────────
//   • Родственник — NavigatorTechInfoPreview / NavigatorPassportPreview
//     (статичная Tailwind/CSS-блок-схема, role="img" + aria-label,
//     без состояния, без recharts, без fetch).
//   • Честный статус: системный слой не выдумывает домены — произвольные
//     allowed_values/min/max из наблюдаемых данных не строятся
//     (докстринг rule_resolver.py); без эталона чек честно «pending».
//
// ── a11y ────────────────────────────────────────────────────────────
//   • Корень: role="img" + aria-label со всей цепочкой — скринридер
//     читает блок-схему как одно изображение.
//   • Стрелки/иконки — aria-hidden="true" (дублируют текст, единый
//     паттерн с другими Navigator*Preview).

import {
  CalendarClock,
  ChevronDown,
  ClipboardList,
  Database,
  FileSliders,
  FileCog,
  GitBranch,
  Hash,
  ListChecks,
  Percent,
  ShieldCheck,
  Table2,
  Type,
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
      "type_schema пользователя — исправления из «Мастера исправления типов», coerce включён",
    source: "session_overrides + type_schema",
  },
  {
    priority: 2,
    id: "template",
    label: "Шаблон",
    detail: "YAML-шаблон правил: default_rules / fao_prices / macro",
    source: "rules/<template>.yaml",
  },
  {
    priority: 3,
    id: "system",
    label: "Система",
    detail:
      "безопасный авто-вывод по dtype, приводимости значений и семантике названия",
    source: "infer_system_type_schema(df)",
  },
];

// ── Ветки системного вывода (validation/engine.py::infer_system_type_schema) ──

interface TypeLane {
  /** Ожидаемый тип (стабилен — на нём строятся тесты). */
  id: string;
  /** Условие вывода (if/elif chain: первое совпадение выигрывает). */
  condition: string;
  icon: LucideIcon;
}

const TYPE_LANES: TypeLane[] = [
  { id: "boolean", condition: "is_bool_dtype", icon: GitBranch },
  { id: "integer", condition: "is_integer_dtype", icon: Hash },
  { id: "float", condition: "is_float_dtype", icon: Percent },
  { id: "datetime", condition: "is_datetime64_any_dtype", icon: CalendarClock },
  { id: "string", condition: "fallback (object после проверок приводимости)", icon: Type },
];

// Пороги приводимости object-колонок (infer_system_type_schema).
const COERCE_RULES: Array<{ rule: string; note: string }> = [
  {
    rule: "имя year/год + числовость ≥ 0.5",
    note: "→ integer",
  },
  {
    rule: "имя price/цена/value/amount/volume/quantity/count/rate/percent/pct/share + ≥ 0.5",
    note: "→ integer|float (по дробности остатка)",
  },
  {
    rule: "числовость значений ≥ 0.9 (без подсказки имени)",
    note: "→ integer|float",
  },
  {
    rule: "имя date/дата/time/время + парсинг дат ≥ 0.8",
    note: "→ datetime",
  },
];

// ── Проверки pandera (validation/engine.py::build_pandera_schema) ────

const PANDERA_CHECKS: Array<{ when: string; check: string }> = [
  { when: "nullable: false", check: "Check.notna()" },
  { when: "min / max", check: "Check.in_range(min, max)" },
  { when: "allowed_values", check: "Check.isin([...])" },
  { when: "unique: true", check: "Check.unique()" },
  { when: "pattern", check: "Check.str_matches(...)" },
];

// ── Статусы чека (_run_all_checks::_data_types) ──────────────────────

const STATUS_ITEMS: Array<{ status: string; meaning: string }> = [
  { status: "done", meaning: "0 нарушений — фактические dtype соответствуют эталону" },
  { status: "warning", meaning: ">0 нарушений — есть значения, не приводимые к ожидаемому типу" },
  { status: "pending", meaning: "эталон пуст (нет schema.columns) — проверка неприменима" },
];

// ── Компонент ──────────────────────────────────────────────────────

export function NavigatorValidationDataTypesPreview() {
  // Описание для скринридера — вся цепочка одной строкой.
  const ariaLabel =
    "Блок-схема проверки «Типы данных» остановки «Валидация». " +
    "Эталон типов — три источника по приоритету: сессия (type_schema из " +
    "Мастера исправления типов), шаблон YAML, системный вывод. " +
    "Системный вывод infer_system_type_schema: boolean, integer, float, " +
    "datetime по dtype; object-колонки — приводимость to_numeric с " +
    "порогами 0.5 и 0.9, даты с порогом 0.8, fallback string; смешанная " +
    "Price=[10, 20, ошибка] остаётся числовой и ловит ошибку. " +
    "Pandera-схема build_pandera_schema: Int64, Float64, String, Bool, " +
    "DateTime, проверки notna, in_range, isin, unique, str_matches, " +
    "coerce=True, strict=False. " +
    "Прогон schema.validate lazy=True → SchemaErrors → failure_cases → " +
    "schema_errors_by_column. Агрегация: count = сумма ошибок, " +
    "статусы done, warning, pending, scope dataset. " +
    "Исправление — «Мастер исправления типов» через type_schema сессии";

  return (
    <div
      role="img"
      aria-label={ariaLabel}
      className="rounded-lg border border-neutral-200 bg-white p-3"
    >
      {/* Шапка: заголовок + фронт-контракт чека */}
      <div className="flex items-baseline justify-between gap-2 mb-3 px-1">
        <h3 className="text-[13px] font-semibold text-neutral-900">
          Типы данных: Валидация
        </h3>
        <code className="text-[10px] text-neutral-500 font-mono">
          GET /v1/session/dataset/validate
        </code>
      </div>

      {/* Блок 1: эталон типов — 3 источника с приоритетом */}
      <div className="rounded-md border border-brand/30 bg-white px-3 py-2 mb-2">
        <div className="flex items-center gap-2 mb-1.5">
          <span
            className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-brand-light text-brand"
            aria-hidden="true"
          >
            <ClipboardList size={12} />
          </span>
          <span className="text-[11px] font-semibold text-neutral-900 leading-tight">
            Эталон типов — 3 источника, приоритет фиксирован
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
          Источник отмечается на фронте: <span className="font-mono">system → template → session</span>{" "}
          (правило сессии всегда видит, откуда взялся эталон).
        </p>
      </div>

      <div className="flex justify-center" aria-hidden="true">
        <ChevronDown size={16} className="text-neutral-400" aria-label="chevron down" role="img" />
      </div>

      {/* Блок 2: системный вывод эталона (infer_system_type_schema) */}
      <div className="rounded-md border border-brand/30 bg-white px-3 py-2 mb-2">
        <div className="flex items-center gap-2 mb-1.5">
          <span
            className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-brand-light text-brand"
            aria-hidden="true"
          >
            <ShieldCheck size={12} />
          </span>
          <span className="text-[11px] font-semibold text-neutral-900 leading-tight">
            Системный вывод: ожидаемый тип для каждой колонки
          </span>
          <code className="ml-auto text-[9px] text-neutral-400 font-mono hidden sm:inline">
            infer_system_type_schema
          </code>
        </div>
        {/* 5 веток dtype (if/elif chain) */}
        <div className="grid grid-cols-5 gap-1.5 mb-2">
          {TYPE_LANES.map((lane) => {
            const Icon = lane.icon;
            return (
              <div
                key={lane.id}
                className="rounded border border-neutral-200 px-1 py-1.5 flex flex-col gap-0.5 min-w-0"
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
                  {lane.condition}
                </code>
              </div>
            );
          })}
        </div>
        {/* Приводимость object-колонок */}
        <div className="text-[9.5px] text-neutral-600 leading-snug">
          <span className="font-semibold text-neutral-700">object-колонка</span> —{" "}
          приводимость значений{" "}
          <code className="font-mono text-neutral-700">pd.to_numeric(errors=&quot;coerce&quot;)</code>:
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-2 gap-y-0.5 mt-0.5">
          {COERCE_RULES.map((r) => (
            <span key={r.rule} className="text-[9px] text-neutral-600 leading-snug">
              {r.rule} <span className="font-mono text-neutral-700">{r.note}</span>
            </span>
          ))}
        </div>
        {/* Честность алгоритма: смешанная колонка */}
        <p className="text-[9.5px] text-neutral-500 leading-snug mt-1 pl-1 border-l border-neutral-100">
          Смешанная колонка <code className="font-mono">Price=[10, 20, &quot;ошибка&quot;]</code> остаётся{" "}
          <span className="font-semibold">числовой</span> — и честно ловит ошибку, а не
          объявляется строковой целиком. Домены и диапазоны из наблюдаемых данных
          системой не выдумываются.
        </p>
      </div>

      <div className="flex justify-center" aria-hidden="true">
        <ChevronDown size={16} className="text-neutral-400" aria-label="chevron down" role="img" />
      </div>

      {/* Блок 3: pandera-схема */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-2">
        <div className="rounded-md border border-brand/30 bg-white px-2 py-2 min-w-0">
          <div className="flex items-center gap-1.5 mb-1">
            <span
              className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-brand-light text-brand"
              aria-hidden="true"
            >
              <Table2 size={12} />
            </span>
            <span className="text-[11px] font-semibold text-neutral-900 leading-tight">
              Pandera-схема
            </span>
            <code className="ml-auto text-[9px] text-neutral-400 font-mono hidden sm:inline">
              build_pandera_schema
            </code>
          </div>
          <div className="text-[9px] text-neutral-600 leading-snug">
            <span className="font-mono text-neutral-700">dtype_map:</span>{" "}
            integer → <span className="font-mono">Int64</span> · float →{" "}
            <span className="font-mono">Float64</span> · string →{" "}
            <span className="font-mono">String</span> · boolean →{" "}
            <span className="font-mono">Bool</span> · datetime →{" "}
            <span className="font-mono">DateTime</span>
          </div>
          <div className="mt-1 text-[9px] text-neutral-600 leading-snug">
            <span className="font-mono text-neutral-700">Column(..., coerce=True)</span>, схема{" "}
            <span className="font-mono text-neutral-700">strict=False, coerce=True</span> —
            значения приводятся к эталону, лишние колонки не падают.
          </div>
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
              Проверки из правил
            </span>
          </div>
          <ul className="flex flex-col gap-0.5">
            {PANDERA_CHECKS.map((c) => (
              <li key={c.check} className="text-[9px] text-neutral-600 leading-snug pl-1 border-l border-neutral-100">
                <span className="text-neutral-500">{c.when}</span> →{" "}
                <code className="font-mono text-neutral-700">{c.check}</code>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="flex justify-center" aria-hidden="true">
        <ChevronDown size={16} className="text-neutral-400" aria-label="chevron down" role="img" />
      </div>

      {/* Блок 4: прогон + агрегация нарушений */}
      <div className="rounded-md border border-neutral-300 bg-white px-3 py-2 mb-2">
        <div className="flex items-center gap-2 mb-1">
          <Database size={12} className="text-brand" aria-hidden="true" />
          <span className="text-[11px] font-semibold text-neutral-900">
            Прогон и сбор нарушений
          </span>
        </div>
        <div className="text-[9.5px] text-neutral-600 leading-snug">
          <code className="font-mono text-neutral-700">schema.validate(df, lazy=True)</code> →{" "}
          <span className="font-mono">SchemaErrors</span> →{" "}
          <code className="font-mono text-neutral-700">failure_cases</code> →{" "}
          <span className="font-mono">groupby(&quot;column&quot;)</span> →{" "}
          <code className="font-mono text-neutral-700">schema_errors_by_column</code> —
          ошибки агрегируются по колонкам (до 100 первых попадают в детализацию).
        </div>
      </div>

      {/* Блок 5: статусы чека */}
      <div className="rounded-md border border-neutral-300 bg-brand-light/40 px-3 py-2 mb-2">
        <div className="flex items-center gap-2 mb-1">
          <FileCog size={12} className="text-brand" aria-hidden="true" />
          <span className="text-[11px] font-semibold text-neutral-900">
            Итог чека «Типы данных»
          </span>
          <code className="ml-auto text-[9px] text-neutral-400 font-mono hidden sm:inline">
            _run_all_checks → _data_types
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
        <p className="text-[9.5px] text-neutral-500 leading-snug mt-1 pl-1 border-l border-neutral-100">
          Нарушения уходят на фронт списком <span className="font-mono">items=[{"{"}label: колонка, count{"}"}]</span>;{" "}
          проверка <span className="font-semibold">dataset-wide</span> — не скоупится до одной
          колонки при выборе признака (scope честно показывает «dataset»).
        </p>
      </div>

      {/* Финальный блок: исправление через Мастер типов */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <div className="rounded-md border border-brand/30 bg-brand-light/30 px-2 py-1.5 flex items-center gap-1.5">
          <Wrench size={12} className="text-brand shrink-0" aria-hidden="true" />
          <span className="text-[9.5px] text-neutral-700 leading-tight">
            Исправление — <span className="font-semibold">«Мастер исправления типов»</span> в карточке
            чека: целевой тип по колонке
          </span>
        </div>
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1.5 flex items-center gap-1.5">
          <FileSliders size={12} className="text-emerald-600 shrink-0" aria-hidden="true" />
          <span className="text-[9.5px] text-emerald-800 leading-tight">
            Выбор фиксируется в <span className="font-mono">type_schema</span> сессии — источник
            «сессия» становится высшим приоритетом при следующем прогоне
          </span>
        </div>
      </div>

      {/* Подпись: место чека в методике + честный статус */}
      <p className="text-[10px] text-neutral-500 mt-2.5 px-1 leading-snug">
        «Типы данных» — первый из 10 критериев Data Quality (DAMA DMBOK) вкладки
        «Валидация»: фактический профиль dtype и семантический класс колонок
        сверяется с эталоном. Системный эталон консервативен — он не объявляет
        фактические категории допустимым справочником и не строит произвольные
        min/max из наблюдаемого диапазона.
      </p>
    </div>
  );
}
