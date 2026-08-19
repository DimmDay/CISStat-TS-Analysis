// apps/embedded/app/page.tsx
//
// Главная страница embedded — исследовательская карта.
// Та же HomeHero, что в standalone: единая идентичность.
// Navigator переезжает на /navigator.

import { HomeHero } from "@cisstat/ui";

export default function Page() {
  return <HomeHero />;
}
