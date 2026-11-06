"use client";

// packages/ui/components/AdminProgressDashboard.tsx
//
// Admin-панель мониторинга «Прогресса» (Task PROGR-8, spec_progress.md
// §10 + §9, §6.3: «AdminProgressDashboard.tsx (только Role.ADMIN)»;
// миграция AUTH-07 -- spec_auth_architecture.md строка 196).
//
// AUTH-07: панель -- часть ОБЩЕЙ админки обеих оболочек; доступ --
// named-сессия администратора (cookie через first-party /api-прокси,
// AUTH-06), гейт страницы -- AdminGate. X-API-Key из браузера больше
// НЕ отправляется: серверная гвард require_admin_role (auth.py)
// принимает named-сессию с ролью ADMIN и верифицированным MFA
// (mfa_verified_at), API-ключ сохранён как программный канал до AUTH-10.
// Панель не вводит и не хранит никаких ключей.
//
// Состав §10 (агрегаты по корпусу, без содержимого датасетов):
//   * запуски по статусам за период + всего;
//   * распределение времени по стадиям («где застревают»);
//   * топ узлов warning/error;
//   * частота правил «Следующий шаг» (§7.1);
//   * частота sanity-предупреждений (§7.2) по правилу и по узлу;
//   * предпочтения Прогнозирования: модели/горизонты/alpha (§9).
// Отдельно -- отбор кандидатов банка кейсов (§9): алгоритмическая
// эвристика; суммаризация трассы в читаемый кейс -- офлайн-джоба вне
// этого сервиса (§9 дословно).
//
// Пустой корпус -- честные нули с пояснением: старт этапа -- по
// накоплении данных, кодом не гейтится (приёмка plan_progress.md).
// 401/403 -- различимые подсказки (сессия истекла / роль не ADMIN).

import { useCallback, useEffect, useState } from "react";
import {
  fetchAdminOverview,
  fetchCaseBankCandidates,
  type AdminOverviewInfo,
  type CaseBankResponseInfo,
} from "../lib/admin";
import { nodeLabel, runStatusLabel, stageLabel } from "../lib/progress";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-neutral-200 bg-white p-4">
      <h3 className="text-sm font-semibold text-neutral-800">{title}</h3>
      <div className="mt-2 text-sm text-neutral-700">{children}</div>
    </section>
  );
}

function FrequencyList({
  items,
}: {
  items: ReadonlyArray<{ label: string; count: number }>;
}) {
  if (items.length === 0) {
    return <p className="text-xs text-neutral-400">Пока нет данных.</p>;
  }
  return (
    <ul className="space-y-1">
      {items.map((item) => (
        <li key={item.label} className="flex items-center justify-between gap-2 text-xs">
          <span className="truncate text-neutral-700">{item.label}</span>
          <span className="font-semibold text-neutral-900">{item.count}</span>
        </li>
      ))}
    </ul>
  );
}

const EMPTY_OVERVIEW: AdminOverviewInfo = {
  generated_at: "",
  period_days: 30,
  runs_total_all_time: 0,
  runs_total_in_period: 0,
  runs_by_status: { active: 0, paused: 0, completed: 0, abandoned: 0 },
  stage_time: [],
  top_problem_nodes: [],
  next_step_frequency: [],
  sanity_by_rule: [],
  sanity_by_node: [],
  forecasting_model_frequency: [],
  forecasting_horizon_frequency: [],
  forecasting_alpha_frequency: [],
};

