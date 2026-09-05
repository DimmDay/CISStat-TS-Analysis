"use client";

// packages/ui/components/TsAnalysisModeling.tsx
//
// ОБЩИЙ компонент фичи «Моделирование» — используется И embedded-,
// И standalone-приложением. 3-колоночный лейаут (как TsAnalysisEDA).
//
// Компоновка:
//   [Левая ~240px]       [Центр flex-1]          [Правая ~320px]
//   Моделирование         Описание                Панель управления
//   Контекст hand-off     [таблица кандидатов]    модели с бейджами
//   4/11 ░░░             [метрики-сводка]        [Метрики и алгоритм]
//   ┌─Определение──○─┐   [фильтр по уровню]     [Полный пайплайн]
//   ├─Структура───○─┤                           [Запустить бэктест]
//   └──────────────┘

import {
  useState,
  useRef,
  useEffect,
  useCallback,
} from "react";
import { ChevronDown, ChevronUp, RefreshCw, Filter, Loader2 } from "lucide-react";
import { Button } from "./Button";
import { Metric } from "./Metric";
import { BacktestComparisonChart } from "./BacktestComparisonChart";
import { BacktestOofChart } from "./BacktestOofChart";
import { StatusIcon, type CheckStatus } from "./StatusIcon";
import {
  type ModelCandidate,
  type CandidatesResponse,
  type ApplicabilityLevel,
  type BacktestResponse,
  type ModelingContext,
  type ModelingExecutionScope,
  type ModelAction,
  type TargetColumnResponse,
  APPLICABILITY_LABEL,
  APPLICABILITY_BADGE,
  MODEL_FAMILIES,
  PIPELINE_STAGES,
} from "../lib/modeling";
import { useAppShell } from "../context/AppShellContext";
import { getApiBase } from "../lib/apiClient";
import { ModelingTraceabilityOverview } from "./ModelingTraceabilityOverview";
import { ModelingWorkflowOverview } from "./ModelingWorkflowOverview";

// ── Константы ──────────────────────────────────────────────────

// В проде -- ОТНОСИТЕЛЬНЫЙ путь "/api" (Next.js rewrite проксирует на
// бэкенд). НЕ дёргаем NEXT_PUBLIC_API_URL напрямую -- иначе обойдём
// прокси и потеряем first-party cookie (см. lib/apiClient.ts::getApiBase).
const API_BASE = getApiBase();

const FREQUENCY_LABELS: Record<string, string> = {
  D: "Дневная",
  W: "Недельная",
  M: "Месячная",
  Q: "Квартальная",
  Y: "Годовая",
};

const VALIDATION_STRATEGY_LABELS: Record<string, string> = {
  expanding: "Expanding",
  sliding: "Sliding",
  single: "Single holdout",
};

// ── Утилита для рендера detail ошибок (Task 14 fix) ──────────────
// FastAPI/Pydantic v2 возвращает ошибки ДВУХ форм:
//   1. HTTPException(detail="строка") → detail = "строка" → просто вернуть
//   2. Pydantic validation error → detail = [{loc:[...], msg:..., type:...}, ...]
//      → если просто сделать String(arr), получим "[object Object],[object Object]"
//      (это и было причиной бага в UI до Task 14 fix).
//   3. Массив строк (редкий случай) — джойним.
//
// Эта функция нормализует все три случая в человекочитаемую строку.
function formatErrorDetail(detail: unknown): string | null {
  if (detail == null) return null;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // Каждый элемент — объект с полями {loc, msg, type} (Pydantic v2)
    const parts = detail.map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object") {
        const itemObj = item as Record<string, unknown>;
        const rawLoc = itemObj.loc;
        const locArr = Array.isArray(rawLoc)
          ? (rawLoc as unknown[]).map((x) => String(x))
          : null;
        const msg = itemObj.msg;
        if (locArr && typeof msg === "string") {
          return `${locArr.join(".")}: ${msg}`;
        }
        if (typeof msg === "string") return msg;
      }
      try {
        return JSON.stringify(item);
      } catch {
        return String(item);
      }
    });
    return parts.filter(Boolean).join("; ");
  }
  // Неожиданный тип (число, объект без array) — stringify
  try {
    return JSON.stringify(detail);
  } catch {
    return String(detail);
  }
}

// ── Справка по целям модуля «Моделирование» ────────────────────

const MODELING_HELP = `Цели модуля "Моделирование"

Моделирование — это одноразовый процесс выбора лучшей модели для данного временного ряда. Это НЕ прогнозирование: моделирование выбирает модель, прогнозирование генерирует прогнозы.

Целевая колонка, профиль ряда и план валидации поступают из подтверждённого EDA hand-off и в этом модуле доступны только для чтения.

Движок применимости (23 правила, 4 уровня):
1. RECOMMENDED — модель подходит для данного профиля данных
2. CONDITIONALLY_APPLICABLE — применима с оговорками
3. NOT_RECOMMENDED — формально возможна, но результат вряд ли полезен
4. NOT_APPLICABLE — модель не может быть применена

8 семейств моделей (24 модели):
• Baselines (4) — Naive, Seasonal Naive, Drift, Mean
• Эксп. сглаживание (3) — ETS, ETS Damped, Theta
• ARIMA (2) — ARIMA/SARIMA, Auto-ARIMA
• Многомерные (2) — VAR, VECM
• Волатильность (2) — GARCH, EGARCH
• Структурные (2) — Prophet, TBATS
• Деревья и бустинг (4) — XGBoost, LightGBM, CatBoost, RF
• Нейросетевые (5) — LSTM, DeepAR, TFT, N-BEATS, N-HiTS

11-стадийный пайплайн:
1. Определение задачи → 2. Структура данных → 3. Ограничения
→ 4. Пул кандидатов → 5. Baseline → 6. Бэктест → 7. Тюнинг
→ 8. Диагностика → 9. Сравнение → 10. Выбор модели → 11. Model Card

Метрики ранжирования: MAE(0.35) + RMSE(0.25) + MAPE(0.20) + MASE(0.20). R² исключён из ранжирования.`;

interface ModelingStageDescription {
  content: string;
}

