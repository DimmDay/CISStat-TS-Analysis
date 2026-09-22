"use client";

// packages/ui/components/NavigatorValidationFormatsPreview.tsx
//
// Статичная информационная блок-схема для окна «Обзор» пункта «Форматы
// и шаблоны» (id="formats", второй пункт) секции «Этапы модуля»
// остановки «Валидация» на странице Навигатор (Task NAVDET-FORMATS,
// 2026-09-22). Родственник NavigatorValidationDataTypesPreview.
//
// ── Контракт ────────────────────────────────────────────────────────
//   • Визуализация — СТАТИЧНАЯ информационная блок-схема алгоритма
//     проверки «Форматы и шаблоны» (второй из 10 критериев Data
//     Quality): эталон правил форматов → системный вывод шаблонов по
//     имени колонки → маска нарушений (fullmatch, пропуски не считаются)
//     → прогон/сбор нарушений → статусы чека → исправление через
//     «Мастер исправления форматов и шаблонов».
//   • Схема основана на РЕАЛЬНОЙ логике:
//       - validation/rule_resolver.py::resolve_validation_rules
//         (_deep_merge(_deep_merge(system_rules, template_rules),
//         overrides) — приоритет: сессия > шаблон YAML
//         (rules/<template>.yaml, по умолчанию default_rules.yaml) >
//         системный вывод; CHECK_SECTIONS["formats"] = "formats")
//       - validation/engine.py::_system_format_rules (вызывается из
//         auto_generate_rules): только object/string-колонки; шаблон
//         назначается по семантике ИМЕНИ — email/e-mail → email-шаблон
//         (threshold 95), phone/телефон/mobile → телефон РФ (90),
//         date/дата → дата ISO YYYY-MM-DD (98), currency/валюта →
//         код валюты [A-Z]{3} (100); колонке без семантики имени
//         правило НЕ назначается (правило не выводится из фактических
//         значений — иначе каждое наблюдаемое значение стало бы валидным
//         по построению)
//       - validation/engine.py::DEFAULT_FORMAT_PATTERNS (email,
//         phone_ru, date_iso, currency — дефолтные regex + пороги)
//       - validation/engine.py::format_invalid_mask
//         (re.compile — шаблон валиден до прогона; str.fullmatch —
//         совпадает ВСЁ значение, не подстрока; пропуски (NaN) не
//         считаются нарушениями)
//       - validation/engine.py::profile_formats (threshold по умолчанию
//         95; match_pct = доля прошедших шаблон; invalid_examples — до
//         5 уникальных нарушающих значений; пустая колонка (total_count
//         = 0) не делает проверку применимой)
//       - validation/engine.py::validate_formats (строка результата на
//         КАЖДУЮ matched колонку — даже с 0 нарушений: надёжный сигнал
//         применимости «правило matched эту колонку»; match_pct >=
//         threshold → Норма, ниже → Отклонение)
//       - validation/engine.py::_run_all_checks::_formats
//         (items=[{label: колонка, count: Нарушений}], count=Σ;
//         _status: done(0)/warning(>0)/pending(нет правила); scope=
//         "column" — при выбранном признаке чек скоупится до одной
//         колонки: не matched → pending (честный сигнал «правила нет»),
//         matched → статус по её нарушениям; отличие от «Типов данных»,
//         где scope="dataset")
//       - apps/api/routers/session.py::get_dataset_format_profile
//         (GET /v1/session/dataset/format-profile — профиль применимых
//         правил + rule_source) и correct_dataset_formats
//         (POST /v1/session/dataset/format-corrections — preview/apply;
//         regex всегда из resolved rules, а не из клиента; preview не
//         мутирует сессию, apply сохраняет подготовленную копию атомарно)
//       - apps/api/format_correction.py::preview_format_corrections
//         (4 стратегии: replace_null — нарушение → NA; smart_replace —
//         медиана валидных для числовых, unknown@example.com для email,
//         +79990000000 для телефона, NaT для даты, USD для валюты;
//         normalize — strip/lower/чистка мусорных символов (неприменима
//         к числовым); flag — добавляет булеву колонку <имя>_format_valid)
//   • Отображается ПРИ ЛЮБЫХ УСЛОВИЯХ — НЕ зависит от useAppShell,
//     activeDataset, fetch, сети, сессии (паттерн других остановок:
//     NavigatorTechInfoPreview, NavigatorPassportPreview,
//     NavigatorValidationDataTypesPreview и родня).
//
// ── a11y ────────────────────────────────────────────────────────────
//   • Корень: role="img" + aria-label со всей цепочкой — скринридер
//     читает блок-схему как одно изображение.
//   • Стрелки/иконки — aria-hidden="true" (дублируют текст, единый
//     паттерн с другими Navigator*Preview).

