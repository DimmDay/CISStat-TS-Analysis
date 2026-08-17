// apps/embedded/app/page.tsx
//
// Главная страница embedded — "Навигатор". Тот же компонент, что и в
// standalone: единая идентичность (одни и те же цвета/шрифты/компоненты),
// разные внешние обвязки (PortalNavBar в layout.tsx, ProductHeader в
// standalone). См. MIGRATION_ARCHITECTURE.md §1.2.
//
// Embedded-режим: пользователь уже внутри портала (сотрудник CISStat),
// доступ регулируется на уровне портала, не здесь. Поэтому auth-логики
// в embedded-Навигаторе нет (см. EmbeddedHome.tsx — там тоже не было).

import { NavigatorHero, TsAnalysisNavigator } from "@cisstat/ui";

export default function Page() {
  return (
    <>
      <NavigatorHero />
      <TsAnalysisNavigator />
    </>
  );
}
