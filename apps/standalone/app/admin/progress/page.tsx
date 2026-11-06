// apps/standalone/app/admin/progress/page.tsx
//
// AUTH-07: Admin-панель мониторинга «Прогресса» в standalone-оболочке
// (до AUTH-07 была только в embedded, инвентаризация spec
// spec_auth_architecture.md §1). Доступ -- AdminGate (named ADMIN-
// сессия с MFA); данные -- /v1/progress/admin/* под той же сессией
// (require_admin_role, auth.py).

import { AdminGate } from "@cisstat/ui/components/AdminGate";
import { AdminProgressDashboard } from "@cisstat/ui";

export const dynamic = "force-dynamic";
export const metadata = {
  title: "Администрирование → Прогресс — CISStat DataTime Lab",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

export default function Page() {
  return (
    <AdminGate returnTo="/admin/progress">
      <AdminProgressDashboard />
    </AdminGate>
  );
}
