"use client";

// packages/ui/components/TasksCauses.tsx
//
// Вертикальный срез задачи «Причины» (XAI) — v2 первого среза задач
// (spec_tasks_ia_addendum_v1_1.md §10, §10.1). Паттерн C —
// информационный/навигационный 3-колоночный (§11.2): колонка методов →
// колонка факторов → деталь выбранного фактора; по образцу
// AppliedTasksNavigator. Браузинг уже вычисленного, не пайплайн:
// StatusIcon/степпер отсутствуют сознательно (§11.2 — только там, где
// есть реальная стадийность).
//
// Строительные блоки §11.2 (обязательные во всех паттернах):
//  - бейджи «Когда использовать»/«Что нужно для запуска» —
//    методологический контекст задачи на её собственной странице
//    (классы StaticHalfBadge NavigatorHero);
//  - «Панель управления» — заголовок правой колонки;
//  - контракт высоты рабочего окна 468px + ExpandableChartPanel/
//    ExpandableChartsProvider для графика (прецедент
//    EdaCorrelationOverview).
//
// Честная маркировка (§9.1): данные — ТОЛЬКО реально вычисленные
// сессией факты с бэкенда (GET /v1/session/tasks/causes); методы без
// артефакта — not_computed с видимой причиной; без Model Card —
// честное пустое состояние с CTA на этап-владелец (прецедент R5 хаба),
// поход в сеть не выполняется. Fetch — в useEffect с alive-флагом
// (прецедент TaskArtifactRibbon, без гидратационных расхождений).
//
// Цвета Recharts — токеные: обёртка text-brand + fill="currentColor"
// (новых hex-литералов не создаём — урок DKT-3; var()-токены живут в
// обеих темах, DKT-2).

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Check, SearchCheck } from "lucide-react";
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useAppShell } from "../context/AppShellContext";
import {
  fetchCauses,
  type CausesFactor,
  type CausesMethod,
  type TasksCausesResponse,
} from "../lib/tasks";
import { ExpandableChartPanel } from "./ExpandableChartPanel";
import { ExpandableChartsProvider } from "./ExpandableChartsProvider";

// ── Методологический контекст задачи (§11.2: бейджи по образцу
//    NavigatorHero «Для кого»/«Для чего»; классы StaticHalfBadge) ──
const BADGE_WHEN_TO_USE =
  "После Моделирования, когда нужно понять, какие факторы и связи стоят за прогнозом: атрибуция вклада факторов и причинные связи между рядами.";
const BADGE_WHAT_IS_NEEDED =
  "Model Card из Моделирования. Прогноз не требуется: объяснения считаются обученной моделью на исторических данных сессии.";

function MethodologyBadges() {
  return (
    <div
      className="grid grid-cols-1 gap-3 px-6 md:grid-cols-2"
      data-testid="causes-badges"
    >
      <div
        data-testid="badge-when-to-use"
        className="rounded-lg border border-brand/20 bg-brand-light/40 px-4 py-3.5"
      >
        <div className="flex items-center gap-2">
          <Check size={16} className="shrink-0 text-green-700" aria-hidden="true" />
          <span className="text-xs font-semibold uppercase tracking-wide text-neutral-600">
            Когда использовать
          </span>
        </div>
        <p className="mt-2 text-sm leading-relaxed text-neutral-700">
          {BADGE_WHEN_TO_USE}
        </p>
      </div>
      <div
        data-testid="badge-what-is-needed"
        className="rounded-lg border border-brand/20 bg-brand-light/40 px-4 py-3.5"
      >
        <div className="flex items-center gap-2">
          <Check size={16} className="shrink-0 text-green-700" aria-hidden="true" />
          <span className="text-xs font-semibold uppercase tracking-wide text-neutral-600">
            Что нужно для запуска
          </span>
        </div>
        <p className="mt-2 text-sm leading-relaxed text-neutral-700">
          {BADGE_WHAT_IS_NEEDED}
        </p>
      </div>
    </div>
  );
}

