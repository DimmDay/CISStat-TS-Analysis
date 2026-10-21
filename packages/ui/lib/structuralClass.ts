// packages/ui/lib/structuralClass.ts
//
// Структурный класс данных -- пункт 8 контракта вкладки «Загрузка»:
// "определение класса данных загруженного датасета для автоматической
// маршрутизации и определения траектории исследования". Дерево решений
// -- по спецификации тимлида (см. чат):
//
//   Нет даты И нет группировки                          → Cross-Sectional
//   Есть дата, ОДНА числовая колонка, нет группировки    → Univariate TS
//   Есть дата, МНОГО числовых колонок, нет группировки   → Multivariate TS
//   Есть дата И есть группирующая колонка                → Panel Data
//     ├─ у всех групп одинаковый набор дат               → Balanced
//     └─ иначе                                           → Unbalanced
//   Есть колонки координат (lat/long) + дата              → Spatio-Temporal
//   Обнаружена вложенная иерархия (страна→регион→...)     → Hierarchical
//   Timestamp + категориальная "событие"/"действие",
//   нерегулярный шаг, нет содержательных числовых рядов   → Event Time Series
//
// Классификация живёт на клиенте (не на бэкенде), потому что зависит от
// РЕЗУЛЬТАТА детекции структуры (TsAnalysisUpload.tsx,
// buildDetectionFromColumns) -- эвристики, которую пользователь может
// вручную поправить в UI до применения. Серверная версия детекции не
// знает про эти правки, клиентская знает.
//
// ИСКЛЮЧЕНИЕ -- Balanced/Unbalanced: это единственная ветка, которую
// невозможно определить эвристикой по columns_info (нужно сравнить
// РЕАЛЬНЫЕ множества дат у каждой группы, а превью 5+5 строк для этого
// недостаточно). Считается реальным запросом к бэкенду --
// GET /v1/session/dataset/panel-balance -- см. вызов в TsAnalysisUpload.tsx.
// Пока результат не пришёл, класс показывается как "Panel Data" без
// уточнения баланса (см. panelBalance: "unknown").
//
// ОХВАТ: сама МАРШРУТИЗАЦИЯ (автоматическая активация конкретных
// проверок/моделей в других вкладках под structuralClass) -- future
// work, отдельная задача. Здесь реализован сигнал (вычисление и
// визуальная схема) -- уже самостоятельная ценность (прозрачность:
// "почему система будет предлагать именно эти методы").

export type StructuralClass =
  | "cross_sectional"
  | "univariate_ts"
  | "multivariate_ts"
  | "panel_balanced"
  | "panel_unbalanced"
  | "panel_unknown"
  | "spatio_temporal"
  | "hierarchical"
  | "event_ts";

// ── UPLOAD-RECOMP-2 (2026-10-20), пункт (б) + дополнение тимлида ───────
// ЕДИНЫЙ ИСТОЧНИК русскоязычных определений классов (RU_DEFINITION) и
// решаемых задач (RU_TASKS) -- столбцы компактной таблицы
// «Определение структуры данных» (StructuralClassSchema.tsx) и карточка
// структурного класса читают отсюда; вторая копия строк запрещена
// (гвард R4: каждый StructuralClass обязан иметь непустое RU-определение
// и непустой список задач -- тесты structural-class-schema-table.test.tsx).
//
// RU_TASKS -- честный перечень задач, решаемых платформой на данных
// соответствующего класса (по фактическому составу модулей: Валидация,
// Предобработка, EDA, каталог моделей, Прогнозирование); обещаний
// несуществующих возможностей нет: панельные модели FE/RE/Panel VAR и
// DeepAR-панель -- контур PANEL-MODELS-3, поставлен этапами 3a/3b/3c
// (PANEL-MODELS-3d) -- статус «доступны в Моделировании» согласован
// с бейджем «Ряд не трансформируем» на той же остановке «Структура».
export const RU_DEFINITION: Record<StructuralClass, string> = {
  cross_sectional: "Кросс-секционные данные: измерения без временно́й оси",
  univariate_ts: "Одномерный временной ряд",
  multivariate_ts: "Многомерный временной ряд: несколько рядов на общей сетке",
  panel_balanced: "Сбалансированная панель",
  panel_unbalanced: "Несбалансированная панель",
  panel_unknown: "Панельные данные (баланс уточняется)",
  spatio_temporal: "Пространственно-временные данные",
  hierarchical: "Иерархические данные: вложенные уровни агрегации",
  event_ts: "Событийный ряд: точки-события, не значения",
};

