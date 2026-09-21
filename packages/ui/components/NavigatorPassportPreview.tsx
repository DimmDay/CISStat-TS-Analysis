"use client";

// packages/ui/components/NavigatorPassportPreview.tsx
//
// Статичная информационная блок-схема для окна «Обзор» пункта «Паспорт
// свойств ряда» (id="passport") секции «Этапы модуля» остановки
// «Загрузка» на странице Навигатор (Task NAVDET-PASSPORT — 10-й,
// последний пункт модуля «Загрузка»).
//
// ── Контракт ────────────────────────────────────────────────────────
//   • Визуализация — СТАТИЧНАЯ информационная блок-схема фиксации
//     первичного снимка свойств ряда (v1.0): предусловия готовности,
//     пайплайн расчёта, группы фиксируемых свойств, роль снимка в
//     цепочке паспортов, отказы.
//   • Схема основана на РЕАЛЬНОЙ логике:
//       - packages/ui/components/TsAnalysisUpload.tsx (DatasetPassportPanel
//         stage="start" внизу страницы «Загрузка», кнопка «Рассчитать
//         паспорт на загрузке»; причины блокировки кнопки — disabledReason)
//       - apps/api/routers/session.py::capture_dataset_passport
//         (POST /dataset/passport/{stage}; контроль порядка точек — 409;
//         _require_passport_series → prepare_passport_series;
//         series_fingerprint — «Свойства ряда не изменились»;
//         append_passport_snapshot → passport_history)
//       - app/core/passport.py::calculate_ts_passport (частота
//         pd.infer_freq — регулярная/«Нерегулярная»; ADF p<0.05;
//         R² тренда ≥0.7; Ljung-Box p>0.05 — только при регулярной
//         частоте; Jarque-Bera p>0.05; направление тренда по slope
//         up/down/flat; топ-3 корреляций признака; сила сезонности
//         STL >0.6, минимум два полных цикла; значимые лаги ACF;
//         Хёрст 0.45/0.55; FFT/периодограмма/вейвлет Морле — топ-3;
//         basic_stats n/mean/std/min/max; минимум 30 валидных точек)
//       - apps/api/session_store.py (PassportSnapshot → passport_history;
//         PASSPORT_STAGES: start → validation → exit → modeling_entry)
//   • Отображается ПРИ ЛЮБЫХ УСЛОВИЯХ — НЕ зависит от useAppShell,
//     activeDataset, fetch, сети, сессии. Даже если датасет удалён,
//     блок-схема остаётся на месте (паттерн других остановок).
//
// ── Что показывает аналитику ─────────────────────────────────────────
//
//   ┌──────────────────────────────────────────────────────────────┐
//   │ Готовность к расчёту:                                        │
//   │ датасет в сессии · признак выбран · дата подтверждена ·      │
//   │ минимум 30 валидных точек                                    │
//   └──────────────────────────────┬───────────────────────────────┘
//   ┌──────────────────────────────▼───────────────────────────────┐
//   │ Пайплайн фиксации:                                           │
//   │ prepare_passport_series → series_fingerprint →               │
//   │ calculate_ts_passport → append_passport_snapshot             │
//   └──────────────────────────────┬───────────────────────────────┘
//   ┌─────────────────┐ ┌─────────────────┐                        │
//   │ Статистика ряда │ │ Структура/тренд │  ← 13 свойств рядом    │
//   ├─────────────────┤ ├─────────────────┤                        │
//   │ Автокорр./сезон.│ │ Распред./спектр │                        │
//   └─────────────────┘ └─────────────────┘                        │
//   ┌──────────────────────────────┬───────────────────────────────┘
//   │ Снимок v1.0 → история паспортов сессии                       │
//   │ точка отсчёта: Валидация v1.1 → Предобработка v1.2 → EDA v1.3│
//   └──────────────────────────────────────────────────────────────┘
//   Ошибки: короткий ряд; свойства не изменились; блокировка кнопки.
//
//   Так аналитик мгновенно понимает:
//     1) что нужно готово до расчёта паспорта на загрузке;
//     2) какие свойства ряда фиксируются в первичном снимке;
//     3) зачем снимок нужен дальше — сравнения v1.0 → v1.1 → v1.2 → v1.3.
//
// ── Архитектурный выбор ──────────────────────────────────────────────
//   • Родственник — NavigatorSourceFileDbPreview (статичная
//     Tailwind/CSS-блок-схема, role="img" + aria-label, без состояния).
//   • Без recharts и fetch — чистая разметка с lucide-react иконками.
//   • Честный статус функционала: паспорт на загрузке реализован
//     полностью (панель DatasetPassportPanel, эндпоинт, история
//     снимков); при нерегулярной частоте часть свойств честно
//     помечается «не применимо» — показано в подписи.
//
// ── a11y ────────────────────────────────────────────────────────────
//   • Корень: role="img" + aria-label со всей цепочкой — скринридер
//     читает блок-схему как одно изображение.
//   • Стрелки/иконки — aria-hidden="true" (дублируют текст,
//     единый паттерн с NavigatorSourceFileDbPreview).