// ── Кнопка-радио колонки-списка (паттерн AppliedTasksNavigator) ──
function RadioRowLabel({
  active,
  title,
  subtitle,
}: {
  active: boolean;
  title: string;
  subtitle?: string | null;
}) {
  return (
    <span className="min-w-0">
      <span
        className={`block text-xs font-semibold leading-tight ${
          active ? "text-brand" : "text-neutral-700"
        }`}
      >
        {title}
      </span>
      {subtitle ? (
        <span className="mt-1 block text-[10px] leading-tight text-neutral-400">
          {subtitle}
        </span>
      ) : null}
    </span>
  );
}

function RadioDot({ active }: { active: boolean }) {
  return (
    <span
      className={`mt-0.5 h-3.5 w-3.5 shrink-0 rounded-full border-2 ${
        active ? "border-brand bg-brand" : "border-neutral-400 bg-white"
      }`}
      aria-hidden="true"
    />
  );
}

const pct = (share: number) => `${(share * 100).toFixed(1)}%`;

export function TasksCauses() {
  const { stages, sessionLoading } = useAppShell();
  const safeStages = stages ?? {};
  const modelingDone = safeStages.modeling === "done";

  const [data, setData] = useState<TasksCausesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!modelingDone || sessionLoading) return;
    let alive = true;
    setLoading(true);
    fetchCauses()
      .then((resp) => {
        if (!alive) return;
        setData(resp);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!alive) return;
        setError(err instanceof Error ? err.message : "Не удалось загрузить данные");
        setData(null);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [modelingDone, sessionLoading]);

  const methods = data?.methods ?? [];
  const firstAvailable = useMemo(
    () => methods.find((m) => m.status === "available") ?? methods[0],
    [methods],
  );
  const [selectedMethodId, setSelectedMethodId] = useState<string | null>(null);
  const [selectedFeature, setSelectedFeature] = useState<string | null>(null);

  const selectedMethod: CausesMethod | undefined =
    methods.find((m) => m.method_id === selectedMethodId) ?? firstAvailable;
  const factors = selectedMethod?.factors ?? [];
  const selectedFactor: CausesFactor | undefined =
    factors.find((f) => f.feature_name === selectedFeature) ?? factors[0];

  const chartData = useMemo(
    () =>
      factors.slice(0, 12).map((factor) => ({
        name: factor.feature_name,
        share: factor.mean_share,
      })),
    [factors],
  );

  const selectMethod = (method: CausesMethod) => {
    if (method.status !== "available") return;
    setSelectedMethodId(method.method_id);
    setSelectedFeature(null);
  };

  return (
    <div className="space-y-10">
      {/* ── Заголовок + поддерживающий текст ── */}
      <div className="text-center">
        <h1 className="font-sans text-2xl font-semibold tracking-tight text-[#1e3a8a]">
          Причины
        </h1>
        <p className="mt-3 text-lg text-[#1e3a8a]">
          драйверы и атрибуция • вклад факторов • причинные связи
        </p>
      </div>

      <MethodologyBadges />

      {/* ── Состояния без данных: честные, без фиктивного заполнения ── */}
      {sessionLoading ? (
        <div className="px-6" data-testid="causes-loading">
          <div
            role="status"
            className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light text-sm text-neutral-500"
          >
            Загружаем состояние сессии…
          </div>
        </div>
      ) : !modelingDone ? (
        <div className="px-6" data-testid="causes-empty">
          <div
            role="group"
            aria-label="Задача «Причины» пока недоступна"
            className="flex h-[468px] flex-col items-center justify-center rounded-lg bg-neutral-50 px-8 text-center"
          >
            <SearchCheck size={24} className="text-neutral-400" aria-hidden="true" />
            <p className="mt-3 text-sm text-neutral-600">
              Задача «Причины» работает поверх Model Card — артефакта этапа
              Моделирование. Сначала обучите модель и создайте Model Card.
            </p>
            <Link
              href="/modeling"
              className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-brand px-3.5 py-2 text-sm font-medium text-white hover:bg-brand/90 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/50"
            >
              Перейти к Моделированию
            </Link>
          </div>
        </div>
      ) : error ? (
        <div className="px-6">
          <div
            role="alert"
            className="flex h-[468px] items-center justify-center rounded-lg bg-red-50 px-8 text-center text-sm text-red-700"
          >
            {error}
          </div>
        </div>
      ) : loading || !data ? (
        <div className="px-6">
          <div
            role="status"
            className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light text-sm text-neutral-500"
          >
            Загружаем объяснения модели…
          </div>
        </div>
      ) : (
        <ExpandableChartsProvider>
          {/* ── Паттерн C: методы → факторы → деталь (§11.2, образец
              AppliedTasksNavigator: поля px-6, gap, shrink-0 колонки,
              flex-1 min-w-0 поглощает дельту) ── */}
          <div className="flex flex-col gap-6 px-6 xl:flex-row xl:gap-[49px]">
            {/* Колонка 1: методы */}
            <aside className="w-full shrink-0 xl:w-60" data-testid="causes-methods">
              <div className="mb-4 flex items-center gap-2">
                <SearchCheck size={16} className="text-brand" aria-hidden="true" />
                <h2 className="text-base font-semibold text-neutral-800">Методы</h2>
              </div>
              <div className="relative">
                <span
                  className="absolute bottom-4 left-[13px] top-4 border-l-2 border-dashed border-neutral-200"
                  aria-hidden="true"
                />
                <ol className="flex flex-col gap-1" aria-label="Методы объяснения">
                  {methods.map((method) => {
                    const isActive = selectedMethod?.method_id === method.method_id;
                    const available = method.status === "available";
                    return (
                      <li key={method.method_id}>
                        <button
                          type="button"
                          onClick={() => selectMethod(method)}
                          disabled={!available}
                          aria-pressed={available ? isActive : undefined}
                          aria-disabled={!available}
                          className={`relative w-full rounded-lg px-2 py-2.5 text-left transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/50 ${
                            isActive && available
                              ? "bg-brand-light"
                              : available
                                ? "hover:bg-neutral-50"
                                : "cursor-not-allowed opacity-60"
                          }`}
                        >
                          <span className="flex items-start gap-2.5">
                            <RadioDot active={isActive && available} />
                            <RadioRowLabel
                              active={isActive && available}
                              title={method.title}
                              subtitle={
                                available ? null : `Не вычислено: ${method.reason ?? ""}`
                              }
                            />
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ol>
              </div>
            </aside>

            {/* Колонка 2: факторы выбранного метода */}
            <aside className="w-full shrink-0 xl:w-80" data-testid="causes-factors">
              <div className="mb-4 flex items-center gap-2">
                <h2 className="text-base font-semibold text-neutral-800">Факторы</h2>
              </div>
              {selectedMethod && selectedMethod.status === "not_computed" ? (
                <div
                  role="status"
                  className="rounded-lg border border-neutral-200 bg-neutral-50 px-4 py-4 text-sm text-neutral-600"
                >
                  Для этого метода в сессии нет вычисленных данных.
                  <p className="mt-2 text-xs leading-relaxed text-neutral-500">
                    {selectedMethod.reason}
                  </p>
                </div>
              ) : (
                <>
                  <div className="space-y-2" role="group" aria-label="Факторы">
                    {factors.map((factor) => {
                      const isActive =
                        selectedFactor?.feature_name === factor.feature_name;
                      return (
                        <button
                          key={factor.feature_name}
                          type="button"
                          onClick={() => setSelectedFeature(factor.feature_name)}
                          aria-pressed={isActive}
                          className={`w-full rounded-lg border p-3 text-left transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/50 ${
                            isActive
                              ? "border-brand bg-brand-light"
                              : "border-neutral-200 bg-white hover:bg-neutral-50"
                          }`}
                        >
                          <span className="flex items-center justify-between gap-2">
                            <span className="block truncate text-sm font-semibold leading-snug text-neutral-800">
                              {factor.feature_name}
                            </span>
                            <span className="shrink-0 text-xs font-medium text-brand">
                              {pct(factor.mean_share)}
                            </span>
                          </span>
                        </button>
                      );
                    })}
                  </div>
                  {selectedMethod?.provenance ? (
                    <p
                      className="mt-3 text-[10px] leading-relaxed text-neutral-400"
                      data-testid="causes-provenance"
                    >
                      Источник: бэктест карты {data.card.model_name ?? data.card.model_id} ·
                      запуск {selectedMethod.provenance.backtest_run_id ?? "—"} ·
                      план {selectedMethod.provenance.plan_id ?? "—"} ·{" "}
                      {selectedMethod.provenance.n_folds} fold(ов)
                    </p>
                  ) : null}
                </>
              )}
            </aside>

            {/* Колонка 3: «Панель управления» — деталь фактора (§11.2) */}
            <section className="min-w-0 flex-1" data-testid="causes-detail">
              <div className="mb-1 flex items-center gap-2">
                <h2 className="font-semibold text-neutral-900">Панель управления</h2>
              </div>
              <p className="mb-3 text-xs text-neutral-500">
                {selectedFactor
                  ? `Деталь фактора: ${selectedFactor.feature_name} · средняя доля ${pct(
                      selectedFactor.mean_share,
                    )} по ${selectedFactor.n_folds} fold(ам)`
                  : "Выберите фактор — здесь появится его деталь."}
              </p>

              {selectedFactor ? (
                <div data-testid="causes-factor-detail">
                  {/* Рабочее окно графика — контракт 468px (§11.2);
                      ExpandableChartPanel требует relative-предка (правка A). */}
                  <div className="relative flex h-[468px] min-h-0 flex-col">
                    <ExpandableChartPanel
                      chartId="causes-factor-detail"
                      title="Средние доли факторов"
                    >
                      <div className="text-brand">
                        <ResponsiveContainer width="100%" height="100%">
                          <BarChart
                            data={chartData}
                            layout="vertical"
                            margin={{ top: 8, right: 24, bottom: 8, left: 8 }}
                          >
                            <XAxis
                              type="number"
                              tickFormatter={(value: number) => pct(value)}
                              tick={{ fontSize: 11 }}
                            />
                            <YAxis
                              type="category"
                              dataKey="name"
                              width={140}
                              tick={{ fontSize: 11 }}
                            />
                            <Tooltip
                              formatter={(value) => pct(Number(value))}
                              labelFormatter={(label) => String(label)}
                            />
                            <Bar dataKey="share" fill="currentColor" fillOpacity={0.35}>
                              {chartData.map((entry) => (
                                <Cell
                                  key={entry.name}
                                  fill="currentColor"
                                  fillOpacity={
                                    selectedFactor.feature_name === entry.name ? 1 : 0.35
                                  }
                                />
                              ))}
                            </Bar>
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    </ExpandableChartPanel>
                  </div>

                  {/* Per-fold деталь выбранного фактора */}
                  <div className="mt-4 overflow-x-auto">
                    <table className="w-full text-left text-xs">
                      <caption className="sr-only">
                        Важность фактора {selectedFactor.feature_name} по fold-ам бэктеста
                      </caption>
                      <thead>
                        <tr className="text-neutral-500">
                          <th scope="col" className="px-2 py-1.5 font-medium">
                            Fold
                          </th>
                          <th scope="col" className="px-2 py-1.5 font-medium">
                            Важность (сырая)
                          </th>
                          <th scope="col" className="px-2 py-1.5 font-medium">
                            Доля в fold
                          </th>
                          <th scope="col" className="px-2 py-1.5 font-medium">
                            Матрица fold
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {selectedFactor.fold_values.map((value) => (
                          <tr key={value.fold} className="border-t border-neutral-200">
                            <td className="px-2 py-1.5 text-neutral-700">
                              fold {value.fold}
                            </td>
                            <td className="px-2 py-1.5 text-neutral-700">
                              {value.importance.toFixed(4)}
                            </td>
                            <td className="px-2 py-1.5 text-neutral-700">
                              {pct(value.share)}
                            </td>
                            <td
                              className="px-2 py-1.5 font-mono text-neutral-400"
                              title={value.matrix_hash ?? undefined}
                            >
                              {value.matrix_hash
                                ? value.matrix_hash.slice(0, 12)
                                : "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : (
                <div
                  role="status"
                  className="flex h-[468px] items-center justify-center rounded-lg bg-neutral-50 px-8 text-center text-sm text-neutral-500"
                >
                  Для выбранного метода нет факторов с вычисленными данными.
                </div>
              )}
            </section>
          </div>
        </ExpandableChartsProvider>
      )}
    </div>
  );
}