export const RU_TASKS: Record<StructuralClass, readonly string[]> = {
  cross_sectional: [
    "Валидация качества: типы, форматы, пропуски, выбросы, дубликаты",
    "Описательная статистика и распределения (EDA)",
    "Корреляционный анализ между колонками",
  ],
  univariate_ts: [
    "Полный контур одномерного ряда: паспорт свойств, декомпозиция, стационарность, сезонность",
    "Классические модели каталога (ARIMA/SARIMA/ETS и др.) с бэктестом",
    "Прогнозирование с интервальными оценками",
  ],
  multivariate_ts: [
    "Контур одномерного ряда для каждой колонки + кросс-корреляции",
    "Причинность (Грейнджер) и многомерные модели (VAR/VECM)",
    "Прогнозирование по нескольким рядам",
  ],
  panel_balanced: [
    "По-сущностные проверки регулярности и достаточности",
    "Панельная проверка баланса",
    "Сведение к одному ряду: фильтр сущности или агрегация по времени (на этой остановке)",
    "Панельные модели (FE/RE/Panel VAR, DeepAR-панель) — доступны в «Моделировании»",
  ],
  panel_unbalanced: [
    "По-сущностные проверки регулярности и достаточности",
    "Панельная проверка баланса; выравнивание сеток — в «Предобработке»",
    "Сведение к одному ряду: фильтр сущности или агрегация по времени (на этой остановке)",
    "Панельные модели (FE/RE/Panel VAR, DeepAR-панель) — доступны в «Моделировании»",
  ],
  panel_unknown: [
    "По-сущностные проверки регулярности и достаточности",
    "Панельная проверка баланса (уточняется запросом)",
    "Сведение к одному ряду: фильтр сущности или агрегация по времени (на этой остановке)",
    "Панельные модели (FE/RE/Panel VAR, DeepAR-панель) — доступны в «Моделировании»",
  ],
  spatio_temporal: [
    "Валидация и EDA по временным рядам точек наблюдения",
    "Пространственно-временная визуализация по координатам",
    "Модели и прогноз — после сведения к рядам (фильтр точки / агрегация)",
  ],
  hierarchical: [
    "Проверки качества и EDA по каждой ветви иерархии",
    "Агрегация/дезагрегация по уровням",
    "Прогнозирование по уровням (top-down / bottom-up)",
  ],
  event_ts: [
    "Анализ интервалов между событиями",
    "Частотный профиль событий по времени",
  ],
};

export interface StructuralClassResult {
  id: StructuralClass;
  label: string;
  description: string;
  routingHint: string;
}

export type PanelBalance = "balanced" | "unbalanced" | "unknown";

export interface ColumnLike {
  name: string;
  type_icon: "numeric" | "datetime" | "categorical" | "text";
  unique: number;
}

interface ClassifyInput {
  hasDateColumn: boolean;
  hasEntityColumn: boolean;
  entityUniqueCount: number | null; // null, если группирующая колонка не выбрана
  isRegularFrequency: boolean; // есть ли уверенно определённая частота (не "(авто, не получилось)")
  columnsInfo: ColumnLike[];
  panelBalance?: PanelBalance; // подтягивается отдельным запросом, см. докстринг выше
  // UPLOAD-RECOMP-2-DECOMP (2026-10-20): выбранная временная колонка
  // (detection.dateCol.selected) -- исключается из иерархической цепочки:
  // время -- ось наблюдений, а не уровень вложенности сущностей.
  dateColumnName?: string | null;
}

