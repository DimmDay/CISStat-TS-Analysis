// apps/embedded/app/admin/progress/page.tsx
//
// Admin-панель мониторинга «Прогресса» (Task PROGR-8, spec_progress.md
// §10 + §9). Embedded-портал -- внутренний контур CISStat: страница
// администратора платформы монтируется по прямому пути /admin/progress.
//
// §10 дословно: админ заходит ДРУГИМ ПУТЁМ -- API-ключ с ролью ADMIN,
// не cookie-сессия аналитика. Ключ вводится в самой панели
// (AdminProgressDashboard) и живёт только в стее вкладки; серверной
// авторизации страниц в портале нет -- доступ определяется ключом на
// уровне API (require_admin_role, 403 для не-ADMIN).

import { AdminProgressDashboard } from "@cisstat/ui";

export default function Page() {
  return <AdminProgressDashboard />;
}
