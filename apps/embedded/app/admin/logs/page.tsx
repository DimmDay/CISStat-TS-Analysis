// apps/embedded/app/admin/logs/page.tsx
//
// Панель журналов/аудита/поддержки embedded-портала (задача DOCLOG-7,
// spec_auth_architecture.md §14.2: «рядом, не вместо» /admin/progress).
// Embedded-портал -- внутренний контур CISStat: страница администратора
// монтируется по прямому пути /admin/logs.
//
// Миграция AUTH-07 (spec_auth_architecture.md строка 196): исторический
// путь «API-ключ вводится в панели» заменён named-сессией администратора
// (cookie через first-party /api-прокси, AUTH-06). Доступ -- общий
// AdminGate: не вошёл → /login?return_to=/admin/logs (пароль+MFA);
// роль не admin (analyst/OWNER) → различимый отказ. Решающая проверка
// роли/MFA/scopes/support-grants -- сервер на каждом запросе
// (auth.py require_admin_role, routers/logs.py).

import { AdminGate } from "@cisstat/ui/components/AdminGate";
import { AdminLogsDashboard } from "@cisstat/ui";

export const dynamic = "force-dynamic";
export const metadata = {
  title: "Администрирование → Журналы и поддержка — CISStat DataTime Lab (Embedded)",
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
