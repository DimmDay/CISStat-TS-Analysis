// apps/embedded/app/admin/progress/page.tsx
//
// Admin-панель мониторинга «Прогресса» (Task PROGR-8, spec_progress.md
// §10 + §9). Embedded-портал -- внутренний контур CISStat: страница
// администратора платформы монтируется по прямому пути /admin/progress.
//
// Миграция AUTH-07 (spec_auth_architecture.md строка 196): исторический
// путь «API-ключ вводится в панели» заменён named-сессией администратора
// (cookie через first-party /api-прокси, AUTH-06). Доступ -- общий
// AdminGate: не вошёл → /login?return_to=/admin/progress (пароль+MFA);
// роль не admin (analyst/OWNER) → различимый отказ. Решающая проверка
// роли/MFA -- сервер на каждом запросе (auth.py require_admin_role).

import { AdminGate } from "@cisstat/ui/components/AdminGate";
import { AdminProgressDashboard } from "@cisstat/ui";

export const dynamic = "force-dynamic";
export const metadata = {
  title: "Администрирование → Прогресс — CISStat DataTime Lab (Embedded)",
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
