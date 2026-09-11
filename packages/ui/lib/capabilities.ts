// packages/ui/lib/capabilities.ts
//
// Источник истины для секции «Возможности» на главной странице (/)
// standalone-режима. Содержит:
//   - Заголовок H2 и поддерживающий текст секции
//   - 14 stat-счётчиков (Block A, marquee-лента) — масштаб продукта
//     в 14 числах
//   - 6 capability-карточек (Block B, сетка 3×2) — ключевые возможности
//     и принципы платформы
//   - Manifesto-цитату (Block C) — эмоциональное закрытие секции,
//     перифраз PURPOSE_TEXT из navigator-stops.ts (не дословная копия,
//     чтобы не дублировать источник истины — там живёт канонический текст).
//
// Все числа и формулировки опираются на реальный код:
//   - "10 модулей"     ← NAVIGATOR_STOPS.length (6 этапов пайплайна +
//                         4 будущих модуля из вкладки «Задачи»)
//   - "8 семейств"     ← MODEL_FAMILIES.length в lib/modeling.ts
//   - "600+ тестов"    ← pytest (~453 + 146 = ~600) и jest (174)
//   - "1 API-контракт" ← FastAPI /docs (Swagger/OpenAPI из коробки)
//
// Задача M-01 (2026-09-12, решение тимлида): добавлены 10 новых
// маркетинговых тезисов; каждый верифицирован по коду main @ 23ca75b:
//   - "24 модели"      ← rules/modeling.yaml (naive…deepar/tft/nhits),
//                         согласуется с живым каталогом Render (24)
//   - "129 эндпоинтов" ← apps/api/routers/*: 129 @router-декораторов
//                         (session 83, modeling_session 24, internal 9,
//                         public 7, models 4, diagnostics 2)
//   - "11 стадий"      ← PIPELINE_STAGES (lib/modeling.ts):
//                         problem_definition → … → model_card
//   - "4 уровня"       ← APPLICABILITY_LABEL: Recommended /
//                         Conditionally applicable / Not recommended /
//                         Not applicable — вместо бинарного Yes/No
//   - "10 критериев"   ← CHECK_META (TsAnalysisValidation.tsx):
//                         Data Quality по DAMA DMBOK
//   - "6 метрик"       ← BacktestMetrics: mae, rmse, mape, mase,
//                         smape, rmsse
//   - "4 теста"        ← rules/modeling.yaml, diagnostics:
//                         ljung_box, jarque_bera, arch_lm, durbin_watson
//   - "5 частот"       ← FREQUENCIES: D / W / M / Q / Y
//   - "4 стратегии"    ← rules/modeling.yaml, ensembles:
//                         simple_average, weighted_average, median,
//                         stacking (заменяют прежний тезис про
//                         дата-контракты — решение тимлида от 2026-09-12)
//   - "3 метода"       ← app/preprocessing/decomposition.py:
//                         STL / Additive / Multiplicative
//
// Формулировки подписей подобраны под фиксированные 2 строки бейджа
// (h-7 + line-clamp-2 при ширине w-[clamp(180px,18vw,300px)]).
//
// Решение тимлида (2026-08-20): capabilities-секция уместна ТОЛЬКО в
// маркетинговом сценарии standalone для неавторизованного. В embedded
// НЕ подключается — там пользователь уже внутри портала.

import type { LucideIcon } from "lucide-react";
import {
  Layers,
  FileCode2,
  ShieldCheck,
  Repeat,
  Cable,
  Lock,
} from "lucide-react";

// ── Заголовок секции ──────────────────────────────────────────

export const CAPABILITIES_TITLE =
  "Исследование данных в едином аналитическом контуре";

export const CAPABILITIES_SUBTITLE =
  "от наблюдения данных — к их глубокому пониманию и обоснованным выводам";

// Section tag — мелкий моноширинный лейбл над H2 (паттерн из Metriqa).
// export const CAPABILITIES_TAG = "ВОЗМОЖНОСТИ";