const MODELING_STAGE_DESCRIPTIONS: Record<string, ModelingStageDescription> = {
  problem_definition: {
    content: `Определение задачи

Цель остановки — зафиксировать, что именно прогнозируется и на каком горизонте. Модуль читает целевую колонку и BacktestPlan из подтверждённого EDA hand-off; менять эти факты здесь нельзя.

Вход: целевая колонка, временная ось, горизонт, стратегия и folds валидации.
Результат: трассируемая постановка задачи, пригодная для единого сравнения моделей.
Критерий завершения: checkpoint modeling_entry содержит согласованные цель и план валидации.`,
  },
  data_structure: {
    content: `Структура данных

Остановка проверяет финальные свойства ряда перед запуском моделей: объём истории, частоту, регулярность, сезонность, количество рядов и экзогенных признаков.

Здесь отображается read-only срез финального паспорта EDA. Он определяет допустимые семейства моделей и необходимую fold-local предобработку.
Критерий завершения: структура однозначно восстановлена из modeling_entry без локального переопределения.`,
  },
  constraint_mapping: {
    content: `Ограничения

Остановка переводит свойства ряда и ограничения среды в capability-контракт моделей. Жёсткие запреты отделяются от предупреждений и условий применимости.

Вход: финальный паспорт, BacktestPlan и доступность production-dispatch.
Результат: объяснимые статусы available, not_applicable, blocked или not_implemented для каждой стадии.
Критерий завершения: каждое ограничение имеет источник и не подменяет фактический статус исполнения.`,
  },
  candidate_generation: {
    content: `Пул кандидатов

Движок применимости формирует воспроизводимый список моделей из полного методологического каталога. Для каждой модели отдельно показываются применимость к ряду и готовность production-исполнения.

Вход: checkpoint modeling_entry и единая capability-матрица.
Результат: каталог моделей, исполнимый shortlist и причины включения или блокировки.
Критерий завершения: пул сохранён в сессии, а обязательные baseline-модели рассчитаны на согласованном горизонте.`,
  },
  baseline_estimation: {
    content: `Baseline

Остановка рассчитывает простые эталонные модели на том же горизонте, тех же folds и той же шкале, что будут использоваться для кандидатов.

Baseline задаёт честную нижнюю границу качества. Сложная модель не проходит gate, если не подтверждает улучшение относительно сопоставимого OOF-прогноза.
Критерий завершения: обязательные baseline имеют текущие backtest run и horizon-aligned метрики.`,
  },
  backtest: {
    content: `Бэктест

Остановка оценивает модели без нарушения временного порядка. Используется согласованный в EDA BacktestPlan; преобразования обучаются только на train-части каждого fold.

Результат: фактические OOF-прогнозы, метрики MAE, RMSE, MAPE и MASE, сигнатуры параметров и предупреждения.
Критерий завершения: все модели execution scope рассчитаны либо явно исключены с обоснованием.`,
  },
  tuning: {
    content: `Тюнинг

Остановка подбирает гиперпараметры только для моделей с capability tune, используя тот же BacktestPlan и fold-local preprocessing, что и основной бэктест.

Можно принять параметры по умолчанию для всего ожидающего scope. Решение фиксируется атомарно и не теряется при обновлении пула кандидатов.
Критерий завершения: каждая применимая модель имеет tuning result либо явный подтверждённый skip.`,
  },
  diagnostics: {
    content: `Диагностика

Остановка анализирует остатки актуального OOF-бэктеста выбранной версии модели. Проверяются автокорреляция, нормальность, ARCH-эффекты и статистика Durbin–Watson.

Диагностика не добавляется скрытым весом к рейтингу: её статус показывается отдельным доказательством риска.
Критерий завершения: для всех моделей текущего scope есть отчёт, связанный с актуальными backtest и parameter signature.`,
  },
  comparison: {
    content: `Сравнение

Остановка сопоставляет только модели одного проверенного OOF-cohort. Рейтинг строится по прогнозным метрикам, а применимость, диагностика и стабильность folds отображаются отдельными слоями решения.

MASE сопровождается прозрачным train-only знаменателем; baseline gate использует фактически совмещённые OOF-точки одинакового горизонта.
Критерий завершения: сформирован воспроизводимый ranking с полными сигнатурами входных артефактов.`,
  },
  selection: {
    content: `Выбор модели

Остановка фиксирует победителя на основании проверенного comparison. Single-кандидат определяется primary OOF loss; ensemble допускается только после фактической проверки прироста на совместимых OOF-прогнозах.

Риски baseline gate, диагностики и selection bias требуют явного подтверждения, а не скрытого обхода.
Критерий завершения: выбран один трассируемый вариант и сохранено обоснование решения.`,
  },
  model_card: {
    content: `Model Card

Финальная остановка собирает паспорт выбранной модели: назначение, данные, BacktestPlan, параметры, метрики, диагностику, ограничения и происхождение артефактов.

Model Card не пересчитывает модель и не заменяет результаты предыдущих остановок. Он фиксирует их согласованную версию для передачи в прогнозирование.
Критерий завершения: карточка создана из актуального selection и доступна как неизменяемый трассируемый артефакт.`,
  },
};

type DescriptionSection =
  | "metrics"
  | "pipeline"
  | "backtest"
  | "scope"
  | "help"
  | null;

// ── Компонент ──────────────────────────────────────────────────

