"use client";

// packages/ui/components/TsAnalysisModeling.tsx
//
// ОБЩИЙ компонент фичи «Моделирование» — используется И embedded-,
// И standalone-приложением. 3-колоночный лейаут (как TsAnalysisEDA).
//
// Компоновка:
//   [Левая ~240px]       [Центр flex-1]          [Правая ~320px]
//   Моделирование         Описание                Семейство: ...
//   ▼ Профиль данных     [таблица кандидатов]    модели с бейджами
//   4/11 ░░░             [метрики-сводка]        [Метрики и алгоритм]
//   ┌─Определение──○─┐   [фильтр по уровню]     [Полный пайплайн]
//   ├─Структура───○─┤                           [Запустить бэктест]
//   └──────────────┘

import {
  useState,
  useRef,
  useEffect,
  useCallback,
  type ChangeEvent,
} from "react";
import { ChevronDown, ChevronUp, RefreshCw, Filter, Loader2 } from "lucide-react";
import { Button } from "./Button";
import { Metric } from "./Metric";
import { StatusIcon, type CheckStatus } from "./StatusIcon";
import {
  type DataProfile,
  type ModelCandidate,
  type CandidatesResponse,
  type ApplicabilityLevel,
  APPLICABILITY_LABEL,
  APPLICABILITY_BADGE,
  MODEL_FAMILIES,
  PIPELINE_STAGES,
  DEFAULT_PROFILE,
  DOMAINS,
  FREQUENCIES,
} from "../lib/modeling";
import { useAppShell } from "../context/AppShellContext";

// ── Константы ──────────────────────────────────────────────────

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Справка по целям модуля «Моделирование» ────────────────────

const MODELING_HELP = `Цели модуля "Моделирование"

Моделирование — это одноразовый процесс выбора лучшей модели для данного временного ряда. Это НЕ прогнозирование: моделирование выбирает модель, прогнозирование генерирует прогнозы.

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
• Нейросетевые (5) — LSTM, DeepAR, TFT, N-BEATS, WaveNet

11-стадийный пайплайн:
1. Определение задачи → 2. Структура данных → 3. Ограничения
→ 4. Пул кандидатов → 5. Baseline → 6. Бэктест → 7. Тюнинг
→ 8. Диагностика → 9. Сравнение → 10. Выбор модели → 11. Model Card

Метрики ранжирования: MAE(0.35) + RMSE(0.25) + MAPE(0.20) + MASE(0.20). R² исключён из ранжирования.`;

// ── Компонент ──────────────────────────────────────────────────

