"use client";

// apps/standalone/components/StandaloneHome.tsx
//
// Двойная жизнь Home в standalone, по решению тимлида:
//   - неавторизован -> маркетинговая посадочная страница (ценностное
//     предложение, тарифы, ссылка на документацию) -- инструмент не
//     продаст себя сам.
//   - авторизован, нет активного датасета -> "Рабочий стол" (список
//     прошлых анализов, расход API) -- НЕ та же маркетинговая страница,
//     иначе платящий клиент каждый раз видит рекламу самому себе.
//   - авторизован, есть активный датасет -> WorkbenchSummary (общий с
//     embedded компонент, см. packages/ui/components/WorkbenchSummary.tsx).
//
// auth.isAuthenticated -- ЗАГЛУШКА (см. lib/useAuth.ts), реальной
// авторизации ещё нет. "Список прошлых анализов" и "расход API за
// период" ниже -- тоже честно помечены как нереализованный бэкенд
// (нет истории датасетов, только текущая сессия), а не выдуманы.

import Link from "next/link";
import { useAppShell, WorkbenchSummary, PLAN_DEFINITIONS } from "@cisstat/ui";
import { Loader2, Check, Minus, ArrowRight } from "lucide-react";
import { useAuth } from "../lib/useAuth";
import { ProductJourneyGuide } from "./ProductJourneyGuide";

function DevAuthToggle() {
  const { isAuthenticated, setDevAuthOverride } = useAuth();
  // TODO: убрать этот блок или спрятать за флагом окружения, когда
  // появится реальная авторизация (см. lib/useAuth.ts).
  return (
    <div className="mt-10 border-t border-dashed border-neutral-300 pt-4 text-xs text-neutral-400">
      <span className="mr-2">Режим разработки (заглушка авторизации):</span>
      <button
        type="button"
        onClick={() => setDevAuthOverride(!isAuthenticated)}
        className="underline hover:text-neutral-600"
      >
        {isAuthenticated ? "Выйти (смотреть как гость)" : "Войти (смотреть как клиент)"}
      </button>
    </div>
  );
}

function MarketingHome() {
  return (
    <div className="space-y-10">
      {/* ── Hero ── */}
      <div>
        <h1 className="text-3xl font-semibold mb-3 text-neutral-900">
          Анализ временных рядов — от файла до прогноза
        </h1>
        <p className="text-neutral-600 mb-5 max-w-2xl text-base">
          Загрузите датасет — платформа сама определит структуру, проверит качество, подготовит
          ряд и построит прогноз с доверительными интервалами. Тот же анализ доступен как REST API
          для интеграции в вашу ИТ-систему.
        </p>
        <div className="flex flex-wrap gap-3">
          <Link
            href="/upload"
            className="inline-flex items-center gap-2 bg-brand text-white rounded px-5 py-2.5 text-sm font-medium hover:bg-brand/90 transition-colors"
          >
            Загрузить датасет и начать <ArrowRight size={16} aria-hidden="true" />
          </Link>
          <Link
            href="/docs"
            className="inline-flex items-center gap-2 border border-neutral-300 rounded px-5 py-2.5 text-sm hover:bg-neutral-50 transition-colors"
          >
            Документация API
          </Link>
        </div>
      </div>

      {/* ── Путеводитель: продающая витрина + быстрая ориентация по всем 6 этапам ── */}
      <div>
        <h2 className="font-semibold text-neutral-900 mb-1">Как устроен анализ</h2>
        <p className="text-sm text-neutral-500 mb-3">
          Шесть этапов пайплайна — наведите или нажмите на этап, чтобы увидеть, что он умеет.
        </p>
        <ProductJourneyGuide />
      </div>

      <div>
        <h2 className="font-semibold text-neutral-900 mb-3">Тарифы</h2>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {(Object.keys(PLAN_DEFINITIONS) as Array<keyof typeof PLAN_DEFINITIONS>).map((planName) => {
            const plan = PLAN_DEFINITIONS[planName];
            return (
              <div key={planName} className="border border-neutral-200 rounded-lg p-4 bg-white">
                <h3 className="font-medium text-neutral-900 capitalize mb-1">{planName}</h3>
                {/* Цены -- уточнить у коммерческой команды, не выдумывать числа */}
                <p className="text-xs text-neutral-400 mb-3">цена уточняется</p>
                <ul className="text-xs text-neutral-600 space-y-1">
                  <li className="flex items-center gap-1.5">
                    {plan.canUseApi ? (
                      <Check size={12} className="text-green-600" aria-hidden="true" />
                    ) : (
                      <Minus size={12} className="text-neutral-300" aria-hidden="true" />
                    )}
                    Доступ к API
                  </li>
                  <li className="flex items-center gap-1.5">
                    {plan.canTrainModels ? (
                      <Check size={12} className="text-green-600" aria-hidden="true" />
                    ) : (
                      <Minus size={12} className="text-neutral-300" aria-hidden="true" />
                    )}
                    Обучение моделей
                  </li>
                  <li className="text-neutral-500">
                    {plan.maxDatasetRows ? `до ${plan.maxDatasetRows.toLocaleString("ru-RU")} строк` : "без лимита строк"}
                  </li>
                </ul>
              </div>
            );
          })}
        </div>
      </div>

      <DevAuthToggle />
    </div>
  );
}

function AuthenticatedWorkbenchHome() {
  const { activeDataset, stages, lastActiveStage } = useAppShell();

  if (activeDataset) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-semibold text-neutral-900">CISStat TS Analysis</h1>
        <WorkbenchSummary dataset={activeDataset} stages={stages} lastActiveStage={lastActiveStage} />
        <DevAuthToggle />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-neutral-900">Рабочий стол</h1>

      <div className="bg-white rounded-lg border border-neutral-200 p-5">
        <h2 className="font-medium text-neutral-900 text-sm mb-2">Прошлые анализы</h2>
        {/* TODO: нет бэкенд-эндпоинта истории датасетов (только текущая
            сессия) -- честный пустой стейт вместо выдуманных данных. */}
        <p className="text-sm text-neutral-500">
          История прошлых анализов появится здесь, когда будет реализовано постоянное хранилище
          датасетов (сейчас платформа хранит только текущую сессию).
        </p>
      </div>

      <div className="bg-white rounded-lg border border-neutral-200 p-5">
        <h2 className="font-medium text-neutral-900 text-sm mb-2">Использование API за период</h2>
        {/* TODO: нет бэкенд-учёта вызовов API по клиенту (apps/api/plans.py
            хранит только лимиты, без счётчика использования). */}
        <p className="text-sm text-neutral-500">
          Учёт расхода API пока не реализован — см. apps/api/plans.py, раздел лимитов.
        </p>
      </div>

      <Link
        href="/upload"
        className="inline-block bg-brand text-white rounded px-4 py-2 text-sm font-medium hover:bg-brand/90 transition-colors"
      >
        Загрузить датасет →
      </Link>

      <DevAuthToggle />
    </div>
  );
}

export function StandaloneHome() {
  const { isAuthenticated, ready } = useAuth();
  const { sessionLoading } = useAppShell();

  if (!ready || sessionLoading) {
    return (
      <div className="flex items-center gap-2 text-neutral-500 text-sm py-10">
        <Loader2 size={16} className="animate-spin" aria-hidden="true" /> Загрузка…
      </div>
    );
  }

  return isAuthenticated ? <AuthenticatedWorkbenchHome /> : <MarketingHome />;
}
