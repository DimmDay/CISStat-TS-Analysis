import { DemoLanding } from "@cisstat/ui/components/DemoLanding";

// apps/embedded/app/demo/page.tsx
// AUTH-KABINET-DEMO: синхронно со standalone — /demo рендерит лендинг
// вкладки «Демо» (одинаковые секции, паттерн PlatformIntroduction).
// robots index:true — как в standalone; no-referrer сохранён.
export const dynamic = "force-dynamic";
export const metadata = {
  title: "Демо-режим — CISStat DataTime Lab",
  robots: { index: true, follow: true },
  referrer: "no-referrer",
};
export default function Page() {
  return <DemoLanding />;
}