const LAT_RE = /^(lat|latitude|широта)$/i;
const LON_RE = /^(lon|lng|long|longitude|долгота)$/i;
const EVENT_RE = /event|action|событи|действи|\bтип\b/i;

/** Есть ли пара колонок координат -- пункт "Spatio-Temporal" дерева. */
function detectLatLong(columnsInfo: ColumnLike[]): { latCol: string; lonCol: string } | null {
  const lat = columnsInfo.find((c) => LAT_RE.test(c.name));
  const lon = columnsInfo.find((c) => LON_RE.test(c.name));
  return lat && lon ? { latCol: lat.name, lonCol: lon.name } : null;
}

/**
 * ЭВРИСТИКА (не строгая проверка containment через groupby -- та требует
 * полных данных, не только columns_info): категориальные колонки с
 * заметно разной кардинальностью -- кандидат на вложенную иерархию
 * (страна → регион → город). Возвращает от грубой к мелкой.
 *
 * UPLOAD-RECOMP-2-DECOMP (2026-10-20): excludeNames -- колонки, НЕ
 * являющиеся уровнями сущностей (прежде всего ВЫБРАННАЯ временная
 * колонка). Время -- ось наблюдений, а не уровень вложенности; без
 * исключения любая панель со строчными датами CSV (type_icon
 * "categorical") строила ложную цепочку "region -> month"
 * (кардинальность 2 -> 36 проходит порог 1.5x) и классифицировалась
 * как Hierarchical, перекрывая Panel Data: панельные микросервисы
 * не появлялись и путь к декомпозиции был заблокирован (дефект
 * воспроизведён на живом стеке, см. structuralClass.test.ts R1–R4).
 */
function detectHierarchyCandidates(columnsInfo: ColumnLike[], excludeNames: ReadonlySet<string>): string[] {
  const categorical = columnsInfo
    .filter((c) => c.type_icon === "categorical" && c.unique > 1 && !excludeNames.has(c.name))
    .sort((a, b) => a.unique - b.unique);
  if (categorical.length < 2) return [];
  // Кандидат считается валидным, только если кардинальность растёт минимум
  // вдвое на каждом уровне -- иначе это просто две независимые категории,
  // не вложенность.
  const chain: string[] = [categorical[0].name];
  for (let i = 1; i < categorical.length; i++) {
    if (categorical[i].unique >= chain.length * categorical[0].unique * 1.5) {
      chain.push(categorical[i].name);
    }
  }
  return chain.length >= 2 ? chain : [];
}

function detectEventColumn(columnsInfo: ColumnLike[]): string | null {
  const col = columnsInfo.find((c) => c.type_icon === "categorical" && EVENT_RE.test(c.name));
  return col?.name ?? null;
}