import {
  Activity,
  AudioWaveform,
  BarChart3,
  ChevronDown,
  ClipboardCheck,
  Cog,
  FileX,
  History,
  ScrollText,
  TrendingUp,
} from "lucide-react";

// ── Предусловия готовности (DatasetPassportPanel disabledReason + passport.py) ──

const READINESS_ITEMS: Array<{ ok: string; fail: string }> = [
  { ok: "Датасет в сессии", fail: "Сначала загрузите датасет" },
  { ok: "Исследуемый признак выбран", fail: "Сначала выберите исследуемый признак" },
  { ok: "Временная колонка подтверждена", fail: "Выберите временную колонку" },
  { ok: "Длина ряда — минимум 30 валидных точек", fail: "короткий ряд не рассчитывается" },
];

// ── Шаги пайплайна фиксации (session.py + session_store.py + passport.py) ──

const PIPELINE_STEPS: Array<{ fn: string; note: string }> = [
  {
    fn: "prepare_passport_series",
    note: "признак → ряд с DatetimeIndex",
  },
  {
    fn: "series_fingerprint",
    note: "отпечаток ряда — контроль изменений свойств",
  },
  {
    fn: "calculate_ts_passport",
    note: "расчёт свойств ряда",
  },
  {
    fn: "append_passport_snapshot",
    note: "снимок → история паспортов сессии",
  },
];

// ── Компонент ──────────────────────────────────────────────────────

