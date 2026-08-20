// apps/standalone/app/page.tsx
//
// Главная страница standalone — две секции:
//   1. HomeHero — исследовательская карта (H1 + 6 маршрутов, Task 24)
//   2. HomeCapabilities — информационная секция «Возможности»
//      (Block A: 4 stat + Block B: 3×2 карточек + Block C: manifesto,
//      Task 27). Только в standalone — в embedded маркетинговый контекст
//      не нужен, пользователь уже внутри портала.

import { HomeHero, HomeCapabilities } from "@cisstat/ui";

export default function Page() {
  return (
    <div className="space-y-12">
      <HomeHero />
      <HomeCapabilities />
    </div>
  );
}