import {
  Banknote,
  CalendarClock,
  ChevronDown,
  ClipboardList,
  FileCog,
  FileText,
  ListChecks,
  Mail,
  Phone,
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
      "overrides сессии — исправления из «Мастера исправления форматов» (formats-секция правил)",
    source: "session overrides",
  },
  {
    priority: 2,
    id: "template",
    label: "Шаблон",
    detail:
      "YAML-шаблон правил: rules/<template>.yaml — колонка → pattern + threshold (по умолчанию default_rules.yaml)",
    source: "default_rules.yaml",
  },
  {
    priority: 3,
    id: "system",
    label: "Система",
    detail:
      "авто-вывод шаблонов по семантике имени object/string-колонок",
    source: "auto_generate_rules → _system_format_rules",
  },
];

// ── Системный вывод шаблонов (validation/engine.py::_system_format_rules) ──

interface FormatLane {
  /** Семантика имени (стабильна — на ней строятся тесты). */
  id: string;
  /** Токены имени колонки. */
  tokens: string;
  /** Дефолтный шаблон. */
  pattern: string;
  /** Порог дефолтного правила. */
  threshold: string;
  icon: LucideIcon;
}

const FORMAT_LANES: FormatLane[] = [
  {
    id: "email",
    tokens: "email / e-mail",
    pattern: "Email-шаблон",
    threshold: "95",
    icon: Mail,
  },
  {
    id: "phone",
    tokens: "phone / телефон / mobile",
    pattern: "Телефон РФ",
    threshold: "90",
    icon: Phone,
  },
  {
    id: "date",
    tokens: "date / дата",
    pattern: "Дата ISO: YYYY-MM-DD",
    threshold: "98",
    icon: CalendarClock,
  },
  {
    id: "currency",
    tokens: "currency / валюта",
    pattern: "Код валюты: [A-Z]{3}",
    threshold: "100",
    icon: Banknote,
  },
];

// ── Механика маски нарушений (validation/engine.py::format_invalid_mask) ──

const MASK_STEPS: Array<{ code: string; meaning: string }> = [
  { code: "re.compile(pattern)", meaning: "шаблон валиден до прогона (невалидный regex — ошибка правила, не молчаливый пропуск)" },
  { code: "str.fullmatch(pattern)", meaning: "совпадать должно ВСЁ значение, а не подстрока" },
  { code: "series.notna() & ~mask", meaning: "пропуски не считаются нарушениями" },
];

// ── Стратегии исправления (apps/api/format_correction.py) ────────────

const STRATEGIES: Array<{ id: string; detail: string }> = [
  { id: "replace_null", detail: "нарушающие значения → NA" },
  { id: "smart_replace", detail: "числовые — медиана валидных; email → unknown@example.com; телефон → +79990000000; дата → NaT; валюта → USD" },
  { id: "normalize", detail: "strip, lower, чистка мусорных символов (неприменима к числовым)" },
  { id: "flag", detail: "булева колонка <имя>_format_valid — без изменения значений" },
];

// ── Статусы чека (_run_all_checks::_formats) ─────────────────────────

const STATUS_ITEMS: Array<{ status: string; meaning: string }> = [
  { status: "done", meaning: "0 нарушений — все значения matched колонок соответствуют шаблонам" },
  { status: "warning", meaning: ">0 нарушений — есть значения, не прошедшие fullmatch" },
  { status: "pending", meaning: "нет правила для колонки (или проверка не применима)" },
];

// ── Компонент ──────────────────────────────────────────────────────