export function classifyStructure(input: ClassifyInput): StructuralClassResult {
  const { hasDateColumn, hasEntityColumn, entityUniqueCount, isRegularFrequency, columnsInfo, panelBalance, dateColumnName } = input;
  const numericCount = columnsInfo.filter((c) => c.type_icon === "numeric").length;
  const isPanel = hasDateColumn && hasEntityColumn && (entityUniqueCount ?? 0) > 1;
  const latLong = detectLatLong(columnsInfo);
  const eventCol = detectEventColumn(columnsInfo);

  // Временная колонка -- не уровень иерархии сущностей (см.
  // detectHierarchyCandidates): исключается ДО построения цепочки.
  const hierarchyChain = detectHierarchyCandidates(
    columnsInfo,
    new Set(dateColumnName ? [dateColumnName] : [])
  );

  // ── Event Time Series: самая специфичная ветка, проверяем первой ──
  if (hasDateColumn && eventCol && !isRegularFrequency && numericCount === 0) {
    return {
      id: "event_ts",
      label: "Event Time Series",
      description: `Временная метка + категориальная колонка «${eventCol}» (событие/действие), нерегулярный шаг, содержательных числовых рядов нет.`,
      routingHint: "Активны: анализ интервалов между событиями, point-process модели — НЕ классические ARIMA/SARIMA (те ждут регулярный числовой ряд).",
    };
  }

  // ── Spatio-Temporal: координаты + дата ──
  if (hasDateColumn && latLong) {
    return {
      id: "spatio_temporal",
      label: "Spatio-Temporal",
      description: `Обнаружены координаты (${latLong.latCol}/${latLong.lonCol}) вместе с датой.`,
      routingHint: "Активны: пространственно-временная визуализация, geo-декомпозиция — обычная EDA по одному ряду недостаточна.",
    };
  }

  // ── Panel Data: дата + группировка ──
  // UPLOAD-RECOMP-2-DECOMP (2026-10-20): ветка ПЕРЕНЕСЕНА ВЫШЕ
  // Hierarchical -- порядок правила дерева спеки (§3.2): правило 4
  // «Есть дата И есть группирующая колонка -> Panel Data» стоит РАНЬШЕ
  // правила 6 «Обнаружена вложенная иерархия -> Hierarchical».
  // Код отклонялся от дерева (иерархия проверялась первой), из-за чего
  // панельный класс крался эвристикой кардинальности на ЛЮБОЙ панели
  // с категориальной датой (region -> month) -- воспроизведено;
  // панельная детекция -- явные факты (селекторы даты/группировки +
  // бэкенд panel-balance), иерархия -- эвристика, чей собственный
  // routingHint честно говорит «не проверено группировкой».
  if (isPanel) {
    if (panelBalance === "balanced") {
      return {
        id: "panel_balanced",
        label: "Panel Data — Balanced",
        description: `${entityUniqueCount} сущностей, у всех совпадает набор дат.`,
        routingHint: "Активны: панельные модели (VAR, fixed/random effects), сравнение сущностей на общей временной сетке.",
      };
    }
    if (panelBalance === "unbalanced") {
      return {
        id: "panel_unbalanced",
        label: "Panel Data — Unbalanced",
        description: `${entityUniqueCount} сущностей, наборы дат по сущностям различаются.`,
        routingHint: "Потребуется выравнивание/ресемплирование по сущностям в «Предобработке» перед панельными моделями.",
      };
    }
    return {
      id: "panel_unknown",
      label: "Panel Data",
      description: `${entityUniqueCount} сущностей × временной индекс. Проверка Balanced/Unbalanced требует полных данных — считается отдельным запросом.`,
      routingHint: "Balanced/Unbalanced уточнит доступные панельные модели — дождитесь расчёта.",
    };
  }

  // ── Hierarchical: вложенная категориальная структура ──
  if (hierarchyChain.length >= 2) {
    return {
      id: "hierarchical",
      label: "Hierarchical",
      description: `Похоже на вложенную иерархию: ${hierarchyChain.join(" → ")} (эвристика по росту кардинальности, не проверено группировкой).`,
      routingHint: "Активны: агрегация/дезагрегация по уровням иерархии, top-down и bottom-up прогнозирование.",
    };
  }

  // ── Без даты и без группировки ──
  if (!hasDateColumn) {
    return {
      id: "cross_sectional",
      label: "Cross-Sectional",
      description: "Дата не обнаружена или не выбрана — это не временной ряд в строгом смысле.",
      routingHint: "Методы временных рядов (STL, ACF/PACF, ARIMA) неприменимы без даты.",
    };
  }

  // ── Одномерный / многомерный ряд без группировки ──
  if (numericCount <= 1) {
    return {
      id: "univariate_ts",
      label: "Univariate TS",
      description: "Один временной ряд (одна числовая колонка), без группировки.",
      routingHint: "Активны: полный набор классических моделей одномерного ряда (ARIMA/SARIMA/ETS).",
    };
  }
  return {
    id: "multivariate_ts",
    label: "Multivariate TS",
    description: `Несколько числовых колонок (${numericCount}) на общей временной оси, без группировки.`,
    routingHint: "Активны: многомерные модели (VAR), анализ кросс-корреляций между рядами.",
  };
}
