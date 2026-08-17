// apps/standalone/app/page.tsx
//
// Главная страница standalone — "Навигатор".
// По решению тимлида (вопрос 1, вариант (a)): Навигатор показывается ВСЕГДА
// (и неавторизованному посетителю, и авторизованному без датасета).
// WorkbenchSummary / "Рабочий стол" переносятся на /dashboard — отдельная
// задача, в рамках текущей не делается.
//
// Auth-ветвление из StandaloneHome.tsx сознательно убрано: Навигатор — это
// функциональный инструмент (а не маркетинг), и платящий клиент не должен
// видеть рекламу самому себе, но и не должен терять ориентацию в продукте.
// Кнопка "Начать анализ" в Путеводителе ведёт на /upload — единственный
// сквозной CTA, без зависимости от auth-состояния.
//
// Auth-логика (useAuth) и DevAuthToggle из StandaloneHome.tsx пока не
// используются здесь, но оставлены в apps/standalone/components/ до
// отдельной задачи по переносу WorkbenchSummary на /dashboard.

import { NavigatorHero, TsAnalysisNavigator } from "@cisstat/ui";

export default function Page() {
  return (
    <>
      <NavigatorHero />
      <TsAnalysisNavigator />
    </>
  );
}