export function TsAnalysisModeling() {
  // ── Контекст: активный датасет ──
  const { activeDataset } = useAppShell();

  // ── Состояние ──
  const [profile, setProfile] = useState<DataProfile>(DEFAULT_PROFILE);
  const [candidates, setCandidates] = useState<ModelCandidate[]>([]);
  const [statistics, setStatistics] = useState<{
    total_candidates: number;
    by_level: Record<string, number>;
    total_models_in_spec: number;
  } | null>(null);
  const [specVersion, setSpecVersion] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasFetched, setHasFetched] = useState(false);

  // UI-состояние
  const [activeStageId, setActiveStageId] = useState("candidate_pool");
  const [activeFamilyId, setActiveFamilyId] = useState<string | null>(null);
  const [activeCandidateId, setActiveCandidateId] = useState<string | null>(
    null
  );
  const [levelFilter, setLevelFilter] = useState<string>("all");
  const [descriptionSection, setDescriptionSection] = useState<
    "metrics" | "pipeline" | "help" | null
  >(null);
  const [descriptionExpanded, setDescriptionExpanded] = useState(false);
  const [hasOverflow, setHasOverflow] = useState(false);
  const descRef = useRef<HTMLDivElement>(null);

  // ── Автозаполнение профиля из activeDataset ──
  useEffect(() => {
    if (activeDataset) {
      setProfile((prev) => ({
        ...prev,
        n_observations: activeDataset.rows || prev.n_observations,
      }));
    }
  }, [activeDataset]);

  // ── Fetch кандидатов ──
  const fetchCandidates = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/v1/models/candidates`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          profile,
          min_level: "CONDITIONALLY_APPLICABLE",
        }),
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(
          errBody.detail || `HTTP ${res.status}: ${res.statusText}`
        );
      }
      const data: CandidatesResponse = await res.json();
      setCandidates(data.candidates);
      setStatistics(data.statistics);
      setSpecVersion(data.spec_version);
      setHasFetched(true);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Неизвестная ошибка запроса"
      );
    } finally {
      setIsLoading(false);
    }
  }, [profile]);

  // ── Авто-фetch при маунте ──
  useEffect(() => {
    fetchCandidates();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Collapse/Expand description ──
  useEffect(() => {
    setDescriptionExpanded(false);
  }, [descriptionSection]);

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
  }, [descriptionSection, candidates]);

  // ── Обработчики профиля ──
  const handleProfileChange = useCallback(
    (field: keyof DataProfile, value: number | string | boolean | number[]) => {
      setProfile((prev) => ({ ...prev, [field]: value }));
    },
    []
  );

  // ── Фильтрация и группировка ──
  const filteredCandidates = candidates.filter((c) => {
    if (levelFilter !== "all" && c.level !== levelFilter) return false;
    return true;
  });

  // Группировка по семействам
  const candidatesByFamily = MODEL_FAMILIES.map((fam) => ({
    ...fam,
    models: filteredCandidates.filter((c) => c.family_id === fam.id),
  })).filter((fam) => fam.models.length > 0);

  // Активный кандидат
  const activeCandidate = candidates.find(
    (c) => c.model_id === activeCandidateId
  );

  // Пайплайн — прогресс
  const doneStages = PIPELINE_STAGES.filter(
    (s) => s.status === "done"
  ).length;
  const progressPct = Math.round(
    (doneStages / PIPELINE_STAGES.length) * 100
  );

  // Описание для центрального поля
  const descriptionContent = (() => {
    if (descriptionSection === "help") return MODELING_HELP;
    if (!descriptionSection) return null;
    if (descriptionSection === "metrics") {
      if (activeCandidate) {
        return `Метрики и алгоритм: ${activeCandidate.model_name}\n\nСемейство: ${activeCandidate.family_id}\nУровень применимости: ${APPLICABILITY_LABEL[activeCandidate.level as ApplicabilityLevel]}\n${activeCandidate.rule_id ? `Правило: ${activeCandidate.rule_id}` : ""}\n${activeCandidate.message}\n\nАлгоритм: движок применимости оценивает 23 правила (5 forbidden, 6 discouraged, 5 conditional, 7 preferred) и определяет наивысший уровень применимости модели для данного профиля данных.`;
      }
      return `Метрики и алгоритм: Пул кандидатов\n\nАлгоритм формирования пула:\n1. Применить 23 правила применимости ко всем 24 моделям\n2. Отфильтровать по минимальному уровню (≥ CONDITIONALLY_APPLICABLE)\n3. Baseline-модели включаются всегда\n4. Сортировка по рангу уровня (RECOMMENDED → CONDITIONALLY_APPLICABLE → NOT_RECOMMENDED)`;
    }
    return `Полный пайплайн: Моделирование\n\n1. Определение задачи → 2. Структура данных → 3. Ограничения → 4. Пул кандидатов → 5. Baseline → 6. Бэктест → 7. Тюнинг → 8. Диагностика → 9. Сравнение → 10. Выбор модели → 11. Model Card\n\nТекущая стадия: Пул кандидатов — движок применимости определил ${candidates.length} моделей-кандидатов из ${statistics?.total_models_in_spec || 24} моделей спецификации.`;
  })();

  const descriptionSubtitle = (() => {
    if (descriptionSection === "help")
      return "Справка — Цели модуля и результаты моделирования";
    if (!descriptionSection) return "Настройте профиль данных и нажмите «Загрузить пул»";
    if (descriptionSection === "metrics")
      return activeCandidate
        ? `Метрики и алгоритм — ${activeCandidate.model_name}`
        : "Метрики и алгоритм — Пул кандидатов";
    return "Полный пайплайн — Моделирование";
  })();

  // ── Рендер ──
  return (
    <div className="flex gap-6">
      {/* ══ ЛЕВАЯ КОЛОНКА: профиль + прогресс + степпер ══ */}
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

        {/* ── Компактная форма профиля данных ── */}
        <div className="space-y-2">
          <p className="text-[11px] text-neutral-500 font-medium">
            Профиль данных
          </p>

          {/* n_observations */}
          <div>
            <label className="text-[10px] text-neutral-500 block mb-0.5">
              Наблюдений
            </label>
            <input
              type="number"
              min={1}
              value={profile.n_observations}
              onChange={(e: ChangeEvent<HTMLInputElement>) =>
                handleProfileChange(
                  "n_observations",
                  Math.max(1, Number(e.target.value))
                )
              }
              className="w-full rounded border border-neutral-300 bg-white px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-brand"
              data-testid="profile-n-observations"
            />
          </div>

          {/* n_series */}
          <div>
            <label className="text-[10px] text-neutral-500 block mb-0.5">
              Рядов
            </label>
            <input
              type="number"
              min={1}
              value={profile.n_series}
              onChange={(e: ChangeEvent<HTMLInputElement>) =>
                handleProfileChange(
                  "n_series",
                  Math.max(1, Number(e.target.value))
                )
              }
              className="w-full rounded border border-neutral-300 bg-white px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-brand"
              data-testid="profile-n-series"
            />
          </div>

          {/* frequency */}
          <div>
            <label className="text-[10px] text-neutral-500 block mb-0.5">
              Частота
            </label>
            <select
              value={profile.frequency}
              onChange={(e) => handleProfileChange("frequency", e.target.value)}
              className="w-full rounded border border-neutral-300 bg-white px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-brand"
              data-testid="profile-frequency"
            >
              {FREQUENCIES.map((f) => (
                <option key={f.value} value={f.value}>
                  {f.label}
                </option>
              ))}
            </select>
          </div>

          {/* domain */}
          <div>
            <label className="text-[10px] text-neutral-500 block mb-0.5">
              Предметная область
            </label>
            <select
              value={profile.domain}
              onChange={(e) => handleProfileChange("domain", e.target.value)}
              className="w-full rounded border border-neutral-300 bg-white px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-brand"
              data-testid="profile-domain"
            >
              {DOMAINS.map((d) => (
                <option key={d.value} value={d.value}>
                  {d.label}
                </option>
              ))}
            </select>
          </div>

          {/* Тогглы в одну строку */}
          <div className="flex gap-3">
            <label className="flex items-center gap-1 text-[10px] text-neutral-600">
              <input
                type="checkbox"
                checked={profile.has_seasonality}
                onChange={(e) =>
                  handleProfileChange("has_seasonality", e.target.checked)
                }
                className="rounded border-neutral-300"
              />
              Сезонность
            </label>
            <label className="flex items-center gap-1 text-[10px] text-neutral-600">
              <input
                type="checkbox"
                checked={profile.gpu_available}
                onChange={(e) =>
                  handleProfileChange("gpu_available", e.target.checked)
                }
                className="rounded border-neutral-300"
              />
              GPU
            </label>
          </div>

          {/* Кнопка «Загрузить пул» */}
          <Button
            onClick={fetchCandidates}
            disabled={isLoading}
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
            {doneStages}/{PIPELINE_STAGES.length}
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
          {PIPELINE_STAGES.map((stage) => (
            <button
              key={stage.id}
              onClick={() => {
                setActiveStageId(stage.id);
                if (descriptionSection === "help") setDescriptionSection(null);
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
          <p className="text-xs text-neutral-500 mb-2">
            {descriptionSubtitle}
          </p>
          <div className="relative min-h-[220px]">
            <div
              ref={descRef}
              className={`rounded-lg border border-neutral-200 px-4 py-3 overflow-y-auto text-sm text-neutral-600 whitespace-pre-wrap ${
                descriptionExpanded
                  ? "absolute top-0 left-0 right-0 z-20 max-h-[calc(100vh-180px)] shadow-lg border-brand/30 min-h-[220px] bg-brand-light"
                  : "max-h-[220px] min-h-[220px] bg-brand-light/50"
              }`}
            >
              {descriptionContent || (
                <span className="text-neutral-400 italic">
                  Нажмите «Метрики и алгоритм», «Полный пайплайн» или «Справка»
                </span>
              )}
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

        {/* ── Ошибка API ── */}
        {error && (
          <div
            className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
            data-testid="api-error"
          >
            Ошибка: {error}
          </div>
        )}

        {/* ── Фильтр по уровню применимости ── */}
        {hasFetched && (
          <div className="flex items-center gap-2 mb-3">
            <Filter size={14} className="text-neutral-500" />
            <span className="text-xs text-neutral-500">Уровень:</span>
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
                  className="w-full flex items-center justify-between mb-2"
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
                    className={`text-neutral-400 transition-transform ${
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
                        onClick={() => setActiveCandidateId(c.model_id)}
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
                        {/* Бейдж применимости */}
                        <span
                          className={`ml-2 shrink-0 inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${badge.bg} ${badge.text} ${badge.border}`}
                          data-testid={`badge-${c.model_id}`}
                        >
                          {APPLICABILITY_LABEL[c.level as ApplicabilityLevel]}
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
              label="Рекомендовано"
              value={String(statistics.by_level.RECOMMENDED || 0)}
            />
            <Metric
              label="Условно"
              value={String(
                statistics.by_level.CONDITIONALLY_APPLICABLE || 0
              )}
            />
            <Metric
              label="Всего в спецификации"
              value={String(statistics.total_models_in_spec)}
            />
          </div>
        )}

        {/* ── Спецификация ── */}
        {specVersion && (
          <p className="text-[11px] text-neutral-400 mt-2">
            Спецификация v{specVersion}
          </p>
        )}
      </section>

      {/* ══ ПРАВАЯ КОЛОНКА: карточки семейств/кандидатов ══ */}
      <aside className="w-80 shrink-0">
        <div className="max-h-[830px] overflow-y-auto pr-2 space-y-5 feed-scroll">
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
                className={`w-full mb-3 rounded px-3 py-2 text-sm text-left font-medium transition-colors ${
                  descriptionSection === "pipeline"
                    ? "bg-brand text-white"
                    : "bg-brand-light hover:bg-brand-light/80 text-neutral-800"
                }`}
              >
                Полный пайплайн
              </button>

              <Button>Запустить бэктест</Button>
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
                Убедитесь, что API-сервер запущен (
                <code className="text-xs bg-neutral-100 px-1 rounded">
                          NEXT_PUBLIC_API_URL
                </code>
                ) и повторите попытку кнопкой «Загрузить пул».
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
