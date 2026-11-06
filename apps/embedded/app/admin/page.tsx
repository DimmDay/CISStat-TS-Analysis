// apps/embedded/app/admin/page.tsx
//
// AUTH-07 «Общая админка обеих оболочек» (spec_auth_architecture.md,
// строка 196): лендинг админки embedded-портала (внутренний контур
// CISStat). Поток входа (spec §3): /login?return_to=/admin → личный
// password+MFA → /admin. Доступ -- AdminGate (named ADMIN-сессия;
// analyst/OWNER получают отказ); решающая проверка роли/MFA --
// сервер на каждом API-запросе.

import { AdminGate } from "@cisstat/ui/components/AdminGate";
import { AdminHome } from "@cisstat/ui/components/AdminHome";

export const dynamic = "force-dynamic";
export const metadata = {
  title: "Администрирование — CISStat DataTime Lab (Embedded)",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

export default function Page() {
  return (
    <AdminGate returnTo="/admin">
      <AdminHome />
    </AdminGate>
  );
}
