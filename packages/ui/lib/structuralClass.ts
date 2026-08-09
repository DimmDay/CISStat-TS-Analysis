// packages/ui/lib/structuralClass.ts
//
// Структурный класс данных -- пункт 8 контракта вкладки «Загрузка»:
// "определение класса данных загруженного датасета для автоматической
// маршрутизации и определения траектории исследования". Классификация
// живёт на клиенте (не на бэкенде), потому что зависит от РЕЗУЛЬТАТА
// детекции структуры (packages/ui/components/TsAnalysisUpload.tsx,
// buildDetectionFromColumns) -- эвристики, которую пользователь может
// вручную поправить в UI до применения. Серверная версия детекции не
// знает про эти правки, клиентская знает.
//
// ОХВАТ: сама МАРШРУТИЗАЦИЯ (автоматическая активация конкретных
// проверок/моделей в других вкладках под structuralClass) -- future
// work, отдельная задача. Здесь реализован только сигнал -- вычисление
// и явный показ класса пользователю, это уже самостоятельная ценность
// (прозрачность: "почему система будет предлагать именно эти методы").

export type StructuralClass =
  | "panel_regular"
  | "panel_irregular"
  | "univariate_regular"
  | "univariate_irregular"
  | "cross_sectional";

export interface StructuralClassResult {
  id: StructuralClass;
  label: string;
  description: string;
  routingHint: string;
}

interface ClassifyInput {
  hasDateColumn: boolean;
  hasEntityColumn: boolean;
  entityUniqueCount: number | null; // null, если группирующая колонка не выбрана
  isRegularFrequency: boolean; // есть ли уверенно определённая частота (не "(авто, не получилось)")
}

export function classifyStructure(input: ClassifyInput): StructuralClassResult {
  const { hasDateColumn, hasEntityColumn, entityUniqueCount, isRegularFrequency } = input;

  if (!hasDateColumn) {
    return {
      id: "cross_sectional",
      label: "Кросс-секционные данные",
      description: "Дата не обнаружена или не выбрана — это не временной ряд в строгом смысле.",
      routingHint: "Методы временных рядов (STL, ACF/PACF, ARIMA) неприменимы без даты.",
    };
  }

  const isPanel = hasEntityColumn && (entityUniqueCount ?? 0) > 1;

  if (isPanel && isRegularFrequency) {
    return {
      id: "panel_regular",
      label: "Панельные данные (регулярные)",
      description: `Несколько сущностей (${entityUniqueCount}) × регулярный временной индекс.`,
      routingHint: "Активны: сравнение по сущностям, панельные модели (VAR), групповая декомпозиция.",
    };
  }
  if (isPanel) {
    return {
      id: "panel_irregular",
      label: "Панельные данные (нерегулярные)",
      description: `Несколько сущностей (${entityUniqueCount}), шаг времени неравномерен.`,
      routingHint: "Сначала потребуется ресемплирование в «Предобработке» перед панельными моделями.",
    };
  }
  if (isRegularFrequency) {
    return {
      id: "univariate_regular",
      label: "Одномерный регулярный ряд",
      description: "Один временной ряд, шаг времени регулярен.",
      routingHint: "Активны: полный набор классических моделей (ARIMA/SARIMA/ETS) без предварительного ресемплирования.",
    };
  }
  return {
    id: "univariate_irregular",
    label: "Одномерный нерегулярный ряд",
    description: "Один временной ряд, но шаг времени неравномерен.",
    routingHint: "Потребуется приведение к регулярному шагу в «Предобработке» до ARIMA/SARIMA/декомпозиции.",
  };
}
