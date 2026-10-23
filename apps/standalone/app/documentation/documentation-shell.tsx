// apps/standalone/app/documentation/documentation-shell.tsx
//
// Точечные UI-правки DOCLOG-4: статическая оболочка страницы «Документы
// исследования». Вынесена из page.tsx в отдельный файл — Next.js разрешает
// page-модулю только default export («DocumentationPageShell is not a valid
// Page export field» на next build), а оболочке нужна именованная экспорт-
// видимость для контракт-тестов page.test.tsx.
//
// Состав правок:
//   1. Заголовок «Документы исследования» — брендовый индиго (text-brand;
//      в тёмной теме utility-ревизия .dark .text-brand → brand-bright
//      применяется автоматически — globals.css §3, инвариант DKT-2R).
//   2. Фон страницы = фон «О платформе» в УСЕЧЁННОМ по высоте варианте
//      (верхняя половина композиции отрезана — DocumentationWavesBackground),
//      подключён по паттерну главной страницы: обёртка relative isolate
//      -mt-6 pt-6, фон — первым ребёнком, позади контента. -mt-6 сдвигает
//      обёртку (и абсолютный фон) вверх на padding-top <main>, вплотную к
//      меню; компенсирующий pt-6 возвращает содержимое на прежнюю позицию
//      (один и тот же токен шкалы — компенсация точная, прецедент page.tsx).
//   3. Отступы ТЕКСТА и БЕЙДЖЕЙ от краёв страницы — по паттерну главной
//      страницы (HomeHero/HomeCapabilities/NavigatorHero): собственные
//      поля 24px (px-6) у обёртки КОНТЕНТА от границ фоновой коробки.
//      Фоновая коробка (root) собственной горизонтальной подложки НЕ
//      несёт (её границы = content-box <main>, сам фон ужался бы вместе
//      с боксом); итог от границ страницы: текст/бейджи — 48px
//      (24px <main class="px-6"> + 24px px-6 контента), фон — 24px —
//      байт-равно главной странице. Прежняя правка «без своей подложки,
//      24px обеспечивает main» давала контенту 24px вместо 48px и
//      НЕ соответствовала эталону «О платформе» — исправлено.
//
// Серверный компонент без «use client» — только разметка, без состояния;
// клиентский workspace подключается в page.tsx под Suspense.

import type { ReactNode } from "react";
import { DocumentationWavesBackground } from "@cisstat/ui";

export function DocumentationPageShell({ children }: { children: ReactNode }) {
  return (
    <div className="relative isolate -mt-6 pt-6 mx-auto w-full max-w-[1600px]">
      <DocumentationWavesBackground />
      <div className="relative px-6">
        <header className="mb-4">
          <h1 className="text-xl font-semibold text-brand">
            Документы исследования
          </h1>
          <p className="mt-1 max-w-3xl text-sm text-neutral-600 dark:text-neutral-400">
            Замороженные снимки исследования (D01–D09): планы, паспорта,
            протоколы, записки EDA, карточки моделей и выпуски прогноза.
            Просмотр и скачивание не меняют состояние исследования; сборка
            формата выполняется поверх зафиксированной версии.
          </p>
        </header>
        {children}
      </div>
    </div>
  );
}