export function AdminProgressDashboard() {
  const [loading, setLoading] = useState(false);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  const [overview, setOverview] = useState<AdminOverviewInfo | null>(null);
  const [caseBank, setCaseBank] = useState<CaseBankResponseInfo | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErrorStatus(null);
    const overviewResult = await fetchAdminOverview();
    const caseBankResult = await fetchCaseBankCandidates();
    if (overviewResult.ok && overviewResult.data) {
      setOverview(overviewResult.data);
      setCaseBank(caseBankResult.ok && caseBankResult.data ? caseBankResult.data : null);
    } else {
      setErrorStatus(overviewResult.status);
      setOverview(null);
      setCaseBank(null);
    }
    setLoading(false);
  }, []);

  // Named-сессия администратора (AUTH-07): данные загружаются сразу
  // при монтировании; гейт доступа -- AdminGate на странице.
  useEffect(() => {
    void load();
  }, [load]);

  const isEmptyCorpus =
    overview !== null && overview.runs_total_all_time === 0;

  return (
    <main
      aria-label="Admin-панель мониторинга Прогресса"
      className="mx-auto max-w-4xl space-y-4 p-6"
    >
      <header>
        <h2 className="text-lg font-bold text-neutral-900">
          Admin-панель мониторинга
        </h2>
        <p className="mt-1 text-xs text-neutral-500">
          Агрегаты микросервиса «Прогресс» по корпусу запусков (§10) и
          отбор кандидатов банка кейсов (§9). Доступ -- личный вход
          администратора (named-сессия с MFA, AUTH-07); никакие ключи
          в браузере не вводятся и не хранятся.
        </p>
      </header>

      {overview !== null && (
        <div className="flex justify-end">
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="text-xs text-neutral-500 hover:text-neutral-900 disabled:text-neutral-300"
          >
            Обновить
          </button>
        </div>
      )}

      {errorStatus !== null && (
        <div role="alert" className="rounded bg-red-50 p-3 text-sm text-red-700">
          {errorStatus === 401 &&
            "Сессия не действительна или истекла. Войдите как администратор заново."}
          {errorStatus === 403 &&
            "Доступ закрыт: панель требует роли «администратор платформы» (named-сессия с MFA)."}
          {errorStatus !== 401 &&
            errorStatus !== 403 &&
            "Сервис недоступен; попробуйте обновить позже."}
        </div>
      )}

      {loading && (
        <p role="status" className="text-sm text-neutral-500">
          Загрузка агрегатов…
        </p>
      )}

      {isEmptyCorpus && (
        <p className="rounded bg-blue-50 p-3 text-sm text-blue-800">
          Корпус пуст: агрегаты наполнятся по мере работы платформы
          (этап стартует по накоплении данных, кодом не гейтится).
        </p>
      )}

      {overview !== null && !isEmptyCorpus && (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            <Section title="Запуски за период">
              <p className="text-xs text-neutral-500">
                Период: {overview.period_days} дн.
              </p>
              <ul className="mt-2 space-y-1">
                {Object.entries(overview.runs_by_status).map(([status, count]) => (
                  <li key={status} className="flex items-center justify-between text-xs">
                    <span>{runStatusLabel(status)}</span>
                    <span className="font-semibold">{count}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-neutral-500">
                За период: {overview.runs_total_in_period} из{" "}
                {overview.runs_total_all_time} всего
              </p>
            </Section>

            <Section title="Время по стадиям (где застревают)">
              {overview.stage_time.length === 0 ? (
                <p className="text-xs text-neutral-400">Пока нет данных.</p>
              ) : (
                <ul className="space-y-1">
                  {overview.stage_time.map((item) => (
                    <li key={item.stage} className="flex items-center justify-between text-xs">
                      <span>{stageLabel(item.stage)}</span>
                      <span>
                        ~{item.mean_minutes.toFixed(1)} мин
                        <span className="ml-1 text-neutral-400">
                          (медиана {item.median_minutes.toFixed(1)}, запусков:{" "}
                          {item.runs_with_stage})
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Section>

            <Section title="Топ узлов с замечаниями (warning/error)">
              <FrequencyList
                items={overview.top_problem_nodes.map((item) => ({
                  label: `${stageLabel(item.stage)} · ${nodeLabel(item.stage, item.node_id)} (${item.status})`,
                  count: item.count,
                }))}
              />
            </Section>

            <Section title="Частота правил «Следующий шаг» (§7.1)">
              <FrequencyList
                items={overview.next_step_frequency.map((item) => ({
                  label: item.rule_id,
                  count: item.count,
                }))}
              />
            </Section>

            <Section title="Sanity-предупреждения по правилу (§7.2)">
              <FrequencyList
                items={overview.sanity_by_rule.map((item) => ({
                  label: item.rule_id,
                  count: item.count,
                }))}
              />
            </Section>

            <Section title="Sanity-предупреждения по узлу (§7.2)">
              <FrequencyList
                items={overview.sanity_by_node.map((item) => ({
                  label: `${stageLabel(item.stage)} · ${nodeLabel(item.stage, item.node_id)}`,
                  count: item.count,
                }))}
              />
            </Section>

            <Section title="Прогнозирование: модели (§9)">
              <FrequencyList
                items={overview.forecasting_model_frequency.map((item) => ({
                  label: item.value,
                  count: item.count,
                }))}
              />
            </Section>

            <Section title="Прогнозирование: горизонты и alpha (§9)">
              <FrequencyList
                items={[
                  ...overview.forecasting_horizon_frequency.map((item) => ({
                    label: `горизонт ${item.value}`,
                    count: item.count,
                  })),
                  ...overview.forecasting_alpha_frequency.map((item) => ({
                    label: `alpha ${item.value}`,
                    count: item.count,
                  })),
                ]}
              />
            </Section>
          </div>

          {caseBank !== null && (
            <Section title="Банк кейсов: кандидаты (§9)">
              <p className="text-xs text-neutral-500">
                Рассмотрено завершённых запусков: {caseBank.total_completed}.
                Суммаризация трассы в читаемый кейс -- офлайн-джоба вне сервиса.
              </p>
              {caseBank.candidates.length === 0 ? (
                <p className="mt-2 text-xs text-neutral-400">
                  Кандидатов по текущим порогам не найдено.
                </p>
              ) : (
                <ul className="mt-2 space-y-2">
                  {caseBank.candidates.map((candidate) => (
                    <li
                      key={candidate.run_id}
                      className="rounded border border-neutral-100 bg-neutral-50 p-2 text-xs"
                    >
                      <span className="font-semibold">{candidate.run_id}</span>
                      <span className="ml-2 text-neutral-600">
                        {candidate.dataset_name}
                      </span>
                      <span className="ml-2 text-neutral-500">
                        бэктест MAPE {candidate.backtest_mape} · замечаний:{" "}
                        {candidate.warning_nodes} · sanity: {candidate.sanity_warnings}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Section>
          )}
        </>
      )}
    </main>
  );
}
