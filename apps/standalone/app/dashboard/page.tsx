import { DashboardPivot } from "@/components/DashboardPivot";

// apps/standalone/app/dashboard/page.tsx
// AUTH-KABINET-DEMO: маршрут /dashboard — цель надписи «Вход» ProductHeader
// (спека spec_auth_kabinet_demo.md, TASK-1). Серверная обёртка пивота:
// сами переходы клиентские (DashboardPivot): authed → /account,
// anonymous → /login?return_to=/account (safeReturnTo уже содержит /account),
// fail-closed при недоступном сервисе авторизации. noindex: служебный
// маршрут, прямой доступ извне login-потока не предусмотрен; credentials
// в URL не передаются (AC22).
export const dynamic = "force-dynamic";
export const metadata = {
  title: "Вход — CISStat DataTime Lab",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};
export default function Page() {
  return <DashboardPivot />;
}