export function NavigatorValidationFormatsPreview() {
  // Описание для скринридера — вся цепочка одной строкой.
  const ariaLabel =
    "Блок-схема проверки «Форматы и шаблоны» остановки «Валидация». " +
    "Эталон правил форматов — три источника по приоритету " +
    "(resolve_validation_rules, глубокое слияние system → template → " +
    "session): сессия, шаблон YAML (default_rules.yaml), системный вывод " +
    "по семантике имени колонки (_system_format_rules). " +
    "Системный вывод: email, телефон, дата ISO YYYY-MM-DD, код валюты " +
    "A-Z 3 буквы; колонке без семантики имени правило не назначается. " +
    "Маска нарушений format_invalid_mask: re.compile, fullmatch — " +
    "совпадает всё значение, пропуски не считаются нарушениями. " +
    "Профиль profile_formats: match_pct, invalid_examples, порог " +
    "threshold по умолчанию 95; ниже порога — Отклонение. " +
    "Прогон validate_formats — строка на каждую matched колонку даже " +
    "с 0 нарушений; агрегация items по колонкам, scope column — чек " +
    "скоупится до выбранного признака; статусы done, warning, pending. " +
    "Исправление — «Мастер исправления форматов» через " +
    "format-profile и format-corrections: 4 стратегии replace_null, " +
    "smart_replace, normalize, flag; regex всегда из resolved rules " +
    "сервера, не из клиента";

  return (
    <div
      role="img"
      aria-label={ariaLabel}
      className="rounded-lg border border-neutral-200 bg-white p-3"
    >
      {/* Шапка: заголовок + фронт-контракт чека */}
      <div className="flex items-baseline justify-between gap-2 mb-3 px-1">
        <h3 className="text-[13px] font-semibold text-neutral-900">
          Форматы и шаблоны: Валидация
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
            Эталон правил форматов — 3 источника, приоритет фиксирован
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

      {/* Блок 2: системный вывод шаблонов по имени колонки */}
      <div className="rounded-md border border-brand/30 bg-white px-3 py-2 mb-2">
        <div className="flex items-center gap-2 mb-1.5">
          <span
            className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-brand-light text-brand"
            aria-hidden="true"
          >
            <ShieldCheck size={12} />
          </span>
          <span className="text-[11px] font-semibold text-neutral-900 leading-tight">
            Системный вывод: шаблон по семантике имени колонки
          </span>
          <code className="ml-auto text-[9px] text-neutral-400 font-mono hidden sm:inline">
            _system_format_rules
          </code>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
          {FORMAT_LANES.map((lane) => {
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
                  <span className="ml-auto text-[8.5px] font-mono font-semibold text-brand">
                    {lane.threshold}
                  </span>
                </div>
                <code className="text-[8px] text-neutral-400 font-mono leading-tight break-all">
                  {lane.tokens}
                </code>
                <span className="text-[9px] text-neutral-600 leading-snug">
                  {lane.pattern}
                </span>
              </div>
            );
          })}
        </div>
        <p className="text-[9.5px] text-neutral-500 leading-snug mt-1 pl-1 border-l border-neutral-100">
          Только <span className="font-mono">object/string</span>-колонки. Колонке{" "}
          <span className="font-semibold">без семантики имени</span> правило не
          назначается: правило не выводится из фактических значений — иначе каждое
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
              format_invalid_mask
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
              profile_formats
            </code>
          </div>
          <div className="text-[9px] text-neutral-600 leading-snug">
            <span className="font-mono text-neutral-700">match_pct</span> — доля
            прошедших шаблон; порог{" "}
            <span className="font-mono text-neutral-700">threshold</span> — по умолчанию{" "}
            <span className="font-mono font-semibold text-brand">95</span>:{" "}
            <span className="text-neutral-700">match_pct ≥ threshold → Норма</span>, ниже —{" "}
            <span className="text-neutral-700">Отклонение</span>.
          </div>
          <div className="mt-1 text-[9px] text-neutral-600 leading-snug">
            <span className="font-mono text-neutral-700">invalid_examples</span> — до 5
            уникальных нарушающих значений; пустая колонка не делает проверку применимой.
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
            validate_formats → _formats
          </code>
        </div>
        <div className="text-[9.5px] text-neutral-600 leading-snug">
          <code className="font-mono text-neutral-700">validate_formats</code> эмитит
          запись для КАЖДОЙ matched колонки — даже с 0 нарушений (надёжный сигнал
          применимости «правило matched эту колонку»).{" "}
          <span className="font-mono">items=[{"{"}label: колонка, count: Нарушений{"}"}]</span>,{" "}
          <span className="font-mono">count = Σ</span> по нарушениям.
        </div>
        <p className="text-[9.5px] text-neutral-500 leading-snug mt-1 pl-1 border-l border-neutral-100">
          <span className="font-mono text-neutral-700">scope=&quot;column&quot;</span> — при
          выбранном признаке чек скоупится до одной колонки: нет правила для признака →{" "}
          <span className="font-mono">pending</span> (честный сигнал «правила нет», а не
          «нарушений нет»); matched → статус по её нарушениям. В отличие от «Типов
          данных» (scope=&quot;dataset&quot;), правило формата принадлежит конкретной колонке.
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
            Итог чека «Форматы и шаблоны»
          </span>
          <code className="ml-auto text-[9px] text-neutral-400 font-mono hidden sm:inline">
            _run_all_checks → _formats
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

      {/* Финальный блок: исправление через Мастер форматов */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <div className="rounded-md border border-brand/30 bg-brand-light/30 px-2 py-1.5 flex items-start gap-1.5">
          <Wrench size={12} className="text-brand shrink-0 mt-0.5" aria-hidden="true" />
          <div className="text-[9.5px] text-neutral-700 leading-tight min-w-0">
            <span className="font-semibold">«Мастер исправления форматов»</span> в карточке
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
            <code className="font-mono">GET /v1/session/dataset/format-profile</code> —
            профиль + rule_source;{" "}
            <code className="font-mono">POST /v1/session/dataset/format-corrections</code> —
            preview/apply.
            <div className="mt-1">
              Regex всегда из resolved rules сервера — не из клиента; preview на копии,
              apply — атомарная подмена датасета.
            </div>
          </div>
        </div>
      </div>

      {/* Подпись: место чека в методике + честный статус */}
      <p className="text-[10px] text-neutral-500 mt-2.5 px-1 leading-snug">
        «Форматы и шаблоны» — второй из 10 критериев Data Quality (DAMA DMBOK)
        вкладки «Валидация»: текстовые поля сверяются с regex-шаблонами (email,
        телефон, дата, код валюты). Значения, не прошедшие шаблон, не могут
        использоваться в автоматическом пайплайне — проверка выявляет все нарушения
        по шаблонам из resolved rules.
      </p>
    </div>
  );
}