export function TsAnalysisModeling() {
  // ── Контекст: активный датасет ──
  const { activeDataset } = useAppShell();

  // ── Состояние ──
  const [candidates, setCandidates] = useState<ModelCandidate[]>([]);
  const [catalog, setCatalog] = useState<ModelCandidate[]>([]);
  const [statistics, setStatistics] = useState<{
    total_candidates: number;
    by_level: Record<string, number>;
    total_models_in_spec: number;
    runnable_candidates?: number;
    catalog_only_candidates?: number;
    blocked_candidates?: number;
  } | null>(null);
  const [specVersion, setSpecVersion] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasFetched, setHasFetched] = useState(false);

  // UI-состояние
  const [activeStageId, setActiveStageId] = useState("candidate_generation");
  const [activeFamilyId, setActiveFamilyId] = useState<string | null>(null);
  const [activeCandidateId, setActiveCandidateId] = useState<string | null>(
    null
  );
  const [levelFilter, setLevelFilter] = useState<string>("all");
  const [availabilityFilter, setAvailabilityFilter] = useState<"runnable" | "all">("runnable");
  // null — каноническое описание активной остановки. Любая операция
  // временно замещает его и всегда имеет явный путь возврата.
  const [descriptionSection, setDescriptionSection] = useState<DescriptionSection>(null);
  const [descriptionExpanded, setDescriptionExpanded] = useState(false);
  const [hasOverflow, setHasOverflow] = useState(false);
  const descRef = useRef<HTMLDivElement>(null);

  // ── Бэктест ──
  const [backtestResults, setBacktestResults] = useState<
    Record<string, BacktestResponse>
  >({});
  const [backtestLoading, setBacktestLoading] = useState(false);
  const [backtestError, setBacktestError] = useState<string | null>(null);
  const [executionScope, setExecutionScope] = useState<ModelingExecutionScope | null>(null);
  const [exclusionReason, setExclusionReason] = useState("");

  // ── Read-only target_column (мост Upload/EDA → Modeling) ──
  // Модуль читает уже подтверждённую цель из session API, но не
  // меняет её: POST здесь сбросил бы upstream-паспорта и artifacts.
  const [targetColumn, setTargetColumn] = useState<string | null>(null);
  const [hasDataset, setHasDataset] = useState(false);
  const [targetColumnLoading, setTargetColumnLoading] = useState(false);
  const [targetColumnError, setTargetColumnError] = useState<string | null>(
    null
  );

  // Канонический hand-off EDA → Modeling — единственный источник
  // профиля, валидационного плана и checkpoint для расчётов.
  const [modelingContext, setModelingContext] = useState<ModelingContext | null>(null);
  const [modelingContextError, setModelingContextError] = useState<string | null>(null);

  // Первый render происходит до useEffect/fetchModelingContext, поэтому один
  // isLoading (он включается только внутри fetchCandidates) оставлял кадр со
  // «Сравнением бэктестов». Держим bootstrap активным от самого первого
  // render до результата Движка применимости. Неготовый EDA hand-off и ошибки
  // завершают ожидание и передают управление предметным gate/error-состояниям.
  const isApplicabilityBootstrapping = !hasFetched
    && !error
    && !modelingContextError
    && (modelingContext === null || modelingContext.ready === true);

  // ── Завершённые стадии пайплайна ──
  const [completedStages, setCompletedStages] = useState<Set<string>>(new Set<string>());

  const fetchModelingState = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/v1/session/modeling/state`, {
        credentials: "include",
      });
      if (!response.ok) return;
      const body = await response.json();
      if (body?.pipeline) {
        setCompletedStages(new Set(
          Object.entries(body.pipeline)
            .filter(([, status]) => status === "done")
            .map(([stage]) => stage),
        ));
      }
      if (body?.artifacts?.backtests) {
        setBacktestResults(body.artifacts.backtests as Record<string, BacktestResponse>);
      }
      if (body?.artifacts?.execution_scope) {
        setExecutionScope(body.artifacts.execution_scope as ModelingExecutionScope);
      }
    } catch {
      // Контекст остаётся рабочим; state boot можно повторить после операции.
    }
  }, []);

  const fetchModelingContext = useCallback(async () => {
    setModelingContextError(null);
    try {
      const response = await fetch(`${API_BASE}/v1/session/modeling/context`, {
        credentials: "include",
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        setModelingContextError(formatErrorDetail(body.detail) || `HTTP ${response.status}`);
        setModelingContext(null);
        return;
      }
      if (body?.profile && body?.checkpoint && body?.validation_strategy) {
        const context = body as ModelingContext;
        setModelingContext(context);
        setModelingContextError(null);
        if (context.ready) {
          void fetchModelingState();
          setCompletedStages((previous) => {
            const next = new Set(previous);
            next.add("problem_definition");
            next.add("data_structure");
            next.add("constraint_mapping");
            return next;
          });
        }
        return;
      }
      setModelingContext(null);
      setModelingContextError("Ответ EDA hand-off не содержит полный контекст.");
    } catch (reason) {
      setModelingContext(null);
      setModelingContextError(reason instanceof Error ? reason.message : "Контекст моделирования недоступен");
    }
  }, [fetchModelingState]);

  // ── Read-only target_column из сессии ──
  // Modeling только показывает уже подтверждённую upstream-цель. Изменение
  // target здесь запрещено: POST сбросил бы паспорта, EDA hand-off и все
  // Modeling artifacts.
  const fetchTargetColumn = useCallback(async () => {
    setTargetColumnLoading(true);
    setTargetColumnError(null);
    try {
      const res = await fetch(`${API_BASE}/v1/session/target-column`, {
        method: "GET",
        credentials: "include", // cookie сессии обязателен (см. apiClient.ts)
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(
          formatErrorDetail(errBody.detail) || `HTTP ${res.status}: ${res.statusText}`
        );
      }
      const data: TargetColumnResponse = await res.json();
      setTargetColumn(data.target_column);
      setHasDataset(data.has_dataset);
    } catch (err) {
      // Ошибка чтения target_column не подменяется синтетическим рядом.
      setTargetColumnError(
        err instanceof Error ? err.message : "Не удалось получить колонки"
      );
    } finally {
      setTargetColumnLoading(false);
    }
  }, []);

  // datasetId различает повторную загрузку одноимённого файла. Имя остаётся
  // fallback для старого AppShell-контракта.
  const activeDatasetKey = activeDataset?.datasetId ?? activeDataset?.name;
  useEffect(() => {
    // Не показываем цель, контекст и результаты предыдущего
    // dataset, пока session API повторно не подтвердит hand-off.
    setTargetColumn(null);
    setHasDataset(false);
    setModelingContext(null);
    setModelingContextError(null);
    setCandidates([]);
    setCatalog([]);
    setStatistics(null);
    setBacktestResults({});
    setError(null);
    setBacktestError(null);
    setExecutionScope(null);
    setExclusionReason("");
    setActiveCandidateId(null);
    setHasFetched(false);
    setCompletedStages(new Set<string>());
    void fetchTargetColumn();
    void fetchModelingContext();
  }, [activeDatasetKey, fetchTargetColumn, fetchModelingContext]);

  // ── Fetch кандидатов ──
  // Профиль формируется на сервере из подтверждённого EDA hand-off.
  // Ручной профиль и синтетический fallback в рабочий контур не попадают.
  const fetchCandidates = useCallback(async () => {
    if (modelingContext?.ready !== true) {
      setError("Подтвердите финальный паспорт «Для моделирования» на вкладке EDA.");
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/v1/session/modeling/candidates`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          min_level: "CONDITIONALLY_APPLICABLE",
          strategy: modelingContext.validation_strategy.strategy || "expanding",
          horizon: Number(modelingContext.validation_strategy.horizon || 12),
          n_splits: Number(modelingContext.validation_strategy.n_splits || 5),
          gap: Number(modelingContext.validation_strategy.gap || 0),
          train_window: Number(modelingContext.validation_strategy.train_window || 60),
        }),
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(
          formatErrorDetail(errBody.detail) || `HTTP ${res.status}: ${res.statusText}`
        );
      }
      const data: CandidatesResponse = await res.json();
      const baselineRes = await fetch(`${API_BASE}/v1/session/modeling/baselines`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
      });
      if (!baselineRes.ok) {
        const errBody = await baselineRes.json().catch(() => ({}));
        throw new Error(
          formatErrorDetail(errBody.detail)
          || `Baseline bootstrap: HTTP ${baselineRes.status}: ${baselineRes.statusText}`
        );
      }
      const baselineData = await baselineRes.json() as {
        backtests: Record<string, BacktestResponse>;
      };
      if (!baselineData.backtests || Object.keys(baselineData.backtests).length === 0) {
        throw new Error("Baseline bootstrap завершён без рассчитанных моделей.");
      }
      setCandidates(data.candidates);
      setCatalog(data.catalog ?? data.candidates);
      setStatistics(data.statistics);
      setSpecVersion(data.spec_version);
      setBacktestResults((previous) => ({ ...previous, ...baselineData.backtests }));
      setCompletedStages((previous) => {
        const next = new Set(previous);
        next.add("candidate_generation");
        return next;
      });
      void fetchModelingState();
      setHasFetched(true);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Неизвестная ошибка запроса"
      );
    } finally {
      setIsLoading(false);
    }
  }, [modelingContext, fetchModelingState]);

  // ── Авто-fetch только после успешного EDA hand-off ──
  useEffect(() => {
    if (modelingContext?.ready) void fetchCandidates();
  }, [modelingContext?.fingerprint]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Продвижение пайплайна при загрузке пула ──
  useEffect(() => {
    if (hasFetched && candidates.length > 0) {
      setCompletedStages((prev) => {
        const next = new Set(prev);
        next.add("candidate_generation");
        return next;
      });
    }
  }, [hasFetched, candidates.length]);

  // ── Запуск бэктеста ──
  // Маршрут читает канонический, отсортированный по дате ряд из checkpoint.
  // Синтетический fallback намеренно запрещён.
  const runBacktest = useCallback(
    async (modelId: string) => {
      const candidate = catalog.find((item) => item.model_id === modelId);
      if (!candidate?.available_actions.includes("backtest")) {
        setBacktestError(candidate?.blocking_reason || "Production backtest для модели недоступен.");
        return;
      }
      if (modelingContext?.ready !== true) {
        setBacktestError("Бэктест заблокирован: нет подтверждённого EDA hand-off.");
        return;
      }
      setBacktestLoading(true);
      setBacktestError(null);
      try {
        const res = await fetch(`${API_BASE}/v1/session/modeling/backtest`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include", // cookie сессии — для чтения target_column
          body: JSON.stringify({ model_id: modelId }),
        });
        if (!res.ok) {
          const errBody = await res.json().catch(() => ({}));
          throw new Error(
            formatErrorDetail(errBody.detail) || `HTTP ${res.status}: ${res.statusText}`
          );
        }
        const data: BacktestResponse = await res.json();
        if (data.data_source !== "session") {
          throw new Error("Нарушена трассируемость: backend вернул не сессионный ряд.");
        }
        setBacktestResults((prev) => ({ ...prev, [modelId]: data }));
        void fetchModelingState();
      } catch (err) {
        setBacktestError(
          err instanceof Error ? err.message : "Ошибка бэктеста"
        );
      } finally {
        setBacktestLoading(false);
      }
    },
    [catalog, modelingContext, fetchModelingState]
  );

  const decideBacktestScope = useCallback(async (modelId: string, decision: "exclude" | "include") => {
    setBacktestError(null);
    try {
      const reason = decision === "exclude" ? exclusionReason.trim() : undefined;
      if (decision === "exclude" && (!reason || reason.length < 3)) {
        setBacktestError("Укажите причину исключения модели из comparison.");
        return;
      }
      const response = await fetch(`${API_BASE}/v1/session/modeling/backtest/exclude`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ model_id: modelId, decision, reason, acknowledge: decision === "exclude" }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(formatErrorDetail(body.detail) || `HTTP ${response.status}`);
      setExclusionReason("");
      await fetchModelingState();
    } catch (reason) {
      setBacktestError(reason instanceof Error ? reason.message : "Не удалось изменить execution scope");
    }
  }, [exclusionReason, fetchModelingState]);

  // ── Collapse/Expand description ──
  useEffect(() => {
    setDescriptionExpanded(false);
  }, [activeStageId, descriptionSection]);

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

  // ── Overflow detection ──
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
  }, [activeStageId, descriptionSection, catalog]);

  // ── Фильтрация и группировка ──
  const visibleModels = availabilityFilter === "all" ? catalog : candidates;
  const filteredCandidates = visibleModels.filter((c) => {
    if (availabilityFilter === "runnable" && !c.available_actions.includes("backtest")) return false;
    if (levelFilter !== "all" && c.level !== levelFilter) return false;
    return true;
  });

  // Группировка по семействам
  const candidatesByFamily = MODEL_FAMILIES.map((fam) => ({
    ...fam,
    models: filteredCandidates.filter((c) => c.family_id === fam.id),
  })).filter((fam) => fam.models.length > 0);

  // Активный кандидат
  const activeCandidate = catalog.find(
    (c) => c.model_id === activeCandidateId
  );

  useEffect(() => {
    if (activeCandidateId && !filteredCandidates.some((item) => item.model_id === activeCandidateId)) {
      setActiveCandidateId(null);
      setDescriptionSection(null);
    }
  }, [activeCandidateId, availabilityFilter, levelFilter, filteredCandidates]);

  // Пайплайн — динамические статусы на основе completedStages
  const dynamicStages = PIPELINE_STAGES.map((s) => {
    if (completedStages.has(s.id)) return { ...s, status: "done" as const };
    // Первая не-done стадия — active
    const firstNotDone = PIPELINE_STAGES.find(
      (st) => !completedStages.has(st.id)
    );
    if (firstNotDone && firstNotDone.id === s.id)
      return { ...s, status: "active" as const };
    return { ...s, status: "pending" as const };
  });
  const doneStages = dynamicStages.filter((s) => s.status === "done").length;
  const progressPct = Math.round(
    (doneStages / dynamicStages.length) * 100
  );

  const activeStage = PIPELINE_STAGES.find((stage) => stage.id === activeStageId)
    ?? PIPELINE_STAGES[0];
  const activeStageDescription = MODELING_STAGE_DESCRIPTIONS[activeStageId]
    ?? MODELING_STAGE_DESCRIPTIONS.problem_definition;

  // Контекстное описание: активная остановка → выбранная операция → возврат.
  const descriptionContent = (() => {
    if (descriptionSection === "help") return MODELING_HELP;
    if (!descriptionSection) return activeStageDescription.content;
    if (descriptionSection === "metrics") {
      if (activeCandidate) {
        return `Метрики и алгоритм: ${activeCandidate.model_name}\n\nСемейство: ${activeCandidate.family_id}\nУровень применимости: ${APPLICABILITY_LABEL[activeCandidate.level as ApplicabilityLevel]}\nСтатус исполнения: ${activeCandidate.available_actions.includes("backtest") ? "production backtest готов" : "только методологический каталог"}\n${activeCandidate.blocking_reason || ""}\n${activeCandidate.rule_id ? `Правило: ${activeCandidate.rule_id}` : ""}\n${activeCandidate.message}\n\nАлгоритм: движок применимости оценивает 23 правила (5 forbidden, 6 discouraged, 5 conditional, 7 preferred) и определяет наивысший уровень применимости модели для данного профиля данных. Статус исполнения формируется отдельно из реестра реальных backend-dispatch.`;
      }
      return `Метрики и алгоритм: Пул кандидатов\n\nАлгоритм формирования пула:\n1. Применить 23 правила применимости ко всем 24 моделям\n2. Отфильтровать по минимальному уровню (≥ CONDITIONALLY_APPLICABLE)\n3. Baseline-модели включаются всегда\n4. Сортировка по рангу уровня (RECOMMENDED → CONDITIONALLY_APPLICABLE → NOT_RECOMMENDED)`;
    }
    if (descriptionSection === "backtest") {
      return activeCandidate
        ? `Запуск бэктеста: ${activeCandidate.model_name}\n\nОперация рассчитывает фактические OOF-прогнозы на каноническом BacktestPlan из EDA. Предобработка обучается отдельно внутри train-части каждого fold; метрики возвращаются на исходной шкале.\n\nПовторный запуск заменит текущий backtest этой модели и потребует актуализировать зависящие от него диагностику, сравнение и выбор.`
        : activeStageDescription.content;
    }
    if (descriptionSection === "scope") {
      return activeCandidate
        ? `Execution scope: ${activeCandidate.model_name}\n\nИсключение разрешает продолжить сравнение без ещё не рассчитанной модели, но требует явной причины и подтверждения. Возврат модели в scope снова делает её бэктест обязательным.\n\nРешение сохраняется в сессии и остаётся видимым в трассе моделирования.`
        : activeStageDescription.content;
    }
    if (activeCandidate?.stage_capabilities) {
      const labels: Record<string, string> = Object.fromEntries(
        PIPELINE_STAGES.map((stage) => [stage.id, stage.label]),
      );
      const lines = Object.entries(activeCandidate.stage_capabilities).map(([stage, capability]) => (
        `${labels[stage] ?? stage}: ${capability.status}${capability.required ? " · required" : ""} — ${capability.reason}`
      ));
      return `Полный пайплайн: ${activeCandidate.model_name}\n\nCapability contract по 11 стадиям:\n${lines.join("\n")}\n\nСтатус capability не подменяет execution status: завершённость вычисляется по полному session scope.`;
    }
    return `Полный пайплайн: Моделирование\n\n1. Определение задачи → 2. Структура данных → 3. Ограничения → 4. Пул кандидатов → 5. Baseline → 6. Бэктест → 7. Тюнинг → 8. Диагностика → 9. Сравнение → 10. Выбор модели → 11. Model Card\n\nВход: checkpoint modeling_entry и трасса 30 источников. Синтетические метрики в рабочем session-контуре запрещены.`;
  })();

  const descriptionSubtitle = (() => {
    if (descriptionSection === "help")
      return "Справка — Цели модуля и результаты моделирования";
    if (!descriptionSection) return `Остановка · ${activeStage.label}`;
    if (descriptionSection === "metrics")
      return activeCandidate
        ? `Операция · Метрики и алгоритм — ${activeCandidate.model_name}`
        : "Операция · Метрики и алгоритм — Пул кандидатов";
    if (descriptionSection === "backtest")
      return `Операция · ${backtestResults[activeCandidate?.model_id ?? ""] ? "Пересчитать бэктест" : "Запустить бэктест"}${activeCandidate ? ` — ${activeCandidate.model_name}` : ""}`;
    if (descriptionSection === "scope")
      return `Операция · Execution scope${activeCandidate ? ` — ${activeCandidate.model_name}` : ""}`;
    return `Операция · Полный пайплайн${activeCandidate ? ` — ${activeCandidate.model_name}` : ""}`;
  })();

  const descriptionTestId = descriptionSection === null
    ? "description-stage"
    : descriptionSection === "help"
      ? "description-help"
      : "description-operation";

  const contextProfile = modelingContext?.profile;
  const validationStrategy = modelingContext?.validation_strategy;
  const rawDateColumn = validationStrategy?.order_column;
  const dateColumn = typeof rawDateColumn === "string" ? rawDateColumn : "—";
  const frequencyLabel = contextProfile
    ? FREQUENCY_LABELS[contextProfile.frequency] ?? contextProfile.frequency
    : "—";
  const strategyLabel = validationStrategy
    ? VALIDATION_STRATEGY_LABELS[validationStrategy.strategy] ?? validationStrategy.strategy
    : "—";
  const seasonalPeriods = contextProfile?.seasonal_periods ?? [];

  // ── Рендер ──
  return (
    <div className="flex gap-6">
      {/* ══ ЛЕВАЯ КОЛОНКА: read-only контекст + прогресс + степпер ══ */}
      <aside className="w-60 shrink-0 flex flex-col gap-3 pt-1">
        {/* Заголовок модуля + справка */}
        <div className="mb-1">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-neutral-800 truncate min-w-0">
              Моделирование
            </h2>
            <button
              onClick={() =>
                setDescriptionSection((prev) =>
                  prev === "help" ? null : "help"
                )
              }
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
            Выбор модели для прогнозирования
          </p>
        </div>

        {/* ── Канонический read-only контекст EDA → Modeling ── */}
        <div
          className="space-y-2 rounded-lg border border-neutral-200 bg-neutral-50/70 p-2.5"
          data-testid="modeling-context-summary"
        >
          <div className="flex items-center justify-between">
            <p className="text-[11px] font-semibold text-neutral-700">
              Контекст моделирования
            </p>
            <span className={`rounded px-1.5 py-0.5 text-[9px] font-medium ${
              modelingContext?.ready
                ? "bg-brand-light text-brand"
                : "bg-amber-100 text-amber-800"
            }`}>
              {modelingContext?.ready
                ? "EDA hand-off"
                : modelingContext
                  ? "есть ограничения"
                  : "ожидает EDA"}
            </span>
          </div>

          {/* Визуально сохраняем селектор, но его значение является фактом
              upstream-контракта и никогда не редактируется в Modeling. */}
          <div
            className="border-t border-neutral-200 pt-2"
            data-testid="target-column-block"
          >
            <div className="flex items-center justify-between mb-0.5">
              <label className="text-[10px] text-neutral-500 font-medium">
                Целевая колонка
              </label>
              {targetColumnLoading && (
                <Loader2
                  size={10}
                  className="animate-spin text-neutral-400"
                  data-testid="target-column-loading"
                />
              )}
            </div>
            <select
              value={targetColumn ?? ""}
              disabled
              aria-label="Целевая колонка — только чтение"
              className="w-full rounded border border-neutral-300 bg-neutral-100 px-2 py-1 text-xs text-neutral-600 disabled:cursor-not-allowed disabled:opacity-100"
              data-testid="target-column-select"
            >
              {targetColumn ? (
                <option value={targetColumn}>{targetColumn}</option>
              ) : (
                <option value="">
                  {hasDataset ? "Цель не выбрана" : "Нет активного датасета"}
                </option>
              )}
            </select>
            <p className="mt-0.5 text-[9px] text-neutral-500">
              Зафиксирована предыдущими этапами; изменение выполняется до EDA hand-off.
            </p>

            {targetColumnError && (
              <p
                className="text-[10px] text-red-600 mt-0.5"
                data-testid="target-column-error"
              >
                {targetColumnError}
              </p>
            )}
          </div>

          {modelingContext && contextProfile && validationStrategy ? (
            <>
              <dl className="grid grid-cols-2 gap-x-2 gap-y-1 border-t border-neutral-200 pt-2 text-[10px]">
                <div>
                  <dt className="text-neutral-500">Наблюдений</dt>
                  <dd className="font-semibold text-neutral-800" data-testid="context-observations">
                    {contextProfile.n_observations}
                  </dd>
                </div>
                <div>
                  <dt className="text-neutral-500">Частота</dt>
                  <dd className="font-semibold text-neutral-800" data-testid="context-frequency">
                    {frequencyLabel}
                  </dd>
                </div>
                <div>
                  <dt className="text-neutral-500">Рядов / X</dt>
                  <dd className="font-semibold text-neutral-800">
                    {contextProfile.n_series} / {contextProfile.n_exogenous}
                  </dd>
                </div>
                <div>
                  <dt className="text-neutral-500">Сезонность</dt>
                  <dd className="font-semibold text-neutral-800">
                    {contextProfile.has_seasonality
                      ? seasonalPeriods.length > 0
                        ? `Да · ${seasonalPeriods.join(", ")}`
                        : "Да"
                      : "Нет"}
                  </dd>
                </div>
                <div>
                  <dt className="text-neutral-500">Регулярность</dt>
                  <dd className="font-semibold text-neutral-800">
                    {contextProfile.is_regular ? "Регулярный" : "Нерегулярный"}
                  </dd>
                </div>
                <div>
                  <dt className="text-neutral-500">Колонка времени</dt>
                  <dd className="truncate font-semibold text-neutral-800" data-testid="context-date-column" title={dateColumn}>
                    {dateColumn}
                  </dd>
                </div>
              </dl>

              <div className="rounded border border-neutral-200 bg-white px-2 py-1.5 text-[9px] text-neutral-600" data-testid="context-validation-plan">
                <span className="font-semibold text-neutral-800">{strategyLabel}</span>
                {` · H=${validationStrategy.horizon} · folds=${validationStrategy.n_splits} · gap=${validationStrategy.gap}`}
              </div>

              <div className="text-[9px] text-neutral-500" data-testid="context-checkpoint">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-neutral-700">modeling_entry</span>
                  <span>{modelingContext.checkpoint.source_stage}</span>
                </div>
                <p className="truncate font-mono" title={modelingContext.fingerprint}>
                  SHA {modelingContext.fingerprint.slice(0, 12)}…
                </p>
              </div>

              {!modelingContext.ready && (
                <p className="rounded border border-amber-200 bg-amber-50 px-2 py-1.5 text-[9px] text-amber-800" data-testid="context-restrictions">
                  EDA hand-off зафиксирован, но пул моделей заблокирован ограничениями контекста.
                </p>
              )}
            </>
          ) : (
            <p className="rounded border border-amber-200 bg-amber-50 px-2 py-1.5 text-[9px] text-amber-800" data-testid="context-unavailable">
              {modelingContextError || "Подтвердите финальный паспорт «Для моделирования» на вкладке EDA."}
            </p>
          )}

          {/* Кнопка «Загрузить пул» */}
          <Button
            onClick={fetchCandidates}
            disabled={isLoading || modelingContext?.ready !== true}
            className="w-full text-xs"
            data-testid="fetch-candidates-btn"
          >
            {isLoading ? (
              <span className="flex items-center justify-center gap-1">
                <Loader2 size={12} className="animate-spin" /> Загрузка…
              </span>
            ) : (
              <span className="flex items-center justify-center gap-1">
                <RefreshCw size={12} /> Загрузить пул
              </span>
            )}
          </Button>
        </div>

        {/* Прогресс пайплайна */}
        <div className="flex items-center gap-2">
          <p className="text-[11px] text-neutral-500 tabular-nums">
            {doneStages}/{dynamicStages.length}
          </p>
          <div className="flex-1 bg-neutral-200 rounded-full h-1.5">
            <div
              className="bg-brand h-1.5 rounded-full transition-all"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>

        {/* Степпер: 11 стадий пайплайна */}
        <div className="flex flex-col gap-1.5">
          {dynamicStages.map((stage) => (
            <button
              key={stage.id}
              onClick={() => {
                setActiveStageId(stage.id);
                setDescriptionSection(null);
              }}
              className={`w-full flex items-center justify-between rounded-md border px-3 py-2 text-xs transition-colors ${
                stage.id === activeStageId
                  ? "bg-brand text-white border-brand"
                  : stage.status === "done"
                  ? "bg-green-50 border-green-200 text-green-800"
                  : "bg-white border-neutral-200 hover:bg-neutral-50 text-neutral-800"
              }`}
            >
              <span className="truncate">{stage.label}</span>
              <span className="ml-2 shrink-0">
                <StatusIcon
                  status={
                    stage.status === "done"
                      ? "done"
                      : stage.status === "active"
                      ? "warning"
                      : "pending"
                  }
                />
              </span>
            </button>
          ))}
        </div>
      </aside>

      {/* ══ ЦЕНТРАЛЬНАЯ КОЛОНКА: описание + таблица + метрики ══ */}
      <section className="flex-1 min-w-0">
        {/* Блок «Описание» */}
        <div className="mb-5">
          <h3 className="font-semibold mb-1">Описание</h3>
          <div className="mb-2 flex min-h-5 items-start justify-between gap-3">
            <p
              className="text-xs text-neutral-500"
              data-testid={descriptionTestId}
            >
              {descriptionSubtitle}
            </p>
            {descriptionSection !== null && (
              <button
                type="button"
                onClick={() => setDescriptionSection(null)}
                className="shrink-0 text-[11px] font-medium text-brand underline decoration-brand/40 underline-offset-2 hover:decoration-brand"
                aria-label={`Вернуться к описанию остановки «${activeStage.label}»`}
              >
                К описанию остановки
              </button>
            )}
          </div>
          <div className="relative min-h-[220px]">
            <div
              ref={descRef}
              className={`rounded-lg border border-neutral-200 px-4 py-3 overflow-y-auto text-sm text-neutral-600 whitespace-pre-wrap ${
                descriptionExpanded
                  ? "absolute top-0 left-0 right-0 z-20 max-h-[calc(100vh-180px)] shadow-lg border-brand/30 min-h-[220px] bg-brand-light"
                  : "max-h-[220px] min-h-[220px] bg-brand-light/50"
              }`}
            >
              {descriptionContent}
              {descriptionExpanded && (
                <div className="sticky bottom-0 flex justify-center py-1 bg-brand-light rounded-b-lg">
                  <button
                    onClick={() => setDescriptionExpanded(false)}
                    className="flex items-center justify-center w-8 h-5 rounded-t bg-brand/10 hover:bg-brand/20 text-brand transition-colors"
                    aria-label="Свернуть описание"
                    data-testid="desc-collapse-btn"
                  >
                    <ChevronUp size={14} />
                  </button>
                </div>
              )}
            </div>
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
          </div>
        </div>

        {(["problem_definition", "data_structure", "constraint_mapping"].includes(activeStageId)) && (
          modelingContext ? (
            <ModelingTraceabilityOverview context={modelingContext} />
          ) : (
            <div className="flex h-[468px] items-center justify-center rounded-lg border border-amber-200 bg-amber-50 p-6 text-center text-sm text-amber-800" data-testid="modeling-context-gate">
              {modelingContextError || "Подтвердите финальный паспорт «Для моделирования» на вкладке EDA."}
            </div>
          )
        )}

        {(["tuning", "diagnostics", "comparison", "selection", "model_card"].includes(activeStageId)) && (
          <ModelingWorkflowOverview
            stageId={activeStageId}
            modelIds={Object.keys(backtestResults)}
            modelActions={Object.fromEntries(
              catalog.map((candidate) => [candidate.model_id, candidate.available_actions as ModelAction[]]),
            )}
            tuningSkippedModelIds={Object.keys(executionScope?.tuning_skips ?? {})}
            tuningCompletedModelIds={executionScope?.completed_tuning_model_ids ?? []}
            tuningPendingModelIds={executionScope?.pending_tuning_model_ids}
            onStageComplete={() => fetchModelingState()}
            onBacktestPromoted={(promoted) => setBacktestResults((previous) => ({
              ...previous,
              [promoted.model_id]: promoted,
            }))}
          />
        )}

        {(["candidate_generation", "baseline_estimation", "backtest"].includes(activeStageId)) && (<>

        {/* ── Ошибка API ── */}
        {error && (
          <div
            className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
            data-testid="api-error"
          >
            Ошибка: {error}
          </div>
        )}

        {executionScope && (
          <div className="mb-3 rounded border border-blue-200 bg-blue-50 px-3 py-2 text-[10px] text-blue-900" data-testid="execution-scope-summary">
            <b>Execution scope:</b> {executionScope.completed_backtest_model_ids.length}/{executionScope.included_backtest_model_ids.length} backtests · {executionScope.pending_backtest_model_ids.length} ожидают · {Object.keys(executionScope.backtest_exclusions).length} исключены с обоснованием.
          </div>
        )}

        {/* ── Фильтр по уровню применимости ── */}
        {hasFetched && (
          <div className="mb-3 space-y-2">
            <div className="flex items-center gap-2">
              <Filter size={14} className="text-neutral-500" />
              <span className="text-xs text-neutral-500">Исполнение:</span>
              <button
                onClick={() => setAvailabilityFilter("runnable")}
                className={`rounded border px-2 py-1 text-xs ${availabilityFilter === "runnable" ? "border-brand bg-brand text-white" : "border-neutral-200 bg-white text-neutral-700"}`}
              >
                Доступные ({candidates.filter((item) => item.available_actions.includes("backtest")).length})
              </button>
              <button
                onClick={() => setAvailabilityFilter("all")}
                className={`rounded border px-2 py-1 text-xs ${availabilityFilter === "all" ? "border-brand bg-brand text-white" : "border-neutral-200 bg-white text-neutral-700"}`}
              >
                Весь каталог ({catalog.length})
              </button>
            </div>
            <div className="flex items-center gap-2">
              <span className="ml-6 text-xs text-neutral-500">Применимость:</span>
              {[
              { value: "all", label: "Все" },
              { value: "RECOMMENDED", label: "Рекоменд." },
              {
                value: "CONDITIONALLY_APPLICABLE",
                label: "Условно",
              },
              {
                value: "NOT_RECOMMENDED",
                label: "Не реком.",
              },
              ].map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setLevelFilter(opt.value)}
                  className={`text-xs px-2 py-1 rounded border transition-colors ${
                    levelFilter === opt.value
                      ? "bg-brand text-white border-brand"
                      : "bg-white border-neutral-200 text-neutral-700 hover:bg-neutral-50"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* ── Таблица пула кандидатов по семействам ── */}
        {hasFetched && (
          <div data-testid="candidate-pool">
            {candidatesByFamily.map((fam) => (
              <div key={fam.id} className="mb-4">
                {/* Заголовок семейства */}
                <button
                  onClick={() =>
                    setActiveFamilyId(
                      activeFamilyId === fam.id ? null : fam.id
                    )
                  }
                  className="w-full flex items-center justify-between rounded border border-neutral-300 bg-white px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-brand"
                  data-testid={`family-header-${fam.id}`}
                >
                  <h4 className="text-sm font-semibold text-neutral-800">
                    {fam.name}
                    <span className="ml-2 text-xs font-normal text-neutral-500">
                      ({fam.models.length})
                    </span>
                  </h4>
                  <ChevronDown
                    size={14}
                    strokeWidth={2.5}
                    className={`text-black transition-transform ${
                      activeFamilyId === fam.id ? "rotate-180" : ""
                    }`}
                  />
                </button>

                {/* Модели семейства */}
                <div
                  className={`space-y-1.5 ${
                    activeFamilyId === fam.id ? "" : "hidden"
                  }`}
                  data-testid={`family-models-${fam.id}`}
                >
                  {fam.models.map((c) => {
                    const badge = APPLICABILITY_BADGE[c.level as ApplicabilityLevel];
                    return (
                      <div
                        key={c.model_id}
                        onClick={() => {
                          setActiveCandidateId(c.model_id);
                          setDescriptionSection(null);
                        }}
                        className={`flex items-center justify-between rounded-md border px-3 py-2 text-sm cursor-pointer transition-colors ${
                          c.model_id === activeCandidateId
                            ? "border-brand bg-brand-light/50"
                            : "border-neutral-200 bg-white hover:bg-neutral-50"
                        }`}
                        data-testid={`candidate-${c.model_id}`}
                      >
                        <span className="truncate text-neutral-800">
                          {c.model_name}
                        </span>
                        <span className="ml-2 flex shrink-0 items-center gap-1">
                          <span
                            className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${badge.bg} ${badge.text} ${badge.border}`}
                            data-testid={`badge-${c.model_id}`}
                          >
                            {APPLICABILITY_LABEL[c.level as ApplicabilityLevel]}
                          </span>
                          <span
                            className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${c.available_actions.includes("backtest") ? "border-green-200 bg-green-50 text-green-700" : "border-neutral-200 bg-neutral-100 text-neutral-600"}`}
                            data-testid={`execution-badge-${c.model_id}`}
                          >
                            {c.available_actions.includes("backtest") ? "Готово" : c.platform_status === "catalog_only" ? "В каталоге" : "Ограничено"}
                          </span>
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}

            {filteredCandidates.length === 0 && !isLoading && (
              <p className="text-sm text-neutral-500 text-center py-8">
                Нет моделей с выбранным фильтром применимости.
              </p>
            )}
          </div>
        )}

        {/* ── Метрики-сводка ── */}
        {statistics && (
          <div className="grid grid-cols-4 gap-3 mt-4" data-testid="statistics-grid">
            <Metric label="Кандидатов" value={String(statistics.total_candidates)} />
            <Metric
              label="Доступно"
              value={String(statistics.runnable_candidates ?? candidates.filter((item) => item.available_actions.includes("backtest")).length)}
            />
            <Metric
              label="Только каталог"
              value={String(statistics.catalog_only_candidates ?? catalog.filter((item) => item.platform_status === "catalog_only").length)}
            />
            <Metric
              label="Всего в спецификации"
              value={String(statistics.total_models_in_spec)}
            />
          </div>
        )}

        {/* ── Сравнение бэктестов (Recharts) ──
            Реальные данные -- backtestResults, накопленный компонентом
            при клике «Запустить бэктест» (справа). Не новый запрос к API.
            Показывается всегда (не только при statistics), т.к. не зависит
            от пула кандидатов -- от факта хотя бы одного бэктеста. */}
        <div className="mt-4" data-testid="backtest-comparison-panel">
          {isApplicabilityBootstrapping ? (
            <>
              <h3 className="mb-1 text-sm font-semibold text-neutral-800">
                Загружаю доступные модели, минутку...
              </h3>
              <div
                role="status"
                className="flex h-[198px] items-center justify-center gap-2 rounded-lg border border-neutral-200 bg-neutral-50 text-sm text-neutral-500"
              >
                <Loader2 size={16} className="animate-spin" aria-hidden="true" />
                Движок применимости анализирует профиль ряда
              </div>
            </>
          ) : (
            <>
              <h3 className="mb-1 text-sm font-semibold text-neutral-800">
                Сравнение бэктестов
              </h3>
              <BacktestComparisonChart backtestResults={backtestResults} />
            </>
          )}
        </div>

        {activeCandidateId && backtestResults[activeCandidateId] && (
          <div className="mt-4" data-testid="active-oof-backtest">
            <h3 className="mb-1 text-sm font-semibold text-neutral-800">
              Out-of-fold: {backtestResults[activeCandidateId].model_name}
            </h3>
            <BacktestOofChart result={backtestResults[activeCandidateId]} />
          </div>
        )}

        {/* ── Спецификация ── */}
        {specVersion && (
          <p className="text-[11px] text-neutral-400 mt-2">
            Спецификация v{specVersion}
          </p>
        )}
        </>)}
      </section>

      {/* ══ ПРАВАЯ КОЛОНКА: панель управления ══ */}
      <aside className="w-80 shrink-0 pt-1">
        <div className="mb-4">
          <h2 className="text-lg font-semibold text-neutral-800">
            Панель управления
          </h2>
        </div>
        <div className="h-[468px] overflow-y-auto pr-2 space-y-5 feed-scroll">
          {/* Карточка активного кандидата */}
          {activeCandidate && (
            <article
              className="pb-5 border-b border-neutral-100 border-l-4 border-l-brand pl-3"
              data-testid="active-candidate-detail"
            >
              <h3 className="font-semibold mb-1">
                {activeCandidate.model_name}
              </h3>

              <p className="text-sm text-neutral-600 mb-2">
                Семейство: {activeCandidate.family_id}
              </p>

              {/* Бейдж */}
              {(() => {
                const badge = APPLICABILITY_BADGE[
                  activeCandidate.level as ApplicabilityLevel
                ];
                return (
                  <p
                    className={`text-sm rounded px-3 py-2 mb-2 border ${badge.bg} ${badge.text} ${badge.border}`}
                  >
                    {APPLICABILITY_LABEL[
                      activeCandidate.level as ApplicabilityLevel
                    ]}
                  </p>
                );
              })()}

              <p
                className={`mb-2 rounded border px-3 py-2 text-xs ${activeCandidate.available_actions.includes("backtest") ? "border-green-200 bg-green-50 text-green-700" : "border-neutral-200 bg-neutral-50 text-neutral-700"}`}
                data-testid="candidate-runtime-status"
              >
                {activeCandidate.available_actions.includes("backtest")
                  ? "Production backtest подключён"
                  : activeCandidate.platform_status === "catalog_only"
                    ? "Метод есть в методологическом каталоге, но ещё не реализован в production"
                    : "Production-модель ограничена для текущего ряда"}
              </p>

              {/* Сообщение движка */}
              {activeCandidate.message && (
                <p className="text-xs text-neutral-500 mb-2">
                  {activeCandidate.message}
                </p>
              )}

              {/* Правило */}
              {activeCandidate.rule_id && (
                <p className="text-xs text-neutral-400 mb-2">
                  Правило: {activeCandidate.rule_id}
                </p>
              )}

              {/* Кнопка «Метрики и алгоритм» */}
              <button
                onClick={() => {
                  setActiveCandidateId(activeCandidate.model_id);
                  setDescriptionSection("metrics");
                }}
                aria-pressed={descriptionSection === "metrics"}
                className={`w-full mb-2 rounded px-3 py-2 text-sm text-left font-medium transition-colors ${
                  descriptionSection === "metrics"
                    ? "bg-brand text-white"
                    : "bg-brand-light hover:bg-brand-light/80 text-neutral-800"
                }`}
              >
                Метрики и алгоритм
              </button>

              {/* Кнопка «Полный пайплайн» */}
              <button
                onClick={() => {
                  setActiveCandidateId(activeCandidate.model_id);
                  setDescriptionSection("pipeline");
                }}
                aria-pressed={descriptionSection === "pipeline"}
                className={`w-full mb-3 rounded px-3 py-2 text-sm text-left font-medium transition-colors ${
                  descriptionSection === "pipeline"
                    ? "bg-brand text-white"
                    : "bg-brand-light hover:bg-brand-light/80 text-neutral-800"
                }`}
              >
                Полный пайплайн
              </button>

              {/* Кнопка / Результат «Запустить бэктест» */}
              {!activeCandidate.available_actions.includes("backtest") ? (
                <div
                  className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800"
                  data-testid="backtest-unavailable"
                >
                  <p className="font-medium">Бэктест недоступен</p>
                  <p className="mt-1">{activeCandidate.blocking_reason}</p>
                </div>
              ) : backtestResults[activeCandidate.model_id] ? (
                <div
                  className="mt-2 p-3 rounded-lg border border-brand/30 bg-brand-light/50 space-y-2"
                  data-testid="backtest-result"
                >
                  <p className="text-[11px] font-semibold text-brand">
                    Бэктест завершён
                  </p>
                  {(() => {
                    const bt = backtestResults[activeCandidate.model_id];
                    const m = bt.metrics;
                    return (
                      <>
                        <span
                          className="inline-flex items-center rounded-full border border-green-200 bg-green-50 px-2 py-0.5 text-[10px] font-medium text-green-700"
                          data-testid="data-source-badge"
                        >
                          Реальные данные
                        </span>
                        <div className="grid grid-cols-2 gap-2 text-[11px]">
                          <div>
                            <span className="text-neutral-500">MAE</span>
                            <p className="font-mono font-semibold text-neutral-800">
                              {m.mae.toFixed(2)}
                            </p>
                          </div>
                          <div>
                            <span className="text-neutral-500">RMSE</span>
                            <p className="font-mono font-semibold text-neutral-800">
                              {m.rmse.toFixed(2)}
                            </p>
                          </div>
                          <div>
                            <span className="text-neutral-500">MAPE</span>
                            <p className="font-mono font-semibold text-neutral-800">
                              {m.mape == null ? "—" : `${m.mape.toFixed(1)}%`}
                            </p>
                          </div>
                          <div>
                            <span className="text-neutral-500">MASE</span>
                            <p className="font-mono font-semibold text-neutral-800">
                              {m.mase == null ? "—" : m.mase.toFixed(2)}
                            </p>
                          </div>
                        </div>
                        <div
                          className="flex items-center justify-between text-[10px] text-neutral-500 pt-1 border-t border-neutral-200"
                          data-testid="backtest-fold-summary"
                        >
                          <span>{bt.strategy ?? "single"} · {bt.n_folds ?? 1} folds · h={bt.horizon ?? bt.n_test}</span>
                          <span>
                            train(last) {bt.n_train} · OOF {bt.n_test}
                          </span>
                        </div>
                        {(bt.warnings ?? []).map((warning) => (
                          <p key={warning} className="text-[10px] text-amber-700">{warning}</p>
                        ))}
                        <Button
                          onClick={() => {
                            setDescriptionSection("backtest");
                            void runBacktest(activeCandidate.model_id);
                          }}
                          disabled={backtestLoading}
                          className="w-full text-xs"
                          data-testid="run-backtest-btn"
                        >
                          {backtestLoading ? "Расчёт…" : "Пересчитать бэктест"}
                        </Button>
                      </>
                    );
                  })()}
                </div>
              ) : (
                <Button
                  onClick={() => {
                    setDescriptionSection("backtest");
                    void runBacktest(activeCandidate.model_id);
                  }}
                  disabled={backtestLoading}
                  className="w-full text-xs"
                  data-testid="run-backtest-btn"
                >
                  {backtestLoading ? (
                    <span className="flex items-center justify-center gap-1">
                      <Loader2 size={12} className="animate-spin" /> Расчёт…
                    </span>
                  ) : (
                    "Запустить бэктест"
                  )}
                </Button>
              )}

              {activeCandidate.family_id !== "baselines"
                && activeCandidate.available_actions.includes("backtest")
                && !backtestResults[activeCandidate.model_id]
                && (executionScope?.backtest_exclusions[activeCandidate.model_id] ? (
                  <div className="mt-2 rounded border border-amber-200 bg-amber-50 p-2 text-[10px] text-amber-800" data-testid="backtest-excluded">
                    <p>Исключена из текущего comparison: {executionScope.backtest_exclusions[activeCandidate.model_id].reason}</p>
                    <button
                      className="mt-1 underline"
                      onClick={() => {
                        setDescriptionSection("scope");
                        void decideBacktestScope(activeCandidate.model_id, "include");
                      }}
                    >
                      Вернуть в execution scope
                    </button>
                  </div>
                ) : (
                  <div className="mt-2 space-y-1 rounded border border-neutral-200 p-2" data-testid="backtest-exclusion-control">
                    <input className="w-full rounded border border-neutral-300 px-2 py-1 text-[10px]" value={exclusionReason} onChange={(event) => setExclusionReason(event.target.value)} placeholder="Причина осознанного исключения" />
                    <button
                      className="text-[10px] text-amber-700 underline disabled:text-neutral-300"
                      disabled={exclusionReason.trim().length < 3}
                      onClick={() => {
                        setDescriptionSection("scope");
                        void decideBacktestScope(activeCandidate.model_id, "exclude");
                      }}
                    >
                      Исключить из comparison
                    </button>
                  </div>
                ))}

              {/* Ошибка бэктеста */}
              {backtestError && (
                <p className="text-xs text-red-600 mt-1" data-testid="backtest-error">
                  {backtestError}
                </p>
              )}
            </article>
          )}

          {/* Сводка по семействам (если нет активного кандидата) */}
          {!activeCandidate &&
            candidatesByFamily.map((fam) => (
              <article
                key={fam.id}
                className="pb-5 border-b border-neutral-100"
              >
                <h3 className="font-semibold mb-1">{fam.name}</h3>
                <p className="text-sm text-neutral-600 mb-2">
                  {fam.models.length} моделей-кандидатов
                </p>
                {/* Мини-бейджи */}
                <div className="flex flex-wrap gap-1">
                  {fam.models.slice(0, 5).map((c) => {
                    const badge = APPLICABILITY_BADGE[
                      c.level as ApplicabilityLevel
                    ];
                    return (
                      <span
                        key={c.model_id}
                        className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[9px] font-medium ${badge.bg} ${badge.text} ${badge.border}`}
                      >
                        {c.model_name}
                      </span>
                    );
                  })}
                  {fam.models.length > 5 && (
                    <span className="text-[9px] text-neutral-400">
                      +{fam.models.length - 5}
                    </span>
                  )}
                </div>
              </article>
            ))}

          {/* Placeholder при отсутствии данных (нет ошибки) */}
          {!hasFetched && !isLoading && !error && (
            <article className="pb-5">
              <h3 className="font-semibold mb-1">Пул кандидатов</h3>
              <p className="text-sm text-neutral-500">
                Настройте профиль данных слева и нажмите «Загрузить пул» для
                получения списка моделей-кандидатов с оценкой применимости.
              </p>
            </article>
          )}

          {/* Fallback при ошибке API — показываем инструкцию в правой колонке */}
          {error && !isLoading && (
            <article className="pb-5">
              <h3 className="font-semibold mb-1">Пул кандидатов</h3>
              <p className="text-sm text-red-600 mb-2">
                Не удалось загрузить пул: {error}
              </p>
              <p className="text-sm text-neutral-500">
                Убедитесь, что API-сервер запущен (переменная
                <code className="text-xs bg-neutral-100 px-1 rounded">
                          API_URL
                </code>
                на Vercel) и повторите попытку кнопкой «Загрузить пул».
              </p>
            </article>
          )}

          {/* Loading */}
          {isLoading && (
            <article className="pb-5">
              <h3 className="font-semibold mb-1">Загрузка…</h3>
              <p className="text-sm text-neutral-500 flex items-center gap-2">
                <Loader2 size={14} className="animate-spin" />
                Движок применимости оценивает 24 модели…
              </p>
            </article>
          )}
        </div>
      </aside>
    </div>
  );
}