// ── Stat-счётчики (Block A, marquee-лента из 14 бейджей) ─────

export interface CapabilityStat {
  /** Крупная цифра (строка — чтобы поддержать "600+" и т.д.). */
  value: string;
  /** Короткая подпись под цифрой (умещается в 2 строки бейджа). */
  label: string;
}

export const CAPABILITY_STATS: CapabilityStat[] = [
  // Исходные 4 бейджа (Task 27/29/30)
  { value: "10", label: "модулей глубокого анализа" },
  { value: "8", label: "семейств прогностических моделей" },
  { value: "2800+", label: "автотестов покрывают бизнес-логику" },
  { value: "1", label: "единая исследовательская среда" },
  // 10 новых тезисов (M-01, 2026-09-12; фактура — main @ 23ca75b)
  { value: "24", label: "модели в каталоге: от Naive до нейросетей" },
  { value: "130+", label: "API-эндпоинтов с OpenAPI-документацией" },
  { value: "11", label: "стадий пайплайна моделирования" },
  { value: "4", label: "уровня применимости моделей вместо Yes/No" },
  { value: "10", label: "критериев качества данных по DAMA DMBOK" },
  { value: "6", label: "метрик точности прогноза" },
  { value: "4", label: "статистических теста диагностики остатков" },
  { value: "5", label: "частот рядов: от дневной до годовой" },
  { value: "4", label: "стратегии ансамблевого прогноза" },
  { value: "3", label: "метода декомпозиции ряда" },
];

// ── Capability-карточки (Block B, 6 штук, сетка 3×2) ─────────
//
// Решение тимлида (2026-08-20): из исходных 9 карточек оставлены
// №№ 1, 2, 3, 5, 7, 9 (по 3×2). Убраны:
//   №4 "Паспорт ряда"           — деталь этапа, не принцип платформы
//   №6 "One source of truth"    — внутренний принцип разработки,
//                                  не пользовательская ценность
//   №8 "Двойная жизнь"          — архитектурный факт, не преимущество
//                                  для неавторизованного посетителя
// Оставшиеся 6 формируют плотный, не перегруженный блок.

export interface Capability {
  /** Короткий заголовок (1 строка). */
  title: string;
  /** Описание 1-2 предложениями. */
  description: string;
  /** Пиктограмма из lucide-react. */
  icon: LucideIcon;
}

export const CAPABILITIES: Capability[] = [
  {
    title: "Общее аналитическое пространство",
    description:
      "Все 10 модулей — в одной сессии с сохранением прогресса по 6 этапам. Без переключения инструментов и потери контекста.",
    icon: Layers,
  },
  {
    title: "Открытые спецификации",
    description:
      "Каталог моделей и правила валидации — в YAML, в репозитории. Не чёрный ящик: применимость модели всегда объясняется правилом.",
    icon: FileCode2,
  },
  {
    title: "Промышленные стандарты качества",
    description:
      "Критерии валидации по международным стандартам DAMA DMBOK. Метод 'расширяющегося окна' без заглядывания в будущее. Модели — statsmodels.",
    icon: ShieldCheck,
  },
  {
    title: "Воспроизводимость и аудит",
    description:
      "Возможность повторить анализ с теми же параметрами. Проверить, как были получены результаты. Убедиться в корректности методологии.",
    icon: Repeat,
  },
  {
    title: "Программный доступ",
    description:
      "Та же валидация, предобработка и прогноз — через REST API с OpenAPI-документацией. Два семейства роутов: /v1/public и /v1/internal.",
    icon: Cable,
  },
  {
    title: "Безопасность данных",
    description:
      "Данные не покидают контур: cookie-сессия в браузере, Redis кэширует на бэкенде. Pre-signed и LTTB-сэмплинг для больших файлов.",
    icon: Lock,
  },
];