export function NavigatorPassportPreview() {
  // Описание для скринридера — вся цепочка одной строкой.
  const ariaLabel =
    "Блок-схема фиксации паспорта свойств ряда на загрузке. " +
    "Готовность: датасет в сессии, исследуемый признак выбран, " +
    "временная колонка подтверждена, минимум 30 валидных точек. " +
    "Пайплайн: prepare_passport_series, series_fingerprint, " +
    "calculate_ts_passport, append_passport_snapshot. " +
    "Фиксируются свойства ряда: статистика, частота, стационарность ADF, " +
    "детерминированность тренда, автокорреляция Ljung-Box, нормальность " +
    "Jarque-Bera, направление тренда, корреляции, сезонность STL, " +
    "периоды ACF, показатель Хёрста, FFT, периодограмма, вейвлет Морле. " +
    "Результат: первичный снимок v1.0 в истории паспортов сессии — " +
    "точка отсчёта сравнений после Валидации, Предобработки и EDA. " +
    "Ошибки: сообщение в панели паспорта";

  return (
    <div
      role="img"
      aria-label={ariaLabel}
      className="rounded-lg border border-neutral-200 bg-white p-3"
    >
      {/* Шапка: заголовок + эндпоинт фиксации снимка */}
      <div className="flex items-baseline justify-between gap-2 mb-3 px-1">
        <h3 className="text-[13px] font-semibold text-neutral-900">
          Паспорт свойств ряда: Загрузка
        </h3>
        <code className="text-[10px] text-neutral-500 font-mono">
          POST /dataset/passport/start
        </code>
      </div>

      {/* Готовность к расчёту — предусловия страницы «Загрузка» */}
      <div className="rounded-md border border-brand/30 bg-white px-3 py-2 mb-2">
        <div className="flex items-center gap-2 mb-1.5">
          <span
            className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-brand-light text-brand"
            aria-hidden="true"
          >
            <ClipboardCheck size={12} />
          </span>
          <span className="text-[11px] text-neutral-700 leading-tight">
            Готовность к расчёту — панель паспорта внизу страницы «Загрузка»
          </span>
        </div>
        <div className="grid grid-cols-2 gap-x-2 gap-y-0.5">
          {READINESS_ITEMS.map((item) => (
            <span key={item.ok} className="text-[9.5px] text-neutral-600 leading-snug">
              {item.ok}
              {item.fail ? (
                <>
                  {" — иначе "}
                  <span className="font-mono text-neutral-400">{item.fail}</span>
                </>
              ) : null}
            </span>
          ))}
        </div>
      </div>

      {/* Пайплайн фиксации — реальные шаги бэкенда */}
      <div className="rounded-md border border-brand/30 bg-white px-3 py-2 mb-2">
        <div className="flex items-center gap-2 mb-1.5">
          <span
            className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-brand-light text-brand"
            aria-hidden="true"
          >
            <Cog size={12} />
          </span>
          <span className="text-[11px] font-semibold text-neutral-900 leading-tight">
            Пайплайн фиксации снимка
          </span>
        </div>
        <div className="grid grid-cols-2 gap-x-2 gap-y-0.5">
          {PIPELINE_STEPS.map((step, i) => (
            <span key={step.fn} className="text-[9.5px] text-neutral-600 leading-snug">
              <span className="font-mono text-brand">{i + 1}. {step.fn}</span>{" "}
              — {step.note}
            </span>
          ))}
        </div>
        <p className="text-[9.5px] text-neutral-500 leading-snug mt-1 pl-1 border-l border-neutral-100">
          Повторный расчёт при том же отпечатке ряда не нужен — срабатывает
          контроль изменений свойств (HTTP 409).
        </p>
      </div>

      <div className="flex justify-center" aria-hidden="true">
        <ChevronDown size={16} className="text-neutral-400" aria-label="chevron down" role="img" />
      </div>

      {/* Что фиксируется: 4 группы свойств ряда (passport.py) */}
      <div className="grid grid-cols-2 gap-2 mb-1">
        {/* Группа 1: Статистика ряда */}
        <div className="rounded-md border border-brand/30 bg-white px-2 py-2 flex flex-col gap-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <span
              className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-brand-light text-brand"
              aria-hidden="true"
            >
              <BarChart3 size={12} />
            </span>
            <span className="text-[11px] font-semibold text-neutral-900 leading-tight">
              Статистика ряда
            </span>
          </div>
          <ul className="flex flex-col gap-0.5">
            <li className="text-[9.5px] text-neutral-600 leading-snug pl-1 border-l border-neutral-100">
              <span className="font-mono text-neutral-700">basic_stats</span> — n · mean ·
              std · min · max
            </li>
            <li className="text-[9.5px] text-neutral-600 leading-snug pl-1 border-l border-neutral-100">
              частота: <span className="font-mono text-neutral-700">infer_freq</span> —
              регулярная или «Нерегулярная»
            </li>
          </ul>
        </div>

        {/* Группа 2: Структура и тренд */}
        <div className="rounded-md border border-brand/30 bg-white px-2 py-2 flex flex-col gap-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <span
              className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-brand-light text-brand"
              aria-hidden="true"
            >
              <TrendingUp size={12} />
            </span>
            <span className="text-[11px] font-semibold text-neutral-900 leading-tight">
              Структура и тренд
            </span>
          </div>
          <ul className="flex flex-col gap-0.5">
            <li className="text-[9.5px] text-neutral-600 leading-snug pl-1 border-l border-neutral-100">
              стационарность: <span className="font-mono text-neutral-700">ADF</span>,{" "}
              p &lt; 0.05 → стационарен
            </li>
            <li className="text-[9.5px] text-neutral-600 leading-snug pl-1 border-l border-neutral-100">
              детерминированность: R² тренда ≥ 0.7
            </li>
            <li className="text-[9.5px] text-neutral-600 leading-snug pl-1 border-l border-neutral-100">
              направление по slope: up · down · flat
            </li>
            <li className="text-[9.5px] text-neutral-600 leading-snug pl-1 border-l border-neutral-100">
              корреляции признака — топ-3
            </li>
          </ul>
        </div>

        {/* Группа 3: Автокорреляция и сезонность */}
        <div className="rounded-md border border-brand/30 bg-white px-2 py-2 flex flex-col gap-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <span
              className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-brand-light text-brand"
              aria-hidden="true"
            >
              <AudioWaveform size={12} />
            </span>
            <span className="text-[11px] font-semibold text-neutral-900 leading-tight">
              Автокорреляция и сезонность
            </span>
          </div>
          <ul className="flex flex-col gap-0.5">
            <li className="text-[9.5px] text-neutral-600 leading-snug pl-1 border-l border-neutral-100">
              <span className="font-mono text-neutral-700">Ljung-Box</span>, p &gt; 0.05 →
              белый шум
            </li>
            <li className="text-[9.5px] text-neutral-600 leading-snug pl-1 border-l border-neutral-100">
              <span className="font-mono text-neutral-700">STL</span> — сила &gt; 0.6,
              минимум два полных цикла
            </li>
            <li className="text-[9.5px] text-neutral-600 leading-snug pl-1 border-l border-neutral-100">
              сезонные периоды: <span className="font-mono text-neutral-700">ACF</span>,
              топ-3 лага
            </li>
          </ul>
        </div>

        {/* Группа 4: Распределение и спектр */}
        <div className="rounded-md border border-brand/30 bg-white px-2 py-2 flex flex-col gap-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <span
              className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-brand-light text-brand"
              aria-hidden="true"
            >
              <Activity size={12} />
            </span>
            <span className="text-[11px] font-semibold text-neutral-900 leading-tight">
              Распределение и спектр
            </span>
          </div>
          <ul className="flex flex-col gap-0.5">
            <li className="text-[9.5px] text-neutral-600 leading-snug pl-1 border-l border-neutral-100">
              нормальность: <span className="font-mono text-neutral-700">Jarque-Bera</span>,
              p &gt; 0.05
            </li>
            <li className="text-[9.5px] text-neutral-600 leading-snug pl-1 border-l border-neutral-100">
              <span className="font-mono text-neutral-700">Хёрст</span>: &lt; 0.45 / &gt; 0.55
              — тип памяти
            </li>
            <li className="text-[9.5px] text-neutral-600 leading-snug pl-1 border-l border-neutral-100">
              <span className="font-mono text-neutral-700">FFT</span> и Периодограмма —
              периоды, топ-3
            </li>
            <li className="text-[9.5px] text-neutral-600 leading-snug pl-1 border-l border-neutral-100">
              вейвлет Морле — масштабы, топ-3
            </li>
          </ul>
        </div>
      </div>

      {/* Стрелка вниз — к результату фиксации */}
      <div className="flex justify-center" aria-hidden="true">
        <ChevronDown size={16} className="text-neutral-400" aria-label="chevron down" role="img" />
      </div>

      {/* Блок-результат: снимок v1.0 и его роль в цепочке паспортов */}
      <div className="rounded-md border border-neutral-300 bg-brand-light/40 px-3 py-2 mb-2">
        <div className="flex items-center gap-2 mb-1">
          <History size={12} className="text-brand" aria-hidden="true" />
          <span className="text-[11px] font-semibold text-neutral-900">
            Первичный снимок v1.0 → история паспортов сессии
          </span>
        </div>
        <div className="text-[9.5px] text-neutral-600 leading-snug">
          <span className="font-semibold text-neutral-700">Точка отсчёта сравнений:</span>{" "}
          Валидация v1.1 → Предобработка v1.2 → EDA v1.3. Baseline нельзя менять после
          фиксации следующей точки; смена признака или временной колонки — сброс цепочки
          паспортов.
        </div>
      </div>

      {/* Ошибки: отказы расчёта и блокировки кнопки */}
      <div className="rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5 mb-2">
        <div className="flex items-center gap-1.5 mb-1">
          <FileX size={12} className="text-amber-600 shrink-0" aria-hidden="true" />
          <span className="text-[10px] font-semibold text-amber-800 leading-tight">
            Если расчёт не прошёл — сообщение в панели паспорта
          </span>
        </div>
        <div className="grid grid-cols-2 gap-x-2 gap-y-0.5">
          <span className="text-[9.5px] text-amber-800 leading-snug">
            Недостаточно данных (нужно минимум 30 валидных точек)
          </span>
          <span className="text-[9.5px] text-amber-800 leading-snug">
            Свойства ряда не изменились с последнего расчёта
          </span>
        </div>
      </div>

      {/* Подпись: где живёт функционал + честный статус */}
      <p className="text-[10px] text-neutral-500 mt-1 px-1 leading-snug">
        Панель «Паспорт свойств ряда: Загрузка» — внизу страницы «Загрузка»:
        кнопка «Рассчитать паспорт на загрузке» фиксирует снимок, статус-точки
        показывают место снимка в цепочке. При нерегулярном шаге ряда часть
        свойств честно помечается как не применимая — вместо выдуманных чисел.
      </p>
    </div>
  );
}
