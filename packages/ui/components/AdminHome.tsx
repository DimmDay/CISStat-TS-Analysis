"use client";

// packages/ui/components/AdminHome.tsx
//
// AUTH-07 «Общая админка обеих оболочек» (spec_auth_architecture.md,
// строка 196): лендинг /admin -- один общий компонент для standalone и
// embedded (spec §3: «Общие UI компоненты: progress, users/sessions,
// campaigns, logs/support, policies»; в скоупе AUTH-07 -- progress и
// logs, остальные -- последующие AUTH-задачи AUTH-08/15+).
//
// Рендерится ТОЛЬКО под AdminGate (страницы оборачивают), поэтому
// здесь -- только навигация по разделам, никаких проверок доступа
// (UI не заменяет backend enforcement; admission -- UI-навигация).

const SECTIONS: ReadonlyArray<{
  href: string;
  title: string;
  description: string;
}> = [
  {
    href: "/admin/progress",
    title: "Прогресс запусков",
    description:
      "Агрегаты микросервиса «Прогресс» по корпусу (§10 spec_progress): статусы, время по стадиям, проблемные узлы, частоты правил, банк кейсов (§9).",
  },
  {
    href: "/admin/logs",
    title: "Журналы и поддержка",
    description:
      "DOCLOG-7 §14.2: технические события, аудит доступа, доставка и документы; support-гранты и диагностический пакет «без данных».",
  },
];

export function AdminHome() {
  return (
    <section className="mx-auto max-w-3xl space-y-4 p-6" aria-label="Панель администрирования">
      <header>
        <h2 className="text-lg font-bold text-neutral-900">Администрирование</h2>
        <p className="mt-1 text-xs text-neutral-500">
          Платформенные разделы (AUTH-07). Доступ -- личный вход
          администратора: named-сессия с подтверждением MFA; роль
          проверяется сервером на каждом запросе.
        </p>
      </header>
      <ul className="grid gap-3 md:grid-cols-2">
        {SECTIONS.map((section) => (
          <li key={section.href}>
            <a
              href={section.href}
              className="block h-full rounded-lg border border-neutral-200 bg-white p-4 transition-colors hover:border-brand"
            >
              <span className="text-sm font-semibold text-neutral-900">
                {section.title}
              </span>
              <span className="mt-1 block text-xs text-neutral-600">
                {section.description}
              </span>
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}
