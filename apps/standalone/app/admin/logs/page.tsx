// apps/standalone/app/admin/logs/page.tsx
//
// AUTH-07 «Общая админка обеих оболочек» (spec_auth_architecture.md,
// строка 196): панель журналов/аудита/поддержки standalone-оболочки
// (до AUTH-07 была только в embedded, подтверждено инвентаризацией
// spec §1). Доступ -- AdminGate (named ADMIN-сессия со свежим MFA;
// analyst/OWNER получают отказ); данные -- /v1/logs/* под той же
// сессией (require_admin_role + support grants, routers/logs.py);
// решающая проверка роли/MFA/scopes -- сервер на каждом запросе.

import { AdminGate } from "@cisstat/ui/components/AdminGate";
import { AdminLogsDashboard } from "@cisstat/ui";

export const dynamic = "force-dynamic";
export const metadata = {
  title: "Администрирование → Журналы и поддержка — CISStat DataTime Lab",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

export default function Page() {
  return (
    <AdminGate returnTo="/admin/logs">
      <AdminLogsDashboard />
    </AdminGate>
  );
}
