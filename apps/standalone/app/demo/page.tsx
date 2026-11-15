import { DemoLanding } from "@cisstat/ui/components/DemoLanding";

// apps/standalone/app/demo/page.tsx
// AUTH-KABINET-DEMO: /demo — индексная поверхность вкладки «Демо»
// ProductHeader: лендинг с условиями самообслуживаемого демо + вход.
// robots index:true — поверхность стала публично обнаружимой (маркетинг);
// credentials в URL не передаются (AC22), enter — POST, rate-limited;
// no-referrer сохранён. noindex /account, /login, /dashboard не тронуты.
export const dynamic = "force-dynamic";
export const metadata = {
  title: "Демо-режим — CISStat DataTime Lab",
  robots: { index: true, follow: true },
  referrer: "no-referrer",
};
export default function Page() {
  return <DemoLanding />;
}
