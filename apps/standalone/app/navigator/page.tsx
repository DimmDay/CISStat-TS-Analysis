// apps/standalone/app/navigator/page.tsx
//
// Страница «Знакомство с платформой». Общая композиция живёт в @cisstat/ui,
// чтобы standalone и embedded использовали одинаковые секции и якоря.

import { PlatformIntroduction } from "@cisstat/ui";

export default function NavigatorPage() {
  return <PlatformIntroduction />;
}
